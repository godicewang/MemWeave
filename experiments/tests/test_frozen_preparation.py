import copy
import time

import pytest
from test_images import LIMITS

pytest_plugins = ["test_images"]
from test_suites import make_task

from memweave_eval import images
from memweave_eval.suites import task_digest


def frozen_task(tmp_path, builder):
    source = make_task(tmp_path / 'original', 'one')
    with (source / 'task.toml').open('a') as stream:
        stream.write('\n[verifier]\nenvironment_mode="separate"\ntimeout_sec=791\n')
    (source / 'tests/Dockerfile').write_text('FROM official-grader\nCOPY . /tests\n')
    record = images.prepare_task(source, tmp_path / 'old', 'linux/amd64', time.monotonic()+60, {}, LIMITS)
    builder.clear()
    return source, record


def test_partial_preparation_reuses_exact_roles_without_build(tmp_path, builder, monkeypatch):
    source, old = frozen_task(tmp_path, builder)
    identities = {x['id']: x for x in old['images'].values()}
    tags = {}
    calls = []

    def inspect(reference, env=None):
        x = identities[tags.get(reference, reference)]
        return {k: reference if k == 'reference' else x[k] for k in ('reference', 'id', 'platform', 'repo_digests')}

    def docker(args, log, timeout, env):
        assert args[:2] == ['docker', 'tag']
        calls.append(args)
        tags[args[3]] = args[2]

    monkeypatch.setattr(images, 'inspect_image', inspect)
    monkeypatch.setattr(images, '_run_docker', docker)
    before = task_digest(source)
    record = images.prepare_task(source, tmp_path / 'new', 'linux/amd64', time.monotonic()+60, {}, LIMITS, frozen=old)
    assert not builder
    assert len(calls) == 2
    assert task_digest(source) == before
    assert {k: v['id'] for k, v in record['images'].items()} == {k: v['id'] for k, v in old['images'].items()}
    assert images.protocol_view(source) == images.protocol_view(tmp_path / 'new' / record['runtime_path'])
    images.verify_prepared_task(tmp_path / 'new', record)


@pytest.mark.parametrize('change', ['source', 'context', 'dockerfile', 'platform', 'missing_role', 'identity'])
def test_changed_frozen_preparation_fails_before_any_tag(tmp_path, builder, monkeypatch, change):
    source, old = frozen_task(tmp_path, builder)
    frozen = copy.deepcopy(old)
    if change == 'source': frozen['source_sha256'] = 'bad'
    if change == 'context': frozen['images']['verifier']['context_sha256'] = 'bad'
    if change == 'dockerfile': frozen['images']['verifier']['dockerfile_sha256'] = 'bad'
    if change == 'platform': frozen['platform'] = 'linux/arm64'
    if change == 'missing_role': frozen['images'].pop('verifier')

    def inspect(reference, env=None):
        x = next(v for v in old['images'].values() if v['id'] == reference)
        return dict(x, id='different' if change == 'identity' else x['id'])

    def forbidden(*args):
        pytest.fail('must validate every frozen role before tag/build')

    monkeypatch.setattr(images, 'inspect_image', inspect)
    monkeypatch.setattr(images, '_run_docker', forbidden)
    with pytest.raises(ValueError, match='frozen'):
        images.prepare_task(source, tmp_path / 'new', 'linux/amd64', time.monotonic()+60, {}, LIMITS, frozen=frozen)
    assert not builder
