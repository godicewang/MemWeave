"""Original-benchmark preparation and isolated Harbor backend for RSI.

No credential is read by catalog/plan/prepare. Paid execution is an explicit
separate entry and retains the existing trusted quota authority's limits.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import time
import tomllib
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, model_validator

from .actor_adapter import RSI_PI, ActorAdapter
from .rsi_catalog import load_catalog, validate_catalog
from .rsi_policy import active_history_seconds, is_active_policy, policy_for_catalog
from .rsi_resources import ResourceAmounts, ResourcePolicy
from .rsi_scheduler import (
    ExperimentScheduler,
    TaskIdentity,
    VariantIdentity,
    qualified_basis_tasks,
)
from .spec import Model, Runtime, StrictModel, Subject, load_yaml, outside_repository
from .storage import atomic_json, file_digest
from .suites import task_digest


class RSIConfig(StrictModel):
    schema_version: Literal[1] = 1
    id: Annotated[str, Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$')]
    catalog: Path
    grouping_path: Path | None = None
    source_cache: Path
    root: Path
    subject: Subject
    runtime: Runtime
    model: Model = Field(default_factory=lambda: Model(id='deepseek-flash'))
    concurrency: Annotated[int, Field(strict=True, ge=1)] = 20
    resources: ResourcePolicy = Field(default_factory=ResourcePolicy)
    max_attempts: Annotated[int, Field(strict=True, ge=1, le=3)] = 3
    platform: Literal['linux/amd64'] = 'linux/amd64'
    unbounded: bool = False
    max_cost_usd: Annotated[float, Field(strict=True, gt=0, le=29)] | None = None
    max_elapsed_seconds: Annotated[int, Field(strict=True, ge=1)] | None = None

    @model_validator(mode='after')
    def boundaries(self):
        if self.unbounded and (self.max_cost_usd is not None or self.max_elapsed_seconds is not None):
            raise ValueError("unbounded mode must not also define aggregate limits")
        self.root = outside_repository(self.root)
        self.source_cache = outside_repository(self.source_cache)
        if self.model.id != 'deepseek-flash' or self.model.thinking is not None:
            raise ValueError('current trusted transport supports unmodified deepseek-flash defaults')
        return self


def _catalog(spec):
    return (load_catalog(spec.catalog, grouping_path=spec.grouping_path)
            if spec.grouping_path is not None else load_catalog(spec.catalog))


def _validate_catalog(spec, catalog):
    return (validate_catalog(catalog, spec.source_cache, grouping_path=spec.grouping_path)
            if spec.grouping_path is not None else validate_catalog(catalog, spec.source_cache))


def evaluator_digest() -> str:
    """Freeze evaluator/transport code as part of the comparison contract."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.iterdir()):
        if path.is_file() and path.suffix in {'.py', '.mjs', '.ts', '.sh'}:
            digest.update(path.name.encode()+b'\0')
            digest.update(bytes.fromhex(file_digest(path)))
    return digest.hexdigest()


def load_config(path: Path) -> RSIConfig:
    path = path.resolve()
    raw = load_yaml(path)
    for field in ('catalog', 'source_cache', 'root'):
        raw[field] = (path.parent / Path(raw[field]).expanduser()).resolve()
    raw['subject']['package'] = (
        path.parent / Path(raw['subject']['package']).expanduser()).resolve()
    return RSIConfig.model_validate(raw)


def source_paths(spec: RSIConfig, catalog: dict) -> dict[tuple[str, str], Path]:
    sources = {s['id']: s for s in catalog['sources']}
    return {(row['suite_id'], row['task_id']): spec.source_cache /
            f"{row['suite_id']}-{sources[row['suite_id']]['revision']}" / row['original_path']
            for row in catalog['tasks']}


def allocations(paths: dict) -> list[dict]:
    """Count original actor and separate-verifier resources, never adapt them."""
    from harbor.models.task.config import TaskConfig
    from harbor.models.task.paths import TaskPaths
    from harbor.models.task.verifier_mode import resolve_verifier_environment_definition

    result = []
    for key, path in paths.items():
        cfg = TaskConfig.model_validate_toml((path / 'task.toml').read_text())
        verifier = resolve_verifier_environment_definition(cfg, TaskPaths(path))
        envs = [cfg.environment] + ([verifier.config] if verifier else [])
        # Separate verifier may overlap teardown: reserve the sum, not a guessed peak.
        result.append({'task_id': '/'.join(key), **{
            field: sum(getattr(env, field) for env in envs)
            for field in ('cpus', 'memory_mb', 'storage_mb')}})
    return result


def tool_env(spec: RSIConfig, catalog: dict) -> dict:
    names = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TERM', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
    env = {name: os.environ[name] for name in names if name in os.environ}
    tools = Path.home() / '.local/share/memweave-experiments/tools'
    env['PATH'] = os.pathsep.join([str(tools/'native/bin'), str(tools/'bin'), env.get('PATH', '')])
    env['DOCKER_HOST'] = 'unix://' + str(Path.home()/'.colima/memweave-eval/docker.sock')
    env['DOCKER_CONFIG'] = str(tools/'docker-config')
    source = next(s for s in catalog['sources'] if s['id'] == 'swe-bench-pro-v2')
    env['PYTHONPATH'] = os.pathsep.join([
        str(Path(__file__).resolve().parents[1]),
        str(spec.source_cache/f"{source['id']}-{source['revision']}"/'v2/tooling')])
    env.update(HARBOR_TELEMETRY='0', DO_NOT_TRACK='1', PYTHONDONTWRITEBYTECODE='1')
    return env


def binary_outcome(raw: dict) -> str:
    if raw.get('exception_info'):
        return 'error'
    reward = (raw.get('verifier_result') or {}).get('rewards', {}).get('reward')
    if type(reward) not in (int, float) or reward not in (0, 1):
        return 'error'
    return 'passed' if reward == 1 else 'failed'


def attempt_usage(ledger: dict, episode: str, arm: str) -> tuple[int | None, int | None]:
    records = [r for r in ledger['requests'].values()
               if r.get('episode') == episode and r.get('arm') == arm]
    if any(r.get('status') != 'settled' or
           any(type(r.get(k)) is not int or r[k] < 0 for k in ('input', 'output'))
           for r in records):
        return None, None
    return sum(r['input'] for r in records), sum(r['output'] for r in records)


def build_single_job(spec: RSIConfig, root: Path, name: str, task: Path, protocol: str, *,
                     variant: str | None = None, runtime_plan: Path | None = None,
                     runtime_objects: dict | None = None, prepare_only: bool = False,
                     runtime_cache_read_only: bool = False, asset_only: bool = False,
                     control: str | None = None, source_job: Path | None = None,
                     broker_client: Path | None = None, deadline: float | None = None,
                     elapsed_clock: dict | None = None, adapter: ActorAdapter = RSI_PI) -> dict:
    if asset_only and (not prepare_only or variant != 'pi-memweave' or control or source_job
                       or broker_client or deadline is not None or elapsed_clock is not None or runtime_cache_read_only):
        raise ValueError('asset-only job forbids model/control authority')
    if control:
        agent = {'name': control}
    elif source_job:
        agent = {'import_path': 'patch_replay:PatchReplayAgent', 'model_name': 'replay',
                 'kwargs': {'source_job': str(source_job)}}
    else:
        options = {'version': spec.runtime.pi_version, 'node_version': spec.runtime.node_version,
                       'variant': variant, 'package_path': str(spec.subject.package),
                       'package_sha256': spec.subject.sha256, 'auth_path': '', 'protocol': protocol,
                       'runtime_plan': str(runtime_plan),
                       'runtime_plan_sha256': file_digest(runtime_plan)
                       if runtime_plan and runtime_plan.is_file() else None,
                       'runtime_objects': runtime_objects, 'prepare_only': prepare_only,
                       'runtime_cache_read_only': runtime_cache_read_only,
                       'evaluation_primary_default': True, 'evaluation_output_tokens': 384000,
                       # Private frozen Node supports actor watchdog and independent mock.
                       # Real quota admission remains exclusively in the external broker.
                       'evaluation_quota_backend': 'node'}
        if asset_only:
            options['asset_only'] = True
        if broker_client:
            options.update(evaluation_broker_client=str(broker_client),
                           evaluation_broker_client_sha256=file_digest(broker_client),
                           evaluation_deadline=deadline, evaluation_run_id=root.name,
                           **({'evaluation_elapsed_clock': elapsed_clock} if elapsed_clock is not None else {}))
        agent = adapter.agent('deepseek/deepseek-flash', options,
                             allowed_hosts=['memweave-broker.internal'] if broker_client else [])
    cfg = {'job_name': name, 'jobs_dir': str(root/'harbor'), 'n_attempts': 1,
           'n_concurrent_trials': 1, 'quiet': True, 'retry': {'max_retries': 0},
           'environment': {'type': 'docker', 'delete': True}, 'agents': [agent],
           'tasks': [{'path': str(task)}]}
    if asset_only:
        cfg['install_only'] = True
    if prepare_only or (protocol == 'swe-pro-v2' and not control and source_job is None):
        cfg['verifier'] = {'disable': True}
    if prepare_only:
        cfg['agents'][0].update(override_setup_timeout_sec=3600, override_timeout_sec=240)
    return cfg


def actor_uses_egress(config: dict, task: Path) -> bool:
    """Match Harbor0.24 actor-environment phase selection without starting Docker."""
    from harbor.models.job.config import JobConfig
    from harbor.models.task.config import NetworkMode, TaskConfig, TaskOS
    from harbor.models.task.verifier_mode import (
        resolve_step_verifier_mode,
        resolve_task_verifier_mode,
    )
    from harbor.trial.network_policy import resolve_trial_network_plan

    job = JobConfig.model_validate(config)
    if len(job.agents) != 1 or job.environment.type.value != 'docker':
        raise ValueError('broker attachment requires one Docker agent')
    original = TaskConfig.model_validate_toml((Path(task)/'task.toml').read_text())
    if original.environment.os != TaskOS.LINUX:
        raise ValueError('broker attachment is validated only for Linux')
    policies = []
    for step in original.steps or [None]:
        mode = (resolve_step_verifier_mode(original, step) if step is not None
                else resolve_task_verifier_mode(original))
        plan = resolve_trial_network_plan(original, job.agents[0], job.environment,
                                          step, verifier_mode=mode)
        policies.extend([plan.agent_env_baseline, plan.agent_phase])
        if plan.verifier_env_baseline is None:
            policies.append(plan.verifier_phase)
    # If the pinned Docker backend cannot enforce this policy, Harbor must fail;
    # never silently attach main directly as a fallback.
    return any(policy.network_mode != NetworkMode.PUBLIC for policy in policies)


def _overlay(root: Path, spec: RSIConfig, *, role: Literal['actor', 'verifier'], broker_network: str | None = None,
             controlled: bool = False, owner: str | None = None) -> Path:
    if role not in ('actor', 'verifier'):
        raise ValueError('explicit actor or verifier overlay role required')
    if role == 'verifier' and broker_network is not None:
        raise ValueError('independent verifier cannot join actor broker network')
    path = root/'platform.yaml'
    labels = {'org.memweave.eval.run': owner or root.name}
    # These overlays only enter after exact frozen image inspection/preparation.
    # A local derived tag must never be interpreted as a registry to pull.
    main = {'platform': spec.platform, 'labels': labels, 'pull_policy': 'never'}
    if role == 'actor':
        # Actor only, including public networks; sidecar and verifier stay unchanged.
        main['cap_drop'] = ['NET_RAW']
    document = {'services': {'main': main}}
    if broker_network is not None:
        if not re.fullmatch(r'memweave-broker-ipc-[a-f0-9]{24}', broker_network):
            raise ValueError('invalid owned broker network name')
        document['networks'] = {'broker_ipc': {'external': True, 'name': broker_network}}
        networks = {'default': {}, 'broker_ipc': {}}
        if controlled:
            # Explicit main networking would make Harbor skip transparent egress.
            document['services']['harbor-docker-egress-control-sidecar'] = {
                'labels': labels, 'networks': networks}
        else:
            main['networks'] = networks
    path.write_text(yaml.safe_dump(document))
    return path


