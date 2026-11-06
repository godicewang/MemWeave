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




def test_artifact_tree_refuses_symlinks(tmp_path):
    from memweave_eval.artifact_replay import artifact_digest

    (tmp_path / "link").symlink_to(Path("/tmp"))
    with pytest.raises(ValueError, match="symlink"):
        artifact_digest(tmp_path)
