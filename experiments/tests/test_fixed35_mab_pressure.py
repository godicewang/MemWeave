import json
from pathlib import Path

import pytest

from memweave_eval.fixed35_mab import eviction_eligible, grade_three_evictions
from memweave_eval.fixed35_mab_pressure import SUPPORT, bind_support, derive_pressure_task


def test_all_current_multihop_support_is_required_and_bound_uniquely(tmp_path):
    for i,needle in enumerate(SUPPORT['MAB-02'],1):
        p=tmp_path/'steps'/f'ingest-{i:04d}'/'instruction.md';p.parent.mkdir(parents=True)
        p.write_text(needle)
    bound=bind_support(tmp_path,SUPPORT['MAB-02'])
    assert max(p['stage_id']for p in bound)==2
    Path(bound[0]['path']).write_text('no source')
    with pytest.raises(ValueError):bind_support(tmp_path,SUPPORT['MAB-02'])


def test_eligible_evictions_start_after_current_source_not_first_unrelated_cut():
    def eligible(**extra):return eviction_eligible(protocol='eligible-after-current-source-v3',
        **dict({'stage':8,'valid_after':7,'source_seen':True,'source_visible':False},**extra))
    assert eligible()
    assert not eligible(stage=2)
    assert not eligible(source_seen=False)
    assert not eligible(source_visible=True)
    # Eligibility never depends on retained=True; a middle loss must still fail.
    points=[{'boundary_id':str(i),'original_source_absent':True,
        'current_facts_retained':i!=1,'delivered_version_correct':True}for i in range(3)]
    assert grade_three_evictions(points,observation_complete=True)['score']==0
    assert grade_three_evictions([points[0],points[2]],observation_complete=True)['score']is None
    assert eviction_eligible(protocol=None,stage=1,valid_after=40,source_seen=False,source_visible=True)


def test_pressure_copy_keeps_original_query_and_environment_gold_stays_outside_actor(tmp_path):
    source=tmp_path/'original';(source/'steps/query').mkdir(parents=True)
    (source/'steps/query/instruction.md').write_text('Original question, no gold.')
    (source/'environment').mkdir();(source/'environment/Dockerfile').write_text('FROM original')
    (source/'task.toml').write_text('[agent]\ntimeout_sec=1800\n[[steps]]\nname="query"\n')
    result=derive_pressure_task(source,'MAB-02',SUPPORT['MAB-02']+['Natural next source.']*4,
        ['private target'],{'context_sha256':'a'*64},tmp_path/'output')
    task=Path(result['task_path']);contract=json.loads(Path(result['contract_path']).read_text())
    assert (task/'steps/query/instruction.md').read_bytes()==(source/'steps/query/instruction.md').read_bytes()
    assert (task/'environment/Dockerfile').read_bytes()==(source/'environment/Dockerfile').read_bytes()
    assert contract['literal_valid_after_stage']==2
    assert contract['task_config']['memory_config']=={'recent_turns':2,'evict_turns':1}
    assert 'private target'not in '\n'.join(p.read_text()for p in task.rglob('*')if p.is_file())
    assert result['three_post_source_boundaries_not_yet_observed']
    with pytest.raises(FileExistsError):derive_pressure_task(source,'MAB-02',SUPPORT['MAB-02'],
        ['private target'],{},tmp_path/'output')
