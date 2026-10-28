"""Immutable software objects; never a snapshot of a solve container or user profile."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import posixpath
import re
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

from .storage import atomic_json, file_digest


def descriptor(**identity) -> dict:
    identity = dict(schema_version=1, **identity)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return {"key": key, "identity": identity}


def object_path(cache: Path, desc: dict) -> Path:
    if desc != descriptor(**{k: v for k, v in desc["identity"].items() if k != "schema_version"}):
        raise ValueError("invalid cache identity")
    return cache / desc["key"]


def validate_archive(path: Path, top: str) -> None:
    """Allow internal npm shims; disallow any route outside the one declared tree."""
    names = set()
    with tarfile.open(path) as archive:
        for entry in archive:
            p = PurePosixPath(entry.name)
            if (
                not p.parts
                or p.is_absolute()
                or ".." in p.parts
                or p.parts[0] != top
                or entry.name in names
                or "auth.json" in p.parts
                or not (entry.isdir() or entry.isfile() or entry.issym())
            ):
                raise ValueError("unsafe or private software archive member")
            names.add(entry.name)
            if entry.issym():
                target = posixpath.normpath(posixpath.join(str(p.parent), entry.linkname))
                if entry.linkname.startswith("/") or not target.startswith(top + "/"):
                    raise ValueError("software archive link escapes its tree")
        if not names:
            raise ValueError("empty software archive")


def verify_object(cache: Path, desc: dict) -> dict:
    root = object_path(cache, desc)
    if not root.exists():
        raise ValueError(f"software cache missing: {desc['key']}; run preparation first")
    if root.is_symlink():
        raise ValueError("software cache cannot be a symlink")
    manifest, payload = root / "manifest.json", root / "payload.tar"
    if manifest.is_symlink() or payload.is_symlink():
        raise ValueError("software cache cannot contain redirected objects")
    record = json.loads(manifest.read_text())
    if record.get("identity") != desc["identity"] or record.get("key") != desc["key"]:
        raise ValueError("software cache identity mismatch")
    if record.get("size") != payload.stat().st_size or record.get("sha256") != file_digest(payload):
        raise ValueError("software cache checksum mismatch; explicitly remove corrupt object")
    return dict(record, manifest_sha256=file_digest(manifest))


async def materialize(cache: Path, desc: dict, top: str, builder, *, allow_create: bool):
    root = object_path(cache, desc)
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Sealed objects never change: concurrent Trial readers must not take a writer lock.
    if root.exists():
        return verify_object(cache, desc), True
    if not allow_create:
        raise ValueError(f"software cache missing: {desc['key']}; frozen Trials cannot install")
    with (cache / (desc["key"] + ".lock")).open("a") as lock:
        # A second writer is an error, rather than an unbounded setup wait.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if root.exists():
            return verify_object(cache, desc), True
        with tempfile.TemporaryDirectory(prefix=".build-", dir=cache) as directory:
            stage = Path(directory) / "object"
            stage.mkdir(mode=0o700)
            payload = stage / "payload.tar"
            provenance = await builder(payload)
            validate_archive(payload, top)
            atomic_json(
                stage / "manifest.json",
                dict(
                    **desc,
                    sha256=file_digest(payload),
                    size=payload.stat().st_size,
                    provenance=provenance,
                ),
                immutable=True,
            )
            payload.chmod(0o444)
            (stage / "manifest.json").chmod(0o444)
            os.rename(stage, root)
        return verify_object(cache, desc), False


def node_download(cache: Path, version: str, platform: str) -> tuple[Path, dict]:
    """Exact official binary + HTTPS checksum receipt. Warm hits make no requests."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or platform not in {
        "linux/amd64",
        "linux/arm64",
    }:
        raise ValueError("unsupported Node download identity")
    arch = {"linux/amd64": "x64", "linux/arm64": "arm64"}[platform]
    filename = f"node-v{version}-linux-{arch}.tar.gz"
    directory = cache / "downloads"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path, receipt = directory / filename, directory / (filename + ".json")
    with (directory / (filename + ".lock")).open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if receipt.exists():
            data = json.loads(receipt.read_text())
            if path.is_symlink() or file_digest(path) != data["sha256"]:
                raise ValueError("Node download cache checksum mismatch")
            return path, data
        base = f"https://nodejs.org/dist/v{version}/"
        with urllib.request.urlopen(base + "SHASUMS256.txt", timeout=30) as response:
            checksums = response.read().decode()
        expected = next(
            (line.split()[0] for line in checksums.splitlines() if line.split()[1:] == [filename]),
            None,
        )
        if not expected or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError("official Node checksum missing")
        with tempfile.TemporaryDirectory(prefix=".download-", dir=directory) as temporary:
            staged = Path(temporary) / filename
            with (
                urllib.request.urlopen(base + filename, timeout=30) as response,
                staged.open("wb") as f,
            ):
                while chunk := response.read(1024 * 1024):
                    f.write(chunk)
            if file_digest(staged) != expected:
                raise ValueError("official Node download checksum mismatch")
            os.replace(staged, path)
        data = {"url": base + filename, "checksum_url": base + "SHASUMS256.txt", "sha256": expected}
        atomic_json(receipt, data, immutable=True)
        return path, data


def create_plan(spec, images: dict) -> dict:
    recipe = hashlib.sha256(
        b"".join(
            (Path(__file__).parent / name).read_bytes()
            for name in ("runtime_cache.py", "pi_agent.py")
        )
    ).hexdigest()
    with tarfile.open(spec.subject.package) as package:
        raw = package.extractfile("package/resources/embedding/e5-small.json").read()
        paths = package.extractfile("package/src/storage/paths.ts").read()
    models = descriptor(kind="models", manifest_sha256=hashlib.sha256(raw).hexdigest(),
                        paths_sha256=hashlib.sha256(paths).hexdigest())
    entries = {}
    for name, image in images.items():
        if name.endswith(":verifier"):
            continue
        common = {
            "image": image["id"],
            "platform": image["platform"],
            "node": spec.runtime.node_version,
            "pi": spec.runtime.pi_version,
            "recipe": recipe,
        }
        entries[image["reference"]] = {
            "image": image,
            "base": descriptor(kind="base", **common),
            "addon": descriptor(kind="addon", **common, package=spec.subject.sha256),
            "models": models,
        }
    return {
        "schema_version": 1,
        "cache": str(spec.root / "cache/agent-assets/v1"),
        "entries": entries,
    }


def snapshot(plan: dict) -> dict:
    cache = Path(plan["cache"])
    return {
        desc["key"]: verify_object(cache, desc)
        for entry in plan["entries"].values()
        for desc in (entry["base"], entry["addon"], entry["models"])
    }
