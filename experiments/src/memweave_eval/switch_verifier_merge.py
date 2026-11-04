"""Exact, versioned repair of trusted-base copy, never candidate/test selection."""
from __future__ import annotations

VERSION='fixed35-switch-trusted-merge-20261104-v1'
ORIGINAL='''            shutil.copytree(base, repo, dirs_exist_ok=True, symlinks=True,
                            ignore=shutil.ignore_patterns(".git", "__pycache__"))'''
REPAIRED='''            # fixed35-switch-trusted-merge-20261104-v1: clone already has tracked links.
            def ignore_existing_trusted_links(folder, names):
                folder = Path(folder)
                destination = repo / folder.relative_to(base)
                return [name for name in names if name in {".git", "__pycache__"} or (
                    (folder / name).is_symlink() and (destination / name).is_symlink() and
                    os.readlink(folder / name) == os.readlink(destination / name))]
            shutil.copytree(base, repo, dirs_exist_ok=True, symlinks=True,
                            ignore=ignore_existing_trusted_links)'''


def repair_grader(source:str)->str:
    if source.count(ORIGINAL)!=1 or VERSION in source:
        raise ValueError('exactly one pinned trusted merge statement required')
    return source.replace(ORIGINAL,REPAIRED)