def _one_result(root: Path, name: str, task_id: str) -> tuple[Path, dict]:
    from .runner import trial_results
    records = trial_results(root/'harbor'/name)
    if set(records) != {task_id}:
        raise ValueError('exactly one official task result is required')
    return records[task_id]


def inspect_plan(spec: RSIConfig, *, split='all', task_ids=None, _validated=None) -> dict:
    from .rsi_environment import inspect_environment
    from .rsi_preparation import select_rows
    from .runner import verify_package

    if _validated is None:
        catalog = _catalog(spec)
        summary = _validate_catalog(spec, catalog)
    else:
        catalog, summary = _validated
    selected = select_rows(catalog, split, task_ids)
    paths = source_paths(spec, dict(catalog, tasks=selected))
    archive = verify_package(spec.subject.package, spec.subject.sha256, spec.subject.commit)
    # Capacity is independently calculated from originals, including separate verifiers.
    requirements = allocations(paths)
    status = inspect_environment(Path(__file__).resolve().parents[3],
                                 concurrency=spec.concurrency, allocations=requirements,
                                 source_cache=spec.source_cache, candidate=spec.subject.package,
                                 resource_policy=spec.resources)
    return {'catalog': summary, 'selected_count': len(selected), 'split': split,
            'package': archive, 'environment': status, 'requirements': requirements,
            'concurrency': spec.concurrency, 'paid_execution_authorized': False}



def require_preparation_storage(spec: RSIConfig, task: Path, env: dict, evidence_path=None) -> None:
    """Recheck image-growth headroom before each serial original preparation."""
    from .rsi_environment import available_storage_mb, original_allocation

    available = available_storage_mb(env)
    if evidence_path is not None:
        from .rsi_asset_storage_failure import PreparationStorageUnavailable, storage_values
        observed = storage_values(spec, task, available)
        atomic_json(Path(evidence_path), observed, immutable=True)
        if observed['sufficient'] is not True:
            raise PreparationStorageUnavailable(
                f'original task storage no longer fits: {task.name}; '
                f'needs {observed["required_mb"]:g} MiB, available budget {observed["usable_mb"]:g} MiB',
                evidence_path)
        return
    cap = spec.resources.storage_mb
    if cap is not None and cap > available:
        raise ValueError('configured storage cap now exceeds available Docker disk')
    limit = available if cap is None else cap
    usable = limit - max(limit*spec.resources.reserve_storage_fraction,
                         spec.resources.reserve_storage_mb)
    required = original_allocation(task/'task.toml')['storage_mb']
    if required > usable:
        raise ValueError(f'original task storage no longer fits: {task.name}; '
                         f'needs {required:g} MiB, available budget {usable:g} MiB')


def prepare(spec: RSIConfig, destination: Path, *, split='all', timeout_seconds=None,
            task_ids=None, frozen_preparations=None, seal_only=False) -> dict:
    from .rsi_environment import daemon_lease
    from .rsi_preparation import prepare_incrementally

    with daemon_lease() as lease:
        return prepare_incrementally(spec, destination, split=split, timeout_seconds=timeout_seconds,
                                     task_ids=task_ids, frozen_preparations=frozen_preparations,
                                     seal_only=seal_only, lease=lease)


def _prepare_one(spec: RSIConfig, destination: Path, *, task_row, catalog, plan, deadline,
                 frozen=None, broker_images=None, warm_only=False, stop_event=None, ownership=None,
                 lease=None, work_ticket=None) -> dict:
    """One fresh task, sealed only after all original and synthetic controls."""
    from contextlib import nullcontext

    from .images import prepare_task, verify_prepared_task
    from .rsi_helpers import PreparationLifecycle
    from .rsi_image_metadata import cached_images
    from .runner import execute_harbor
    from .runtime_cache import create_plan, snapshot

    if type(warm_only) is not bool or (warm_only and frozen is None):
        raise ValueError("warm-only preparation requires exact frozen images")
    lifecycle = PreparationLifecycle(destination, lease=lease, ticket=work_ticket, ownership=ownership)
    rows = [task_row]
    paths = source_paths(spec, dict(catalog, tasks=rows))
    atomic_json(destination/'preparation-plan.json', plan, immutable=True)
    env = tool_env(spec, catalog)
    limits = {'max_'+name: max(r[name] for r in plan['requirements'])
              for name in ('cpus', 'memory_mb', 'storage_mb')}
    records, images = {}, {}
    jobs = []
    image_preparation = None
    authority_entered = False
    variants_entered = []

    def check_stop():
        if (stop_event is not None and stop_event.is_set()) or (destination/'STOP_REQUESTED').exists():
            raise TimeoutError('preparation stopped before next phase')

    def execute(cfg):
        check_stop()
        overlay_root = destination/'control-platforms'/cfg['job_name']
        overlay_root.mkdir(parents=True, mode=0o700)
        task = Path(cfg['tasks'][0]['path'])
        cfg['environment']['extra_docker_compose'] = [str(_overlay(
            overlay_root, spec, role='actor', controlled=actor_uses_egress(cfg, task), owner=destination.name))]
        lifecycle.enter_harbor(cfg['job_name'])
        jobs.append(cfg['job_name'])
        code = execute_harbor(cfg, destination, env, deadline, float('inf'),
                              **({'stop_event': stop_event} if stop_event is not None else {}))
        if code:
            raise RuntimeError('official preparation job failed; retained private console has details')

    try:
        # Serial build/install avoids concurrent writers of shared immutable software objects.
        for index, row in enumerate(rows):
            check_stop()
            key = (row['suite_id'], row['task_id'])
            task = paths[key]
            if task_digest(task) != row['sha256']:
                raise ValueError('original task changed before preparation')
            require_preparation_storage(spec, task, env)
            with lifecycle.image_commands():
                record = prepare_task(task, destination, spec.platform, deadline, env, limits,
                                      **({'frozen': frozen} if frozen is not None else {}),
                                      **({'warm_only': True} if warm_only else {}))
            image_preparation = dict(record)
            runtime = destination/record['runtime_path']
            # Verify complete immutable software before starting any controls.
            # Install also enforces read-only mode, so a missing object cannot
            # race this check into an unbounded writer during execution.
            task_images = (cached_images(frozen, prepared=record) if warm_only else
                           prepared_images(record, env, lifecycle=lifecycle))
            warm_objects = (snapshot(create_plan(spec, task_images))
                            if warm_only else None)
            protocol = 'tb4' if row['suite_id'] == 'terminal-bench-4' else 'swe-pro-v2'
            for control, expected in (('oracle', 'passed'), ('nop', 'failed')):
                name = f'control-{index:03d}-{control}'
                execute(build_single_job(spec, destination, name, runtime, protocol, control=control))
                evidence, raw = _one_result(destination, name, task.name)
                if binary_outcome(raw) != expected:
                    raise ValueError('original oracle/nop control did not produce expected binary result')
                record[control] = {'path': str(evidence.relative_to(destination)),
                                   'sha256': file_digest(evidence)}
            verify_prepared_task(destination, record)
            records['/'.join(key)] = record
            images.update(cached_images(frozen, prepared=record) if warm_only else task_images)
            atomic_json(destination/'progress.json', {'prepared': len(records), 'total': len(rows),
                                                       'model_requests': 0})
        check_stop()
        broker_candidates = {**(broker_images or {}), **images}
        broker_image = choose_broker_image(broker_candidates, env, destination=destination,
                                          lifecycle=lifecycle)
        broker_identity = next(value for value in broker_candidates.values()
                               if value['reference'] == broker_image)
        assets = create_plan(spec, images)
        asset_path = destination/'runtime-assets.json'
        atomic_json(asset_path, assets, immutable=True)
        # The complete CLI/preload/broker path is exercised with an external
        # fake authority before any real provider credential may be read.
        from .budget_guard import initialize
        from .trusted_broker import TrustedBroker
        for index, row in enumerate(rows):
            record = records[row['suite_id']+'/'+row['task_id']]
            runtime = destination/record['runtime_path']
            protocol = 'tb4' if row['suite_id'] == 'terminal-bench-4' else 'swe-pro-v2'
            free_root = destination/'private'/f'fixture-{index:03d}'
            control = free_root/'control'
            free_seconds = min(1800, max(1, deadline-time.monotonic()))
            free_deadline = time.time()+free_seconds
            from .rsi_elapsed import ActiveTimer
            free_timer = ActiveTimer(remaining_seconds=free_seconds)
            initialize(control/'quota.json', 29.0, free_deadline,
                       arm_limits={'pi-native': 14.5, 'pi-memweave': 14.5})
            quota = json.loads((control/'quota.json').read_text())
            quota['elapsed_budget_seconds'] = free_seconds
            atomic_json(control/'quota.json', quota)
            (control/'WRITER_PLATFORM').write_text('linux\n')
            episode = f'{destination.name}-preflight-{index:03d}'
            authority = TrustedBroker(free_root/'broker', control, episode, broker_image, env)
            authority_registered = False
            try:
                check_stop()
                authority_entered = True
                with ownership.transition() if ownership else nullcontext():
                    authority.start('synthetic-fixture-not-a-provider-credential',
                                    [{'arm': v, 'episode': episode}
                                     for v in ('pi-native', 'pi-memweave')], fixture=True)
                    if ownership:
                        ownership.register_broker(episode, authority)
                        authority_registered = True
                for variant in ('pi-native', 'pi-memweave'):
                    check_stop()
                    name = f'runtime-{index:03d}-{variant}'
                    cfg = build_single_job(spec, destination, name, runtime, protocol,
                                           variant=variant, runtime_plan=asset_path,
                                           prepare_only=True,
                                           runtime_cache_read_only=warm_only,
                                           runtime_objects=warm_objects,
                                           broker_client=authority.clients[(episode, variant)],
                                           deadline=free_deadline, elapsed_clock=free_timer.start)
                    owner = f'{episode}-{variant}'
                    variant_root = free_root/variant
                    variant_root.mkdir(mode=0o700)
                    try:
                        variants_entered.append(variant)
                        network = authority.connect_attempt(owner)
                        cfg['environment']['extra_docker_compose'] = [str(_overlay(
                            variant_root, spec, role='actor', broker_network=network,
                            controlled=actor_uses_egress(cfg, runtime), owner=owner))]
                        lifecycle.enter_harbor(name)
                        jobs.append(name)
                        code = execute_harbor(cfg, destination, env, deadline, float('inf'),
                              **({'stop_event': stop_event} if stop_event is not None else {}))
                        evidence, raw = _one_result(destination, name, runtime.name)
                        probe = evidence.parent/'agent/runtime-preflight.json'
                        transport = evidence.parent/'agent/cli-transport-result.json'
                        backend = evidence.parent/'agent/mock-backend-preflight.json'
                        from .rsi_preparation import verify_backend_probe
                        if backend.is_file():
                            try:
                                verify_backend_probe(json.loads(backend.read_text()),
                                                     spec.runtime.node_version)
                            except ValueError as error:
                                raise ValueError('independent synthetic Node/flock backend unavailable; '
                                                 'see '+str(backend.relative_to(destination))) from error
                        if code or raw.get('exception_info') or not probe.is_file():
                            raise ValueError('original environment Pi/transport preflight failed')
                        if json.loads(probe.read_text()).get('model_requests') != 0:
                            raise ValueError('software preflight must contain no model requests')
                        if not transport.is_file():
                            raise ValueError('exact CLI external transport proof missing')
                        proof = json.loads(transport.read_text())
                        if not (proof.get('real_model_requests') == 0 and proof.get('positive') is True
                                and proof.get('external_authority') is True
                                and proof.get('lost_guard_upstream_requests') == 0
                                and proof.get('actual_cli_pid_deadline') is True):
                            raise ValueError('exact CLI transport positive/negative/stop proof failed')
                        verify_backend_probe(json.loads(backend.read_text()), spec.runtime.node_version)
                        record.setdefault('backend_probes', {})[variant] = {
                            'path': str(backend.relative_to(destination)), 'sha256': file_digest(backend)}
                        record.setdefault('transport', {})[variant] = {
                            'path': str(transport.relative_to(destination)), 'sha256': file_digest(transport)}
                        record.setdefault('probes', {})[variant] = {
                            'path': str(probe.relative_to(destination)), 'sha256': file_digest(probe)}
                        record.setdefault('runtime_results', {})[variant] = {
                            'path': str(evidence.relative_to(destination)), 'sha256': file_digest(evidence)}
                    finally:
                        cleanup = cleanup_attempt(destination, owner, env)
                        if cleanup['confirmed']:
                            cleanup['network'] = authority.disconnect_attempt(owner)
                            cleanup['confirmed'] = cleanup['network'].get('confirmed') is True
                        atomic_json(variant_root/'cleanup.json', cleanup, immutable=True)
                        if not cleanup['confirmed']:
                            raise RuntimeError('fixture attempt container/network cleanup unconfirmed')
            finally:
                if authority.process is not None:
                    with ownership.transition() if ownership else nullcontext():
                        cleanup = authority.stop()
                        atomic_json(free_root/'cleanup.json', cleanup, immutable=True)
                        if (not cleanup.get('stopped') or not cleanup.get('terminal_available')
                                or cleanup.get('networks_confirmed') is not True):
                            raise RuntimeError('fixture authority stop could not be verified')
                        if ownership and authority_registered:
                            ownership.remove_broker(episode)
        objects = snapshot(assets)
        atomic_json(destination/'runtime-assets.lock.json',
                    {'plan_sha256': file_digest(asset_path), 'objects': objects}, immutable=True)
        from .rsi_preparation import task_identity

        record = {'schema_version': 2, 'config': spec.model_dump(mode='json'), 'rows': rows,
                  'kind': 'single-task-preparation',
                  'qualification': task_identity(spec, catalog, task_row,
                      environment_identity=plan['environment']['qualification_identity']),
                  'started_sha256': file_digest(destination/'started.json'),
                  'preparation_root': str(destination.resolve()),
                  'catalog_sha256': file_digest(spec.catalog),
                  'preparations': records, 'images': images, 'model_requests': 0,
                  'broker_image': broker_image, 'broker_identity': broker_identity,
                  'transport_verified': True,
                  'evaluator_sha256': evaluator_digest(),
                  'runtime_plan_sha256': file_digest(asset_path),
                  'runtime_lock_sha256': file_digest(destination/'runtime-assets.lock.json')}
        cleanup = cleanup_attempt(destination, destination.name, env)
        atomic_json(destination/'container-cleanup.json', cleanup, immutable=True)
        if not cleanup['confirmed']:
            raise RuntimeError('preparation container cleanup unconfirmed')
        from .rsi_preparation import proof, terminal_jobs

        record['cleanup_proofs'] = [proof(destination, path) for path in sorted(
            (destination/'private').rglob('cleanup.json'))]
        record['cleanup_proofs'].append(proof(destination, destination/'container-cleanup.json'))
        record['jobs'] = terminal_jobs(destination, jobs)
        record['preparation_lifecycle'] = lifecycle.finish(jobs)
        record['broker_selection'] = proof(destination, destination/'broker-probes/selection.json')
        record['environment_plan'] = proof(destination, destination/'preparation-plan.json')
        atomic_json(destination/'task-prepared.json', record, immutable=True)
        atomic_json(destination/'task-receipt-proof.json',
                    proof(destination, destination/'task-prepared.json'), immutable=True)
        return record
    except BaseException as exc:
        cleanup = cleanup_attempt(destination, destination.name, env)
        atomic_json(destination/'failed-cleanup.json', cleanup, immutable=True)
        atomic_json(destination/'incomplete.json', {'complete': False, 'error': type(exc).__name__,
                                                   'reason': str(exc), 'execution_started': True,
                                                   'cleanup_confirmed': cleanup['confirmed'],
                                                   'prepared_tasks': len(records), 'model_requests': 0}, immutable=True)
        if image_preparation is not None:
            from .rsi_preparation import record_failed_terminal

            try:
                phases = lifecycle.finish(jobs)
            except (ValueError, OSError, KeyError, TypeError):
                phases = None  # Unknown helper/suboperation cannot certify a failed terminal.
            record_failed_terminal(destination, image_preparation, jobs,
                                   authority_entered, variants_entered, lifecycle=phases)
        raise


