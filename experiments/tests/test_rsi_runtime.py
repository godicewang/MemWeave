"""RSI integration policy is testable without Docker, credentials or model calls."""


import pytest

from memweave_eval.rsi_runtime import (
    RSIConfig,
    attempt_usage,
    binary_outcome,
    build_single_job,
    load_config,
)


@pytest.fixture(autouse=True)
def isolated_controller_lease(monkeypatch, tmp_path):
    from memweave_eval.rsi_environment import daemon_lease
    monkeypatch.setattr("memweave_eval.rsi_environment.daemon_lease",
                        lambda: daemon_lease(tmp_path/'controller.lock'))


def config(tmp_path, **changes):
    value = {'schema_version': 1, 'id': 'rsi-test', 'catalog': tmp_path/'catalog.json',
                 'source_cache': tmp_path/'cache', 'root': tmp_path/'external',
                 'subject': {'commit': 'a'*40, 'package': tmp_path/'subject.tgz', 'sha256': 'b'*64},
                 'runtime': {'node_version': '24.22.0'}}
    value.update(changes)
    return RSIConfig.model_validate(value)


def runtime_sources(tmp_path, monkeypatch, spec, count=2):
    """Small original-task fixtures; source validation has its own catalog suite."""
    import json

    from memweave_eval import rsi_runtime

    rows, paths = [], {}
    for index in range(count):
        name = f'original-{index:03d}'
        task = tmp_path/'originals'/name
        task.mkdir(parents=True)
        (task/'instruction.md').write_text(f'Original instruction {index}')
        (task/'task.toml').write_text('[verifier]\ntimeout_sec=1\n')
        row = {'suite_id': 'terminal-bench-4', 'task_id': name,
               'sha256': 'd'*64, 'original_path': name,
               'split': 'regression' if index < (40 if count == 200 else 1) else 'capability'}
        rows.append(row)
        paths[(row['suite_id'], name)] = task
    catalog = {'sources': [{'id': 'terminal-bench-4', 'revision': 'e'*40}], 'tasks': rows}
    spec.catalog.write_text(json.dumps(catalog))
    monkeypatch.setattr(rsi_runtime, 'load_catalog', lambda *a: catalog)
    monkeypatch.setattr(rsi_runtime, 'validate_catalog', lambda *a: None)
    monkeypatch.setattr(rsi_runtime, 'source_paths', lambda spec, selected: {
        (row['suite_id'], row['task_id']): paths[(row['suite_id'], row['task_id'])]
        for row in selected['tasks']})
    monkeypatch.setattr(rsi_runtime, 'tool_env', lambda *a: {})
    return catalog, paths


def test_default_twenty_and_no_four_instance_ceiling(tmp_path):
    assert config(tmp_path).concurrency == 20
    assert config(tmp_path, concurrency=50).concurrency == 50
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            config(tmp_path, concurrency=invalid)


def test_paid_limits_are_not_an_implicit_authorization(tmp_path):
    assert config(tmp_path).max_cost_usd is None
    with pytest.raises(ValueError):
        config(tmp_path, max_cost_usd=30.0)
    with pytest.raises(ValueError):
        config(tmp_path, model={'id': 'other'})


def test_original_binary_judgment_only():
    assert binary_outcome({'verifier_result': {'rewards': {'reward': 1}}}) == 'passed'
    assert binary_outcome({'verifier_result': {'rewards': {'reward': 0}}}) == 'failed'
    for reward in (True, 0.5, None, '1'):
        assert binary_outcome({'verifier_result': {'rewards': {'reward': reward}}}) == 'error'
    assert binary_outcome({'exception_info': {'exception_type': 'timeout'},
                           'verifier_result': {'rewards': {'reward': 1}}}) == 'error'


def test_usage_counts_failed_attempts_and_unknown_reservations():
    ledger = {'requests': {
        'a': {'episode': 'ep', 'arm': 'pi-native', 'status': 'settled', 'input': 4, 'output': 5},
        'b': {'episode': 'ep', 'arm': 'pi-native', 'status': 'settled', 'input': 6, 'output': 7},
        'c': {'episode': 'other', 'arm': 'pi-native', 'status': 'settled', 'input': 99, 'output': 99}}}
    assert attempt_usage(ledger, 'ep', 'pi-native') == (10, 12)
    ledger['requests']['d'] = {'episode': 'ep', 'arm': 'pi-native', 'status': 'reserved'}
    assert attempt_usage(ledger, 'ep', 'pi-native') == (None, None)


def test_single_job_has_one_fresh_trial_and_no_sampling_override(tmp_path):
    cfg = build_single_job(config(tmp_path), tmp_path, 'trial', tmp_path/'task', 'tb4',
                           variant='pi-memweave', runtime_plan=tmp_path/'plan.json',
                           runtime_objects={})
    assert cfg['n_attempts'] == cfg['n_concurrent_trials'] == 1
    assert cfg['retry']['max_retries'] == 0
    options = cfg['agents'][0]['kwargs']
    assert options['evaluation_primary_default'] is True
    assert 'thinking' not in options and 'max_turns' not in options
    assert options['auth_path'] == ''
    assert options['evaluation_output_tokens'] == 384000
    assert cfg['environment']['delete'] is True


def test_swe_actor_disabled_verifier_and_official_fresh_replay(tmp_path):
    spec = config(tmp_path)
    actor = build_single_job(spec, tmp_path, 'actor', tmp_path/'task', 'swe-pro-v2',
                            variant='pi-native', runtime_plan=tmp_path/'plan.json')
    assert actor['verifier']['disable'] is True
    replay = build_single_job(spec, tmp_path, 'replay', tmp_path/'task', 'swe-pro-v2',
                             source_job=tmp_path/'harbor/actor')
    assert replay['agents'][0]['import_path'] == 'patch_replay:PatchReplayAgent'
    assert 'verifier' not in replay


def test_prepare_only_never_reads_auth_or_sets_deadline(tmp_path):
    cfg = build_single_job(config(tmp_path), tmp_path, 'prepare', tmp_path/'task', 'tb4',
                           variant='pi-native', runtime_plan=tmp_path/'plan.json', prepare_only=True)
    assert cfg['verifier']['disable'] is True
    assert cfg['agents'][0]['kwargs']['prepare_only'] is True
    assert 'evaluation_deadline' not in cfg['agents'][0]['kwargs']
    assert 'evaluation_broker_client' not in cfg['agents'][0]['kwargs']


def test_relative_paths_resolve_from_configuration(tmp_path):
    path = tmp_path/'input.yaml'
    path.write_text('schema_version: 1\nid: demo\ncatalog: catalog.json\n'
                    'source_cache: /tmp/source-cache\nroot: /tmp/rsi-runtime-test\n'
                    'subject:\n  commit: '+ 'a'*40 + '\n  package: subject.tgz\n  sha256: '+
                    'b'*64+'\nruntime:\n  node_version: 24.22.0\n')
    result = load_config(path)
    assert result.catalog == tmp_path/'catalog.json'
    assert result.subject.package == tmp_path/'subject.tgz'


def test_overlay_owner_is_unique_not_generic_output(tmp_path):
    from memweave_eval.rsi_runtime import _overlay
    one = tmp_path/'one/output'
    two = tmp_path/'two/output'
    one.mkdir(parents=True)
    two.mkdir(parents=True)
    first = _overlay(one, config(tmp_path), role='actor', broker_network='memweave-broker-ipc-'+'a'*24, controlled=True, owner='run-episode-1').read_text()
    second = _overlay(two, config(tmp_path), role='actor', broker_network='memweave-broker-ipc-'+'b'*24, controlled=True, owner='run-episode-2').read_text()
    assert 'run-episode-1' in first and 'run-episode-2' in second
    assert 'host-gateway' not in first
    assert 'harbor-docker-egress-control-sidecar' in first


def test_exact_cleanup_queries_never_inspect_unrelated_containers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from memweave_eval.rsi_runtime import cleanup_attempt, trial_projects
    trial = 'task__abcXYZ1'
    folder = tmp_path/'harbor/actor'/trial
    folder.mkdir(parents=True)
    (folder/'config.json').write_text('{"trial_name":"'+trial+'"}')
    calls = []
    live = {'abcdef123456'}

    def fake(argv, **kwargs):
        calls.append(argv)
        if 'rm' in argv:
            live.clear()
        if 'ps' in argv:
            assert '--filter' in argv and 'label=' in argv[argv.index('--filter')+1]
            return SimpleNamespace(returncode=0, stdout='\n'.join(live))
        return SimpleNamespace(returncode=0, stdout='')

    monkeypatch.setattr('memweave_eval.rsi_runtime.subprocess.run', fake)
    assert cleanup_attempt(tmp_path, 'unique-attempt', {'DOCKER_HOST':'dedicated'})['confirmed']
    actor, verifier = trial_projects(trial)
    assert any('label=com.docker.compose.project='+actor in call for call in calls)
    assert any('label=com.docker.compose.project='+verifier in call for call in calls)
    assert not any('inspect' in call for call in calls)


def test_verifier_project_matches_pinned_harbor_algorithm():
    from types import SimpleNamespace

    from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
    from harbor.trial.trial import Trial

    from memweave_eval.rsi_runtime import trial_projects
    for trial in ('task__abcXYZ1', 'very-long-original-task-id-1234567890__ABCDEFG', 'X'*75):
        instance = SimpleNamespace(config=SimpleNamespace(trial_name=trial))
        expected = _sanitize_docker_compose_project_name(
            Trial._separate_verifier_session_id(instance, 'trial'))
        assert trial_projects(trial)[1] == expected


