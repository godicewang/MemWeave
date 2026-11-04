"""Existing experiment CLI's fixed-package source, collection and scoring commands."""
from __future__ import annotations

import json
from pathlib import Path

from .fixed35_sources import applicability_matrix, prepare_source_manifest, read_design
from .storage import atomic_json


def register(sub):
    parser=sub.add_parser('fixed35',help='Prepare or evaluate the fixed 35-case campaign')
    commands=parser.add_subparsers(dest='fixed35_command',required=True)
    sources=commands.add_parser('sources',help='Verify all pinned selectors and freeze evaluator-only mapping')
    sources.add_argument('design',type=Path)
    sources.add_argument('--sources',type=Path,required=True)
    sources.add_argument('--output',type=Path,required=True)
    dispatch=commands.add_parser('dispatch-contract',help='Freeze TB-09 exact event-cutoff source checks and CLI transcript; no actor execution')
    dispatch.add_argument('--design',type=Path,required=True)
    dispatch.add_argument('--source',type=Path,required=True)
    dispatch.add_argument('--output',type=Path,required=True)
    dispatch_replay=commands.add_parser('dispatch',help='Replay TB-09 real business scores; its CTRF is not a task-quality signal')
    dispatch_replay.add_argument('trial',type=Path)
    dispatch_replay.add_argument('--contract',type=Path,required=True)
    dispatch_replay.add_argument('--fixture-control',action='store_true')
    dispatch_replay.add_argument('--output',type=Path,required=True)
    selected=commands.add_parser('selected-source-contract',help='Freeze explicit selected parity/archive/session/entity/checkpoint/anonymization source gold; no models or admission')
    selected.add_argument('case_id',choices=['TB-01','TB-03','TB-04','TB-06','TB-07','TB-10'])
    selected.add_argument('--design',type=Path,required=True)
    selected.add_argument('--source',type=Path,required=True)
    selected.add_argument('--output',type=Path,required=True)
    selected_replay=commands.add_parser('selected-source',help='Replay exact selected source cases with console and CTRF identity cross-checks')
    selected_replay.add_argument('trial',type=Path)
    selected_replay.add_argument('--contract',type=Path,required=True)
    selected_replay.add_argument('--fixture-control',action='store_true')
    selected_replay.add_argument('--output',type=Path,required=True)
    wal=commands.add_parser('wal-contract',help='Freeze TB-05 exact original test identities and gate checkpoints; no model calls or admission')
    wal.add_argument('--design',type=Path,required=True)
    wal.add_argument('--source',type=Path,required=True)
    wal.add_argument('--output',type=Path,required=True)
    wal_replay=commands.add_parser('wal',help='Replay TB-05 original verifier gates, 97-case source outcomes and ten-run determinism')
    wal_replay.add_argument('trial',type=Path)
    wal_replay.add_argument('--contract',type=Path,required=True)
    wal_replay.add_argument('--fixture-control',action='store_true')
    wal_replay.add_argument('--output',type=Path,required=True)
    warranty=commands.add_parser('warranty-tasks',help='Bind TB-02 portal source gold and a shared claim-recording schema; no models or admission')
    warranty.add_argument('--design',type=Path,required=True)
    warranty.add_argument('--source',type=Path,required=True)
    warranty.add_argument('--runtime-task',type=Path,required=True)
    warranty.add_argument('--output',type=Path,required=True)
    warranty_replay=commands.add_parser('warranty',help='Replay real signed final/first portal decisions and pre-submission State')
    warranty_replay.add_argument('trial',type=Path)
    warranty_replay.add_argument('--contract',type=Path,required=True)
    warranty_replay.add_argument('--arm',choices=['pi-native','pi-memweave'],required=True)
    warranty_replay.add_argument('--fixture-control',action='store_true')
    warranty_replay.add_argument('--output',type=Path,required=True)
    fk=commands.add_parser('slop-fk-tasks',help='Derive SCB-02 source FK correction checkpoints; no model calls or admission')
    fk.add_argument('--design',type=Path,required=True)
    fk.add_argument('--source',type=Path,required=True)
    fk.add_argument('--runtime-task',type=Path,required=True)
    fk.add_argument('--output',type=Path,required=True)
    fk_replay=commands.add_parser('slop-fk',help='Replay SCB-02 rule timing, semantic invalidation, business tests and Task continuity')
    fk_replay.add_argument('trial',type=Path)
    fk_replay.add_argument('--contract',type=Path,required=True)
    fk_replay.add_argument('--official-outcome',type=Path)
    fk_replay.add_argument('--arm',choices=['pi-native','pi-memweave'],required=True)
    fk_replay.add_argument('--fixture-control',action='store_true')
    fk_replay.add_argument('--output',type=Path,required=True)
    interrupt=commands.add_parser('interrupt-contract',help='Freeze selected Interrupt final-value source gold; browser environment and temporal behavior are not admitted')
    interrupt.add_argument('--design',type=Path,required=True)
    interrupt.add_argument('--source',type=Path,required=True)
    interrupt.add_argument('--case-id',choices=['INT-08','INT-09','INT-10'],required=True)
    interrupt.add_argument('--output',type=Path,required=True)
    baseline=commands.add_parser('interrupt-baseline',help='Freeze one shared source replay prefix; no model calls, browser replay, or opportunity claim')
    baseline.add_argument('--contract',type=Path,required=True)
    baseline.add_argument('--replay',type=Path,required=True)
    baseline.add_argument('--output',type=Path,required=True)
    baseline.add_argument('--fixture-control',action='store_true')
    final_interrupt=commands.add_parser('interrupt-final',help='Grade final selected browser-query evidence; does not infer temporal correction or rating removal from URL alone')
    final_interrupt.add_argument('--contract',type=Path,required=True)
    final_interrupt.add_argument('--capture',type=Path,required=True)
    final_interrupt.add_argument('--output',type=Path,required=True)
    final_interrupt.add_argument('--fixture-control',action='store_true')
    wdm=commands.add_parser('wdm-contract',help='Freeze source-bound LONG-02 output artifact predicates; no model calls or admission')
    wdm.add_argument('--design',type=Path,required=True)
    wdm.add_argument('--source',type=Path,required=True)
    wdm.add_argument('--output',type=Path,required=True)
    state=commands.add_parser('state-contract',help='Freeze evaluator-only program predicates for a pinned STATE case; no model calls')
    state.add_argument('case_id',choices=[f'INT-0{i}'for i in range(1,6)])
    state.add_argument('--source',type=Path,required=True)
    state.add_argument('--output',type=Path,required=True)
    state.add_argument('--overlay',choices=['equal-authority-conflict-v1','equal-authority-conflict-v2','equal-authority-conflict-v3'])
    conflict=commands.add_parser('state-conflict',help='Replay the selected INT-04 typed-authority overlay; no paid judge')
    conflict.add_argument('trial',type=Path)
    conflict.add_argument('--private',type=Path,required=True)
    conflict.add_argument('--contract',type=Path,required=True)
    conflict.add_argument('--arm',choices=['pi-native','pi-memweave'],required=True)
    conflict.add_argument('--output',type=Path,required=True)
    switch=commands.add_parser('switch-contract',help='Bind selected Switch source stages and original tests; evaluator-only component, not Task admission')
    switch.add_argument('case_id',choices=['INT-06','INT-07'])
    switch.add_argument('--source',type=Path,required=True)
    switch.add_argument('--output',type=Path,required=True)
    protection=commands.add_parser('source-protection-tasks',help='Freeze selected source-protection gold and a shared recording overlay; no model calls or admission')
    protection.add_argument('case_id',choices=['LONG-03','LONG-04','TB-08'])
    protection.add_argument('--design',type=Path,required=True)
    protection.add_argument('--source',type=Path,required=True)
    protection.add_argument('--runtime-task',type=Path,required=True)
    protection.add_argument('--output',type=Path,required=True)
    probes=commands.add_parser('switch-probe-tasks',help='Derive source-bound closed-set Task/remembered-contract checkpoints; no model calls or formal admission')
    probes.add_argument('case_id',choices=['INT-06','INT-07'])
    probes.add_argument('--source',type=Path,required=True)
    probes.add_argument('--runtime-task',type=Path,required=True)
    probes.add_argument('--output',type=Path,required=True)
    probe_replay=commands.add_parser('switch-probes',help='Replay selected Switch contract/Task actions from actual CLI evidence; no model calls')
    probe_replay.add_argument('trial',type=Path)
    probe_replay.add_argument('--contract',type=Path,required=True)
    probe_replay.add_argument('--arm',choices=['pi-native','pi-memweave'],required=True)
    probe_replay.add_argument('--output',type=Path,required=True)
    final=commands.add_parser('switch-final',help='Evaluate source-bound final-delivery and original-test checkpoints offline; no memory inference')
    final.add_argument('--contract',type=Path,required=True)
    final.add_argument('--answer',type=Path)
    final.add_argument('--outcomes',type=Path)
    final.add_argument('--original-result',type=Path)
    final.add_argument('--output',type=Path,required=True)
    task=commands.add_parser('task-checkpoints',help='Replay real Task checkpoint evidence with a frozen evaluator-only opportunity contract; no model calls')
    task.add_argument('trial',type=Path)
    task.add_argument('--contract',type=Path,required=True)
    task.add_argument('--action-evidence',type=Path)
    task.add_argument('--output',type=Path,required=True)
    mab=commands.add_parser('mab-contracts',help='Freeze all eight evaluator-only MAB action/correction components; not formal admissions')
    mab.add_argument('adapter',type=Path)
    mab.add_argument('--output',type=Path,required=True)
    books=commands.add_parser('mab-book-contracts',help='Freeze selected book-event relation gold and public schema; evaluator-only, no model calls')
    books.add_argument('adapter',type=Path)
    books.add_argument('--output',type=Path,required=True)
    books.add_argument('--derive-tasks',action='store_true',help='Copy only original actor files and append the public generic card schema; gold stays separate')
    pressure=commands.add_parser('mab-pressure-tasks',help='Derive all eight source-only MAB pressure tasks and private current-source contracts; no model calls')
    pressure.add_argument('adapter',type=Path)
    pressure.add_argument('--design',type=Path,required=True)
    pressure.add_argument('--data',type=Path,required=True)
    pressure.add_argument('--nltk-data',type=Path,required=True)
    pressure.add_argument('--output',type=Path,required=True)
    replay=commands.add_parser('replay',help='Verify exact request/tool evidence without model calls')
    replay.add_argument('root',type=Path)
    replay.add_argument('--transport',type=Path,required=True)
    replay.add_argument('--output',type=Path,required=True)
    run=commands.add_parser('run',help='Run an admitted case through the existing paired Harbor/Pi path')
    run.add_argument('admission',type=Path)
    run.add_argument('--output',type=Path,required=True)
    schedule=commands.add_parser('schedule',help='Dry-run the fixed35 resource queue, or explicitly execute admitted cases')
    schedule.add_argument('plan',type=Path)
    schedule.add_argument('--output',type=Path,required=True)
    schedule.add_argument('--execute',action='store_true')
    report=commands.add_parser('report',help='Recompute offline into a new explicit output directory')
    report.add_argument('root',type=Path)
    report.add_argument('--output',type=Path,required=True)
    report.add_argument('--official-outcomes',type=Path)
    report.add_argument('--fixture-control',action='store_true',help='Explicitly label offline fake-provider control reports; rejected by real pack scoring')
    package=commands.add_parser('pack-report',help='Report the complete frozen 35-case matrix')
    package.add_argument('manifest',type=Path)
    package.add_argument('--output',type=Path,required=True)


