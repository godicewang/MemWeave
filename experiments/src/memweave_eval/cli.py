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
    sub.add_parser("report").add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
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
                            "planned_tasks": 49,
                            "model_trials": 98,
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
