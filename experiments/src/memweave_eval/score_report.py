"""Existing evaluator's detailed score views and immutable historical supplements."""
from __future__ import annotations

import csv
import io
import json
import shutil
from copy import deepcopy
from pathlib import Path

from .normalized_scores import VERSION, attach_normalized_scores, catalogue
from .storage import atomic_json, contained, file_digest

SCORE_COLUMNS = tuple(f'normalized_{profile}_{key}'
                      for profile in ('common_product', 'plugin_memory')
                      for key in ('score', 'observed_score', 'coverage', 'lower', 'upper', 'status'))
LONG_COLUMNS = ('task_id', 'variant_id', 'id', 'meaning', 'raw', 'observed_raw', 'unit', 'raw_formula',
                'direction', 'score', 'status', 'coverage', 'lower', 'upper',
                'score_formula', 'mapping_version', 'weight', 'weights', 'weight_basis',
                'threshold_basis', 'score_qualification', 'reason', 'source', 'source_hash', 'support',
                'support_s', 'support_f', 'support_u', 'support_n')


def _display(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.6g}'
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return str(value)


def _cell(value):
    return _display(value).replace('|', '\\|').replace('\n', '<br>')


def normalization_markdown(rows, summary=None):
    lines = ['', '## 原始口径与百分制评分', '',
             (f'映射版本 `{VERSION}`。完整逐项解释、原值、分数、公式、权重和来源见 '
              '[normalized-scores.md](normalized-scores.md) / [CSV](normalized-scores.csv)。'),
             ('两类固定各50%。点总分仅完整覆盖时展示；已观测均分是条件统计，'
              '缺失权重不重分。区间下限是已证实贡献，不是把未知判0。'), '',
             '|任务|组|profile|工程已观测分/覆盖|行为已观测分/覆盖|点总分|已观测总均分|固定权重覆盖|完整区间|状态|',
             '|---|---|---|---|---|---:|---:|---:|---|---|']
    for row in rows:
        for profile, value in row['normalized_scores']['profiles'].items():
            classes = value.get('classes') or {}
            def cls(name, classes=classes):
                c = classes.get(name) or {}
                return f"{_display(c.get('observed_score'))}/{_display(c.get('coverage'))}"
            fields = (row['task_id'], row['variant_id'], profile, cls('engineering'), cls('behavior'),
                      value.get('score'), value.get('observed_score'), value['coverage'],
                      f"[{_display(value['lower'])},{_display(value['upper'])}]" if value['status'] != 'not_applicable' else 'N/A', value['status'])
            lines.append('|' + '|'.join(_cell(v) for v in fields) + '|')
    lines += ['', ('缓存利用度、相对费用指数权重0；低费用不能奖励质量或记忆分。'
              '自然未触发的检索/引用仍留覆盖缺口，原生无State使用结构性N/A的独立profile。'
              '不同已知子集的条件均分不能直接判胜。同题先看共同证据权重比较，跨题按任务等权宏平均。')]
    if summary:
        lines += ['', '|同题公共profile|共同证据权重覆盖|原生共同已知分|插件共同已知分|插件−原生|状态|',
                  '|---|---:|---:|---:|---:|---|']
        for pair in summary['pairs']:
            fields = (pair['task_id'], pair.get('shared_weight_coverage'), pair.get('native_shared_observed_score'),
                      pair.get('plugin_shared_observed_score'), pair.get('plugin_minus_native_shared'), pair['status'])
            lines.append('|'+'|'.join(_cell(v) for v in fields)+'|')
    return lines


