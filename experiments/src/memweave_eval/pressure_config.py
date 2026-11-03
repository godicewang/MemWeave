"""Explicit evaluation-only Recent Window settings; no product defaults change."""
from __future__ import annotations


def window_settings(task_config):
    settings=task_config.get('memory_config')
    if settings is None:return None
    if not isinstance(settings,dict)or set(settings)!={'recent_turns','evict_turns'}:
        raise ValueError('pressure protocol permits only explicit Recent Window N/B')
    n,b=settings['recent_turns'],settings['evict_turns']
    if any(type(v)is not int or v<1 for v in (n,b))or b>n:
        raise ValueError('pressure protocol requires integer 1 <= B <= N')
    return dict(settings)