def test_cleanup_failure_does_not_claim_reap(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from memweave_eval.rsi_runtime import cleanup_attempt
    monkeypatch.setattr('memweave_eval.rsi_runtime.subprocess.run',
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout=''))
    assert cleanup_attempt(tmp_path, 'owned-run', {})['confirmed'] is False


@pytest.fixture
def offline_preparation(tmp_path, monkeypatch):
    """Exercise real RSI prepare wiring and Harbor schemas, fake only external work."""
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from test_rsi_helpers import fake_docker

    helper_docker = fake_docker(monkeypatch)

    from harbor.models.job.config import JobConfig

    from memweave_eval import (
        budget_guard,
        images,
        rsi_runtime,
        runner,
        runtime_cache,
        trusted_broker,
    )

    spec = config(tmp_path)
    spec.catalog.write_text('{}')
    rows = [
        {'suite_id': suite, 'task_id': name, 'original_path': name,
         'sha256': 'c'*64, 'split': 'regression'}
        for suite, name in [('terminal-bench-4', 'terminal-original'),
                            ('swe-bench-pro-v2', 'swe-original')]
    ]
    catalog = {'sources': [{'id': row['suite_id'], 'revision': 'd'*40} for row in rows],
               'tasks': rows}
    sources = {}
    for row in rows:
        path = tmp_path/'originals'/row['task_id']
        path.mkdir(parents=True)
        (path/'instruction.md').write_text('Original task input')
        (path/'task.toml').write_text('[environment]\ncpus=1\nmemory_mb=4096\nstorage_mb=10240\n')
        sources[row['suite_id'], row['task_id']] = path
    state = SimpleNamespace(spec=spec, destination=tmp_path/'prepared', rows=rows,
                            jobs=[], authorities=[], proof_changes={}, backend_changes={}, probe_requests=0,
                            omit_transport=False, environment_ready=True, cleanup_confirmed=True, results={},
                            rewards={}, prepare_inputs=[], helper_docker=helper_docker)
    monkeypatch.setattr(rsi_runtime, 'validate_catalog', lambda *a: {})
    monkeypatch.setattr(runner, 'verify_package', lambda *a: {})
    state.environment_identity = {'schema_version': 1, 'docker_endpoint': 'synthetic-dedicated',
        'daemon': {'ID': 'synthetic-daemon', 'ServerVersion': '28.5.1',
                   'Architecture': 'aarch64', 'OSType': 'linux', 'NCPU': 12, 'MemTotal': 42*1024**3},
        'tools': {'python_version': [3, 12, 10], 'harbor_version': '0.24.0',
                  'node_version': 'v24.22.0', 'pi_versions': {'pi-ai': '1.4.0', 'pi-coding-agent': '1.4.0'}},
        'dependency_locks': {'uv.lock': 'a'*64, 'package-lock.json': 'b'*64}}
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', lambda *a, **k: {
        'environment': {'ready': state.environment_ready,
                        'qualification_identity': state.environment_identity},
        'requirements': [{'cpus': 2, 'memory_mb': 8192, 'storage_mb': 20480}]})
    monkeypatch.setattr(rsi_runtime, 'load_catalog', lambda *a: catalog)
    monkeypatch.setattr(rsi_runtime, 'source_paths', lambda *a: sources)
    monkeypatch.setattr(rsi_runtime, 'tool_env', lambda *a: {'DOCKER_HOST': 'dedicated-only'})
    monkeypatch.setattr(rsi_runtime, 'task_digest', lambda *a: 'c'*64)
    monkeypatch.setattr(rsi_runtime, 'require_preparation_storage', lambda *a: None)
    monkeypatch.setattr(rsi_runtime, 'cleanup_attempt', lambda *a: {'confirmed': state.cleanup_confirmed})
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('free gate accessed credentials'))
    def broker_probe(argv, **kwargs):
        from memweave_eval.rsi_broker_probe import PROBE, SCOPE
        if argv[:2] != ['docker', 'run'] or PROBE not in argv:
            pytest.fail('unexpected external process')
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({
            'schema_version': 1, 'passed': True, 'scope': SCOPE,
            'code_sha256': json.loads(argv[-1]), 'python_version': [3, 9, 23]}))
    monkeypatch.setattr(rsi_runtime.subprocess, 'run', broker_probe)

    def prepare_task(task, destination, platform, deadline, env, limits, **kwargs):
        state.prepare_inputs.append((task.name, kwargs))
        assert env == {'DOCKER_HOST': 'dedicated-only'}
        assert limits == {'max_cpus': 2, 'max_memory_mb': 8192, 'max_storage_mb': 20480}
        relative = 'runtime/'+task.name
        (destination/relative).mkdir(parents=True)
        (destination/relative/'task.toml').write_text((task/'task.toml').read_text())
        from memweave_eval.storage import atomic_json, file_digest
        from memweave_eval.suites import task_digest
        record = {'task_id': task.name, 'runtime_path': relative,
                  'source_sha256': 'c'*64, 'runtime_sha256': task_digest(destination/relative),
                  'platform': platform, 'protocol_equivalent': True,
                  'config_diff': 'preparation/task.toml.diff',
                  'images': {'main': {'reference': 'official:'+task.name, 'id': 'sha256:'+'a'*64,
                                     'platform': platform, 'repo_digests': [],
                                     'build_log': 'preparation/main.log'}}}
        manifest = destination/'preparation/manifest.json'
        atomic_json(manifest, record, immutable=True)
        (destination/record['config_diff']).write_text('unchanged original protocol')
        return dict(record, manifest_path='preparation/manifest.json',
                    manifest_sha256=file_digest(manifest))

    monkeypatch.setattr(images, 'prepare_task', prepare_task)
    monkeypatch.setattr(images, 'inspect_image', lambda reference, env: {
        'reference': reference, 'id': 'sha256:'+'a'*64, 'platform': 'linux/amd64', 'repo_digests': []})
    def fake_images(record, env=None, **kwargs):
        return {record['task_id']: {'reference': 'official:'+record['task_id'], 'id': 'sha256:'+'a'*64,
                            'platform': 'linux/amd64', 'repo_digests': [], 'libc': 'gnu'}}
    state.real_prepared_images = rsi_runtime.prepared_images
    monkeypatch.setattr(rsi_runtime, 'prepared_images', fake_images)
    monkeypatch.setattr('memweave_eval.rsi_image_metadata.cached_images',
                        lambda frozen, *, prepared=None: fake_images(prepared or frozen))
    monkeypatch.setattr(runtime_cache, 'create_plan', lambda *a: {'schema_version': 1})
    monkeypatch.setattr(runtime_cache, 'snapshot', lambda *a: {'node': 'fixed-public-object'})

    def initialize(path, *a, **k):
        path.parent.mkdir(parents=True)
        path.write_text('{}')

    monkeypatch.setattr(budget_guard, 'initialize', initialize)

    class FakeAuthority:
        def __init__(self, root, control, episode, image, env):
            self.root, self.control, self.episode = root, control, episode
            self.process = None
            self.clients = {}
            self.stopped = False
            state.authorities.append(self)

        def start(self, credential, principals, *, fixture=False):
            assert fixture is True
            assert credential == 'synthetic-fixture-not-a-provider-credential'
            self.root.mkdir(parents=True)
            self.process = object()
            identity = {'schema': 'rsi-process-identity-v1', 'status': 'captured', 'pid': 123,
                        'platform': 'linux', 'host_boot_id': 'test-boot',
                        'start_identity': 'test-start', 'precision': 'test-precision',
                        'command_sha256': 'a'*64}
            (self.root/'controller-start.json').write_text(json.dumps({
                'run_id': self.episode, 'child_pid': 123, 'child_group': 123,
                'child_process_identity': identity}))
            for principal in principals:
                client = self.root/(principal['arm']+'.json')
                client.write_text('{}')
                self.clients[principal['episode'], principal['arm']] = client

        def connect_attempt(self, owner):
            return 'memweave-broker-ipc-'+'a'*24

        def disconnect_attempt(self, owner):
            return {'confirmed': True}

        def stop(self):
            self.stopped = True
            (self.control/'quota.final.json').write_text(json.dumps({
                'schema_version': 1, 'requests': {}, 'exposure_usd': 0}))
            (self.control/'transport-terminal.json').write_text(json.dumps({
                'schema_version': 'trusted-transport-terminal.v1', 'finalized': True,
                'audit_events': 1, 'audit_head': 'a'*64,
                'entries': [{'episode': self.episode, 'arm': variant,
                             'admitted_request_ids': [], 'http_request_ids': [],
                             'terminal_request_ids': []}
                            for variant in ('pi-native', 'pi-memweave')]}))
            result = {'stopped': True, 'removed': True, 'terminal_available': True,
                      'networks_confirmed': True}
            from test_rsi_launch_cleanup_gates import broker_bindings
            broker_bindings(self.root.parent, result, broker_root=self.root, run_id=self.episode)
            (self.root/'controller-end.json').write_text(json.dumps(result))
            return result

    monkeypatch.setattr('memweave_eval.rsi_recovery.probe_process_identity',
                        lambda _: {'state': 'not_running'})
    monkeypatch.setattr(trusted_broker, 'TrustedBroker', FakeAuthority)

    def execute(cfg, destination, env, *args, **kwargs):
        # Keep the pinned Harbor contract real, including both original controls
        # and the full ExperimentPi job kwargs produced by build_single_job.
        parsed = JobConfig.model_validate(cfg)
        assert parsed.n_attempts == 1
        state.jobs.append(cfg)
        from memweave_eval.storage import atomic_json, file_digest
        config_path = destination/'configs'/f"{cfg['job_name']}.json"
        atomic_json(config_path, cfg, immutable=True)
        started = {'job_name': cfg['job_name'], 'identity': 'mock-process',
                   'config_sha256': file_digest(config_path), 'process_identity': {
                       'schema': 'rsi-process-identity-v1', 'status': 'captured', 'pid': 123,
                       'platform': 'darwin', 'host_boot_id': 'test-boot', 'start_identity': '123.456',
                       'precision': 'test-microsecond', 'command_sha256': 'a'*64}}
        atomic_json(destination/'lifecycle'/f"{cfg['job_name']}.start.json", started, immutable=True)
        atomic_json(destination/'lifecycle'/f"{cfg['job_name']}.end.json",
                    dict(started, status='terminal', return_code=0), immutable=True)
        folder = destination/'harbor'/cfg['job_name']/'trial'
        folder.mkdir(parents=True)
        evidence = folder/'result.json'
        reward = 1 if cfg['job_name'].endswith('-oracle') else 0
        reward = state.rewards.get((Path(cfg['tasks'][0]['path']).name, cfg['job_name']), reward)
        raw = {'verifier_result': {'rewards': {'reward': reward}}}
        evidence.write_text(json.dumps(raw))
        state.results[cfg['job_name']] = (evidence, raw)
        if cfg['job_name'].startswith('runtime-'):
            options = cfg['agents'][0]['kwargs']
            assert options['prepare_only'] is True
            assert options['auth_path'] == ''
            assert options['evaluation_broker_client_sha256']
            assert options['runtime_plan_sha256']
            (folder/'agent').mkdir()
            (folder/'agent/mock-backend-preflight.json').write_text(json.dumps({
                'schema_version': 2, 'process_timeout_ms': 4000, 'backend': 'node', 'scope': 'independent-synthetic-quota',
                'node_version': 'v24.22.0', 'node_path': '/private/node/bin/node',
                'command': ['flock', '-x', '/logs/agent/mock-backend-preflight.lock',
                            '/private/node/bin/node', '-e',
                            'process.stdout.write("memweave-node-flock-ready")'],
                'passed': True, 'return_code': 0,
                'error_code': None, 'signal': None, 'stdout': 'memweave-node-flock-ready',
                **state.backend_changes}))
            (folder/'agent/runtime-preflight.json').write_text(
                json.dumps({'model_requests': state.probe_requests}))
            proof = {'real_model_requests': 0, 'positive': True, 'external_authority': True,
                     'lost_guard_upstream_requests': 0, 'actual_cli_pid_deadline': True}
            proof.update(state.proof_changes)
            if not state.omit_transport:
                (folder/'agent/cli-transport-result.json').write_text(json.dumps(proof))
        return 0

    monkeypatch.setattr(runner, 'execute_harbor', execute)
    monkeypatch.setattr(rsi_runtime, '_one_result', lambda root, name, task: state.results[name])
    return state


