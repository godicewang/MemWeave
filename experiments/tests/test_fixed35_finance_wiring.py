import json

import pytest

from memweave_eval.finance_metrics import cache_metrics
from memweave_eval.fixed35_report import single_report
from memweave_eval.normalized_scores import catalogue
from memweave_eval.storage import file_digest


@pytest.mark.parametrize('reverse',[False,True])
def test_episode_finance_raw_fields_are_wired_and_arm_order_cannot_swap_costs(tmp_path,reverse):
    wanted={'Q6.input_tokens','Q6.cache_tokens','Q6.output_tokens','Q6.estimated_usd','Q6.cache_input_utilization','Q6.cache_all_tokens_share','Q6.paired_cost_ratio'}
    contract=tmp_path/'contract.json';contract.write_text(json.dumps({'version':'unit-finance','metric_matrix':[
        {'metric_id':m['id'],'design_status':'PLANNED'if m['id']in wanted else'DESIGN_NA',
         'reason':'Unit scope only','opportunity_ids':['unit']}for m in catalogue()['metrics']]}))
    (tmp_path/'admission.json').write_text(json.dumps({'case_id':'unit','benchmark':'unit','family':'unit',
        'contract_path':str(contract),'contract_sha256':file_digest(contract)}))
    arms=[]
    for arm,cost in [('pi-native',.2),('pi-memweave',.1)]:
        usage={'input_tokens':100,'cache_tokens':0,'output_tokens':20}
        collection={'state_metrics':{},'tools':{},'cache':cache_metrics(usage),'usage':usage,
            'estimated_usd':cost,'transport_collection_complete':True,'collection_complete':True,'fixture_control':True}
        arms.append({'arm':arm,'collection':collection,'result_path':str(tmp_path/arm/'result.json'),
            'exception':None,'verifier':None})
    (tmp_path/'pair-result.json').write_text(json.dumps({'arms':arms[::-1]if reverse else arms}))
    single_report(tmp_path,tmp_path/'report',fixture_control=True)
    result=json.loads((tmp_path/'report/results.json').read_text());assert result['collection_accepted']
    for row in result['rows']:
        metrics={m['id']:m for m in row['normalized_metrics']}
        assert metrics['Q6.input_tokens']['raw']==100
        assert metrics['Q6.cache_tokens']['raw']==0
        assert metrics['Q6.cache_input_utilization']['score']==0
        assert metrics['Q6.paired_cost_ratio']['score']==pytest.approx(200/3)
        assert row['finance_estimated_usd']==(.2 if row['variant_id']=='pi-native'else .1)
