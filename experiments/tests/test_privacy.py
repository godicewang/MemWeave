import io
import tarfile

import pytest

from memweave_eval.storage import check_private_evidence


def test_credentials_block_indexing_raw_and_compressed_evidence(tmp_path):
    token = b"private-test-key-1234567890"
    p = tmp_path / "session.jsonl"
    p.write_bytes(b"text " + token)
    with pytest.raises(ValueError, match="credential"):
        check_private_evidence(tmp_path, token)
    p.unlink()
    p = tmp_path / "memory.tar.gz"
    with tarfile.open(p, "w:gz") as archive:
        item = tarfile.TarInfo("memory/state.json")
        item.size = len(token)
        archive.addfile(item, io.BytesIO(token))
    with pytest.raises(ValueError, match="credential"):
        check_private_evidence(tmp_path, token)
