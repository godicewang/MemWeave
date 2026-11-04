import json
from pathlib import Path

import pytest

from memweave_eval.budget_guard import change, initialize


def test_primary_stop_is_durable_but_confirmed_inflight_usage_can_settle(tmp_path):
    ledger=tmp_path/'quota.json';initialize(ledger,2,1000,arm_limits={'native':1})
    op={'action':'reserve','id':'r1','max_output':128,'arm':'native'}
    change(ledger,op,now=1);reserved=json.loads(ledger.read_text())['exposure_usd']
    (tmp_path/'STOP_REQUESTED').write_text('explicit stop')
    with pytest.raises(ValueError,match='stop'):change(ledger,op|{'id':'r2'},now=2)
    assert json.loads(ledger.read_text())['exposure_usd']==reserved
    change(ledger,{'action':'settle','id':'r1','input':100,'output':20,'cache_input':0},now=3)
    assert json.loads(ledger.read_text())['requests']['r1']['status']=='settled'
    with pytest.raises(ValueError,match='stop'):change(ledger,op|{'id':'r3'},now=4)


def test_primary_ledger_mutations_are_confined_to_the_vm_writer_platform(tmp_path,monkeypatch):
    import sys

    ledger=tmp_path/'quota.json';initialize(ledger,2,1000)
    (tmp_path/'WRITER_PLATFORM').write_text('linux')
    op={'action':'reserve','id':'r','max_output':128}
    monkeypatch.setattr(sys,'platform','darwin')
    with pytest.raises(ValueError,match='writer'):change(ledger,op,now=1)
    assert not json.loads(ledger.read_text())['requests']
    monkeypatch.setattr(sys,'platform','linux');change(ledger,op,now=2)
    assert json.loads(ledger.read_text())['requests']['r']['status']=='reserved'


def test_stopped_directory_cannot_be_reinitialized(tmp_path):
    (tmp_path/'STOP_REQUESTED').write_text('stop')
    with pytest.raises(ValueError,match='stop'):initialize(tmp_path/'quota.json',2,1000)
    assert not Path(tmp_path/'quota.json').exists()


def test_runner_stop_closes_quota_admission_before_any_child_can_start(tmp_path):
    import time
    from unittest.mock import patch

    from memweave_eval.runner import execute_harbor

    (tmp_path/'STOP_REQUESTED').touch();marker=tmp_path/'budget/STOP_REQUESTED'
    with patch('harbor.models.job.config.JobConfig.model_validate'),patch('memweave_eval.runner.subprocess.Popen')as start:
        with pytest.raises(TimeoutError):execute_harbor({},tmp_path,{},time.monotonic()+30,1,budget_stop_file=marker)
        start.assert_not_called()
    assert marker.exists()


def test_score_design_is_not_new_spending_authorization(tmp_path):
    from types import SimpleNamespace as NS

    from memweave_eval.spec import require_primary_authorization
    p=tmp_path/'contract.json';p.write_text('{"formal_run_allowed":false,"budget_authorization":null}')
    spec=NS(evaluation=NS(primary_default=True,primary_contract=p,deadline_utc='2026-11-06T12:00:00+00:00',admission_budget_usd=2),limits=NS(max_cost_usd=2))
    with pytest.raises(ValueError,match='new explicit budget'):require_primary_authorization(spec)
    c={'formal_run_allowed':True,'budget_authorization':{'maximum_usd':2,'start_utc':'2026-11-06T00:00:00+00:00','deadline_utc':'2026-11-07T00:00:00+00:00','evidence_reference':'unit fixture only, not actual authorization'}}
    p.write_text(json.dumps(c));require_primary_authorization(spec,now=1793923200)
    spec.evaluation.admission_budget_usd=3
    with pytest.raises(ValueError,match='exceeds'):require_primary_authorization(spec,now=1793923200)
