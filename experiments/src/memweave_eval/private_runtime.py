"""Private GNU loader for musl images; no system-library or global-env replacement."""

from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from .runtime_cache import validate_archive
from .storage import file_digest

GNU_RECIPE = "214780dd31b908ff78644ee5fd1a62fa4f82dd22afcb28f038a47d0998a32823"
BUNDLE_SHA = "17c5fca0aa59dd2ff00c26c95c06dbf922fad1c052bd87b01fc5aee07c283903"
PREFIX = "/opt/memweave-eval/glibc-v1"


@lru_cache(maxsize=256)
def image_libc(image, platform):
    text = subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", "--platform", platform,
         "--cpus", "0.1", "--memory", "64m", "--entrypoint", "sh", image, "-c",
         "cat /etc/os-release 2>/dev/null; ldd --version 2>&1 || true"],
        text=True, timeout=30,
    )
    return "musl" if "musl" in text.lower() or "ID=alpine" in text else "gnu"


def runtime_bundle(cache):
    root = cache / "downloads/gnu-runtime-v1"
    path = root / "bundle.tar"
    if path.is_symlink() or not path.is_file() or file_digest(path) != BUNDLE_SHA:
        raise ValueError("private GNU runtime missing or corrupt; prepare the pinned bundle")
    record = json.loads((root / "manifest.json").read_text())
    if record.get("sha256") != BUNDLE_SHA or record.get("size") != path.stat().st_size:
        raise ValueError("private GNU runtime manifest mismatch")
    validate_archive(path, "glibc")
    return path, record


def node_wrapper():
    shell = (
        '#!/bin/sh\nnode_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        f'exec {PREFIX}/ld-linux-x86-64.so.2 --library-path {PREFIX} '
        '"$node_dir/node.real" --require "$node_dir/compat.cjs" "$@"\n'
    )
    shim = "const p=require('node:path');process.execPath=p.join(__dirname,'node');process.argv[0]=process.execPath;\n"
    return shell, shim


async def activate(agent, environment):
    if getattr(agent, "_private_gnu_active", False):
        return
    source = shlex.quote(agent._asset_root + "/node/glibc")
    await agent.exec_as_root(
        environment,
        f"test ! -e {PREFIX} && mkdir -p /opt/memweave-eval && cp -a {source} {PREFIX}",
    )
    agent._private_gnu_active = True


async def prepare(agent, environment, cache):
    archive, record = runtime_bundle(cache)
    remote = agent._asset_root + "/gnu-runtime.tar"
    await environment.upload_file(archive, remote)
    await agent.exec_as_agent(
        environment,
        f"tar -xf {shlex.quote(remote)} -C {shlex.quote(agent._asset_root + '/node')} "
        f"&& rm {shlex.quote(remote)} && mv {shlex.quote(agent._asset_root + '/node/bin/node')} "
        f"{shlex.quote(agent._asset_root + '/node/bin/node.real')}",
    )
    shell, shim = node_wrapper()
    with tempfile.TemporaryDirectory(prefix="memweave-node-wrapper-") as directory:
        for name, content in (("node", shell), ("compat.cjs", shim)):
            local = Path(directory) / name
            local.write_text(content)
            await environment.upload_file(local, agent._asset_root + "/node/bin/" + name)
    await agent.exec_as_root(
        environment,
        "chmod 755 " + shlex.quote(agent._asset_root + "/node/bin/node")
        + " && chmod 644 " + shlex.quote(agent._asset_root + "/node/bin/compat.cjs"),
    )
    await activate(agent, environment)
    return record
