import json

import pytest

from memweave_eval.storage import file_digest


def scope(tmp_path):
    from memweave_eval.normalized_scores import catalogue
    source=tmp_path/'public-instruction.md';source.write_text('Original history and final query; no task switch or fault injection.')
    gold=tmp_path/'gold.json';gold.write_text('{"expected":"fixed"}')
    data={'version':'fixed35-authored-applicability-20261104-v3','case_id':'MAB-01','benchmark':'MemoryAgentBench',
        'protocol_inputs':[{'path':str(source),'sha256':file_digest(source)}],
        'decisions':[{'metric_id':m['id'],'design_status':'DESIGN_NA','designed_trigger':False,
            'absence_basis':'no_designed_event','reason':'This frozen history/query protocol contains no corresponding designed event',
            'opportunity_ids':[]}for m in catalogue()['metrics']]}
    data['decisions'][0].update(design_status='PLANNED',designed_trigger=True,opportunity_ids=['actual-tool-call'],
        gold={'path':str(gold),'sha256':file_digest(gold)},evidence_fields=['call_id','actual_result'])
    path=tmp_path/'scope.json';path.write_text(json.dumps(data));return path,data,source,gold


def test_explicit_scope_can_close_a_case_without_all_pack_capabilities(tmp_path):
    from memweave_eval.fixed35_campaign import validate_case_design
    from memweave_eval.fixed35_scope import compile_scope
    p,_d,_,_=scope(tmp_path);matrix=compile_scope(p)
    assert len(matrix)==170 and matrix[0]['design_status']=='PLANNED'
    assert matrix[1]['design_status']=='DESIGN_NA'
    contract={'case_id':'MAB-01','metric_matrix':matrix,
        'applicability_scope':{'path':str(p),'sha256':file_digest(p)}}
    validate_case_design(contract)
    contract['metric_matrix'][0].update(design_status='DESIGN_NA',reason='silently removed')
    with pytest.raises(ValueError):validate_case_design(contract)


@pytest.mark.parametrize('mode',['omit','duplicate','designed-as-na','missing-reason','missing-basis','no-evidence','source-changed','gold-changed'])
def test_absence_is_not_a_default_and_missing_designed_evidence_cannot_be_na(tmp_path,mode):
    from memweave_eval.fixed35_scope import compile_scope
    p,d,source,gold=scope(tmp_path)
    if mode=='omit':d['decisions'].pop()
    elif mode=='duplicate':d['decisions'][-1]=d['decisions'][0]
    elif mode=='designed-as-na':d['decisions'][1]['designed_trigger']=True
    elif mode=='missing-reason':d['decisions'][1]['reason']=''
    elif mode=='missing-basis':d['decisions'][1].pop('absence_basis')
    elif mode=='no-evidence':d['decisions'][0]['evidence_fields']=[]
    elif mode=='source-changed':source.write_text('Now includes a switch')
    else:gold.write_text('{"expected":"different"}')
    p.write_text(json.dumps(d))
    with pytest.raises((ValueError,TypeError)):compile_scope(p)


def test_unreviewed_stays_unresolved_and_cannot_be_admitted(tmp_path):
    from memweave_eval.fixed35_campaign import validate_case_design
    from memweave_eval.fixed35_scope import compile_scope
    p,d,_,_=scope(tmp_path);d['decisions'][1].update(design_status='DESIGN_UNRESOLVED',designed_trigger=None,
        reason='Case-specific gold and applicability not yet reviewed');p.write_text(json.dumps(d))
    rows=compile_scope(p);assert rows[1]['design_status']=='DESIGN_UNRESOLVED'
    with pytest.raises(ValueError):validate_case_design({'case_id':'MAB-01','metric_matrix':rows,
        'applicability_scope':{'path':str(p),'sha256':file_digest(p)}})
