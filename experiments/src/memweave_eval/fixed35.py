"""Fixed-package evaluator contracts; checkpoints, cases and families stay distinct."""
from __future__ import annotations

import math
import re
from collections import defaultdict

VERSION = 'fixed35-20261102-v1'


def validate_selection(selection, *, expected_count=35):
    cases = selection['cases']
    if len(cases) != expected_count:
        raise ValueError('fixed source case count mismatch')
    labels, sources = set(), set()
    for case in cases:
        label = case['pack_case_id']
        source = (case['benchmark'], case['upstream_case_id'], case['source_revision'])
        if label in labels or source in sources:
            raise ValueError('duplicate source case; overlays/checkpoints do not add cases')
        if not re.fullmatch(r'[a-f0-9]{40}', case['source_revision']):
            raise ValueError('unfixed source revision')
        labels.add(label)
        sources.add(source)
        if case['benchmark'] == 'MemoryAgentBench' and not all(k in case for k in
            ('data_revision', 'context_sha256', 'short_qa_id')):
            raise ValueError('MAB requires split/row/context hash/QA identity')
    return {'cases': len(cases), 'families': len({c['benchmark'] for c in cases})}


def checkpoint_verdict(contract, evidence):
    required = contract['required_assertions']
    if not required or len(set(required)) != len(required):
        raise ValueError('checkpoint requires nonempty unique assertion IDs')
    missing = [i for i in required if type(evidence.get(i)) is not bool]
    failed = [i for i in required if evidence.get(i) is False]
    score = 0 if failed else None if missing else 100
    return {'checkpoint_id': contract['id'], 'score': score,
            'status': 'SCORED' if score is not None else 'MISSING_EVIDENCE',
            'failed_assertions': failed, 'missing_assertions': missing,
            'collection_complete': not missing,
            'assertions': {i: {'value': evidence.get(i) if type(evidence.get(i)) is bool else None,
                               'status': 'fail' if i in failed else 'missing' if i in missing else 'pass'}
                           for i in required}}


def aggregate_metric(rows):
    groups = defaultdict(list)
    counts = {'valid_cases': 0, 'eligible_cases': 0, 'design_na': 0, 'missing': 0, 'excluded': 0, 'not_run': 0}
    identities = set()
    for row in rows:
        identity = (row['benchmark'], row['case_id'])
        if identity in identities:
            raise ValueError('aggregate checkpoints/replicates within case before family mean')
        identities.add(identity)
        status, score = row['status'], row.get('score')
        if status == 'DESIGN_NA':
            if not row.get('reason'):
                raise ValueError('design NA requires frozen reason')
            counts['design_na'] += 1
            continue
        counts['eligible_cases'] += 1
        if status == 'EXCLUDED_UNCOLLECTABLE':
            if not row.get('reason') or not row.get('repair_attempts'):
                raise ValueError('uncollectable exception requires reason and attempted repairs')
            counts['excluded'] += 1
        elif status == 'NOT_RUN':
            counts['not_run'] += 1
        elif status != 'SCORED' or score is None:
            counts['missing'] += 1
        else:
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100:
                raise ValueError('invalid normalized score')
            counts['valid_cases'] += 1
            groups[row['benchmark']].append(score)
            if row.get('collection_complete') is False:
                counts['missing'] += 1
    benchmarks = {name: {'score': sum(values)/len(values), 'valid_cases': len(values)}
                  for name, values in sorted(groups.items())}
    return {'score': sum(b['score'] for b in benchmarks.values())/len(benchmarks) if benchmarks else None,
            'benchmarks': benchmarks, **counts,
            'collection_accepted': counts['missing'] == counts['excluded'] == counts['not_run'] == 0,
            'aggregation': 'equal_cases_within_benchmark_then_equal_available_benchmarks',
            'version': VERSION}


def paired_effective_rows(rows):
    groups = defaultdict(dict)
    for row in rows:
        key = (row['case_id'], row['metric_id'])
        if row['arm'] in groups[key]:
            raise ValueError('ambiguous repeated arm')
        groups[key][row['arm']] = row
    paired = {'pi-native': [], 'pi-memweave': [], 'excluded_pairs': []}
    for key, arms in sorted(groups.items()):
        if set(arms) == {'pi-native', 'pi-memweave'} and all(r['status'] == 'SCORED' and r.get('score') is not None for r in arms.values()):
            for arm, row in arms.items():
                paired[arm].append(row)
        else:
            paired['excluded_pairs'].append(key)
    return paired
