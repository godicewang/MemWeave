from pathlib import Path

import pytest

from memweave_eval.switch_verifier_merge import ORIGINAL, repair_grader


def apply_merge(base,repo):
    source='import os,shutil\nfrom pathlib import Path\ndef merge(base,repo):\n'+ORIGINAL+'\n'
    namespace={};exec(compile(repair_grader(source),'grader','exec'),namespace)  # noqa: S102 -- fixed evaluator fixture, no external text.
    namespace['merge'](base,repo)


def test_identical_trusted_links_are_preserved_and_missing_files_still_copied(tmp_path):
    base=tmp_path/'base';repo=tmp_path/'repo';base.mkdir();repo.mkdir()
    for root in [base,repo]:
        (root/'docs').mkdir();(root/'docs/icon.png').symlink_to('../missing-icon.png')
    (base/'fixture.so').write_bytes(b'trusted fixture');(base/'other').symlink_to('fixture.so')
    (base/'.git').mkdir();(base/'.git/config').write_text('private base config')
    apply_merge(base,repo)
    assert (repo/'docs/icon.png').readlink()==Path('../missing-icon.png')
    assert (repo/'fixture.so').read_bytes()==b'trusted fixture'
    assert (repo/'other').readlink()==Path('fixture.so')and not(repo/'.git').exists()


def test_conflicting_link_is_not_silently_accepted(tmp_path):
    base=tmp_path/'base';repo=tmp_path/'repo';base.mkdir();repo.mkdir()
    (base/'icon').symlink_to('new');(repo/'icon').symlink_to('different')
    with pytest.raises(Exception,match='File exists'):apply_merge(base,repo)
    assert (repo/'icon').readlink()==Path('different')


@pytest.mark.parametrize('source',['missing source',ORIGINAL+ORIGINAL])
def test_unknown_or_duplicate_source_merge_is_rejected(source):
    with pytest.raises(ValueError,match='exactly one'):repair_grader(source)
