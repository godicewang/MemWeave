"""Fixed checkpoint predicates over audited, normalized case evidence.

Only controlled adapters may produce normalized facts/actions. This is not a parser
that declares arbitrary free-form State text semantically correct.
"""

from __future__ import annotations

from .behavior_metrics import evaluate_behavior


def memory_evidence(case: dict, observation: dict) -> dict:
    """Derive assertion booleans, rather than accepting an agent's self-assessment."""
    if observation.get("triggered") is False:
        return {"applicable": False, "reason": "preregistered trigger absent"}
    snapshots = {s["checkpoint"]: s for s in observation.get("snapshots", [])}
    actions = {a["id"]: a for a in observation.get("actions", [])}
    derived = {}
    for predicate in case["predicates"]:
        kind = predicate["kind"]
        snapshot = snapshots.get(predicate.get("checkpoint"))
        action = actions.get(predicate.get("action_id"))
        value = None
        ids = []
        if kind in ("required_facts", "no_active_contradiction", "old_inactive"):
            if snapshot and snapshot.get("complete") is True:
                facts = snapshot.get("facts", [])
                active = [f for f in facts if f.get("active") is True]
                if kind == "required_facts":
                    value = all(
                        any(all(f.get(k) == v for k, v in expected.items()) for f in active)
                        for expected in predicate["facts"]
                    )
                elif kind == "old_inactive":
                    value = not any(f.get("id") in predicate["old_ids"] for f in active)
                else:
                    value = not any(
                        all(f.get(k) == v for k, v in forbidden.items())
                        for f in active
                        for forbidden in predicate["forbidden"]
                    )
                ids = snapshot.get("evidence_ids", [])
        elif kind == "action_fields":
            if action and action.get("complete") is True:
                value = all(action.get(k) == v for k, v in predicate["expected"].items())
                ids = action.get("evidence_ids", [])
            elif action is None and observation.get("actions_complete") is True:
                value = False
                ids = observation.get("action_observation_evidence_ids", [])
        elif kind == "before_boundary":
            first = observation.get(predicate["first"])
            second = observation.get(predicate["second"])
            if type(first) is int and type(second) is int:
                value = first < second
                ids = observation.get("sequence_evidence_ids", [])
        elif kind == "window_evicted":
            source = predicate["source_id"]
            window = observation
            if "checkpoint" in predicate:
                window = next((w for w in observation.get("windows", [])
                               if w.get("checkpoint") == predicate["checkpoint"]
                               and w.get("complete") is True), {})
            visible = window.get("visible_event_ids")
            original = window.get("original_event_ids")
            if isinstance(visible, list) and isinstance(original, list):
                value = source in original and source not in visible
                ids = window.get("evidence_ids", window.get("request_evidence_ids", []))
        elif kind == "clarify_before_action" and observation.get("clarification_complete") is True:
            asked, acted = observation.get("clarify_seq"), observation.get("dependent_seq")
            value = type(asked) is int and (acted is None or asked < acted)
            ids = observation.get("sequence_evidence_ids", [])
        elif kind == "no_clarification" and observation.get("clarifications_complete") is True:
            questions = observation.get("clarifications")
            if isinstance(questions, list):
                value = not questions
                ids = observation.get("clarification_evidence_ids", [])
        elif kind == "network_policy" and observation.get("network_complete") is True:
            events = observation.get("network_events")
            if isinstance(events, list) and all(isinstance(e, dict) and
                    type(e.get("external")) is bool and isinstance(e.get("scope"), str)
                    and isinstance(e.get("phase"), str) for e in events):
                value = not any(e["external"] and e["scope"] == predicate["scope"]
                                and e["phase"] in predicate["forbidden_phases"] for e in events)
                ids = observation.get("network_evidence_ids", [])
        derived[predicate["name"]] = {"value": value, "evidence_ids": ids}
    return derived


def task_evidence(case: dict, observation: dict) -> dict:
    """Controlled artifact projections derive business booleans, not agent self-grades."""
    result = dict(observation)

    def projection(expected, observed):
        if not isinstance(observed, dict) or observed.get("complete") is not True or not observed.get("evidence_ids"):
            return None
        return all(observed.get(k) == v for k, v in expected.items())

    if case["kind"] == "restore":
        if "request_expected" in case:
            result["request_current"] = projection(case["request_expected"], observation.get("request"))
        if "action_expected" in case:
            result["action_passed"] = projection(case["action_expected"], observation.get("first_action"))
    elif case["kind"] == "route":
        if "goal_expected" in case:
            tasks, created = observation.get("created_tasks"), observation.get("created_ids")
            valid = observation.get("created_tasks_complete") is True and isinstance(tasks, list) and isinstance(created, list)
            selected = [t for t in tasks if isinstance(t, dict) and t.get("id") in created] if valid else []
            result["goal_scope_correct"] = (
                all(all(t["goal_fields"].get(k) == v for k, v in case["goal_expected"].items()) for t in selected)
                and {t["id"] for t in selected} == set(created)
                if valid and all(isinstance(t.get("goal_fields"), dict) for t in selected)
                and observation.get("creation_evidence_ids") else None
            )
        if "answer_expected" in case:
            result["answer_passed"] = projection(case["answer_expected"], observation.get("answer"))
        if "protected_expected" in case:
            after = observation.get("protected_after")
            result["protected_unchanged"] = (
                all(after.get(k) == v for k, v in case["protected_expected"].items())
                if observation.get("protected_snapshot_complete") is True and isinstance(after, dict)
                and observation.get("protected_evidence_ids") else None
            )
    return result


def score_case_suite(gold: dict, observations: dict) -> dict:
    cases = []
    evidence = {}
    for case in gold["cases"]:
        if case["kind"] == "memory":
            evidence[case["id"]] = memory_evidence(case, observations.get(case["id"], {}))
            cases.append(
                dict(case, kind="checkpoint", assertions=[p["name"] for p in case["predicates"]])
            )
        else:
            cases.append(case)
            evidence[case["id"]] = task_evidence(case, observations.get(case["id"], {}))
    return evaluate_behavior(dict(gold, cases=cases), evidence)
