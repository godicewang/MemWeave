"""Preserve trusted base symlinks when overlaying a clone's prebuilt fixtures."""
from __future__ import annotations

import shutil
from pathlib import Path


def copy_overlay(base:Path,repo:Path,*,ignore):
    # copytree(dirs_exist_ok=True, symlinks=True) cannot replace an already-cloned
    # symlink. Remove only the corresponding destination link/file, then copy the
    # exact trusted base entry. Do not follow or normalize link targets.
    for source in base.rglob('*'):
        relative=source.relative_to(base)
        if any(part in {'.git','__pycache__'}for part in relative.parts):continue
        if source.is_symlink():
            target=repo/relative
            if target.is_symlink()or target.is_file():target.unlink()
    shutil.copytree(base,repo,dirs_exist_ok=True,symlinks=True,ignore=ignore)
