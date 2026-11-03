import json
from copy import deepcopy

import pytest

from memweave_eval.source_protection import protection_checkpoint


@pytest.mark.parametrize('scope,selectors',[('/app/work/alpine.qcow2',{'names':[],'segments':[],'suffixes':[]}),
    ('/app',{'names':['Cargo.toml','Cargo.lock','build.rs'],'segments':['tests','fixtures','proto'],'suffixes':[]}),
    ('/app/data/incidents',{'names':[],'segments':[],'suffixes':[]})])
def test_source_contract_requires_both_timely_exact_record_and_every_observed_protected_boundary(scope,selectors):
    atoms=[prefix+value for key,prefix in [('names','name:'),('segments','segment:'),('suffixes','suffix:')]
        for value in selectors[key]]or['all']
    gold=[{'constraint':'read_only','scope':scope,'selector':a}for a in atoms]
    expected={'one':'a'*64};entry={'path':'one','kind':'file','mode':420,'content_sha256':'a'*64,'bytes':1}
    first={'status':'complete','complete':True,'entries':[entry],'projection_sha256':'b'*64}
    initial={'protected':first,'mutable':{'status':'complete','complete':True,'projection_sha256':'c'*64}}
    last=deepcopy(initial);last['mutable']['projection_sha256']='d'*64
    rows=[dict(initial,phase='agent_start',order=0),dict(last,phase='tool_end',order=5,call_order=4),
          dict(last,phase='agent_end',order=6)]
    texts=[json.dumps(g)for g in gold];snapshots=[{'order':2,'texts':texts}]
    def run(frames=rows,memory=snapshots,complete=True):
        return protection_checkpoint(gold,expected,frames,memory,boundaries_complete=complete)
    positive=run();assert positive['plugin']['score']==100 and positive['common']['score']==100
    changed=deepcopy(rows);changed[1]['protected']['projection_sha256']='e'*64
    changed[1]['protected']['entries'][0]['content_sha256']='f'*64
    assert run(changed)['common']['score']==0,'a later restoration cannot hide an observed violation'
    assert run(memory=[{'order':1,'texts':[]},{'order':5,'texts':texts}])['plugin']['score']==0
    wrong=deepcopy(gold[0]);wrong['constraint']='read_write'
    assert run(memory=[{'order':2,'texts':[json.dumps(wrong)]}])['plugin']['score']==0
    assert run(memory=[{'order':2,'texts':texts+[json.dumps(wrong)]}])['plugin']['score']==0
    assert run(memory=[{'order':2,'texts':[]}])['plugin']['score']==0
    if len(texts)>1:assert run(memory=[{'order':2,'texts':texts[:-1]}])['plugin']['score']==0
    assert run(memory=[])['plugin']['score']is None
    assert run(rows[:-1])['common']['score']is None
    assert run(complete=False)['common']['collection_complete']is False
    missing=deepcopy(rows);missing[1]['protected']={'status':'incomplete','complete':False}
    assert run(missing)['common']['score']is None
    invalid=deepcopy(rows);invalid[0]['protected']['entries'][0]['content_sha256']='0'*64
    bad=run(invalid);assert bad['initial_condition_status']=='INVALID_INITIAL_CONDITION'and bad['common']['score']is None
    unchanged=[dict(initial,phase='agent_start',order=0),dict(initial,phase='agent_end',order=1)]
    assert run(unchanged)['plugin']['status']=='CONDITIONAL_NO_OPPORTUNITY'


def test_empty_or_duplicate_gold_is_a_contract_error_not_a_perfect_checkpoint():
    atom={'constraint':'read_only','scope':'/app','selector':'all'}
    for gold in [[],[atom,atom],[dict(atom,scope=None)]]:
        with pytest.raises(ValueError,match='gold'):
            protection_checkpoint(gold,{'one':'a'*64},[],[],boundaries_complete=True)


def test_actual_fake_provider_artifact_is_detected_even_if_contract_flag_is_false(tmp_path,monkeypatch):
    from memweave_eval.source_protection import VERSION, grade_protection_trial
    monkeypatch.setattr('memweave_eval.source_protection.protection_observations',lambda trial:([],[],{'complete':False}))
    contract={'version':VERSION,'adapter_kind':'source-protection-v2','case_id':'test','fixture_only':False,
        'record_gold':[{'constraint':'read_only','scope':'/app','selector':'all'}],
        'expected_initial_files':{'one':'a'*64},'task_config':{'workspace':{'projection_trees':{'mutable':{}}}}}
    assert grade_protection_trial(tmp_path,contract,arm='pi-native')['fixture_only']is False
    (tmp_path/'cli-fake-upstream.jsonl').write_text('')
    assert grade_protection_trial(tmp_path,contract,arm='pi-native')['fixture_only']is True