def test_offline_prepare_integrates_both_variants_and_free_authority(offline_preparation):
    import json

    from memweave_eval.rsi_runtime import prepare

    state = offline_preparation
    result = prepare(state.spec, state.destination)
    assert result['prepared'] and result['model_requests'] == 0
    assert len(state.jobs) == 8  # Two controls and two variants for each original task.
    variants = [job['agents'][0]['kwargs']['variant'] for job in state.jobs
                if job['job_name'].startswith('runtime-')]
    assert variants == ['pi-native', 'pi-memweave'] * 2
    assert all(authority.stopped for authority in state.authorities)
    lock = json.loads((state.destination/'prepared.json').read_text())
    assert lock['transport_verified'] is True
    for record in lock['preparations'].values():
        assert set(record['transport']) == {'pi-native', 'pi-memweave'}
        assert set(record) >= {'oracle', 'nop'}
        for proof in record['backend_probes'].values():
            assert (state.destination/proof['path']).is_file()


@pytest.mark.parametrize('field,value', [
    ('real_model_requests', 1), ('positive', False), ('external_authority', False),
    ('lost_guard_upstream_requests', 1), ('actual_cli_pid_deadline', False),
])
def test_prepare_rejects_bad_transport_and_stops_free_authority(offline_preparation, field, value):
    from memweave_eval.rsi_runtime import prepare

    state = offline_preparation
    state.proof_changes[field] = value
    result = prepare(state.spec, state.destination)
    assert not result['ok']
    assert 'transport positive/negative/stop' in result['blocked'][0]['reason']
    assert all(authority.stopped for authority in state.authorities)
    assert not (state.destination/'prepared.json').exists()
    assert list(state.destination.rglob('incomplete.json'))


def test_prepare_rejects_missing_transport_before_certifying(offline_preparation):
    from memweave_eval.rsi_runtime import prepare

    state = offline_preparation
    state.omit_transport = True
    result = prepare(state.spec, state.destination)
    assert not result['ok'] and 'transport proof missing' in result['blocked'][0]['reason']
    assert state.authorities[0].stopped
    assert not (state.destination/'prepared.json').exists()


def test_prepare_rejects_model_calls_in_free_probe(offline_preparation):
    from memweave_eval.rsi_runtime import prepare

    state = offline_preparation
    state.probe_requests = 1
    result = prepare(state.spec, state.destination)
    assert not result['ok'] and 'no model requests' in result['blocked'][0]['reason']
    assert state.authorities[0].stopped


def test_prepare_capacity_block_retains_no_execution_receipt(offline_preparation):
    from memweave_eval.rsi_runtime import prepare

    state = offline_preparation
    state.environment_ready = False
    result = prepare(state.spec, state.destination)
    assert not result['ok'] and not result['prepared']
    assert all(not row['execution_started'] for row in result['blocked'])
    assert list(state.destination.rglob('blocked/*.json'))
    assert not list(state.destination.rglob('started.json'))
    assert state.jobs == state.authorities == []


@pytest.mark.parametrize('gate', ['missing_budget', 'mismatched_budget', 'capacity', 'transport', 'evaluator'])
def test_run_prepared_rejects_before_any_auth_access(tmp_path, monkeypatch, gate):
    import asyncio
    import json

    from memweave_eval import rsi_runtime, runner

    spec = config(tmp_path, **({} if gate == 'missing_budget' else
                             {'max_cost_usd': 1.0, 'max_elapsed_seconds': 3600}))
    runtime_sources(tmp_path, monkeypatch, spec)
    called = []
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('gates must precede auth'))
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', lambda *a, **k:
                        (called.append('plan') or {'environment': {'ready': gate != 'capacity'}}))
    directory = tmp_path/'prepared'
    directory.mkdir()
    (directory/'prepared.json').write_text(json.dumps({'transport_verified': False,
        'evaluator_sha256': '0'*64 if gate == 'evaluator' else rsi_runtime.evaluator_digest()}))
    expected = {'missing_budget': 'matching new-run budget', 'mismatched_budget': 'matching new-run budget',
                'capacity': 'no credentials read', 'transport': 'preflight not verified',
                'evaluator': 'evaluator or transport code changed'}[gate]
    with pytest.raises(ValueError, match=expected):
        asyncio.run(rsi_runtime.run_prepared(spec, directory, split='regression',
                                            approved_budget_usd=2.0 if gate == 'mismatched_budget' else 1.0))
    assert called == ([] if 'budget' in gate else ['plan'])
    assert not (spec.root/'runs').exists()


@pytest.mark.parametrize('variant', ['pi-native', 'pi-memweave'])
def test_real_harbor_schema_accepts_runtime_and_fresh_swe_replay(tmp_path, variant):
    from harbor.models.job.config import JobConfig

    from memweave_eval.storage import file_digest

    plan = tmp_path/'runtime-assets.json'
    plan.write_text('{"schema_version":1}')
    spec = config(tmp_path)
    actor = build_single_job(spec, tmp_path, 'actor', tmp_path/'original', 'swe-pro-v2',
                            variant=variant, runtime_plan=plan,
                            runtime_objects={'node': 'fixed'})
    parsed = JobConfig.model_validate(actor)
    assert parsed.verifier.disable is True
    assert parsed.agents[0].kwargs['runtime_plan_sha256'] == file_digest(plan)
    assert parsed.agents[0].kwargs['variant'] == variant
    replay = build_single_job(spec, tmp_path, 'regrade', tmp_path/'original', 'swe-pro-v2',
                             source_job=tmp_path/'harbor/actor')
    replay_parsed = JobConfig.model_validate(replay)
    assert replay_parsed.verifier.disable is False
    assert replay_parsed.agents[0].import_path == 'patch_replay:PatchReplayAgent'
    assert replay_parsed.environment.delete is True


def test_cli_all_stage_reaches_active_policy_before_native_complete(offline_execution, monkeypatch):
    from memweave_eval import cli, rsi_cli
    state = offline_execution(count=2)
    state.catalog['id'] = 'rsi-100-v1'
    monkeypatch.setattr(rsi_cli, 'load_config', lambda *a: state.spec)
    assert cli.main(['rsi', 'run', 'unused.yaml', str(state.prepared), '--split', 'all']) == 0
    assert len(state.calls) == 2


def test_prepare_never_seals_when_owned_cleanup_unconfirmed(offline_preparation):
    from memweave_eval.rsi_runtime import prepare
    state = offline_preparation
    state.cleanup_confirmed = False
    result = prepare(state.spec, state.destination)
    assert not result['ok'] and 'cleanup unconfirmed' in result['blocked'][0]['reason']
    assert not (state.destination/'prepared.json').exists()
    assert list(state.destination.rglob('incomplete.json'))


