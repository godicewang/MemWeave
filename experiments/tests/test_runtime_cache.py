import asyncio
import io
import json
import tarfile

import pytest

from memweave_eval.runtime_cache import (
    descriptor,
    materialize,
    validate_archive,
    verify_object,
)


def archive(path, name="node/bin/node", *, link=None):
    with tarfile.open(path, "w") as stream:
        entry = tarfile.TarInfo(name)
        if link:
            entry.type = tarfile.SYMTYPE
            entry.linkname = link
            stream.addfile(entry)
        else:
            entry.size = 3
            stream.addfile(entry, io.BytesIO(b"abc"))


def test_cache_identity_tracks_abi_versions_and_candidate():
    base = {
        "kind": "base",
        "image": "sha256:one",
        "platform": "linux/amd64",
        "node": "24.22.0",
        "pi": "1.4.0",
        "recipe": "a" * 64,
    }
    key = descriptor(**base)["key"]
    for field in ("image", "platform", "node", "pi", "recipe"):
        assert descriptor(**dict(base, **{field: "changed"}))["key"] != key
    assert (
        descriptor(**dict(base, kind="addon", package="a" * 64))["key"]
        != descriptor(**dict(base, kind="addon", package="b" * 64))["key"]
    )


@pytest.mark.parametrize(
    "name,link",
    [
        ("../escape", None),
        ("/node/file", None),
        ("package/auth.json", None),
        (".pi/agent/settings.json", None),
        ("node/link", "/etc/passwd"),
        ("node/link", "../../escape"),
        ("node/link", "../package/secret"),
    ],
)
def test_archive_rejects_private_paths_and_escaping_links(tmp_path, name, link):
    p = tmp_path / "payload.tar"
    archive(p, name, link=link)
    with pytest.raises(ValueError):
        validate_archive(p, "node")


def test_valid_relative_npm_shim_is_preserved(tmp_path):
    p = tmp_path / "payload.tar"
    archive(p, "node/bin/pi", link="../lib/node_modules/pi/cli.js")
    validate_archive(p, "node")


def test_warm_cache_never_calls_builder_and_corruption_fails_closed(tmp_path):
    desc = descriptor(kind="base", image="one")
    calls = []

    async def build(path):
        calls.append(path)
        archive(path)

    first, hit = asyncio.run(materialize(tmp_path, desc, "node", build, allow_create=True))
    assert not hit
    again, hit = asyncio.run(materialize(tmp_path, desc, "node", build, allow_create=False))
    assert hit and first == again and len(calls) == 1
    assert verify_object(tmp_path, desc) == first
    payload = tmp_path / desc["key"] / "payload.tar"
    payload.chmod(0o644)
    payload.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        asyncio.run(materialize(tmp_path, desc, "node", build, allow_create=True))
    assert len(calls) == 1


def test_partial_failure_is_not_a_cache_hit_or_committed_object(tmp_path):
    desc = descriptor(kind="base", image="one")

    async def fail(path):
        archive(path)
        raise RuntimeError("installation failed")

    with pytest.raises(RuntimeError):
        asyncio.run(materialize(tmp_path, desc, "node", fail, allow_create=True))
    assert not (tmp_path / desc["key"]).exists()
    assert not list(tmp_path.glob(".build-*"))
    with pytest.raises(ValueError, match="missing"):
        asyncio.run(materialize(tmp_path, desc, "node", fail, allow_create=False))


def test_manifest_identity_cannot_silently_select_other_payload(tmp_path):
    desc = descriptor(kind="base", image="one")

    async def build(path):
        archive(path)

    asyncio.run(materialize(tmp_path, desc, "node", build, allow_create=True))
    manifest = tmp_path / desc["key"] / "manifest.json"
    data = json.loads(manifest.read_text())
    data["identity"]["image"] = "two"
    manifest.chmod(0o644)
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="identity"):
        verify_object(tmp_path, desc)


def test_concurrent_warm_readers_do_not_compete_for_writer_lock(tmp_path):
    import fcntl

    desc = descriptor(kind="base", image="shared")

    async def build(path):
        archive(path)

    asyncio.run(materialize(tmp_path, desc, "node", build, allow_create=True))
    with (tmp_path / (desc["key"] + ".lock")).open("a") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert asyncio.run(materialize(tmp_path, desc, "node", build, allow_create=False))[1]


def test_node_download_hit_is_offline_and_validates_bytes(tmp_path):
    from unittest.mock import patch

    from memweave_eval.runtime_cache import node_download
    from memweave_eval.storage import atomic_json, file_digest

    directory = tmp_path / "downloads"
    directory.mkdir()
    path = directory / "node-v24.22.0-linux-x64.tar.gz"
    path.write_bytes(b"fixed node archive")
    atomic_json(path.with_name(path.name + ".json"), {"sha256": file_digest(path)})
    with patch("urllib.request.urlopen", side_effect=AssertionError("must remain offline")):
        assert node_download(tmp_path, "24.22.0", "linux/amd64")[0] == path
        path.write_bytes(b"corruption")
        with pytest.raises(ValueError, match="checksum"):
            node_download(tmp_path, "24.22.0", "linux/amd64")


def test_plan_keeps_native_base_independent_of_candidate_and_excludes_grader(tmp_path):
    from test_runner import package
    from test_spec import configuration

    from memweave_eval.runtime_cache import create_plan
    from memweave_eval.spec import Experiment

    subject = tmp_path / "subject.tgz"
    package(subject, [("package/resources/embedding/e5-small.json", '{"revision":"one"}'),
                      ("package/src/storage/paths.ts", "product paths v1")])
    config = configuration(tmp_path)
    config["subject"]["package"] = str(subject)
    images = {"one": {"reference": "fixed", "id": "sha256:one", "platform": "linux/amd64"},
              "one:verifier": {"reference": "grader", "id": "sha256:two", "platform": "linux/amd64"}}
    first = create_plan(Experiment.model_validate(config), images)
    config["subject"]["sha256"] = "c" * 64
    second = create_plan(Experiment.model_validate(config), images)
    assert set(first["entries"]) == {"fixed"}
    a, b = first["entries"]["fixed"], second["entries"]["fixed"]
    assert a["base"] == b["base"]
    assert a["addon"] != b["addon"]
    assert a["models"] == b["models"]
    package(subject, [("package/resources/embedding/e5-small.json", '{"revision":"one"}'),
                      ("package/src/storage/paths.ts", "product paths v2")])
    assert create_plan(Experiment.model_validate(config), images)["entries"]["fixed"]["models"] != a["models"]


def test_archive_rejects_hard_links_and_duplicate_members(tmp_path):
    p = tmp_path / "payload.tar"
    for duplicate in (False, True):
        with tarfile.open(p, "w") as stream:
            item = tarfile.TarInfo("node/file")
            if duplicate:
                stream.addfile(item)
            else:
                item.type = tarfile.LNKTYPE
                item.linkname = "node/other"
            stream.addfile(item)
        with pytest.raises(ValueError):
            validate_archive(p, "node")
