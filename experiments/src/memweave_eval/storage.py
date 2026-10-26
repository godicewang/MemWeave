"""Experiment files only. Product runtime paths are owned by the product package."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


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
    for p in sorted((root / "harbor").rglob("*")):
        if p.is_symlink():
            raise ValueError("evidence contains a symlink")
        if not p.is_file():
            continue
        relative = p.relative_to(root).as_posix()
        if any(part in {"auth.json", ".env", "models.local.json"} for part in p.parts):
            raise ValueError("credential file found in evidence")
        records.append({"path": relative, "sha256": file_digest(p), "size": p.stat().st_size})
    return records
