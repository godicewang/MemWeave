import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from memweave_eval.domain_backend import DomainBackend


def test_scoped_backend_only_exposes_allowlisted_tools_and_captures_real_state(tmp_path):
    state={'value':3}
    def update(args):state['value']=args['value'];return {'ok':True}
    backend=DomainBackend(SimpleNamespace(tool_handlers={'set':update},
                          get_full_snapshot=lambda:dict(state)),tmp_path/'backend.jsonl')
    port=backend.start();url=f'http://127.0.0.1:{port}/tool'
    def call(payload,token):
        return urlopen(Request(url,data=json.dumps(payload).encode(),headers={
            'Authorization':'Bearer '+token,'Content-Type':'application/json'}),timeout=2)
    try:
        with pytest.raises(HTTPError):call({'name':'set','arguments':{'value':9},'call_id':'x'},'wrong')
        assert state['value']==3
        with pytest.raises(HTTPError):call({'name':'read_gold','arguments':{},'call_id':'x'},backend.token)
        result=call({'name':'set','arguments':{'value':9},'call_id':'t'},backend.token)
        assert json.load(result)=={'ok':True}
        record=json.loads((tmp_path/'backend.jsonl').read_text())
        assert record['before']['value']==3 and record['after']['value']==9 and record['call_id']=='t'
        assert backend.token not in (tmp_path/'backend.jsonl').read_text()
    finally:backend.close()
