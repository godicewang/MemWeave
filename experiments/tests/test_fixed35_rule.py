import pytest

from memweave_eval.fixed35_rule import CLOSE, OPEN, rendered_rule, rule_checkpoint

TEMPLATE='Remember the exact constraint. Capacity {{count}}.\nNever discard the exception.\n'
VARIABLES={'count':100}


def payload(body=None):
    return {'messages':[{'role':'system','content':'native\n'+OPEN+'\n'+
        (rendered_rule(TEMPLATE,VARIABLES)if body is None else body)+'\n'+CLOSE},
        {'role':'user','content':'work'}]}


def test_independent_template_exact_body_and_position_all_required():
    assert all(rule_checkpoint(payload(),TEMPLATE,VARIABLES,observed_template=TEMPLATE).values())
    for body in [rendered_rule(TEMPLATE,{'count':200}),rendered_rule(TEMPLATE,VARIABLES).replace('Never','May'),
                 TEMPLATE,'',rendered_rule(TEMPLATE,VARIABLES)+CLOSE+OPEN]:
        assert False in rule_checkpoint(payload(body),TEMPLATE,VARIABLES,observed_template=TEMPLATE).values()
    p=payload();p['messages'].reverse()
    assert rule_checkpoint(p,TEMPLATE,VARIABLES,observed_template=TEMPLATE)['system_before_history'] is False


def test_missing_rule_is_failure_but_missing_observation_is_unknown():
    assert rule_checkpoint({'messages':[]},TEMPLATE,VARIABLES,observed_template=TEMPLATE)['one_complete_rule'] is False
    assert set(rule_checkpoint(None,TEMPLATE,VARIABLES,observed_template=None).values())=={None}
    assert rule_checkpoint(payload(),TEMPLATE,VARIABLES,observed_template=None)['source_template_matches'] is None
    assert rule_checkpoint(payload(),TEMPLATE,VARIABLES,observed_template=TEMPLATE+'x')['source_template_matches'] is False


def test_literal_user_system_append_is_not_a_rule_placeholder():
    p=payload();p['messages'][0]['content']='User template example: {{count}}\n'+p['messages'][0]['content']
    assert all(rule_checkpoint(p,TEMPLATE,VARIABLES,observed_template=TEMPLATE).values())


@pytest.mark.parametrize('template,variables',[(TEMPLATE,{}),(TEMPLATE,{'count':False}),
    (TEMPLATE,{'count':0}),(TEMPLATE,{'count':100,'extra':1}),('expression {{count+1}}',{}),('',{})])
def test_incomplete_or_expression_gold_is_not_a_valid_rule_oracle(template,variables):
    with pytest.raises(ValueError):rendered_rule(template,variables)
