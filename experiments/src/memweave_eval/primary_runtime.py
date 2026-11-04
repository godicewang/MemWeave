"""Primary-case orchestration helpers; no provider credential enters Actor."""
from __future__ import annotations

import time
from contextlib import contextmanager

from .budget_guard import initialize
from .storage import atomic_json
from .trusted_broker import TrustedBroker


def actor_image(images):
    candidates=[v for k,v in images.items()if not k.endswith(':verifier')]
    if len(candidates)!=1:raise ValueError('one reviewed primary task required')
    return candidates[0]['reference']


@contextmanager
def free_authority(spec,root,images,env):
    control=root/'private/free-control';initialize(control/'quota.json',29.,time.time()+1800,
        arm_limits={v.id:14.5 for v in spec.variants});(control/'WRITER_PLATFORM').write_text('linux\n')
    episode=root.name+':free-preflight';broker=TrustedBroker(root/'private/free-broker',control,root.name+':free',actor_image(images),env)
    try:
        broker.start('free-fixture-authority-not-a-provider-key',[{'arm':v.id,'episode':episode}for v in spec.variants],fixture=True)
        yield {v.id:broker.clients[(episode,v.id)]for v in spec.variants}
    finally:
        atomic_json(root/'free-authority-cleanup.json',broker.stop(),immutable=True)


def start_paid_authority(spec,root,control,images,env,credential):
    if not spec.evaluation.primary_default:raise ValueError('only reviewed primary paid protocol is enabled')
    formal=root.name;canary=root.name+':canary';principals=[]
    for v in spec.variants:
        task_id=next(k for k in images if not k.endswith(':verifier'))
        arm=(task_id+':'+v.id)if spec.evaluation.per_task_arm_caps else v.id
        principals.append({'arm':arm,'episode':formal})
        if spec.evaluation.canary_preflight:principals.append({'arm':arm,'episode':canary,'request_limit':1})
    atomic_json(control/'phase.json',{'episode':canary if spec.evaluation.canary_preflight else formal})
    broker=TrustedBroker(root/'private/paid-broker',control,root.name,actor_image(images),env)
    return broker.start(credential,principals)


def broker_client(broker,episode,variant,task_id=None):
    arm=task_id+':'+variant if task_id else variant
    return broker.clients[(episode,arm)]


def seal_authority(root,broker):
    result=broker.stop();atomic_json(root/'trusted-authority-cleanup.json',result,immutable=True)
    if not result['stopped']or not result['terminal_available']:raise RuntimeError('trusted authority terminal or stop unconfirmed')
    for name in ('quota.final.json','transport-terminal.json','transport-audit.jsonl'):
        source=broker.control/name;target=root/'trusted'/name;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb')as stream:stream.write(source.read_bytes())