def write_score_artifacts(output: Path, rows, summary):
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output/'normalized-scores.json', {'version': VERSION, 'summary': summary,
                'registry': catalogue(), 'trials': [dict(task_id=r['task_id'], variant_id=r['variant_id'],
                repetition=r.get('repetition', 1), **r['normalized_scores']) for r in rows]})
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=LONG_COLUMNS, extrasaction='ignore')
    writer.writeheader()
    lines = ['# 每项原始口径与百分制说明', '', f'版本：{VERSION}。权重列给出两个profile的固定总权重。',
             '诊断行无内在优劣基准，不凭计数创造质量分。unknown/N/A/invalid不填0或100。', '']
    for row in rows:
        lines += [f"## {row['task_id']} / {row['variant_id']}", '',
                  '|ID / 指标含义|原值 / 单位|原始计算方式|百分制 / 状态 / 覆盖 / 区间|转换公式|权重及依据|阈值依据|缺失/资格说明|来源|',
                  '|---|---|---|---|---|---|---|---|---|']
        for m in row['normalized_scores']['metrics']:
            record = {'task_id': row['task_id'], 'variant_id': row['variant_id'], **m}
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in record.items() if k in LONG_COLUMNS})
            score = f"{_display(m['score'])} / {m['status']} / {m['coverage']:.4g} / [{m['lower']:.6g},{m['upper']:.6g}]"
            raw = f"{_display(m['raw'])} / {m['unit']}"
            if m['support'] is not None:
                raw += (f"; 已知子集原比率={_display(m['observed_raw'])}; "
                        f"s/f/u/n={_display(m['support_s'])}/{_display(m['support_f'])}/"
                        f"{_display(m['support_u'])}/{_display(m['support_n'])}; 原分子分母={_display(m['support'])}")
            fields = (m['id']+' / '+m['meaning'], raw,
                      m['raw_formula'], score, m['score_formula'],
                      f"{_display(m['weights'])}; {m['weight_basis']}", m['threshold_basis'],
                      m.get('reason') or m.get('score_qualification') or '证据完整', m['source'])
            lines.append('|' + '|'.join(_cell(v) for v in fields) + '|')
    (output/'normalized-scores.csv').write_text(stream.getvalue())
    (output/'normalized-scores.md').write_text('\n'.join(lines)+'\n')
    weights = io.StringIO()
    writer = csv.DictWriter(weights, fieldnames=('profile', 'class', 'class_weight', 'family',
                                                'family_within_class', 'metric_id', 'leaf_within_family', 'total_weight'))
    writer.writeheader()
    for profile, declaration in catalogue()['profiles'].items():
        for cls in ('engineering', 'behavior'):
            for family, detail in declaration[cls].items():
                for identity, leaf in detail['leaves'].items():
                    writer.writerow({'profile': profile, 'class': cls,
                        'class_weight': declaration['class_weights'][cls], 'family': family,
                        'family_within_class': detail['weight'], 'metric_id': identity,
                        'leaf_within_family': leaf, 'total_weight': declaration['class_weights'][cls]*detail['weight']*leaf})
    (output/'normalized-weights.csv').write_text(weights.getvalue())


def generate_score_report(source: Path, output: Path):
    source, output = source.resolve(), output.resolve()
    if output.exists() or output == source or output in source.parents:
        raise ValueError('score-report requires a new independent output directory')
    original = json.loads(source.read_text())
    inputs = {str(source): file_digest(source)}
    for item in original.get('normalization_inputs', []):
        path = Path(item['path'])
        if not path.is_file() or file_digest(path) != item['sha256']:
            raise ValueError('normalization input hash mismatch')
        inputs[str(path)] = item['sha256']
        if path.name == 'evidence-index.json':
            index = json.loads(path.read_text())
            for entry in index['files']:
                if file_digest(contained(path.parent, entry['path'])) != entry['sha256']:
                    raise ValueError('original evidence hash mismatch')
    for root in original.get('protected_roots', []):
        root = Path(root).resolve()
        if output == root or output.is_relative_to(root) and not output.is_relative_to(root/'supplements'):
            raise ValueError('output must not modify original reports, raw data or ledgers')
    rows = deepcopy(original.get('trials', original.get('rows', [])))
    if not isinstance(rows, list) or not rows:
        raise ValueError('score-report input requires trial rows')
    for row in rows:
        row.setdefault('_normalization_source', {'file': str(source), 'sha256': inputs[str(source)]})
    summary = attach_normalized_scores(rows)
    provenance = {'version': VERSION, 'inputs': inputs, 'paid_model_requests': 0,
                  'original_files_modified': False,
                  'evaluator_files': {p.name: file_digest(p) for p in
                    [Path(__file__), Path(__file__).with_name('normalized_scores.py'),
                     Path(__file__).with_name('score_catalog.json')]}}
    output.mkdir(parents=True, exist_ok=False)
    write_score_artifacts(output, rows, summary)
    atomic_json(output/'provenance.json', provenance, immutable=True)
    (output/'report.md').write_text('# 历史实验百分制独立重算\n\n'+'\n'.join(normalization_markdown(rows, summary))+'\n')
    # Copy the already-small registry for portable offline review, never original Sessions.
    shutil.copyfile(Path(__file__).with_name('score_catalog.json'), output/'registry.json')
    if any(file_digest(Path(p)) != expected for p, expected in inputs.items()):
        raise ValueError('original scoring inputs changed during report generation')
    atomic_json(output/'artifact-index.json', {'files': [
        {'path': p.name, 'sha256': file_digest(p)} for p in sorted(output.iterdir()) if p.is_file()]}, immutable=True)
    return {'output': str(output), 'summary': summary, 'provenance': provenance}