def choose_broker_image(images: dict, env: dict, *, destination: Path, lifecycle=None) -> str:
    """Prove actual frozen broker imports; retain diagnostics for every candidate."""
    from .rsi_broker_probe import choose

    return choose(images, env, destination, lifecycle=lifecycle)


LIBC_COMMAND = 'cat /etc/os-release 2>/dev/null; ldd --version 2>&1 || true'


def libc_from_output(output):
    output = output.lower()
    if 'musl' in output or 'id=alpine' in output:
        return 'musl'
    if 'gnu libc' in output or 'glibc' in output or 'free software foundation' in output:
        return 'gnu'
    raise ValueError('libc probe did not identify GNU or musl')


def prepared_images(record: dict, env: dict, *, lifecycle=None, libc_proofs=None) -> dict:
    """Probe frozen images on the explicit dedicated daemon, not personal context."""
    from .images import inspect_image

    if lifecycle is None:
        raise ValueError('libc probe requires a live durable preparation lifecycle')
    result = {}
    for role, image in record['images'].items():
        current = inspect_image(image['reference'], env)
        if current['id'] != image['id'] or current['platform'] != image['platform']:
            raise ValueError('image changed during original controls')
        if role == 'main':
            probe = lifecycle.run_container('libc', image, ['--entrypoint', 'sh'],
                ['-c', LIBC_COMMAND], env, 30)
            if probe.returncode:
                raise ValueError('libc probe failed')
            current['libc'] = libc_from_output(probe.stdout)
            if libc_proofs is not None:
                libc_proofs[record['task_id']] = probe.helper
        key = record['task_id'] + (':verifier' if role != 'main' else '')
        result[key] = current
    return result


def trial_projects(trial: str) -> tuple[str, str]:
    """Pinned Harbor0.24 single-step identifiers, including verifier truncation."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,150}', trial):
        raise ValueError('unsafe trial identifier')
    verifier = trial+'__verifier__trial'
    if len(verifier) > 63:
        suffix = '__'+hashlib.sha1(verifier.encode()).hexdigest()[:8]
        verifier = verifier[:63-len(suffix)].rstrip('-._')+suffix

    def sanitize(value):
        value = value.lower()
        if not value[0].isalnum():
            value = '0'+value
        return re.sub(r'[^a-z0-9_-]', '-', value)

    return sanitize(trial+'__env'), sanitize(verifier)


def cleanup_attempt(output: Path, owner: str, env: dict) -> dict:
    """Query/stop only exact owned actor and independent-verifier projects.

    Harbor drops evaluator overlays for separate verifiers. Their exact project
    IDs come from the trusted host trial config. No global prune or image/volume
    deletion, and no inspection of unrelated container environment/credentials.
    """
    def command(args):
        return subprocess.run(['docker', *args], env=env, capture_output=True,
                              text=True, timeout=30, check=False)

    try:
        projects = set()
        for path in (output/'harbor').glob('*/*/config.json'):
            if path.is_symlink():
                raise ValueError('redirected trial config')
            config = json.loads(path.read_text())
            trial = config.get('trial_name')
            if not isinstance(trial, str) or trial != path.parent.name:
                raise ValueError('trial ownership identity mismatch')
            projects.update(trial_projects(trial))
        selectors = ['org.memweave.eval.run='+owner] + [
            'com.docker.compose.project='+project for project in sorted(projects)]

        def selected():
            result = set()
            for selector in selectors:
                query = command(['ps', '-a', '--filter', 'label='+selector, '--format', '{{.ID}}'])
                if query.returncode:
                    raise ValueError('owned container query failed')
                ids = query.stdout.split()
                if any(not re.fullmatch('[0-9a-f]{12,64}', item) for item in ids):
                    raise ValueError('invalid Docker container identity')
                result.update(ids)
            return result

        owned = selected()
        for identity in sorted(owned):
            command(['stop', '--time', '10', identity])
            command(['rm', identity])
        remaining = selected()
        from .rsi_cleanup import cleanup_project_networks

        networks = (cleanup_project_networks(projects, command) if not remaining else
                    {'confirmed': False, 'reason': 'owned containers remain'})
        return {'confirmed': not remaining and networks['confirmed'],
                'owned_containers': sorted(owned), 'remaining': sorted(remaining),
                'project_networks': networks,
                'scope': 'exact attempt actor/verifier containers and empty project networks'}
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return {'confirmed': False, 'reason': 'ownership or cleanup could not be verified'}


def _verify_prepared(spec: RSIConfig, directory: Path, split: str) -> tuple[dict, list[dict]]:
    from .images import inspect_image, verify_prepared_task
    from .runner import verify_package
    from .runtime_cache import snapshot

    if (directory/'store.json').is_file():
        from .rsi_preparation import verify_sealed
        return verify_sealed(spec, directory, split)
    # Legacy full seals retain their original strict validation.
    if not (directory/'prepared.json').is_file():
        raise ValueError('requested split was not completely prepared; no final seal')
    lock = json.loads((directory/'prepared.json').read_text())
    if lock.get('schema_version') == 2:
        from .rsi_preparation import verify_sealed

        return verify_sealed(spec, directory, split)
    if lock.get('evaluator_sha256') != evaluator_digest():
        raise ValueError('evaluator or transport code changed after preparation')
    if lock.get('transport_verified') is not True:
        raise ValueError('exact free CLI/authority preflight not verified')
    cleanup = json.loads((directory/'container-cleanup.json').read_text())
    if cleanup.get('confirmed') is not True:
        raise ValueError('preparation container cleanup not confirmed')
    original = lock['config']
    current = spec.model_dump(mode='json')
    for key in ('subject', 'runtime', 'model', 'platform', 'source_cache'):
        if original[key] != current[key]:
            raise ValueError('prepared software, source or model identity changed')
    verify_package(spec.subject.package, spec.subject.sha256, spec.subject.commit)
    if lock['catalog_sha256'] != file_digest(spec.catalog):
        raise ValueError('catalog changed after preparation')
    _validate_catalog(spec, _catalog(spec))
    runtime_plan = directory/'runtime-assets.json'
    runtime_lock = directory/'runtime-assets.lock.json'
    if (file_digest(runtime_plan) != lock['runtime_plan_sha256'] or
            file_digest(runtime_lock) != lock['runtime_lock_sha256']):
        raise ValueError('frozen runtime manifest changed')
    if snapshot(json.loads(runtime_plan.read_text())) != json.loads(runtime_lock.read_text())['objects']:
        raise ValueError('frozen software objects changed')
    rows = [r for r in lock['rows'] if split == 'all' or r['split'] == split]
    expected = [r for r in _catalog(spec)['tasks']
                if split == 'all' or r['split'] == split]
    if rows != expected:
        raise ValueError('requested split was not completely prepared')
    for row in rows:
        record = lock['preparations'][row['suite_id']+'/'+row['task_id']]
        verify_prepared_task(directory, record)
        for variant in ('pi-native', 'pi-memweave'):
            proof = record.get('transport', {}).get(variant)
            if not proof or file_digest(directory/proof['path']) != proof['sha256']:
                raise ValueError('free CLI/authority evidence changed')
        for control in ('oracle', 'nop'):
            if file_digest(directory/record[control]['path']) != record[control]['sha256']:
                raise ValueError('original control evidence changed')
    for identity in lock['images'].values():
        if inspect_image(identity['reference'], tool_env(spec, _catalog(spec)))['id'] != identity['id']:
            raise ValueError('prepared image tag changed')
    return lock, rows


def _verify_admitted(spec, directory, split, *, plan=None):
    if (directory/'store.json').is_file():
        from .rsi_preparation import verify_admitted
        return verify_admitted(spec, directory, split, plan=plan)
    return _verify_prepared(spec, directory, split)


def admission_capacity(plan):
    """Task shortfalls wait; daemon, ownership and invalid capacity still block."""
    environment = plan['environment']
    checks = environment.get('checks', [])
    resource = next((row for row in checks if row['name'] == 'docker_capacity'), None)
    if (resource is None or resource.get('errors')
            or any(row.get('status') != 'pass' for row in checks
                   if row['name'] != 'docker_capacity')):
        raise ValueError('requested concurrency/resources unavailable; no credentials read')
    return resource


def admission_waiting(result, lock, resource):
    prepared = set(lock['preparations'])
    requirements = {(row['benchmark'], row['task_id']): ResourceAmounts(**row['original'])
                    for row in resource['requirements']}
    expected = {(task.benchmark, task.task_id) for task in result.tasks}
    if set(requirements) != expected or not prepared <= {a+'/'+b for a, b in expected}:
        raise ValueError('admission resource/preparation identity differs from requested tasks')
    budget = ResourceAmounts(**resource['budget'])
    progress = []
    for row in result.progress:
        row = dict(row)
        key = row['benchmark'], row['task_id']
        if row['status'] == 'pending':
            if '/'.join(key) not in prepared:
                row['status'] = 'waiting_preparation'
            elif not requirements[key].fits(budget):
                row['status'] = 'waiting_capacity'
        progress.append(row)
    return replace(result, progress=tuple(progress))


def record_actor_phase(output: Path, evidence: Path, raw: dict, return_code: int) -> str | None:
    """Publish actor status without replacing SWE's required fresh patch grade."""
    exception = raw.get('exception_info')
    kind = None
    if exception:
        value = exception.get('exception_type') if isinstance(exception, dict) else None
        kind = value if isinstance(value, str) and re.fullmatch(
            r'[A-Za-z_][A-Za-z0-9_.]{0,99}', value) else 'UnclassifiedException'
    atomic_json(output/'actor-status.json', {
        'result_path': str(evidence), 'result_sha256': file_digest(evidence),
        'return_code': return_code, 'exception_type': kind,
        'fresh_regrade_required': True}, immutable=True)
    if return_code or kind:
        return (f'Official fresh regrade retained; actor return_code={return_code}, '
                f'exception_type={kind}; see actor-status.json')
    return None


