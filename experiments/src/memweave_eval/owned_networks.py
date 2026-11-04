"""Reclaim only empty Compose networks proved by completed campaign trials.

No daemon settings, address pools, attached networks or global prune operation.
This observer does not alter Actor inputs, artifacts, verifiers or paid requests.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .storage import file_digest


def cleanup_networks(root:Path,*,execute=False,command=None,observe=None):
    root=Path(root).absolute()
    if root.is_symlink()or not root.is_dir():raise ValueError('explicit campaign directory required')
    config=root/'campaign.json'
    if config.is_symlink()or not config.is_file():raise ValueError('campaign identity missing')
    campaign=json.loads(config.read_text())
    if campaign.get('schema_version')!=1 or campaign.get('budget_id')!=root.name:
        raise ValueError('campaign identity differs from cleanup root')
    projects={}
    for path in sorted(root.glob('**/harbor/*/*/result.json')):
        if path.is_symlink()or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('redirected trial result cannot prove ownership')
        trial=json.loads(path.read_text());name=trial.get('trial_name');finished=trial.get('finished_at')
        if not isinstance(name,str)or not re.fullmatch('[A-Za-z0-9_-]+',name)or name!=path.parent.name:
            raise ValueError('trial identity differs from trusted artifact directory')
        if finished is None:continue
        if not isinstance(finished,str):raise TypeError('invalid terminal trial time')
        stamp=datetime.fromisoformat(finished)
        if stamp.tzinfo is None:raise ValueError('terminal time must have a timezone')
        for suffix in ('__env','__verifier__trial'):
            project=name.lower()+suffix
            projects.setdefault(project,{'trial_path':str(path),'trial_sha256':file_digest(path)})
    if command is None:
        def command(args):
            return subprocess.check_output(args,text=True,timeout=30)
    rows=[];removed=0;empty=0
    for project,proof in projects.items():
        ids=command(['docker','network','ls','--filter','label=com.docker.compose.project='+project,
            '--format','{{.ID}}']).splitlines()
        for identity in ids:
            if not re.fullmatch('[a-f0-9]{12,64}',identity):raise ValueError('invalid network identity')
            raw=json.loads(command(['docker','network','inspect',identity]))
            if not isinstance(raw,list)or len(raw)!=1:raise ValueError('unique network proof required')
            net=raw[0];row=dict(proof,project=project,network_id=identity,status='SKIPPED')
            actual=net.get('Id');labels=net.get('Labels');containers=net.get('Containers')
            if not isinstance(actual,str)or not actual.startswith(identity)or not isinstance(labels,dict)or \
                    labels.get('com.docker.compose.project')!=project:
                row['reason']='network ownership mismatch';rows.append(row);continue
            if containers!={}:
                row['reason']='network attached or attachment evidence unavailable';rows.append(row);continue
            empty+=1;row['status']='EMPTY_CANDIDATE'
            if execute:
                check=json.loads(command(['docker','network','inspect',identity]))
                if len(check)!=1 or check[0].get('Id')!=actual or check[0].get('Containers')!={}or \
                        check[0].get('Labels',{}).get('com.docker.compose.project')!=project:
                    row.update(status='SKIPPED',reason='network changed before removal')
                else:
                    if observe:observe(dict(row,status='REMOVE_INTENT'))
                    command(['docker','network','rm',identity]);removed+=1;row['status']='REMOVED'
            rows.append(row)
            if observe:observe(row)
    return {'version':'fixed35-owned-empty-networks-20261104-v1','at':datetime.now(UTC).isoformat(),
        'campaign':str(root),'campaign_sha256':file_digest(config),'execute':execute,
        'completed_projects':len(projects),'empty_candidates':empty,'removed':removed,'rows':rows,
        'real_model_requests':0,'global_network_settings_changed':False}