def test_existing_native_baseline_reuses_without_budget_capacity_or_credentials(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from memweave_eval import rsi_baseline, rsi_runtime, runner
    spec = config(tmp_path)
    spec.catalog.write_text('{}')
    record = SimpleNamespace(result=SimpleNamespace(output_root=tmp_path/'original-native'),
                             contract={'max_attempts': 1}, mismatches=lambda contract: [])

    class Store:
        def __init__(self, root, question_digest):
            assert question_digest == 'c'*64

        def lookup(self):
            return record

    monkeypatch.setattr(rsi_baseline, 'BaselineStore', Store)
    catalog_loads = []
    def load_once(_):
        catalog_loads.append(True)
        assert len(catalog_loads) == 1, 'reuse must use one question-set snapshot'
        return {}
    monkeypatch.setattr(rsi_runtime, 'load_catalog', load_once)
    monkeypatch.setattr(rsi_baseline, 'question_set_digest', lambda _: 'c'*64)
    monkeypatch.setattr(rsi_runtime, 'validate_catalog', lambda *a: None)
    monkeypatch.setattr(rsi_runtime, 'native_contract', lambda *a: {})
    def stages(result, catalog, attempts):
        assert attempts == 1  # Preserve original denominator despite current max_attempts=3.
        return {'regression': 40, 'capability': 160}

    monkeypatch.setattr(rsi_runtime, 'stage_summaries', stages)
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', lambda *a, **k: pytest.fail('reuse started preparation'))
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('reuse accessed credentials'))
    result = asyncio.run(rsi_runtime.run_prepared(spec, tmp_path/'prepared', split='all',
                                                  variant='pi-native', approved_budget_usd=None))
    assert result['model_run'] is False and result['reused_native_baseline'] is True
    assert result['stages'] == {'regression': 40, 'capability': 160}
    assert not spec.root.exists()


def test_unbounded_mode_requires_explicit_choice_and_no_conflicting_limits(tmp_path):
    assert config(tmp_path).unbounded is False
    unlimited = config(tmp_path, unbounded=True)
    assert unlimited.max_cost_usd is unlimited.max_elapsed_seconds is None
    with pytest.raises(ValueError, match='unbounded mode'):
        config(tmp_path, unbounded=True, max_cost_usd=1.0)
    with pytest.raises(ValueError, match='unbounded mode'):
        config(tmp_path, unbounded=True, max_elapsed_seconds=1)


def test_unbounded_execution_still_checks_capacity_before_credentials(tmp_path, monkeypatch):
    import asyncio

    from memweave_eval import rsi_runtime, runner
    spec = config(tmp_path, unbounded=True)
    runtime_sources(tmp_path, monkeypatch, spec)
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', lambda *a, **kw: {'environment': {'ready': False}})
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('unexpected credential read'))
    with pytest.raises(ValueError, match='no credentials read'):
        asyncio.run(rsi_runtime.run_prepared(spec, tmp_path/'prepared', split='regression',
                                             approved_budget_usd=None))


def test_unbounded_run_retains_finite_original_task_time_envelope(tmp_path):
    from memweave_eval.rsi_runtime import original_time_envelope
    task = tmp_path/'task'
    task.mkdir()
    (task/'task.toml').write_text('[environment]\nbuild_timeout_sec=600\n'
        '[agent]\ntimeout_sec=3000\n[verifier]\ntimeout_sec=1200\n')
    actor, end = original_time_envelope(task, now=10)
    assert actor >= 10+600+3000
    assert end >= actor+1200+600
    assert end < float('inf')


def test_owned_work_drains_after_repeated_cancellation():
    import asyncio

    from memweave_eval.rsi_runtime import drain_owned_work

    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        async def work():
            started.set()
            await finish.wait()
            return 'cleanup-confirmed'
        child = asyncio.create_task(work())
        parent = asyncio.create_task(drain_owned_work(child))
        await started.wait()
        parent.cancel()
        await asyncio.sleep(0)
        parent.cancel()
        await asyncio.sleep(0)
        assert not parent.done() and not child.cancelled()
        finish.set()
        assert await parent == ('cleanup-confirmed', True)
    asyncio.run(scenario())


def test_preparation_stops_when_images_consume_required_disk(tmp_path, monkeypatch):
    from memweave_eval import rsi_environment
    from memweave_eval.rsi_runtime import require_preparation_storage
    task = tmp_path/'large-original'
    task.mkdir()
    (task/'task.toml').write_text('[environment]\ncpus=1\nmemory_mb=4096\nstorage_mb=10240\n')
    monkeypatch.setattr(rsi_environment, 'available_storage_mb', lambda env: 25000)
    with pytest.raises(ValueError, match='storage no longer fits'):
        require_preparation_storage(config(tmp_path), task, {})


@pytest.mark.parametrize('container_ok,network_ok,throws', [
    (False, True, False), (True, False, False), (True, True, True), (True, True, False),
])
def test_attempt_cleanup_retains_network_until_containers_confirmed(tmp_path, monkeypatch,
                                                                  container_ok, network_ok, throws):
    import asyncio

    from memweave_eval import rsi_runtime
    called = []
    monkeypatch.setattr(rsi_runtime, 'cleanup_attempt', lambda *a: {'confirmed': container_ok})
    class Broker:
        def disconnect_attempt(self, owner):
            called.append(owner)
            if throws:
                raise OSError('sanitized')
            return {'confirmed': network_ok}
    cleanup, cancelled = asyncio.run(rsi_runtime.finish_attempt_resources(tmp_path, 'owned', {}, Broker()))
    assert cleanup['confirmed'] is (container_ok and network_ok and not throws)
    assert called == (['owned'] if container_ok else [])
    assert cancelled is False


@pytest.mark.parametrize('role', ['actor', 'verifier'])
@pytest.mark.parametrize('controlled', [False, True])
@pytest.mark.parametrize('broker', [False, True])
def test_overlay_role_not_network_controls_actor_capabilities(tmp_path, role, controlled, broker):
    import yaml

    from memweave_eval.rsi_runtime import _overlay
    root = tmp_path/'overlay'
    root.mkdir()
    if role == 'verifier' and broker:
        with pytest.raises(ValueError, match='verifier'):
            _overlay(root, config(tmp_path), role=role, controlled=controlled,
                     broker_network='memweave-broker-ipc-'+'a'*24)
        assert not (root/'platform.yaml').exists()
        return
    value = yaml.safe_load(_overlay(root, config(tmp_path), role=role, controlled=controlled,
        broker_network=('memweave-broker-ipc-'+'a'*24) if broker else None).read_text())
    main = value['services']['main']
    assert main.get('cap_drop', []) == (['NET_RAW'] if role == 'actor' else [])
    assert 'cap_add' not in main and 'privileged' not in main
    if role == 'verifier':
        assert set(main) == {'platform', 'labels', 'pull_policy'}
    assert main['pull_policy'] == 'never'
    if broker and controlled:
        sidecar = value['services']['harbor-docker-egress-control-sidecar']
        assert set(sidecar) == {'labels', 'networks'}
        assert 'networks' not in main and 'network_mode' not in main
    elif broker:
        assert 'broker_ipc' in main['networks']


def test_overlay_requires_explicit_valid_role(tmp_path):
    from memweave_eval.rsi_runtime import _overlay
    with pytest.raises(TypeError):
        _overlay(tmp_path, config(tmp_path))
    with pytest.raises(ValueError, match='role'):
        _overlay(tmp_path, config(tmp_path), role='unknown')


def test_preparation_controls_share_restricted_actor_permissions(offline_preparation):
    import yaml

    from memweave_eval.rsi_runtime import prepare

    state = offline_preparation
    original = state.spec.source_cache.parent/'originals'/'swe-original'/'task.toml'
    with original.open('a') as stream:
        stream.write('network_mode="no-network"\n')
    prepare(state.spec, state.destination)
    for job in state.jobs:
        with open(job['environment']['extra_docker_compose'][0]) as stream:
            document = yaml.safe_load(stream)
        expected = ['NET_RAW']
        assert document['services']['main'].get('cap_drop', []) == expected
        if job['agents'][0].get('name') in ('oracle', 'nop'):
            assert 'networks' not in document


@pytest.mark.parametrize('exit_code,exception,expected_detail', [
    (0, None, False), (1, 'RuntimeError', True),
    (124, 'AgentTimeoutError', True), (1, 'NonZeroAgentExitCodeError', True),
])
def test_swe_actor_evidence_survives_official_regrading(tmp_path, exit_code, exception, expected_detail):
    import json

    from memweave_eval.rsi_runtime import record_actor_phase
    from memweave_eval.storage import file_digest

    raw = {'exception_info': {'exception_type': exception}} if exception else {}
    evidence = tmp_path/'actor-result.json'
    evidence.write_text(json.dumps(raw))
    detail = record_actor_phase(tmp_path, evidence, raw, exit_code)
    proof = json.loads((tmp_path/'actor-status.json').read_text())
    assert proof['result_path'] == str(evidence)
    assert proof['result_sha256'] == file_digest(evidence)
    assert proof['return_code'] == exit_code
    assert proof['exception_type'] == exception
    assert bool(detail) is expected_detail
    assert proof['fresh_regrade_required'] is True
    if exception:
        assert exception in detail