def episode_id(run_id: str, task_id: str, variant: str, attempt: int) -> str:
    return run_id + ':' + hashlib.sha256(
        f'{task_id}\0{variant}\0{attempt}'.encode()).hexdigest()[:20]


def native_contract(spec: RSIConfig, catalog: dict) -> dict:
    from .rsi_baseline import question_set_digest

    paths = source_paths(spec, catalog)
    revisions = {source['id']: source['revision'] for source in catalog['sources']}
    tasks = [TaskIdentity(row['task_id'], row['suite_id'], revisions[row['suite_id']],
                          row['sha256'], (paths[(row['suite_id'], row['task_id'])]/'instruction.md')
                          .read_text()) for row in catalog['tasks']]
    policy = policy_for_catalog(catalog)
    if is_active_policy(policy) and spec.max_attempts != policy['max_attempts']:
        raise ValueError('new catalog attempt limit differs from immutable execution policy')
    return {**({'execution_policy': policy} if is_active_policy(policy) else {}),
            'catalog_sha256': file_digest(spec.catalog),
            'question_set_sha256': question_set_digest(catalog),
            'tasks': [asdict(task) for task in tasks],
            'model': spec.model.model_dump(mode='json'), 'runtime': spec.runtime.model_dump(mode='json'),
            'sources': catalog['sources'], 'max_attempts': spec.max_attempts,
            'evaluator_sha256': evaluator_digest(), 'platform': spec.platform}



def original_time_envelope(task: Path, *, now: float | None = None) -> tuple[float, float]:
    """Finite cleanup envelope from unchanged official stage limits, not a run budget."""
    from harbor.models.task.config import TaskConfig

    from .pi_agent import ExperimentPi

    cfg = TaskConfig.model_validate_toml((task/'task.toml').read_text())
    actor = cfg.agent.timeout_sec
    if actor is None or actor <= 0:
        raise ValueError('original task needs a declared actor timeout for isolated transport')
    started = time.time() if now is None else now
    build, setup = cfg.environment.build_timeout_sec, ExperimentPi.DEFAULT_SETUP_TIMEOUT_SEC
    # Harbor enforces the actual official actor/verifier clocks. This outer guard
    # includes setup/build and a complete fresh SWE replay, without shortening them.
    actor_end = started + build + setup + actor + 600
    end = actor_end + 2*build + setup + actor + cfg.verifier.timeout_sec + 600
    return actor_end, end


def stage_summaries(result, catalog: dict, max_attempts: int) -> dict:
    """Keep the selected catalog's separate stage denominators in reports."""
    stages = {}
    for split in ('regression', 'capability'):
        wanted = {(r['suite_id'], r['task_id']) for r in catalog['tasks'] if r['split'] == split}
        tasks = [t for t in result.tasks if (t.benchmark, t.task_id) in wanted]
        if not tasks:
            continue
        variants = {}
        for variant in result.variants:
            passed = complete = 0
            for task in tasks:
                records = [r for r in result.attempts if r['task'] == asdict(task)
                           and r['variant'] == asdict(variant)]
                # Legacy complete baseline records predate classification; their
                # official outcomes were independently verified by BaselineStore.
                ability = [r for r in records if r.get('classification', 'ability') == 'ability']
                success = any(r['outcome'] == 'passed' for r in ability)
                failed = sum(r['outcome'] == 'failed' for r in ability) >= max_attempts
                passed += success
                timeout = (not any(r.get('classification') in ('cleanup_unconfirmed', 'manual_review')
                    for r in records) and is_active_policy(policy_for_catalog(catalog)) and
                    active_history_seconds(records, policy_for_catalog(catalog)) >=
                    policy_for_catalog(catalog)['task_timeout_seconds'])
                complete += success or failed or timeout
            variants[variant.variant_id] = {'passed': passed, 'total': len(tasks),
                'completed': complete, 'complete': complete == len(tasks),
                'incomplete': len(tasks)-complete,
                'effective_pass_rate': passed/complete if complete else None,
                'pass_rate': passed/len(tasks) if complete == len(tasks) else None}
        stages[split] = variants
    return stages



async def drain_owned_work(work) -> tuple[object, bool]:
    """Repeated cancellation cannot abandon an owned startup or cleanup thread."""
    cancelled = False
    while not work.done():
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            cancelled = True
    return work.result(), cancelled



async def finish_attempt_resources(output: Path, owner: str, env: dict, broker, *,
                                   episode=None, arm=None, reason='attempt_finished') -> tuple[dict, bool]:
    """A failed/uncertain cleanup is data, never an exception that loses ownership."""
    cancelled = False
    cancellation = {'confirmed': True, 'not_requested': episode is None}
    if episode is not None:
        try:
            work = asyncio.create_task(asyncio.to_thread(
                broker.cancel_attempt, episode, arm, reason=reason))
            cancellation, interrupted = await drain_owned_work(work)
            cancelled |= interrupted
        except Exception as exc:  # noqa: BLE001 -- uncertain requests retain resources
            cancellation = {'confirmed': False, 'reason': type(exc).__name__}
    try:
        work = asyncio.create_task(asyncio.to_thread(cleanup_attempt, output, owner, env))
        cleanup, interrupted = await drain_owned_work(work)
        cancelled |= interrupted
    except Exception as exc:  # noqa: BLE001 -- any cleanup failure retains ownership
        cleanup = {'confirmed': False, 'reason': type(exc).__name__}
    if cleanup.get('confirmed') is True:
        try:
            work = asyncio.create_task(asyncio.to_thread(broker.disconnect_attempt, owner))
            network, interrupted = await drain_owned_work(work)
            cancelled |= interrupted
        except Exception as exc:  # noqa: BLE001 -- never lose uncertain network ownership
            network = {'confirmed': False, 'reason': type(exc).__name__}
        cleanup['network'] = network
        cleanup['confirmed'] = network.get('confirmed') is True
    else:
        cleanup['confirmed'] = False
    cleanup['requests'] = cancellation
    cleanup['confirmed'] = cleanup['confirmed'] and cancellation.get('confirmed') is True
    return cleanup, cancelled


async def run_prepared(spec: RSIConfig, directory: Path, *, split: str,
                       approved_budget_usd: float | None, variant: str = 'pi-memweave',
                       calibration: bool = False) -> dict:
    from .rsi_environment import daemon_lease

    with daemon_lease() as lease:
        response = await _run_prepared_impl(spec, directory, split=split,
            approved_budget_usd=approved_budget_usd, variant=variant, calibration=calibration, lease=lease)
        if calibration:
            response.update(purpose='initial-calibration-only', promotion_allowed=False)
        return response


