import asyncio
import json
from types import SimpleNamespace

import pytest

from memweave_eval.network_probe import check_network


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
