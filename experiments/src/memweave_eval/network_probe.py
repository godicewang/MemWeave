"""Credential-free Pro network probes using the already deployed exact Node."""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Annotated

from pydantic import Field, StrictBool

from .spec import StrictModel
from .storage import atomic_json

PROBE_SCRIPT = r"""
import https from 'node:https';
const errors=new Set(['ECONNRESET','ECONNREFUSED','ENOTFOUND','EAI_AGAIN',
 'ETIMEDOUT','ENETUNREACH','EHOSTUNREACH','CONNECT_TIMEOUT','TOTAL_TIMEOUT']);
function probe(url,connectMs,totalMs){return new Promise(resolve=>{
 let done=false,connectTimer,totalTimer,request;
 const finish=value=>{if(done)return;done=true;clearTimeout(connectTimer);
  clearTimeout(totalTimer);resolve(value);};
 const fail=code=>{finish({ok:false,status:null,error:code});request?.destroy();};
 request=https.get(url,{agent:false},response=>{
  finish({ok:true,status:response.statusCode,error:null});response.destroy();
 });
 request.on('error',error=>finish({ok:false,status:null,
  error:errors.has(error.code)?error.code:'NETWORK_ERROR'}));
 connectTimer=setTimeout(()=>fail('CONNECT_TIMEOUT'),connectMs);
 totalTimer=setTimeout(()=>fail('TOTAL_TIMEOUT'),totalMs);
 request.on('socket',socket=>socket.once('secureConnect',()=>clearTimeout(connectTimer)));
});}
const model=await probe('https://api.deepseek.com/models',5000,10000);
const targets=['https://example.com','https://registry.npmjs.org/-/ping',
 'https://www.iana.org/domains/reserved'];
const outside_targets=Object.fromEntries(await Promise.all(
 targets.map(async url=>[url,await probe(url,3000,5000)])));
process.stdout.write(JSON.stringify({model,outside_targets})+'\n');
"""

PUBLIC_TARGETS = frozenset(('https://example.com', 'https://registry.npmjs.org/-/ping',
                            'https://www.iana.org/domains/reserved'))


class Endpoint(StrictModel):
    ok: StrictBool
    status: Annotated[int, Field(strict=True, ge=100, le=599)] | None
    error: Annotated[str, Field(pattern=r"^[A-Z_]+$", max_length=40)] | None


class Checks(StrictModel):
    model: Endpoint
    outside: Endpoint | None = None
    outside_targets: dict[str, Endpoint] | None = None


async def check_network(environment, node: str, logs: Path, *, general_internet_allowed=False):
    attempts = []
    for _ in range(3):
        began = time.monotonic()
        record = await _check_once(environment, node, general_internet_allowed=general_internet_allowed)
        record["elapsed_seconds"] = time.monotonic() - began
        attempts.append(record)
        checks = record.get("checks", {})
        model, outside = checks.get("model", {}), checks.get("outside", {})
        transient={"ECONNRESET", "ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN",
                   "ETIMEDOUT", "ENETUNREACH", "EHOSTUNREACH", "CONNECT_TIMEOUT", "TOTAL_TIMEOUT"}
        model_retry=model.get('ok')is False and model.get('error')in transient
        outside_retry=general_internet_allowed and outside.get('ok')is False and outside.get('error')in transient
        # An unexpectedly reachable forbidden endpoint is a policy violation,
        # never a transient failure to hide with retries.
        forbidden_access=not general_internet_allowed and outside.get('ok')is True
        if record["passed"]or forbidden_access or not(model_retry or outside_retry):
            break
    final = dict(attempts[-1], attempts=attempts)
    atomic_json(logs / "network-probe.json", final)
    if not final["passed"]:
        raise RuntimeError("Declared network/model-endpoint probes failed; see network-probe.json")


async def _check_once(environment, node: str, *, general_internet_allowed=False):
    record = {"passed": False, "credential_free": True,
              "expected_general_internet_allowed":general_internet_allowed}
    try:
        result = await environment.exec(
            command=shlex.quote(node) + " --input-type=module -e " + shlex.quote(PROBE_SCRIPT),
            timeout_sec=30,
        )
        if result.return_code:
            record["execution_return_code"] = result.return_code
            raise ValueError("probe did not execute")
        checks = Checks.model_validate_json(result.stdout)
        if checks.outside_targets is not None:
            if set(checks.outside_targets) != PUBLIC_TARGETS or checks.outside is not None:
                raise ValueError('incomplete or ambiguous public target observations')
            endpoints = list(checks.outside_targets.values())
            reachable = next((endpoint for endpoint in endpoints if endpoint.ok), None)
            outside = reachable or next((endpoint for endpoint in endpoints if endpoint.error in {
                'ECONNRESET', 'ECONNREFUSED', 'ENOTFOUND', 'EAI_AGAIN', 'ETIMEDOUT',
                'ENETUNREACH', 'EHOSTUNREACH', 'CONNECT_TIMEOUT', 'TOTAL_TIMEOUT',
            }), endpoints[0])
            record['probe_version'] = 'fixed-public-targets-v2'
        elif checks.outside is not None:
            # Read legacy fixture/adapter observations explicitly; new probes always
            # report the full fixed set and never fall back after target failures.
            outside = checks.outside
            record['probe_version'] = 'legacy-single-target-v1'
        else:
            raise ValueError('missing public endpoint observations')
        record["checks"] = checks.model_dump(mode="json", exclude_none=True)
        record['checks']['outside'] = outside.model_dump(mode='json')
        record['evidence_scope'] = 'fixed target reachability only; not universal internet policy proof'
        record["passed"] = bool(
            checks.model.ok and checks.model.status in (200, 401) and outside.ok is general_internet_allowed
        )
        record["model_endpoint"] = "reachable" if checks.model.ok else "unreachable"
        record["general_internet"] = "blocked" if not outside.ok else "reachable"
    except Exception as exc:  # noqa: BLE001 -- record only a safe error category.
        record["probe_error_type"] = type(exc).__name__
    return record