def execute(args):
    if args.fixed35_command=='dispatch-contract':
        from .dispatch_gold import freeze_contract
        design=read_design(args.design);case=next(c for c in design['selection']['cases']if c['pack_case_id']=='TB-09')
        matrix=[r for r in applicability_matrix(design)if r['case_id']=='TB-09']
        for row in matrix:
            if row['metric_id']in {'S.common.protected_constraints','S.common.process_validation'}:
                row.update(design_status='PLANNED',opportunity_ids=['selected-dispatch-source-trace'],
                    reason='Original temporal/current-event program cases and actual command protocol; no MemWeave State adoption inference')
            if row['metric_id']=='S3.partial_pass_rate':
                row.update(design_status='DESIGN_NA',opportunity_ids=[],
                    reason='Original CTRF always says 1/1 passed even for absent executable; not a meaningful task partial-test rate. Original weighted business diagnostic has a distinct supplementary ID and formula.',
                    assignment_basis='authored_source_protocol_CTRF_is_constant_success_not_business_score')
        value=freeze_contract(case,args.source,args.output,metric_matrix=matrix)
        return {'case_id':'TB-09','output':str(args.output),'weighted_source_checks':len(value['weighted_checks']),
            'source_commands':len(value['commands']),'not_formal_admission':True,'paid_requests':0}
    if args.fixed35_command=='dispatch':
        from .dispatch_gold import grade_trial
        value=grade_trial(args.trial,json.loads(args.contract.read_text()),fixture_control=args.fixture_control)
        atomic_json(args.output,value,immutable=True)
        return {'case_id':'TB-09','output':str(args.output),'collection_complete':value['collection_complete'],
            'fixture_only':value['fixture_only'],'paid_requests':0}
    if args.fixed35_command=='selected-source-contract':
        from .pytest_source_gold import freeze_contract
        design=read_design(args.design);case=next(c for c in design['selection']['cases']if c['pack_case_id']==args.case_id)
        matrix=[r for r in applicability_matrix(design)if r['case_id']==args.case_id]
        for row in matrix:
            if row['metric_id']in {'S.common.protected_constraints','S.common.process_validation'}or(
                    args.case_id=='TB-03'and row['metric_id']=='S.common.dependency_constraints'):
                row.update(design_status='PLANNED',opportunity_ids=['selected-exact-source-tests'],
                    reason='Pinned original selected business cases, complete source validation and TB-03 finite readable/non-wrapper checks; no general memory or provenance inference')
        value=freeze_contract(case,args.source,args.output,metric_matrix=matrix)
        return {'case_id':args.case_id,'output':str(args.output),'source_test_ids':len(value['test_ids']),
            'not_formal_admission':True,'paid_requests':0}
    if args.fixed35_command=='selected-source':
        from .pytest_source_gold import grade_trial
        value=grade_trial(args.trial,json.loads(args.contract.read_text()),fixture_control=args.fixture_control)
        atomic_json(args.output,value,immutable=True)
        return {'case_id':value['case_id'],'output':str(args.output),'collection_complete':value['collection_complete'],
            'fixture_only':value['fixture_only'],'paid_requests':0}
    if args.fixed35_command=='wal-contract':
        from .wal_gold import freeze_contract
        design=read_design(args.design);case=next(c for c in design['selection']['cases']if c['pack_case_id']=='TB-05')
        matrix=[r for r in applicability_matrix(design)if r['case_id']=='TB-05']
        for metric in matrix:
            if metric['metric_id']in {'S.common.protected_constraints','S.common.process_validation','S.common.dependency_constraints'}:
                metric.update(design_status='PLANNED',opportunity_ids=['selected-wal-source-verifier'],
                    reason='Frozen exact source behavior, ten-run validation and structural gates respectively; no general memory inference')
        value=freeze_contract(case,args.source,args.output,metric_matrix=matrix)
        return {'case_id':'TB-05','output':str(args.output),'source_test_ids':len(value['test_ids']),
            'not_formal_admission':True,'paid_requests':0}
    if args.fixed35_command=='wal':
        from .wal_gold import grade_trial
        value=grade_trial(args.trial,json.loads(args.contract.read_text()),fixture_control=args.fixture_control)
        atomic_json(args.output,value,immutable=True)
        return {'case_id':'TB-05','output':str(args.output),'collection_complete':value['collection_complete'],
            'fixture_only':value['fixture_only'],'paid_requests':0}
    if args.fixed35_command=='warranty-tasks':
        from .warranty_gold import freeze_contract
        design=read_design(args.design);case=next(c for c in design['selection']['cases']if c['pack_case_id']=='TB-02')
        matrix=[r for r in applicability_matrix(design)if r['case_id']=='TB-02']
        for row in matrix:
            if row['metric_id']=='S.common.protected_constraints':
                row.update(design_status='PLANNED',opportunity_ids=['20-source-claim-decisions'],reason='Mean of 20 signed claim-specific multi-assertion checkpoints; original all-or-nothing reward remains separate')
            if row['metric_id']in {'S1.timely_write','S1.retention','S1.write_precision','S1.pollution'}:
                row.update(design_status='PLANNED',opportunity_ids=['finite-warranty-claim-cards-v1'],
                    reason='Restricted source claim c/b/q grammar; four required late-material slots and reported judgeable creation coverage, not all free-text memory')
        result=freeze_contract(case,args.source,args.runtime_task,args.output,metric_matrix=matrix)
        return {'case_id':result['case_id'],'task_path':result['task_path'],'paid_requests':0,'not_formal_admission':True}
    if args.fixed35_command=='warranty':
        from .warranty_gold import grade_trial
        result=grade_trial(args.trial,json.loads(args.contract.read_text()),arm=args.arm)
        if result['fixture_only']and not args.fixture_control:raise ValueError('Warranty fixture requires explicit fixture-control')
        atomic_json(args.output,result,immutable=True)
        return {'case_id':result['case_id'],'output':str(args.output),'fixture_only':result['fixture_only'],'collection_complete':result['collection_complete'],'paid_requests':0}
    if args.fixed35_command=='slop-fk-tasks':
        from .slop_fk_gold import freeze_contract
        design=read_design(args.design);case=next(c for c in design['selection']['cases']if c['pack_case_id']=='SCB-02')
        matrix=[r for r in applicability_matrix(design)if r['case_id']=='SCB-02']
        for row in matrix:
            if row['metric_id']=='S.common.protected_constraints':
                row.update(design_status='PLANNED',opportunity_ids=['checkpoint-3-five-fk-source-tests'],
                    reason='Five independent original FK/rollback test assertions AND; not general constraints or entire source outcome')
        result=freeze_contract(case,args.source,args.runtime_task,args.output,metric_matrix=matrix)
        return {'case_id':result['case_id'],'task_path':result['task_path'],'paid_requests':0,'not_formal_admission':True}
    if args.fixed35_command=='slop-fk':
        from .slop_fk_gold import grade_trial
        contract=json.loads(args.contract.read_text())
        outcome=json.loads(args.official_outcome.read_text())if args.official_outcome else None
        result=grade_trial(args.trial,contract,arm=args.arm,official_outcome=outcome)
        if result['fixture_only']and not args.fixture_control:raise ValueError('Slop FK fixtures require explicit fixture-control')
        atomic_json(args.output,result,immutable=True)
        return {'case_id':result['case_id'],'output':str(args.output),'paid_requests':0,
            'fixture_only':result['fixture_only'],'collection_complete':result['collection_complete']}
    if args.fixed35_command=='interrupt-contract':
        from .interrupt_source_gold import freeze_contract
        design=read_design(args.design);case=next(c for c in design['selection']['cases']if c['pack_case_id']==args.case_id)
        matrix=[r for r in applicability_matrix(design)if r['case_id']==args.case_id]
        for row in matrix:
            if row['metric_id']=='S.common.protected_constraints':
                row.update(design_status='DESIGN_UNRESOLVED'if args.case_id=='INT-10'else'PLANNED',
                    opportunity_ids=['selected-final-source-values'],reason='Final source DOM constraints only; not timely memory correction'
                        if args.case_id!='INT-10'else'Source URL cannot prove rating retraction; calibrated active-filter observation is not implemented')
        result=freeze_contract(case,args.source,args.output,metric_matrix=matrix)
        return {'case_id':args.case_id,'output':str(args.output),'paid_requests':0,
            'not_formal_admission':True,'pending':result['pending']}
    if args.fixed35_command=='interrupt-baseline':
        from .interrupt_source_gold import freeze_baseline
        result=freeze_baseline(json.loads(args.contract.read_text()),args.replay,args.output,
            fixture_control=getattr(args,'fixture_control',False))
        return {'case_id':result['case_id'],'output':str(args.output),'paid_requests':0,
            'total_actions':result['total_actions'],'interrupt_at_action':result['interrupt_at_action'],
            'baseline_sha256':result['baseline_sha256'],'behavior_opportunity_verified':False,
            'fixture_only':result['fixture_only']}
    if args.fixed35_command=='interrupt-final':
        from .interrupt_source_gold import grade_capture
        contract=json.loads(args.contract.read_text());capture=json.loads(args.capture.read_text())if args.capture.is_file()else None
        result=grade_capture(contract,capture)
        if (result['fixture_only']is True or contract.get('fixture_only')is True)and not args.fixture_control:
            raise ValueError('Interrupt fixtures require explicit fixture-control; never model performance')
        atomic_json(args.output,result,immutable=True)
        return {'case_id':result['case_id'],'output':str(args.output),'paid_requests':0,
            'collection_complete':result['collection_complete'],'fixture_only':result['fixture_only']}
    if args.fixed35_command=='wdm-contract':
        from .wdm_artifact import wdm_contract
        case=next(c for c in read_design(args.design)['selection']['cases']if c['pack_case_id']=='LONG-02')
        result=wdm_contract(case,args.source,args.output)
        return {'case_id':'LONG-02','version':result['version'],'paid_requests':0,'not_formal_admission':True,
            'output':str(args.output),'required_assertions':result['required_assertions']}
    if args.fixed35_command=='source-protection-tasks':
        from .source_protection import derive_protection
        case=next(c for c in read_design(args.design)['selection']['cases']if c['pack_case_id']==args.case_id)
        record=derive_protection(case,args.source,args.runtime_task,args.output)
        return {'case_id':args.case_id,'task_path':record['task_path'],'task_sha256':record['task_sha256'],
            'protected_source_files':len(record['expected_initial_files']),'paid_requests':0,'not_formal_admission':True}
    if args.fixed35_command=='switch-probes':
        from .fixed35_switch_replay import grade_switch_probe_trial
        result=grade_switch_probe_trial(args.trial,json.loads(args.contract.read_text()),arm=args.arm)
        atomic_json(args.output,result,immutable=True)
        return {'case_id':result['case_id'],'output':str(args.output),'paid_requests':0,
            'collection_complete':result['collection_complete'],'fixture_only':result['fixture_only']}
    if args.fixed35_command=='switch-probe-tasks':
        from .fixed35_switch_probes import derive_switch_probes
        record=derive_switch_probes(args.source,args.runtime_task,args.case_id,args.output)
        return {'case_id':args.case_id,'task_path':record['task_path'],'task_sha256':record['task_sha256'],
            'probes':len(record['probes']),'paid_requests':0,'not_formal_admission':True}
    if args.fixed35_command=='mab-pressure-tasks':
        from .fixed35_adapters import mab_chunks
        from .fixed35_mab_cards import BOOKS, book_contract
        from .fixed35_mab_pressure import POLICY, VERSION, derive_pressure_task
        from .fixed35_sources import load_mab_row
        args.output.mkdir(parents=True,exist_ok=False)
        records=[]
        for case in read_design(args.design)['selection']['cases']:
            identity=case['pack_case_id']
            if identity not in POLICY:continue
            public,private=load_mab_row(case,args.data)
            chunks=mab_chunks(public,args.nltk_data,limit=POLICY[identity][0])
            records.append(derive_pressure_task(args.adapter/'tasks'/identity,identity,chunks,
                private['answers'],public['selector'],args.output,
                book_gold=book_contract(args.adapter,identity)if identity in BOOKS else None))
        atomic_json(args.output/'manifest.json',{'version':VERSION,'cases':records,
            'paid_requests':0,'status':'SOURCE_BOUND_COMPONENTS_NOT_REAL_EVICTION_OR_MODEL_RESULTS'},immutable=True)
        return {'components':len(records),'output':str(args.output),'paid_requests':0,'not_formal_admission':True}
    if args.fixed35_command=='mab-book-contracts':
        from .fixed35_mab_cards import BOOKS, book_contract, derive_book_task
        args.output.mkdir(parents=True,exist_ok=False)
        records=[book_contract(args.adapter,identity)for identity in BOOKS]
        for record in records:atomic_json(args.output/(record['case_id']+'.json'),record,immutable=True)
        if getattr(args,'derive_tasks',False):
            tasks=[derive_book_task(args.adapter,identity,args.output)for identity in BOOKS]
            atomic_json(args.output/'tasks.json',tasks,immutable=True)
        return {'contracts':len(records),'output':str(args.output),'paid_requests':0,
            'status':'DERIVED_TYPED_RECORDING_COMPONENT_NOT_AGENT_PERFORMANCE'}
    if args.fixed35_command=='state-conflict':
        from .state_conflict import grade_conflict_trial
        result=grade_conflict_trial(args.trial,args.private,json.loads(args.contract.read_text()),arm=args.arm)
        atomic_json(args.output,result,immutable=True)
        return {'output':str(args.output),'paid_requests':0,'collection_complete':result['collection_complete'],
            'fixture_only':result.get('fixture_only'),'status':'DERIVED_TYPED_AUTHORITY_PROTOCOL'}
    if args.fixed35_command=='switch-contract':
        from .fixed35_switch import switch_contract
        result=switch_contract(args.source,args.case_id)
        atomic_json(args.output,result,immutable=True)
        return {'case_id':args.case_id,'output':str(args.output),'paid_requests':0,
            'source_stages':len(result['route_ledger'])+1,'status':result['status']}
    if args.fixed35_command=='switch-final':
        from .fixed35_switch import grade_switch_final
        from .storage import file_digest
        result=grade_switch_final(json.loads(args.contract.read_text()),
            answer=args.answer.read_text()if args.answer else None,
            outcomes=json.loads(args.outcomes.read_text())if args.outcomes else None,
            original_result=json.loads(args.original_result.read_text())if args.original_result else None)
        result['source_sha256']={name:file_digest(path)for name,path in {
            'contract':args.contract,'answer':args.answer,'outcomes':args.outcomes,
            'original_result':args.original_result}.items()if path}
        atomic_json(args.output,result,immutable=True)
        return {'output':str(args.output),'paid_requests':0,'collection_complete':result['collection_complete'],
            'status':'BUSINESS_COMPONENT_REPLAY_NOT_A_MEMORY_OR_TASK_RESULT'}
    if args.fixed35_command=='mab-contracts':
        from .fixed35_mab import prepare_mab_components
        return prepare_mab_components(args.adapter,args.output)
    if args.fixed35_command=='task-checkpoints':
        from .fixed35_task_behavior import grade_task_trial
        from .storage import file_digest
        actions=json.loads(args.action_evidence.read_text())if args.action_evidence else None
        result=grade_task_trial(args.trial,json.loads(args.contract.read_text()),action_evidence=actions)
        result['contract_sha256']=file_digest(args.contract)
        result['action_evidence_sha256']=file_digest(args.action_evidence)if args.action_evidence else None
        atomic_json(args.output,result,immutable=True)
        return {'output':str(args.output),'paid_requests':0,'checkpoints':len(result['cases']),
            'status':'EVIDENCE_REPLAY_NOT_A_NEW_ACTOR_RUN'}
    if args.fixed35_command=='state-contract':
        from .fixed35_state_behavior import state_contract
        if getattr(args,'overlay',None):
            if args.case_id!='INT-04':raise ValueError('equal-authority overlay is bound to selected INT-04')
            from .state_conflict import conflict_contract
            record=conflict_contract(args.source,state_records=args.overlay!='equal-authority-conflict-v1',
                strict_current=args.overlay=='equal-authority-conflict-v3')
        else:record=state_contract(args.source,args.case_id)
        atomic_json(args.output,record,immutable=True)
        return {'case_id':args.case_id,'output':str(args.output),'paid_requests':0,
            'status':'PROGRAM_ORACLE_COMPONENT_NOT_A_MODEL_RESULT'}
    if args.fixed35_command=='schedule':
        from .fixed35_schedule import execute_schedule
        return execute_schedule(args.plan,args.output,dry_run=not args.execute)
    if args.fixed35_command=='pack-report':
        from .fixed35_pack import pack_report
        return pack_report(args.manifest,args.output)
    if args.fixed35_command=='report':
        from .fixed35_report import single_report
        return single_report(args.root,args.output,getattr(args,'official_outcomes',None),
            fixture_control=getattr(args,'fixture_control',False))
    if args.fixed35_command=='run':
        from .fixed35_campaign import run_pair
        return run_pair(args.admission,args.output)
    if args.fixed35_command=='sources':
        args.output.mkdir(parents=True,exist_ok=False)
        record=prepare_source_manifest(args.design,args.sources,args.output/'sources.json')
        matrix=applicability_matrix(read_design(args.design))
        atomic_json(args.output/'research-applicability.json',matrix,immutable=True)
        from .fixed35_sources import freeze_draft_contracts
        manifest=freeze_draft_contracts(record,matrix,args.output)
        return {'sources':record['source_case_count'],'mapping_cells':len(matrix),
                'draft_package_manifest':str(manifest),
                'paid_requests':0,'status':'SOURCE_VERIFIED_NOT_ENVIRONMENT_ADMITTED'}
    if args.fixed35_command=='replay':
        from .evidence_replay import replay_content
        transport=[json.loads(line)for line in args.transport.read_text().splitlines()]
        ids={r['request_id']for r in transport if r['event']=='http_attempt'}
        result=replay_content(args.root,expected_request_ids=ids)
        atomic_json(args.output,result,immutable=True)
        return {'replayed_requests':len(result['requests']),
                'repaired_source_records':len(result['damaged_source_records']),
                'output':str(args.output),'paid_requests':0}
    raise ValueError('unknown fixed35 operation')
