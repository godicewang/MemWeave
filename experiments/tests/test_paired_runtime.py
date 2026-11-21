import asyncio
import importlib
import sys
from types import ModuleType

import pytest

from memweave_eval.storage import atomic_json


@pytest.mark.parametrize("failed", [False, True])
def test_driver_keeps_upstream_loop_and_restores_its_network_binding(tmp_path, monkeypatch, failed):
    pilot = ModuleType("pilot_paid")
    calls = []

    async def check(environment, node, logs, **options):
        calls.append((environment, node, options))
        atomic_json(logs / "network-probe.json", {"passed": True}, immutable=True)

    class Upstream:
        async def _run_formal(self, instruction, environment, context):
            assert (instruction, context) == ("unchanged question", "unchanged context")
            await pilot.pilot_network(environment, "unchanged node", tmp_path)
            if failed:
                raise ValueError("upstream stopped")
            return "upstream agent loop"

    pilot.PaidPi = Upstream
    pilot.pilot_network = check
    monkeypatch.setitem(sys.modules, "pilot_paid", pilot)
    sys.modules.pop("memweave_eval.paired_runtime", None)
    module = importlib.import_module("memweave_eval.paired_runtime")
    try:
        async def run():
            return await module.PairedPi()._run_formal(
                "unchanged question", "unchanged environment", "unchanged context")

        if failed:
            with pytest.raises(ValueError, match="upstream stopped"):
                asyncio.run(run())
        else:
            assert asyncio.run(run()) == "upstream agent loop"
        assert calls == [("unchanged environment", "unchanged node", {})]
        assert pilot.pilot_network is check
    finally:
        sys.modules.pop("memweave_eval.paired_runtime", None)
