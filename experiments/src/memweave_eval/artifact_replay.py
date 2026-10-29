"""No-model official artifact materialization for an audited ungraded attempt."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Literal

from harbor.agents.nop import NopAgent
from harbor.agents.options import AgentOptions
from harbor.models.trial.paths import EnvironmentPaths
from harbor.trial.artifact_handler import ArtifactHandler

from .storage import file_digest

AUDITED_VERIFIER_TIMEOUT = {
    "result": "77d8a41a03e1566d9a6b38f1cec76f90b81f717bc996cb5af967cb3265b909e5",
    "manifest": "9e3af49d69bb9a608c7e2632607214574cb16347f28024471f877fe128e021d5",
    "group": "fc61c803aed142040ec14237341147f2d2dcfea86bd1a6ff42cf294f563973fa",
}


def artifact_digest(directory: Path) -> str:
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("captured artifact symlink is unsupported")
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = file_digest(path)
    if "manifest.json" not in files:
        raise ValueError("captured artifacts have no manifest")
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def audited_verifier_timeout(path: Path) -> bool:
    files = {"result": path, "manifest": path.parent / "artifacts/manifest.json",
             "group": path.parents[3] / "group.lock.json"}
    if any(not p.is_file() or file_digest(p) != AUDITED_VERIFIER_TIMEOUT[k] for k, p in files.items()):
        return False
    error = json.loads(path.read_text()).get("exception_info") or {}
    return (error.get("exception_type") == "VerifierTimeoutError"
            and error.get("exception_message") == "Verifier execution timed out after 900.0 seconds")


class ArtifactReplayOptions(AgentOptions):
    source_result: str
    result_sha256: str
    artifacts_sha256: str
    variant: Literal["pi-native", "pi-memweave"]


class ArtifactReplayAgent(NopAgent):
    options_model = ArtifactReplayOptions

    @staticmethod
    def name():
        return "memweave-artifact-replay"

    async def run(self, instruction, environment, context):
        path = Path(self.options.source_result)
        artifacts = path.parent / "artifacts"
        if (file_digest(path) != self.options.result_sha256
                or artifact_digest(artifacts) != self.options.artifacts_sha256):
            raise ValueError("captured artifact source changed")
        raw = json.loads(path.read_text())
        task = Path(raw["config"]["task"]["path"])
        definition = tomllib.loads((task / "task.toml").read_text())
        handler = ArtifactHandler(artifacts=definition.get("artifacts", []), logger=self.logger)
        await handler.upload_artifacts(
            environment, artifacts_dir=artifacts,
            source_artifacts_dir=EnvironmentPaths.artifacts_dir,
            target_artifacts_dir=EnvironmentPaths.artifacts_dir,
        )
        (self.logs_dir / "artifact-replay.json").write_text(json.dumps({
            "model_requests": 0, "source_result": str(path),
            "result_sha256": self.options.result_sha256,
            "artifacts_sha256": self.options.artifacts_sha256,
        }) + "\n")
