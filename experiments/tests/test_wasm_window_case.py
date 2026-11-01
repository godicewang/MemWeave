import json

import pytest

from memweave_eval.wasm_metrics import wasm_metrics


@pytest.mark.parametrize(
    "state,changed,evicted,expected",
    [
        (True, False, True, 1),
        (False, False, True, 0),
        (None, False, True, None),
        (True, True, True, 0),
        (True, False, False, None),
    ],
)
def test_actual_request_window_and_later_dependency_are_required(
    tmp_path, state, changed, evicted, expected
):
    gold = {
        "version": "window-v1",
        "protected_hashes": {"src/spec.rs": "good", "src/main.rs": "good"},
        "allowed_dependencies": ["serde"],
        "cases": [
            {
                "id": "wasm-constraint-after-window",
                "kind": "checkpoint",
                "assertions": [
                    "evicted",
                    "state_before_eviction",
                    "state_after_eviction",
                    "post_eviction_protection",
                ],
            }
        ],
    }

    def workspace(runtime="old", protected="good"):
        return {
            "files": {"src/spec.rs": "good", "src/main.rs": protected, "src/runtime.rs": runtime},
            "cargo": '[dependencies]\nserde="1"',
        }

    records = [
        {
            "event": "request_ready",
            "request_kind": "agent",
            "original_instruction_visible": True,
            "state_protected_constraint": True,
            "workspace": workspace(),
        },
        {"event": "case_input"},
        {
            "event": "request_ready",
            "request_kind": "agent",
            "original_instruction_visible": not evicted,
            "state_protected_constraint": state,
            "workspace": workspace(),
        },
        {
            "event": "workspace_checkpoint",
            "phase": "tool_end",
            "workspace": workspace("new", "bad" if changed else "good"),
        },
    ]
    (tmp_path / "request-trace.jsonl").write_text("\n".join(map(json.dumps, records)))
    result = wasm_metrics(tmp_path, gold, enabled=True)["cases"][0]
    assert result["value"] == expected
    if not evicted:
        assert result["status"] == "not_applicable"