async def _run_prepared_impl(spec: RSIConfig, directory: Path, *, split: str,
                             approved_budget_usd: float | None, variant: str, calibration: bool = False,
                             lease=None, pipeline=None) -> dict:
    """Acquire stable progress before considering any new provider request."""
    from .rsi_baseline import BaselineStore, question_set_digest
    from .rsi_progress import ProgressStore

    if variant not in ('pi-native', 'pi-memweave'):
        raise ValueError('run exactly one native baseline or plugin variant')
    if calibration and (variant != 'pi-memweave' or split != 'all'):
        raise ValueError('initial calibration requires exactly plugin all tasks')
    catalog = _catalog(spec)
    execution_policy = policy_for_catalog(catalog)
    active = is_active_policy(execution_policy)
    if (variant == 'pi-native' and split != 'all') or (
            variant == 'pi-memweave' and split not in ('regression', 'capability')
            and not calibration and not (active and split == 'all')):
        raise ValueError('native baseline covers the full catalog; plugin runs one explicit stage')
    execution_policy = execution_policy if active else None
    qset = question_set_digest(catalog)
    legacy_store = BaselineStore(spec.root/'native-baselines', qset)
    legacy = None if active else legacy_store.lookup()
    if not active and legacy is None and legacy_store.directory.exists():
        raise ValueError('legacy incomplete baseline requires explicit evidence reconciliation; cannot reset time or counts')
    if variant == 'pi-native' and legacy is not None:
        _validate_catalog(spec, catalog)
        return {'reused_native_baseline': True, 'reused_results': True, 'model_run': False,
                'path': str(legacy.result.output_root),
                'stages': stage_summaries(legacy.result, catalog, legacy.contract['max_attempts']),
                'native_metadata_changes': legacy.mismatches(native_contract(spec, catalog))}
    contract = native_contract(spec, catalog)
    all_tasks = [TaskIdentity(**row) for row in contract['tasks']]
    selected = {(row['suite_id'], row['task_id']) for row in catalog['tasks']
                if split == 'all' or row['split'] == split}
    tasks = [task for task in all_tasks if (task.benchmark, task.task_id) in selected]
    if pipeline is not None:
        pipeline.validate_scope(tasks)
    identity = VariantIdentity(variant, 'pi:'+spec.runtime.pi_version if variant == 'pi-native'
                               else spec.subject.commit+':'+spec.subject.sha256)
    store = ProgressStore(spec.root/'progress', identity, question_set_sha256=qset,
                          execution_policy=execution_policy)
    with store.acquire():
        if calibration:
            from .rsi_calibration import register_calibration
            native = ProgressStore(spec.root/'progress', VariantIdentity('pi-native',
                'pi:'+spec.runtime.pi_version), question_set_sha256=qset, execution_policy=execution_policy)
            # Registration revalidates complete original200 and freezes this subject
            # before recovery can execute a grader or any new plugin launch.
            with native.acquire():
                native_snapshot = native.scan(all_tasks)
                if len(all_tasks) != len(catalog['tasks']) or (not active and not native_snapshot.complete):
                    raise ValueError(f'complete initial native{len(all_tasks)} required before calibration')
                register_calibration(spec.root, catalog, native, store, contract)
        snapshot = store.scan(tasks)
        env = tool_env(spec, catalog)
        if snapshot.unsettled_launches or snapshot.unresolved:
            recovery = await reconcile_series(store, env, spec=spec, lease=lease)
            snapshot = store.scan(tasks)
            if not recovery['ready']:
                return {'path': str(store.directory), 'model_run': False, 'recovery': recovery,
                        'blocked': 'existing execution requires reconciliation',
                        'stages': stage_summaries(snapshot.result(store.directory), catalog, spec.max_attempts)}
        baseline_result = legacy.result if legacy else None
        baseline_changes = legacy.mismatches(contract) if legacy else []
        native_context = getattr(pipeline, 'native_baseline_context', None)
        if variant == 'pi-memweave' and native_context is not None:
            baseline_result, baseline_changes = native_context
        if variant == 'pi-memweave' and baseline_result is None and native_context is None:
            native = ProgressStore(spec.root/'progress', VariantIdentity('pi-native',
                'pi:'+spec.runtime.pi_version), question_set_sha256=qset, execution_policy=execution_policy)
            with native.acquire():
                initial = native.scan(all_tasks)
                if initial.complete:
                    baseline_result, _ = series_accounting(native, initial.result(native.directory))
                    baseline_changes = initial.mismatches(contract)
        if snapshot.complete:
            _validate_catalog(spec, catalog)
            result, accounting = series_accounting(store, snapshot.result(store.directory))
            return result_response(result, catalog, spec, variant=variant, reused=True,
                path=store.directory, accounting=accounting, baseline_result=baseline_result,
                metadata_changes=baseline_changes if variant == 'pi-memweave' else snapshot.mismatches(contract),
                max_attempts=(snapshot.contract or {}).get('max_attempts', spec.max_attempts))
        view = snapshot.result(store.directory)
        runnable = [row for row in view.progress if row['status'] == 'pending']
        if not runnable and not active:
            store.begin_supplementary_batch(tasks)
            snapshot = store.scan(tasks)
            view = snapshot.result(store.directory)
            runnable = [row for row in view.progress if row['status'] == 'pending']
        if not runnable:
            result, accounting = series_accounting(store, view)
            response = result_response(result, catalog, spec, variant=variant, reused=True,
                path=store.directory, accounting=accounting, baseline_result=baseline_result,
                metadata_changes=baseline_changes,
                max_attempts=(snapshot.contract or {}).get('max_attempts', spec.max_attempts))
            response.update(blocked='questions need supplementary testing or cause review',
                            reused_results=False)
            return response
        if not spec.unbounded and (spec.max_cost_usd is None or spec.max_elapsed_seconds is None or
                                    approved_budget_usd != spec.max_cost_usd):
            raise ValueError('explicit matching new-run budget and elapsed-time limit required')
        directory = outside_repository(directory)
        plan = inspect_plan(spec, split=split)
        # Preserve early rejection of invalid environment checks, even before proofs.
        if not plan['environment'].get('checks') and not plan['environment']['ready']:
            raise ValueError('requested concurrency/resources unavailable; no credentials read')
        lock, rows = _verify_admitted(spec, directory, split, plan=plan)
        resource = admission_capacity(plan)
        if {(r['suite_id'], r['task_id']) for r in rows} != selected:
            raise ValueError('prepared task selection differs from registered series')
        if variant == 'pi-memweave' and baseline_result is None and not active:
            raise ValueError('complete initial native catalog baseline required; no provider credentials read')
        waiting_view = (pipeline.waiting_view if pipeline is not None else admission_waiting)(view, lock, resource)
        if not any(row['status'] == 'pending' for row in waiting_view.progress):
            result, accounting = series_accounting(store, waiting_view)
            response = result_response(result, catalog, spec, variant=variant, reused=True,
                path=store.directory, accounting=accounting, baseline_result=baseline_result,
                metadata_changes=baseline_changes)
            response.update(blocked='tasks waiting for full preparation or resource capacity',
                            reused_results=False)
            return response
        # One explicit invocation may finish the initial batch and its one
        # authorized supplementary batch. It never auto-resumes a manual stop,
        # nor grants repeated new windows after the supplementary batch expires.
        invocation_started = time.time()
        launch_paths = []
        while True:
            if any((path/'STOP_REQUESTED').exists() for path in launch_paths):
                return dict(response, blocked='manual stop requested before supplementary launch')
            registered_before = {row['launch_id'] for row in store.registered_launches()}
            try:
                amount, deadline = automatic_launch_limits(spec, launch_paths, invocation_started)
                response = await (pipeline.execute if pipeline is not None else execute_launch)(
                    spec, directory, split=split, lease=lease,
                    approved_budget_usd=approved_budget_usd, variant=variant, catalog=catalog,
                    tasks=tasks, identity=snapshot.variant, contract=contract, store=store,
                    resume=snapshot.resume_state(), plan=plan, lock=lock, env=env,
                    baseline_result=baseline_result, baseline_changes=baseline_changes,
                    launch_cost_limit=amount, launch_deadline=deadline)
            except ValueError as exc:
                registered_after = {row['launch_id'] for row in store.registered_launches()}
                if not launch_paths or registered_after != registered_before:
                    raise  # Never hide a new/uncertain registered execution.
                return dict(response, blocked=str(exc), supplementary_registered_not_started=True)
            launch_paths.append(Path(response['path']))
            response['launch_paths'] = [str(path) for path in launch_paths]
            snapshot = store.scan(tasks)
            if any((path/'STOP_REQUESTED').exists() for path in launch_paths):
                return dict(response, blocked='manual stop requested before supplementary launch')
            rollover = active and any(row.get('status') == 'waiting_principal'
                for row in response.get('task_progress', []))
            if snapshot.complete or (not rollover and (active or any(row['status'] == 'pending'
                    for row in snapshot.result(store.directory).progress))):
                return response
            if not active:
                store.begin_supplementary_batch(tasks)
                snapshot = store.scan(tasks)
            if not any(row['status'] == 'pending'
                    for row in snapshot.result(store.directory).progress):
                return response
            # Capacity and sealed inputs are rechecked after the first batch;
            # image growth or external workload changes never reuse stale budgets.
            try:
                automatic_launch_limits(spec, launch_paths, invocation_started)
                plan = inspect_plan(spec, split=split)
                admission_capacity(plan)
                lock, verified_rows = _verify_admitted(spec, directory, split, plan=plan)
                if {(r['suite_id'], r['task_id']) for r in verified_rows} != selected:
                    raise ValueError('supplementary prepared task selection changed')
                waiting_view = (pipeline.waiting_view if pipeline is not None else admission_waiting)(snapshot.result(store.directory), lock,
                                                 admission_capacity(plan))
                if not any(row['status'] == 'pending' for row in waiting_view.progress):
                    response['task_progress'] = list(waiting_view.progress)
                    response['supplementary_required'] = supplementary_required(waiting_view.progress)
                    response['blocked'] = 'supplementary tasks waiting for preparation or capacity'
                    response['supplementary_registered_not_started'] = True
                    return response
            except ValueError as exc:
                response['blocked'] = str(exc)
                response['supplementary_registered_not_started'] = True
                return response


def automatic_launch_limits(spec, launch_paths, invocation_started, *, now=None):
    """Supplementary work shares this invocation's finite approval envelope.

    A partial/unknown ledger cannot authorize additional finite spend. Unbounded
    mode deliberately retains unknown accounting without making it a batch stop.
    """
    if spec.unbounded:
        return None, None
    now = time.time() if now is None else now
    deadline = invocation_started + spec.max_elapsed_seconds
    remaining = spec.max_cost_usd
    for root in launch_paths:
        accounting = json.loads((Path(root)/'accounting.json').read_text())
        exposure = accounting['global'].get('exposure_usd')
        if type(exposure) not in (int, float) or not math.isfinite(exposure) or exposure < 0:
            raise ValueError('finite supplementary budget exposure is unknown')
        remaining -= exposure
    if remaining <= 0 or now >= deadline:
        raise ValueError('finite supplementary budget or elapsed limit exhausted')
    return remaining, deadline


def physical_principal_bound(policy, max_attempts: int) -> int:
    """Finite principal pool; a bound for legacy wall time, a pool size for active time.

    This is not an infrastructure failure cap. Active-policy pool exhaustion
    returns waiting_principal and may use a new launch after verified cleanup.
    """
    elapsed, failures = 0., 0
    while elapsed < policy.task_timeout_seconds:
        failures += 1
        elapsed += policy.backoff_seconds(failures)
    return max_attempts + failures + 1


def series_accounting(store, result):
    from .rsi_accounting import aggregate_accounting, apply_final_accounting

    sources, included = [], []
    selected = [asdict(task) for task in result.tasks]
    launches = list(store.registered_launches())
    checked_reuses = set()
    for record in result.attempts:
        reference = record.get('reuse_reference')
        if reference is not None and reference['sha256'] not in checked_reuses:
            from .rsi_pass_reuse import validate_pass_reuse
            verified = validate_pass_reuse(reference, execution_policy=store.execution_policy)
            launches.extend(verified['source_launches'])
            checked_reuses.add(reference['sha256'])
    unique_launches = {}
    for launch in launches:
        key = launch['launch_id']
        if key in unique_launches and unique_launches[key] != launch:
            raise ValueError('accounting launch identity conflicts with historical reuse')
        unique_launches[key] = launch
    for launch in unique_launches.values():
        overlaps = [task for task in launch['tasks'] if task in selected]
        if not overlaps:
            continue
        included.append(launch)
        path = Path(launch['run_root'])/'accounting.json'
        if not path.is_file():
            raise ValueError('registered launch accounting is missing; recovery required')
        sources.append({'launch_id': launch['launch_id'], 'path': str(path),
                        'sha256': file_digest(path)})
    if not sources:
        return result, None
    accounting = aggregate_accounting(sources)
    principals = []
    for record in result.attempts:
        owners = [launch for launch in included if Path(record['root']).is_relative_to(
            Path(launch['output_root']))]
        if len(owners) != 1:
            raise ValueError('attempt accounting launch ownership is not unique')
        run_id = Path(owners[0]['run_root']).name
        principals.append({'episode': episode_id(run_id,
            record['task']['benchmark']+'/'+record['task']['task_id'],
            record['variant']['variant_id'], record['attempt_index']),
            'arm': record['variant']['variant_id']})
    result = apply_final_accounting(result, accounting, principals=principals)
    return result, {**accounting,
        'report_scope': 'all requests in referenced launches; result tokens are selected attempts only',
        'selected_principals': principals}


def supplementary_required(progress):
    """Report only expired eligible work or already registered supplemental work."""
    return [row for row in progress
        if row.get('first_started_at') is not None
        and row.get('status') not in ('passed', 'ability_exhausted', 'manual_review', 'cleanup_unconfirmed')
        and not row.get('supplementary_hold_reason')
        and (row.get('batch_id', 'initial') != 'initial'
             or row.get('status') == 'deadline_exhausted')]


def result_response(result, catalog, spec, *, variant, reused, path, accounting,
                    metadata_changes=(), baseline_result=None, max_attempts=None, preparation_report=None):
    qualified = None
    if (variant == 'pi-memweave' and baseline_result is not None
            and catalog.get('regression_status') == 'calibrated-qualified'):
        combined = replace(result, attempts=baseline_result.attempts+result.attempts,
                           variants=baseline_result.variants+result.variants)
        regression = {(row['suite_id'], row['task_id']) for row in catalog['tasks']
                      if row['split'] == 'regression'}
        qualified = sum((task.benchmark, task.task_id) in regression
            for task in qualified_basis_tasks(combined, native_variant='pi-native',
                                              plugin_variant='pi-memweave'))
    return {'path': str(path), 'summaries': result.summaries, 'tokens': result.tokens,
            'stages': stage_summaries(result, catalog,
                spec.max_attempts if max_attempts is None else max_attempts),
            'task_progress': list(result.progress), 'accounting': accounting,
            'compatible_historical_attempts': sum(r.get('reuse_reference') is not None
                for r in result.attempts),
            'scope': 'experiment-stage-only; no evolution promotion',
            'variant': variant, 'qualified_regression_count': qualified,
            'reused_results': reused, 'reused_native_baseline': variant == 'pi-native' and reused
                or variant == 'pi-memweave' and baseline_result is not None,
            'native_baseline_ready': (baseline_result is not None if variant == 'pi-memweave'
                else all(row['complete'] for row in result.summaries.values())),
            'native_metadata_changes': list(metadata_changes), 'model_run': not reused,
            'supplementary_required': supplementary_required(result.progress),
            'promotion_allowed': False,
            **({'pipeline_preparation': preparation_report} if preparation_report is not None else {})}



def trusted_stop_source(output):
    """Read only the host-owned stop receipt; elapsed time alone is not one."""
    path = Path(output)/'stop-reason.json'
    if not path.exists():
        return None
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('redirected stop receipt')
    value = json.loads(path.read_text())
    timestamp = value.get('timestamp')
    if (not isinstance(value.get('reason'), str) or type(timestamp) not in (int, float)
            or not math.isfinite(timestamp) or timestamp <= 0):
        raise ValueError('invalid host stop receipt')
    return {**value, 'verified': True, 'reference': {'path': str(path), 'sha256': file_digest(path)}}


