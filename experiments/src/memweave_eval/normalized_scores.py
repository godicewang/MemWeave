"""Versioned 0–100 views; fixed weights never turn missing evidence into success."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

VERSION = 'normalized-20261102-v1'


@lru_cache(maxsize=1)
def catalogue():
    value = json.loads(Path(__file__).with_name('score_catalog.json').read_text())
    assert value['version'] == VERSION
    return value


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _safe_raw(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {'invalid_number': repr(value)}
    if isinstance(value, dict):
        return {k: _safe_raw(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_raw(v) for v in value]
    return value


def _empty(status='unknown', reason='required_evidence_missing'):
    return {'score': None, 'coverage': 0., 'lower': 0., 'upper': 100.,
            'status': status, 'reason': reason, 'observed_raw': None}


def score_value(value, mapping, *, support=None, status=None, reason=None):
    if support is not None and status!='invalid':
        counts=tuple(support.get(k)for k in ('numerator','denominator','unknown'))
        if any(v is None for v in counts):return _empty('unknown','rate_count_evidence_missing')
        num,den,unknown=counts
        if not all(_number(v)and v>=0 for v in counts)or num>den:
            return _empty('invalid','invalid_rate_counts')
        if status=='not_applicable'and den+unknown>0:
            return _empty('invalid','nonzero_opportunities_conflict_with_na_flag')
    if status in ('invalid', 'unknown', 'insufficient_sample', 'not_applicable'):
        return _empty(status, reason or status)
    if mapping == 'diagnostic':
        if value is None:
            return _empty(reason=reason or 'raw_diagnostic_evidence_missing')
        if _number(value) and value < 0 or isinstance(value, float) and not math.isfinite(value):
            return _empty('invalid', 'invalid_raw_diagnostic_value')
        return _empty('diagnostic', 'no_intrinsic_good_direction_or_preregistered_target')
    if support is not None:
        n, d, u = (support.get(k) for k in ('numerator', 'denominator', 'unknown'))
        if not all(_number(x) and x >= 0 for x in (n, d, u)) or n > d:
            return _empty('invalid', 'invalid_rate_counts')
        if value is not None and (not _number(value) or not 0 <= value <= 1):
            return _empty('invalid', 'invalid_original_rate_scalar')
        total = d + u
        if not total:
            return _empty('not_applicable', reason or 'no_eligible_opportunities')
        if mapping not in ('rate', 'rate_lower'):
            return _empty('invalid', 'count_support_for_nonrate_mapping')
        coverage = d / total
        raw = n / d if d else None
        if value is not None and raw is not None and not math.isclose(value, raw, rel_tol=1e-9, abs_tol=1e-12):
            return _empty('invalid', 'original_rate_scalar_disagrees_with_counts')
        observed = (100 * (1 - raw if mapping == 'rate_lower' else raw)) if d else None
        lo, hi = 100*n/total, 100*(n+u)/total
        if mapping == 'rate_lower':
            lo, hi = 100-hi, 100-lo
        return {'score': observed, 'coverage': coverage, 'lower': lo, 'upper': hi,
                'observed_raw': raw, 'status': 'scored' if not u else 'partial' if d else 'unknown',
                'reason': reason or ('unknown_opportunity_results' if u else None)}
    if value is None:
        return _empty(reason=reason or 'required_evidence_missing')
    if not _number(value) or value < 0:
        return _empty('invalid', 'negative_nonfinite_or_nonnumeric_value')
    if mapping in ('rate', 'rate_lower'):
        if value > 1:
            return _empty('invalid', 'rate_outside_closed_unit_interval')
        score = 100 * (1 - value if mapping == 'rate_lower' else value)
    elif mapping == 'band':
        score = 100 if .05 <= value <= .10 else 100*value/.05 if value < .05 else 100*.10/value
    elif mapping in ('cv', 'cost_index'):
        score = 100 / (1 + value)
    else:
        return _empty('invalid', 'unknown_mapping')
    return {'score': score, 'coverage': 1., 'lower': score, 'upper': score,
            'observed_raw': value, 'status': 'scored', 'reason': None}


def relative_cost_score(native, plugin, *, compatible=True):
    if not compatible:
        return _empty(reason='incompatible_or_incomplete_pair_context')
    if native is None or plugin is None:
        return _empty(reason='missing_pair_cost')
    if not all(_number(v) and v >= 0 for v in (native, plugin)):
        return _empty('invalid', 'invalid_pair_cost')
    if native + plugin == 0:
        return _empty('not_applicable', 'both_costs_zero')
    score = 100 * native / (native + plugin)
    return {'score': score, 'coverage': 1., 'lower': score, 'upper': score,
            'observed_raw': plugin/native if native else None,
            'status': 'scored', 'reason': 'ratio_NA_zero_native_but_index_defined' if not native else None}


def _get(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _view(row):
    view = dict(row)
    behavior = row.get('behavior_metrics') or {}
    cases = {c['case_id']: c for c in behavior.get('cases', [])}
    view['business_checks'] = view['case_by_id'] = cases
    native = behavior.get('native_metrics') or behavior.get('original_metrics') or {}
    reward = row.get('native_reward')
    passed = native.get('passed', native.get('new_passed', native.get('total_passed')))
    total = native.get('total', native.get('new_total', native.get('total_tests')))
    partial, partial_status, partial_reason, partial_support = None, None, None, None
    if passed is None or total is None:
        partial_status, partial_reason = 'unknown', 'passed_or_total_count_missing'
    elif not _number(passed) or not _number(total) or passed < 0 or total < 0 or passed > total:
        partial = {'invalid_passed': passed, 'invalid_total': total}
        partial_status, partial_reason = 'invalid', 'invalid_passed_or_total_count'
    elif total == 0:
        partial_status, partial_reason = 'not_applicable', 'zero_test_denominator'
    else:
        partial, partial_support = passed/total, {'numerator': passed, 'denominator': total, 'unknown': 0}
    view['quality'] = {'binary': reward.get('reward') if isinstance(reward, dict) else reward,
                       'partial': partial, 'partial_status': partial_status,
                       'partial_reason': partial_reason, 'partial_support': partial_support}
    engineering = row.get('engineering_metrics') or {}
    ready, bad = engineering.get('request_ready'), engineering.get('unresolved_template_requests')
    template = None
    if _number(ready) and ready > 0 and _number(bad):
        template = 1-bad/ready
    view['derived'] = {'template_integrity': template}
    for name, ids in {
        'protected_constraints': ('wasm-protected-files', 'protected-files'),
        'process_validation': ('wasm-process-validation', 'public-validation'),
        'dependency_constraints': ('wasm-dependencies',),
    }.items():
        found = [cases[i] for i in ids if i in cases]
        view['derived'][name] = found[0] if len(found) == 1 else {
            'value': None, 'status': 'unknown', 'reason': 'no_preregistered_task_adapter_opportunity'}
    return view


def _support(row, spec):
    identity, path = spec['id'], spec['raw_source']
    explicit=(row.get('normalization_evidence')or{}).get(identity)
    if isinstance(explicit,dict)and all(k in explicit for k in ('numerator','denominator','unknown')):
        return {k:explicit[k]for k in ('numerator','denominator','unknown')}
    if identity == 'S3.partial_pass_rate':
        return _get(row, 'quality.partial_support')
    if identity.startswith('Q1.tool.') and identity.endswith('.error_rate'):
        tool = identity.split('.')[2]
        value = _get(row, 'engineering_metrics.tools.' + tool)
        if isinstance(value, dict):
            a, e, u = (value.get(k) for k in ('attempts', 'errors', 'unknown_results'))
            if all(_number(x) for x in (a, e, u)):
                return {'numerator': e, 'denominator': a-u, 'unknown': u}
    if identity.startswith('Q2.write.'):
        value = _get(row, path.rsplit('.', 1)[0])
        if isinstance(value, dict):
            a, s, u = (value.get(k) for k in ('attempts', 'successes', 'unknown'))
            if all(_number(x) for x in (a, s, u)):
                return {'numerator': s, 'denominator': a-u, 'unknown': u}
    if path.endswith('.value'):
        value = _get(row, path[:-6])
        if isinstance(value, dict) and all(k in value for k in ('numerator', 'denominator', 'unknown')):
            counts = {k: value[k] for k in ('numerator', 'denominator', 'unknown')}
            if all(v is not None for v in counts.values()):
                return counts
    return None


def normalize_trial_scores(row):
    view = _view(row)
    metrics = []
    invalid = str(row.get('execution_status', '')).startswith('invalid')
    for spec in catalogue()['metrics']:
        identity, path = spec['id'], spec['raw_source']
        raw = _get(view, path)
        parent = _get(view, path.rsplit('.', 1)[0]) if path.endswith('.value') else None
        explicit = (row.get('normalization_evidence') or {}).get(identity)
        if isinstance(explicit, dict):
            parent, raw = explicit, explicit.get('value')
        support = _support(view, spec)
        source_status = parent.get('status') if isinstance(parent, dict) else None
        reason = parent.get('reason') if isinstance(parent, dict) else None
        if identity == 'S3.partial_pass_rate':
            source_status, reason = _get(view, 'quality.partial_status'), _get(view, 'quality.partial_reason')
        if identity.startswith(('Q2.write.', 'Q1.tool.')):
            # Counts can still expose a useful interval when the original scalar is null.
            source_status = None
        if identity == 'Q7.uniformity_cv':
            uniformity = _get(view, 'state_metrics.uniformity') or {}
            gaps = uniformity.get('intervals')
            if uniformity.get('status') == 'insufficient_sample' or isinstance(gaps, list) and len(gaps) < 2:
                source_status = 'insufficient_sample'
            elif not isinstance(gaps, list):
                source_status, reason = 'unknown', 'internal_gap_sample_evidence_missing'
            elif not all(_number(g) and g >= 0 for g in gaps):
                source_status, reason = 'invalid', 'invalid_internal_gap_samples'
            elif sum(gaps) == 0:
                source_status, reason = 'insufficient_sample', 'zero_mean_internal_interval_CV_undefined'
            else:
                average = sum(gaps)/len(gaps)
                expected_cv = math.sqrt(sum((g-average)**2 for g in gaps)/len(gaps))/average
                if _number(raw) and not math.isclose(raw, expected_cv, rel_tol=1e-9, abs_tol=1e-12):
                    source_status, reason = 'invalid', 'CV_disagrees_with_population_gap_samples'
        if identity.startswith('Q7.') and _get(view, 'state_metrics.source_status') in ('invalid_session', 'invalid_evidence'):
            source_status = 'invalid'
        if identity.startswith('Q6.cache_'):
            key = 'input_cache_utilization' if identity.endswith('input_utilization') else 'all_tokens_cache_share'
            cm = _get(view, 'finance.cache_metrics.' + key)
            if isinstance(cm, dict):
                source_status, reason = cm.get('status'), cm.get('reason')
        if isinstance(explicit, dict) and all(k in explicit for k in ('numerator', 'denominator', 'unknown')):
            support = {k: explicit[k] for k in ('numerator', 'denominator', 'unknown')}
        if invalid:
            value = _empty('invalid', 'invalid_original_evidence_or_result')
        elif spec['applicability'] == 'plugin' and row.get('variant_id') == 'pi-native':
            value = _empty('not_applicable', 'native_profile_has_no_State_or_Task_tools')
        elif identity == 'Q6.paired_cost_ratio':
            pair = row.get('_normalization_cost_pair') or {}
            value = relative_cost_score(pair.get('native'), pair.get('plugin'), compatible=pair.get('compatible') is True)
        else:
            # A partial summary's counts define bounds; a coarse unknown flag cannot erase them.
            if support and source_status in ('partial', 'unknown') and support.get('denominator') is not None:
                source_status = None
            value = score_value(raw, spec['mapping'], support=support,
                                status=source_status, reason=reason)
        if raw is None and value['reason'] == 'required_evidence_missing':
            value['reason'] = spec.get('score_qualification') or 'required_original_evidence_or_gold_missing'
        if identity == 'Q7.fd_density' and _get(view, 'state_metrics.sample_status') == 'short_sample' and value['score'] is not None:
            value['reason'] = 'short_sample_strategy_score_not_long_term_behavior_evidence'
        source = row.get('_normalization_source') or {}
        ss = sf = su = sn = None
        if support and all(_number(support.get(k)) for k in ('numerator', 'denominator', 'unknown')):
            num, den, su = (support[k] for k in ('numerator', 'denominator', 'unknown'))
            ss, sf = (den-num, num) if spec['mapping'] == 'rate_lower' else (num, den-num)
            sn = den+su
        metrics.append({**deepcopy(spec), 'raw': _safe_raw(raw), **value,
                        'weight': spec['weights']['common_product'],
                        'support': _safe_raw(support), 'source': {'raw_path': path, **source},
                        'support_s': ss, 'support_f': sf, 'support_u': su, 'support_n': sn,
                        'source_hash': source.get('sha256'),
                        'evidence_ids': parent.get('evidence_ids', []) if isinstance(parent, dict) else []})
    by_id = {m['id']: m for m in metrics}
    profiles = {}
    for name, profile in catalogue()['profiles'].items():
        if name == 'plugin_memory' and row.get('variant_id') == 'pi-native':
            profiles[name] = {**_empty('not_applicable', 'structural_native_without_memory'),
                              'observed_score': None, 'classes': {}, 'planned_weight': 0.}
            continue
        profiles[name] = weighted_score(by_id, {m['id']: m['weights'][name] for m in metrics})
        profiles[name]['classes'] = {}
        for cls in ('engineering', 'behavior'):
            weights = {m['id']: m['weights'][name] for m in metrics if m['category'] == cls}
            item = weighted_score(by_id, weights)
            item['families'] = {family: weighted_score(by_id, detail['leaves'])
                                for family, detail in profile[cls].items()}
            profiles[name]['classes'][cls] = item
    return {'version': VERSION, 'metrics': metrics, 'profiles': profiles,
            'interpretation': 'Observed means are conditional; incomplete full-profile scores stay null. Cost/cache are auxiliary, not quality gains.'}


def weighted_score(metrics, weights):
    planned = sum(w for w in weights.values() if w > 0)
    if not planned:
        return {**_empty('not_applicable', 'empty_profile'), 'observed_score': None,
                'planned_weight': 0., 'known_weight': 0.}
    contribution = known = lower = upper = 0.
    for identity, weight in weights.items():
        if weight <= 0:
            continue
        m = metrics.get(identity) or _empty()
        coverage = m.get('coverage') or 0.
        known += weight * coverage
        if m.get('score') is not None:
            contribution += weight * coverage * m['score']
        lower += weight * m['lower']
        upper += weight * m['upper']
    coverage = known / planned
    complete = math.isclose(coverage, 1., abs_tol=1e-12)
    observed = contribution/known if known else None
    return {'score': observed if complete else None, 'observed_score': observed,
            'coverage': coverage, 'lower': lower/planned, 'upper': upper/planned,
            'planned_weight': planned, 'known_weight': known,
            'status': 'scored' if complete else 'provisional' if known else 'unknown',
            'reason': None if complete else 'fixed_profile_evidence_incomplete_no_weight_redistribution'}


def _macro(items):
    if not items:
        return {**_empty('not_applicable', 'no_eligible_tasks'), 'observed_score': None, 'task_count': 0}
    n = len(items)
    cov = sum(i['coverage'] for i in items)/n
    contribution = sum((i.get('observed_score') or 0)*i['coverage'] for i in items)/n
    observed = contribution/cov if cov else None
    return {'score': observed if math.isclose(cov, 1., abs_tol=1e-12) else None,
            'observed_score': observed, 'coverage': cov,
            'task_macro_observed_score': sum(i['observed_score'] for i in items)/n
            if all(i.get('observed_score') is not None for i in items) else None,
            'lower': sum(i['lower'] for i in items)/n, 'upper': sum(i['upper'] for i in items)/n,
            'task_count': n, 'status': 'scored' if math.isclose(cov, 1., abs_tol=1e-12) else 'provisional',
            'aggregation': 'full-profile contribution/coverage/bounds use equal task weights; observed_score is conditional supported-weight mean; task_macro_observed_score equally averages task conditional means'}


def attach_normalized_scores(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row.get('suite_id'), row['task_id'], row.get('repetition', 1))].append(row)
    pairs, costs, cost_contexts = [], [], set()
    for key, group in groups.items():
        a = [r for r in group if r['variant_id'] == 'pi-native']
        b = [r for r in group if r['variant_id'] == 'pi-memweave']
        if len(a) == len(b) == 1:
            a, b = a[0], b[0]
            ca, cb = a.get('finance_context') or {}, b.get('finance_context') or {}
            compatible = all(ca.get(k) is not None and ca.get(k) == cb.get(k) for k in ('model', 'price', 'currency'))
            compatible = compatible and a.get('actual_task_id', a['task_id']) == b.get('actual_task_id', b['task_id'])
            compatible = compatible and all(r.get('cost_pair_status') not in ('unknown', 'invalid') for r in (a, b))
            compatible = compatible and all(type((r.get('finance') or {}).get('unknown_charge_attempts')) is int
                and r['finance']['unknown_charge_attempts'] == 0 for r in (a, b))
            pair = {'native': a.get('finance_estimated_usd'), 'plugin': b.get('finance_estimated_usd'),
                    'compatible': compatible}
            if compatible and all(_number(pair[k]) and pair[k] >= 0 for k in ('native', 'plugin')):
                costs.append((pair['native'], pair['plugin']))
                cost_contexts.add(tuple(ca[k] for k in ('model', 'price', 'currency')))
            for row in (a, b):
                row['_normalization_cost_pair'] = pair
    for row in rows:
        row['normalized_scores'] = normalize_trial_scores(row)
        row.pop('_normalization_cost_pair', None)
        for name, item in row['normalized_scores']['profiles'].items():
            for key in ('score', 'observed_score', 'coverage', 'lower', 'upper', 'status'):
                row[f'normalized_{name}_{key}'] = item.get(key)
    for key, group in groups.items():
        a = [r for r in group if r['variant_id'] == 'pi-native']
        b = [r for r in group if r['variant_id'] == 'pi-memweave']
        if len(a) != 1 or len(b) != 1:
            pairs.append({'task_id': key[1], 'status': 'unknown', 'reason': 'missing_or_duplicate_arm'})
            continue
        if a[0].get('actual_task_id', a[0]['task_id']) != b[0].get('actual_task_id', b[0]['task_id']):
            pairs.append({'task_id': key[1], 'status': 'unknown', 'reason': 'different_actual_tasks_in_same_slot'})
            continue
        ca, cb = a[0].get('finance_context') or {}, b[0].get('finance_context') or {}
        if ca.get('model') is None or ca.get('model') != cb.get('model'):
            pairs.append({'task_id': key[1], 'status': 'unknown', 'reason': 'missing_or_different_paired_model_context'})
            continue
        am = {m['id']: m for m in a[0]['normalized_scores']['metrics']}
        bm = {m['id']: m for m in b[0]['normalized_scores']['metrics']}
        weights = {m['id']: m['weights']['common_product'] for m in am.values()}
        shared = {i: w*min(am[i]['coverage'], bm[i]['coverage']) for i, w in weights.items()}
        coverage = sum(shared.values())
        av = sum(w*am[i]['score'] for i, w in shared.items() if w and am[i]['score'] is not None)/coverage if coverage else None
        bv = sum(w*bm[i]['score'] for i, w in shared.items() if w and bm[i]['score'] is not None)/coverage if coverage else None
        pairs.append({'task_id': key[1], 'repetition': key[2], 'profile': 'common_product',
                      'shared_weight_coverage': coverage, 'native_shared_observed_score': av,
                      'plugin_shared_observed_score': bv,
                      'plugin_minus_native_shared': bv-av if coverage else None,
                      'status': 'scored' if math.isclose(coverage, 1., abs_tol=1e-12) else 'provisional',
                      'reason': 'same metric slots; only common supported weight; not matched individual tool calls'})
    variants = {}
    for variant in sorted({r['variant_id'] for r in rows}):
        variants[variant] = {}
        for profile in catalogue()['profiles']:
            if variant == 'pi-native' and profile == 'plugin_memory':
                variants[variant][profile] = {**_empty('not_applicable', 'structural_native_without_memory'),
                                               'observed_score': None, 'task_count': 0}
                continue
            tasks = defaultdict(list)
            for row in rows:
                if row['variant_id'] == variant:
                    tasks[row['task_id']].append(row['normalized_scores']['profiles'][profile])
            item = _macro([_macro(v) for v in tasks.values()])
            item['classes'] = {cls: _macro([_macro([r['normalized_scores']['profiles'][profile]['classes'][cls]
                         for r in rows if r['variant_id'] == variant and r['task_id'] == task])
                         for task in tasks]) for cls in ('engineering', 'behavior')}
            variants[variant][profile] = item
    from .finance_metrics import aggregate_cache
    cache = {variant: aggregate_cache(r.get('finance_usage') or {} for r in rows if r['variant_id'] == variant)
             for variant in sorted({r['variant_id'] for r in rows})}
    auxiliary = {'relative_cost_overall': relative_cost_score(
        sum(n for n, _ in costs), sum(p for _, p in costs),
        compatible=bool(groups) and len(costs) == len(groups) and len(cost_contexts) == 1),
        'cost_aggregation': 'sum_matched_native_and_plugin_costs_before_mapping; weight0',
        'cache_by_variant': {v: {k: {**m, 'score': 100*m['value'] if m.get('value') is not None else None}
            for k, m in data.items() if k in ('input_cache_utilization', 'all_tokens_cache_share')}
            for v, data in cache.items()}}
    return {'version': VERSION, 'profiles': deepcopy(catalogue()['profiles']),
            'by_variant': variants, 'pairs': pairs,
            'auxiliary_finance': auxiliary,
            'warnings': ['Missing evidence never redistributes fixed weights.',
                         'Compare only the same profile and common evidence scope.',
                         'Task quality, cache utilization and cost index remain separately visible.']}
