import json

import pytest

from memweave_eval.fixed35_switch import grade_switch_final


@pytest.fixture
def contract():
    return {'case_id':'INT-06','response_task_id':'logical-source-id','f2p':['canonical','invalid-type'],
        'p2p':['valid-bytes'],'protected_paths':['tests/test_source.py'],'scope':'Final delivery only; not memory'}


def answer(**updates):
    return json.dumps({'task_id':'logical-source-id','analysis':'Source constraint implemented.',
        'patch':'diff --git a/django/db/models/fields/__init__.py b/django/db/models/fields/__init__.py\n'
        '--- a/django/db/models/fields/__init__.py\n+++ b/django/db/models/fields/__init__.py\n@@ -1 +1 @@\n-old\n+new\n',**updates})


def grade(contract,**updates):
    return grade_switch_final(contract,**{'answer':answer(),'outcomes':{'canonical':'pass','invalid-type':'pass','valid-bytes':'pass'},
        'original_result':{'status':'graded'},**updates})


def test_final_delivery_and_business_are_separate_and_and_checkpoints(contract):
    result=grade(contract)
    assert [p['score']for p in result['checkpoints']]==[100,100]
    assert result['memory_adoption_score']is None and result['runtime_memweave_task_ids']is None
    failed=grade(contract,outcomes={'canonical':'pass','invalid-type':'fail','valid-bytes':'pass'})
    assert [p['score']for p in failed['checkpoints']]==[100,0]
    assert failed['collection_complete']


@pytest.mark.parametrize('field', ['answer','outcomes','original_result'])
def test_absent_evidence_never_passes(contract,field):
    result=grade(contract,**{field:None})
    assert not result['collection_complete']
    assert any(p['score']is None for p in result['checkpoints'])


def test_missing_single_original_test_is_unknown_but_known_failure_remains_zero(contract):
    result=grade(contract,outcomes={'canonical':'pass','valid-bytes':'pass'})
    assert result['checkpoints'][1]['score']is None
    result=grade(contract,outcomes={'canonical':'fail'})
    assert result['checkpoints'][1]['score']==0 and not result['collection_complete']
    assert grade(contract,original_result={'status':'error'})['checkpoints'][1]['score']is None


@pytest.mark.parametrize('updates',[{'task_id':'runtime-memweave-id'},{'analysis':''},{'patch':'no patch'},
    {'patch':'diff --git a/tests/test_source.py b/tests/test_source.py\n@@ -1 +1 @@\n-a\n+b\n'},
    {'patch':'diff --git a/../bad b/../bad\n@@ -1 +1 @@\n-a\n+b\n'}])
def test_delivery_negative_variants_are_zero_without_changing_business(contract,updates):
    assert [p['score']for p in grade(contract,answer=answer(**updates))['checkpoints']]==[0,100]


def test_empty_or_malformed_answer_is_observed_failure_not_missing(contract):
    assert grade(contract,answer='')['checkpoints'][0]['score']==0
    assert grade(contract,answer='```json\n{}\n```')['checkpoints'][0]['score']==0


def test_bad_test_status_is_missing_instead_of_infrastructure_crash(contract):
    assert grade(contract,outcomes={'canonical':[],'invalid-type':'pass','valid-bytes':'pass'})['checkpoints'][1]['score']is None


@pytest.mark.parametrize('text',[
    '{"task_id":"logical-source-id","task_id":"logical-source-id","analysis":"a","patch":"p"}',
    '{"task_id":"logical-source-id","analysis":NaN,"patch":"p"}'])
def test_strict_delivery_rejects_duplicate_keys_and_nonfinite_json(contract,text):
    assert grade(contract,answer=text)['checkpoints'][0]['score']==0


def test_existing_cli_preserves_missing_checkpoint_and_provenance(tmp_path,contract):
    from types import SimpleNamespace

    from memweave_eval.fixed35_cli import execute
    path=tmp_path/'contract.json';path.write_text(json.dumps(contract))
    output=tmp_path/'result.json'
    result=execute(SimpleNamespace(fixed35_command='switch-final',contract=path,answer=None,
        outcomes=None,original_result=None,output=output))
    assert result['paid_requests']==0 and not result['collection_complete']
    data=json.loads(output.read_text())
    assert [p['score']for p in data['checkpoints']]==[None,None]
    assert set(data['source_sha256'])=={'contract'}
