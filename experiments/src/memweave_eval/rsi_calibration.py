"""One-time calibration identity registration, based on verified progress evidence.

Selection uses only the approved multiple-scenario/multiple-difficulty floor.
No model, credentials or Docker access.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from itertools import combinations
from pathlib import Path

from .actor_adapter import RSI_PI
from .rsi_attempt_evidence import _unique
from .rsi_baseline import _contract, question_set_digest
from .rsi_catalog import Catalog, catalog_counts
from .rsi_progress import _MATERIAL, ProgressStore, _read, _reference
from .rsi_scheduler import TaskIdentity
from .spec import outside_repository
from .storage import atomic_json


def _json(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=_unique)


def registration_path(root, catalog):
    from .rsi_policy import is_active_policy, policy_digest, policy_for_catalog
    directory = outside_repository(Path(root))/'calibrations'/question_set_digest(catalog)
    policy = policy_for_catalog(catalog)
    if is_active_policy(policy):
        directory = directory/policy_digest(policy)
    return directory/'registration.json'


def _material(contract):
    result = {key: contract[key] for key in _MATERIAL}
    if 'execution_policy' in contract:
        result['execution_policy'] = contract['execution_policy']
    return result


def _attempt_preparation(run, launch, attempt, initial, bind):
    """Select archival task qualification without weakening legacy launch proofs."""
    reference = attempt.get('admission_reference')
    if run.get('pipeline_admission') is not True:
        if reference is not None or 'pipeline_admission' in run:
            raise ValueError('dynamic admission requires explicit pipeline launch contract')
        return initial
    root = Path(launch['run_root'])
    task, variant = attempt['task'], attempt['variant']
    key = [task['benchmark'], task['task_id']]
    scope = run.get('authorized_task_keys')
    if (not isinstance(scope, list) or not scope or key not in scope
            or any(not isinstance(k, list) or len(k) != 2
                   or any(not isinstance(v, str) or not v for v in k) for k in scope)
            or len({tuple(k) for k in scope}) != len(scope)):
        raise ValueError('pipeline task outside exact authorized scope')
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise ValueError('pipeline attempt admission reference missing')
    attempt_root = Path(attempt['root'])
    if not attempt_root.is_relative_to(Path(launch['output_root'])):
        raise ValueError('pipeline attempt outside registered launch')
    started = _read(bind(attempt_root/'started.json'))
    if (started.get('admission_reference') != reference or started.get('task') != task
            or started.get('variant') != variant
            or started.get('attempt_index') != attempt['attempt_index']):
        raise ValueError('pipeline result/start admission identity differs')
    binding = _read(reference, root)
    if bind(reference['path']) != reference:
        raise ValueError('pipeline admission reference changed')
    if (set(binding) != {'schema_version', 'task', 'variant', 'launch_id', 'task_key',
                        'prepared_path', 'prepared_sha256', 'principals'}
            or binding['schema_version'] != 'rsi-pipeline-admission.v1'
            or binding['task'] != task or binding['variant'] != variant
            or binding['launch_id'] != launch['launch_id'] or binding['task_key'] != key):
        raise ValueError('pipeline admission binding differs from actual attempt')
    principal_ref = {'path': str(root/'principals.json'), 'sha256': run.get('principals_sha256')}
    global_principals = _read(principal_ref, root).get('principals')
    if bind(principal_ref['path']) != principal_ref:
        raise ValueError('pipeline principal scope changed')
    principals = binding['principals']
    if (not isinstance(global_principals, list) or not isinstance(principals, list) or not principals
            or any(not isinstance(p, dict) or set(p) != {'arm', 'episode'}
                   or p['arm'] != variant['variant_id'] or not isinstance(p['episode'], str)
                   or p not in global_principals for p in principals)
            or len({(p['arm'], p['episode']) for p in principals}) != len(principals)):
        raise ValueError('pipeline admission has invalid/unregistered principals')
    from .rsi_runtime import episode_id
    if {'arm': variant['variant_id'], 'episode': episode_id(root.name, '/'.join(key),
            variant['variant_id'], attempt['attempt_index'])} not in principals:
        raise ValueError('actual attempt principal was not authorized')
    prepared_ref = {'path': binding['prepared_path'], 'sha256': binding['prepared_sha256']}
    prepared = _read(prepared_ref)
    if bind(prepared_ref['path']) != prepared_ref:
        raise ValueError('pipeline preparation snapshot changed')
    if (prepared.get('preparation_root') != initial['preparation_root']
            or prepared.get('evaluator_sha256') != initial['evaluator_sha256']
            or prepared.get('transport_verified') is not True
            or '/'.join(key) not in prepared.get('task_receipts', {})):
        raise ValueError('pipeline preparation scope/evaluator/qualification changed')
    return prepared


def _verify_historic_qualification(catalog, task_root, value, prepared, run, task):
    from .rsi_preparation import verify_historical_task
    from .rsi_runtime import RSIConfig

    rows = [row for row in catalog['tasks'] if _key(row) == (task['benchmark'], task['task_id'])]
    if len(rows) != 1:
        raise ValueError('qualification task not in exact catalog')
    spec = RSIConfig.model_validate(value['config'])
    if any(value['config'][key] != run['config'][key] for key in
           ('subject', 'runtime', 'model', 'platform', 'source_cache', 'root')):
        raise ValueError('qualification software/subject differs from actual launch')
    return verify_historical_task(spec, task_root, rows[0], prepared['contract'], catalog=catalog)


def _verify_official_attempt(attempt, expected_runtime, config):
    from .rsi_attempt_evidence import _official
    from .rsi_recovery import inspect_attempt

    protocol = 'tb4' if attempt['task']['benchmark'] == 'terminal-bench-4' else 'swe-pro-v2'
    inspection = inspect_attempt(Path(attempt['root'])/'output', task_id=attempt['task']['task_id'],
        protocol=protocol, process_probe=lambda _: {'state': 'not_running', 'basis': 'verified_settled_launch'},
        cleanup_confirmed=True)
    # This is archival verification, not a live process probe. The callback
    # above is justified only by each identity-bound wait receipt below. A
    # settled launch or cleanup boolean cannot manufacture missing termination
    # evidence, even when the official reward itself is already available.
    for lifecycle in inspection.get('lifecycle', {}).values():
        end = lifecycle.get('end')
        if (not end or end['raw'].get('status') != 'terminal'
                or type(end['raw'].get('return_code')) is not int):
            raise ValueError('official execution lacks verified process terminal evidence')
    role = 'actor' if protocol == 'tb4' else 'regrade'
    official = inspection.get(role)
    if (inspection.get('action') != 'reuse_result' or not inspection.get('evidence_complete')
            or not official or official['path'] != attempt['official_evidence']
            or official['sha256'] != attempt['official_evidence_sha256']
            or _official(official['raw']) != attempt['outcome']):
        raise ValueError('official result lacks exact completed actor/fresh grading evidence')
    actor = inspection['job_configs']['actor']['raw']['agents'][0]
    options = actor.get('kwargs', {})
    if (actor.get('import_path') != RSI_PI.entry(attempt['variant']['variant_id'])
            or options.get('prepare_only') is not False
            or options.get('variant') != attempt['variant']['variant_id']
            or actor.get('model_name') != 'deepseek/deepseek-flash'
            or options.get('package_sha256') != config['subject']['sha256']
            or options.get('version') != config['runtime']['pi_version']
            or inspection['job_configs']['actor']['raw'].get('tasks') != [{'path': str(expected_runtime)}]):
        raise ValueError('official score is not from a normal model actor')
    return inspection['evidence']


def _series_evidence(catalog, store, *, require_complete):
    if not isinstance(store, ProgressStore):
        raise TypeError('calibration requires an existing verified ProgressStore')
    catalog = Catalog.model_validate(catalog).model_dump(mode='json')
    if catalog['id'] == 'rsi-100-v1':
        from .rsi_candidate_policy import validate_frozen_candidate
        validate_frozen_candidate(catalog)
    qset = question_set_digest(catalog)
    launches = store.registered_launches()
    if not launches and not tuple((store.directory/'reuses').glob('*.json')):
        raise ValueError('calibration requires registered execution evidence')
    contract_ref = (launches[0]['contract'] if launches else
                    _read(_reference(store.directory/'series.json'))['contract'])
    contract = _contract(_read(contract_ref), qset)
    tasks = [TaskIdentity(**row) for row in contract['tasks']]
    expected = [(r['suite_id'], r['task_id'], r['sha256']) for r in catalog['tasks']]
    if [(t.benchmark, t.task_id, t.source_sha256) for t in tasks] != expected:
        raise ValueError('calibration task identity/order differs from original catalog')
    snapshot = store.scan(tasks)
    if snapshot.unresolved or snapshot.unsettled_launches:
        raise ValueError('calibration cannot use unresolved/unsettled execution')
    result = snapshot.result(store.directory)
    if require_complete and not snapshot.complete:
        raise ValueError(f'calibration requires all {len(tasks)} actual task results complete')
    refs = {}
    def bind(path):
        ref = _reference(Path(path))
        refs[ref['path']] = ref
        return ref
    # Freeze the reconstruction inputs, not generated summaries. writer.lock is
    # intentionally excluded; no run/private/auth tree is enumerated.
    for path in store.directory.rglob('*.json'):
        bind(path)
    evaluators = []
    execution_bindings = {}
    for launch in launches:
        actual = _contract(_read(launch['contract']), qset)
        if _material(actual) != _material(contract) or actual['tasks'] != contract['tasks']:
            raise ValueError('calibration launch material or original task identity changed')
        if launch['variant'] != asdict(store.variant):
            raise ValueError('calibration launch has a different frozen subject')
        root = Path(launch['run_root'])
        run_ref = bind(root/'run-contract.json')
        run = _read(run_ref)
        if (run.get('progress_series') != str(store.directory)
                or run.get('variant') != store.variant.variant_id):
            raise ValueError('calibration run registration differs from series')
        prepared_ref = {'path': run['prepared_path'], 'sha256': run['prepared_sha256']}
        prepared = _read(prepared_ref)
        bind(prepared_ref['path'])
        if prepared.get('evaluator_sha256') != actual['evaluator_sha256']:
            raise ValueError('calibration preparation/evaluator mismatch')
        prep_root = outside_repository(Path(prepared['preparation_root']))
        if prepared.get('transport_verified') is not True or not prepared.get('task_receipts'):
            raise ValueError('calibration launch lacks complete task qualification references')
        launched_attempts = [attempt for attempt in result.attempts
                             if Path(attempt['root']).is_relative_to(Path(launch['output_root']))]
        for attempt in launched_attempts:
            task = attempt['task']
            qualified = _attempt_preparation(run, launch, attempt, prepared, bind)
            key = task['benchmark']+'/'+task['task_id']
            if key not in qualified['task_receipts']:
                raise ValueError('launched task was not qualified')
            receipt = qualified['task_receipts'][key]
            receipt_ref = {'path': str(prep_root/receipt['path']), 'sha256': receipt['sha256']}
            value = _read(receipt_ref, prep_root)
            bind(receipt_ref['path'])
            if (value.get('evaluator_sha256') != actual['evaluator_sha256']
                    or value.get('schema_version') != 2 or value.get('kind') != 'single-task-preparation'
                    or value.get('transport_verified') is not True or value.get('model_requests') != 0):
                raise ValueError('task qualification identity or completeness changed')
            task_root = Path(receipt_ref['path']).parent
            _verify_historic_qualification(catalog, task_root, value, qualified, run, task)
            record = value['preparations'][task['benchmark']+'/'+task['task_id']]
            execution_bindings[(str(root), task['benchmark'], task['task_id'])] = (
                task_root/record['runtime_path'], run['config'])
            for filename in ('started.json', 'task-receipt-proof.json', 'runtime-assets.json', 'runtime-assets.lock.json'):
                bind(task_root/filename)
            def bind_proofs(node, task_root=task_root):
                if isinstance(node, list):
                    for child in node: bind_proofs(child)
                elif isinstance(node, dict):
                    if isinstance(node.get('path'), str) and isinstance(node.get('sha256'), str):
                        candidate = Path(node['path'])
                        candidate = candidate if candidate.is_absolute() else task_root/candidate
                        ref = _reference(candidate)
                        if ref['sha256'] != node['sha256']:
                            raise ValueError('qualification referenced evidence changed')
                        bind(candidate)
                    for child in node.values(): bind_proofs(child)
            bind_proofs(value)

        evaluators.append({'launch_id': launch['launch_id'], 'evaluator_sha256': actual['evaluator_sha256'],
                           'prepared': prepared_ref})
        # Settlement verifies its file list and cleanup before this method. Bind
        # those referenced original JSONs and cleanup again into registration.
        settlement = _json(store.directory/'settled'/f"{launch['launch_id']}.json")
        for ref in [settlement['cleanup'], *settlement['files']]:
            _read(ref)
            bind(ref['path'])
    passed = []
    reused = {}
    for attempt in result.attempts:
        if attempt.get('reuse_reference') is not None:
            from .rsi_pass_reuse import validate_pass_reuse
            reference = attempt['reuse_reference']
            reuse_key = (reference['path'], reference['sha256'])
            if reuse_key not in reused:
                reused[reuse_key] = validate_pass_reuse(reference, task=attempt['task'],
                    variant=store.variant, question_set_sha256=qset,
                    execution_policy=contract.get('execution_policy'), contract=contract)
            verified = reused[reuse_key]
            if attempt not in verified['attempts']:
                raise ValueError('calibration reuse projection differs from verified source')
            for ref in verified['references']:
                if bind(ref['path']) != ref:
                    raise ValueError('calibration compatible source evidence changed')
            if attempt['classification'] == 'ability' and attempt['outcome'] == 'passed':
                passed.append([attempt['task']['benchmark'], attempt['task']['task_id']])
            continue
        if attempt['classification'] != 'ability':
            continue
        owners = [launch for launch in launches if Path(attempt['root']).is_relative_to(Path(launch['output_root']))]
        if len(owners) != 1:
            raise ValueError('official attempt has no unique launch')
        binding = execution_bindings[(owners[0]['run_root'], attempt['task']['benchmark'], attempt['task']['task_id'])]
        for reference in _verify_official_attempt(attempt, *binding):
            if bind(reference['path']) != reference:
                raise ValueError('official execution evidence changed')
        official_ref = {'path': attempt['official_evidence'], 'sha256': attempt['official_evidence_sha256']}
        official = _read(official_ref)
        reward = (official.get('verifier_result') or {}).get('rewards', {}).get('reward')
        if (type(reward) not in (int, float) or reward not in (0, 1)
                or ('passed' if reward == 1 else 'failed') != attempt['outcome']):
            raise ValueError('calibration official reward does not match recorded outcome')
        bind(official_ref['path'])
        if reward == 1:
            passed.append([attempt['task']['benchmark'], attempt['task']['task_id']])
    return {'store_root': str(store.root), 'store_directory': str(store.directory),
            'variant': asdict(store.variant), 'question_set_sha256': qset,
            'material': _material(contract), 'complete': snapshot.complete,
            'passed': sorted(passed), 'evaluators': evaluators,
            'references': sorted(refs.values(), key=lambda ref: ref['path'])}


def register_calibration(root, catalog, native_store, plugin_store, contract):
    """Pin the sole plugin identity before its first calibration execution."""
    if native_store.variant.variant_id != 'pi-native' or plugin_store.variant.variant_id != 'pi-memweave':
        raise ValueError('calibration requires native and plugin identities')
    root = outside_repository(Path(root))
    if native_store.root != root/'progress' or plugin_store.root != root/'progress':
        raise ValueError('calibration progress belongs to another experiment root')
    native = _series_evidence(catalog, native_store, require_complete=False)
    expected = _contract(contract, question_set_digest(catalog))
    if _material(expected) != native['material']:
        raise ValueError('native/plugin calibration material differs')
    for launch in plugin_store.registered_launches():
        actual = _contract(_read(launch['contract']), native['question_set_sha256'])
        if _material(actual) != native['material'] or launch['variant'] != asdict(plugin_store.variant):
            raise ValueError('existing plugin evidence differs from frozen calibration identity')
    if _reference(FIXED_PACKAGE)['sha256'] != FIXED_PACKAGE_SHA:
        raise ValueError('approved calibration package bytes changed')
    if plugin_store.variant.subject_id != FIXED_SUBJECT:
        raise ValueError('calibration candidate is not the approved frozen package')
    if (expected['runtime'].get('pi_version') != '1.4.0' or expected['model'].get('id') != 'deepseek-flash'
            or expected['model'].get('provider') != 'deepseek'):
        raise ValueError('calibration requires frozen Pi/model')
    value = {'schema_version': 'rsi-calibration-registration.v1', 'purpose': 'initial-grouping-only',
             'question_set_sha256': native['question_set_sha256'],
             'native_store': str(native_store.directory), 'native_variant': asdict(native_store.variant),
             'plugin_store': str(plugin_store.directory),
             'plugin_variant': asdict(plugin_store.variant), 'material': _material(expected)}
    path = registration_path(root, catalog)
    if path.exists():
        if _json(path) != value:
            raise ValueError('calibration already registered with different identity/evidence')
    else:
        atomic_json(path, value, immutable=True)
    return _reference(path)


FIXED_PACKAGE = Path.home()/'.local/share/memweave-experiments/rsi-validation-20261107/candidate/godice-memweave-0.1.0.tgz'
FIXED_PACKAGE_SHA = 'b93c8573347d8fca27a3226a488b70a77a8bb99b54d09373cc0a6aeac7845e40'
FIXED_SUBJECT = ('4ac655923776d23d6dbb8cea3bfc234d49b1de6d:'
                 'b93c8573347d8fca27a3226a488b70a77a8bb99b54d09373cc0a6aeac7845e40')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _key(row):
    return row['suite_id'], row['task_id']


def coverage(rows):
    return {field: dict(sorted(Counter(row[field] for row in rows).items()))
            for field in ('scenario', 'difficulty', 'suite_id')}


def _balanced_choice(catalog, intersection):
    """Gain new marginal coverage, then favor least represented labels, then order.

