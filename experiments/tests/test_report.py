from memweave_eval.report import normalize_trial, summarize


def test_missing_score_and_cost_are_not_zero_or_success():
    row = normalize_trial(
        {
            "task_name": "task",
            "exception_info": {
                "exception_type": "EnvironmentStartError",
                "exception_message": "failed",
            },
        },
        {"task_id": "task", "variant_id": "pi-native", "repetition": 1},
    )
    assert row["success"] is None
    assert row["usage"]["cost_usd"] is None
    assert row["execution_status"] == "infrastructure_error"


def test_partial_patch_score_keeps_agent_error_and_valid_reward():
    raw = {
        "verifier_result": {"rewards": {"reward": 1.0}},
        "exception_info": {"exception_type": "AgentTimeoutError"},
        "agent_result": {
            "n_input_tokens": 100,
            "n_cache_tokens": 60,
            "n_output_tokens": 5,
            "cost_usd": 0.1,
        },
    }
    row = normalize_trial(raw, {"task_id": "task", "variant_id": "pi-native", "repetition": 1})
    assert row["success"] is True
    assert row["error_type"] == "AgentTimeoutError"
    assert row["usage"]["input_tokens"] == 100  # cache already included


def test_native_phase_durations_are_derived_without_guessing_missing_values():
    row = normalize_trial(
        {
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:10Z",
            "agent_execution": {
                "started_at": "2026-01-01T00:00:02Z",
                "finished_at": "2026-01-01T00:00:08Z",
            },
        },
        {"task_id": "x"},
    )
    assert row["elapsed_seconds"] == 10
    assert row["phase_seconds"]["agent_execution"] == 6
    assert row["phase_seconds"]["verifier"] is None


def test_full_denominator_and_pairs_are_preserved():
    rows = []
    for variant, reward in [("pi-native", 0), ("pi-memweave", 1)]:
        rows.append(
            normalize_trial(
                {"verifier_result": {"rewards": {"reward": reward}}},
                {"task_id": "a", "variant_id": variant, "repetition": 1},
            )
        )
        rows.append(normalize_trial(None, {"task_id": "b", "variant_id": variant, "repetition": 1}))
    summary = summarize(rows)
    assert summary["variants"]["pi-memweave"]["planned"] == 2
    assert summary["variants"]["pi-memweave"]["coverage_success_rate"] == 0.5
    assert summary["pairs"]["memweave_only"] == 1
    assert summary["pairs"]["missing"] == 1


def test_nonbinary_or_nonfinite_reward_is_invalid():
    for reward in [0.5, float("nan"), "1", True]:
        row = normalize_trial(
            {"verifier_result": {"rewards": {"reward": reward}}},
            {"task_id": "x", "variant_id": "pi-native", "repetition": 1},
        )
        assert row["success"] is None
        assert row["execution_status"] == "invalid_result"
