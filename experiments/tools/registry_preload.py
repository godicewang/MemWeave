"""Verified, preparation-only public GHCR blob prefetch; never runs an Agent."""
from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ACCEPT = ('application/vnd.oci.image.index.v1+json, '
          'application/vnd.oci.image.manifest.v1+json, '
          'application/vnd.docker.distribution.manifest.list.v2+json, '
          'application/vnd.docker.distribution.manifest.v2+json')


class PreparationError(ValueError):
    """Only fixed, credential-free diagnostics may cross the CLI boundary."""


def digest_hex(value):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
        raise PreparationError('invalid SHA256 descriptor')
    return value.split(':')[1]


def validate_reference(value):
    if not re.fullmatch(r'ghcr\.io/[a-z0-9._/-]+(?::[A-Za-z0-9_.-]+|@sha256:[0-9a-f]{64})', value):
        raise PreparationError('only canonical public GHCR references are supported')
    if '..' in value.split('/') or '?' in value:
        raise PreparationError('invalid registry reference')
    return value


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(1024 * 1024):
            result.update(data)
    return result.hexdigest()


def fetch_blob(cache, digest, size, resolve, *, workers=32, chunk_size=4194304, progress=None):
    name = digest_hex(digest)
    if type(size) is not int or size < 0 or not 1 <= workers <= 32 or chunk_size < 1:
        raise PreparationError('invalid blob preparation limits')
    directory = cache / 'sha256'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if target.is_symlink():
        raise PreparationError('cached blob cannot be a symlink')
    with (directory / (name + '.lock')).open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        if target.exists():
            if target.stat().st_size != size or sha(target) != name:
                raise PreparationError('cached blob checksum or size mismatch')
            return target
        parts = directory / (name + '.parts')
        parts.mkdir(exist_ok=True)
        spans = [(n, min(size-1, n+chunk_size-1)) for n in range(0, size, chunk_size)]

        stopped = threading.Event()

        def chunk(span):
            if stopped.is_set():
                raise PreparationError('preparation cancelled after another range failed')
            start, end = span
            path = parts / f'{start:016d}.part'
            if path.is_symlink():
                raise PreparationError('part cannot be a symlink')
            if path.is_file() and path.stat().st_size == end-start+1:
                return path
            for attempt in range(3):
                temp = path.with_suffix('.tmp')
                try:
                    url, headers = resolve()
                    request = urllib.request.Request(url, headers=dict(headers, Range=f'bytes={start}-{end}',
                                                                      **{'Accept-Encoding': 'identity'}))
                    began = time.monotonic()
                    with urllib.request.urlopen(request, timeout=30) as response, temp.open('wb') as out:
                        expected = f'bytes {start}-{end}/{size}'
                        if response.status != 206 or response.headers.get('Content-Range') != expected:
                            raise PreparationError('server did not honor exact Range')
                        count = 0
                        while data := response.read1(min(65536, end-start+2-count)):
                            count += len(data)
                            if stopped.is_set() or count > end-start+1 or time.monotonic()-began > 120:
                                raise PreparationError('range body exceeds size or wall limit')
                            out.write(data)
                        if count != end-start+1:
                            raise PreparationError('truncated range body')
                    os.replace(temp, path)
                    return path
                except (urllib.error.URLError, TimeoutError, OSError):
                    temp.unlink(missing_ok=True)
                    if hasattr(resolve, 'invalidate'):
                        resolve.invalidate()
                    if attempt == 2:
                        raise PreparationError('range transport failed after three attempts') from None
                    time.sleep(attempt+1)
                except BaseException:
                    temp.unlink(missing_ok=True)
                    raise

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(chunk, span) for span in spans]
            done = 0
            try:
                for future in concurrent.futures.as_completed(futures):
                    path = future.result()
                    done += path.stat().st_size
                    if progress:
                        progress(done, size)
            except BaseException:
                stopped.set()
                for future in futures:
                    future.cancel()
                raise
        temp = directory / (name + '.tmp')
        checksum = hashlib.sha256()
        with temp.open('wb') as out:
            for start, _ in spans:
                with (parts / f'{start:016d}.part').open('rb') as source:
                    while data := source.read(1024*1024):
                        out.write(data)
                        checksum.update(data)
        if temp.stat().st_size != size or checksum.hexdigest() != name:
            temp.unlink(missing_ok=True)
            for part in parts.iterdir():
                part.unlink()
            raise PreparationError('complete blob SHA256 mismatch')
        os.replace(temp, target)
        for part in parts.iterdir():
            part.unlink()
        parts.rmdir()
        return target


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class Registry:
    def __init__(self, reference):
        validate_reference(reference)
        self.reference = reference
        value = reference.removeprefix('ghcr.io/')
        self.repository, self.tag = value.rsplit('@', 1) if '@' in value else value.rsplit(':', 1)
        self.lock = threading.Lock()
        self._token, self._token_at = '', 0

    def auth(self):
        with self.lock:
            if not self._token or time.monotonic()-self._token_at > 240:
                query = urllib.parse.urlencode({'service': 'ghcr.io', 'scope': 'repository:'+self.repository+':pull'})
                with urllib.request.urlopen('https://ghcr.io/token?'+query, timeout=30) as response:
                    self._token = json.loads(response.read(131072))['token']
                self._token_at = time.monotonic()
            return {'Authorization': 'Bearer '+self._token}

    def manifest(self, reference):
        request = urllib.request.Request('https://ghcr.io/v2/'+self.repository+'/manifests/'+reference,
                                         headers=dict(self.auth(), Accept=ACCEPT))
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(4*1024*1024+1)
            if len(raw) > 4*1024*1024:
                raise PreparationError('manifest too large')
            digest = 'sha256:'+hashlib.sha256(raw).hexdigest()
            expected = response.headers.get('Docker-Content-Digest', digest)
            if digest != expected or (reference.startswith('sha256:') and reference != digest):
                raise PreparationError('manifest digest mismatch')
        return raw, digest

    def resolver(self, digest):
        registry = self
        class Resolver:
            def __init__(self):
                self.lock, self.current, self.expires = threading.Lock(), None, 0

            def invalidate(self):
                with self.lock:
                    self.expires = 0

            def __call__(self):
                with self.lock:
                    if time.monotonic() < self.expires:
                        return self.current
                    url = 'https://ghcr.io/v2/'+registry.repository+'/blobs/'+digest
                    headers = registry.auth()
                    request = urllib.request.Request(url, headers=headers, method='HEAD')
                    try:
                        with urllib.request.build_opener(NoRedirect).open(request, timeout=30):
                            pass
                    except urllib.error.HTTPError as error:
                        if error.code not in (301, 302, 303, 307, 308):
                            raise
                        url = urllib.parse.urljoin(url, error.headers['Location'])
                        if urllib.parse.urlparse(url).scheme != 'https':
                            raise PreparationError('insecure blob redirect') from None
                        headers = {}  # Never forward registry authorization to another host.
                    self.current, self.expires = (url, headers), time.monotonic()+600
                    return self.current
        return Resolver()


