import asyncio
import json

import pytest

from memweave_eval.preflight_retry import retry_pilot_preflight
from memweave_eval.storage import atomic_json

TARGETS = ("https://example.com", "https://registry.npmjs.org/-/ping",
           "https://www.iana.org/domains/reserved")


def record(*, passed=False, public=True, broker_status=401):
    endpoint = {"ok": passed, "status": 200 if passed else None,
                "error": None if passed else "CONNECT_TIMEOUT"}
    return {"passed": passed, "credential_free": True,
            "expected_general_internet_allowed": public,
            "checks": {"model": {"ok": True, "status": broker_status,
                                 "capability_rejected": broker_status == 401},
                       "outside_targets": {url: dict(endpoint) for url in TARGETS}}}


class Probe:
    def __init__(self, values):
        self.values = values
        self.paths = []

    async def __call__(self, environment, node, logs, **options):
        assert environment == "original actor" and node == "original node"
        assert options == {"general_internet_allowed": True, "broker_url": "original broker"}
        self.paths.append(logs)
        value = self.values[len(self.paths) - 1]
        atomic_json(logs / "network-probe.json", value, immutable=True)
        if not value["passed"]:
            raise RuntimeError("pilot network/credential-isolation probe failed")


def run(probe, logs):
    return asyncio.run(retry_pilot_preflight(
        probe, "original actor", "original node", logs,
        general_internet_allowed=True, broker_url="original broker"))


def test_cold_connection_failure_keeps_both_checks_and_publishes_original_success(tmp_path):
    first, second = record(), record(passed=True)
    probe = Probe([first, second])
    run(probe, tmp_path)
    assert len(set(probe.paths)) == 2
    assert [json.loads((p / "network-probe.json").read_text()) for p in probe.paths] == [first, second]
    assert json.loads((tmp_path / "network-probe.json").read_text()) == second


@pytest.mark.parametrize("change", ["broker", "restricted", "incomplete", "unexpected"])
def test_auth_policy_or_incomplete_failures_are_never_retried(tmp_path, change):
    value = record()
    if change == "broker":
        value["checks"]["model"]["capability_rejected"] = False
    elif change == "restricted":
        value["expected_general_internet_allowed"] = False
    elif change == "incomplete":
        value["checks"]["outside_targets"].pop(TARGETS[0])
    else:
        value["checks"]["outside_targets"][TARGETS[0]]["error"] = "NETWORK_ERROR"
    probe = Probe([value])
    with pytest.raises(RuntimeError, match="credential-isolation"):
        run(probe, tmp_path)
    assert len(probe.paths) == 1
    assert json.loads((tmp_path / "network-probe.json").read_text()) == value


def test_three_transient_failures_stop_and_preserve_all_checks(tmp_path):
    probe = Probe([record(), record(), record()])
    with pytest.raises(RuntimeError, match="credential-isolation"):
        run(probe, tmp_path)
    assert len(probe.paths) == 3
    assert all((p / "network-probe.json").exists() for p in probe.paths)


def test_existing_trial_evidence_is_not_overwritten(tmp_path):
    original = record(passed=True)
    atomic_json(tmp_path / "network-probe.json", original, immutable=True)
    probe = Probe([record()])
    with pytest.raises(FileExistsError):
        run(probe, tmp_path)
    assert probe.paths == []
    assert json.loads((tmp_path / "network-probe.json").read_text()) == original
