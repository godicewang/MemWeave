"""One pinned public npm tarball, never personal npm configuration or caches."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from .storage import atomic_json

EXPECTED = {
    "name": "onnxruntime-node", "version": "1.30.0",
    "url": "https://registry.npmjs.org/onnxruntime-node/-/onnxruntime-node-1.30.0.tgz",
    "integrity": "sha512-twhs1C2C/BFkz1yc5OY0KIU2GUq6DURO7hD4bx5Q2Qy3nAMJwRXW8xU3NVczE29VA9lolLOYepoD8fjTGOfIqw==",
    "sha256": "6e3390d6b783e7be946fad629292799da28d0b42f84856e50d2c1b0383291e75",
    "size": 113507888,
}


def _verify(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("public archive integrity: missing or redirected file")
    sha256, sha512 = hashlib.sha256(), hashlib.sha512()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            sha256.update(part)
            sha512.update(part)
    integrity = "sha512-" + base64.b64encode(sha512.digest()).decode()
    if (path.stat().st_size != EXPECTED["size"] or sha256.hexdigest() != EXPECTED["sha256"]
            or integrity != EXPECTED["integrity"]):
        raise ValueError("public archive integrity mismatch")
    with tarfile.open(path) as archive:
        package = json.load(archive.extractfile("package/package.json"))
    if package.get("name") != EXPECTED["name"] or package.get("version") != EXPECTED["version"]:
        raise ValueError("public archive package identity mismatch")


def public_archive(cache: Path, source: Path | None = None):
    directory = cache / "downloads/npm"
    root = directory / "onnxruntime-node-1.30.0"

    def read():
        if root.is_symlink():
            raise ValueError("public archive integrity: redirected object")
        record = json.loads((root / "manifest.json").read_text())
        if record != EXPECTED:
            raise ValueError("public archive integrity: descriptor mismatch")
        _verify(root / "archive.tgz")
        return root / "archive.tgz", record

    if root.exists():
        return read()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / ".onnxruntime-node-1.30.0.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if root.exists():
            return read()
        if source is None:
            digest = base64.b64decode(EXPECTED["integrity"].split("-", 1)[1]).hex()
            source = Path.home() / ".npm/_cacache/content-v2/sha512" / digest[:2] / digest[2:4] / digest[4:]
        _verify(source)
        with tempfile.TemporaryDirectory(prefix=".import-", dir=directory) as temporary:
            stage = Path(temporary) / "object"
            stage.mkdir(mode=0o700)
            shutil.copyfile(source, stage / "archive.tgz")
            _verify(stage / "archive.tgz")
            atomic_json(stage / "manifest.json", EXPECTED, immutable=True)
            (stage / "archive.tgz").chmod(0o444)
            (stage / "manifest.json").chmod(0o444)
            os.rename(stage, root)
    return read()
