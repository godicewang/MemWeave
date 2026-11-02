import shutil

import pytest

from memweave_eval.verifier_overlay import copy_overlay


def test_trusted_symlink_overlay_preserves_target_bytes_and_ignores_git(tmp_path):
    base=tmp_path/'base';repo=tmp_path/'repo';base.mkdir();repo.mkdir()
    (base/'asset').write_bytes(b'trusted');(base/'alias').symlink_to('asset')
    (repo/'asset').write_bytes(b'old');(repo/'alias').symlink_to('asset')
    (base/'.git').mkdir();(base/'.git/config').write_text('not copied')
    (repo/'.git').mkdir();(repo/'.git/config').write_text('clone config')
    copy_overlay(base,repo,ignore=shutil.ignore_patterns('.git','__pycache__'))
    assert (repo/'asset').read_bytes()==b'trusted'
    assert (repo/'alias').is_symlink()and (repo/'alias').readlink().as_posix()=='asset'
    assert (repo/'.git/config').read_text()=='clone config'
    copy_overlay(base,repo,ignore=shutil.ignore_patterns('.git','__pycache__'))
    assert (repo/'alias').read_bytes()==b'trusted'


def test_directory_collision_is_not_silently_deleted(tmp_path):
    base=tmp_path/'base';repo=tmp_path/'repo';base.mkdir();repo.mkdir()
    (base/'alias').symlink_to('missing');(repo/'alias').mkdir();(repo/'alias/keep').write_text('keep')
    with pytest.raises(shutil.Error):copy_overlay(base,repo,ignore=shutil.ignore_patterns('.git','__pycache__'))
    assert (repo/'alias/keep').read_text()=='keep'
