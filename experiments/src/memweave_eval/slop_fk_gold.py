"""SCB-02's actual OFF -> ON specification revision; evaluator-only gold.

Visible and semantically unarchived records are deliberately separate. Moving
an old rule out of the display window is not a correction of that rule.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .evidence_replay import read_object
from .fixed35 import checkpoint_verdict
from .fixed35_business import case_events, execution_boundaries
from .storage import atomic_json, file_digest
from .suites import task_digest

VERSION='fixed35-slop-fk-20261103-v1'
PUBLIC_PROTOCOL='''Derived recording protocol, identical for both variants:
If structured State tools are available, represent an important current foreign
key migration rule in a compact JSON Fact with exactly r, v, lo, hi:
{"r":"fk","v":"ON or OFF","lo":first_applicable_checkpoint,"hi":last_applicable_checkpoint_or_null}.
Use the actual rule and scope from the checkpoint specifications supplied so far.
Correct superseded records before dependent implementation; historical scoped
rules may remain. This schema gives no future rule or implementation answer.
'''.strip()
REQUIRED_TESTS=[
    ('checkpoint_3-Core','test_add_foreign_key'),
    ('checkpoint_3-Functionality','test_add_foreign_key_on_empty_table_enforces_future_writes'),
    ('checkpoint_3-Error','test_foreign_key_violation_existing_data'),
    ('checkpoint_3-Functionality','test_foreign_key_on_delete_set_null'),
    ('checkpoint_3-Error','test_transactional_rollback_on_failure'),
]


def freeze_contract(case,source:Path,runtime_task:Path,output:Path,*,metric_matrix=None):
    if case['pack_case_id']!='SCB-02'or case['upstream_case_id']!='database_migration':
        raise ValueError('selected SCB-02 source identity required')
    revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if revision!=case['source_revision']or subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True):
        raise ValueError('Slop source pin changed or dirty')
    hashes={};fragments={1:"Use SQLite's `PRAGMA foreign_keys = OFF` during migrations",
        3:'Enable foreign keys at the start of each migration: `PRAGMA foreign_keys = ON`'}
    for stage,fragment in fragments.items():
        path=source/'database_migration'/f'checkpoint_{stage}.md'
        if path.read_text().count(fragment)!=1:raise ValueError('actual source FK contract missing or ambiguous')
        hashes[str(path)]=file_digest(path)
    if any(p.is_symlink()for p in runtime_task.rglob('*')):raise ValueError('redirected actor task')
    target=output/'tasks'/'SCB-02';shutil.copytree(runtime_task,target)
    first=target/'steps/checkpoint_1/instruction.md';first.write_text(first.read_text()+'\n\n'+PUBLIC_PROTOCOL+'\n')
    contract={'version':VERSION,'adapter_kind':'slop-fk-source-v1','case_id':'SCB-02','fixture_only':False,
        'source_revision':revision,'source_hashes':hashes,'source_fragments':fragments,'metric_matrix':metric_matrix or[],
        'task_path':str(target),'task_sha256':task_digest(target),'source_task_sha256':task_digest(runtime_task),
        'source_stages':[f'checkpoint_{i}'for i in range(1,6)],'record_stages':{'2':'OFF','3':'ON'},
        'required_source_tests':REQUIRED_TESTS,'public_protocol':PUBLIC_PROTOCOL,
        'task_config':{'workspace':{'root':'/workspace','files':[],
            'projection_trees':{'mutable':{'path':'.','selectors':{'names':['requirements.txt'],'segments':[],'suffixes':['.py']}}}}},
        'scope':'Finite typed FK rule, source-change timing, original source test subset, and mechanical Task continuity; not general semantic memory or original outcome',
        'not_formal_admission':True,'gold_actor_visible':False}
    private=output/'evaluator-only/SCB-02/contract.json';atomic_json(private,contract,immutable=True)
    return contract


def journal_entries(rows):
    """Read-only semantic projection of a verified original State journal."""
    entries={};counts={'F':0,'D':0};seen=set()
    for position,row in enumerate(rows,1):
        if not isinstance(row,dict)or not isinstance(row.get('op_id'),str)or row['op_id']in seen:
            raise ValueError('invalid or duplicate State operation')
        seen.add(row['op_id']);op=row.get('op')
        if position==1 and op!='update_goal':raise ValueError('State journal lacks initial Goal')
        if op=='update_goal':
            if not isinstance(row.get('goal'),str):raise ValueError('invalid Goal')
            continue
        if op in {'append_fact','append_decision','modify_fact'}:
            if op=='modify_fact':
                archived=row.get('archive')
                if not isinstance(archived,list)or not archived or len(set(archived))!=len(archived):raise ValueError('invalid archive set')
                for identity in archived:
                    if identity not in entries or entries[identity]['archived']:raise ValueError('invalid archive target')
                    entries[identity].update(archived=True,visible=False)
            kind='D'if op=='append_decision'else'F';counts[kind]+=1;identity=kind+str(counts[kind])
            if op!='modify_fact'and row.get('id')!=identity:raise ValueError('noncontiguous State ID')
            text=row.get('append_fact',{}).get('content')if op=='modify_fact'else row.get('decision'if kind=='D'else'fact')
            if not isinstance(text,str):raise ValueError('invalid State content')
            entries[identity]={'id':identity,'text':text,'position':position,'archived':False,'visible':True}
        elif op=='slide_window':
            bounds=row.get('evicted_range',{});lo,hi=bounds.get('from'),bounds.get('to');retained=row.get('retained_ids')
            if type(lo)is not int or type(hi)is not int or not 0<lo<=hi<position or not isinstance(retained,list):
                raise ValueError('invalid State window range')
            for identity,entry in entries.items():
                if lo<=entry['position']<=hi and identity not in retained:entry['visible']=False
        else:raise ValueError('unsupported State operation')
    return list(entries.values())


def _card(text):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('duplicate JSON key')
            result[k]=v
        return result
    try:value=json.loads(text,object_pairs_hook=unique)
    except (ValueError,TypeError):
        try:ambiguous=json.loads(text)
        except (ValueError,TypeError):return None
        return {'invalid_target':True}if isinstance(ambiguous,dict)and ambiguous.get('r')=='fk'else None
    if not isinstance(value,dict)or value.get('r')!='fk':return None
    valid=set(value)=={'r','v','lo','hi'}and isinstance(value['v'],str)and value['v']in {'ON','OFF'}and type(value['lo'])is int and value['lo']>=1
    valid=valid and(value['hi']is None or type(value['hi'])is int and value['hi']>=value['lo'])
    return value if valid else {'invalid_target':True}


def fk_checkpoint(entries,stage,expected,*,before_dependency,boundaries_complete):
    checks={'correct_visible_current_card':None,'no_unarchived_incompatible_current_card':None,
        'before_dependency':before_dependency if type(before_dependency)is bool else None,
        'complete_execution_boundaries':True if boundaries_complete is True else None}
    if entries is not None:
        cards=[(_card(e['text']),e)for e in entries if not e['archived']]
        malformed=any(c and c.get('invalid_target')for c,e in cards)
        current=[(c,e)for c,e in cards if c and not c.get('invalid_target')and c['lo']<=stage and(c['hi']is None or stage<=c['hi'])]
        checks['correct_visible_current_card']=any(c['v']==expected and e['visible']for c,e in current)
        checks['no_unarchived_incompatible_current_card']=not malformed and all(c['v']==expected for c,e in current)
    return checkpoint_verdict({'id':VERSION+':rule-checkpoint-'+str(stage),'required_assertions':list(checks)},checks)


def source_test_checkpoint(report):
    checks={group+':'+name:None for group,name in REQUIRED_TESTS}
    valid=isinstance(report,dict)and report.get('problem_name')=='database_migration'and report.get('checkpoint_name')=='checkpoint_3' \
        and report.get('infrastructure_failure')is False and type(report.get('pytest_exit_code'))is int \
        and report['pytest_exit_code']in (0,1)and type(report.get('pytest_collected'))is int and report['pytest_collected']>0
    for group,name in REQUIRED_TESTS:
        groups=report.get('tests')if valid else None
        values=groups.get(group)if isinstance(groups,dict)else None
        if not isinstance(values,dict):continue
        if not all(isinstance(values.get(status),list)for status in ('passed','failed','skipped')):continue
        states=[status for status in ('passed','failed','skipped')for item in values[status]if item==name]
        if len(states)==1:checks[group+':'+name]=states==['passed']
    return checkpoint_verdict({'id':VERSION+':source-business-checkpoint-3','required_assertions':list(checks)},checks)


def _state_at(events,locations,cutoff):
    snapshot=None;journals={}
    for order,event in enumerate(events):
        if cutoff is not None and order>=cutoff:break
        block=event.get('prepared_boundary')if event['event']=='request_ready'else event.get('state')if event['event']=='state_after_tool'else None
        if not isinstance(block,dict):continue
        ref=block.get('expected_journal_ref',block.get('journal_ref'));task=block.get('expected_task_id',block.get('task_id'))
        if ref:
            store=locations[(event['producer_id'],event['sequence'])]
            rows=[json.loads(line)for line in read_object(store,ref).decode().splitlines()]
            if task in journals and journals[task]!=rows[:len(journals[task])]:raise ValueError('non-append-only State evidence')
            journals[task]=rows;snapshot=journal_entries(rows)
        elif block.get('status')=='NO_BOUND_TASK'or'expected_task_id'in block and block['expected_task_id']is None:snapshot=[]
        else:snapshot=None
    return snapshot


def dependency_boundary(events,stage):
    frames=[(i,e)for i,e in enumerate(events)if e.get('stage_id')==stage and e['event']=='workspace_checkpoint']
    starts=[(i,e)for i,e in frames if e.get('phase')=='agent_start'];ends=[(i,e)for i,e in frames if e.get('phase')=='agent_end']
    if not starts or not ends:return None,'MISSING_INITIAL_OR_FINAL_BOUNDARY'
    baseline=starts[0][1].get('workspace',{}).get('tree_projections',{}).get('mutable',{})
    if baseline.get('status')!='complete'or not isinstance(baseline.get('projection_sha256'),str):return None,'MISSING_INITIAL_SOURCE_PROJECTION'
    for i,event in frames:
        current=event.get('workspace',{}).get('tree_projections',{}).get('mutable',{})
        if current.get('status')!='complete'or not isinstance(current.get('projection_sha256'),str):return None,'INCOMPLETE_SOURCE_PROJECTION'
        if current['projection_sha256']==baseline['projection_sha256']:continue
        call=next((j for j,e in enumerate(events)if e.get('stage_id')==stage and e['event']=='tool_call'
            and e['producer_id']==event['producer_id']and e.get('call_id')==event.get('call_id')),None)
        if call is None or event.get('phase')not in {'tool_end','tool_result'}:return None,'UNLINKED_SOURCE_CHANGE'
        pending=set()
        for prior in events[starts[0][0]:i]:
            key=prior['producer_id'],prior.get('call_id')
            if prior['event']=='tool_call':pending.add(key)
            elif prior['event']=='workspace_checkpoint'and prior.get('phase')in {'tool_end','tool_result'}:pending.discard(key)
        if pending!={(event['producer_id'],event.get('call_id'))}:return None,'AMBIGUOUS_OVERLAPPING_TOOL_BOUNDARY'
        return call,'FIRST_OBSERVED_PERSISTENT_SOURCE_CHANGE'
    return ends[-1][0],'COMPLETE_STAGE_END_WITHOUT_OBSERVED_SOURCE_CHANGE'


def grade_trial(trial:Path,contract,*,arm,official_outcome=None):
    if contract.get('version')!=VERSION or contract.get('case_id')!='SCB-02':raise ValueError('matching SCB-02 contract required')
    for path,sha in contract['source_hashes'].items():
        if file_digest(Path(path))!=sha:raise ValueError('source-bound FK gold changed')
    events,locations=case_events(trial);points={};boundaries={}
    for stage,value in contract['record_stages'].items():
        selected=[e for e in events if e.get('stage_id')==stage]
        coverage=execution_boundaries(trial/'steps'/('checkpoint_'+stage),selected,stage_id=stage)
        cutoff,reason=dependency_boundary(events,stage)
        entries=_state_at(events,locations,cutoff)if cutoff is not None else None
        point=fk_checkpoint(entries,int(stage),value,before_dependency=True if cutoff is not None else None,
            boundaries_complete=coverage['complete'])
        if arm=='pi-native':point={'score':None,'status':'DESIGN_NA','collection_complete':True,'reason':'Native Pi has no symbolic State tools'}
        points['record-'+stage]=point;boundaries[stage]={'order':cutoff,'reason':reason,'coverage':coverage}
    evidence=(official_outcome or{}).get('source_evidence',{}).get('checkpoint_3',{});report=None
    if evidence.get('report')and evidence.get('sha256'):
        path=Path(evidence['report'])
        if file_digest(path)!=evidence['sha256']:raise ValueError('actual source verifier report changed')
        report=json.loads(path.read_text())
    points['source-business-3']=source_test_checkpoint(report)
    registry=[e for e in events if e['event']=='task_registry_checkpoint']
    all_coverage={str(i):execution_boundaries(trial/'steps'/stage,[e for e in events if e.get('stage_id')==str(i)],stage_id=str(i))
        for i,stage in enumerate(contract['source_stages'],1)}
    complete=bool(registry)and all(e.get('registry',{}).get('complete')is True for e in registry)and all(c['complete']for c in all_coverage.values())
    for stage in all_coverage:
        rows=[e for e in registry if e.get('stage_id')==stage]
        if not any(e.get('phase')=='agent_start'for e in rows)or not any(e.get('phase')=='agent_end'for e in rows):complete=False
    bindings=[e.get('binding',{})for e in registry];ids={b.get('task_id')for b in bindings if b.get('status')=='CAPTURED'}
    created={t['task_id']for e in registry for t in e.get('registry',{}).get('tasks',[])}if complete else None
    check={'one_persistent_task':len(created)==1 if created is not None else None,
        'one_bound_task':len(ids)==1 if complete else None,
        'same_binding_at_dependent_stage_boundaries':None}
    selected=[]
    for stage in ('2','3'):
        cutoff=boundaries[stage]['order']
        relevant=[e for i,e in enumerate(events)if cutoff is not None and i<cutoff and e['event']=='task_registry_checkpoint']
        selected.append(relevant[-1].get('binding',{})if relevant else{})
    if complete and all(b.get('status')in {'CAPTURED','NO_BOUND_TASK'}for b in selected):
        check['same_binding_at_dependent_stage_boundaries']=all(b.get('status')=='CAPTURED'for b in selected)and len({b.get('task_id')for b in selected})==1
    points['task-continuity']=checkpoint_verdict({'id':VERSION+':task-continuity','required_assertions':list(check)},check)if arm=='pi-memweave'else{
        'score':None,'status':'DESIGN_NA','collection_complete':True,'reason':'Native Pi has no Task tools'}
    fixture=contract.get('fixture_only')is True or any(trial.rglob('cli-fake-upstream.jsonl'))
    return {'version':VERSION,'case_id':'SCB-02','fixture_only':fixture,'checkpoints':points,'dependency_boundaries':boundaries,'stage_coverage':all_coverage,
        'collection_complete':all(p['collection_complete']for p in points.values()),'scope':contract['scope']}


def checkpoint_rows(result):
    meanings={
        'record-2':'第2阶段首次持久源码变化前保留适用的OFF卡；完整阶段无变化时取阶段结束边界',
        'record-3':'第3阶段依赖边界前可见ON卡且没有仍适用的未归档冲突卡；限定历史允许保留，窗口驱逐不等于纠错',
        'source-business-3':'第3阶段原测试中的添加外键、空表后续写约束、已有数据冲突、SET NULL和事务回滚五项全部通过',
        'task-continuity':'五阶段完整Task观测中仅一个持久Task，依赖边界绑定同一Task；不推断认知恢复',
    }
    return [{'id':VERSION+':'+name,'raw':point['score']/100 if point['score']is not None else None,
        'score':point['score'],'status':point['status'],'meaning':meanings[name]+'; '+result['scope'],
        'raw_formula':'Design NA: native has no corresponding tools'if point['status']=='DESIGN_NA'else
            'AND('+', '.join(point['assertions'])+'); checkpoints remain independent',
        'score_formula':'100 * binary checkpoint verdict','weights':{'common_product':0,'plugin_memory':0},
        'mapping_version':VERSION,'support':point,'collection_complete':point['collection_complete'],
        'applicability':'all'if name=='source-business-3'else'plugin',
        'support_s':int(point['score']==100)if point['score']is not None else 0,
        'support_f':int(point['score']==0)if point['score']is not None else 0,
        'support_u':int(point['score']is None and point['status']!='DESIGN_NA'),
        'support_n':int(point['status']!='DESIGN_NA'),
        'reason':'Supplementary source component; no duplicate leaf weight'}
        for name,point in result['checkpoints'].items()]
