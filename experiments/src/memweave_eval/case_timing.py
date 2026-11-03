"""Evaluation clocks; no changes to the model or product window budget."""
from __future__ import annotations

import math


def actor_deadline(global_cutoff,episode_started,total_seconds,stage_started,stage_index,stage_budgets):
    values=[global_cutoff,episode_started,total_seconds,stage_started,*stage_budgets]
    if any(type(v)not in (int,float)or not math.isfinite(v)for v in values)or total_seconds<=0:
        raise ValueError('invalid frozen actor clocks')
    if stage_budgets:
        if type(stage_index)is not int or not 1<=stage_index<=len(stage_budgets)or any(v<=0 for v in stage_budgets)or sum(stage_budgets)!=total_seconds:
            raise ValueError('actor stage does not match source budget contract')
        # Harbor budgets each stage separately. Intermediate verification/setup
        # must not consume the next stage's original allowance.
        return min(global_cutoff,stage_started+stage_budgets[stage_index-1])
    return min(global_cutoff,episode_started+total_seconds)
