import hashlib
import json
import time
from types import SimpleNamespace

from memweave_eval.domain_backend import DomainBackend


def test_scoped_backend_keeps_gold_private_and_records_actual_tool_state(tmp_path):
    state={'value':3}
    def update(args):state['value']=args['value'];return {'ok':True}
    exchange=tmp_path/'actor-mounted/channel'
    private=tmp_path/'evaluator-only'
    backend=DomainBackend(SimpleNamespace(tool_handlers={'set':update},
        get_full_snapshot=lambda:dict(state)),private/'backend.jsonl',exchange)
    backend.start()
    def call(identity,name,args,token):
        filename=hashlib.sha256(identity.encode()).hexdigest()+'.json'
        request=exchange/'requests'/filename
        temporary=request.with_suffix('.partial')
        temporary.write_text(json.dumps({'call_id':identity,'name':name,'arguments':args,'token':token}))
        temporary.replace(request)
        response=exchange/'responses'/filename
        until=time.monotonic()+2
        while not response.exists() and time.monotonic()<until:time.sleep(.01)
        return json.loads(response.read_text())
    try:
        assert call('bad','set',{'value':9},'wrong')['bridge_error']=='unauthorized'
        assert state['value']==3
        assert call('unknown','read_gold',{},backend.token)['bridge_error']
        assert call('t','set',{'value':9},backend.token)['result']=={'ok':True}
        record=json.loads((private/'backend.jsonl').read_text())
        assert record['before']['value']==3 and record['after']['value']==9
        assert record['call_id']=='t' and backend.token not in (private/'backend.jsonl').read_text()
        # Actor's mount exposes only actual calls and actual responses, no complete state snapshots.
        assert not any('before' in p.read_text() for p in exchange.rglob('*.json'))
    finally:backend.close()
    assert json.loads((private/'backend.end.json').read_text())['complete']


def test_backend_thread_failure_is_not_claimed_complete(tmp_path):
    env=SimpleNamespace(tool_handlers={},get_full_snapshot=dict)
    backend=DomainBackend(env,tmp_path/'private/log.jsonl',tmp_path/'exchange')
    backend.start()
    (tmp_path/'exchange/requests/wrong.json').write_text('{"call_id":"x"}')
    until=time.monotonic()+2
    while not backend.fatal_error and time.monotonic()<until:time.sleep(.01)
    backend.close()
    end=json.loads((tmp_path/'private/log.end.json').read_text())
    assert end['complete'] is False and end['fatal_error']=='ValueError'