async def resume_same_attempt_regrade(store, spec, env, launch, started, inspection, *, lease=None):
    """Serial fresh official grading under the held daemon lease, never an Agent.

    All old processes/resources have already been reconciled. The unchanged
    original envelope is reserved conservatively by requiring an idle dedicated
    daemon and running just this grader before releasing it to the next question.
    """
    import threading

    from .images import inspect_image
    from .rsi_attempt_evidence import load_transport_evidence
    from .rsi_environment import DaemonLease, inspect_environment, original_allocation
    from .rsi_execution import actor_exit_evidence
    from .rsi_recovery import inspect_attempt
    from .rsi_regrade import (
        pending_grade_validity,
        plan_regrade,
        prepare_regrade,
        record_regrade_cleanup,
        recovery_active_accounting,
    )
    from .runner import execute_harbor

    output, root = Path(started['root'])/'output', Path(launch['run_root'])
    episode = episode_id(root.name, started['task']['benchmark']+'/'+started['task']['task_id'],
                         started['variant']['variant_id'], started['attempt_index'])
    owner = episode.replace(':', '-')
    proof = store.registered_attempt_window(started, launch)
    active_mode = is_active_policy(started.get('execution_policy'))
    todo = plan_regrade(output, started=started, registered_window=proof, cleanup_confirmed=True,
        monotonic=active_mode)
    if todo['action'] in ('hold', 'reuse_result'):
        return dict(todo.get('inspection', inspection), action=todo['action'],
                    reason=todo['reason'], cleanup_confirmed=True)
    transport = load_transport_evidence(root/'private/control', episode=episode,
                                        arm=started['variant']['variant_id'])
    validity = pending_grade_validity(inspection, actor_exit=actor_exit_evidence(inspection),
        transport=transport, stop_source=trusted_stop_source(output))
    if not validity['eligible']:
        return dict(inspection, action='hold', reason=validity['reason'], cleanup_confirmed=True)
    if todo['action'] == 'expired_patch':
        return dict(inspection, action='expired_patch', reason=todo['reason'],
                    pending_grade_validity=validity, cleanup_confirmed=True)
    if not isinstance(lease, DaemonLease) or not lease.active:
        raise ValueError('live daemon lease required before recovery verifier')
    contract = json.loads((root/'run-contract.json').read_text())
    if contract.get('prepared_path'):
        prepared = outside_repository(Path(contract['prepared_path']))
    else:
        # Legacy launch: derive only from its immutable actor runtime-plan path.
        actor = json.loads((output/'configs/actor.json').read_text())
        runtime_plan = Path(actor['agents'][0]['kwargs']['runtime_plan'])
        prepared = outside_repository(runtime_plan.parent/'prepared.json')
    if file_digest(prepared) != contract['prepared_sha256']:
        raise ValueError('original recovery prepared evidence changed')
    lock = json.loads(prepared.read_text())
    if contract.get('pipeline_admission') is True:
        from .rsi_calibration import _attempt_preparation
        from .rsi_progress import _reference

        lock = _attempt_preparation(contract, launch, started, lock, _reference)
        prepared = outside_repository(Path(lock['admission_path']))
    record = lock['preparations'][started['task']['benchmark']+'/'+started['task']['task_id']]
    preparation_root = Path(lock.get('preparation_root', prepared.parent))
    runtime = preparation_root/record['runtime_path']
    original = original_allocation(runtime/'task.toml')
    original['task_id'] = started['task']['benchmark']+'/'+started['task']['task_id']
    capacity = await asyncio.to_thread(inspect_environment, Path(__file__).resolve().parents[3],
        concurrency=1, allocations=[original], candidate=spec.subject.package,
        source_cache=spec.source_cache, resource_policy=spec.resources)
    if not capacity['ready']:
        return dict(inspection, action='hold', reason='same_attempt_regrade_resources_unavailable',
                    resource_admission=capacity, cleanup_confirmed=True)
    observed = {}
    for role, image in record['images'].items():
        current = await asyncio.to_thread(inspect_image, image['reference'], env)
        observed[role] = {key: current[key] for key in ('reference', 'id', 'platform')}
    admitted_at = None
    recovery_timer = None
    original_global_deadline = None
    if is_active_policy(started.get('execution_policy')):
        # Capacity/image checks are outside active time. Fix the segment clock
        # exactly once after admission, shared by plan and immutable intent.
        admitted_at = time.time()
        from .rsi_elapsed import ActiveTimer
        before = recovery_active_accounting(started, inspection)['active_used_seconds']
        remaining = started['execution_policy']['task_timeout_seconds']-before
        if remaining <= 0:
            return dict(inspection, action='expired_patch', reason='active_budget_exhausted', cleanup_confirmed=True)
        recovery_timer = ActiveTimer(remaining_seconds=remaining)
        original_global_deadline = contract.get('deadline')
        if original_global_deadline is not None and (
                type(original_global_deadline) not in (int, float)
                or not math.isfinite(original_global_deadline) or original_global_deadline <= 0):
            raise ValueError('original recovery global deadline invalid')
        if ((root/'STOP_REQUESTED').exists() or original_global_deadline is not None
                and admitted_at >= original_global_deadline):
            return dict(inspection, action='hold', reason='original_global_or_user_stop',
                        cleanup_confirmed=True)
        todo = plan_regrade(output, started=started, registered_window=proof,
                           cleanup_confirmed=True, now=admitted_at, monotonic=True)
        if todo['action'] != 'ready':
            return dict(todo.get('inspection', inspection), action=todo['action'],
                        reason=todo['reason'], cleanup_confirmed=True,
                        pending_grade_validity=validity)
    recovery_root = Path(todo['recovery_root'])
    recovery_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    config = build_single_job(spec, recovery_root, 'regrade', runtime, 'swe-pro-v2',
                              source_job=output/'harbor/actor')
    config['environment']['extra_docker_compose'] = [
        str(_overlay(recovery_root, spec, role='verifier', owner=owner))]
    prepare_regrade(output, started=started, launch=launch, plan=todo, job_config=config,
        prepared_path=prepared, image_observations=observed, cleanup_confirmed=True,
        registered_window=proof, **({'now': admitted_at, 'elapsed_clock': recovery_timer.start} if admitted_at is not None else {}))
    if recovery_timer is not None:
        atomic_json(recovery_root/'elapsed-start.json', {'started_at': admitted_at,
            'elapsed_clock': recovery_timer.start,
            'intent': {'path': str(recovery_root/'intent.json'), 'sha256': file_digest(recovery_root/'intent.json')},
            'original_started': {'path': str(output.parent/'started.json'), 'sha256': file_digest(output.parent/'started.json')}}, immutable=True)
        recovery_timer.bind(output.parent, start_path=recovery_root/'elapsed-start.json', directory=recovery_root/'elapsed-time')
    atomic_json(recovery_root/'resource-admission.json', capacity, immutable=True)
    stop, cancelled, error = threading.Event(), False, None
    selected_deadline = min(todo['question_deadline'], original_global_deadline or float('inf'))
    deadline = time.monotonic() + max(0, min(recovery_timer.remaining_seconds(), selected_deadline-admitted_at) if recovery_timer is not None
                                        else selected_deadline-time.time())
    ticket = lease.begin_work(owner, recovery_root, kind='same-attempt-regrade',
        daemon_identity=capacity['qualification_identity'], evaluator_sha256=evaluator_digest())
    def mark_recovery_stop(reason):
        try:
            path = recovery_root/'stop-reason.json'
            if not path.exists():
                from .rsi_elapsed import observation
                atomic_json(path, {'reason': reason, 'timestamp': time.time(),
                    **({'monotonic': observation()} if recovery_timer is not None else {})}, immutable=True)
        finally:
            stop.set()  # A recording error must not leave owned work running.

    async def stop_watch():
        while not work.done():
            reason = ('user_stop' if (root/'STOP_REQUESTED').exists() else
                'global_deadline' if original_global_deadline is not None
                and time.time() >= original_global_deadline else
                'question_deadline' if (recovery_timer.remaining_seconds() <= 0 if recovery_timer is not None
                                        else time.time() >= todo['question_deadline']) else None)
            if recovery_timer is not None:
                recovery_timer.checkpoint()
            if reason:
                mark_recovery_stop(reason)
                return
            await asyncio.sleep(.2)

    work = asyncio.create_task(asyncio.to_thread(execute_harbor, config, recovery_root,
        env, deadline, float('inf'), budget_stop_file=None, stop_event=stop))
    watcher = (asyncio.create_task(stop_watch())
               if is_active_policy(started.get('execution_policy')) else None)
    try:
        await asyncio.shield(work)
    except asyncio.CancelledError:
        cancelled = True
        mark_recovery_stop('controller_interrupted')
    except Exception as exc:  # noqa: BLE001 -- no raw third-party error in reports
        error = type(exc).__name__
    finally:
        # The thread must own its child through terminal lifecycle before any
        # container cleanup or daemon-budget release, even on repeated cancel.
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                cancelled = True
                stop.set()
            except Exception as exc:  # noqa: BLE001
                error = type(exc).__name__
        if not work.cancelled():
            try:
                work.result()
            except Exception as exc:  # noqa: BLE001
                error = type(exc).__name__
        if watcher is not None:
            watcher.cancel()
            observed, interrupted = await drain_owned_work(
                asyncio.gather(watcher, return_exceptions=True))
            cancelled |= interrupted
            if isinstance(observed[0], Exception):
                error = type(observed[0]).__name__
        current = inspect_attempt(output, task_id=started['task']['task_id'],
                                  protocol='swe-pro-v2', cleanup_confirmed=False)
        life = current.get('lifecycle', {})
        stopped = (current.get('evidence_complete') is True
            and f"regrade_recovery_{todo['grade_index']:04d}" in life and all(not value.get('legacy_terminal') and
            value.get('process', {}).get('state') == 'not_running' for value in life.values()))
        if not stopped:
            raise RuntimeError('same-attempt regrade process cleanup unconfirmed')
        cleaning = asyncio.create_task(asyncio.to_thread(cleanup_attempt, recovery_root, owner, env))
        cleanup, interrupted = await drain_owned_work(cleaning)
        cancelled |= interrupted
        if cleanup.get('confirmed') is not True:
            raise RuntimeError('same-attempt regrade container cleanup unconfirmed')
        record_regrade_cleanup(recovery_root, cleanup=cleanup)
        if recovery_timer is not None:
            recovery_timer.finish(wall_finished_at=time.time())
        lease.complete_work(ticket, recovery_root/'cleanup.json')
    if cancelled:
        raise asyncio.CancelledError
    result = inspect_attempt(output, task_id=started['task']['task_id'],
                             protocol='swe-pro-v2', cleanup_confirmed=True)
    if error:
        result['regrade_execution_error_type'] = error
    exhausted = (recovery_active_accounting(started, result)['active_used_seconds'] >=
        started['execution_policy']['task_timeout_seconds']
        if is_active_policy(started.get('execution_policy')) else time.time() >= todo['question_deadline'])
    if exhausted and result['action'] == 'needs_regrade':
        result.update(action='expired_patch', reason='registered_window_expired_patch_diagnostic_only',
                      pending_grade_validity=validity)
    return dict(result, cleanup_confirmed=True)


