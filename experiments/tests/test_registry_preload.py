import hashlib
import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

MODULE = Path(__file__).parents[1] / 'tools/registry_preload.py'
spec = importlib.util.spec_from_file_location('registry_preload', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def server():
    data = bytes(range(256)) * 4097
    calls = []
    mode = ['valid']

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            start, end = map(int, self.headers['Range'].removeprefix('bytes=').split('-'))
            calls.append((start, end))
            self.send_response(200 if mode[0] == 'ignore' else 206)
            if mode[0] != 'ignore':
                begin = start + (1 if mode[0] == 'wrong' else 0)
                self.send_header('Content-Range', f'bytes {begin}-{end}/{len(data)}')
            body = data[start:end+1]
            if mode[0] == 'corrupt':
                body = bytes([body[0] ^ 1]) + body[1:]
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    host = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=host.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{host.server_port}', data, calls, mode
    host.shutdown()
    thread.join()


def test_parallel_chunks_publish_only_verified_blob_and_reuse(tmp_path, server):
    url, data, calls, _ = server
    digest = 'sha256:' + hashlib.sha256(data).hexdigest()
    result = module.fetch_blob(tmp_path, digest, len(data), lambda: (url, {}), workers=4, chunk_size=65536)
    assert result.read_bytes() == data
    assert sorted(calls) == [(n, min(n+65535, len(data)-1)) for n in range(0, len(data), 65536)]
    count = len(calls)
    assert module.fetch_blob(tmp_path, digest, len(data), lambda: (_ for _ in ()).throw(AssertionError())) == result
    assert len(calls) == count
    result.write_bytes(b'bad cache')
    with pytest.raises(ValueError, match='cached blob'):
        module.fetch_blob(tmp_path, digest, len(data), lambda: (url, {}))


@pytest.mark.parametrize('bad_mode', ['ignore', 'wrong', 'corrupt'])
def test_range_or_integrity_failure_never_publishes(tmp_path, server, bad_mode):
    url, data, _, mode = server
    mode[0] = bad_mode
    digest = 'sha256:' + hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        module.fetch_blob(tmp_path, digest, len(data), lambda: (url, {}), workers=2, chunk_size=131072)
    assert not (tmp_path / 'sha256' / digest.split(':')[1]).exists()


def test_reference_and_digest_are_strict():
    assert module.validate_reference('ghcr.io/scaleapi/swe-bench_pro-v2:public')
    for value in ('http://example.com/x', 'ghcr.io/private/x?token=secret', '../escape'):
        with pytest.raises(ValueError):
            module.validate_reference(value)
    with pytest.raises(ValueError):
        module.digest_hex('sha256:../escape')


def test_oci_archive_preserves_original_verified_blobs(tmp_path):
    import io
    import json
    import tarfile

    layer = b'exact compressed layer bytes'
    config = b'{"os":"linux","architecture":"amd64","rootfs":{"type":"layers","diff_ids":[]}}'
    layer_digest = module.store(tmp_path, layer)
    config_digest = module.store(tmp_path, config)
    manifest = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                           'config': {'digest': config_digest, 'size': len(config)},
                           'layers': [{'digest': layer_digest, 'size': len(layer)}]}).encode()
    manifest_digest = module.store(tmp_path, manifest)
    stream = io.BytesIO()
    module.write_oci(stream, 'ghcr.io/example/public:test', manifest, tmp_path)
    with tarfile.open(fileobj=io.BytesIO(stream.getvalue())) as archive:
        assert len(archive.getmembers()) == 5
        assert all(m.isfile() for m in archive.getmembers())
        for digest, data in ((layer_digest, layer), (config_digest, config), (manifest_digest, manifest)):
            assert archive.extractfile('blobs/sha256/'+digest.split(':')[1]).read() == data
        index = json.load(archive.extractfile('index.json'))
        assert index['manifests'][0]['digest'] == manifest_digest
        assert index['manifests'][0]['annotations']['org.opencontainers.image.ref.name'] == 'ghcr.io/example/public:test'
    (tmp_path/'sha256'/layer_digest.split(':')[1]).write_bytes(b'corruption')
    with pytest.raises(ValueError, match='not verified'):
        module.write_oci(io.BytesIO(), 'ghcr.io/example/public:test', manifest, tmp_path)