The hard floor needs at most four representatives. Selection never removes a
chosen task, so covering every available label (while seats remain) cannot erase
an attained floor. Source balance and broader coverage are soft goals only.
"""
    keys = [tuple(key) for key in intersection]
    allowed = {_key(row) for row in catalog['tasks']}
    if len(set(keys)) != len(keys) or not set(keys) <= allowed:
        raise ValueError('unknown or duplicate calibrated identity')
    eligible = [row for row in catalog['tasks'] if _key(row) in set(keys)]
    target = catalog_counts(catalog)['regression']
    if (len(eligible) < target or len({r['scenario'] for r in eligible}) < 2
            or len({r['difficulty'] for r in eligible}) < 2):
        raise ValueError(f'intersection cannot meet {target} and multiple scenario/difficulty floor')
    selected = []
    counts = {f: Counter() for f in ('scenario', 'difficulty', 'suite_id')}
    while len(selected) < target:
        def priority(index_row):
            index, row = index_row
            return (-sum(counts[f][row[f]] == 0 for f in counts),
                    sum(counts[f][row[f]] for f in counts), index)
        _, row = min(enumerate(eligible), key=priority)
        selected.append(row)
        eligible.remove(row)
        for f, counter in counts.items():
            counter[row[f]] += 1
    return [list(_key(row)) for row in catalog['tasks'] if row in selected]


def choose_regression(catalog, intersection):
    chosen = _balanced_choice(catalog, intersection)
    def diverse(rows):
        return len({r['scenario'] for r in rows}) >= 2 and len({r['difficulty'] for r in rows}) >= 2
    def complement(keys):
        selected = set(map(tuple, keys))
        return [r for r in catalog['tasks'] if _key(r) not in selected]
    if diverse(complement(chosen)):
        return chosen
    # Any set with >=2 scenarios and >=2 difficulties contains a pair
    # differing on both. Reserve such a pair for the complement; enumerating
    # all pairs is therefore an exact feasibility fallback, not a greedy veto.
    for a, b in combinations(catalog['tasks'], 2):
        if a['scenario'] == b['scenario'] or a['difficulty'] == b['difficulty']:
            continue
        remaining = [key for key in intersection if tuple(key) not in {_key(a), _key(b)}]
        try:
            return _balanced_choice(catalog, remaining)
        except ValueError:
            continue
    counts = catalog_counts(catalog)
    raise ValueError(f"no {counts['regression']}/{counts['capability']} partition meets both groups diversity floor")


def _grouped(catalog, keys):
    selected = {tuple(k) for k in keys}
    result = json.loads(json.dumps(catalog))
    result['regression_status'] = 'calibrated-qualified'
    for row in result['tasks']:
        row['split'] = 'regression' if _key(row) in selected else 'capability'
    return Catalog.model_validate(result).model_dump(mode='json')


def _freeze_value(catalog, native_store, plugin_store):
    catalog = Catalog.model_validate(catalog).model_dump(mode='json')
    if catalog['regression_status'] != 'candidates-unqualified':
        raise ValueError('grouping must derive from original unqualified catalog')
    reg = registration_path(native_store.root.parent, catalog)
    registration = _json(reg)
    expected_keys = {'schema_version', 'purpose', 'question_set_sha256', 'native_store',
                     'native_variant', 'plugin_store', 'plugin_variant', 'material'}
    if (set(registration) != expected_keys or registration['schema_version'] != 'rsi-calibration-registration.v1'
            or registration['purpose'] != 'initial-grouping-only'
            or registration['question_set_sha256'] != question_set_digest(catalog)
            or registration['native_store'] != str(native_store.directory)
            or registration['native_variant'] != asdict(native_store.variant)
            or registration['plugin_store'] != str(plugin_store.directory)
            or registration['plugin_variant'] != asdict(plugin_store.variant)
            or plugin_store.variant.subject_id != FIXED_SUBJECT):
        raise ValueError('grouping does not match initial calibration registration')
    native = _series_evidence(catalog, native_store, require_complete=True)
    plugin = _series_evidence(catalog, plugin_store, require_complete=True)
    if native['material'] != plugin['material'] or native['material'] != registration['material']:
        raise ValueError('calibration evidence material differs')
    intersection = sorted(set(map(tuple, native['passed'])) & set(map(tuple, plugin['passed'])))
    chosen = choose_regression(catalog, intersection)
    grouped = _grouped(catalog, chosen)
    return {'schema_version': 'rsi-calibrated-grouping.v1', 'purpose': 'initial-grouping-only',
            'algorithm': 'marginal-coverage-balance-original-order.v1',
            'registration': _reference(reg), 'native': native, 'plugin': plugin,
            'original_catalog': catalog, 'before_catalog_sha256': _digest(catalog), 'after_catalog_sha256': _digest(grouped),
            'regression': chosen, 'coverage': coverage([r for r in grouped['tasks'] if r['split'] == 'regression']),
            'original_candidate_coverage': coverage([r for r in catalog['tasks'] if r['split'] == 'regression'])}


def freeze_grouping(catalog, native_store, plugin_store, destination):
    native_store.assert_acquired()
    plugin_store.assert_acquired()
    destination = outside_repository(Path(destination))
    if destination != registration_path(native_store.root.parent, catalog).with_name('grouping.json'):
        raise ValueError('grouping must use the sole registered calibration destination')
    value = _freeze_value(catalog, native_store, plugin_store)
    if destination.exists():
        if _json(destination) != value:
            raise ValueError('initial grouping already frozen; replacement forbidden')
    else:
        atomic_json(destination, value, immutable=True)
    return dict(value, path=str(destination))


def load_grouping(catalog, path):
    from .rsi_scheduler import VariantIdentity
    path = outside_repository(Path(path))
    value = _json(_reference(path)['path'])
    native_data, plugin_data = value['native'], value['plugin']
    from .rsi_policy import is_active_policy, policy_for_catalog
    policy = policy_for_catalog(catalog)
    options = {'execution_policy': policy} if is_active_policy(policy) else {}
    native = ProgressStore(Path(native_data['store_root']), VariantIdentity(**native_data['variant']),
                           question_set_sha256=native_data['question_set_sha256'], **options)
    plugin_options = dict(options, question_set_sha256=plugin_data['question_set_sha256']) if options else {}
    plugin = ProgressStore(Path(plugin_data['store_root']), VariantIdentity(**plugin_data['variant']),
                           **plugin_options)
    if path != registration_path(native.root.parent, catalog).with_name('grouping.json'):
        raise ValueError('unregistered grouping location')
    if _freeze_value(catalog, native, plugin) != value:
        raise ValueError('frozen grouping evidence or selection changed')
    return _grouped(catalog, value['regression'])
