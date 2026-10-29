"""Keep one reviewed official resource-ending attempt; never retry its model."""
import json

import pytest

import memweave_eval.paired as module
from memweave_eval.storage import atomic_json, file_digest


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    path = tmp_path / "groups/g32/harbor/solve/original/result.json"
    raw = {"exception_info": {
        "exception_type": "NonZeroAgentExitCodeError",
        "exception_message": "Command failed (exit 137): timeout -k 30 2940 bash -o pipefail -c original",
    }, "config": {"agent": {"kwargs": {"variant": "pi-memweave", "protocol": "swe-pro-v2"}}}}
    atomic_json(path, raw)
    patch = path.parent / "agent/model.patch"
    patch.parent.mkdir()
    patch.write_text("original resource-limited patch")
    atomic_json(path.parent / "agent/network-probe.json", {"passed": True})
    group = path.parents[3] / "group.lock.json"
    atomic_json(group, {"frozen": "reviewed original"})
    binding = {"result": file_digest(path), "patch": file_digest(patch), "group": file_digest(group)}
    monkeypatch.setattr(module, "AUDITED_RESOURCE_END", binding, raising=False)
    row = {"task_id": "original-task", "variant_id": "pi-memweave",
           "suite_id": "swe-bench-pro-v2", "solve_source": str(path),
           "solve_status": "agent_error", "success": False,
           "session_diagnostics": {"model_responses_with_usage": 9}}
    return tmp_path, path, patch, group, binding, row


def test_known_resource_end_is_kept_as_first_zero_and_not_retried(reviewed):
    root, path, _, _, _, row = reviewed
    kept, pending, history = module.partition_primary_rows(root, [row])
    assert len(kept) == 1 and kept[0]["success"] is False
    assert kept[0]["solve_status"] == "agent_error"
    assert not pending and not history
    plan = module.continuation_plan([{"task_id": row["task_id"], "variant_id": row["variant_id"]}], kept, pending)
    assert plan == []
    assert json.loads(path.read_text())["exception_info"]["exception_type"] == "NonZeroAgentExitCodeError"


@pytest.mark.parametrize("change", [
    {"success": None}, {"success": True}, {"variant_id": "pi-native"},
    {"suite_id": "terminal-bench-4"}, {"session_diagnostics": {"model_responses_with_usage": 0}},
])
def test_unknown_grade_other_variant_or_missing_model_evidence_rejected(reviewed, change):
    root, _, _, _, _, row = reviewed
    with pytest.raises(ValueError, match="incomplete"):
        module.partition_primary_rows(root, [dict(row, **change)])


@pytest.mark.parametrize("which", ["result", "patch", "group", "probe"])
def test_changed_source_or_failed_network_not_accepted(reviewed, which):
    root, path, patch, group, _, row = reviewed
    if which == "probe":
        atomic_json(path.parent / "agent/network-probe.json", {"passed": False})
    else:
        target = {"result": path, "patch": patch, "group": group}[which]
        target.write_text(target.read_text() + "changed")
    with pytest.raises(ValueError, match="incomplete"):
        module.partition_primary_rows(root, [row])


@pytest.mark.parametrize("field,value", [
    ("exception_type", "AgentTimeoutError"),
    ("exception_message", "Command failed (exit 137): arbitrary process"),
    ("protocol", "tb4"), ("variant", "pi-native"),
])
def test_hash_binding_alone_does_not_replace_error_and_protocol_checks(reviewed, field, value):
    root, path, _, _, binding, row = reviewed
    raw = json.loads(path.read_text())
    target = raw["exception_info"] if field.startswith("exception_") else raw["config"]["agent"]["kwargs"]
    target[field] = value
    atomic_json(path, raw)
    binding["result"] = file_digest(path)
    with pytest.raises(ValueError, match="incomplete"):
        module.partition_primary_rows(root, [row])
