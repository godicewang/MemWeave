import json

import pytest

from memweave_eval.budget_guard import initialize
from memweave_eval.fixed35_campaign_config import campaign_config, verify_account
from memweave_eval.storage import file_digest


def freeze(tmp_path,**changes):
    config={'schema_version': 1,'budget_id': 'new-independent','ledger': str(tmp_path/'new-independent/quota.json'),
        'started_at': 1000,'model_cutoff': 2000,'judge_cutoff': 3000,'container_cutoff': 4000,'hard_deadline': 5000,
        'maximum_usd': 19.,'authorized_usd': 20.,'arm_limits': {'pi-native':9.,'pi-memweave':9.,'preflight':1.}}
    config.update(changes)
    path=tmp_path/'campaign.json';path.write_text(json.dumps(config))
    return {'campaign':{'path':str(path),'sha256':file_digest(path)}}


def test_independent_budget_and_clocks_are_hash_bound(tmp_path):
    record=freeze(tmp_path);config=campaign_config(record)
    from pathlib import Path
    initialize(Path(config['ledger']),19.,3000,arm_limits=config['arm_limits'])
    assert verify_account(config)['requests']=={}
    Path(record['campaign']['path']).write_text('{}')
    with pytest.raises(ValueError,match='changed'):campaign_config(record)


@pytest.mark.parametrize('changes',[{'maximum_usd':21.},{'authorized_usd':30.},
    {'model_cutoff':float('nan')},{'judge_cutoff':2000},{'container_cutoff':6000},
    {'arm_limits':{'pi-native':8.,'pi-memweave':9.,'preflight':1.}},
    {'ledger':'/old-budget/quota.json'}])
def test_configuration_cannot_reuse_old_budget_or_expand_authorization(tmp_path,changes):
    with pytest.raises(ValueError):campaign_config(freeze(tmp_path,**changes))


def test_ledger_configuration_mismatch_is_fail_closed(tmp_path):
    from pathlib import Path
    config=campaign_config(freeze(tmp_path))
    initialize(Path(config['ledger']),19.,2999,arm_limits=config['arm_limits'])
    with pytest.raises(ValueError,match='mismatch'):verify_account(config)


@pytest.mark.parametrize('mode',['valid','overallocated','changed','understated','invalid'])
def test_old_unknown_risk_is_hash_bound_and_cannot_be_spent_again(tmp_path,mode):
    old=tmp_path/'old-budget'/'quota.json';old.parent.mkdir()
    old.write_text(json.dumps({'requests':{'old-call':{'status':'reserved','charge_usd':.3}}}))
    risk={'ledger':str(old),'sha256':file_digest(old),'reserved_usd':.3}
    changes={'carry_in_risk':[risk]}
    if mode=='overallocated':changes.update(maximum_usd=19.8)
    elif mode=='understated':risk['reserved_usd']=.2
    elif mode=='invalid':risk['reserved_usd']=True
    record=freeze(tmp_path,**changes)
    if mode=='changed':old.write_text('{}')
    if mode=='valid':
        assert campaign_config(record)['carry_in_risk']==[risk]
        assert json.loads(old.read_text())['requests']['old-call']['status']=='reserved'
    else:
        with pytest.raises(ValueError):campaign_config(record)


def test_schedule_uses_admission_campaign_clock_not_old_global(tmp_path):
    from memweave_eval.fixed35_schedule import pair_policy
    task=tmp_path/'task';task.mkdir()
    (task/'task.toml').write_text('[environment]\ncpus=2\nmemory_mb=4096\n[verifier]\ntimeout_sec=100\n')
    policy=pair_policy(dict(freeze(tmp_path),case_id='c',task_path=str(task),
        resources={'cpus':2,'memory_mb':4096},seconds=200))
    assert policy['latest_pair_start_unix']==1680


def test_schedule_reserves_intermediate_verification_before_last_actor(tmp_path):
    from memweave_eval.fixed35_schedule import pair_policy
    task=tmp_path/'task';task.mkdir()
    (task/'task.toml').write_text('[environment]\ncpus=2\nmemory_mb=4096\n[verifier]\ntimeout_sec=100\n[[steps]]\nname="a"\n[[steps]]\nname="b"\n')
    record=dict(freeze(tmp_path),case_id='c',task_path=str(task),
        resources={'cpus':2,'memory_mb':4096},seconds=1200,time_policy='source-per-stage')
    assert pair_policy(record)['latest_pair_start_unix']==580
    assert pair_policy(dict(record,host_scored=True))['latest_pair_start_unix']==680
