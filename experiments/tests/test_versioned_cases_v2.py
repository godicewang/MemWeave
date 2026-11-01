import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from memweave_eval.case_oracles import score_case_suite

ROOT = Path(__file__).parents[1]
GOLD = ROOT / 'cases/wasm-memory-task-v2.json'
DATA = ROOT / 'fixtures/wasm-memory-task-v2'


@pytest.mark.parametrize('variant,expected', [('positive', 1), ('negative', 0), ('missing', None)])
def test_distinct_cases_through_existing_cli(variant, expected):
    result = subprocess.run([sys.executable, '-m', 'memweave_eval.cli', 'score-cases',
                             str(GOLD), str(DATA / (variant + '.json'))],
                            env=os.environ.copy(), capture_output=True, text=True, check=True)
    scored = json.loads(result.stdout)
    assert len(scored['cases']) == 14
    assert all(c['value'] == expected for c in scored['cases']), scored['cases']


def test_case_definitions_have_distinct_checkpoints_and_oracles():
    gold = json.loads(GOLD.read_text())
    declarations = [json.dumps({k:v for k,v in case.items() if k not in ('id', 'purpose')},
                                sort_keys=True) for case in gold['cases']]
    assert len(set(declarations)) == len(gold['cases'])
    result = score_case_suite(gold, json.loads((DATA / 'negative.json').read_text()))
    cases = {c['case_id']: c for c in result['cases']}
    assert cases['T1-retrieval-ranking']['checks']['hit_at_k'] == 1
    assert cases['T1-retrieval-ranking']['checks']['best_top1'] == 0
    assert cases['T2-current-task-restore']['checks']['restore_end_to_end'] is False
    assert cases['T3-independent-goal-create']['checks']['create_recall'] is False
    assert cases['T4-ephemeral-interruption']['checks']['simple_no_create_and_complete'] is False


def test_retention_negative_controls_start_correct_and_have_later_dependency():
    gold = json.loads(GOLD.read_text())
    negative = score_case_suite(gold, json.loads((DATA/'negative.json').read_text()))
    observed = {case['case_id']:case for case in negative['cases']}
    for case in gold['cases']:
        if 'retention_preconditions' in case:
            checks = observed[case['id']]['checks']
            assert checks['pre_boundary_correct'] is True
            assert checks['write_before_cut'] is True
            assert checks['dependency_after_cut'] is True
    # These fail after a correct initial State, not because the setup was already wrong.
    assert observed['C1-transient-baseline']['checks']['baseline_retained'] is False
    assert observed['C4-three-window-checkpoints']['checks']['retained_at_cut_2'] is False
    network = json.loads((DATA/'negative.json').read_text())['C7-implicit-runtime-offline']
    assert all(event['sequence'] > network['last_eviction_seq'] for event in network['network_events']
               if event['phase'] == 'runtime')
