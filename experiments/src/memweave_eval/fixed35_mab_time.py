"""Versioned MAB-only phase caps. Public history/query and coding tasks stay intact."""
from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import toml

from .fixed35_execution import source_stage_budgets
from .storage import file_digest
from .suites import task_digest

VERSION='fixed35-mab-phase-caps-20261104-v1'


def derive_mab_time_policy(source:Path,target:Path,*,ingest_seconds=300,query_seconds=600):
    if any(type(v)is not int or v<1 for v in [ingest_seconds,query_seconds]):
        raise ValueError('positive explicit derived phase caps required')
    config=tomllib.loads((source/'task.toml').read_text());steps=config.get('steps')or[]
    adapter=config.get('metadata',{}).get('derived_adapter','')
    if not adapter.startswith('fixed35-mab-')or not steps or steps[-1].get('name')!='query' \
            or any(not s.get('name','').startswith('ingest-')for s in steps[:-1]):
        raise ValueError('this derived timing policy is only for the MAB history/query adapter')
    if any(p.is_symlink()for p in source.rglob('*')):raise ValueError('redirected source rejected')
    old=source_stage_budgets(source);before=task_digest(source)
    shutil.copytree(source,target)
    for step in steps:step.setdefault('agent',{})['timeout_sec']=query_seconds if step['name']=='query'else ingest_seconds
    config['agent']['timeout_sec']=ingest_seconds
    config['metadata']['derived_time_policy']=VERSION
    (target/'task.toml').write_text(toml.dumps(config))
    original={str(p.relative_to(source)):file_digest(p)for p in source.rglob('*')if p.is_file()and p.name!='task.toml'}
    copied={str(p.relative_to(target)):file_digest(p)for p in target.rglob('*')if p.is_file()and p.name!='task.toml'}
    assert original==copied and task_digest(source)==before
    return {'version':VERSION,'source_task_sha256':before,'task_sha256':task_digest(target),
        'old_stage_upper_bounds':old,'new_stage_upper_bounds':source_stage_budgets(target),
        'source_content_unchanged':True,'changes':['task.toml phase caps','common explicit frozen-budget notice'],
        'not_an_official_mab_agent_time_limit':True,'same_policy_both_variants':True}
