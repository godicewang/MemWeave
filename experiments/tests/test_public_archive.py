import base64
import hashlib
import io
import json
import tarfile

import pytest

import memweave_eval.public_archive as module


def archive(tmp_path, monkeypatch):
    source = tmp_path / "public.tgz"
    raw = json.dumps({"name": "onnxruntime-node", "version": "1.30.0"}).encode()
    with tarfile.open(source, "w:gz") as t:
        info = tarfile.TarInfo("package/package.json")
        info.size = len(raw)
        t.addfile(info, io.BytesIO(raw))
    data = source.read_bytes()
    expected = dict(module.EXPECTED, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                    integrity="sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode())
    monkeypatch.setattr(module, "EXPECTED", expected)
    return source


def test_import_exact_public_archive_and_reject_tampering(tmp_path, monkeypatch):
    source = archive(tmp_path, monkeypatch)
    path, record = module.public_archive(tmp_path / "cache", source)
    assert path.read_bytes() == source.read_bytes()
    assert record["url"].startswith("https://registry.npmjs.org/")
    assert module.public_archive(tmp_path / "cache")[0] == path
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        module.public_archive(tmp_path / "cache")


def test_failed_import_never_publishes_a_cache_object(tmp_path, monkeypatch):
    source = archive(tmp_path, monkeypatch)
    source.write_bytes(b"wrong public blob")
    with pytest.raises(ValueError, match="integrity"):
        module.public_archive(tmp_path / "cache", source)
    assert not list((tmp_path / "cache").glob("downloads/npm/*/manifest.json"))
