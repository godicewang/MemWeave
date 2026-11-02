import asyncio
import json
from types import SimpleNamespace

import pytest

from memweave_eval.network_probe import check_network


def test_public_policy_single_outside_timeout_is_diagnostic_not_a_safety_rejection(tmp_path):
    class Environment:
        async def exec(self,**kwargs):
            return SimpleNamespace(return_code=0,stdout=json.dumps({
                'model':{'ok':True,'status':401,'error':None},
                'outside':{'ok':False,'status':None,'error':'CONNECT_TIMEOUT'}}))
    asyncio.run(check_network(Environment(),'/node',tmp_path,expected_offline=False))
    record=json.loads((tmp_path/'network-probe.json').read_text())
    assert record['passed']and record['general_internet']=='probe_unreachable'
    assert record['public_probe_warning']


def test_fixed_public_environment_checks_original_policy_without_changing_it(tmp_path):
    class Environment:
        async def exec(self, **_):
            return SimpleNamespace(return_code=0,stdout=json.dumps({
                'model':{'ok':True,'status':401,'error':None},
                'outside':{'ok':True,'status':200,'error':None}}))
    asyncio.run(check_network(Environment(),'/fixed/node/bin/node',tmp_path,expected_offline=False))
    result=json.loads((tmp_path/'network-probe.json').read_text())
    assert result['passed'] and result['expected_offline'] is False


@pytest.mark.parametrize("status", [200, 401])
def test_node_probe_uses_no_system_curl_and_preserves_policy(tmp_path, status):
    class Environment:
        async def exec(self, *, command, timeout_sec):
            assert command.startswith("/fixed/node/bin/node ")
            assert "curl" not in command
            assert "api.deepseek.com/models" in command and "example.com" in command
            return SimpleNamespace(return_code=0, stdout=json.dumps({
                "model": {"ok": True, "status": status, "error": None},
                "outside": {"ok": False, "status": None, "error": "CONNECT_TIMEOUT"},
            }))
    asyncio.run(check_network(Environment(), "/fixed/node/bin/node", tmp_path))
    record = json.loads((tmp_path / "network-probe.json").read_text())
    assert record["passed"] is True
    assert record["general_internet"] == "blocked"


@pytest.mark.parametrize("raw", [
    {"model": {"ok": True, "status": 401, "error": None},
     "outside": {"ok": True, "status": 503, "error": None}},
    {"model": {"ok": False, "status": None, "error": "ECONNRESET"},
     "outside": {"ok": False, "status": None, "error": "CONNECT_TIMEOUT"}},
    {"model": {"ok": True, "status": 301, "error": None},
     "outside": {"ok": False, "status": None, "error": "CONNECT_TIMEOUT"}},
    {"bad": "data"},
])
def test_network_failure_is_recorded_before_pi_can_start(tmp_path, raw):
    class Environment:
        async def exec(self, **kwargs):
            return SimpleNamespace(return_code=0, stdout=json.dumps(raw))
    with pytest.raises(RuntimeError, match="network"):
        asyncio.run(check_network(Environment(), "/fixed/node/bin/node", tmp_path))
    assert json.loads((tmp_path / "network-probe.json").read_text())["passed"] is False


def test_transient_model_transport_retries_without_relaxing_outside_policy(tmp_path):
    class Environment:
        calls = 0

        async def exec(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(return_code=0, stdout=json.dumps({
                "model": ({"ok": False, "status": None, "error": "TOTAL_TIMEOUT"}
                          if self.calls == 1 else {"ok": True, "status": 401, "error": None}),
                "outside": {"ok": False, "status": None, "error": "ECONNRESET"},
            }))

    env = Environment()
    asyncio.run(check_network(env, "/fixed/node/bin/node", tmp_path))
    record = json.loads((tmp_path / "network-probe.json").read_text())
    assert env.calls == 2
    assert record["passed"] is True
    assert len(record["attempts"]) == 2
    assert record["attempts"][0]["checks"]["model"]["error"] == "TOTAL_TIMEOUT"


def test_transport_retry_is_bounded_and_outside_access_fails_immediately(tmp_path):
    class Environment:
        def __init__(self, outside):
            self.calls = 0
            self.outside = outside

        async def exec(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(return_code=0, stdout=json.dumps({
                "model": {"ok": False, "status": None, "error": "TOTAL_TIMEOUT"},
                "outside": {"ok": self.outside, "status": 200 if self.outside else None,
                            "error": None if self.outside else "ECONNRESET"},
            }))

    for outside, expected in ((False, 3), (True, 1)):
        env = Environment(outside)
        with pytest.raises(RuntimeError, match="network"):
            asyncio.run(check_network(env, "/fixed/node/bin/node", tmp_path))
        assert env.calls == expected
        record = json.loads((tmp_path / "network-probe.json").read_text())
        assert not record["passed"] and len(record["attempts"]) == expected