async def reconcile_series(store, env, *, spec=None, lease=None):
    from .rsi_accounting import recovered_accounting
    from .rsi_attempt_evidence import load_transport_evidence
    from .rsi_execution import classification_result
    from .rsi_recovery import inspect_attempt, stop_expired_attempt
    from .rsi_regrade import recovery_active_accounting, recovery_deadline, selected_active_deadline
    from .rsi_resume import RecoveryCallbacks, reconcile_progress
    from .rsi_scheduler import RetryPolicy
    from .trusted_broker import TrustedBroker

    stop_receipts = {}
    def protocol(started):
        return 'tb4' if started['task']['benchmark'] == 'terminal-bench-4' else 'swe-pro-v2'
    def inspect(launch, started, *, cleanup_confirmed=False):
        output = Path(started['root'])/'output'
        inspection = inspect_attempt(output, task_id=started['task']['task_id'],
            protocol=protocol(started), cleanup_confirmed=cleanup_confirmed)
        deadline = started['question_deadline']
        if inspection['action'] == 'wait_existing' and is_active_policy(started.get('execution_policy')):
            deadline = recovery_deadline(output, started,
                store.registered_attempt_window(started, launch)
                if hasattr(store, 'registered_attempt_window') else None, inspection)
        expired = time.time() >= deadline
        if started.get('elapsed_clock') is not None:
            try:
                from .rsi_elapsed import remaining_seconds
                from .rsi_regrade import selected_elapsed_clock
                expired = remaining_seconds(selected_elapsed_clock(started, inspection)) <= 0
            except (OSError, ValueError, KeyError):
                return dict(inspection, action='hold', reason='elapsed_clock_domain_unconfirmed')
        if (not cleanup_confirmed and inspection['action'] == 'wait_existing' and expired):
            stopped = stop_expired_attempt(output, started=started,
                **({'registered_window': store.registered_attempt_window(started, launch)}
                   if hasattr(store, 'registered_attempt_window') else {}))
            if stopped.get('confirmed') is True:
                inspection = inspect_attempt(output, task_id=started['task']['task_id'],
                    protocol=protocol(started), cleanup_confirmed=False)
                stop_receipts[started['root']] = stopped
            else:
                inspection = dict(inspection, action='hold', reason='expired_process_stop_unconfirmed')
            inspection['expired_stop'] = stopped
        prior_stop = stop_receipts.get(started['root'])
        if prior_stop is not None:
            inspection['expired_stop'] = prior_stop
            if prior_stop.get('receipt'):
                inspection.setdefault('evidence', []).append(prior_stop['receipt'])
        return inspection
    def stop_broker(launch):
        root = Path(launch['run_root'])
        cleanup = TrustedBroker.recover_stop(root/'private/broker', root/'private/control', root.name, env)
        if cleanup.get('confirmed') is True and not (root/'accounting.json').exists():
            manifest = json.loads((root/'principals.json').read_text())
            accounting = recovered_accounting(root/'private/control',
                principals=manifest['principals'], broker_stopped=True)
            atomic_json(root/'accounting.json', accounting, immutable=True)
        return cleanup
    def clean(launch, started):
        root = Path(launch['run_root'])
        episode = episode_id(root.name, started['task']['benchmark']+'/'+started['task']['task_id'],
                             started['variant']['variant_id'], started['attempt_index'])
        output = Path(started['root'])/'output'
        inspected = inspect_attempt(output, task_id=started['task']['task_id'],
            protocol=protocol(started), cleanup_confirmed=False)
        life = inspected.get('lifecycle', {})
        if inspected.get('evidence_complete') is not True or not life or any(value.get('legacy_terminal') or
                value.get('process', {}).get('state') != 'not_running' for value in life.values()):
            return {'confirmed': False, 'reason': 'recovery_process_identity_uncertain'}
        proofs = [cleanup_attempt(output, episode.replace(':', '-'), env)]
        for entry in inspected.get('recovery_regrades', []):
            from .rsi_regrade import record_regrade_cleanup
            grade_root = Path(entry['root'])
            cleanup = cleanup_attempt(grade_root, episode.replace(':', '-'), env)
            proofs.append(cleanup)
            if cleanup.get('confirmed') is True and not (grade_root/'cleanup.json').exists():
                record_regrade_cleanup(grade_root, cleanup=cleanup)
        return {'confirmed': all(p.get('confirmed') is True for p in proofs), 'stages': proofs}
    def recover(launch, started, inspection):
        root, output = Path(launch['run_root']), Path(started['root'])/'output'
        episode = episode_id(root.name, started['task']['benchmark']+'/'+started['task']['task_id'],
                             started['variant']['variant_id'], started['attempt_index'])
        arm = started['variant']['variant_id']
        source = trusted_stop_source(output)
        if source is not None:
            inspection.setdefault('evidence', []).append(source['reference'])
        original_stop = (source or {}).get('reason')
        # Classification only: original deadlines never claim historical signal
        # delivery, replace stop receipts, or reset the registered question clock.
        contract_path = root/'run-contract.json'
        if any(path.is_symlink() for path in (contract_path, *contract_path.parents)):
            raise ValueError('redirected original run contract')
        contract = json.loads(contract_path.read_text())
        unbounded = contract['config']['unbounded']
        global_deadline = contract['deadline']
        if type(unbounded) is not bool or (unbounded and global_deadline is not None) or (
                not unbounded and (type(global_deadline) not in (int, float)
                    or not math.isfinite(global_deadline) or global_deadline <= 0)):
            raise ValueError('invalid original global deadline')
        envelope_path = output/'time-envelope.json'
        official = inspection.get('regrade') if protocol(started) == 'swe-pro-v2' else inspection.get('actor')
        if envelope_path.exists() or envelope_path.is_symlink() or official is not None:
            if any(path.is_symlink() for path in (envelope_path, *envelope_path.parents)):
                raise ValueError('redirected original time envelope')
            envelope_text = envelope_path.read_text()
            envelope = json.loads(envelope_text)
            for key in ('question_deadline', 'first_started_at'):
                value = envelope[key]
                if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                        or value != started[key]):
                    raise ValueError('original time envelope conflicts with started')
            aggregate = envelope['aggregate_deadline']
            if ((aggregate is not None and (type(aggregate) not in (int, float)
                    or not math.isfinite(aggregate) or aggregate <= 0)) or aggregate != global_deadline):
                raise ValueError('original time envelope conflicts with run deadline')
            global_deadline = aggregate  # The attempt's persisted boundary, not a renewed run limit.
            inspection.setdefault('evidence', []).append({'path': str(envelope_path),
                'sha256': hashlib.sha256(envelope_text.encode()).hexdigest()})
        transport = load_transport_evidence(root/'private/control', episode=episode, arm=arm)
        if protocol(started) == 'swe-pro-v2':
            from .rsi_regrade import selected_grade_stop_source
            source = selected_grade_stop_source(output, inspection, source)
            if (source or {}).get('reason') in ('user_stop', 'global_stop', 'global_deadline'):
                original_stop = source['reason']
        active_accounting = (recovery_active_accounting(started, inspection)
            if is_active_policy(started.get('execution_policy')) else {})
        from .rsi_regrade import selected_elapsed_clock
        decision = classification_result(inspection, protocol=protocol(started),
            transport=transport,
            stop_source=source, question_deadline=selected_active_deadline(started, inspection),
            global_deadline=global_deadline,
            elapsed_clock=selected_elapsed_clock(started, inspection))
        if inspection['action'] == 'expired_patch':
            if inspection.get('pending_grade_validity', {}).get('eligible') is not True:
                return None
            decision = {**decision, 'disposition': 'interrupted',
                        'reason_code': 'question_deadline'}
        elif decision['disposition'] == 'needs_regrade':
            return None
        classification, outcome = {'completed': ('ability', decision['official_outcome']),
            'infra_interrupted': ('infrastructure', 'error'),
            'interrupted': ('interrupted', 'cancelled')}.get(decision['disposition'],
                                                           ('manual_review', 'error'))
        if inspection['action'] == 'retry_fresh' and classification != 'infrastructure':
            classification, outcome = 'interrupted', 'cancelled'
        official = inspection.get('regrade') if protocol(started) == 'swe-pro-v2' else inspection.get('actor')
        try:
            usage = attempt_usage(json.loads((root/'private/control/quota.json').read_text()), episode, arm)
        except (OSError, ValueError, TypeError, KeyError):
            usage = None, None
        finished = time.time()
        record = {**started, **active_accounting, 'classification': classification, 'outcome': outcome,
            'input_tokens': usage[0], 'output_tokens': usage[1],
            'official_evidence': official['path'] if official else None,
            'official_evidence_sha256': official['sha256'] if official else None,
            'finished_at': finished, 'next_eligible_at': None,
            'detail': decision['reason_code'],
            'stop_reason': ('manual_stop' if original_stop in ('user_stop', 'manual_stop', 'global_stop', 'global_deadline')
                else 'question_deadline' if decision['reason_code'] == 'question_deadline'
                else 'recovered_controller_interruption')}
        if classification == 'infrastructure':
            prior = store.scan([TaskIdentity(**started['task'])]).attempts
            failures = sum(r['classification'] == 'infrastructure' for r in prior) + 1
            record['next_eligible_at'] = finished + RetryPolicy().backoff_seconds(failures)
        return record
    async def regrade(launch, started, inspection):
        return await resume_same_attempt_regrade(store, spec, env, launch, started, inspection, lease=lease)
    return await reconcile_progress(store, RecoveryCallbacks(inspect, stop_broker, clean, recover,
        regrade if spec is not None else None))


def verify_broker_cleanup(broker_root, run_id, authority):
    """Read-only exact broker process/container/network terminal verification."""
    from .rsi_accounting import _read
    from .rsi_recovery import _valid_identity, probe_process_identity

    broker_root = Path(broker_root)
    if any(authority.get(key) is not True for key in ('stopped', 'removed', 'networks_confirmed', 'terminal_available')):
        raise ValueError('trusted authority physical cleanup unconfirmed')
    start, _ = _read(broker_root/'controller-start.json')
    end, _ = _read(broker_root/'controller-end.json')
    identity = start.get('child_process_identity')
    if (start.get('run_id') != run_id or not _valid_identity(identity)
            or start.get('child_pid') != identity['pid'] or start.get('child_group') != identity['pid']
            or probe_process_identity(identity).get('state') != 'not_running' or end != authority):
        raise ValueError('strong authority process terminal evidence required')
    service, _ = _read(broker_root/'service-identity.json')
    networks, _ = _read(broker_root/'networks.json')
    cid_path = broker_root/'container.cid'
    if any(p.is_symlink() for p in (cid_path, *cid_path.parents)):
        raise ValueError('redirected authority container identity')
    cid = cid_path.read_text().strip()
    controller = start.get('controller_id')
    if (not re.fullmatch(r'[a-f0-9]{64}', cid) or service.get('container_id') != cid
            or not isinstance(controller, str) or not re.fullmatch(r'[a-f0-9]{32}', controller)
            or networks.get('schema_version') != 1 or networks.get('controller_id') != controller
            or not isinstance(networks.get('attempts'), dict) or not isinstance(networks.get('egress'), dict)):
        raise ValueError('exact authority container/network identity missing')
    network_cleanups = []
    records = [('ipc', owner, record) for owner, record in networks['attempts'].items()]
    records.append(('egress', run_id, networks['egress']))
    for role, owner, record in records:
        if not isinstance(record, dict) or not isinstance(record.get('cleanup'), dict):
            raise ValueError('authority network cleanup record malformed')  # noqa: TRY004 -- persisted evidence
        identity = hashlib.sha256((controller+'\0'+role+'\0'+owner).encode()).hexdigest()[:24]
        labels = {'org.memweave.eval.broker_run': run_id,
                  'org.memweave.eval.broker_controller': controller,
                  'org.memweave.eval.broker_role': role, 'org.memweave.eval.broker_owner': owner}
        cleanup = record.get('cleanup', {})
        if (record.get('name') != f'memweave-broker-{role}-{identity}'
                or record.get('labels') != labels or record.get('internal') is not (role == 'ipc')
                or not isinstance(record.get('id'), str) or not re.fullmatch(r'[a-f0-9]{64}', record['id'])
                or record.get('removed') is not True or cleanup.get('confirmed') is not True
                or cleanup.get('network_name') != record['name'] or cleanup.get('network_id') != record['id']):
            raise ValueError('exact authority network cleanup unconfirmed')
        network_cleanups.append(cleanup)
    if authority.get('network_cleanup') != network_cleanups:
        raise ValueError('authority cleanup omits registered networks')
    paths = [broker_root/name for name in ('controller-start.json', 'controller-end.json',
              'container.cid', 'service-identity.json', 'networks.json')]
    return [{'path': str(path), 'sha256': file_digest(path)} for path in paths]