def store(cache, data):
    name = hashlib.sha256(data).hexdigest()
    path = cache / 'sha256' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise PreparationError('cached metadata cannot be a symlink')
    if path.exists() and path.read_bytes() != data:
        raise PreparationError('cached metadata corrupt')
    if not path.exists():
        temp = path.with_suffix('.tmp')
        temp.write_bytes(data)
        os.replace(temp, path)
    return 'sha256:'+name


def write_oci(stream, reference, manifest, cache):
    document = json.loads(manifest)
    digest = 'sha256:'+hashlib.sha256(manifest).hexdigest()
    descriptor = {'mediaType': document['mediaType'], 'digest': digest, 'size': len(manifest),
                  'platform': {'os': 'linux', 'architecture': 'amd64'},
                  'annotations': {'org.opencontainers.image.ref.name': reference,
                                  'io.containerd.image.name': reference}}
    index = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
             'manifests': [descriptor]}
    values = {'oci-layout': b'{"imageLayoutVersion":"1.0.0"}', 'index.json': json.dumps(index).encode()}
    blobs = {digest: len(manifest), document['config']['digest']: document['config']['size']}
    blobs.update({row['digest']: row['size'] for row in document['layers']})
    with tarfile.open(fileobj=stream, mode='w|') as archive:
        for name, data in values.items():
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
        for digest, size in blobs.items():
            name = digest_hex(digest)
            path = cache / 'sha256' / name
            if path.stat().st_size != size or sha(path) != name:
                raise PreparationError('OCI export blob not verified')
            info = tarfile.TarInfo('blobs/sha256/'+name); info.size = size; info.mode = 0o644
            with path.open('rb') as source:
                archive.addfile(info, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference')
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=32)
    parser.add_argument('--load', action='store_true')
    args = parser.parse_args()
    registry = Registry(args.reference)
    args.evidence.mkdir(parents=True, exist_ok=True)
    raw, root_digest = registry.manifest(registry.tag)
    store(args.cache, raw)
    doc = json.loads(raw)
    if 'manifests' in doc:
        selected = next(r for r in doc['manifests'] if r.get('platform', {}).get('os') == 'linux'
                        and r.get('platform', {}).get('architecture') == 'amd64')
        raw, _ = registry.manifest(selected['digest'])
        doc = json.loads(raw)
    store(args.cache, raw)
    records = [doc['config']] + doc['layers']
    for item in records:
        digest_hex(item['digest'])
        last = [0.0]
        def progress(done, size, last=last, item=item):
            now = time.monotonic()
            if now-last[0] > 5 or done == size:
                print(json.dumps({'blob': item['digest'], 'completed_bytes': done, 'total_bytes': size}), flush=True)
                last[0] = now
        fetch_blob(args.cache, item['digest'], item['size'], registry.resolver(item['digest']),
                   workers=args.workers, progress=progress)
    config = json.loads((args.cache/'sha256'/digest_hex(doc['config']['digest'])).read_text())
    if config['os'] != 'linux' or config['architecture'] != 'amd64':
        raise PreparationError('unexpected image platform')
    receipt = {'reference': args.reference, 'registry_root': root_digest,
               'manifest': 'sha256:'+hashlib.sha256(raw).hexdigest(), 'blobs': records,
               'model_requests': 0, 'changed_image_bytes': False, 'tool_source_sha256': sha(Path(__file__))}
    if args.load:
        with (args.evidence/'docker-load.log').open('wb') as log:
            process = subprocess.Popen(['docker', 'load'], stdin=subprocess.PIPE, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                write_oci(process.stdin, args.reference, raw, args.cache)
                process.stdin.close()
                if process.wait(timeout=600):
                    raise PreparationError('Docker OCI import failed; inspect local log')
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=30)
        loaded = json.loads(subprocess.check_output(['docker','image','inspect',args.reference], text=True))[0]
        if (loaded['Architecture'] != 'amd64' or loaded['Os'] != 'linux'
                or loaded['RootFS']['Layers'] != config['rootfs']['diff_ids']):
            raise PreparationError('imported platform or filesystem digest mismatch')
        for key, value in config.get('config', {}).items():
            if (key in ('Env', 'Cmd', 'Entrypoint', 'User', 'WorkingDir', 'Labels', 'Healthcheck', 'Volumes')
                    and loaded['Config'].get(key) != value):
                raise PreparationError('imported image configuration mismatch')
        receipt['loaded'] = {key: loaded.get(key) for key in ('Id', 'RepoDigests', 'Os', 'Architecture')}
    (args.evidence/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({'prepared': True, 'reference': args.reference, 'model_requests': 0}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001 -- sanitize signed URLs in all failure paths.
        # HTTP exception text may contain a temporary signed URL: never emit it.
        print(json.dumps({'prepared': False, 'error_type': type(error).__name__, 'reason': str(error) if isinstance(error, PreparationError) else None}), flush=True)
        sys.exit(1)
