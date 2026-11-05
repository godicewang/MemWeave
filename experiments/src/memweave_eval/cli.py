from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .report import generate_report
from .runner import run_experiment, verify_package
from .spec import load_experiment, load_yaml


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run and compare frozen public Pi/MemWeave experiments"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run"):
        sub.add_parser(name).add_argument("config", type=Path)
    report = sub.add_parser("report")
    report.add_argument("run_dir", type=Path)
    report.add_argument("--metrics-version", choices=("1", "2"), default="1")
    report.add_argument("--output", type=Path)
    report.add_argument("--contracts", type=Path)
    finance=sub.add_parser('finance-report',help='Write a new financial supplement without changing frozen reports')
    finance.add_argument('run_dir',type=Path)
    finance.add_argument('--output',type=Path,required=True)
    scores=sub.add_parser('score-report',help='Write versioned raw/0–100 scores to a new directory, without model requests')
    scores.add_argument('source',type=Path)
    scores.add_argument('--output',type=Path,required=True)
    review=sub.add_parser('primary-review',help='Re-evaluate frozen primary evidence into a new review directory; no model calls')
    review.add_argument('run_dir',type=Path)
    review.add_argument('--output',type=Path,required=True)
    cases=sub.add_parser('score-cases',help='Score frozen offline cases with deterministic predicates')
    cases.add_argument('gold',type=Path)
    cases.add_argument('evidence',type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command=='primary-review':
            from .primary_report import review_primary_run
            result=review_primary_run(args.run_dir,args.output)
            print(json.dumps({'output':str(args.output),'provenance':result['provenance']},ensure_ascii=False,indent=2))
            return 0
        if args.command=='score-report':
            from .score_report import generate_score_report
            print(json.dumps(generate_score_report(args.source,args.output),ensure_ascii=False,indent=2))
            return 0
        if args.command=='finance-report':
            from .finance_report import generate_finance_supplement
            print(json.dumps(generate_finance_supplement(args.run_dir,args.output),ensure_ascii=False,indent=2))
            return 0
        if args.command=='score-cases':
            from .case_oracles import score_case_suite
            result=score_case_suite(json.loads(args.gold.read_text()),json.loads(args.evidence.read_text()))
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0
        if args.command == "report":
            if args.metrics_version == "2":
                if args.output is None:
                    raise ValueError('v2 requires an explicit new output directory')
                from .supplement_report import generate_supplement
                result = generate_supplement(args.run_dir, args.output, args.contracts)
                print(json.dumps({'output':str(args.output),'provenance':result['provenance'],
                                  'fixture_validation':result['fixture_validation']},ensure_ascii=False,indent=2))
                return 0
            if args.output is not None or args.contracts is not None:
                raise ValueError('separate output/contracts require --metrics-version 2')
            summary = generate_report(args.run_dir.resolve())
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if summary["complete"] else 2
        if load_yaml(args.config).get("schema_version") == 2:
            from .campaign import load_campaign, run_campaign

            spec = load_campaign(args.config)
            if args.command == "validate":
                archive = verify_package(spec.subject.package, spec.subject.sha256)
                print(
                    json.dumps(
                        {
                            "valid": True,
                            "planned_tasks": 1 if spec.phase == "bootstrap" else 49,
                            "model_trials": 2 if spec.phase == "bootstrap" else 98,
                            "package": archive,
                            "requires_preflight": True,
                        },
                        indent=2,
                    )
                )
                return 0
            root = run_campaign(spec)
            print(str(root))
            return 0 if json.loads((root / "summary.json").read_text())["complete"] else 2
        spec, suite, subset = load_experiment(args.config)
        if args.command == "validate":
            archive = verify_package(spec.subject.package, spec.subject.sha256)
            print(
                json.dumps(
                    {
                        "valid": True,
                        "suite": suite.id,
                        "requested_tasks": subset.count,
                        "model_trials": subset.count
                        * len(spec.variants)
                        * spec.execution.repetitions,
                        "package": archive,
                        "requires_preflight": [
                            "official task resolution and controls",
                            "Docker resources and ISA",
                            "network policy",
                            "private authentication",
                        ],
                    },
                    indent=2,
                )
            )
            return 0
        root = run_experiment(spec, suite, subset)
        print(str(root))
        return 0 if json.loads((root / "run.json").read_text())["complete"] else 2
    except (KeyboardInterrupt, TimeoutError) as exc:
        print(f"Experiment stopped: {type(exc).__name__}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 -- CLI boundary must sanitize provider failures.
        # Provider exceptions can contain credentials; report type, not arbitrary bodies.
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            for issue in exc.errors(include_input=False, include_url=False):
                print(f"Invalid config at {issue['loc']}: {issue['msg']}", file=sys.stderr)
        elif isinstance(exc, ValueError):
            print(f"Validation failed: {exc}", file=sys.stderr)
        else:
            print(
                f"Experiment failed ({type(exc).__name__}); see local run evidence.",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
