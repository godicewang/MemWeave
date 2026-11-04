import tomllib

import pytest


def test_mab_time_policy_is_explicit_and_preserves_all_public_material(tmp_path):
    from memweave_eval.fixed35_execution import source_stage_budgets
    from memweave_eval.fixed35_mab_time import derive_mab_time_policy
    source=tmp_path/'old/MAB-01';(source/'steps/ingest-0001').mkdir(parents=True);(source/'steps/query').mkdir()
    (source/'steps/ingest-0001/instruction.md').write_text('Original history')
    (source/'steps/query/instruction.md').write_text('Original query')
    (source/'task.toml').write_text('[metadata]\nderived_adapter="fixed35-mab-pressure-20261103-v2"\n[agent]\ntimeout_sec=1800\n[[steps]]\nname="ingest-0001"\n[[steps]]\nname="query"\n')
    result=derive_mab_time_policy(source,tmp_path/'new/MAB-01')
    assert result['old_stage_upper_bounds']==[1800,1800]
    assert result['new_stage_upper_bounds']==[300,600]and result['source_content_unchanged']
    assert source_stage_budgets(tmp_path/'new/MAB-01')==[300,600]
    assert (source/'steps/query/instruction.md').read_bytes()==(tmp_path/'new/MAB-01/steps/query/instruction.md').read_bytes()
    assert tomllib.loads((source/'task.toml').read_text())['agent']['timeout_sec']==1800
    with pytest.raises(ValueError):derive_mab_time_policy(source,tmp_path/'other',ingest_seconds=True)


def test_time_policy_cannot_silently_shorten_source_coding_tasks(tmp_path):
    from memweave_eval.fixed35_mab_time import derive_mab_time_policy
    source=tmp_path/'TB-10';source.mkdir();(source/'task.toml').write_text('[agent]\ntimeout_sec=28800\n')
    with pytest.raises(ValueError):derive_mab_time_policy(source,tmp_path/'new')
