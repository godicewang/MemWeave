import pytest

from memweave_eval.capability_coverage import capability_coverage, long_qualification_proof


def row(identity,*,status='SCORED',score=0,complete=True):
    return {'case_id':'a','arm':'pi-memweave','metric_id':identity,'status':status,
        'score':score,'raw':0,'collection_complete':complete}


def test_known_zero_covers_its_group_but_does_not_prove_success_or_other_categories():
    result=capability_coverage([row('F35.C4-three-window-checkpoints'),row('S1.retention')])
    assert result['observed_group_count']==2
    assert result['groups']['C4']['observed_cases']==['a']
    assert 'C5'in result['unobserved_groups']and result['complete']is False


def test_na_zero_opportunity_missing_and_native_only_never_fill_plugin_capability_coverage():
    rows=[row('F35.C1-transient-baseline',status=s,score=None)for s in
        ['DESIGN_NA','CONDITIONAL_NO_OPPORTUNITY','MISSING_EVIDENCE','NOT_RUN']]
    rows.append(row('F35.C2-exception',complete=False))
    rows.append(dict(row('F35.C3-before-dependent-edit'),arm='pi-native'))
    assert capability_coverage(rows)['observed_group_count']==0


def test_delivery_does_not_claim_reference_or_window_fidelity_and_alias_rows_do_not_inflate_groups():
    result=capability_coverage([row('Q4_8.state_latest_at_prepare'),row('Q1.tool.bash.error_rate'),
        row('Q1.tool.read.error_rate'),row('Q1.tool.write.error_rate')])
    assert result['observed_group_count']==2 and 'Q4'in result['unobserved_groups']
    assert long_qualification_proof(None)['qualified_cases']is None


def test_unbound_or_fabricated_long_qualification_is_not_accepted(tmp_path):
    import json

    from memweave_eval.long_qualification import CASES, VERSION
    from memweave_eval.storage import file_digest
    p=tmp_path/'long.json';data={'version':VERSION,'reference_variant':'pi-native','model':'fixed','model_version':'v1',
        'cases':[{'case_id':i,'formal_attempts':[],'qualified':False}for i in CASES]}
    p.write_text(json.dumps(data));proof={'path':str(p),'sha256':file_digest(p)}
    assert long_qualification_proof(proof)['qualified_cases']==0
    data['cases'][0]['qualified']=True;p.write_text(json.dumps(data));proof['sha256']=file_digest(p)
    with pytest.raises(ValueError,match='qualified'):long_qualification_proof(proof)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,101,True])
def test_invalid_scores_do_not_supply_capability_evidence(value):
    with pytest.raises(ValueError,match='invalid score'):
        capability_coverage([row('S1.retention',score=value)])


def test_long_qualified_flags_are_replayed_from_actual_attempt_evidence(tmp_path,monkeypatch):
    import json

    from memweave_eval import capability_coverage as c
    from memweave_eval.long_qualification import CASES, VERSION
    from memweave_eval.storage import file_digest
    attempt={'run_root':'/formal','qualified':True,'completed_unique_actor_calls':1000}
    monkeypatch.setattr(c,'_formal_attempt',lambda *args:dict(attempt))
    data={'version':VERSION,'reference_variant':'pi-native','model':'fixed','model_version':'v1',
        'cases':[{'case_id':i,'formal_attempts':[attempt]if i==CASES[0]else[],
            'qualified':i==CASES[0]}for i in CASES]}
    path=tmp_path/'proof.json';path.write_text(json.dumps(data));proof={'path':str(path),'sha256':file_digest(path)}
    assert c.long_qualification_proof(proof)['qualified_cases']==1
    attempt['completed_unique_actor_calls']=999
    with pytest.raises(ValueError,match='differs'):c.long_qualification_proof(proof)
