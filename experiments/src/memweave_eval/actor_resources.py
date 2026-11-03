"""Validate actual Docker actor limits before making credentials available."""
from __future__ import annotations


def verify_actor_limits(host_config,expected):
    if not isinstance(expected,dict)or any(type(expected.get(k))is not int or expected[k]<=0
            for k in ('cpus','memory_mb')):
        raise ValueError('positive frozen actor CPU/memory limits required')
    if not isinstance(host_config,dict)or any(type(host_config.get(k))is not int for k in ('NanoCpus','Memory')):
        raise ValueError('actual Docker actor limits unavailable')
    wanted={'NanoCpus':expected['cpus']*1_000_000_000,'Memory':expected['memory_mb']*1024**2}
    actual={key:host_config[key]for key in wanted}
    if actual!=wanted:raise ValueError('actual actor CPU/memory limits differ from frozen paired policy')
    return {'expected':wanted,'actual':actual,'verified_before_credentials':True}
