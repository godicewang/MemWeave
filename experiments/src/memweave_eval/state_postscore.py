"""Official STATE judges run after Harbor's actor phase, on the same quota authority."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .aux_client import GuardedAuxClient
from .storage import atomic_json, file_digest


def score_state_trial(options,trial:Path,*,scorer=None,judge_factory=None,client_factory=GuardedAuxClient):
    channel=options.get('evaluation_aux_quota_channels',{}).get('official_judge')
    if not channel:raise ValueError('host STATE judge requires a scoped quota channel')
    private=Path(options['state_evaluator_output']).resolve()/trial.name
    original=private/'state-trajectory-original.json'
    if not original.is_file():raise ValueError('original STATE actor trajectory absent')
    output=private/'state-official-scores.json'
    if output.exists():raise ValueError('official STATE output already exists; use a versioned rescore, never overwrite')
    before=file_digest(original)
    trajectory=json.loads(original.read_text())
    if trajectory.get('fixture_only')is True or trajectory.get('metadata',{}).get('fixture_only')is True:
        raise ValueError('fixture-only STATE trajectory cannot be sent to the paid official judge')
    source=Path(options['state_source_path']);domain_name,_=options['state_selector'].split('/',1)
    client=client_factory(ledger=options['evaluation_host_ledger'],trace=private/'official_judge-transport.jsonl',
        evidence=private/'official_judge-content',auth=options['auth_path'],arm=options['variant'],
        case_id=options['evaluation_case_id'],run_id=options['evaluation_run_id']+':judge',
        deadline=options['evaluation_judge_deadline'],role='official_judge',
        max_output=options['evaluation_output_tokens'],episode_budget=.4,quota_channel=channel)
    if scorer is None or judge_factory is None:
        sys.path.insert(0,str(source))
        from state_bench.domain import get_domain_config
        from state_bench.scoring import TaskRequirementsJudge, UXQualityJudge
        from state_bench.scripts.score import score_one
        domain=get_domain_config(domain_name)
        scorer=scorer or score_one
        judge_factory=judge_factory or(lambda c:(TaskRequirementsJudge(c,domain.prompts_dir,domain.judge_system_prompt),
            UXQualityJudge(c,domain.prompts_dir,domain.judge_system_prompt)))
    task_judge,ux_judge=judge_factory(client)
    began=time.monotonic()
    result=scorer(original,source/'state_bench/domains'/domain_name/'tasks',task_judge,ux_judge,output)
    elapsed=time.monotonic()-began
    if file_digest(original)!=before:raise ValueError('official STATE scorer changed the original trajectory')
    status={'official_status':result,'original_sha256':before,'scored_file':str(output),
        'scored_sha256':file_digest(output)if output.exists()else None,
        'phase':'host_after_Harbor_actor','judge_episode':options['evaluation_run_id']+':judge',
        'host_verifier_timing':{'status':'CAPTURED','clock':'monotonic','wall_seconds':elapsed},
        'llm_judge_is_not_programmatic_behavior_score':True}
    atomic_json(private/'state-scoring-status.json',status,immutable=True)
    return status
