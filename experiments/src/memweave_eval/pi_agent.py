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
from pydantic import model_validator

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
    evaluation_primary_default: bool = False
    evaluation_broker_client: str | None = None
    evaluation_broker_client_sha256: str | None = None
    evaluation_output_tokens: int = 16384
    evaluation_quota_backend: Literal["python", "node"] = "python"
    evaluation_per_task_arms: bool = False
    # PiOptions is a Pydantic model; mutable field defaults are copied per instance.
    evaluation_task_ids: list[str] = []  # noqa: RUF012
    evaluation_run_id: str | None = None
    smoke_barrier: str | None = None
    evaluation_canary: bool = False
    evaluation_request_limit: int | None = None
    evaluation_episode_budget: float | None = None
    runtime_plan: str | None = None
    runtime_plan_sha256: str | None = None
    prepare_only: bool = False
    runtime_objects: dict[str, dict] | None = None
    extension: Annotated[str | None, Cli("--extension")] = None

    @model_validator(mode="after")
    def primary_defaults(self):
        if self.evaluation_primary_default and (self.thinking is not None or self.evaluation_output_tokens!=384000):
            raise ValueError('primary_default forbids sampling overrides')
        return self


def profile_configurations(options):
    """Sampling and compaction are owned by Pi/product in primary-default runs."""
    if options.evaluation_primary_default:return {}
    files={'settings.json':{'compaction':{'enabled':options.variant=='pi-native'}}}
    if options.evaluation_deadline:
        files['models.json']={'providers':{'deepseek':{'modelOverrides':{'deepseek-flash':{
            'samplingParams':{'max_tokens':options.evaluation_output_tokens}}}}}}
    return files


