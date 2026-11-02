"""Thin public Harbor Pi integration: frozen package setup and official Pro handoff."""

from __future__ import annotations

import json
import shlex
import tempfile
import time
from datetime import UTC, datetime
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
    protocol: Literal["tb4", "swe-pro-v2", "swe-marathon"]
    evaluation_deadline: float | None = None
    evaluation_output_tokens: int = 16384
    evaluation_quota_backend: Literal["python", "node"] = "python"
    evaluation_per_task_arms: bool = False
    evaluation_content_evidence: bool = False
    # PiOptions is a Pydantic model; mutable field defaults are copied per instance.
    evaluation_task_timeouts: dict[str,int] = {}  # noqa: RUF012
    evaluation_task_ids: list[str] = []  # noqa: RUF012
    evaluation_task_configs: dict = {}  # noqa: RUF012
    evaluation_sealed_tasks: list[str] = []  # noqa: RUF012
    evaluation_run_id: str | None = None
    evaluation_progress_after_returns: int = 80
    smoke_barrier: str | None = None
    evaluation_canary: bool = False
    evaluation_request_limit: int | None = None
    evaluation_episode_budget: float | None = None
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
        identity = await self.exec_as_agent(environment, "id -u && id -g")
        ids = identity.stdout.strip().splitlines()
        if len(ids) != 2 or any(not value.isascii() or not value.isdecimal() for value in ids):
            raise ValueError("unexpected Agent numeric identity")
        with tempfile.TemporaryDirectory(prefix="memweave-auth-") as directory:
            local = Path(directory) / "private.json"
            local.write_text(content)
            local.chmod(0o600)
            await environment.upload_file(local, remote)
        target = shlex.quote(remote)
        command = f"chown {ids[0]}:{ids[1]} {target} && chmod 600 {target}"
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
        matches=[t for t in self.options.evaluation_task_ids if any(part.startswith(t+'__') for part in self.logs_dir.parts)]
        if self.options.evaluation_per_task_arms and len(matches)!=1:
            raise ValueError('Cannot identify trusted task-arm from Harbor trial directory')
        self._evaluation_task_id=matches[0] if len(matches)==1 else None
        self._evaluation_task_config=self.options.evaluation_task_configs.get(self._evaluation_task_id,{})
        self._evaluation_sealed=self._evaluation_task_id in self.options.evaluation_sealed_tasks
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
        if self.options.evaluation_deadline:
            evaluator = self._asset_root + '/evaluation'
            await self.exec_as_agent(environment, f'mkdir -p {shlex.quote(evaluator)}')
            for filename in ('fetch_guard.mjs', 'content_evidence.mjs', 'guard_bootstrap.mjs', 'preload.mjs', 'budget_guard.py', 'container_deadline.py', 'budget_guard.mjs', 'container_deadline.mjs', 'sealed_runtime.mjs', 'sealed_bash_env.sh', 'request_boundary.ts', 'checkpoint_observer.ts'):
                await environment.upload_file(Path(__file__).with_name(filename), evaluator+'/'+filename)
            if self.options.prepare_only:
                await environment.upload_file(Path(__file__).with_name('probe_request.mjs'),evaluator+'/probe_request.mjs')
                await environment.upload_file(Path(__file__).with_name('fixture_transport.ts'),evaluator+'/fixture_transport.ts')
            await self.upload_private(environment,json.dumps({'providers':{'deepseek':{
                'modelOverrides':{'deepseek-flash':{'samplingParams':{
                    'max_tokens':self.options.evaluation_output_tokens}}}}}}),profile+'/models.json')
        # No credential file is read or uploaded by preparation Jobs.
        if not self.options.prepare_only:
            auth = json.loads(Path(self.options.auth_path).read_text())
            if "deepseek" not in auth or auth["deepseek"].get("type") != "api_key":
                raise ValueError("an API-key DeepSeek private profile is required")
            if self.options.evaluation_deadline:
                await self.upload_private(environment,json.dumps({'deepseek':auth['deepseek']}),
                                          self._asset_root+'/evaluation/private-auth.json')
                auth={'deepseek':{'type':'api_key','key':'memweave-evaluation-guard-placeholder'}}
            await self.upload_private(
                environment, json.dumps({"deepseek": auth["deepseek"]}), profile + "/auth.json"
            )
        await self.upload_private(
            environment,
            json.dumps({"compaction": {"enabled": self.options.variant == "pi-native"}}),
            profile + "/settings.json",
        )
        container_identity=await self.exec_as_agent(environment,'cat /etc/hostname')
        setup = {
            'container_hostname':container_identity.stdout.strip(),
            "pi_version": self.options.version,
            "node_version": self.options.node_version,
            "variant": self.options.variant,
            "cwd": cwd,
            "prepare_only": self.options.prepare_only,
            "canary": self.options.evaluation_canary,
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
            f"additionalExtensionPaths:{json.dumps(([self._asset_root+'/evaluation/checkpoint_observer.ts'] if self.options.evaluation_deadline else []) + ([self.options.extension] if self.options.extension else []))}}});"
            "await loader.reload();const runtime=await sdk.ModelRuntime.create({"
            "authPath:agentDir+'/auth.json',modelsPath:agentDir+'/models.json',"
            "allowModelNetwork:false,refreshOnCreate:false});"
            f"const selectedModel={('runtime.getModel(\"deepseek\",\"deepseek-flash\")' if self.options.evaluation_deadline else 'null')};"
            f"if({json.dumps(bool(self.options.evaluation_deadline))} && !selectedModel)throw Error('Frozen model missing');"
            f"if(selectedModel && selectedModel.samplingParams?.max_tokens!=={self.options.evaluation_output_tokens})throw Error('Wrong frozen output override');"
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
            "model_requests:0,tools,embedding_dimensions:embedding,selected_model:selectedModel,"
            "session_id:session.sessionId,"
            "compaction:session.autoCompactionEnabled,system_prompt_sha256:"
            "createHash('sha256').update(session.systemPrompt).digest('hex')}));"
            "}finally{session.dispose();}"
        )
        await self.exec_as_agent(
            environment, "node --input-type=module -e " + shlex.quote(script), timeout_sec=180,
            env={'MEMWEAVE_EVAL_TRACE':'/logs/agent/preflight-observer.jsonl',
                 'MEMWEAVE_EVAL_PROGRESS_AFTER':str(self.options.evaluation_progress_after_returns)}
        )
        if self.options.evaluation_deadline:
            await check_network(environment,self._asset_root+'/node/bin/node',self.logs_dir)
            args=[self._asset_root+'/evaluation/probe_request.mjs',sdk,
                  self._experiment_home+'/.pi/agent',self.options.extension or '-',self.options.variant,
                  str(self.options.evaluation_output_tokens),self.options.smoke_barrier or '-']
            await self.exec_as_agent(environment,'node '+' '.join(shlex.quote(arg) for arg in args),
                timeout_sec=180,env={'MEMWEAVE_EVAL_TRACE':'/logs/agent/mock-request-trace.jsonl',
                                    'MEMWEAVE_EVAL_PROGRESS_AFTER':str(self.options.evaluation_progress_after_returns),
                                    'MEMWEAVE_EVAL_QUOTA_BACKEND':self.options.evaluation_quota_backend})
            await self.cli_transport_preflight(environment)

    async def cli_transport_preflight(self,environment):
        """Use the exact print CLI/dispatcher path; SDK-only probes cannot certify preloads."""
        evaluator=self._asset_root+'/evaluation'
        await self.upload_private(environment,json.dumps({'deepseek':{'type':'api_key','key':'fixture-only'}}),
                                  evaluator+'/private-auth.json')
        await self.upload_private(environment,json.dumps({'deepseek':{'type':'api_key','key':'memweave-evaluation-guard-placeholder'}}),
                                  self._experiment_home+'/.pi/agent/auth.json')
        with tempfile.TemporaryDirectory(prefix='memweave-cli-probe-') as directory:
            for name,value in (
                ('instruction.md','Verify offline CLI request conversion.'),
                ('quota.json',json.dumps({'schema_version':1,'maximum_usd':1.,'deadline':self.options.evaluation_deadline,
                                         'exposure_usd':0.,'requests':{},'arm_limits':{}})),
            ):
                local=Path(directory)/name;local.write_text(value)
                await environment.upload_file(local,evaluator+'/instruction.md' if name=='instruction.md' else '/logs/agent/cli-probe-quota.json')
        extension=(' --extension '+shlex.quote(self.options.extension)) if self.options.extension else ''
        command=('pi --print --mode json --provider deepseek --model deepseek-flash --thinking off '
                 '--session-dir /logs/agent/cli-probe/sessions'+extension+' '+shlex.quote('Verify offline CLI request conversion.'))
        await self.exec_as_agent(environment,command,timeout_sec=120)
        validate="""import fs from 'node:fs';
const e=fs.readFileSync('/logs/agent/cli-request-trace.jsonl','utf8').trim().split('\\n').map(JSON.parse);
const a=e.filter(x=>x.event==='http_attempt'),s=e.filter(x=>x.event==='budget_settled');
if(a.length!==EXPECTED || s.length!==EXPECTED)throw Error('CLI guard missing or not settled');
if(e.some(x=>x.event==='sealed_tool_rejected'))throw Error('Harmless query rejected');
fs.renameSync('/logs/agent/cli-request-trace.jsonl','/logs/agent/cli-positive-trace.jsonl');
fs.renameSync('/logs/agent/cli-fake-upstream.jsonl','/logs/agent/cli-positive-upstream.jsonl');
""".replace('EXPECTED',str((2 if self.options.variant=='pi-memweave' else 1)+(1 if self._evaluation_sealed else 0)))
        await self.exec_as_agent(environment,'node --input-type=module -e '+shlex.quote(validate),timeout_sec=20)
        if self._evaluation_sealed:
            await self.exec_as_agent(environment,command,timeout_sec=120,env={'MEMWEAVE_EVAL_EXECUTION_NEGATIVE':'1'})
            check="import fs from 'node:fs';const e=fs.readFileSync('/logs/agent/cli-request-trace.jsonl','utf8').trim().split('\\n').map(JSON.parse);if(!e.some(x=>x.event==='sealed_tool_rejected'&&x.executables?.includes('injected-runtime')))throw Error('Actual interpreter execution not rejected');fs.renameSync('/logs/agent/cli-request-trace.jsonl','/logs/agent/cli-execution-negative-trace.jsonl');fs.rmSync('/logs/agent/cli-fake-upstream.jsonl',{force:true});"
            await self.exec_as_agent(environment,'node --input-type=module -e '+shlex.quote(check),timeout_sec=20)
            negative=await self.exec_as_agent(environment,command+' || true',timeout_sec=120,
                env={'MEMWEAVE_EVAL_COMPRESSED_FIXTURE_NEGATIVE':'1'})
            if 'Codec unavailable in sealed evaluation runtime' not in ((negative.stdout or '')+(negative.stderr or '')):
                raise ValueError('compressed real-HTTP CLI negative did not reproduce codec isolation')
            await self.exec_as_agent(environment,"mv /logs/agent/cli-request-trace.jsonl /logs/agent/cli-compression-negative-trace.jsonl; rm -f /logs/agent/cli-fake-upstream.jsonl",timeout_sec=20)
        await self.exec_as_agent(environment,command+' || true',timeout_sec=120,
                                 env={'MEMWEAVE_EVAL_DROP_GUARD':'1'})
        negative="""import fs from 'node:fs';
const e=fs.readFileSync('/logs/agent/cli-request-trace.jsonl','utf8').trim().split('\\n').map(JSON.parse);
if(!e.some(x=>x.event==='guard_lost') || e.some(x=>x.event==='http_attempt') ||
fs.existsSync('/logs/agent/cli-fake-upstream.jsonl'))throw Error('Guard loss did not fail closed');
fs.renameSync('/logs/agent/cli-request-trace.jsonl','/logs/agent/cli-negative-trace.jsonl');
"""
        await self.exec_as_agent(environment,'node --input-type=module -e '+shlex.quote(negative),timeout_sec=20)
        await self.exec_as_agent(environment,command+' || true',timeout_sec=15,
            env={'MEMWEAVE_EVAL_HANG_FIXTURE':'1','MEMWEAVE_EVAL_LOCAL_STOP_AFTER':'2'})
        terminated="""import fs from 'node:fs';
const e=fs.readFileSync('/logs/agent/cli-request-trace.jsonl','utf8').trim().split('\\n').map(JSON.parse);
if(!e.some(x=>x.event==='local_deadline_stop'))throw Error('CLI PID deadline not enforced');
fs.writeFileSync('/logs/agent/cli-transport-result.json',JSON.stringify({real_model_requests:0,
positive:true,lost_guard_upstream_requests:0,actual_cli_pid_deadline:true}));
"""
        await self.exec_as_agent(environment,'node --input-type=module -e '+shlex.quote(terminated),timeout_sec=20)

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
            if self.options.evaluation_deadline:
                evaluator = self._asset_root + '/evaluation'
                extensions=('--extension '+shlex.quote(evaluator+'/fixture_transport.ts')+' ' if self.options.prepare_only else '')
                command = command.replace('pi --print --mode json', 'pi --print --mode json '+extensions+'--extension '
                                          +shlex.quote(evaluator+'/checkpoint_observer.ts'))
                kwargs['env'].update(
                    NODE_OPTIONS='--import '+evaluator+'/preload.mjs',
                    MEMWEAVE_EVAL_LEDGER='/logs/agent/cli-probe-quota.json' if self.options.prepare_only else '/opt/memweave-eval-control/quota.json',
                    MEMWEAVE_EVAL_TRACE='/logs/agent/cli-request-trace.jsonl' if self.options.prepare_only else '/logs/agent/request-trace.jsonl',
                    MEMWEAVE_EVAL_DEADLINE=str(getattr(self,'_evaluation_effective_deadline',self.options.evaluation_deadline)),
                    MEMWEAVE_EVAL_VARIANT=self.options.variant,
                    MEMWEAVE_EVAL_QUOTA_BACKEND=self.options.evaluation_quota_backend,
                    MEMWEAVE_EVAL_BUDGET_ARM=(self._evaluation_task_id+':'+self.options.variant) if self.options.evaluation_per_task_arms else self.options.variant,
                    MEMWEAVE_EVAL_SEALED='1' if self._evaluation_sealed else '0',
                    MEMWEAVE_EVAL_POLICY_FILE=evaluator+'/sealed_bash_env.sh',
                    MEMWEAVE_EVAL_ASSET_ROOT=self._asset_root,
                    MEMWEAVE_EVAL_WORKSPACE=json.dumps(self._evaluation_task_config.get('workspace',{})),
                    MEMWEAVE_EVAL_MAX_OUTPUT=str(self.options.evaluation_output_tokens),
                    MEMWEAVE_EVAL_RUN_ID=self.options.evaluation_run_id or 'unknown',
                    MEMWEAVE_EVAL_PROGRESS_AFTER=str(self.options.evaluation_progress_after_returns),
                    MEMWEAVE_EVAL_INSTRUCTION_PATH=evaluator+'/instruction.md',
                    MEMWEAVE_EVAL_CREDENTIAL_FILE=evaluator+'/private-auth.json',
                    MEMWEAVE_EVAL_REQUEST_LIMIT=str(self.options.evaluation_request_limit or 0),
                    MEMWEAVE_EVAL_EPISODE_BUDGET=str(self.options.evaluation_episode_budget or 0),
                    MEMWEAVE_EVAL_CONTENT_STORE='/logs/agent/request-content' if self.options.evaluation_content_evidence else '',
                )
                if self.options.prepare_only and kwargs['env'].get('MEMWEAVE_EVAL_LOCAL_STOP_AFTER'):
                    kwargs['env']['MEMWEAVE_EVAL_DEADLINE']=str(time.time()+float(kwargs['env']['MEMWEAVE_EVAL_LOCAL_STOP_AFTER']))
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
            if self.options.evaluation_canary:
                instruction='Reply only OK. Do not call any tools. This is a connectivity canary.'
            timeout=self.options.evaluation_task_timeouts.get(self._evaluation_task_id)
            if timeout and not self.options.evaluation_canary:
                self._evaluation_effective_deadline=min(self.options.evaluation_deadline,time.time()+timeout)
                instruction+=('\n\nEvaluation budget notice (identical policy for both arms): '
                    f'the effective agent execution budget is {timeout} seconds ({timeout/3600:g} hours), '
                    'with 2 CPUs and 8192 MiB memory. This notice supersedes any larger time budget in the original statement. '
                    'Run bash /app/timer.sh for actual remaining time. The external model cutoff is '
                    +datetime.fromtimestamp(self.options.evaluation_deadline,UTC).isoformat()+'.')
                script=('#!/bin/bash\n'+f'DEADLINE={int(self._evaluation_effective_deadline)}\n'+
                    'NOW=$(date +%s)\nREMAINING=$((DEADLINE-NOW))\n[ "$REMAINING" -gt 0 ] || REMAINING=0\n'+
                    'printf "Remaining agent seconds: %s\\n" "$REMAINING"\n')
                await self.exec_as_agent(environment,'cp /app/timer.sh /logs/agent/original-timer.sh')
                await self.upload_private(environment,script,'/app/timer.sh')
                (self.logs_dir/'effective-budget.json').write_text(json.dumps({'seconds':timeout,
                    'deadline_unix':self._evaluation_effective_deadline,'notice':instruction.split('Evaluation budget notice',1)[1]}))
            if self.options.evaluation_deadline:
                with tempfile.TemporaryDirectory(prefix='memweave-eval-instruction-') as directory:
                    local=Path(directory)/'instruction.md'
                    local.write_text(instruction)
                    await environment.upload_file(local,self._asset_root+'/evaluation/instruction.md')
            if self.options.protocol in ("swe-pro-v2", "swe-marathon"):
                await check_network(environment, self._asset_root + "/node/bin/node", self.logs_dir)
            await super().run(instruction, environment, context)
        finally:
            if getattr(self,'_evaluation_sealed',False):
                capture="tar -czf /logs/agent/model-source-original.tar.gz -C /app src"
                result=await environment.exec(command=capture,user='root',timeout_sec=120)
                if result.return_code: raise RuntimeError('Sealed source evidence archive failed')
                try:
                    await self.exec_as_agent(environment,'node '+shlex.quote(self._asset_root+'/evaluation/sealed_runtime.mjs')+
                        ' /app/src /logs/agent/sealed-handoff.json',timeout_sec=120)
                except Exception as error:
                    raise RuntimeError('ADAPTER_HANDOFF_FAILED: see sealed-handoff.json; not an Agent business score') from error
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
