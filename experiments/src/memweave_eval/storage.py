"""Experiment files only. Product runtime paths are owned by the product package."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value, *, immutable=False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            os.link(temporary, path)  # atomic create-if-absent, never replace evidence
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def contained(root: Path, relative: str) -> Path:
    p = root / relative
    if Path(relative).is_absolute() or root.resolve() not in p.resolve().parents:
        raise ValueError("evidence path escapes its run directory")
    current = p
    while current != root:
        if current.is_symlink():
            raise ValueError("evidence symlinks are forbidden")
        current = current.parent
    return p


def evidence_index(root: Path) -> list[dict]:
    records = []
    candidates = [p for name in ("harbor", "preparation", "runtime-tasks")
                  for p in (root / name).rglob("*")]
    if (root / "admission.json").exists():
        candidates.append(root / "admission.json")
    for p in sorted(candidates):
        if p.is_symlink():
            raise ValueError("evidence contains a symlink")
        if not p.is_file():
            continue
        relative = p.relative_to(root).as_posix()
        if any(part in {"auth.json", ".env", "models.local.json"} for part in p.parts):
            raise ValueError("credential file found in evidence")
        records.append({"path": relative, "sha256": file_digest(p), "size": p.stat().st_size})
    return records


def check_private_evidence(root: Path, credential: bytes) -> None:
    """Fail closed before indexing; never rewrite original logs to conceal a leak."""

    def check(stream):
        previous = b""
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            data = previous + chunk
            if credential in data:
                raise ValueError("credential detected in private evidence; indexing stopped")
            previous = data[-len(credential) :]

    if not credential:
        raise ValueError("empty credential cannot be used for evidence privacy validation")
    for p in root.rglob("*"):
        if p.is_symlink():
            raise ValueError("symlink found in private evidence")
        if not p.is_file():
            continue
        with p.open("rb") as stream:
            check(stream)
        if p.name == "memory.tar.gz":
            with tarfile.open(p, "r:gz") as archive:
                for item in archive:
                    relative = PurePosixPath(item.name)
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or not (item.isfile() or item.isdir())
                    ):
                        raise ValueError("unsafe memory evidence archive")
                    if item.isfile():
                        check(archive.extractfile(item))
