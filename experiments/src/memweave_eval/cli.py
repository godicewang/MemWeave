"""Offline validation of preserved environment inputs; legacy evaluators are retired."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .runner import verify_package
from .spec import load_experiment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Validate preserved benchmark environment inputs')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('validate').add_argument('config', type=Path)
    args = parser.parse_args(argv)
    try:
        spec, suite, subset = load_experiment(args.config)
        archive = verify_package(spec.subject.package, spec.subject.sha256)
        print(json.dumps({'valid': True, 'suite': suite.id, 'requested_tasks': subset.count,
                          'package': archive, 'execution_enabled': False}, indent=2))
        return 0
    except ValidationError as exc:
        for issue in exc.errors(include_input=False, include_url=False):
            print(f"Invalid config at {issue['loc']}: {issue['msg']}", file=sys.stderr)
    except ValueError as exc:
        print(f'Validation failed: {exc}', file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 -- sanitize potentially sensitive file/provider bodies.
        print(f'Validation failed ({type(exc).__name__})', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