def verify_launch_cleanup(root, authority, attempt_proofs, accounting):
    """Recheck stopped physical ownership and request terminals, not known usage.

    The same check is usable when replaying immutable daemon-journal evidence.
    A stopped broker without request terminal coverage is not a settled launch.
    """
    from .rsi_accounting import _read, _verified_report
    from .rsi_recovery import _lifecycle, _valid_identity, probe_process_identity

    root = Path(root)
    if not isinstance(accounting.get('source'), dict) or not accounting['source'].get('transport_terminal'):
        raise ValueError('verified request terminal evidence required before launch settlement')
    verified, raw_paths = _verified_report(accounting)
    principals, _ = _read(root/'principals.json')
    registered = principals.get('principals')
    if (not isinstance(registered, list) or len(registered) != len(verified['attempts'])
            or sorted(registered, key=lambda p: (p['episode'], p['arm'])) !=
            [{'episode': p['episode'], 'arm': p['arm']} for p in verified['attempts']]):
        raise ValueError('request terminal does not cover registered launch principals')
    if any(not Path(path).is_relative_to(root/'private/control') for path in raw_paths):
        raise ValueError('request terminal evidence belongs to another launch')
    broker_evidence = verify_broker_cleanup(root/'private/broker', root.name, authority)
    expected_attempts = {path/'output/container-cleanup.json'
                         for path in (root/'results').glob('task-*/variant-*/attempt-*')}
    if len(attempt_proofs) != len(expected_attempts) or set(map(Path, attempt_proofs)) != expected_attempts:
        raise ValueError('attempt cleanup evidence does not cover every physical attempt')
    evidence_paths = [root/'principals.json', root/'authority-cleanup.json']
    for path in attempt_proofs:
        path = Path(path)
        if not path.is_relative_to(root):
            raise ValueError('attempt cleanup evidence belongs to another launch')
        cleanup, _ = _read(path)
        if cleanup.get('confirmed') is not True or cleanup.get('processes_confirmed') is not True:
            raise ValueError('strong attempt process/resource cleanup unconfirmed')
        launches = cleanup.get('host_launches')
        if not isinstance(launches, dict) or not set(launches) <= {'actor', 'regrade'}:
            raise ValueError('attempt host launch ownership missing')
        for phase in ('actor', 'regrade'):
            info = launches.get(phase)
            artifacts = [path.parent/'harbor'/phase, *(path.parent/'lifecycle'/f'{phase}.{kind}.json'
                         for kind in ('start', 'lease', 'end'))]
            if info is None:
                if any(p.exists() or p.is_symlink() for p in artifacts):
                    raise ValueError('unregistered attempt process artifacts')
                continue
            if not isinstance(info, dict) or any(type(info.get(k)) is not bool for k in
                    ('spawned', 'preexisting_artifacts', 'execution_artifacts_present')):
                raise ValueError('attempt host launch ownership malformed')
            if not info['spawned'] and not info['preexisting_artifacts'] and not info['execution_artifacts_present']:
                if any(p.exists() or p.is_symlink() for p in artifacts):
                    raise ValueError('unspawned attempt has process artifacts')
                continue
            config_path = path.parent/'configs'/f'{phase}.json'
            lifecycle = _lifecycle(path.parent, phase, file_digest(config_path), probe_process_identity)
            if (not _valid_identity(lifecycle['start']['raw'].get('process_identity'))
                    or lifecycle['process'].get('state') != 'not_running'
                    or not lifecycle['end'] or lifecycle['end']['raw'].get('status') != 'terminal'
                    or lifecycle['end']['raw'].get('process_identity') !=
                    lifecycle['start']['raw']['process_identity']):
                raise ValueError('strong attempt process terminal evidence required')
            evidence_paths.extend([config_path, artifacts[1], artifacts[3]])
        evidence_paths.append(path)
    references = [{'path': str(path), 'sha256': file_digest(path)} for path in evidence_paths]
    return [*references[:2], *broker_evidence, *references[2:]]


async def execute_launch(spec, directory, *, split, approved_budget_usd, variant, catalog,
                         tasks, identity, contract, store, resume, plan, lock, env,
                         baseline_result, baseline_changes, launch_cost_limit=None, launch_deadline=None, lease=None):
    from .rsi_environment import DaemonLease

    if not isinstance(lease, DaemonLease) or not lease.active:
        raise ValueError('live daemon lease required before execution')
    from .budget_guard import initialize
    from .images import inspect_image
    from .rsi_accounting import recovered_accounting
    from .rsi_execution import make_executor
    from .rsi_scheduler import RetryPolicy
    from .runner import auth_file, require_primary_time
    from .trusted_broker import TrustedBroker

    original_paths = source_paths(spec, dict(catalog, tasks=[row for row in catalog['tasks']
        if split == 'all' or row['split'] == split]))
    root = spec.root/'runs'/(spec.id+'-'+uuid.uuid4().hex[:12])
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    control = root/'private/control'
    stop = control/'STOP_REQUESTED'
    end = None if spec.unbounded else (launch_deadline or time.time()+spec.max_elapsed_seconds)
    cost_limit = None if spec.unbounded else (spec.max_cost_usd if launch_cost_limit is None else launch_cost_limit)
    resource = admission_capacity(plan)
    available = ResourceAmounts(**resource['budget'])
    fitting = {(row['benchmark'], row['task_id']) for row in resource['requirements']
               if ResourceAmounts(**row['original']).fits(available)}
    ready_paths = [path for key, path in original_paths.items()
                   if '/'.join(key) in lock['preparations'] and key in fitting]
    verifier_reserve = max(1500, 180+max(tomllib.loads((p/'task.toml').read_text())['verifier']['timeout_sec']
                                       for p in ready_paths))
    actor_end = None if end is None else end-verifier_reserve
    if end is not None:
        require_primary_time(ready_paths, actor_end, end)
    initialize(control/'quota.json', cost_limit, actor_end, unbounded=spec.unbounded,
               arm_limits={} if spec.unbounded else {variant: cost_limit})
    (control/'WRITER_PLATFORM').write_text('linux\n')
    inspect_image(lock['broker_image'], env)
    execution_policy = contract.get('execution_policy')
    active = is_active_policy(execution_policy)
    policy = RetryPolicy(task_timeout_seconds=execution_policy['task_timeout_seconds']) if active else RetryPolicy()
    principal_limits = {(task.benchmark, task.task_id):
        resume.next_attempt_index.get((task.benchmark, task.task_id, identity.variant_id), 1)
        + physical_principal_bound(policy, spec.max_attempts)-1 for task in tasks} if active else None
    principals = []
    for task in tasks:
        if task.benchmark+'/'+task.task_id not in lock['preparations'] or (
                task.benchmark, task.task_id) not in fitting:
            continue
        start = resume.next_attempt_index.get((task.benchmark, task.task_id, identity.variant_id), 1)
        principals.extend({'arm': identity.variant_id,
            'episode': episode_id(root.name, task.benchmark+'/'+task.task_id, identity.variant_id, index)}
            for index in range(start, start+physical_principal_bound(policy, spec.max_attempts)))
    atomic_json(root/'principals.json', {'principals': principals}, immutable=True)
    from .rsi_environment import clock_admission_guard

    qualified_daemon = plan.get('environment', {}).get('qualification_identity', {}).get('daemon')
    daemon_id = qualified_daemon.get('ID') if isinstance(qualified_daemon, dict) else None
    scheduler = ExperimentScheduler(root/'results', concurrency=spec.concurrency,
        max_attempts=spec.max_attempts, retry_policy=policy,
        execution_policy=execution_policy, principal_attempt_limits=principal_limits,
        admission_guard=clock_admission_guard(env, root/'admission-checks', daemon_id=daemon_id),
        resource_budget=ResourceAmounts(**resource['budget']),
        task_resources={(row['benchmark'], row['task_id']): ResourceAmounts(**row['original'])
                        for row in resource['requirements']})
    prepared_path = Path(lock.get('admission_path', directory/'prepared.json'))
    atomic_json(root/'run-contract.json', {'config': spec.model_dump(mode='json'),
        **({'execution_policy': execution_policy} if active else {}),
        'prepared_path': str(prepared_path),
        'prepared_sha256': file_digest(prepared_path), 'split': split, 'variant': variant,
        'approved_budget_usd': approved_budget_usd, 'launch_cost_limit': cost_limit, 'deadline': end,
        'provider': 'api.deepseek.com', 'model': 'deepseek-flash', 'resource_admission': resource,
        'progress_series': str(store.directory), 'retry_policy': asdict(policy)}, immutable=True)
    # Resolve the configured credential only after all preparation/capacity gates,
    # but before reserving a new launch. An unavailable credential must not create
    # an unrecoverable empty launch or reset a question's first-start clock.
    auth = json.loads(auth_file().read_text()).get('deepseek', {})
    if auth.get('type') != 'api_key' or not isinstance(auth.get('key'), str) or not auth['key']:
        raise ValueError('configured provider credential unavailable')
    launch_id = store.register_launch(root, root/'results', tasks, contract)
    broker = TrustedBroker(root/'private/broker', control, root.name, lock['broker_image'], env)
    pool = ThreadPoolExecutor(max_workers=spec.concurrency, thread_name_prefix='rsi-trial')
    execute = make_executor(spec=spec, directory=directory, lock=lock, original_paths=original_paths,
        env=env, broker=broker, root=root, control=control, end=end, actor_end=actor_end,
        scheduler=scheduler, worker_pool=pool)
    result = None
    cleanup = {'stopped': False, 'networks_confirmed': False, 'terminal_available': False}
    journal_ticket = lease.begin_work(root.name, root, kind='execution',
        daemon_identity=lock.get('contract', {}).get('environment') or
                        plan.get('environment', {}).get('qualification_identity'),
        evaluator_sha256=lock['evaluator_sha256'])
    try:
        startup = asyncio.create_task(asyncio.to_thread(broker.start, auth['key'], principals))
        _, cancelled = await drain_owned_work(startup)
        if cancelled:
            raise asyncio.CancelledError
        result = await scheduler.run(tasks, [identity], execute, resume_state=resume,
            admitted_task_keys={tuple(key.split('/', 1)) for key in lock['preparations']})
    finally:
        stop.touch()
        pool.shutdown(wait=True, cancel_futures=True)
        cancelled = False
        if broker.process is not None:
            work = asyncio.create_task(asyncio.to_thread(broker.stop))
            cleanup, cancelled = await drain_owned_work(work)
            atomic_json(root/'authority-cleanup.json', cleanup, immutable=True)
        physical = cleanup.get('stopped') is True and cleanup.get('networks_confirmed') is True
        attempts = list((root/'results').glob('task-*/variant-*/attempt-*'))
        attempt_proofs = [path/'output/container-cleanup.json' for path in attempts]
        physical = physical and all(path.is_file() and json.loads(path.read_text()).get('confirmed') is True
                                     for path in attempt_proofs)
        if physical:
            accounting = recovered_accounting(control, principals=principals, broker_stopped=True)
            evidence = verify_launch_cleanup(root, cleanup, attempt_proofs, accounting)
            atomic_json(root/'accounting.json', accounting, immutable=True)
            proof = root/'launch-cleanup.json'
            atomic_json(proof, {'schema_version': 'rsi-launch-cleanup.v1', 'run_root': str(root),
                'launch_id': launch_id, 'confirmed': True,
                'authority': str(root/'authority-cleanup.json'),
                'attempt_cleanup': [str(path) for path in attempt_proofs],
                'evidence': [*evidence, {'path': str(root/'accounting.json'),
                                        'sha256': file_digest(root/'accounting.json')}]}, immutable=True)
            store.settle_launch(launch_id, proof)
            lease.complete_work(journal_ticket, proof)
        else:
            raise RuntimeError('trusted execution physical cleanup unconfirmed')
        if cancelled:
            raise asyncio.CancelledError
    if result is None:
        raise RuntimeError('no scheduler result available; resume requires reconciliation')
    result, accounting = series_accounting(store, result)
    atomic_json(root/'results/summary-final.json', {'accounting': accounting,
        'summaries': result.summaries, 'tokens': result.tokens,
        'task_progress': list(result.progress), 'attempt_snapshots_unchanged': True}, immutable=True)
    return result_response(result, catalog, spec, variant=variant, reused=False, path=root,
        accounting=accounting, metadata_changes=baseline_changes, baseline_result=baseline_result)
