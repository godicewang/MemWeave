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
const outside=await probe('https://example.com',3000,5000);
process.stdout.write(JSON.stringify({model,outside})+'\n');
"""


class Endpoint(StrictModel):
    ok: StrictBool
    status: Annotated[int, Field(strict=True, ge=100, le=599)] | None
    error: Annotated[str, Field(pattern=r"^[A-Z_]+$", max_length=40)] | None


class Checks(StrictModel):
    model: Endpoint
    outside: Endpoint


async def check_network(environment, node: str, logs: Path):
    attempts = []
    for _ in range(3):
        began = time.monotonic()
        record = await _check_once(environment, node)
        record["elapsed_seconds"] = time.monotonic() - began
        attempts.append(record)
        checks = record.get("checks", {})
        model, outside = checks.get("model", {}), checks.get("outside", {})
        if (record["passed"] or model.get("ok") is not False
                or model.get("error") not in {
                    "ECONNRESET", "ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN",
                    "ETIMEDOUT", "ENETUNREACH", "EHOSTUNREACH",
                    "CONNECT_TIMEOUT", "TOTAL_TIMEOUT",
                } or outside.get("ok") is not False):
            break
    final = dict(attempts[-1], attempts=attempts)
    atomic_json(logs / "network-probe.json", final)
    if not final["passed"]:
        raise RuntimeError("Pro offline/model-endpoint network probes failed; see network-probe.json")


async def _check_once(environment, node: str):
    record = {"passed": False, "credential_free": True}
    try:
        result = await environment.exec(
            command=shlex.quote(node) + " --input-type=module -e " + shlex.quote(PROBE_SCRIPT),
            timeout_sec=30,
        )
        if result.return_code:
            record["execution_return_code"] = result.return_code
            raise ValueError("probe did not execute")
        checks = Checks.model_validate_json(result.stdout)
        record["checks"] = checks.model_dump(mode="json")
        record["passed"] = bool(
            checks.model.ok and checks.model.status in (200, 401) and not checks.outside.ok
        )
        record["model_endpoint"] = "reachable" if checks.model.ok else "unreachable"
        record["general_internet"] = "blocked" if not checks.outside.ok else "reachable"
    except Exception as exc:  # noqa: BLE001 -- record only a safe error category.
        record["probe_error_type"] = type(exc).__name__
    return record
