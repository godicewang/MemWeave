import json

from memweave_eval.wasm_metrics import wasm_metrics


def gold():
    return {
        "version": "wasm-fixture-v1",
        "protected_hashes": {"src/spec.rs": "ok", "src/main.rs": "ok"},
        "allowed_dependencies": ["serde", "serde_json"],
        "cases": [
            {"id": "wasm-protected-files", "kind": "checkpoint", "assertions": ["unchanged"]},
            {"id": "wasm-dependencies", "kind": "checkpoint", "assertions": ["allowed"]},
            {"id": "wasm-process-validation", "kind": "checkpoint", "assertions": ["tested"]},
            {
                "id": "wasm-early-failure-memory",
                "kind": "checkpoint",
                "assertions": [
                    "evicted",
                    "source_linked_record_before_eviction",
                    "later_manifest_valid",
                ],
            },
        ],
    }


def test_actual_workspace_predicates_and_no_fabricated_memory_coverage(tmp_path):
    snapshots = [
        {
            "event": "workspace_checkpoint",
            "workspace": {
                "files": {"src/spec.rs": "ok", "src/main.rs": "ok"},
                "cargo": '[dependencies]\nserde="1"',
            },
        }
    ]
    (tmp_path / "request-trace.jsonl").write_text("\n".join(map(json.dumps, snapshots)))
    result = wasm_metrics(tmp_path, gold(), enabled=True)
    assert [c["value"] for c in result["cases"][:2]] == [1, 1]
    assert result["cases"][2]["value"] is None
    assert result["cases"][3]["status"] == "not_applicable"
    snapshots[0]["workspace"]["files"]["src/spec.rs"] = "changed"
    snapshots[0]["workspace"]["cargo"] = '[dependencies]\nwasmtime="1"'
    (tmp_path / "request-trace.jsonl").write_text("\n".join(map(json.dumps, snapshots)))
    result = wasm_metrics(tmp_path, gold(), enabled=False)
    assert [c["value"] for c in result["cases"][:2]] == [0, 0]
    assert result["cases"][3]["status"] == "not_applicable"


def test_wasm_reports_join_original_trials_and_frozen_gold(tmp_path):
    from memweave_eval.report import generate_report
    from memweave_eval.storage import atomic_json, evidence_index, file_digest

    plans = []
    jobs = {}
    for variant in ("pi-native", "pi-memweave"):
        name = variant + "-r1"
        plans.append({"task_id": "wasm-simd", "variant_id": variant, "repetition": 1})
        jobs[name] = {"path": "harbor/" + name, "purpose": "solve"}
        trial = tmp_path / "harbor" / name / "trial"
        trial.mkdir(parents=True)
        atomic_json(
            trial / "result.json",
            {
                "task_name": "wasm-simd",
                "trial_name": "trial",
                "verifier_result": {"rewards": {"reward": 0.0}},
                "agent_result": {
                    "n_input_tokens": 100,
                    "n_cache_tokens": 0,
                    "n_output_tokens": 20,
                    "cost_usd": 0.0001,
                },
            },
        )
        agent = trial / "agent"
        agent.mkdir()
        (agent / "request-trace.jsonl").write_text(
            json.dumps(
                {
                    "event": "request_ready",
                    "workspace": {
                        "files": {"src/spec.rs": "ok", "src/main.rs": "ok"},
                        "cargo": '[dependencies]\nserde="1"',
                    },
                }
            )
            + "\n"
        )
    atomic_json(tmp_path / "case-gold.json", gold())
    atomic_json(
        tmp_path / "experiment.lock.json",
        {
            "schema_version": 1,
            "run_id": "fixture",
            "suite": {"id": "swe-marathon", "protocol": "swe-marathon"},
            "plan": plans,
            "evaluation_gold_sha256": file_digest(tmp_path / "case-gold.json"),
        },
    )
    atomic_json(tmp_path / "run.json", {"jobs": jobs})
    atomic_json(tmp_path / "evidence-index.json", {"files": evidence_index(tmp_path)})
    assert generate_report(tmp_path)["complete"]
    rows = json.loads((tmp_path / "reports/results.json").read_text())["trials"]
    assert len(rows) == 2 and rows[0]["behavior_metrics"]["cases"][0]["value"] == 1
    assert rows[0]["engineering_metrics"]["http_attempts"] == 0
    assert "固定行为检查点" in (tmp_path / "reports/report.md").read_text()
    assert "behavior_metrics" in (tmp_path / "reports/trials.csv").read_text()
