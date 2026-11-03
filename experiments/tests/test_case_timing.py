import pytest

from memweave_eval.case_timing import actor_deadline


def test_multistage_keeps_each_stage_original_allowance_and_shared_total_deadline():
    assert actor_deadline(5000,1000,1200,1000,1,[900,300])==1900
    assert actor_deadline(5000,1000,1200,1500,2,[900,300])==1800
    assert actor_deadline(5000,1000,1200,2100,2,[900,300])==2400
    assert actor_deadline(1750,1000,1200,1500,2,[900,300])==1750
    assert actor_deadline(5000,1000,1200,1500,2,[])==2200


@pytest.mark.parametrize('stages,index', [([900,300],0),([900,300],3),([900,300],True),
    ([900,-300],1),([900,float('nan')],1),([300,300],1)])
def test_invalid_stage_contract_cannot_silently_extend_or_collapse_budget(stages,index):
    with pytest.raises(ValueError):actor_deadline(5000,1000,1200,1500,index,stages)
