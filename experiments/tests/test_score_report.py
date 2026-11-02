import csv
import json
from pathlib import Path

import pytest

from memweave_eval.cli import main
from memweave_eval.score_report import generate_score_report
from memweave_eval.storage import file_digest


def test_immutable_offline_cli_and_each_row_explains_the_score(tmp_path, capsys):
    source = tmp_path/'original.json'
    source.write_text(json.dumps({'trials': [{'task_id': 't', 'variant_id': 'pi-native',
        'native_reward': {'reward': 1}, 'engineering_metrics': {'tools': {
            'bash': {'attempts': 5, 'errors': 1, 'unknown_results': 2, 'error_rate': None}}}}]}))
    original = file_digest(source)
    output = tmp_path/'new'
    assert main(['score-report', str(source), '--output', str(output)]) == 0
    assert file_digest(source) == original
    exported = json.loads((output/'normalized-scores.json').read_text())
    metric = next(m for m in exported['trials'][0]['metrics'] if m['id'] == 'Q1.tool.bash.error_rate')
    assert metric['score'] == pytest.approx(200/3)
    assert metric['support'] == {'numerator': 1, 'denominator': 3, 'unknown': 2}
    assert metric['lower'] == 40 and metric['upper'] == 80
    lines = list(csv.DictReader((output/'normalized-scores.csv').open()))
    assert len(lines) == 170
    assert all(r['meaning'] and r['raw_formula'] and r['score_formula'] and r['weight_basis'] and r['threshold_basis'] for r in lines)
    markdown = (output/'normalized-scores.md').read_text()
    assert '100*(1-x)' in markdown and '真实工具错误回执数' in markdown
    assert exported['trials'][0]['profiles']['common_product']['score'] is None
    with pytest.raises(ValueError, match='new independent'):
        generate_score_report(source, output)
    assert file_digest(source) == original
    capsys.readouterr()


def test_input_hash_and_protected_original_paths_are_rejected(tmp_path):
    raw = tmp_path/'run'/'reports'
    raw.mkdir(parents=True)
    original = raw/'results.json'
    original.write_text('{}')
    source = tmp_path/'bundle.json'
    source.write_text(json.dumps({'normalization_inputs': [{'path': str(original), 'sha256': 'wrong'}],
                                  'trials': [{'task_id': 'a', 'variant_id': 'pi-native'}]}))
    with pytest.raises(ValueError, match='hash mismatch'):
        generate_score_report(source, tmp_path/'out')
    assert not (tmp_path/'out').exists()
    source.write_text(json.dumps({'protected_roots': [str(raw.parent)],
                                  'trials': [{'task_id': 'a', 'variant_id': 'pi-native'}]}))
    with pytest.raises(ValueError, match='original reports'):
        generate_score_report(source, raw/'new')
    assert not (raw/'new').exists()


def test_registry_is_declarative_package_resource():
    import memweave_eval.normalized_scores as module
    path = Path(module.__file__).with_name('score_catalog.json')
    assert json.loads(path.read_text())['version'] == module.VERSION
