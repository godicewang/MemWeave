from memweave_eval.long_qualification import qualify_attempt


def evidence(n=1000):
    return {'formal':True,'fixture':False,'collection_complete':True,'original_verifier_passed':True,
        'completed_actor_request_ids':[f'real-{i}'for i in range(n)],
        'actor_http_attempts':n,'tool_attempts':9000,'auxiliary_http_attempts':4}


def test_qualification_requires_a_single_successful_real_episode():
    assert qualify_attempt(evidence())['qualified']is True
    low=qualify_attempt(evidence(999))
    assert low['status']=='SUCCESS_BELOW_THRESHOLD'and low['task_success']is True
    assert low['qualified']is False
    for field,value in [('formal',False),('fixture',True),('collection_complete',False),
                        ('original_verifier_passed',False)]:
        row=evidence();row[field]=value
        assert qualify_attempt(row)['qualified']is False


def test_duplicates_tools_and_auxiliary_calls_never_fill_actor_threshold():
    row=evidence(999);row['completed_actor_request_ids']+=['real-0']
    result=qualify_attempt(row)
    assert result['qualified']is False and result['completed_unique_actor_calls']==999
    assert result['status']=='INVALID_COUNT_EVIDENCE'


def test_missing_and_invalid_fields_are_distinct_from_a_known_failure():
    row=evidence();row.pop('original_verifier_passed')
    assert qualify_attempt(row)['status']=='MISSING_EVIDENCE'
    row=evidence();row['original_verifier_passed']=0
    assert qualify_attempt(row)['status']=='INVALID_COUNT_EVIDENCE'
    row=evidence();row['actor_http_attempts']=999
    assert qualify_attempt(row)['status']=='INVALID_COUNT_EVIDENCE'
    row=evidence();row['completed_actor_request_ids']=None
    assert qualify_attempt(row)['status']=='MISSING_EVIDENCE'


def test_no_combination_of_short_attempts_can_create_a_qualified_attempt():
    assert not any(qualify_attempt(evidence(600))['qualified']for _ in range(2))


def test_table_preserves_five_not_run_cases_and_rejects_omission(tmp_path,monkeypatch):
    import json

    import pytest

    from memweave_eval import long_qualification as q
    design=tmp_path/'design.json';design.write_text('{}')
    monkeypatch.setattr(q,'read_design',lambda _: {'selection':{'cases':[
        {'pack_case_id':i,'upstream_case_id':'source/'+i,'source_revision':'pin'}for i in q.CASES],
        'historical_call_proofs':[]}})
    data={'version':q.VERSION,'reference_variant':'pi-native','model':'fixed','model_version':'v1',
        'cases':[{'case_id':i,'formal_runs':[]}for i in q.CASES]}
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(data));output=tmp_path/'table.json'
    result=q.qualification_table(design,manifest,output)
    assert result['qualified_distinct_cases']==0
    rows=json.loads(output.read_text())['cases']
    assert len(rows)==5 and all(r['status']=='NOT_RUN'for r in rows)
    data['cases'].pop();manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='five distinct'):
        q.qualification_table(design,manifest,tmp_path/'bad.json')
