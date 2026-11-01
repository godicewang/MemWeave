import json

from memweave_eval.engineering_metrics import task_engineering_metrics


def test_tool_errors_durations_unknown_and_http_are_separate(tmp_path):
    values = [
        {"type": "tool_execution_start", "toolCallId": "a", "toolName": "bash"},
        {
            "type": "tool_execution_end",
            "toolCallId": "a",
            "toolName": "bash",
            "isError": True,
            "durationMs": 10,
            "result": {"content": "EPERM"},
        },
        {"type": "tool_execution_start", "toolCallId": "b", "toolName": "read"},
    ]
    (tmp_path / "pi.txt").write_text("\n".join(map(json.dumps, values)))
    (tmp_path / "request-trace.jsonl").write_text(
        "\n".join(
            map(
                json.dumps,
                [
                    {"event": "request_ready", "state_blocks": [{"version": 1}]},
                    {"event": "http_attempt"},
                    {"event": "http_attempt"},
                    {"event": "request_end", "settled": True},
                ],
            )
        )
    )
    result = task_engineering_metrics(tmp_path)
    assert result["tools"]["bash"]["error_rate"] == 1
    assert result["tools"]["bash"]["duration_ms"]["p95"] == 10
    assert result["tools"]["read"]["error_rate"] is None
    assert result["http_attempts"] == 2 and result["usage_confirmed_attempts"] == 1
    assert result["request_ready_coverage"] == 0.5


def test_historical_missing_transport_is_unknown(tmp_path):
    result = task_engineering_metrics(tmp_path)
    assert result["http_attempts"] is None
    assert result["request_ready_coverage"] is None
