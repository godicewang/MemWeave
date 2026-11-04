import json
from types import SimpleNamespace

import pytest

from memweave_eval.state_postscore import score_state_trial


def test_host_judge_has_separate_deadline_and_preserves_actor_original(tmp_path):
    trial=tmp_path/'trial';private=tmp_path/'private/trial';private.mkdir(parents=True)
    original=private/'state-trajectory-original.json';original.write_text('{"task_id":"frozen"}')
    options={'state_evaluator_output':str(tmp_path/'private'),'state_source_path':str(tmp_path/'source'),
        'state_selector':'travel/frozen','evaluation_aux_quota_channels':{'official_judge':'channel'},
        'evaluation_host_ledger':'ledger','auth_path':'private-auth','variant':'pi-native',
        'evaluation_case_id':'INT-04','evaluation_run_id':'episode','evaluation_judge_deadline':2000,
        'evaluation_deadline':1000,'evaluation_output_tokens':8192}
    clients=[]
    def client(**kwargs):clients.append(kwargs);return SimpleNamespace()
    def scorer(source,tasks,task_judge,ux_judge,output):
        assert source==original and task_judge=='task'and ux_judge=='ux'
        output.write_text(json.dumps({'task_completion_pass':True}));return {'status':'OK'}
    result=score_state_trial(options,trial,scorer=scorer,judge_factory=lambda c:('task','ux'),client_factory=client)
    assert result['phase']=='host_after_Harbor_actor'
    assert result['host_verifier_timing']['status']=='CAPTURED'and result['host_verifier_timing']['clock']=='monotonic'
    assert result['host_verifier_timing']['wall_seconds']>=0
    assert clients[0]['deadline']==2000 and clients[0]['run_id']=='episode:judge'
    assert clients[0]['episode_budget']==.4 and original.read_text()=='{"task_id":"frozen"}'
    with pytest.raises(ValueError,match='already exists'):
        score_state_trial(options,trial,scorer=scorer,judge_factory=lambda c:('task','ux'),client_factory=client)
    with pytest.raises(ValueError,match='scoped quota'):
        score_state_trial(dict(options,evaluation_aux_quota_channels={}),trial,client_factory=client)


@pytest.mark.parametrize('marker',[{'fixture_only':True},{'metadata':{'fixture_only':True}}])
def test_fake_actor_never_constructs_a_paid_judge_client(tmp_path,marker):
    private=tmp_path/'private/trial';private.mkdir(parents=True)
    (private/'state-trajectory-original.json').write_text(json.dumps({'task_id':'fixture',**marker}))
    def forbidden(**kwargs):raise AssertionError('paid client must not be constructed')
    with pytest.raises(ValueError,match='fixture-only'):
        score_state_trial({'state_evaluator_output':str(tmp_path/'private'),
            'evaluation_aux_quota_channels':{'official_judge':'scoped-mock'}},tmp_path/'trial',client_factory=forbidden)
