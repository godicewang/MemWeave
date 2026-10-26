"""Thin public Harbor Pi integration: frozen package setup and official Pro handoff."""

from __future__ import annotations

import json
import shlex
import tempfile
import time
from pathlib import Path
from typing import Annotated, Literal

from harbor.agents.installed.node_install import nvm_node_install_snippet
from harbor.agents.installed.pi import Pi, PiOptions
from harbor.agents.options import Cli

from .storage import file_digest


class PiExperimentOptions(PiOptions):
    version: Literal["1.4.0"] = "1.4.0"
    node_version: str
    variant: Literal["pi-native", "pi-memweave"]
    package_path: str
    package_sha256: str
    auth_path: str
    protocol: Literal["tb4", "swe-pro-v2"]
    extension: Annotated[str | None, Cli("--extension")] = None


class ExperimentPi(Pi):
    options_model = PiExperimentOptions
    options: PiExperimentOptions

    @staticmethod
    def name() -> str:
        return "memweave-eval-pi"

    async def upload_private(self, environment, content: str, remote: str) -> None:
        with tempfile.TemporaryDirectory(prefix="memweave-auth-") as directory:
            local = Path(directory) / "private.json"
            local.write_text(content)
            local.chmod(0o600)
            await environment.upload_file(local, remote)
        target = shlex.quote(remote)
        owner = getattr(environment, "default_user", None)
        command = f"chmod 600 {target}"
        if owner is not None:
            command = f"chown {shlex.quote(str(owner))} {target} && " + command
        await self.exec_as_root(environment, command)

    async def install(self, environment) -> None:
        # Normal installed-agent setup, in the task's existing user and image.
        await self.ensure_system_dependencies(environment, ("curl",))
        node = shlex.quote(self.options.node_version)
        bootstrap = nvm_node_install_snippet(int(self.options.node_version.split(".")[0]))
        await self.exec_as_agent(
            environment,
            f"set -euo pipefail; {bootstrap} && nvm install {node} && nvm alias default {node} "
            "&& npm install -g --ignore-scripts @earendil-works/pi-coding-agent@1.4.0 "
            "&& node --version && pi --version",
            timeout_sec=1200,
        )
        info = await self.exec_as_agent(
            environment,
            '. "$HOME/.nvm/nvm.sh"; node -e '
            + shlex.quote(
                "console.log(JSON.stringify({home:require('os').homedir(),cwd:process.cwd()}))"
            ),
        )
        locations = json.loads(info.stdout.strip().splitlines()[-1])
        home = locations["home"]
        if not home.startswith("/"):
            raise ValueError("container has no absolute home directory")
        self._experiment_home = home
        self._experiment_cwd = locations["cwd"]
        profile = home + "/.pi/agent"
        await self.exec_as_agent(environment, f"mkdir -p {shlex.quote(profile)}")
        auth = json.loads(Path(self.options.auth_path).read_text())
        if "deepseek" not in auth or auth["deepseek"].get("type") != "api_key":
            raise ValueError("an API-key DeepSeek private profile is required")
        # The key is transferred as a private file, never placed in command text or job config.
        await self.upload_private(
            environment, json.dumps({"deepseek": auth["deepseek"]}), profile + "/auth.json"
        )
        await self.upload_private(
            environment,
            json.dumps({"compaction": {"enabled": self.options.variant == "pi-native"}}),
            profile + "/settings.json",
        )
        if self.options.variant == "pi-memweave":
            archive = Path(self.options.package_path)
            if file_digest(archive) != self.options.package_sha256:
                raise ValueError("frozen MemWeave package changed")
            remote = home + "/.local/share/memweave-eval"
            await self.exec_as_agent(environment, f"mkdir -p {shlex.quote(remote)}")
            await environment.upload_file(archive, remote + "/subject.tgz")
            await self.exec_as_agent(
                environment,
                '. "$HOME/.nvm/nvm.sh"; set -e; '
                f"tar -xzf {shlex.quote(remote + '/subject.tgz')} -C {shlex.quote(remote)} && "
                f"npm install --prefix {shlex.quote(remote + '/package')} --omit=dev "
                "--ignore-scripts --legacy-peer-deps",
                timeout_sec=1200,
            )
            package = remote + "/package"
            # Reuse product-owned path and resource functions; no parallel memory layout.
            script = (
                f"const {{memoryPaths}}=await import({json.dumps(package + '/src/storage/paths.ts')});"
                f"const {{ensureEmbeddingModel}}=await import({json.dumps(package + '/src/task/embedding.ts')});"
                "const fs=await import('node:fs/promises');const paths=memoryPaths();"
                f"const defaults=JSON.parse(await fs.readFile({json.dumps(package + '/src/config/defaults.json')},'utf8'));"
                "await fs.mkdir(paths.root,{recursive:true});"
                f"await fs.copyFile({json.dumps(package + '/resources/rule.md')},paths.rule);"
                "await ensureEmbeddingModel(paths,defaults.task_search);"
            )
            await self.exec_as_agent(
                environment,
                '. "$HOME/.nvm/nvm.sh"; node --input-type=module -e ' + shlex.quote(script),
                timeout_sec=1200,
            )
            self.options.extension = package + "/src/extension/index.ts"
        setup = {
            "pi_version": self.options.version,
            "node_version": self.options.node_version,
            "variant": self.options.variant,
            "cwd": self._experiment_cwd,
            "package_sha256": self.options.package_sha256 if self.options.extension else None,
        }
        (self.logs_dir / "experiment-setup.json").write_text(json.dumps(setup, indent=2) + "\n")

    async def exec_as_agent(self, environment, command: str, **kwargs):
        is_pi = "pi --print --mode json" in command
        if is_pi:
            # Public upstream Pi command is reused verbatim inside a pipefail shell.
            # The official locked Pro wrappers reserve 60s for patch capture.
            remaining = max(
                1, 2940 - int(time.monotonic() - getattr(self, "_agent_started", time.monotonic()))
            )
            prefix = f"timeout -k 30 {remaining} " if self.options.protocol == "swe-pro-v2" else ""
            command = prefix + "bash -o pipefail -c " + shlex.quote(command)
            if hasattr(self, "_experiment_home"):
                kwargs["env"] = dict(
                    kwargs.get("env") or {},
                    PI_CODING_AGENT_DIR=self._experiment_home + "/.pi/agent",
                )
        result = await super().exec_as_agent(environment, command, **kwargs)
        if not is_pi:
            setup_log = self.logs_dir / "setup/experiment-install.log"
            setup_log.parent.mkdir(parents=True, exist_ok=True)
            with setup_log.open("a") as stream:
                stream.write(getattr(result, "stdout", "") or "")
                stream.write(getattr(result, "stderr", "") or "")
        if getattr(result, "return_code", 0):
            raise RuntimeError(
                f"{'Pi' if is_pi else 'Agent setup'} exited with status {result.return_code}; see native output"
            )
        return result

    async def run(self, instruction, environment, context) -> None:
        self._agent_started = time.monotonic()
        try:
            if self.options.protocol == "swe-pro-v2":
                model = await environment.exec(
                    command="curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 10 "
                    "https://api.deepseek.com/models",
                    timeout_sec=15,
                )
                outside = await environment.exec(
                    command="curl -sS -o /dev/null --connect-timeout 3 --max-time 5 https://example.com",
                    timeout_sec=10,
                )
                if (
                    model.return_code
                    or model.stdout.strip() not in {"200", "401"}
                    or outside.return_code == 0
                ):
                    raise RuntimeError("Pro offline/model-endpoint network probes failed")
                (self.logs_dir / "network-probe.json").write_text(
                    json.dumps({"model_endpoint": "reachable", "general_internet": "blocked"})
                    + "\n"
                )
            await super().run(instruction, environment, context)
        finally:
            if self.options.protocol == "swe-pro-v2":
                # Match the pinned official locked-agent capture: include untracked files,
                # preserve the original task cwd, and leave the index reset afterwards.
                capture = (
                    "mkdir -p /logs/agent; "
                    "repo=$(git -C /app rev-parse --show-toplevel 2>/dev/null || "
                    "git -C /testbed rev-parse --show-toplevel 2>/dev/null || echo /app); "
                    'cd "$repo" && git add -A 2>/dev/null; '
                    "git diff --cached > /logs/agent/model.patch 2>/dev/null; "
                    "git reset -q 2>/dev/null; test -f /logs/agent/model.patch"
                )
                result = await environment.exec(command=capture, user="root", timeout_sec=30)
                if result.return_code != 0:
                    raise RuntimeError("official Pro patch capture failed")
            if self.options.variant == "pi-memweave" and hasattr(self, "_experiment_home"):
                # Snapshot only original runtime evidence, not credentials or model weights.
                home = shlex.quote(self._experiment_home)
                result = await environment.exec(
                    command=f"test ! -d {home}/.pi/memory || tar -czf /logs/agent/memory.tar.gz "
                    f"--exclude=models --exclude=search -C {home}/.pi memory",
                    timeout_sec=120,
                )
                if result.return_code != 0:
                    raise RuntimeError("memory evidence collection failed")
