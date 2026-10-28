"""Thin public Harbor Pi integration: frozen package setup and official Pro handoff."""

from __future__ import annotations

import json
import shlex
import tempfile
import time
from pathlib import Path
from typing import Annotated, Literal

from harbor.agents.installed.pi import Pi, PiOptions
from harbor.agents.options import Cli

from .network_probe import check_network
from .private_runtime import activate as activate_private_runtime
from .private_runtime import prepare as prepare_private_runtime
from .public_archive import public_archive
from .runtime_cache import materialize, node_download
from .storage import file_digest


class PiExperimentOptions(PiOptions):
    version: Literal["1.4.0"] = "1.4.0"
    node_version: str
    variant: Literal["pi-native", "pi-memweave"]
    package_path: str
    package_sha256: str
    auth_path: str
    protocol: Literal["tb4", "swe-pro-v2"]
    runtime_plan: str | None = None
    runtime_plan_sha256: str | None = None
    prepare_only: bool = False
    runtime_objects: dict[str, dict] | None = None
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

    def get_version_command(self) -> str:
        return "pi --version"

    async def pack_asset(self, environment, directory: str, top: str, target: Path):
        remote = self._experiment_home + "/.memweave-export.tar"
        try:
            await self.exec_as_agent(
                environment,
                f"tar -cf {shlex.quote(remote)} -C {shlex.quote(directory)} {shlex.quote(top)}",
            )
            await environment.download_file(remote, target)
        finally:
            await self.exec_as_agent(environment, "rm -f " + shlex.quote(remote))

    async def deploy_asset(self, environment, cache: Path, desc: dict, destination: str):
        remote = self._experiment_home + "/.memweave-import.tar"
        try:
            await environment.upload_file(cache / desc["key"] / "payload.tar", remote)
            await self.exec_as_agent(
                environment,
                f"mkdir -p {shlex.quote(destination)} && "
                f"tar -xf {shlex.quote(remote)} -C {shlex.quote(destination)}",
            )
        finally:
            await self.exec_as_root(environment, "rm -f " + shlex.quote(remote))

    def model_script(self, *, allow_download=False) -> str:
        package = self._asset_root + "/package"
        return (
            f"const {{memoryPaths}}=await import({json.dumps(package + '/src/storage/paths.ts')});"
            f"const {{ensureEmbeddingModel}}=await import({json.dumps(package + '/src/task/embedding.ts')});"
            "const fs=await import('node:fs/promises');const paths=memoryPaths();"
            f"const defaults=JSON.parse(await fs.readFile({json.dumps(package + '/src/config/defaults.json')},'utf8'));"
            + ("" if allow_download else
               "globalThis.fetch=()=>{throw Error('Frozen embedding invalid; downloads disabled');};")
            + "await ensureEmbeddingModel(paths,defaults.task_search);"
        )

    async def install(self, environment) -> None:
        started = time.monotonic()
        if not self.options.runtime_plan or not self.options.runtime_plan_sha256:
            raise ValueError("a frozen software cache plan is required")
        plan_path = Path(self.options.runtime_plan)
        if file_digest(plan_path) != self.options.runtime_plan_sha256:
            raise ValueError("runtime cache plan changed")
        plan = json.loads(plan_path.read_text())
        reference = environment.task_env_config.docker_image
        entry = plan["entries"][reference]
        cache = Path(plan["cache"])
        info = await self.exec_as_agent(environment, 'printf \'%s\\n%s\\n\' "$HOME" "$PWD"')
        home, cwd = info.stdout.strip().splitlines()
        if not home.startswith("/") or not cwd.startswith("/"):
            raise ValueError("container has no absolute home/cwd")
        self._experiment_home, self._experiment_cwd = home, cwd
        self._asset_root = home + "/.local/share/memweave-eval"
        profile = home + "/.pi/agent"
        await self.exec_as_agent(
            environment,
            f"test ! -e {shlex.quote(profile)} && "
            f"test ! -e {shlex.quote(home + '/.pi/memory')} && "
            f"test ! -e {shlex.quote(self._asset_root)} && "
            f"mkdir -p {shlex.quote(self._asset_root)}",
        )
        resources = {}

        async def resource(name, top, builder, destination):
            desc = entry[name]
            record, hit = await materialize(
                cache, desc, top, builder, allow_create=self.options.prepare_only
            )
            if not self.options.prepare_only and (
                self.options.runtime_objects is None
                or self.options.runtime_objects.get(desc["key"]) != record
            ):
                raise ValueError("runtime software differs from the frozen object")
            if hit:
                await self.deploy_asset(environment, cache, desc, destination)
            resources[name] = dict(record, cache_hit=hit)

        async def build_base(target):
            archive, receipt = node_download(
                cache, self.options.node_version, entry["image"]["platform"]
            )
            remote = self._asset_root + "/node.tar.gz"
            await environment.upload_file(archive, remote)
            await self.exec_as_agent(
                environment,
                f"mkdir -p {shlex.quote(self._asset_root + '/node')} && "
                f"tar -xzf {shlex.quote(remote)} --strip-components=1 "
                f"-C {shlex.quote(self._asset_root + '/node')} && rm {shlex.quote(remote)}",
            )
            compatibility = None
            if entry.get("libc") == "musl":
                compatibility = await prepare_private_runtime(self, environment, cache)
            await self.exec_as_agent(
                environment,
                f"npm install -g --prefix {shlex.quote(self._asset_root + '/node')} "
                "--ignore-scripts @earendil-works/pi-coding-agent@1.4.0",
                timeout_sec=1800,
            )
            await self.pack_asset(environment, self._asset_root, "node", target)
            (self.logs_dir / "node-download.json").write_text(json.dumps(receipt) + "\n")
            return {"node_download": receipt, "private_gnu_runtime": compatibility}

        await resource("base", "node", build_base, self._asset_root)
        if entry.get("libc") == "musl":
            await activate_private_runtime(self, environment)
        versions = await self.exec_as_agent(environment, "node --version && pi --version")
        if versions.stdout.strip().splitlines() != [
            "v" + self.options.node_version,
            self.options.version,
        ]:
            raise ValueError("cached Node/Pi version mismatch")

        if self.options.variant == "pi-memweave":
            archive = Path(self.options.package_path)
            if file_digest(archive) != self.options.package_sha256:
                raise ValueError("frozen MemWeave package changed")

            async def build_addon(target):
                remote = self._asset_root + "/subject.tgz"
                await environment.upload_file(archive, remote)
                public, receipt = public_archive(cache)
                seed = self._asset_root + "/onnxruntime-node-1.30.0.tgz"
                await environment.upload_file(public, seed)
                (self.logs_dir / "public-npm-archive.json").write_text(json.dumps(receipt) + "\n")
                installed = self._asset_root + "/production-install"
                destination = self._asset_root + "/package"
                await self.exec_as_agent(
                    environment,
                    f"npm --offline --ignore-scripts cache add {shlex.quote(seed)} && "
                    f"npm install --prefix {shlex.quote(installed)} {shlex.quote(remote)} "
                    "--omit=dev --ignore-scripts --legacy-peer-deps --no-audit --no-fund && "
                    f"mv {shlex.quote(installed + '/node_modules/@godice/memweave')} "
                    f"{shlex.quote(destination)} && "
                    f"mv {shlex.quote(installed + '/node_modules')} {shlex.quote(destination + '/node_modules')} && "
                    f"rm -rf {shlex.quote(installed)} && rm {shlex.quote(seed)} {shlex.quote(remote)}",
                    timeout_sec=1800,
                )
                await self.pack_asset(environment, self._asset_root, "package", target)
                return {"public_npm_archive": receipt, "install": "production tarball dependency"}

            await resource("addon", "package", build_addon, self._asset_root)
            # Product-owned paths/functions determine and verify embedding resources.
            model_info = await self.exec_as_agent(
                environment,
                "node --input-type=module -e "
                + shlex.quote(
                    self.model_script().split("await ensureEmbeddingModel")[0]
                    + "console.log(paths.root);"
                ),
            )
            memory = model_info.stdout.strip().splitlines()[-1]

            async def build_models(target):
                await self.exec_as_agent(
                    environment,
                    "node --input-type=module -e " + shlex.quote(self.model_script(allow_download=True)),
                    timeout_sec=1800,
                )
                await self.pack_asset(environment, memory, "models", target)

            await resource("models", "models", build_models, memory)
            await self.exec_as_agent(
                environment,
                "node --input-type=module -e "
                + shlex.quote(
                    self.model_script()
                    + f"await fs.copyFile({json.dumps(self._asset_root + '/package/resources/rule.md')},paths.rule);"
                ),
                timeout_sec=120,
            )
            self.options.extension = self._asset_root + "/package/src/extension/index.ts"

        await self.exec_as_agent(environment, f"mkdir -p {shlex.quote(profile)}")
        # No credential file is read or uploaded by preparation Jobs.
        if not self.options.prepare_only:
            auth = json.loads(Path(self.options.auth_path).read_text())
            if "deepseek" not in auth or auth["deepseek"].get("type") != "api_key":
                raise ValueError("an API-key DeepSeek private profile is required")
            await self.upload_private(
                environment, json.dumps({"deepseek": auth["deepseek"]}), profile + "/auth.json"
            )
        await self.upload_private(
            environment,
            json.dumps({"compaction": {"enabled": self.options.variant == "pi-native"}}),
            profile + "/settings.json",
        )
        setup = {
            "pi_version": self.options.version,
            "node_version": self.options.node_version,
            "variant": self.options.variant,
            "cwd": cwd,
            "prepare_only": self.options.prepare_only,
            "fresh_profile_and_memory": True,
            "resources": resources,
            "deployment_seconds": time.monotonic() - started,
            "package_sha256": self.options.package_sha256 if self.options.extension else None,
        }
        (self.logs_dir / "experiment-setup.json").write_text(json.dumps(setup, indent=2) + "\n")

    async def runtime_preflight(self, environment):
        # Public SDK startup with full defaults/production entry, never prompt()/LLM.
        sdk = (
            self._asset_root
            + "/node/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js"
        )
        script = (
            "import fs from 'node:fs/promises';import {createHash} from 'node:crypto';"
            f"const sdk=await import({json.dumps(sdk)});"
            f"const agentDir={json.dumps(self._experiment_home + '/.pi/agent')};"
            "const settings=sdk.SettingsManager.create(process.cwd(),agentDir);"
            "const loader=new sdk.DefaultResourceLoader({cwd:process.cwd(),agentDir,settingsManager:settings,"
            f"additionalExtensionPaths:{json.dumps([self.options.extension] if self.options.extension else [])}}});"
            "await loader.reload();const runtime=await sdk.ModelRuntime.create({"
            "authPath:agentDir+'/auth.json',modelsPath:agentDir+'/models.json',"
            "allowModelNetwork:false,refreshOnCreate:false});"
            "const {session,extensionsResult}=await sdk.createAgentSession({agentDir,resourceLoader:loader,"
            "settingsManager:settings,modelRuntime:runtime});"
            "try{const errors=[];await session.bindExtensions({onError:e=>errors.push(String(e.message||e))});"
            "if(extensionsResult.errors.length||errors.length)throw Error('Extension startup failed: '+JSON.stringify({errors,load:extensionsResult.errors}));"
            "const tools=session.getActiveToolNames();"
            "for(const t of ['read','bash','edit','write'])if(!tools.includes(t))throw Error('Missing native tool '+t);"
            f"const enabled={json.dumps(self.options.variant == 'pi-memweave')};"
            "if(tools.includes('task_create')!==enabled)throw Error('Wrong variant tools');"
            "if(session.autoCompactionEnabled===enabled)throw Error('Wrong effective compaction');"
            "let embedding=null;"
        )
        if self.options.variant == "pi-memweave":
            script += self.model_script().replace(
                "const fs=await import('node:fs/promises');", ""
            ) + (
                f"const {{LocalEmbedding}}=await import({json.dumps(self._asset_root + '/package/src/task/embedding.ts')});"
                "const worker=new LocalEmbedding(paths);try{const result=await worker.embed(['runtime preflight'],'query',defaults.task_search);"
                "embedding=result.vectors[0].length;if(embedding!==384)throw Error('Invalid embedding');}finally{await worker.dispose();}"
            )
        script += (
            "await fs.writeFile('/logs/agent/runtime-preflight.json',JSON.stringify({"
            "model_requests:0,tools,embedding_dimensions:embedding,"
            "session_id:session.sessionId,"
            "compaction:session.autoCompactionEnabled,system_prompt_sha256:"
            "createHash('sha256').update(session.systemPrompt).digest('hex')}));"
            "}finally{session.dispose();}"
        )
        await self.exec_as_agent(
            environment, "node --input-type=module -e " + shlex.quote(script), timeout_sec=180
        )

    async def exec_as_agent(self, environment, command: str, **kwargs):
        is_pi = "pi --print --mode json" in command
        if hasattr(self, "_asset_root"):
            if command.startswith(". ~/.nvm/nvm.sh; "):
                command = command.removeprefix(". ~/.nvm/nvm.sh; ")
            command = f"export PATH={shlex.quote(self._asset_root + '/node/bin')}:$PATH; " + command
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
        if self.options.prepare_only:
            await self.runtime_preflight(environment)
            return
        self._agent_started = time.monotonic()
        try:
            if self.options.protocol == "swe-pro-v2":
                await check_network(environment, self._asset_root + "/node/bin/node", self.logs_dir)
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
