import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def source(tmp_path):
    from memweave_eval.storage import atomic_json, file_digest

    task = tmp_path / "task"
    task.mkdir()
    (task / "task.toml").write_text('artifacts = ["/app/src"]\n')
    original = tmp_path / "runs/parent/groups/g46/harbor/solve/trial/result.json"
    atomic_json(original, {"config": {"task": {"path": str(task)}}, "exception_info": {
        "exception_type": "VerifierTimeoutError", "exception_message": "Verifier execution timed out after 900.0 seconds"}})
    artifact = original.parent / "artifacts/app/src/file.ts"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("original captured business code")
    atomic_json(original.parent / "artifacts/manifest.json", [{"source": "/app/src", "status": "ok"}])
    atomic_json(original.parents[3] / "group.lock.json", {"images": {"task": {"id": "fixed"}}})
    return original, file_digest


def test_artifact_replay_is_no_model_and_uses_harbor_materialization(tmp_path):
    from memweave_eval.artifact_replay import ArtifactReplayAgent, artifact_digest

    original, digest = source(tmp_path)
    agent = ArtifactReplayAgent(logs_dir=tmp_path, model_name="replay", source_result=str(original),
        result_sha256=digest(original), artifacts_sha256=artifact_digest(original.parent / "artifacts"),
        variant="pi-memweave")
    with patch("memweave_eval.artifact_replay.ArtifactHandler.upload_artifacts", new_callable=AsyncMock) as upload:
        asyncio.run(agent.run("ignored task text", object(), object()))
        upload.assert_awaited_once()
        assert upload.call_args.kwargs["artifacts_dir"] == original.parent / "artifacts"
    assert json.loads((tmp_path / "artifact-replay.json").read_text())["model_requests"] == 0
    (original.parent / "artifacts/app/src/file.ts").write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(agent.run("ignored", object(), object()))


def test_only_audited_verifier_timeout_is_pending_score_only(tmp_path, monkeypatch):
    import memweave_eval.artifact_replay as replay
    from memweave_eval.paired import partition_primary_rows

    original, digest = source(tmp_path)
    monkeypatch.setattr(replay, "AUDITED_VERIFIER_TIMEOUT", {
        "result": digest(original), "manifest": digest(original.parent / "artifacts/manifest.json"),
        "group": digest(original.parents[3] / "group.lock.json")})
    row = {"task_id": "task", "variant_id": "pi-memweave", "suite_id": "terminal-bench-4",
           "solve_source": str(original), "solve_status": "verifier_error", "success": None,
           "session_diagnostics": {"model_responses_with_usage": 79}}
    keep, pending, history = partition_primary_rows(tmp_path, [row])
    assert not keep and not history and len(pending) == 1
    assert pending[0]["artifact_tree_sha256"] == replay.artifact_digest(original.parent / "artifacts")
    changed = json.loads(original.read_text())
    changed["exception_info"]["exception_type"] = "AgentTimeoutError"
    original.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="incomplete"):
        partition_primary_rows(tmp_path, [row])


def test_artifact_tree_refuses_symlinks(tmp_path):
    from memweave_eval.artifact_replay import artifact_digest

    (tmp_path / "link").symlink_to(Path("/tmp"))
    with pytest.raises(ValueError, match="symlink"):
        artifact_digest(tmp_path)


def test_offline_score_requires_replay_receipt_and_original_image_binding(tmp_path):
    from memweave_eval.campaign_report import valid_artifact_replay
    from memweave_eval.storage import atomic_json

    group = tmp_path / "groups/g46"
    record = {"solve_source": "/original/result.json", "result_sha256": "a" * 64,
              "artifact_tree_sha256": "b" * 64, "variant_id": "pi-memweave",
              "actual_task_id": "task", "images": {"task": {"id": "frozen"}}}
    kwargs = {"source_result": record["solve_source"], "result_sha256": record["result_sha256"],
              "artifacts_sha256": record["artifact_tree_sha256"], "variant": "pi-memweave"}
    score = {"task_name": "suite/task", "trial_name": "replay-trial", "exception_info": None,
             "config": {"agent": {"import_path": "memweave_eval.artifact_replay:ArtifactReplayAgent",
                                   "kwargs": kwargs}}}
    lock = group / "group.lock.json"
    atomic_json(lock, {"images": record["images"]})
    indexed = {lock.relative_to(tmp_path).as_posix()}
    assert not valid_artifact_replay(tmp_path, group, record, score, indexed)
    receipt = group / "harbor/regrade-pi-memweave/replay-trial/agent/artifact-replay.json"
    atomic_json(receipt, dict(kwargs, model_requests=0))
    indexed.add(receipt.relative_to(tmp_path).as_posix())
    assert valid_artifact_replay(tmp_path, group, record, score, indexed)
    atomic_json(receipt, dict(kwargs, model_requests=1))
    assert not valid_artifact_replay(tmp_path, group, record, score, indexed)
    atomic_json(receipt, dict(kwargs, model_requests=0))
    atomic_json(lock, {"images": {"task": {"id": "different"}}})
    assert not valid_artifact_replay(tmp_path, group, record, score, indexed)