def product_initialization_script(package,profile,cwd):
    """Use the installed product's setup transaction, not evaluator-owned defaults.

    Only called in a fresh isolated experiment home. It never touches the host Pi
    profile. This represents the initialized enabled product in headless runs.
    """
    # The installed package has peer dependencies supplied by the host. Load it
    # through Pi's public resource loader, which resolves those peers; direct
    # Node imports do not reproduce the supported package-loading path.
    initializer=(
        f"import {{completeSetup}}from {json.dumps(package+'/src/storage/setup.ts')};"
        f"import {{memoryPaths}}from {json.dumps(package+'/src/storage/paths.ts')};"
        f"import {{loadDefaultRule,loadPackageVersion,disableGlobalCompaction}}from {json.dumps(package+'/src/pi/setup-settings.ts')};"
        "export default function(pi){pi.on('session_start',async()=>{const paths=memoryPaths();"
        f"await completeSetup(paths,{json.dumps(profile)},loadDefaultRule,"
        f"()=>disableGlobalCompaction({json.dumps(cwd)},{json.dumps(profile)}),await loadPackageVersion());"
        "});}"
    )
    sdk=package.rsplit('/',1)[0]+'/node/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js'
    entry=package.rsplit('/',1)[0]+'/product-initializer.ts'
    return (
        f"await fs.writeFile({json.dumps(entry)},{json.dumps(initializer)});"
        f"const sdk=await import({json.dumps(sdk)});"
        f"const settings=sdk.SettingsManager.create({json.dumps(cwd)},{json.dumps(profile)});"
        f"const loader=new sdk.DefaultResourceLoader({{cwd:{json.dumps(cwd)},agentDir:{json.dumps(profile)},settingsManager:settings,additionalExtensionPaths:[{json.dumps(entry)}]}});"
        "await loader.reload();"
        f"const runtime=await sdk.ModelRuntime.create({{authPath:{json.dumps(profile+'/auth.json')},modelsPath:{json.dumps(profile+'/models.json')},allowModelNetwork:false,refreshOnCreate:false}});"
        f"const {{session,extensionsResult}}=await sdk.createAgentSession({{cwd:{json.dumps(cwd)},agentDir:{json.dumps(profile)},settingsManager:settings,resourceLoader:loader,modelRuntime:runtime,model:runtime.getModel('deepseek','deepseek-flash')}});"
        "try{const errors=[];await session.bindExtensions({onError:e=>errors.push(e.error)});"
        "if(errors.length||extensionsResult.errors.length)throw Error('Product initialization failed');}finally{session.dispose();}"
        f"await fs.rm({json.dumps(entry)});"
    )


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
                    + (product_initialization_script(self._asset_root+'/package',profile,cwd)if self.options.evaluation_primary_default else
                       f"await fs.copyFile({json.dumps(self._asset_root + '/package/resources/rule.md')},paths.rule);")
                ),
                timeout_sec=120,
            )
            self.options.extension = self._asset_root + "/package/src/extension/index.ts"

        await self.exec_as_agent(environment, f"mkdir -p {shlex.quote(profile)}")
        if self.options.evaluation_deadline:
            evaluator = self._asset_root + '/evaluation'
            await self.exec_as_agent(environment, f'mkdir -p {shlex.quote(evaluator)}')
            for filename in ('fetch_guard.mjs', 'broker_client.mjs', 'guard_bootstrap.mjs', 'preload.mjs', 'budget_guard.py', 'container_deadline.py', 'budget_guard.mjs', 'container_deadline.mjs', 'checkpoint_observer.ts'):
                await environment.upload_file(Path(__file__).with_name(filename), evaluator+'/'+filename)
            if self.options.prepare_only:
                await environment.upload_file(Path(__file__).with_name('probe_request.mjs'),evaluator+'/probe_request.mjs')
                await environment.upload_file(Path(__file__).with_name('fixture_transport.ts'),evaluator+'/fixture_transport.ts')
                await environment.upload_file(Path(__file__).with_name('broker_guardloss.ts'),evaluator+'/broker_guardloss.ts')
            for name,value in profile_configurations(self.options).items():
                if name=='models.json':await self.upload_private(environment,json.dumps(value),profile+'/'+name)
        # The Actor receives only a scoped broker capability and a provider placeholder.
        # Provider credentials are never read here, even by a non-primary paid Job.
        if self.options.evaluation_broker_client:
            source=Path(self.options.evaluation_broker_client)
            if not self.options.evaluation_deadline or file_digest(source)!=self.options.evaluation_broker_client_sha256:
                raise ValueError('trusted broker client identity missing or changed')
            client=json.loads(source.read_text())
            if set(client)!={'url','capability','arm','episode'}or any(not isinstance(v,str)or not v for v in client.values()):
                raise ValueError('only scoped transport capability fields may enter Actor')
            await self.upload_private(environment,json.dumps(client),self._asset_root+'/evaluation/broker-client.json')
        if not self.options.prepare_only or self.options.evaluation_broker_client:
            if not self.options.evaluation_broker_client:
                raise ValueError('paid Actor requires credential-isolated bounded transport authority')
            auth={'deepseek':{'type':'api_key','key':'memweave-evaluation-guard-placeholder'}}
            await self.upload_private(
                environment, json.dumps({"deepseek": auth["deepseek"]}), profile + "/auth.json"
            )
        for name,value in profile_configurations(self.options).items():
            if name=='settings.json':await self.upload_private(environment,json.dumps(value),profile+'/'+name)
        container_identity=await self.exec_as_agent(environment,'cat /etc/hostname')
        setup = {
            'container_hostname':container_identity.stdout.strip(),
            "pi_version": self.options.version,
            "node_version": self.options.node_version,
            "variant": self.options.variant,
            "cwd": cwd,
            "prepare_only": self.options.prepare_only,
            "canary": self.options.evaluation_canary,
            "primary_default":self.options.evaluation_primary_default,
            "provider_credentials_in_actor":False,
            "external_transport_authority":bool(self.options.evaluation_broker_client),
            "profile_files_written_by_evaluator":list(profile_configurations(self.options)),
            "product_initialization":'installed completeSetup / loadDefaultRule / disableGlobalCompaction'if self.options.evaluation_primary_default and self.options.variant=='pi-memweave'else None,
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
            f"if(selectedModel && !{json.dumps(self.options.evaluation_primary_default)} && selectedModel.samplingParams?.max_tokens!=={self.options.evaluation_output_tokens})throw Error('Wrong frozen output override');"
            + ("if(await fs.stat(agentDir+'/models.json').then(()=>true,()=>false))throw Error('primary_default model override found');"if self.options.evaluation_primary_default else"")
            +
            "const {session,extensionsResult}=await sdk.createAgentSession({agentDir,resourceLoader:loader,"
            "settingsManager:settings,modelRuntime:runtime,...(selectedModel?{model:selectedModel}:{})});"
            "try{const errors=[];await session.bindExtensions({onError:e=>errors.push(String(e.message||e))});"
            + ("const auth=JSON.parse(await fs.readFile(agentDir+'/auth.json','utf8'));"
               "if(auth.deepseek?.key!=='memweave-evaluation-guard-placeholder')throw Error('Actor provider credential is not placeholder');"
               f"if(await fs.stat({json.dumps(self._asset_root+'/evaluation/private-auth.json')}).then(()=>true,()=>false))throw Error('Provider auth file found in Actor');"
               if self.options.evaluation_broker_client else"")
            +
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
            "session_id:session.sessionId,thinking_level:session.thinkingLevel,"
            "settings_thinking_default:settings.getDefaultThinkingLevel()??null,"
            "model_overrides_present:await fs.stat(agentDir+'/models.json').then(()=>true,()=>false),"
            f"credential_isolation_checked:{json.dumps(bool(self.options.evaluation_broker_client))},"
            "compaction:session.autoCompactionEnabled,system_prompt_sha256:"
            "createHash('sha256').update(session.systemPrompt).digest('hex')}));"
            "}finally{session.dispose();}"
        )
        await self.exec_as_agent(
            environment, "node --input-type=module -e " + shlex.quote(script), timeout_sec=180,
            env={'MEMWEAVE_EVAL_TRACE':'/logs/agent/preflight-observer.jsonl'}
        )
        if self.options.evaluation_deadline:
            await check_network(environment,self._asset_root+'/node/bin/node',self.logs_dir,
                general_internet_allowed=environment.network_policy.network_mode.value=='public' if self.options.evaluation_primary_default else False)
            args=[self._asset_root+'/evaluation/probe_request.mjs',sdk,
                  self._experiment_home+'/.pi/agent',self.options.extension or '-',self.options.variant,
                  'default'if self.options.evaluation_primary_default else str(self.options.evaluation_output_tokens),self.options.smoke_barrier or '-']
            await self.exec_as_agent(environment,'node '+' '.join(shlex.quote(arg) for arg in args),
                timeout_sec=180,env={'MEMWEAVE_EVAL_TRACE':'/logs/agent/mock-request-trace.jsonl',
                                    'MEMWEAVE_EVAL_QUOTA_BACKEND':self.options.evaluation_quota_backend})
            await self.cli_transport_preflight(environment)

    async def cli_transport_preflight(self,environment):
        """Use the exact print CLI/dispatcher path; SDK-only probes cannot certify preloads."""
        if self.options.evaluation_broker_client:return await self.broker_cli_preflight(environment)
        if self.options.evaluation_primary_default:raise ValueError('primary CLI preflight requires external credential authority')
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
        command=('pi --print --mode json --provider deepseek --model deepseek-flash '+(''if self.options.evaluation_primary_default else'--thinking off ')
                 +'--session-dir /logs/agent/cli-probe/sessions'+extension+' '+shlex.quote('Verify offline CLI request conversion.'))
        await self.exec_as_agent(environment,command,timeout_sec=120)
        validate="""import fs from 'node:fs';
const e=fs.readFileSync('/logs/agent/cli-request-trace.jsonl','utf8').trim().split('\\n').map(JSON.parse);
const a=e.filter(x=>x.event==='http_attempt'),s=e.filter(x=>x.event==='budget_settled');
if(a.length!==EXPECTED || s.length!==EXPECTED)throw Error('CLI guard missing or not settled');
if(e.some(x=>x.event==='sealed_tool_rejected'))throw Error('Harmless query rejected');
fs.renameSync('/logs/agent/cli-request-trace.jsonl','/logs/agent/cli-positive-trace.jsonl');
fs.renameSync('/logs/agent/cli-fake-upstream.jsonl','/logs/agent/cli-positive-upstream.jsonl');
""".replace('EXPECTED',str(2 if self.options.variant=='pi-memweave' else 1))
        await self.exec_as_agent(environment,'node --input-type=module -e '+shlex.quote(validate),timeout_sec=20)
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

    async def broker_cli_preflight(self,environment):
        evaluator=self._asset_root+'/evaluation'
        await self.upload_private(environment,'Verify offline external-authority conversion.',evaluator+'/instruction.md')
        extension=(' --extension '+shlex.quote(self.options.extension))if self.options.extension else''
        prefix='pi --print --mode json --provider deepseek --model deepseek-flash --session-dir /logs/agent/broker-cli/sessions'+extension+' '
        await self.exec_as_agent(environment,prefix+shlex.quote('Verify offline external-authority conversion.'),timeout_sec=120)
        positive="""import fs from 'node:fs';const events=fs.readFileSync('/logs/agent/cli-request-trace.jsonl','utf8').trim().split('\\n').map(JSON.parse);
const attempts=events.filter(e=>e.event==='http_attempt'),ends=events.filter(e=>e.event==='request_end');
if(attempts.length!==EXPECTED||ends.length!==EXPECTED||ends.some(e=>!e.settled))throw Error('External-authority CLI positive failed');
fs.renameSync('/logs/agent/cli-request-trace.jsonl','/logs/agent/cli-positive-trace.jsonl');
if(fs.existsSync('PRIVATE'))throw Error('Provider credential file present in Actor');
""".replace('EXPECTED',str(3 if self.options.variant=='pi-memweave'else 2)).replace('PRIVATE',evaluator+'/private-auth.json')
        await self.exec_as_agent(environment,'node --input-type=module -e '+shlex.quote(positive),timeout_sec=20)
        await self.exec_as_agent(environment,prefix+shlex.quote('Guard-loss connectivity fixture.')+' || true',timeout_sec=20,env={'MEMWEAVE_EVAL_GUARDLOSS_FIXTURE':'1'})
        negative="""import fs from 'node:fs';const events=fs.readFileSync('/logs/agent/cli-request-trace.jsonl','utf8').trim().split('\\n').map(JSON.parse);
if(!events.some(e=>e.event==='guard_lost')||events.some(e=>e.event==='http_attempt')||fs.existsSync('/logs/agent/unguarded-dispatch.jsonl'))throw Error('External guard loss dispatched');
fs.renameSync('/logs/agent/cli-request-trace.jsonl','/logs/agent/cli-negative-trace.jsonl');"""
        await self.exec_as_agent(environment,'node --input-type=module -e '+shlex.quote(negative),timeout_sec=20)
        await self.exec_as_agent(environment,prefix+shlex.quote('HANG-TRANSPORT-FIXTURE')+' || true',timeout_sec=15,env={'MEMWEAVE_EVAL_LOCAL_STOP_AFTER':'2'})
        terminated="""import fs from 'node:fs';const events=fs.readFileSync('/logs/agent/cli-request-trace.jsonl','utf8').trim().split('\\n').map(JSON.parse);
if(!events.some(e=>e.event==='local_deadline_stop'))throw Error('External transport PID deadline missing');
fs.writeFileSync('/logs/agent/cli-transport-result.json',JSON.stringify({real_model_requests:0,positive:true,lost_guard_upstream_requests:0,actual_cli_pid_deadline:true,provider_credentials_in_actor:false,external_authority:true}));"""
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
                extensions=('--extension '+shlex.quote(evaluator+'/fixture_transport.ts')+' ' if self.options.prepare_only and not self.options.evaluation_broker_client else '')
                if self.options.prepare_only and kwargs.get('env',{}).get('MEMWEAVE_EVAL_GUARDLOSS_FIXTURE'):
                    extensions+='--extension '+shlex.quote(evaluator+'/broker_guardloss.ts')+' '
                command = command.replace('pi --print --mode json', 'pi --print --mode json '+extensions+'--extension '
                                          +shlex.quote(evaluator+'/checkpoint_observer.ts'))
                kwargs['env'].update(
                    NODE_OPTIONS='--import '+evaluator+'/preload.mjs',
                    MEMWEAVE_EVAL_LEDGER='/logs/agent/cli-probe-quota.json' if self.options.prepare_only else '/opt/memweave-eval-control/quota.json',
                    MEMWEAVE_EVAL_TRACE='/logs/agent/cli-request-trace.jsonl' if self.options.prepare_only else '/logs/agent/request-trace.jsonl',
                    MEMWEAVE_EVAL_DEADLINE=str(self.options.evaluation_deadline),
                    MEMWEAVE_EVAL_VARIANT=self.options.variant,
                    MEMWEAVE_EVAL_QUOTA_BACKEND=self.options.evaluation_quota_backend,
                    MEMWEAVE_EVAL_BROKER_CONFIG=evaluator+'/broker-client.json'if self.options.evaluation_broker_client else '',
                    MEMWEAVE_EVAL_PRIMARY_DEFAULT='1'if self.options.evaluation_primary_default else '0',
                    MEMWEAVE_EVAL_BUDGET_ARM=(self._evaluation_task_id+':'+self.options.variant) if self.options.evaluation_per_task_arms else self.options.variant,
                    MEMWEAVE_EVAL_ASSET_ROOT=self._asset_root,
                    MEMWEAVE_EVAL_MAX_OUTPUT=str(self.options.evaluation_output_tokens),
                    MEMWEAVE_EVAL_RUN_ID=self.options.evaluation_run_id or 'unknown',
                    MEMWEAVE_EVAL_INSTRUCTION_PATH=evaluator+'/instruction.md',
                    MEMWEAVE_EVAL_CREDENTIAL_FILE=''if self.options.evaluation_broker_client else evaluator+'/private-auth.json',
                    MEMWEAVE_EVAL_REQUEST_LIMIT=str(self.options.evaluation_request_limit or 0),
                    MEMWEAVE_EVAL_EPISODE_BUDGET=str(self.options.evaluation_episode_budget or 0),
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
            if self.options.evaluation_deadline:
                with tempfile.TemporaryDirectory(prefix='memweave-eval-instruction-') as directory:
                    local=Path(directory)/'instruction.md'
                    local.write_text(instruction)
                    await environment.upload_file(local,self._asset_root+'/evaluation/instruction.md')
            if self.options.protocol in ("swe-pro-v2", "swe-marathon"):
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
