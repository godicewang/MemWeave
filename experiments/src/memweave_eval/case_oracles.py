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
        elif kind == "action_fields" and action and action.get("complete") is True:
            value = all(action.get(k) == v for k, v in predicate["expected"].items())
            ids = action.get("evidence_ids", [])
        elif kind == "before_boundary":
            first = observation.get(predicate["first"])
            second = observation.get(predicate["second"])
            if type(first) is int and type(second) is int:
                value = first < second
                ids = observation.get("sequence_evidence_ids", [])
        elif kind == "window_evicted":
            source = predicate["source_id"]
            visible = observation.get("visible_event_ids")
            original = observation.get("original_event_ids")
            if isinstance(visible, list) and isinstance(original, list):
                value = source in original and source not in visible
                ids = observation.get("request_evidence_ids", [])
        elif kind == "clarify_before_action" and observation.get("clarification_complete") is True:
            asked, acted = observation.get("clarify_seq"), observation.get("dependent_seq")
            value = type(asked) is int and (acted is None or asked < acted)
            ids = observation.get("sequence_evidence_ids", [])
        derived[predicate["name"]] = {"value": value, "evidence_ids": ids}
    return derived


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
            evidence[case["id"]] = observations.get(case["id"], {})
    return evaluate_behavior(dict(gold, cases=cases), evidence)
