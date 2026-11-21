"""Restore bounded public connection checks without changing the pilot probe."""

import json

from .network_probe import PUBLIC_TARGETS
from .storage import atomic_json

_ERROR = "pilot network/credential-isolation probe failed"
_TRANSIENT = frozenset(("ECONNRESET", "ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN",
                        "ETIMEDOUT", "ENETUNREACH", "EHOSTUNREACH",
                        "CONNECT_TIMEOUT", "TOTAL_TIMEOUT"))


def _retryable(record):
    checks = record.get("checks", {})
    model = checks.get("model", {})
    outside = checks.get("outside_targets", {})
    return (
        record.get("passed") is False
        and record.get("credential_free") is True
        and record.get("expected_general_internet_allowed") is True
        and model.get("ok") is True and model.get("status") == 401
        and model.get("capability_rejected") is True
        and set(outside) == PUBLIC_TARGETS
        and all(endpoint.get("ok") is False and endpoint.get("status") is None
                and endpoint.get("error") in _TRANSIENT for endpoint in outside.values())
    )


async def retry_pilot_preflight(probe, environment, node, logs, **options):
    """Keep separate original records; retry only proven public transport faults."""
    canonical = logs / "network-probe.json"
    if canonical.exists() or canonical.is_symlink():
        raise FileExistsError("trial already contains a network probe")
    for index in range(1, 4):
        attempt = logs / "network-preflight" / str(index)
        attempt.mkdir(parents=True, exist_ok=False, mode=0o700)
        failure = None
        try:
            await probe(environment, node, attempt, **options)
        except RuntimeError as error:
            if str(error) != _ERROR:
                raise
            failure = error
        record = json.loads((attempt / "network-probe.json").read_bytes())
        if not isinstance(record, dict) or record.get("passed") is not (failure is None):
            raise ValueError("inconsistent original network probe")
        if (failure is not None and index < 3
                and options.get("general_internet_allowed") is True and _retryable(record)):
            continue
        atomic_json(canonical, record, immutable=True)
        if failure is not None:
            raise failure
        return
