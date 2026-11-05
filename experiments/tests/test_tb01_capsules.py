import copy
import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from memweave_eval.tb01_capsules import FILES, GOLD, NOTE, collect_capsules, truth


@pytest.mark.parametrize('key',list(GOLD))
def test_truth_is_typed_proposition_conjunction_not_keyword_overlap(key):
    expected=GOLD[key]
    assert all(v=='pass'for v in truth([{'value':expected,'archived':False}],key).values())
    wrong=expected|{'s':'other'}
    assert truth([{'value':wrong,'archived':False}],key)['values']=='fail'
    assert truth([{'value':expected,'archived':True}],key)['values']=='fail'
    assert truth([{'value':expected,'archived':False},{'value':wrong,'archived':False}],key)['no_conflict']=='fail'
    assert truth(None,key)==dict.fromkeys(['schema','values','no_conflict'],'missing')
    assert all(v=='fail'for v in truth([],key).values())
    assert len(json.dumps(expected,separators=(',',':')))<100


def fixture(tmp_path,variant):
    agent=tmp_path/'agent';agent.mkdir();verifier=tmp_path/'verifier';verifier.mkdir()
    records=[{'op':'update_goal','op_id':'g','time':'2026-11-05T00:00:00Z','goal':'goal','evidence':{}}]
    for n,value in enumerate(GOLD.values(),1):records.append({'op':'append_fact','op_id':f'f{n}','time':'2026-11-05T00:00:01Z','id':f'F{n}','fact':json.dumps(value,separators=(',',':')),'evidence':{'U1':'source requirements'}})
    lines=[(json.dumps(r)+'\n').encode()for r in records]
    journal=tmp_path/'state.json';journal.write_bytes(b''.join(lines))
    with tarfile.open(agent/'memory.tar.gz','w:gz')as archive:archive.add(journal,arcname='memory/project/tasks/task_one/state.json')
    version=1;note=[];files={f:'a'*64 for f in FILES};trace=[];pi=[]
    def boundary(phase,identity=None,tool=None,path=None):
        state={'expected_task_id':'task_one','expected_version_at_prepare':version,'expected_journal_sha256':hashlib.sha256(b''.join(lines[:version])).hexdigest()}if variant=='pi-memweave'else{'expected_task_id':None}
        trace.append({'event':'workspace_checkpoint','phase':phase,'call_id':identity,'tool_name':tool,'tool_path':path,'tool_is_error':False,
          'workspace':{'files':dict(files),'memory_capsules':{'status':'present'if note else'absent','sha256':'f'*64,'values':copy.deepcopy(note)}},'state_boundary':state})
    def start(identity,tool,path=None):
        pi.append({'type':'tool_execution_start','toolCallId':identity,'toolName':tool});boundary('tool_start',identity,tool,path)
    def end(identity,tool,path=None):boundary('tool_end',identity,tool,path)
    def read(identity):
        tool='state_read'if variant=='pi-memweave'else'read';start(identity,tool,NOTE);end(identity,tool,NOTE)
        trace.append({'event':'request_ready','capsule_deliveries':[{'tool_call_id':identity,'values':list(GOLD.values()),'task_id':'task_one','state_version':4}]})
    boundary('agent_start');start('capture','state_append'if variant=='pi-memweave'else'write');version=4;note=list(GOLD.values());end('capture','state_append'if variant=='pi-memweave'else'write')
    read('initial-read');start('edit','bash');files={f:'b'*64 for f in files};end('edit','bash');read('final-read');boundary('agent_end')
    probes={'results':{'tests':[{'name':f'tb01_capsule_actions.py::test_{k}_{n}','status':'passed'}for k in GOLD for n in (1,2)]}}
    (verifier/'derived-ctrf.json').write_text(json.dumps(probes))
    def save():
        (agent/'request-trace.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in trace));(agent/'pi.txt').write_text(''.join(json.dumps(r)+'\n'for r in pi))
    save();return trace,save


@pytest.mark.parametrize('variant',['pi-native','pi-memweave'])
def test_real_product_reducer_and_boundary_chain_pass(tmp_path,variant):
    fixture(tmp_path,variant);r=collect_capsules(tmp_path,variant)
    assert r['complete']and set(r['assertions'].values())=={'pass'}


@pytest.mark.parametrize('mutation',['no_initial','no_final','no_tool_start','no_projection','missing_projection_field','wrong_read_version','late_only','business_fail','missing_note_field'])
@pytest.mark.parametrize('variant',['pi-native','pi-memweave'])
def test_missing_evidence_and_actual_behavior_failure_are_distinct(tmp_path,variant,mutation):
    trace,save=fixture(tmp_path,variant)
    if mutation=='no_initial':trace[:]=[e for e in trace if e.get('phase')!='agent_start']
    if mutation=='no_final':trace[:]=[e for e in trace if e.get('phase')!='agent_end']
    if mutation=='no_tool_start':trace[:]=[e for e in trace if not(e.get('phase')=='tool_start'and e.get('call_id')=='initial-read')]
    if mutation=='no_projection':
        for e in trace:
            if e.get('event')=='request_ready':e['capsule_deliveries']=[]
    if mutation=='missing_projection_field':
        for e in trace:
            if e.get('event')=='request_ready':del e['capsule_deliveries']
    if mutation=='wrong_read_version':
        for e in trace:
            for d in e.get('capsule_deliveries',[]):d['state_version']=1;d['values']=[]if variant=='pi-native'else d['values']
    if mutation=='late_only':
        edit=next(e for e in trace if e.get('phase')=='tool_start'and e.get('call_id')=='edit')
        if variant=='pi-native':edit['workspace']['memory_capsules']['values']=[]
        else:edit['state_boundary']={'expected_task_id':'task_one','expected_version_at_prepare':1,'expected_journal_sha256':hashlib.sha256((json.dumps({'op':'update_goal','op_id':'g','time':'2026-11-05T00:00:00Z','goal':'goal','evidence':{}})+'\n').encode()).hexdigest()}
    if mutation=='business_fail':
        p=tmp_path/'verifier/derived-ctrf.json';x=json.loads(p.read_text());x['results']['tests'][0]['status']='failed';p.write_text(json.dumps(x))
    if mutation=='missing_note_field':
        if variant=='pi-native':del trace[0]['workspace']['memory_capsules']
        else:del trace[0]['state_boundary']['expected_journal_sha256']
    save();result=collect_capsules(tmp_path,variant)
    if mutation in ['no_initial','no_final','no_tool_start','missing_note_field','missing_projection_field']:
        assert not result['complete']and 'pass'not in {v for k,v in result['assertions'].items()if ':use:probe'not in k}
    else:assert result['complete']and 'fail'in result['assertions'].values()


def test_window_exit_is_not_archive_and_product_reducer_retains_truth(tmp_path):
    from memweave_eval.tb01_capsules import _replay_prefixes
    events=[{'op':'update_goal','op_id':'g','time':'t','goal':'goal','evidence':{}},
      {'op':'append_fact','op_id':'f','time':'t','id':'F1','fact':json.dumps(GOLD['row']),'evidence':{'U1':'source'}},
      {'op':'slide_window','op_id':'s','time':'t','batch_id':'b','evicted_range':{'from':2,'to':2},'retained_ids':[],'status':'committed'}]
    lines=[(json.dumps(e)+'\n').encode()for e in events]
    state=_replay_prefixes({'task':lines},{('task',3)})[('task',3)]
    assert state[0]['active']is False and state[0]['archived']is False
    assert truth([{'value':json.loads(state[0]['content']),'archived':False}],'row')['values']=='pass'
    events.append({'op':'modify_fact','op_id':'m','time':'t','archive':['F1'],'append_fact':{'content':json.dumps(GOLD['row']|{'by':'id'}),'evidence':{'F1':'counterexample'}}})
    lines=[(json.dumps(e)+'\n').encode()for e in events]
    state=_replay_prefixes({'task':lines},{('task',4)})[('task',4)]
    rows=[{'value':json.loads(e['content']),'archived':e['archived']}for e in state]
    assert truth(rows,'row')['values']=='fail'


def test_production_report_consumes_capsule_oracle_and_preserves_independent_totals(tmp_path,monkeypatch):
    import memweave_eval.primary_evidence as evidence
    from memweave_eval.primary_report import score_run, write_primary_artifacts
    from memweave_eval.storage import evidence_index, file_digest

    contract=json.loads((Path(__file__).parents[1]/'cases/TB-01/1.4.0/scoring.json').read_text())
    (tmp_path/'primary-case.json').write_text(json.dumps(contract))
    rows=[]
    for variant in ('pi-native','pi-memweave'):
        trial=tmp_path/'harbor'/variant/'trial';trial.mkdir(parents=True);fixture(trial,variant);(trial/'result.json').write_text('{}')
        rows.append({'variant_id':variant,'task_id':'batched-eval-parity','score_source':str((trial/'result.json').relative_to(tmp_path))})
    def collected(*args,**kwargs):
        return {'metrics':{k:{'raw':v,'status':'observed'}for k,v in [('common_tool_rate',1),('service_complete_rate',1),('model_cost_usd',1),('actor_wall_seconds',1)]},'assertions':{},'parse_issues':[],'sources':{}}
    monkeypatch.setattr(evidence,'collect_arm',collected)
    (tmp_path/'evidence-index.json').write_text(json.dumps({'files':evidence_index(tmp_path)}))
    result=score_run(tmp_path,{'run_id':'mock','primary_case_sha256':file_digest(tmp_path/'primary-case.json')},rows)
    assert result['engineering']['total']['score']==50
    assert all(result['behavior'][a]['total']['score']==100 for a in ('pi-native','pi-memweave'))
    assert result['raw_arms']['pi-memweave']['capsule_evidence']['complete']
    out=tmp_path/'reports';out.mkdir();write_primary_artifacts(out,result)
    assert 'tb01.capsule.truth'in(out/'primary-scores.csv').read_text()
    assert 'combined_total'not in result


@pytest.mark.parametrize('variant',['pi-native','pi-memweave'])
@pytest.mark.parametrize('field',['workspace','state_boundary'])
def test_null_boundary_field_is_missing_evidence_never_a_score(tmp_path,variant,field):
    trace,save=fixture(tmp_path,variant);trace[0][field]=None;save()
    result=collect_capsules(tmp_path,variant)
    assert not result['complete']
    assert all(v=='missing'for k,v in result['assertions'].items()if ':use:probe'not in k)


def test_goal_json_does_not_become_a_fact_capsule(tmp_path):
    from memweave_eval.tb01_capsules import _replay_prefixes
    row={'op':'update_goal','op_id':'g','time':'t','goal':json.dumps(GOLD['row']),'evidence':{}}
    result=_replay_prefixes({'t':[(json.dumps(row)+'\n').encode()]},{('t',1)})
    assert result[('t',1)]==[]
    assert all(v=='fail'for v in truth([], 'row').values())
