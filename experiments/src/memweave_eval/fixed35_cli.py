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
    replay=commands.add_parser('replay',help='Verify exact request/tool evidence without model calls')
    replay.add_argument('root',type=Path)
    replay.add_argument('--transport',type=Path,required=True)
    replay.add_argument('--output',type=Path,required=True)


def execute(args):
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
