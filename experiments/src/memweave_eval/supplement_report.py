"""Versioned, offline appendices. Never regenerate or overwrite the v1 report."""

from __future__ import annotations

import csv
import io
import json
import subprocess
from pathlib import Path

from .case_oracles import score_case_suite
from .contract_evidence import task_contract_metrics
from .storage import atomic_json, contained, file_digest

VERSION = 'p0-cases-v2-20261101'


def generate_supplement(root: Path, output: Path, contracts_path: Path | None = None):
    root, output = root.resolve(), output.resolve()
    if output == root or output in root.parents or any(
            output == root/name or root/name in output.parents
            for name in ('reports', 'harbor', 'runtime-tasks', 'preparation')):
        raise ValueError('v2 output must not change original evidence or reports')
    if output.exists():
        raise ValueError('existing output is immutable; choose a new output directory')
    index_path = root/'evidence-index.json'
    index = json.loads(index_path.read_text())
    for item in index['files']:
        if file_digest(contained(root, item['path'])) != item['sha256']:
            raise ValueError('original evidence hash mismatch')
    baseline_path = root/'reports/results.json'
    baseline = json.loads(baseline_path.read_text())
    delivery = root/'reports/delivery-index.json'
    authenticated = False
    if delivery.exists():
        expected = next((f['sha256'] for f in json.loads(delivery.read_text())['files']
                         if f['path'] == 'reports/results.json'), None)
        if expected != file_digest(baseline_path):
            raise ValueError('original report hash mismatch')
        authenticated = True
    lock = json.loads((root/'experiment.lock.json').read_text())
    contracts = json.loads(contracts_path.read_text()) if contracts_path else {'schema_version':2,'trials':{}}
    if contracts.get('schema_version') != 2 or not isinstance(contracts.get('trials'), dict):
        raise ValueError('invalid evaluator contract bundle')
    experiment = Path(__file__).parents[2]
    gold_path = experiment/'cases/wasm-memory-task-v2.json'
    gold = json.loads(gold_path.read_text())
    fixtures = {}
    expected_values = {'positive':1, 'negative':0, 'missing':None}
    for name, expected in expected_values.items():
        path = experiment/f'fixtures/wasm-memory-task-v2/{name}.json'
        result = score_case_suite(gold, json.loads(path.read_text()))
        fixtures[name] = {'source_sha256':file_digest(path), 'result':result,
                          'matches_expected':all(c['value'] == expected for c in result['cases'])}
    if not all(f['matches_expected'] for f in fixtures.values()):
        raise ValueError('versioned oracle fixture validation failed')
    try:
        revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=experiment,text=True).strip()
        dirty = bool(subprocess.check_output(['git','status','--porcelain'],cwd=experiment,text=True))
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    modules = ('contract_metrics.py','contract_evidence.py','supplement_report.py',
               'case_oracles.py','behavior_metrics.py','cli.py')
    provenance = {'evaluator_version':VERSION,'evaluator_commit':revision,'evaluator_dirty':dirty,
        'evaluator_files':{name:file_digest(Path(__file__).parent/name)for name in modules},
        'model_run_commit':lock.get('experiment_commit'),
        'original_lock_sha256':file_digest(root/'experiment.lock.json'),
        'original_report':str(baseline_path),'original_report_sha256':file_digest(baseline_path),
        'original_report_hash_authenticated':authenticated,'raw_index_sha256':file_digest(index_path),
        'raw_files_verified':len(index['files']),
        'gold_version':gold['version'],'gold_sha256':file_digest(gold_path),
        'external_contracts_sha256':file_digest(contracts_path) if contracts_path else None,
        'paid_model_requests':0,'original_scores_changed':False,
        'case_interpretation':'Distinct offline oracle fixtures; not retrospective model scores or LLM capability validation'}
    trials = []
    for row in baseline['trials']:
        sources = row.get('session_sources') or []
        if not sources:
            raise ValueError('original trial has no auditable agent source')
        agent = contained(root, sources[0]).parent.parent.parent
        metrics = task_contract_metrics(agent, enabled=row['variant_id']=='pi-memweave',
                                       contracts=contracts['trials'].get(row['variant_id']))
        trials.append({'task_id':row['task_id'],'variant_id':row['variant_id'],
            'original_outcome':{k:row.get(k)for k in ('success','native_reward','usage','phase_seconds')},
            'metrics_v2':metrics})
    result = {'schema_version':2,'provenance':provenance,'trials':trials,
        'fixture_validation':{'cases':len(gold['cases']), 'variants':list(fixtures),
                              'all_expected_verdicts':True,
                              'actual_model_coverage':'not_evaluated_new_cases_not_preregistered'}}
    # All validation occurs before creating any output.
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output/'metrics.json', result, immutable=True)
    atomic_json(output/'case-fixture-validation.json', {'provenance':provenance,'fixtures':fixtures}, immutable=True)
    stream = io.StringIO()
    fields = ['variant','metric','numerator','denominator','unknown','not_applicable','value','coverage','status']
    writer = csv.DictWriter(stream,fieldnames=fields)
    writer.writeheader()
    lines = ['# P0指标v2补充报告','',f'评估器：{VERSION}；原模型运行：{root.name}。',
             '', '这是事后离线补充；原v1分数/报表/金标保持不变，新案例只验证程序oracle。',
             '', '| 变体 | 指标 | 分子/已知分母 | unknown | N/A | 值 | 覆盖率 |',
             '|---|---|---:|---:|---:|---:|---:|']
    for trial in trials:
        metrics = trial['metrics_v2']
        items = {k:metrics[k]for k in ('state_latest_at_prepare','state_confirmed_receipt_lower_bound',
                                       'window_integrity','reference_integrity')}
        items.update({f'logical_{k}':metrics['logical_operations'][k]for k in ('recovery','retry_load')})
        for name, value in items.items():
            writer.writerow(dict(variant=trial['variant_id'],metric=name,
                                  **{k:value.get(k)for k in fields[2:]}))
            display = value['value'] if value['value'] is not None else value['status']
            lines.append(f"| {trial['variant_id']} | {name} | {value['numerator']}/{value['denominator']} | "
                         f"{value['unknown']} | {value['not_applicable']} | {display} | {value['coverage']} |")
    lines.extend(['','State回执版本下界通过不代表完整新鲜度：错误但已提交、并发或未观测提交仍可能高于该下界。',
                  'Window缺预期完整投影/assistant调用ID时unknown；零引用读取仅表示机械读取指标N/A。',
                  '',f"独立案例：{len(gold['cases'])}例，正例全部1、负例全部0、缺证据全部unknown；没有新增LLM实验。"])
    (output/'metrics.csv').write_text(stream.getvalue())
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    atomic_json(output/'artifact-index.json',{'provenance':provenance,'files':[
        {'path':p.name,'sha256':file_digest(p)}for p in sorted(output.iterdir())if p.is_file()]},immutable=True)
    return result