def test_actor_phase_never_copies_provider_exception_body(tmp_path):
    import json

    from memweave_eval.rsi_runtime import record_actor_phase

    evidence = tmp_path/'actor-result.json'
    evidence.write_text('{}')
    raw = {'exception_info': {'exception_type': 'invalid private provider body',
                              'exception_message': 'secret response body'}}
    detail = record_actor_phase(tmp_path, evidence, raw, 1)
    text = (tmp_path/'actor-status.json').read_text()
    assert 'private provider body' not in text+detail
    assert 'secret response body' not in text+detail
    assert json.loads(text)['exception_type'] == 'UnclassifiedException'


@pytest.fixture
def offline_execution(tmp_path, monkeypatch):
    """Real progress, scheduler, quota and accounting; only external execution is fake."""
    import json
    from types import SimpleNamespace

    from memweave_eval import (
        budget_guard,
        images,
        rsi_execution,
        rsi_progress,
        rsi_runtime,
        runner,
        trusted_broker,
    )
    from memweave_eval.rsi_scheduler import AttemptInterrupted, AttemptResult
    from memweave_eval.storage import atomic_json

    def create(count=2):
        spec = config(tmp_path, unbounded=True)
        catalog, paths = runtime_sources(tmp_path, monkeypatch, spec, count)
        prepared = tmp_path/'prepared'
        prepared.mkdir()
        (prepared/'prepared.json').write_text('{}')
        auth = tmp_path/'synthetic-auth.json'
        auth.write_text(json.dumps({'deepseek': {'type': 'api_key', 'key': 'synthetic-fixture'}}))
        state = SimpleNamespace(spec=spec, prepared=prepared, catalog=catalog, paths=paths,
                                events=[], calls=[], interrupt_task=None, fail_task=None, failure_once_task=None,
                                corrupt_accounting=False)
        amounts = {'cpus': 1, 'memory_mb': 1, 'storage_mb': 1}
        def plan(*args, split='all', **kwargs):
            rows = [row for row in catalog['tasks'] if split == 'all' or row['split'] == split]
            return {'environment': {'ready': True,
                'qualification_identity': {'daemon': {'ID': 'synthetic-offline-execution'}},
                'checks': [{'name': 'docker_capacity',
                'budget': dict.fromkeys(amounts, 1000), 'requirements': [
                    {'benchmark': row['suite_id'], 'task_id': row['task_id'], 'original': amounts}
                    for row in rows]}]}}
        monkeypatch.setattr(rsi_runtime, 'inspect_plan', plan)
        from memweave_eval import rsi_environment
        monkeypatch.setattr(rsi_environment, 'inspect_daemon_clock', lambda env: ({'ID': 'synthetic-offline-execution'}, {
            'name': 'clock_consistency', 'status': 'pass', 'detail': 'offline clock fixture'}))
        monkeypatch.setattr(rsi_runtime, '_verify_admitted', lambda spec, directory, split, **kwargs:
            ({'broker_image': 'fixture', 'evaluator_sha256': 'a'*64,
              'contract': {'environment': {'daemon': {'ID': 'synthetic-offline-execution'}}},
              'preparations': {row['suite_id']+'/'+row['task_id']: {}
              for row in catalog['tasks'] if (split == 'all' or row['split'] == split)
              and row['task_id'] not in getattr(state, 'unprepared', set())}}, [row for row in catalog['tasks']
                                         if split == 'all' or row['split'] == split]))
        monkeypatch.setattr(images, 'inspect_image', lambda *a: {})
        def auth_file():
            state.events.append('auth')
            return auth
        monkeypatch.setattr(runner, 'auth_file', auth_file)

        class Broker:
            def __init__(self, broker_root, control, run_id, image, env):
                self.control, self.run_id, self.process = control, run_id, None
                self.root = broker_root
            def start(self, credential, principals):
                assert credential == 'synthetic-fixture'
                import sys
                assert (self.control/'WRITER_PLATFORM').read_text().strip() == 'linux'
                # This fake authority runs on the host, not the Linux broker container.
                (self.control/'WRITER_PLATFORM').write_text(sys.platform+'\n')
                self.principals = principals
                state.events.append('started')
                self.process = object()
                from memweave_eval import rsi_recovery
                self.root.mkdir(parents=True)
                (self.root / 'controller-start.json').write_text(json.dumps({
                    'run_id': self.run_id, 'child_pid': 123, 'child_group': 123,
                    'child_process_identity': {'schema': rsi_recovery._SCHEMA, 'status': 'captured',
                        'pid': 123, 'platform': 'linux', 'host_boot_id': 'test',
                        'start_identity': 'test', 'precision': 'test', 'command_sha256': 'a' * 64}}))
            def stop(self):
                if getattr(state, 'manual_stop_after_batch', False):
                    (self.control.parent.parent/'STOP_REQUESTED').touch()
                state.events.append('stopped')
                ledger = json.loads((self.control/'quota.json').read_text())
                entries = []
                for principal in self.principals:
                    ids = [key for key, row in ledger['requests'].items()
                           if all(row.get(k) == principal[k] for k in ('episode', 'arm'))]
                    entries.append({**principal, 'admitted_request_ids': ids,
                                    'http_request_ids': ids, 'terminal_request_ids': ids})
                atomic_json(self.control/'quota.final.json', ledger, immutable=True)
                atomic_json(self.control/'transport-terminal.json', {
                    'schema_version': 'trusted-transport-terminal.v1', 'finalized': True,
                    'audit_events': 1, 'audit_head': 'a'*64, 'entries': entries}, immutable=True)
                result = {'confirmed': True, 'stopped': True, 'removed': True, 'terminal_available': True,
                          'networks_confirmed': True}
                from test_rsi_launch_cleanup_gates import broker_bindings
                broker_bindings(self.root.parent.parent, result)
                (self.root / 'controller-end.json').write_text(json.dumps(result))
                return result
        from memweave_eval import rsi_recovery
        monkeypatch.setattr(rsi_recovery, 'probe_process_identity', lambda _: {'state': 'not_running'})
        monkeypatch.setattr(trusted_broker, 'TrustedBroker', Broker)
        def make_executor(**kwargs):
            root, control = kwargs['root'], kwargs['control']
            async def execute(ctx):
                state.calls.append((ctx.variant.variant_id, ctx.task.task_id, ctx.attempt_index))
                episode = rsi_runtime.episode_id(root.name, ctx.task.benchmark+'/'+ctx.task.task_id,
                                                ctx.variant.variant_id, ctx.attempt_index)
                request_id = 'request-'+episode
                budget_guard.change(control/'quota.json', {'action': 'reserve', 'id': request_id,
                    'episode': episode, 'arm': ctx.variant.variant_id, 'max_output': 128})
                budget_guard.change(control/'quota.json', {'action': 'settle', 'id': request_id,
                    'input': 10, 'output': 2, 'cache_input': 0})
                atomic_json(ctx.output_dir/'container-cleanup.json', {
                    'confirmed': True, 'processes_confirmed': True, 'host_launches': {}}, immutable=True)
                if (ctx.task.task_id == state.interrupt_task and
                        (ctx.task.task_id != state.failure_once_task or ctx.attempt_index > 1)):
                    state.interrupt_task = None
                    raise AttemptInterrupted(AttemptResult('cancelled', 10, 2))
                failed = (ctx.task.task_id == state.fail_task or
                          ctx.task.task_id == state.failure_once_task and ctx.attempt_index == 1)
                official = ctx.output_dir/'official.json'
                atomic_json(official, {'reward': 0 if failed else 1}, immutable=True)
                return AttemptResult('failed' if failed else 'passed', 10, 2, str(official))
            return execute
        monkeypatch.setattr(rsi_execution, 'make_executor', make_executor)
        register = rsi_progress.ProgressStore.register_launch
        settle = rsi_progress.ProgressStore.settle_launch
        def registered(store, *args, **kwargs):
            value = register(store, *args, **kwargs)
            state.events.append('registered')
            return value
        def settled(store, launch_id, cleanup_evidence):
            proof = json.loads(cleanup_evidence.read_text())
            assert (__import__('pathlib').Path(proof['run_root'])/'accounting.json').is_file()
            state.events.append('settled')
            return settle(store, launch_id, cleanup_evidence)
        monkeypatch.setattr(rsi_progress.ProgressStore, 'register_launch', registered)
        monkeypatch.setattr(rsi_progress.ProgressStore, 'settle_launch', settled)
        return state
    return create


@pytest.mark.parametrize('bad_accounting', [False, True])
def test_run_finalizes_accounting_before_native_registration(offline_execution, monkeypatch,
                                                            bad_accounting):
    import asyncio
    import json
    from pathlib import Path

    from memweave_eval import rsi_accounting, rsi_runtime
    state = offline_execution()
    original = rsi_accounting.final_accounting
    def accounting(control, *, principals, broker_stopped):
        assert broker_stopped and state.events[-1] == 'stopped'
        assert len(principals) > 3  # Physical retries are distinct from three ability failures.
        state.events.append('accounted')
        if bad_accounting:
            raise ValueError('terminal ledger incomplete')
        return original(control, principals=principals, broker_stopped=broker_stopped)
    monkeypatch.setattr(rsi_accounting, 'final_accounting', accounting)
    execution = rsi_runtime.run_prepared(state.spec, state.prepared, split='all',
                                         variant='pi-native', approved_budget_usd=None)
    if bad_accounting:
        with pytest.raises(ValueError, match='terminal ledger incomplete'):
            asyncio.run(execution)
        assert state.events == ['auth', 'registered', 'started', 'stopped', 'accounted']
        assert not list(state.spec.root.glob('progress/*/settled/*.json'))
        assert not list(state.spec.root.glob('runs/*/results/summary-final.json'))
    else:
        result = asyncio.run(execution)
        assert state.events == ['auth', 'registered', 'started', 'stopped', 'accounted', 'settled']
        assert result['tokens']['input_tokens'] == 20
        report = json.loads((Path(result['path'])/'results/summary-final.json').read_text())
        assert report['tokens']['input_tokens'] == 20
        assert report['attempt_snapshots_unchanged'] is True


