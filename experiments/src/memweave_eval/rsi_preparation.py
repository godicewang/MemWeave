"""Append-only exact task qualifications and immutable catalog admission snapshots.

Only pre-execution blocks may be retried on a later explicit invocation. Once
execution starts, a missing complete receipt requires investigation, not replay.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import time
import uuid
from pathlib import Path

from .actor_adapter import RSI_PI
from .storage import atomic_json, contained, file_digest

VARIANTS = ('pi-native', 'pi-memweave')


def task_key(row):
    return row['suite_id']+'/'+row['task_id']


def select_rows(catalog, split, task_ids=None):
    if split not in ('all', 'regression', 'capability'):
        raise ValueError('invalid preparation target split')
    rows = [row for row in catalog['tasks'] if split == 'all' or row['split'] == split]
    if task_ids is None:
        return rows
    if (not isinstance(task_ids, (list, tuple)) or not 1 <= len(task_ids) <= 200
            or any(not isinstance(key, str) for key in task_ids)
            or len(set(task_ids)) != len(task_ids)):
        raise ValueError('select 1..200 unique explicit suite/task identities')
    if not set(task_ids) <= {task_key(row) for row in rows}:
        raise ValueError('selected task is not an exact identity in the target split')
    return [row for row in rows if task_key(row) in task_ids]


def proof(root, path):
    relative = path.relative_to(root).as_posix()
    return {'path': relative, 'sha256': file_digest(contained(root, relative))}


def read_proof(root, entry):
    path = contained(root, entry['path'])
    if file_digest(path) != entry['sha256']:
        raise ValueError('preparation evidence changed: '+entry['path'])
    return json.loads(path.read_text())


def terminal_jobs(root, names):
    """Pin actual child terminal receipts and their immutable launch configs."""
    records = {}
    for name in names:
        records[name] = {kind: proof(root, root/path) for kind, path in (
            ('config', f'configs/{name}.json'),
            ('start', f'lifecycle/{name}.start.json'),
            ('end', f'lifecycle/{name}.end.json'))}
        config = read_proof(root, records[name]['config'])
        records[name]['overlays'] = [proof(root, Path(path))
            for path in config.get('environment', {}).get('extra_docker_compose', [])]
    verify_jobs(root, records)
    return records


def verify_jobs(root, records, *, allow_failure=False):
    from .rsi_recovery import _valid_identity

    for name, entries in records.items():
        config = read_proof(root, entries['config'])
        start = read_proof(root, entries['start'])
        end = read_proof(root, entries['end'])
        if (config.get('job_name') != name or start.get('job_name') != name
                or end.get('job_name') != name or end.get('status') != 'terminal'
                or type(end.get('return_code')) is not int
                or (not allow_failure and end['return_code'] != 0)
                or not start.get('identity') or start['identity'] != end.get('identity')
                or start.get('config_sha256') != entries['config']['sha256']
                or end.get('config_sha256') != entries['config']['sha256']
                or not _valid_identity(start.get('process_identity'))
                or end.get('process_identity') != start['process_identity']):
            raise ValueError('preparation child termination/configuration not verified')


def identity(spec, catalog, split, environment_identity):
    from . import rsi_runtime as runtime

    config = spec.model_dump(mode='json')
    value = {'schema_version': 2, 'kind': 'incremental-preparation-store', 'split': split,
            'sources': catalog['sources'], 'environment': environment_identity,
            'rows': select_rows(catalog, split), 'catalog_sha256': file_digest(spec.catalog),
            'evaluator_sha256': runtime.evaluator_digest(),
            'software': {key: config[key] for key in (
                'subject', 'runtime', 'model', 'platform', 'source_cache', 'root')}}
    from .rsi_policy import is_active_policy, policy_for_catalog

    policy = policy_for_catalog(catalog)
    if is_active_policy(policy):
        value.update(catalog_id=catalog['id'], execution_policy=policy)
    return value


def catalog_from_contract(contract):
    """Reconstruct saved sources without inferring a new policy from row counts."""
    from .rsi_policy import is_active_policy, policy_for_catalog, validate_policy

    catalog = {'sources': contract['sources'], 'tasks': contract['rows']}
    if 'catalog_id' not in contract and 'execution_policy' not in contract:
        return catalog  # Legacy immutable stores did not save either field.
    policy = validate_policy(contract.get('execution_policy'))
    catalog['id'] = contract.get('catalog_id')
    if not is_active_policy(policy) or policy_for_catalog(catalog) != policy:
        raise ValueError('preparation catalog and execution policy identity changed')
    return catalog


def task_identity(spec, catalog, row, *, environment_identity):
    """Selection metadata is not execution identity; official source identity is."""
    sources = [source for source in catalog['sources'] if source['id'] == row['suite_id']]
    if len(sources) != 1:
        raise ValueError('exact task official source is missing or ambiguous')
    config = spec.model_dump(mode='json')
    from .rsi_runtime import evaluator_digest

    if not isinstance(environment_identity, dict) or not environment_identity:
        raise ValueError('stable qualified environment identity missing')
    value = {'schema_version': 2, 'environment': environment_identity,
            'original': {key: row[key] for key in ('suite_id', 'task_id', 'original_path', 'sha256')},
            'source': sources[0], 'evaluator_sha256': evaluator_digest(),
            'software': {key: config[key] for key in (
                'subject', 'runtime', 'model', 'platform', 'source_cache', 'root')}}
    from .rsi_policy import is_active_policy, policy_for_catalog

    policy = policy_for_catalog(catalog)
    if is_active_policy(policy):
        value['execution_policy'] = policy
    return value


def verify_store(spec, root, catalog, environment_identity, split=None):
    original = json.loads(contained(root, 'store.json').read_text())
    catalog_from_contract(original)
    current = identity(spec, catalog, original['split'] if split is None else split, environment_identity)
    if any(original.get(key) != current.get(key) for key in (
            'schema_version', 'kind', 'split', 'evaluator_sha256', 'software', 'environment',
            'catalog_id', 'execution_policy')):
        raise ValueError('preparation store identity changed; no reuse or replay allowed')
    return current


def qualified_environment(spec, catalog, split, *, plan=None):
    from . import rsi_runtime as runtime

    plan = plan if plan is not None else runtime.inspect_plan(
        spec, split=split, _validated=(catalog, {}))
    value = plan.get('environment', {}).get('qualification_identity')
    if not isinstance(value, dict) or not value:
        raise ValueError('stable qualified environment identity missing')
    return copy.deepcopy(value)


def snapshot_key(contract):
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def task_directory(root, row, qualification):
    digest = hashlib.sha256(task_key(row).encode()).hexdigest()
    # The final directory name also owns Docker aliases and labels: never generic 'attempt'.
    owner = hashlib.sha256((str(root)+'\0'+snapshot_key(qualification)).encode()).hexdigest()[:24]
    return contained(root, f'tasks/{digest}/attempt-{owner}')


def verify_backend_probe(value, node_version, *, historical=False):
    node = value.get('node_path')
    legacy = historical and value.get('schema_version') == 1
    flags = ['-w', '2'] if legacy else ['-x']
    command = ['flock', *flags, '/logs/agent/mock-backend-preflight.lock', node, '-e',
               'process.stdout.write("memweave-node-flock-ready")']
    if (value.get('schema_version') != (1 if legacy else 2)
            or not legacy and value.get('process_timeout_ms') != 4000
            or value.get('backend') != 'node'
            or value.get('scope') != 'independent-synthetic-quota'
            or value.get('node_version') != 'v'+node_version or value.get('passed') is not True
            or type(value.get('return_code')) is not int or value['return_code'] != 0
            or value.get('error_code') is not None or value.get('signal') is not None
            or value.get('stdout') != 'memweave-node-flock-ready'
            or not isinstance(node, str) or not node.startswith('/')
            or value.get('command') != command):
        raise ValueError('independent synthetic Node/flock backend preflight not verified')


def verify_task(spec, root, row, contract, *, catalog=None):
    return _verify_task_evidence(spec, root, row, contract, catalog=catalog, historical=False)


def verify_historical_task(spec, root, row, contract, *, catalog):
    """Read old complete evidence only; never qualifies an environment for execution."""
    _verify_task_evidence(spec, root, row, contract, catalog=catalog, historical=True)
    return {'historical_evidence_verified': True, 'execution_qualified': False}


def _verify_task_evidence(spec, root, row, contract, *, catalog, historical):
    from . import rsi_runtime as runtime
    from .images import inspect_image, verify_prepared_task
    from .runtime_cache import create_plan, snapshot

    started = json.loads(contained(root, 'started.json').read_text())
    store = root.parents[2]
    catalog = runtime.load_catalog(spec.catalog) if catalog is None else catalog
    def expected_for(item):
        value = task_identity(spec, catalog, item, environment_identity=contract['environment'])
        if historical:
            value['evaluator_sha256'] = contract['evaluator_sha256']
        return value
    expected_identity = expected_for(row)
    if (started.get('qualification') != expected_identity
            or started.get('store_sha256') != file_digest(store/'store.json')):
        raise ValueError('preparation task/store identity changed')
    receipt_proof = json.loads(contained(root, 'task-receipt-proof.json').read_text())
    if receipt_proof.get('path') != 'task-prepared.json':
        raise ValueError('task receipt ownership changed')
    value = read_proof(root, receipt_proof)
    if not historical or started.get('preparation_lifecycle_version') == 2:
        from .rsi_helpers import verify_lifecycle
        verify_lifecycle(root, value.get('preparation_lifecycle'), jobs=value.get('jobs', {}))
    current = spec.model_dump(mode='json')
    if (value.get('schema_version') != 2 or value.get('kind') != 'single-task-preparation'
            or value.get('qualification') != expected_identity
            or value.get('rows') != [started.get('row')]
            or expected_for(started['row']) != expected_identity
            or value.get('started_sha256') != file_digest(root/'started.json')
            or value.get('preparation_root') != str(root.resolve())
            or root != task_directory(store, row, expected_identity)
            or value.get('evaluator_sha256') != contract['evaluator_sha256']
            or value.get('transport_verified') is not True or value.get('model_requests') != 0
            or any(value['config'][key] != current[key] for key in contract['software'])
            or set(value['preparations']) != {task_key(row)}):
        raise ValueError('completed task preparation identity changed')
    environment_plan = read_proof(root, value['environment_plan'])
    if environment_plan.get('environment', {}).get('qualification_identity') != expected_identity['environment']:
        raise ValueError('qualified environment observation changed')
    record = value['preparations'][task_key(row)]
    if (record.get('source_sha256') != row['sha256'] or record.get('task_id') != row['task_id']
            or record.get('protocol_equivalent') is not True or record.get('platform') != spec.platform):
        raise ValueError('completed preparation does not prove the exact original task')
    verify_prepared_task(root, record)
    manifest = read_proof(root, {'path': record['manifest_path'], 'sha256': record['manifest_sha256']})
    if any(record.get(key) != item for key, item in manifest.items()):
        raise ValueError('original preparation manifest identity changed')
    for control, outcome in (('oracle', 'passed'), ('nop', 'failed')):
        if runtime.binary_outcome(read_proof(root, record[control])) != outcome:
            raise ValueError('original oracle/nop outcome no longer verifies')
    for variant in VARIANTS:
        verify_backend_probe(read_proof(root, record['backend_probes'][variant]),
                             spec.runtime.node_version, historical=historical)
        transport = read_proof(root, record['transport'][variant])
        if not (type(transport.get('real_model_requests')) is int
                and transport['real_model_requests'] == 0 and transport.get('positive') is True
                and transport.get('external_authority') is True
                and type(transport.get('lost_guard_upstream_requests')) is int
                and transport['lost_guard_upstream_requests'] == 0
                and transport.get('actual_cli_pid_deadline') is True):
            raise ValueError('exact CLI transport proof failed')
        probe = read_proof(root, record['probes'][variant])
        if type(probe.get('model_requests')) is not int or probe['model_requests'] != 0:
            raise ValueError('software preflight must contain no model requests')
        if read_proof(root, record['runtime_results'][variant]).get('exception_info'):
            raise ValueError('runtime preparation had an exception')
    cleanups = value.get('cleanup_proofs', [])
    expected_cleanup = {'container-cleanup.json', 'private/fixture-000/cleanup.json',
                        *{f'private/fixture-000/{v}/cleanup.json' for v in VARIANTS}}
    if len(cleanups) != 4 or {entry['path'] for entry in cleanups} != expected_cleanup:
        raise ValueError('complete preparation cleanup evidence missing')
    for entry in cleanups:
        cleanup = read_proof(root, entry)
        if entry['path'] == 'private/fixture-000/cleanup.json':
            valid = (cleanup.get('stopped') is True and cleanup.get('terminal_available') is True
                     and cleanup.get('networks_confirmed') is True)
        else:
            valid = cleanup.get('confirmed') is True
            if entry['path'] != 'container-cleanup.json':
                valid = valid and cleanup.get('network', {}).get('confirmed') is True
        if not valid:
            raise ValueError('preparation cleanup unconfirmed')
    names = {'control-000-oracle', 'control-000-nop',
             'runtime-000-pi-native', 'runtime-000-pi-memweave'}
    if set(value.get('jobs', {})) != names:
        raise ValueError('complete preparation process evidence missing')
    verify_jobs(root, value['jobs'])
    for name, entries in value['jobs'].items():
        cfg = read_proof(root, entries['config'])
        if (cfg.get('tasks') != [{'path': str(root/record['runtime_path'])}]
                or cfg.get('n_attempts') != 1 or cfg.get('n_concurrent_trials') != 1
                or cfg.get('retry') != {'max_retries': 0} or len(cfg.get('agents', [])) != 1):
            raise ValueError('control job does not bind the exact original runtime task')
        overlays = entries.get('overlays', [])
        expected_paths = cfg.get('environment', {}).get('extra_docker_compose', [])
        if len(overlays) != 1 or expected_paths != [str(root/entry['path']) for entry in overlays]:
            raise ValueError('preparation overlay ownership missing or changed')
        for entry in overlays:
            path = contained(root, entry['path'])
            if file_digest(path) != entry['sha256']:
                raise ValueError('preparation evidence changed: '+entry['path'])
            import yaml

            overlay = yaml.safe_load(path.read_text())
            owner = (root.name if name.startswith('control-') else
                     root.name+'-preflight-000-'+name.removeprefix('runtime-000-'))
            main = overlay.get('services', {}).get('main', {})
            if (main.get('platform') != spec.platform
                    or main.get('labels', {}).get('org.memweave.eval.run') != owner):
                raise ValueError('preparation overlay ownership changed')
        agent = cfg['agents'][0]
        if name.startswith('control-'):
            if agent != {'name': name.rsplit('-', 1)[1]} or 'verifier' in cfg:
                raise ValueError('original oracle/nop execution changed')
        else:
            variant = name.removeprefix('runtime-000-')
            options = agent.get('kwargs', {})
            expected_options = {'variant': variant, 'prepare_only': True, 'auth_path': '',
                                'version': spec.runtime.pi_version,
                                'node_version': spec.runtime.node_version,
                                'package_path': str(spec.subject.package),
                                'package_sha256': spec.subject.sha256,
                                'runtime_plan': str(root/'runtime-assets.json'),
                                'runtime_plan_sha256': value['runtime_plan_sha256'],
                                'evaluation_quota_backend': 'node'}
            if (agent.get('import_path') != RSI_PI.entry(variant)
                    or cfg.get('verifier') != {'disable': True}
                    or any(options.get(key) != item for key, item in expected_options.items())):
                raise ValueError('native/plugin CLI execution identity changed')
    assets = read_proof(root, {'path': 'runtime-assets.json', 'sha256': value['runtime_plan_sha256']})
    lock = read_proof(root, {'path': 'runtime-assets.lock.json', 'sha256': value['runtime_lock_sha256']})
    if (assets != create_plan(spec, value['images'])
            or lock.get('plan_sha256') != value['runtime_plan_sha256']
            or snapshot(assets) != lock['objects']):
        raise ValueError('frozen preparation software objects changed')
    images = value['images']
    from .rsi_broker_probe import verify_selection

    read_proof(root, value['broker_selection'])
    probe = verify_selection(root, historical=historical)
    broker = value.get('broker_identity', {})
    if probe['image'] != broker:
        raise ValueError('broker capability proof refers to a different image')
    if not images or broker.get('reference') != value['broker_image']:
        raise ValueError('preparation broker image identity missing')
    for image in record['images'].values():
        matches = [item for item in images.values() if item['reference'] == image['reference']]
        if len(matches) != 1 or any(matches[0][key] != image[key]
                                    for key in ('id', 'platform', 'repo_digests')):
            raise ValueError('prepared image differs from exact original image manifest')
    if historical:
        return value
    env = runtime.tool_env(spec, runtime.load_catalog(spec.catalog))
    for image in [*images.values(), broker]:
        actual = inspect_image(image['reference'], env)
        if actual['id'] != image['id'] or actual['platform'] != image['platform']:
            raise ValueError('prepared image identity changed')
    return value


def record_failed_terminal(root, preparation, jobs, authority_entered, variants_entered, *, lifecycle=None):
    """Prove failed work stopped; never reuse its score or authorize its replay."""
    try:
        records = {name: {kind: proof(root, root/path) for kind, path in (
            ('config', f'configs/{name}.json'), ('start', f'lifecycle/{name}.start.json'),
            ('end', f'lifecycle/{name}.end.json'))} for name in jobs}
        paths = ['failed-cleanup.json']
        if authority_entered:
            paths.append('private/fixture-000/cleanup.json')
        paths.extend(f'private/fixture-000/{v}/cleanup.json' for v in variants_entered)
        value = {'schema_version': 2, 'kind': 'failed-terminal-preparation',
                 'started': proof(root, root/'started.json'),
                 'failure': proof(root, root/'incomplete.json'), 'preparation': preparation,
                 'jobs': records, 'authority_entered': authority_entered,
                 'preparation_lifecycle': lifecycle,
                 'variants_entered': variants_entered,
                 'cleanup_proofs': [proof(root, root/path) for path in paths]}
        if (root/'broker-probes').exists():
            value['broker_selection'] = proof(root, root/'broker-probes/selection.json')
        verify_failed_terminal(root, value)
        atomic_json(root/'failed-terminal.json', value, immutable=True)
    except (ValueError, OSError, KeyError, TypeError):
        # No terminal receipt is safer than inferring a stopped child or broker.
        return False
    return True


def verify_failed_terminal(root, value=None):
    from .images import verify_prepared_task

    if value is None:
        value = json.loads(contained(root, 'failed-terminal.json').read_text())
    started = read_proof(root, value['started'])
    failure = read_proof(root, value['failure'])
    strict = started.get('preparation_lifecycle_version') == 2
    if strict:
        from .rsi_helpers import verify_lifecycle
        if value.get('schema_version') != 2 or not value.get('preparation_lifecycle'):
            raise ValueError('future failed preparation lifecycle missing')
        verify_lifecycle(root, value['preparation_lifecycle'], jobs=value['jobs'])
    if (value.get('kind') != 'failed-terminal-preparation' or (not strict and not value.get('jobs'))
            or started['store_sha256'] != file_digest(root.parents[2]/'store.json')
            or failure.get('execution_started') is not True
            or failure.get('complete') is not False or failure.get('cleanup_confirmed') is not True):
        raise ValueError('failed task terminal identity not verified')
    if (root/'broker-probes').exists():
        from .rsi_broker_probe import verify_selection

        read_proof(root, value['broker_selection'])
        # Failure cleanup grants no qualification. Recheck the actual frozen
        # source, helper command and output, even after the live evaluator moves.
        verify_selection(root, require_success=False, historical=True)
    record = value['preparation']
    if (record.get('source_sha256') != started['row']['sha256']
            or record.get('task_id') != started['row']['task_id']
            or record.get('protocol_equivalent') is not True):
        raise ValueError('failed task original image preparation not verified')
    verify_prepared_task(root, record)
    verify_jobs(root, value['jobs'], allow_failure=True)
    expected = {'failed-cleanup.json'}
    if value['authority_entered']:
        expected.add('private/fixture-000/cleanup.json')
    variants = value['variants_entered']
    if (not isinstance(value['authority_entered'], bool) or len(variants) != len(set(variants))
            or not set(variants) <= set(VARIANTS) or (variants and not value['authority_entered'])):
        raise ValueError('failed preparation phase ownership unclear')
    expected.update(f'private/fixture-000/{v}/cleanup.json' for v in variants)
    cleanups = value['cleanup_proofs']
    if len(cleanups) != len(expected) or {p['path'] for p in cleanups} != expected:
        raise ValueError('failed preparation cleanup evidence missing')
    for entry in cleanups:
        cleanup = read_proof(root, entry)
        if entry['path'] == 'private/fixture-000/cleanup.json':
            valid = (cleanup.get('stopped') is True and cleanup.get('terminal_available') is True
                     and cleanup.get('networks_confirmed') is True)
        else:
            valid = cleanup.get('confirmed') is True
            if entry['path'] != 'failed-cleanup.json':
                valid = valid and cleanup.get('network', {}).get('confirmed') is True
        if not valid:
            raise ValueError('failed preparation cleanup unconfirmed')
    return failure


def aggregate(root, completed):
    preparations, images, receipts = {}, {}, {}
    for key, (folder, value) in completed.items():
        prefix = folder.relative_to(root).as_posix()+'/'
        record = copy.deepcopy(value['preparations'][key])
        for field in ('runtime_path', 'manifest_path', 'config_diff'):
            record[field] = prefix+record[field]
        for image in record['images'].values():
            image['build_log'] = prefix+image['build_log']
        for field in ('oracle', 'nop'):
            record[field]['path'] = prefix+record[field]['path']
        for field in ('transport', 'probes', 'runtime_results', 'backend_probes'):
            for entry in record[field].values():
                entry['path'] = prefix+entry['path']
        preparations[key] = record
        for name, image in value['images'].items():
            images[key+(':verifier' if name.endswith(':verifier') else '')] = image
        receipts[key] = proof(root, folder/'task-prepared.json')
    return preparations, images, receipts


def _immutable_or_equal(path, value):
    if path.exists():
        if path.is_symlink() or json.loads(path.read_text()) != value:
            raise ValueError('incomplete final seal has conflicting immutable evidence')
    else:
        atomic_json(path, value, immutable=True)


def _snapshot(spec, root, contract, completed, *, final=False):
    """No mutable aggregate assets: each readiness wave owns its immutable view."""
    from .runtime_cache import create_plan, snapshot

    preparations, images, receipts = aggregate(root, completed)
    scope = {'contract': contract, 'config': spec.model_dump(mode='json'),
             'task_receipts': receipts, 'final': final}
    folder = contained(root, ('seals/' if final else 'admissions/')+snapshot_key(scope))
    if (folder/'prepared.json').exists():
        frozen = json.loads(contained(folder, 'prepared.json').read_text())
        for filename, field in (('container-cleanup.json', 'cleanup_sha256'),
                                ('runtime-assets.json', 'runtime_plan_sha256'),
                                ('runtime-assets.lock.json', 'runtime_lock_sha256')):
            if field in frozen:
                read_proof(folder, {'path': filename, 'sha256': frozen[field]})
    value = {'schema_version': 3, 'kind': 'complete-preparation' if final else 'partial-admission',
             'config': spec.model_dump(mode='json'), 'split': contract['split'],
             'rows': contract['rows'], 'catalog_sha256': contract['catalog_sha256'],
             'evaluator_sha256': contract['evaluator_sha256'], 'transport_verified': True,
             'preparations': preparations, 'images': images, 'model_requests': 0,
             'store_sha256': file_digest(root/'store.json'), 'task_receipts': receipts,
             'preparation_root': str(root), 'contract': contract,
             'admission_path': str(folder/'prepared.json')}
    if completed:
        assets = create_plan(spec, images)
        _immutable_or_equal(folder/'runtime-assets.json', assets)
        _immutable_or_equal(folder/'runtime-assets.lock.json', {
            'plan_sha256': file_digest(folder/'runtime-assets.json'), 'objects': snapshot(assets)})
        value.update({key: next(iter(completed.values()))[1][key]
                      for key in ('broker_image', 'broker_identity')})
        value.update(runtime_plan_path=str(folder/'runtime-assets.json'),
                     runtime_lock_path=str(folder/'runtime-assets.lock.json'),
                     runtime_plan_sha256=file_digest(folder/'runtime-assets.json'),
                     runtime_lock_sha256=file_digest(folder/'runtime-assets.lock.json'))
    _immutable_or_equal(folder/'container-cleanup.json', {
        'confirmed': True, 'scope': 'all listed exact task receipts verified', 'task_receipts': receipts})
    value['cleanup_path'] = str(folder/'container-cleanup.json')
    value['cleanup_sha256'] = file_digest(folder/'container-cleanup.json')
    _immutable_or_equal(folder/'prepared.json', value)
    return value


def seal(spec, root, contract, completed):
    from . import rsi_runtime as runtime

    if set(completed) != {task_key(row) for row in contract['rows']}:
        raise ValueError('requested split was not completely prepared')
    if runtime.evaluator_digest() != contract['evaluator_sha256']:
        raise ValueError('evaluator changed during preparation; refusing final seal')
    value = _snapshot(spec, root, contract, completed, final=True)
    # Keep the first historical entry point byte-identical across later catalogs.
    if not (root/'prepared.json').exists():
        atomic_json(root/'prepared.json', value, immutable=True)
    return value


def _collect(spec, root, catalog, contract):
    completed, unresolved, failed = {}, [], []
    # Inspect every historic attempt too: deleting its catalog slot is not cleanup.
    expected = {task_key(row): row for row in contract['rows']}
    for folder in sorted((root/'tasks').glob('*/attempt-*')):
        started = json.loads(contained(folder, 'started.json').read_text())
        if started.get('store_sha256') != file_digest(root/'store.json'):
            raise ValueError('preparation task/store identity changed')
        historical_row = started['row']
        key = task_key(historical_row)
        if folder != task_directory(root, historical_row, started.get('qualification')):
            raise ValueError('preparation ownership changed')
        if (folder/'task-prepared.json').exists():
            # A removed original cannot be launched, but its prior cleanup still must verify.
            historical_catalog = dict(catalog, sources=[started['qualification']['source']])
            value = verify_task(spec, folder, historical_row, contract, catalog=historical_catalog)
            current_row = expected.get(key)
            if current_row is not None and task_identity(spec, catalog, current_row, environment_identity=contract['environment']) == started['qualification']:
                if key in completed:
                    raise ValueError('duplicate exact task qualification ownership')
                completed[key] = folder, value
        elif (folder/'failed-terminal.json').exists():
            failure = verify_failed_terminal(folder)
            current_row = expected.get(key)
            if current_row is not None and task_identity(spec, catalog, current_row, environment_identity=contract['environment']) == started.get('qualification'):
                failed.append({'task': key, 'execution_started': True, 'terminal_verified': True,
                               'reason': failure['reason'], 'evidence': str(folder)})
        else:
            unresolved.append({'task': key, 'execution_started': True,
                'reason': 'started preparation is incomplete; process/resource investigation required',
                'evidence': str(folder)})
    return completed, unresolved, failed


def verify_admitted(spec, root, split, *, plan=None):
    from . import rsi_runtime as runtime
    from .runner import verify_package

    root = Path(root)
    if root.is_symlink() or not root.is_absolute():
        raise ValueError('preparation store must be an absolute non-symlink path')
    catalog = runtime.load_catalog(spec.catalog)
    runtime.validate_catalog(catalog, spec.source_cache)
    verify_package(spec.subject.package, spec.subject.sha256, spec.subject.commit)
    contract = verify_store(spec, root, catalog, qualified_environment(spec, catalog, split, plan=plan))
    rows = select_rows(catalog, split)
    if any(row not in contract['rows'] for row in rows):
        raise ValueError('requested split was not completely prepared')
    completed, unresolved, _ = _collect(spec, root, catalog, contract)
    if unresolved or (root/'STOP_REQUESTED').exists():
        raise ValueError('preparation stopped or cleanup/process investigation required')
    selected = {task_key(row) for row in rows}
    completed = {key: value for key, value in completed.items() if key in selected}
    return _snapshot(spec, root, dict(contract, rows=rows, split=split), completed), rows


def verify_sealed(spec, root, split):
    from . import rsi_runtime as runtime
    from .runner import verify_package

    catalog = runtime.load_catalog(spec.catalog)
    runtime.validate_catalog(catalog, spec.source_cache)
    verify_package(spec.subject.package, spec.subject.sha256, spec.subject.commit)
    contract = verify_store(spec, root, catalog, qualified_environment(spec, catalog, split))
    completed, unresolved, _ = _collect(spec, root, catalog, contract)
    if unresolved or set(completed) != {task_key(row) for row in contract['rows']}:
        raise ValueError('requested split was not completely prepared; no final seal')
    rows = select_rows(catalog, split)
    if any(row not in contract['rows'] for row in rows):
        raise ValueError('requested split was not completely prepared')
    scope = {'contract': contract, 'config': spec.model_dump(mode='json'),
             'task_receipts': aggregate(root, completed)[2], 'final': True}
    path = contained(root, 'seals/'+snapshot_key(scope)+'/prepared.json')
    if not path.is_file():
        raise ValueError('requested split was not completely prepared; no final seal')
    # _snapshot rechecks every immutable byte; it cannot repair or replace a conflict.
    value = _snapshot(spec, root, contract, completed, final=True)
    historical = root/'prepared.json'
    if historical.exists():
        first = json.loads(contained(root, 'prepared.json').read_text())
        first_path = Path(first.get('admission_path', ''))
        if not first_path.is_absolute() or not first_path.is_relative_to(root):
            raise ValueError('requested split was not completely prepared: sealed ownership changed')
        original = json.loads(contained(root, first_path.relative_to(root).as_posix()).read_text())
        if first != original:
            raise ValueError('requested split was not completely prepared: sealed evidence changed')
    return value, rows


def fixture_terminal_evidence(folder, terminal):
    """Bind actual deterministic fixture request cessation, not its cleanup flag."""
    from .rsi_accounting import _read, recovered_accounting
    from .rsi_runtime import verify_broker_cleanup

    entered = (terminal.get('kind') == 'single-task-preparation'
               or terminal.get('authority_entered') is True)
    if not entered:
        return []
    fixture = folder/'private/fixture-000'
    control = fixture/'control'
    authority, cleanup_reference = _read(fixture/'cleanup.json')
    physical = verify_broker_cleanup(fixture/'broker', folder.name+'-preflight-000', authority)
    principals = [{'arm': variant, 'episode': folder.name+'-preflight-000'}
                  for variant in VARIANTS]
    report = recovered_accounting(control, principals=principals, broker_stopped=True)
    source = report['source']
    if 'transport_terminal' not in source:
        raise ValueError('preparation fixture request terminal evidence missing')
    return [*physical, cleanup_reference, source['transport_terminal'],
            source.get('quota_final', source.get('quota_snapshot'))]


def complete_preparation_work(lease, ticket, folder, row, terminal):
    """Settle only after caller verifies the full typed terminal and drains work."""
    cleanup = folder/'journal-cleanup.json'
    evidence = fixture_terminal_evidence(folder, json.loads(terminal.read_text()))
    atomic_json(cleanup, {
        'schema_version': 'rsi-preparation-journal-cleanup.v2', 'confirmed': True,
        'owner': folder.name, 'task': task_key(row), 'worker_drained': True,
        'started': {'path': str(folder/'started.json'), 'sha256': file_digest(folder/'started.json')},
        'verified_terminal': {'path': str(terminal), 'sha256': file_digest(terminal)},
        'evidence': evidence}, immutable=True)
    lease.complete_work(ticket, cleanup)


def prepare_incrementally(spec, destination, *, split='all', timeout_seconds=None,
                          task_ids=None, frozen_preparations=None, seal_only=False, lease=None):
    from . import rsi_runtime as runtime
    from .images import validate_frozen_preparation
    from .rsi_environment import DaemonLease
    from .runner import verify_package
    from .spec import outside_repository

    if not isinstance(lease, DaemonLease) or not lease.active:
        raise ValueError('active daemon lease required for preparation journal')
    if timeout_seconds is not None and (type(timeout_seconds) is not int or timeout_seconds <= 0):
        raise ValueError('preparation timeout must be a positive integer')
    if seal_only and (task_ids is not None or frozen_preparations):
        raise ValueError('seal-only does not accept execution selections or frozen images')
    if Path(destination).is_symlink():
        raise ValueError('preparation store cannot be a symlink')
    root = outside_repository(destination)
    catalog = runtime.load_catalog(spec.catalog)
    summary = runtime.validate_catalog(catalog, spec.source_cache)  # Always the full 200.
    rows = select_rows(catalog, split, task_ids)
    frozen_preparations = frozen_preparations or {}
    if not set(frozen_preparations) <= {task_key(row) for row in rows}:
        raise ValueError('frozen image input must name a selected task')
    verify_package(spec.subject.package, spec.subject.sha256, spec.subject.commit)
    environment_identity = qualified_environment(spec, catalog, split)
    contract = identity(spec, catalog, split, environment_identity)
    if root.exists():
        if not (root/'store.json').is_file():
            raise ValueError('existing directory is not an incremental preparation store')
        verify_store(spec, root, catalog, environment_identity, split)
    else:
        if seal_only:
            raise ValueError('seal-only requires an existing preparation store')
        root.mkdir(parents=True, mode=0o700)
        atomic_json(root/'store.json', contract, immutable=True)
    completed, unresolved, failed = _collect(spec, root, catalog, contract)
    reused = len(set(completed) & {task_key(row) for row in rows})
    selected_keys = {task_key(row) for row in rows}
    blocked = list(unresolved)+[item for item in failed if item['task'] in selected_keys]
    failed_keys = {item['task'] for item in failed}
    deadline = time.monotonic()+timeout_seconds if timeout_seconds is not None else math.inf
    if not seal_only and not unresolved:
        for row in rows:
            key = task_key(row)
            if key in completed or key in failed_keys:
                continue
            folder = task_directory(root, row, task_identity(spec, catalog, row, environment_identity=contract['environment']))
            plan = None
            try:
                if (root/'STOP_REQUESTED').exists() or time.monotonic() >= deadline:
                    raise ValueError('preparation stopped before task execution')
                plan = runtime.inspect_plan(spec, split=split, task_ids=[key],
                                            _validated=(catalog, summary))
                if qualified_environment(spec, catalog, split, plan=plan) != environment_identity:
                    raise ValueError('qualified environment identity changed before task execution')
                if not plan['environment']['ready']:
                    raise ValueError('environment/capacity preflight blocked; see task plan')
                source = runtime.source_paths(spec, dict(catalog, tasks=[row]))[
                    (row['suite_id'], row['task_id'])]
                runtime.require_preparation_storage(spec, source, runtime.tool_env(spec, catalog))
                frozen = None
                if key in frozen_preparations:
                    path = Path(frozen_preparations[key])
                    if path.is_symlink():
                        raise ValueError('frozen image manifest cannot be a symlink')
                    frozen = json.loads(path.read_text())
                    if (frozen.get('task_id') != row['task_id']
                            or frozen.get('source_sha256') != row['sha256']
                            or frozen.get('platform') != spec.platform):
                        raise ValueError('frozen image manifest is not the selected original identity')
                    validate_frozen_preparation(
                        source, spec.platform, runtime.tool_env(spec, catalog), frozen)
            except (ValueError, OSError, subprocess.CalledProcessError,
                    subprocess.TimeoutExpired) as exc:
                failure = {'task': key, 'execution_started': False, 'reason': str(exc)}
                if plan is not None:
                    failure['plan'] = plan
                atomic_json(folder.parent/'blocked'/f'{uuid.uuid4().hex}.json', failure, immutable=True)
                blocked.append(failure)
                continue
            folder.mkdir(parents=True, mode=0o700)
            atomic_json(folder/'started.json', {'row': row, 'qualification': task_identity(spec, catalog, row, environment_identity=contract['environment']),
                                               'store_sha256': file_digest(root/'store.json'),
                                               'started_at': time.time(),
                                               'preparation_lifecycle_version': 2}, immutable=True)
            if frozen is not None:
                atomic_json(folder/'frozen-input.json', frozen, immutable=True)
            ticket = lease.begin_work(folder.name, folder, daemon_identity=contract['environment'],
                evaluator_sha256=contract['evaluator_sha256'], kind='preparation-v2')
            try:
                brokers = {name: value['broker_identity']
                           for name, (_, value) in completed.items()}
                runtime._prepare_one(spec, folder, task_row=row, catalog=catalog, plan=plan,
                                     deadline=deadline, frozen=frozen, broker_images=brokers,
                                     lease=lease, work_ticket=ticket)
                completed[key] = folder, verify_task(spec, folder, row, contract)
                complete_preparation_work(lease, ticket, folder, row, folder/'task-prepared.json')
            except BaseException as exc:
                blocked.append({'task': key, 'execution_started': True, 'reason': str(exc),
                                'error': type(exc).__name__, 'evidence': str(folder)})
                atomic_json(root/'events'/f'{uuid.uuid4().hex}.json', {
                    'complete': False, 'completed_tasks': list(completed), 'blocked': blocked,
                    'model_requests': 0}, immutable=True)
                if (folder/'failed-terminal.json').exists():
                    verify_failed_terminal(folder)
                    complete_preparation_work(lease, ticket, folder, row, folder/'failed-terminal.json')
                    blocked[-1]['terminal_verified'] = True
                    if not isinstance(exc, Exception):
                        raise
                    continue  # Known failed controls stay failed; other tasks may proceed.
                if not isinstance(exc, Exception):
                    raise
                break  # Unknown child/resource state must never admit another task.
    missing = [task_key(row) for row in contract['rows'] if task_key(row) not in completed]
    if not missing:
        runtime.validate_catalog(runtime.load_catalog(spec.catalog), spec.source_cache)
        completed = {key: (folder, verify_task(spec, folder, next(
            row for row in contract['rows'] if task_key(row) == key), contract))
            for key, (folder, _) in completed.items()}
        if identity(spec, catalog, split, qualified_environment(spec, catalog, split)) != contract:
            raise ValueError('preparation store identity changed during execution')
        seal(spec, root, contract, completed)
    result = {'ok': not blocked and (not seal_only or not missing), 'prepared': not missing,
              'tasks': len(contract['rows']), 'selected_tasks': len(rows),
              'completed_tasks': len(completed), 'reused_tasks': reused, 'missing': missing,
              'blocked': blocked, 'path': str(root), 'model_requests': 0}
    atomic_json(root/'events'/f'{uuid.uuid4().hex}.json', result, immutable=True)
    atomic_json(root/'progress.json', result)
    return result
