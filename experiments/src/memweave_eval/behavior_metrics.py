"""Versioned, deterministic opportunity scoring; no LLM judge or text similarity."""

from __future__ import annotations

from collections import defaultdict


def evaluate_behavior(gold: dict, evidence: dict) -> dict:
    totals = defaultdict(
        lambda: {"numerator": 0, "denominator": 0, "unknown": 0, "not_applicable": 0}
    )
    results = []

    def add(name, value, *, weight=1):
        metric = totals[name]
        if value is None:
            metric["unknown"] += 1
        else:
            metric["numerator"] += float(value) * weight
            metric["denominator"] += weight

    identities = set()
    for case in gold["cases"]:
        identity = case["id"]
        if identity in identities:
            raise ValueError("duplicate gold opportunity")
        identities.add(identity)
        obs = evidence.get(identity, {})
        kind = case["kind"]
        checks = {}
        if obs.get("applicable") is False:
            names = (
                case.get("assertions", [])
                if kind == "checkpoint"
                else ["hit_at_k", "recall_at_k", "best_top1", "top1_given_best_hit"]
                if kind == "retrieval"
                else ["restore_end_to_end", "restore_after_binding"]
                if kind == "restore"
                else ["route_correct"]
            )
            for name in names:
                totals[name]["not_applicable"] += 1
            results.append(
                {
                    "case_id": identity,
                    "kind": kind,
                    "value": None,
                    "status": "not_applicable",
                    "checks": {},
                    "reason": obs.get("reason") or "preregistered trigger absent",
                }
            )
            continue
        if kind == "retrieval":
            k = case["k"]
            relevant, best = set(case["relevant"]), set(case["best"])
            if not relevant or not best or not best <= relevant or type(k) is not int or k < 1:
                raise ValueError("invalid retrieval gold")
            failed=obs.get('query_failed')is True
            if obs.get('complete')is True and not failed and type(obs.get('limit'))is int and 0<obs['limit']<k:
                for name in ['hit_at_k','recall_at_k','best_top1','top1_given_best_hit']:
                    totals[name]['not_applicable']+=1
                results.append({'case_id':identity,'kind':kind,'value':None,'status':'not_applicable','checks':{},
                    'reason':'effective search limit below frozen K; ranking is unobserved, not a collection loss'})
                continue
            known = (
                obs.get("complete") is True
                and (failed or type(obs.get("limit")) is int and obs["limit"] >= k)
                and isinstance(obs.get("candidates"), list)
            )
            candidates = list(dict.fromkeys(obs.get("candidates", [])))[:k] if known and not failed else []
            hit = bool(relevant.intersection(candidates))
            best_hit = bool(best.intersection(candidates))
            checks = {
                "hit_at_k": int(hit) if known else None,
                "recall_at_k": len(relevant.intersection(candidates)) / len(relevant)
                if known
                else None,
                "best_top1": int(bool(candidates) and candidates[0] in best) if known else None,
            }
            for name, value in checks.items():
                add(name, value)
            if known and best_hit:
                add("top1_given_best_hit", checks["best_top1"])
            elif not known:
                add("top1_given_best_hit", None)
            else:
                totals["top1_given_best_hit"]["not_applicable"] += 1
        elif kind == "restore":
            known = obs.get("complete") is True and "bound" in obs
            bound = obs.get("bound") in case["targets"]
            values = [bound, obs.get("request_current"), obs.get("action_passed")]
            value = False if known and any(v is False for v in values) else all(values) if known and all(type(v) is bool for v in values) else None
            add("restore_end_to_end", value)
            if known and bound:
                add("restore_after_binding", value)
            else:
                totals["restore_after_binding"]["not_applicable"] += 1
            checks = {"restore_end_to_end": value}
        elif kind == "route":
            known = obs.get("complete") is True
            creation_known = known and isinstance(obs.get("created_ids"), list)
            created = set(obs["created_ids"]) if creation_known else set()
            route_correct = (
                obs.get("route") in case["allowed"] if known and "route" in obs else None
            )
            required=case.get('required_route_checks',[])
            if not isinstance(required,list)or any(not isinstance(n,str)or not n for n in required) \
                or len(set(required))!=len(required):raise ValueError('invalid required route checks')
            values=[route_correct]
            for name in required:
                program=obs.get('program_route_checks');check=program.get(name,{})if isinstance(program,dict)else{}
                refs=check.get('evidence_ids')if isinstance(check,dict)else None
                value=check.get('passed')if isinstance(check,dict)and type(check.get('passed'))is bool \
                    and isinstance(refs,list)and refs and all(isinstance(ref,str)and ref for ref in refs)else None
                checks['route_program:'+name]=value;values.append(value)
            route_correct=False if False in values else True if all(v is True for v in values)else None
            checks["route_correct"] = route_correct
            add("route_correct", route_correct)
            if creation_known and created:
                correct = (
                    route_correct and len(created) == 1 and obs.get("goal_scope_correct") is True
                )
                correct = (False if route_correct is False or len(created)!=1 else
                    correct if type(obs.get("goal_scope_correct")) is bool else None)
                add("create_precision", correct)
                checks["correct_persistent_creation"] = correct
                add("extra_created_objects", len(created) - 1)
            elif not creation_known:
                add("create_precision", None)
                checks["persistent_creation_observed"] = None
            else:
                totals["create_precision"]["not_applicable"] += 1
            if case.get("must_create"):
                value = (
                    (
                        route_correct
                        and len(created) == 1
                        and obs.get("bound") in created
                        and obs.get("goal_scope_correct") is True
                        and obs.get("before_deadline") is True
                    )
                    if creation_known
                    and "bound" in obs
                    and all(
                        type(obs.get(key)) is bool
                        for key in ("goal_scope_correct", "before_deadline")
                    )
                    else None
                )
                if creation_known and len(created) != 1:
                    value = False
                checks["create_recall"] = value
                add(
                    "create_recall",
                    value,
                )
            if case.get("simple"):
                required = [obs.get("answer_passed"), obs.get("protected_unchanged")]
                if case.get('return_opportunity_id'):
                    required.append(obs.get('return_action_passed'))
                simple = (
                    (not created and all(required))
                    if creation_known and all(type(v) is bool for v in required)
                    else None
                )
                if creation_known and created:
                    simple = False
                add("simple_no_create_and_complete", simple)
                checks["simple_no_create_and_complete"] = simple
                if case.get('return_opportunity_id'):checks['return_after_detour']=obs.get('return_action_passed')
                attempts = obs.get("create_attempts")
                add(
                    "unnecessary_create_attempt",
                    attempts > 0 if known and type(attempts) is int else None,
                )
            if case.get("should_restore"):
                add("old_goal_duplicate_creation", bool(created) if creation_known else None)
                checks["no_old_goal_duplicate"] = not bool(created) if creation_known else None
            if case.get("same_goal"):
                add("within_task_false_split", bool(created) if creation_known else None)
                checks["no_within_task_split"] = not bool(created) if creation_known else None
        elif kind == "checkpoint":
            for assertion in case["assertions"]:
                item = obs.get(assertion, {})
                value = item.get("value")
                checks[assertion] = (
                    value if type(value) is bool and item.get("evidence_ids") else None
                )
                add(assertion, checks[assertion])
        else:
            raise ValueError("unknown gold case kind")
        value = (
            0
            if any(v is not None and v != 1 for v in checks.values())
            else (1 if checks and all(v is not None for v in checks.values()) else None)
        )
        results.append(
            {
                "case_id": identity,
                "kind": kind,
                "value": value,
                "status": "unknown" if value is None else "scored",
                "checks": checks,
                "reason": (obs.get("reason") or "required evidence missing")
                if value is None
                else None,
            }
        )
    return {
        "gold_version": gold["version"],
        "cases": results,
        "metrics": {
            key: dict(
                value,
                value=value["numerator"] / value["denominator"] if value["denominator"] else None,
            )
            for key, value in sorted(totals.items())
        },
    }