def test_cleanup_does_not_release_when_project_network_remains(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from memweave_eval import rsi_cleanup
    from memweave_eval.rsi_runtime import cleanup_attempt, trial_projects

    trial = 'original__abc1234'
    folder = tmp_path/'harbor/actor'/trial
    folder.mkdir(parents=True)
    (folder/'config.json').write_text('{"trial_name":"'+trial+'"}')
    monkeypatch.setattr('memweave_eval.rsi_runtime.subprocess.run',
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=''))
    def network_cleanup(projects, command):
        assert projects == set(trial_projects(trial))
        return {'confirmed': False, 'remaining_networks': ['a'*64]}
    monkeypatch.setattr(rsi_cleanup, 'cleanup_project_networks', network_cleanup)
    result = cleanup_attempt(tmp_path, 'owner', {})
    assert result['confirmed'] is False
    assert result['remaining'] == []
    assert result['project_networks']['remaining_networks'] == ['a'*64]


def test_stage_summary_counts_only_confirmed_ability_failures(tmp_path):
    from dataclasses import asdict

    from memweave_eval.rsi_runtime import stage_summaries
    from memweave_eval.rsi_scheduler import RunResult, TaskIdentity, VariantIdentity

    task = TaskIdentity('q', 'suite', 'revision', 'a'*64, 'Original')
    variant = VariantIdentity('pi-native', 'pi:1.4.0')
    rows = [{'task': asdict(task), 'variant': asdict(variant),
             'outcome': 'error', 'classification': 'infrastructure'} for _ in range(12)]
    rows += [{'task': asdict(task), 'variant': asdict(variant),
              'outcome': 'failed', 'classification': 'ability'} for _ in range(2)]
    catalog = {'tasks': [{'suite_id': 'suite', 'task_id': 'q', 'split': 'regression'}]}
    result = RunResult(tmp_path, (task,), (variant,), tuple(rows), {}, {})
    summary = stage_summaries(result, catalog, 3)['regression']['pi-native']
    assert summary['completed'] == 0 and summary['incomplete'] == 1
    assert summary['pass_rate'] is summary['effective_pass_rate'] is None
    rows.append(dict(rows[-1]))
    result = RunResult(tmp_path, (task,), (variant,), tuple(rows), {}, {})
    summary = stage_summaries(result, catalog, 3)['regression']['pi-native']
    assert summary['completed'] == 1 and summary['incomplete'] == 0
    assert summary['pass_rate'] == summary['effective_pass_rate'] == 0


def test_native_two_launch_resume_preserves_failure_and_complete_reuse(offline_execution, monkeypatch):
    import asyncio
    from pathlib import Path

    from memweave_eval import rsi_runtime, runner
    from memweave_eval.storage import file_digest

    state = offline_execution(count=200)
    state.interrupt_task = state.failure_once_task = 'original-000'
    def run(spec):
        return asyncio.run(rsi_runtime.run_prepared(spec, state.prepared, split='all',
                              variant='pi-native', approved_budget_usd=None))
    first = run(state.spec)
    assert first['summaries']['pi-native']['completed'] == 199
    assert len(state.calls) == 201
    first_progress = next(row for row in first['task_progress'] if row['task_id'] == 'original-000')
    assert first_progress['ability_failures'] == 1
    evidence = {path: file_digest(path) for path in (Path(first['path'])/'results').glob(
        'task-*/variant-*/attempt-*/result.json')}
    second = run(state.spec)
    assert second['summaries']['pi-native']['completed'] == 200
    assert state.calls[-1] == ('pi-native', 'original-000', 3)
    assert len(state.calls) == 202
    restored = next(row for row in second['task_progress'] if row['task_id'] == 'original-000')
    assert restored['first_started_at'] == first_progress['first_started_at']
    assert restored['question_deadline'] == first_progress['question_deadline']
    assert restored['ability_failures'] == 1
    assert all(file_digest(path) == digest for path, digest in evidence.items())
    assert second['tokens']['input_tokens'] == 2020
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('complete native reuse read credentials'))
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', lambda *a, **k: pytest.fail('complete reuse planned'))
    no_budget = state.spec.model_copy(update={'unbounded': False})
    reused = run(no_budget)
    assert reused['model_run'] is False and reused['reused_results'] is True
    assert reused['tokens']['input_tokens'] == 2020
    assert len(state.calls) == 202


def test_complete_plugin_reuse_and_cross_stage_tokens_are_isolated(offline_execution, monkeypatch):
    import asyncio

    from memweave_eval import rsi_runtime, runner

    state = offline_execution(count=200)
    def run(variant, split, spec=None):
        return asyncio.run(rsi_runtime.run_prepared(spec or state.spec, state.prepared,
                             split=split, variant=variant, approved_budget_usd=None))
    assert run('pi-native', 'all')['tokens']['input_tokens'] == 2000
    regression = run('pi-memweave', 'regression')
    assert regression['summaries']['pi-memweave']['total'] == 40
    assert regression['tokens']['input_tokens'] == 400
    assert regression['qualified_regression_count'] is None
    capability = run('pi-memweave', 'capability')
    assert capability['summaries']['pi-memweave']['total'] == 160
    assert capability['tokens']['input_tokens'] == 1600
    count = len(state.calls)
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('complete plugin reuse read credentials'))
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', lambda *a, **k: pytest.fail('complete reuse planned'))
    reused = run('pi-memweave', 'regression', state.spec.model_copy(update={'unbounded': False}))
    assert reused['model_run'] is False
    assert reused['tokens']['input_tokens'] == 400
    assert reused['qualified_regression_count'] is None
    assert len(state.calls) == count
    # Same questions, different stage membership: each old launch now partially
    # overlaps the selected cohort. Reuse must select episodes, not entire ledgers.
    import json
    state.catalog['tasks'][0]['split'] = 'capability'
    state.catalog['tasks'][100]['split'] = 'regression'
    state.spec.catalog.write_text(json.dumps(state.catalog))
    regrouped = run('pi-memweave', 'regression', state.spec.model_copy(update={'unbounded': False}))
    assert regrouped['model_run'] is False
    assert regrouped['tokens']['input_tokens'] == 400
    assert regrouped['summaries']['pi-memweave']['total'] == 40
    assert regrouped['qualified_regression_count'] is None
    assert len(state.calls) == count


def test_missing_credential_never_registers_a_new_progress_launch(offline_execution, monkeypatch):
    import asyncio

    from memweave_eval import rsi_runtime, runner
    state = offline_execution()
    missing = state.spec.root.parent/'empty-auth.json'
    missing.write_text('{}')
    monkeypatch.setattr(runner, 'auth_file', lambda: missing)
    with pytest.raises(ValueError, match='credential unavailable'):
        asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split='all',
                                            variant='pi-native', approved_budget_usd=None))
    assert not list(state.spec.root.glob('progress/*/launches/*.json'))
    assert not state.calls


@pytest.mark.parametrize('prior_classification', ['manual_review', 'cleanup_unconfirmed'])
def test_progress_completed_grade_wins_over_earlier_pending_diagnostic(tmp_path, prior_classification):
    from dataclasses import asdict

    from memweave_eval.rsi_progress import ProgressSnapshot
    from memweave_eval.rsi_scheduler import TaskIdentity, VariantIdentity
    from memweave_eval.storage import atomic_json, file_digest
    task = TaskIdentity('q', 'suite', 'rev', 'a'*64, 'original')
    variant = VariantIdentity('pi-native', 'pi:1')
    records = []
    for index, classification, outcome in ((1, prior_classification, 'error'), (2, 'ability', 'passed')):
        record = {'task': asdict(task), 'variant': asdict(variant), 'attempt_index': index,
                  'classification': classification, 'outcome': outcome,
                  'input_tokens': 1, 'output_tokens': 1}
        path = tmp_path/f'result-{index}.json'
        atomic_json(path, record, immutable=True)
        records.append(record)
    originals = {path: file_digest(path) for path in tmp_path.glob('result-*.json')}
    key = ('suite', 'q', 'pi-native')
    snapshot = ProgressSnapshot((task,), variant, tuple(records), (), (), {key: 100.},
                                {key: 3}, {}, {'max_attempts': 3})
    result = snapshot.result(tmp_path)
    assert result.summaries['pi-native']['complete']
    assert result.progress[0]['status'] == 'passed'
    assert all(file_digest(path) == digest for path, digest in originals.items())


def test_legacy_incomplete_baseline_cannot_restart_through_progress(offline_execution, monkeypatch):
    import asyncio

    from memweave_eval import rsi_runtime, runner
    from memweave_eval.rsi_baseline import BaselineStore, question_set_digest
    state = offline_execution(count=200)
    legacy = BaselineStore(state.spec.root/'native-baselines', question_set_digest(state.catalog))
    legacy.begin(state.spec.root/'old-run', rsi_runtime.native_contract(state.spec, state.catalog))
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('legacy recovery read credentials'))
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', lambda *a, **k: pytest.fail('legacy restart planned'))
    with pytest.raises(ValueError, match='legacy incomplete'):
        asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split='all',
                                            variant='pi-native', approved_budget_usd=None))
    assert not state.calls
    assert not list(state.spec.root.glob('progress/*/launches/*.json'))


