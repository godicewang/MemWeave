"""Name measured MAB predicates accurately; components do not inherit old credit."""
from __future__ import annotations

VERSION='fixed35-mab-rubric-audit-20261104-v1'


def measured_components(behavior,*,arm):
    memory=behavior.get('memory')or{}
    selected=[('answer_schema_artifact','Correct source answer AND exact one-value JSON schema AND actual answer-file value',behavior.get('derived_action'),'all'),
        ('source_retention_action_consistency','Finite source relation/card, pre-action preservation and actual dependent answer; no same-window baseline/negative-control comparison',behavior.get('typed_book_memory')or memory.get('current_validity_before_action')or memory.get('correction'),'plugin')]
    rows=[]
    for name,meaning,point,scope in selected:
        native=scope=='plugin'and arm=='pi-native';point=point or{};score=point.get('score')
        rows.append({'id':'F35.MAB.'+name,'meaning':meaning,'applicability':scope,
            'raw':score/100 if type(score)in (int,float)and not native else None,'score':None if native else score,
            'raw_formula':'AND of this source-bound component\u2019s independent registered predicates; see original evidence',
            'score_formula':'100 * binary component outcome','unit':'binary checkpoint',
            'status':'DESIGN_NA'if native else point.get('status','MISSING_EVIDENCE'),
            'mapping_version':VERSION,'weights':{'common_product':0,'plugin_memory':0},
            'weight_reason':'Diagnostic successor component; no inherited protected-file or causal-baseline weight',
            'collection_complete':True if native else point.get('collection_complete')is True,
            'support_s':int(not native and score==100),'support_f':int(not native and score==0),
            'support_u':int(not native and score is None),'support_n':0 if native else 1,
            'assertions':point.get('assertions',{})})
    return rows


def reject_mismatched_slot(item,identity):
    if identity not in {'S.common.protected_constraints','S.case_v2.C1-transient-baseline'}or item.get('status')=='DESIGN_NA':return
    reason=('The MAB predicate measured answer/schema/artifact validity; no protected-file invariant was designed'
        if identity=='S.common.protected_constraints'else
        'The MAB predicate measured source retention/action consistency; a same-window baseline and negative control were not executed')
    item.update(observed_unaccepted_score=item.get('score'),score=None,status='RUBRIC_DEFINITION_MISMATCH',
        collection_status='REPAIR_REQUIRED',repair_kind='evaluator_design',reason=reason,
        rubric_audit_version=VERSION,
        repair_requirement='Freeze a corrected applicability/metric contract. Missing baseline interventions require a fair new experiment; existing content cannot fabricate them.')
