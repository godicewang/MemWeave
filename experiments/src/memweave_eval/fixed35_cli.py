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
    state=commands.add_parser('state-contract',help='Freeze evaluator-only program predicates for a pinned STATE case; no model calls')
    state.add_argument('case_id',choices=[f'INT-0{i}'for i in range(1,6)])
    state.add_argument('--source',type=Path,required=True)
    state.add_argument('--output',type=Path,required=True)
    task=commands.add_parser('task-checkpoints',help='Replay real Task checkpoint evidence with a frozen evaluator-only opportunity contract; no model calls')
    task.add_argument('trial',type=Path)
    task.add_argument('--contract',type=Path,required=True)
    task.add_argument('--action-evidence',type=Path)
    task.add_argument('--output',type=Path,required=True)
    mab=commands.add_parser('mab-contracts',help='Freeze all eight evaluator-only MAB action/correction components; not formal admissions')
    mab.add_argument('adapter',type=Path)
    mab.add_argument('--output',type=Path,required=True)
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
    package=commands.add_parser('pack-report',help='Report the complete frozen 35-case matrix')
    package.add_argument('manifest',type=Path)
    package.add_argument('--output',type=Path,required=True)


def execute(args):
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
        record=state_contract(args.source,args.case_id)
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
        return single_report(args.root,args.output,getattr(args,'official_outcomes',None))
    if args.fixed35_command=='run':
        from .fixed35_campaign import run_pair
        return run_pair(args.admission,args.output)
    if args.fixed35_command=='sources':
        args.output.mkdir(parents=True,exist_ok=False)
        record=prepare_source_manifest(args.design,args.sources,args.output/'sources.json')
        matrix=applicability_matrix(read_design(args.design))
        atomic_json(args.output/'research-applicability.json',matrix,immutable=True)
        return {'sources':record['source_case_count'],'mapping_cells':len(matrix),
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