def test_reconcile_series_preserves_confirmed_infrastructure_classification(tmp_path, monkeypatch):
    import asyncio
    from dataclasses import asdict
    from types import SimpleNamespace

    from memweave_eval import rsi_attempt_evidence, rsi_execution, rsi_resume, rsi_runtime
    from memweave_eval.rsi_scheduler import RetryPolicy, TaskIdentity, VariantIdentity
    from memweave_eval.storage import atomic_json
    task = TaskIdentity('q', 'terminal-bench-4', 'rev', 'a'*64, 'original')
    root = tmp_path/'old-launch'
    attempt = root/'results/task-0000/variant-00/attempt-3'
    atomic_json(root/'private/control/quota.json', {'requests': {}})
    started = {'task': asdict(task), 'variant': asdict(VariantIdentity('pi-native', 'pi:1')),
               'root': str(attempt), 'attempt_index': 3, 'input_sha256': task.input_sha256,
               'started_at': 100., 'first_started_at': 1., 'question_deadline': 28801.}
    atomic_json(root/'run-contract.json', {'config': {'unbounded': True}, 'deadline': None})
    store = SimpleNamespace(scan=lambda tasks: SimpleNamespace(attempts=(
        {'classification': 'infrastructure'}, {'classification': 'infrastructure'})))
    monkeypatch.setattr(rsi_execution, 'classification_result', lambda *a, **k: {
        'disposition': 'infra_interrupted', 'official_outcome': None,
        'reason_code': 'verified_provider_failure'})
    monkeypatch.setattr(rsi_attempt_evidence, 'load_transport_evidence', lambda *a, **k: {})
    async def inspect_callbacks(actual_store, callbacks):
        assert actual_store is store
        record = callbacks.recover_record({'run_root': str(root)}, started,
                                          {'action': 'retry_fresh', 'actor': None, 'regrade': None})
        assert record['classification'] == 'infrastructure'
        assert record['outcome'] == 'error'
        assert record['next_eligible_at'] == record['finished_at']+RetryPolicy().backoff_seconds(3)
        assert record['first_started_at'] == 1.
        assert record['attempt_index'] == 3
        return {'ready': True}
    monkeypatch.setattr(rsi_resume, 'reconcile_progress', inspect_callbacks)
    assert asyncio.run(rsi_runtime.reconcile_series(store, {})) == {'ready': True}


def test_expired_incomplete_series_does_not_start_empty_broker(offline_execution, monkeypatch):
    import asyncio

    from memweave_eval import rsi_runtime, runner
    from memweave_eval.rsi_scheduler import ExperimentScheduler
    state = offline_execution()
    state.interrupt_task = 'original-000'
    class HistoricalClockScheduler(ExperimentScheduler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._clock = lambda: 100.
    monkeypatch.setattr(rsi_runtime, 'ExperimentScheduler', HistoricalClockScheduler)
    first = asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split='all',
                                                 variant='pi-native', approved_budget_usd=None))
    assert first['summaries']['pi-native']['completed'] == 1
    original_calls = list(state.calls)
    launches = tuple(state.spec.root.glob('progress/*/launches/*.json'))
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('expired series read credentials'))
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', lambda *a, **k: pytest.fail('expired series planned'))
    restored = asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split='all',
                                                    variant='pi-native', approved_budget_usd=None))
    assert restored['model_run'] is False and restored['blocked']
    assert restored['supplementary_required'] == []  # Interrupted cause still needs review.
    assert tuple(state.spec.root.glob('progress/*/launches/*.json')) == launches
    assert state.calls == original_calls


def test_completed_progress_uses_original_attempt_limit_in_stage_report(offline_execution, monkeypatch):
    import asyncio

    from memweave_eval import rsi_runtime, runner

    state = offline_execution()
    state.spec = state.spec.model_copy(update={'max_attempts': 1})
    state.fail_task = 'original-000'
    first = asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split='all',
                                                 variant='pi-native', approved_budget_usd=None))
    assert first['summaries']['pi-native']['complete']
    assert first['stages']['regression']['pi-native']['complete']
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('metadata-only change accessed auth'))
    changed = state.spec.model_copy(update={'max_attempts': 3})
    reused = asyncio.run(rsi_runtime.run_prepared(changed, state.prepared, split='all',
                                                  variant='pi-native', approved_budget_usd=None))
    assert reused['model_run'] is False
    assert reused['summaries']['pi-native']['complete']
    assert reused['stages']['regression']['pi-native']['complete']
    assert 'max_attempts' in reused['native_metadata_changes']


@pytest.mark.parametrize('manual_stop_after_batch', [False, True])
@pytest.mark.parametrize('gate_failure', [False, True])
def test_runtime_automatically_supplements_expired_infra_without_resetting_failures(
        offline_execution, monkeypatch, manual_stop_after_batch, gate_failure):
    import asyncio
    import json
    import time
    from pathlib import Path

    from memweave_eval import rsi_execution, rsi_runtime
    from memweave_eval.rsi_scheduler import AttemptResult, InfrastructureFailure

    state = offline_execution(count=1)
    state.manual_stop_after_batch = manual_stop_after_batch
    state.fail_task = 'original-000'
    clock = [time.time()]
    scheduler = rsi_runtime.ExperimentScheduler
    class ClockScheduler(scheduler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if state.calls:
                clock[0] += 31  # Supplementary initial queue still honors prior backoff.
            self._clock = lambda: clock[0]
    monkeypatch.setattr(rsi_runtime, 'ExperimentScheduler', ClockScheduler)
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    factory = rsi_execution.make_executor
    def executor(**kwargs):
        base = factory(**kwargs)
        async def execute(ctx):
            result = await base(ctx)
            if ctx.attempt_index == 2:
                clock[0] = ctx.question_deadline + 1
                raise InfrastructureFailure(AttemptResult('error', 10, 2))
            return result
        return execute
    monkeypatch.setattr(rsi_execution, 'make_executor', executor)
    launch = rsi_runtime.execute_launch
    async def gated_launch(*args, **kwargs):
        if gate_failure and state.calls:
            raise ValueError('remaining finite window cannot fit original task')
        return await launch(*args, **kwargs)
    monkeypatch.setattr(rsi_runtime, 'execute_launch', gated_launch)
    result = asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared,
        split='all', variant='pi-native', approved_budget_usd=None))
    if manual_stop_after_batch:
        assert [row[2] for row in state.calls] == [1, 2]
        assert 'manual stop' in result['blocked']
        assert len(result['launch_paths']) == 1
        return
    if gate_failure:
        assert [row[2] for row in state.calls] == [1, 2]
        assert 'finite window' in result['blocked']
        assert result['supplementary_registered_not_started']
        assert len(result['launch_paths']) == 1
        assert result['tokens']['input_tokens'] == 20
        return
    assert [row[2] for row in state.calls] == [1, 2, 3, 4]
    progress = result['task_progress'][0]
    assert progress['ability_failures'] == 3
    assert result['summaries']['pi-native']['complete']
    assert result['tokens']['input_tokens'] == 40
    assert len(result['launch_paths']) == 2
    records = [json.loads(p.read_text()) for root in result['launch_paths']
               for p in Path(root).glob('results/task-*/variant-*/attempt-*/result.json')]
    records.sort(key=lambda r: r['attempt_index'])
    assert [r['batch_id'] for r in records[:2]] == ['initial', 'initial']
    assert len({r['first_started_at'] for r in records}) == 1
    assert records[2]['window_started_at'] > records[0]['question_deadline']
    assert records[3]['window_started_at'] == records[2]['window_started_at']
    assert records[2]['question_deadline'] == records[2]['window_started_at'] + 28800
    assert records[2]['batch_id'] == records[3]['batch_id'] != 'initial'


def test_remaining_auto_batch_budget_does_not_reset_or_ignore_unknown(tmp_path):
    import json

    from memweave_eval.rsi_runtime import automatic_launch_limits
    spec = config(tmp_path, max_cost_usd=2.0, max_elapsed_seconds=4000)
    root = tmp_path/'launch'
    root.mkdir()
    (root/'accounting.json').write_text(json.dumps({'global': {'exposure_usd': 0.75}}))
    assert automatic_launch_limits(spec, [root], 100., now=200.) == (1.25, 4100.)
    (root/'accounting.json').write_text(json.dumps({'global': {'exposure_usd': None}}))
    with pytest.raises(ValueError, match='unknown'):
        automatic_launch_limits(spec, [root], 100., now=200.)
    assert automatic_launch_limits(spec.model_copy(update={
        'unbounded': True, 'max_cost_usd': None, 'max_elapsed_seconds': None}),
        [root], 100., now=999999.) == (None, None)


def test_plugin_stage_reuse_does_not_claim_new_question_set_native_baseline(offline_execution):
    import asyncio
    import json

    from memweave_eval import rsi_runtime

    state = offline_execution()
    def run(variant, split):
        return asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split=split,
            variant=variant, approved_budget_usd=None))
    run('pi-native', 'all')
    initial = run('pi-memweave', 'regression')
    assert initial['native_baseline_ready']
    row = state.catalog['tasks'][1]
    old = (row['suite_id'], row['task_id'])
    row['task_id'] = 'new-official-question'
    state.paths[(row['suite_id'], row['task_id'])] = state.paths[old]
    state.spec.catalog.write_text(json.dumps(state.catalog))
    reused = run('pi-memweave', 'regression')
    assert reused['reused_results']
    assert not reused['reused_native_baseline']
    assert not reused['native_baseline_ready']
    assert reused['qualified_regression_count'] is None


