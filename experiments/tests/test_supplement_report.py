import hashlib
import json

import pytest

from memweave_eval.supplement_report import generate_supplement


def source(tmp_path):
    root = tmp_path/'run'
    agent = root/'harbor/job/trial/agent'
    (agent/'pi/sessions').mkdir(parents=True)
    (agent/'pi/sessions/s.jsonl').write_text('')
    (agent/'pi.txt').write_text('')
    (agent/'request-trace.jsonl').write_text('')
    (root/'reports').mkdir()
    (root/'experiment.lock.json').write_text(json.dumps({'experiment_commit':'frozen-v1'}))
    row = {'variant_id':'pi-native','task_id':'wasm-simd','success':True,'native_reward':{'reward':1},
           'session_sources':['harbor/job/trial/agent/pi/sessions/s.jsonl']}
    (root/'reports/results.json').write_text(json.dumps({'summary':{'complete':True},'trials':[row]}))
    records = [{'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (root/'harbor').rglob('*')if p.is_file()]
    (root/'evidence-index.json').write_text(json.dumps({'files':records}))
    return root


def test_v2_is_separate_immutable_and_keeps_v1_scores(tmp_path):
    root = source(tmp_path)
    before = {p:hashlib.sha256(p.read_bytes()).hexdigest()for p in root.rglob('*')if p.is_file()}
    output = tmp_path/'v2'
    result = generate_supplement(root, output)
    assert result['trials'][0]['original_outcome']['success'] is True
    assert result['provenance']['model_run_commit'] == 'frozen-v1'
    assert result['fixture_validation']['cases'] == 14
    assert result['fixture_validation']['all_expected_verdicts'] is True
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in before.items())
    assert (output/'metrics.json').exists() and (output/'report.md').exists()
    with pytest.raises(ValueError, match='existing'):
        generate_supplement(root, output)
    with pytest.raises(ValueError, match='original'):
        generate_supplement(root, root/'reports/new')


def test_v2_rejects_changed_original_before_creating_outputs(tmp_path):
    root = source(tmp_path)
    (root/'harbor/job/trial/agent/pi.txt').write_text('tampered')
    with pytest.raises(ValueError, match='hash'):
        generate_supplement(root, tmp_path/'out')
    assert not (tmp_path/'out').exists()
