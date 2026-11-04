from memweave_eval.fixed35_sources import applicability_matrix


def design():
    return {'selection': {'cases': [
        {'pack_case_id': 'a', 'upstream_case_id': 'source/a', 'benchmark': 'B'},
        {'pack_case_id': 'b', 'upstream_case_id': 'source/b', 'benchmark': 'B'}]},
        'coverage_plan': {'opportunities': [
            {'id': 'native_outcome', 'proposed_case_ids': ['source/a']},
            {'id': 'C1', 'proposed_case_ids': ['source/a']}],
            'metrics': [
                {'metric_id': 'S3.original_reward', 'opportunity_ids': ['native_outcome'], 'disposition': 'reused'},
                {'metric_id': 'S1.retention', 'opportunity_ids': ['C1'], 'disposition': 'reused'},
                {'metric_id': 'S.case.wasm-protected-files', 'opportunity_ids': ['C1'],
                 'disposition': 'legacy_task_specific_NA'}]}}


def test_research_suggestions_do_not_define_negative_applicability():
    rows = applicability_matrix(design())
    lookup = {(r['case_id'], r['metric_id']): r for r in rows}
    assert lookup['a', 'S1.retention']['design_status'] == 'PLANNED'
    unresolved = lookup['b', 'S1.retention']
    assert unresolved['design_status'] == 'DESIGN_UNRESOLVED'
    assert unresolved['opportunity_ids'] == []
    assert 'not evidence of structural inapplicability' in unresolved['reason']
    for case in ('a', 'b'):
        assert lookup[case, 'S3.original_reward']['design_status'] == 'PLANNED'
        assert lookup[case, 'S3.original_reward']['opportunity_ids'] == ['native_outcome']
        assert lookup[case, 'S.case.wasm-protected-files']['design_status'] == 'DESIGN_NA'
    assert all(r['implementation_status'] == 'NOT_ACCEPTED' for r in rows)


def test_mab_compound_selector_is_matched_without_short_qa_alias():
    d = design()
    d['selection']['cases'] = [{'pack_case_id': 'MAB-01', 'upstream_case_id': 'split/row=1/context_sha256=x/qa_pair_id=q',
                                'benchmark': 'MemoryAgentBench'}]
    d['coverage_plan']['opportunities'][1]['proposed_case_ids'] = ['MemoryAgentBench/' + d['selection']['cases'][0]['upstream_case_id']]
    assert next(r for r in applicability_matrix(d) if r['metric_id'] == 'S1.retention')['design_status'] == 'PLANNED'


def test_protocol_telemetry_applies_to_all_cases_without_claiming_tool_attempts():
    d=design()
    d['coverage_plan']['opportunities'].append({'id':'tool_execution','proposed_case_ids':[]})
    d['coverage_plan']['metrics'].append({'metric_id':'Q1.tool.bash.attempts','opportunity_ids':['tool_execution'],
        'disposition':'diagnostic_not_intrinsic_score','score_mapping_preserved':'diagnostic'})
    rows=[r for r in applicability_matrix(d)if r['metric_id']=='Q1.tool.bash.attempts']
    assert len(rows)==2 and all(r['design_status']=='PLANNED'for r in rows)
    assert all(r['measurement_role']=='raw_diagnostic'and r['assignment_basis']=='protocol_wide_telemetry'for r in rows)
    assert all(r['implementation_status']=='NOT_ACCEPTED'for r in rows)


def test_source_draft_is_explicitly_not_an_admission_and_hashes_are_frozen(tmp_path):
    import json

    from memweave_eval.fixed35_sources import freeze_draft_contracts
    from memweave_eval.storage import file_digest
    d=design()
    source={'cases':[dict(c,source_revision='a'*40)for c in d['selection']['cases']], 'design_sha256':'b'*64}
    manifest=freeze_draft_contracts(source,applicability_matrix(d),tmp_path)
    frozen=json.loads(manifest.read_text())
    assert frozen['admission_status']=='NOT_ADMITTED'and len(frozen['cases'])==2
    for case in frozen['cases']:
        from pathlib import Path
        path=Path(case['contract_path']);contract=json.loads(path.read_text())
        assert case['contract_sha256']==file_digest(path)
        assert contract['contract_status']=='DRAFT_NOT_ADMITTED'
        assert len(contract['metric_matrix'])==3


def test_admission_rejects_drafts_unresolved_and_obsolete_false_na_matrices():
    import pytest

    from memweave_eval.fixed35_campaign import validate_case_design
    from memweave_eval.normalized_scores import catalogue
    good={'metric_matrix':[{'metric_id':m['id'],'design_status':'PLANNED','opportunity_ids':['frozen-unit-source'],
        'applicability_version':'fixed35-research-assignments-20261102-v2'}for m in catalogue()['metrics']]}
    validate_case_design(good)
    for bad in ({'metric_matrix':[]},dict(good,contract_status='DRAFT_NOT_ADMITTED'),
        {'metric_matrix':[dict(good['metric_matrix'][0],design_status='DESIGN_UNRESOLVED')]},
        {'metric_matrix':[dict(good['metric_matrix'][0],design_status='DESIGN_NA')]},
        {'metric_matrix':[{'metric_id':'m','design_status':'DESIGN_NA','reason':'No assigned opportunity in approved design'}]}):
        with pytest.raises(ValueError):validate_case_design(bad)


def test_admission_requires_the_whole_registry_and_rejects_fixtures():
    import pytest

    from memweave_eval.fixed35_campaign import validate_case_design
    from memweave_eval.normalized_scores import catalogue
    good={'metric_matrix':[{'metric_id':m['id'],'design_status':'PLANNED','opportunity_ids':['unit-source'],
        'applicability_version':'fixed35-research-assignments-20261102-v2'}for m in catalogue()['metrics']]}
    for change in [{'metric_matrix':good['metric_matrix'][:-1]},{'fixture_only':True},{'fixture_only':'false'},
        {'metric_matrix':[dict(m,opportunity_ids=[])for m in good['metric_matrix']]},
        {'metric_matrix':[dict(m,opportunity_ids=['same','same'])for m in good['metric_matrix']]}]:
        with pytest.raises(ValueError):validate_case_design(dict(good,**change))