def test_native_partial_waves_keep_two_hundred_and_resume(offline_execution):
    import asyncio

    from memweave_eval import rsi_runtime
    state = offline_execution(count=200)
    state.unprepared = {row['task_id'] for row in state.catalog['tasks'][2:]}
    def run():
        return asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared,
            split='all', variant='pi-native', approved_budget_usd=None))
    first = run()
    assert len(state.calls) == 2
    assert first['summaries']['pi-native']['total'] == 200
    assert first['summaries']['pi-native']['completed'] == 2
    assert not first['native_baseline_ready'] and not first['promotion_allowed']
    waiting = first['task_progress'][2:]
    assert all(row['status'] == 'waiting_preparation' and row['first_started_at'] is None
               and row['ability_failures'] == row['physical_launch_count'] == 0 for row in waiting)
    assert not list(state.spec.root.glob('progress/*/batches/*.json'))
    events = list(state.events)
    same = run()
    assert not same['model_run'] and state.events == events
    assert len(same['task_progress']) == 200
    state.unprepared = set()
    final = run()
    assert len(state.calls) == 200
    assert final['summaries']['pi-native']['complete'] and final['native_baseline_ready']
    assert all(index == 1 for _, _, index in state.calls)


def test_capacity_waits_without_auth_or_start_clock(offline_execution, monkeypatch):
    import asyncio

    from memweave_eval import rsi_runtime
    state = offline_execution()
    plan = rsi_runtime.inspect_plan
    def blocked(*args, **kwargs):
        value = plan(*args, **kwargs)
        value['environment']['ready'] = False
        resource = value['environment']['checks'][0]
        resource.update(status='blocked', errors=[], budget=dict.fromkeys(resource['budget'], 0))
        return value
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', blocked)
    result = asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared,
        split='all', variant='pi-native', approved_budget_usd=None))
    assert not result['model_run'] and state.events == []
    assert len(result['task_progress']) == 2
    assert all(row['status'] == 'waiting_capacity' and row['first_started_at'] is None
               and row['ability_failures'] == 0 for row in result['task_progress'])
    assert not (state.spec.root/'runs').exists()


@pytest.mark.parametrize('failure', ['daemon', 'capacity_metadata'])
def test_partial_admission_never_ignores_global_safety_checks(failure):
    from memweave_eval.rsi_runtime import admission_capacity
    resource = {'name': 'docker_capacity', 'status': 'blocked', 'errors': []}
    checks = [resource, {'name': 'docker_idle_before_run', 'status': 'pass'}]
    if failure == 'daemon':
        checks[1]['status'] = 'blocked'
    else:
        resource['errors'] = ['observed daemon storage unavailable']
    with pytest.raises(ValueError, match='no credentials read'):
        admission_capacity({'environment': {'ready': False, 'checks': checks}})


def test_partial_capacity_executes_only_fitting_task(offline_execution, monkeypatch):
    import asyncio

    from memweave_eval import rsi_runtime
    state = offline_execution()
    plan = rsi_runtime.inspect_plan
    def blocked(*args, **kwargs):
        value = plan(*args, **kwargs)
        value['environment']['ready'] = False
        resource = value['environment']['checks'][0]
        resource.update(status='blocked', errors=[])
        resource['requirements'][1]['original'] = {'cpus': 1, 'memory_mb': 1, 'storage_mb': 1001}
        return value
    monkeypatch.setattr(rsi_runtime, 'inspect_plan', blocked)
    result = asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared,
        split='all', variant='pi-native', approved_budget_usd=None))
    assert state.calls == [('pi-native', 'original-000', 1)]
    assert result['summaries']['pi-native']['total'] == 2
    assert result['task_progress'][1]['status'] == 'waiting_capacity'
    assert result['task_progress'][1]['first_started_at'] is None
    assert not result['native_baseline_ready']
    assert not list(state.spec.root.glob('progress/*/batches/*.json'))


@pytest.mark.parametrize('status', ['waiting_preparation', 'waiting_capacity', 'pending'])
def test_initial_unstarted_wait_is_not_supplementary(status):
    from memweave_eval.rsi_runtime import supplementary_required
    row = {"status": status, "first_started_at": None, "question_deadline": None, "batch_id": 'initial'}
    assert supplementary_required([row]) == []
    assert row['first_started_at'] is None and row['question_deadline'] is None


def test_supplementary_report_keeps_only_started_eligible_work():
    from memweave_eval.rsi_runtime import supplementary_required
    base = {"status": 'deadline_exhausted', "first_started_at": 1., "batch_id": 'initial',
                "supplementary_hold_reason": None}
    registered = dict(base, status='waiting_preparation', batch_id='supplementary-known')
    rows = [base, registered, dict(base, status='pending'), dict(base, status='passed'),
            dict(base, status='ability_exhausted'), dict(base, supplementary_hold_reason='manual_stop'),
            dict(base, status='cleanup_unconfirmed')]
    assert supplementary_required(rows) == [base, registered]


def test_calibration_requires_complete_native_before_registry_or_recovery(offline_execution, monkeypatch):
    import asyncio

    from memweave_eval import rsi_calibration, rsi_runtime, runner
    state = offline_execution(count=200)
    monkeypatch.setattr(rsi_calibration, 'register_calibration', lambda *a: pytest.fail('early registration'))
    monkeypatch.setattr(rsi_runtime, 'reconcile_series', lambda *a, **k: pytest.fail('early recovery'))
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('credential read'))
    with pytest.raises(ValueError, match='complete initial native200'):
        asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split='all',
            variant='pi-memweave', approved_budget_usd=None, calibration=True))
    assert state.calls == []


@pytest.mark.parametrize("ready_count", [20, 40])
def test_full_calibration_uses_same_plugin_series_and_reuses_complete_results(offline_execution, monkeypatch, ready_count):
    import asyncio

    from memweave_eval import rsi_calibration, rsi_runtime, runner
    state = offline_execution(count=200)
    commit, digest = rsi_calibration.FIXED_SUBJECT.split(':')
    state.spec.subject.commit, state.spec.subject.sha256 = commit, digest
    def run(variant, split, calibration=False):
        return asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split=split,
            variant=variant, approved_budget_usd=None, calibration=calibration))
    run('pi-native', 'all')
    state.unprepared = {f'original-{i:03d}' for i in range(ready_count, 40)}
    initial = run('pi-memweave', 'regression')
    prior = {row['task_id']: row for row in initial['task_progress'] if row['first_started_at'] is not None}
    assert len(prior) == ready_count
    state.unprepared = set()
    seen = []
    def register(root, catalog, native, plugin, contract):
        native.assert_acquired(); plugin.assert_acquired()
        assert plugin.variant.subject_id == rsi_calibration.FIXED_SUBJECT
        seen.append((native.directory, plugin.directory))
    monkeypatch.setattr(rsi_calibration, 'register_calibration', register)
    result = run('pi-memweave', 'all', True)
    assert result['purpose'] == 'initial-calibration-only' and result['promotion_allowed'] is False
    assert result['summaries']['pi-memweave']['total'] == 200
    assert result['qualified_regression_count'] is None
    assert len(state.calls) == 400  # Existing complete stage results not replayed.
    for row in result['task_progress']:
        if row['task_id'] in prior:
            old = prior[row['task_id']]
            for field in ('first_started_at', 'question_deadline', 'next_attempt_index',
                          'ability_failures', 'physical_launch_count', 'batch_id', 'window_started_at'):
                assert row[field] == old[field]
    before = list(state.calls)
    monkeypatch.setattr(runner, 'auth_file', lambda: pytest.fail('completed calibration read auth'))
    reused = run('pi-memweave', 'all', True)
    assert reused['reused_results'] and not reused['model_run']
    assert state.calls == before and seen[0] == seen[1]
    # Capability stage passes cannot inflate frozen regression qualification.
    state.catalog['regression_status'] = 'calibrated-qualified'
    regression = run('pi-memweave', 'regression')
    capability = run('pi-memweave', 'capability')
    assert regression['qualified_regression_count'] == 40
    assert capability['qualified_regression_count'] == 0


@pytest.mark.parametrize('missing', ['transport-terminal.json', 'processes_confirmed'])
def test_execution_missing_terminal_evidence_never_settles(offline_execution, monkeypatch, missing):
    import asyncio
    import json

    from memweave_eval import rsi_runtime, trusted_broker
    state = offline_execution()
    original = trusted_broker.TrustedBroker.stop
    def stop(broker):
        result = original(broker)
        if missing == 'transport-terminal.json':
            (broker.control / missing).unlink()
        else:
            for path in broker.control.parent.parent.glob('results/task-*/variant-*/attempt-*/output/container-cleanup.json'):
                value = json.loads(path.read_text())
                del value[missing]
                path.write_text(json.dumps(value))
        return result
    monkeypatch.setattr(trusted_broker.TrustedBroker, 'stop', stop)
    with pytest.raises(ValueError, match='request terminal|strong attempt'):
        asyncio.run(rsi_runtime.run_prepared(state.spec, state.prepared, split='all',
            variant='pi-native', approved_budget_usd=None))
    assert 'settled' not in state.events
    assert not list(state.spec.root.glob('runs/*/launch-cleanup.json'))
    assert not list(state.spec.root.glob('progress/*/settled/*.json'))
