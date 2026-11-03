"""Immutable per-campaign budget and clocks; historical campaigns stay unchanged."""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

from .storage import file_digest


def campaign_config(record):
    """Bind an admission to its own ledger, never to a process-wide default."""
    proof=record.get('campaign')
    if not isinstance(proof,dict) or set(proof)!={'path','sha256'}:
        raise ValueError('a frozen campaign configuration is required')
    path=Path(proof['path'])
    if file_digest(path)!=proof['sha256']:
        raise ValueError('campaign configuration changed')
    config=json.loads(path.read_text())
    if config.get('schema_version')!=1 or not isinstance(config.get('budget_id'),str) or not config['budget_id']:
        raise ValueError('invalid campaign identity')
    clocks=[config.get(k)for k in ('started_at','model_cutoff','judge_cutoff','container_cutoff','hard_deadline')]
    if any(type(v)not in (int,float)or not math.isfinite(v)for v in clocks) or not all(a<b for a,b in itertools.pairwise(clocks)):
        raise ValueError('campaign clocks must be finite and strictly ordered')
    maximum=config.get('maximum_usd');authorized=config.get('authorized_usd')
    if any(type(v)not in (int,float)or not math.isfinite(v)for v in (maximum,authorized)) or not 0<maximum<=authorized<=20:
        raise ValueError('campaign budget exceeds the authorized USD20')
    limits=config.get('arm_limits')
    if not isinstance(limits,dict)or set(limits)!={'pi-native','pi-memweave','preflight'} or any(
            type(v)not in (int,float)or not math.isfinite(v)or v<=0 for v in limits.values()):
        raise ValueError('positive paired and preflight limits required')
    if limits['pi-native']!=limits['pi-memweave']or sum(limits.values())>maximum:
        raise ValueError('unequal arm budgets or overallocated campaign')
    ledger=Path(config['ledger'])
    if ledger.name!='quota.json'or ledger.parent.name!=config['budget_id']:
        raise ValueError('ledger must belong to this independent budget identity')
    return config


def verify_account(config):
    account=json.loads(Path(config['ledger']).read_text())
    if account['maximum_usd']!=config['maximum_usd']or account['arm_limits']!=config['arm_limits']or account['deadline']!=config['judge_cutoff']:
        raise ValueError('campaign ledger budget or deadline mismatch')
    return account
