"""Bounded, no-host-mount transfer for the one approved public SCI pilot.

No process/container is started here. Docker RPC runs only on explicit transfer.
Official Harbor scoring remains outside this adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import io
import json
import os
import re
import shlex
import socket
import stat
import tarfile
import time
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlencode, urlsplit

from harbor.environments.docker.docker import DockerEnvironment

from . import rsi_pilot_exports as exports
from .rsi_pilot_stopped import quota

VOLUME = Path("/Volumes/MemWeave-RSI-Pilot")
SOCKET = VOLUME / "colima/rsi-navigation-pilot/docker.sock"
DAEMON = "db787ac5-2568-4a56-b888-c51dc3802592"
MAX_FILE = 512 * 1024**2
MAX_DATA = 768 * 1024**2
MAX_WIRE = 1024 * 1024**2
MAX_ENTRIES = 1024


class MissingGuestPath(FileNotFoundError):
    pass


class TransferError(ValueError):
    """Resource/infrastructure error; never an ability score."""


def within(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    if not path.is_relative_to(root) or ".." in path.parts:
        raise TransferError("host path outside approved transfer root")
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise TransferError("linked host transfer path")
    return path


def source_allowed(path, role):
    path = within(path, VOLUME / "inputs")
    allowed = {
        "actor": ("public", "subject"),
        "nop": ("public", "subject"),
        "oracle": ("public", "subject", "solution"),
        "verifier": ("tests", "submitted"),
    }
    task_parts = {
        "actor": ("environment",),
        "nop": ("environment",),
        "oracle": ("environment", "solution"),
        "verifier": ("tests",),
    }
    if role in task_parts and any(
        path.is_relative_to(VOLUME / "inputs/task" / p) for p in task_parts[role]
    ):
        return path
    if role not in allowed or not any(
        path.is_relative_to(VOLUME / "inputs" / p) for p in allowed[role]
    ):
        raise TransferError("input material is forbidden for this role")
    return path


def octal(field):
    text = field.rstrip(b"\0 ").lstrip(b" ")
    if not re.fullmatch(b"[0-7]+", text):
        raise TransferError("unsupported tar numeric encoding")
    return int(text, 8)


def unpack(stream, expected):
    """Strict USTAR subset, bounded before allocations; returns unpublished bytes."""
    consumed = 0
    deadline = time.monotonic() + 60
    entries = {}
    kinds = {}
    total = 0

    def read(size):
        nonlocal consumed
        if time.monotonic() > deadline:
            raise TransferError("archive transfer deadline exceeded")
        if size < 0 or consumed + size > MAX_WIRE:
            raise TransferError("encoded archive limit exceeded")
        chunks = []
        left = size
        while left:
            if time.monotonic() > deadline:
                raise TransferError("archive transfer deadline exceeded")
            data = stream.read(min(left, 65536))
            if not isinstance(data, bytes) or not data or len(data) > left:
                raise TransferError("truncated or invalid archive stream")
            chunks.append(data)
            consumed += len(data)
            left -= len(data)
        return b"".join(chunks)

    def field(raw):
        value, _, padding = raw.partition(b"\0")
        if padding.strip(b"\0"):
            raise TransferError("invalid tar string padding")
        try:
            return value.decode("utf-8")
        except UnicodeError as exc:
            raise TransferError("invalid tar path encoding") from exc

    while True:
        header = read(512)
        if header == bytes(512):
            if read(512) != bytes(512):
                raise TransferError("invalid archive terminator")
            while True:
                if time.monotonic() > deadline:
                    raise TransferError("archive transfer deadline exceeded")
                tail = stream.read(min(65536, MAX_WIRE - consumed + 1))
                if not isinstance(tail, bytes):
                    raise TransferError("invalid archive tail")
                if not tail:
                    if consumed % 512:
                        raise TransferError("unaligned archive tail")
                    return entries
                consumed += len(tail)
                if consumed > MAX_WIRE or tail.strip(b"\0"):
                    raise TransferError("extra or excessive archive content")
        if len(kinds) >= MAX_ENTRIES:
            raise TransferError("archive entry limit exceeded")
        if octal(header[148:156]) != sum(header[:148] + b" " * 8 + header[156:]):
            raise TransferError("tar checksum mismatch")
        if header[257:263] != b"ustar\0":
            raise TransferError("unsupported tar format")
        name = field(header[:100])
        prefix = field(header[345:500])
        name = (prefix + "/" if prefix else "") + name
        kind = header[156:157]
        if kind == b"5":
            name = name.rstrip("/")
        parts = PurePosixPath(name).parts
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or "\x00" in name
            or any(p in ("", ".", "..") for p in name.split("/"))
            or name in kinds
        ):
            raise TransferError("unsafe or duplicate archive path")
        if not parts or parts[0] != expected:
            raise TransferError("archive root differs from requested resource")
        if kind not in (b"0", b"\0", b"5") or header[157:257].strip(b"\0"):
            raise TransferError("links or special/extended archive entries forbidden")
        if any(kinds.get("/".join(parts[:i])) == "file" for i in range(1, len(parts))):
            raise TransferError("file used as archive directory")
        if kind != b"5" and any(k.startswith(name + "/") for k in kinds):
            raise TransferError("directory replaced by archive file")
        size = octal(header[124:136])
        if kind == b"5" and size:
            raise TransferError("directory contains payload")
        if size > MAX_FILE or total + size > MAX_DATA:
            raise TransferError("archive payload limit exceeded")
        kinds[name] = "dir" if kind == b"5" else "file"
        if kind != b"5":
            entries[name] = read(size)
            total += size
            if read((-size) % 512).strip(b"\0"):
                raise TransferError("nonzero archive padding")


def pack(path, role):
    quota()
    path = source_allowed(path, role)
    files = [path] if path.is_file() else sorted(path.rglob("*"))
    if len(files) + 1 > MAX_ENTRIES:
        raise TransferError("upload entry limit exceeded")
    result = io.BytesIO()
    total = 0
    with tarfile.open(fileobj=result, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for p in ([path] if path.is_dir() else []) + files:
            within(p, path if path.is_dir() else path.parent)
            before = p.lstat()
            if not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode)) or (
                p.is_file() and before.st_nlink != 1
            ):
                raise TransferError("nonexclusive or special upload source")
            name = (
                path.name
                if p == path
                else path.name + "/" + p.relative_to(path).as_posix()
            )
            info = tarfile.TarInfo(name)
            info.mode = stat.S_IMODE(before.st_mode) & 0o777
            if p.is_dir():
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                if before.st_size > MAX_FILE or total + before.st_size > MAX_DATA:
                    raise TransferError("upload payload limit exceeded")
                fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    current = os.fstat(stream.fileno())
                    if (
                        current.st_dev,
                        current.st_ino,
                        current.st_size,
                        current.st_mtime_ns,
                    ) != (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                    ):
                        raise TransferError("upload source changed")
                    data = stream.read(MAX_FILE + 1)
                    after = os.fstat(stream.fileno())
                if len(data) != before.st_size or (
                    after.st_size,
                    after.st_mtime_ns,
                ) != (before.st_size, before.st_mtime_ns):
                    raise TransferError("upload source changed while reading")
                info.size = len(data)
                total += len(data)
                archive.addfile(info, io.BytesIO(data))
            if result.tell() > MAX_WIRE:
                raise TransferError("encoded upload limit exceeded")
    value = result.getvalue()
    if len(value) > MAX_WIRE:
        raise TransferError("encoded upload limit exceeded")
    return value


def publish(
    entries, expected, destination, *, directory, role, metadata=None, operation=None
):
    quota()
    try:
        return exports.publish(
            entries,
            expected,
            destination,
            directory=directory,
            metadata={
                "role": role,
                "daemon_id": DAEMON,
                "trial_id": "unbound",
                "container_id": None,
                **(metadata or {}),
            },
            operation=operation,
        )
    except exports.ExportError as exc:
        raise TransferError(str(exc)) from exc


class _Connection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=30)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(str(SOCKET))


class PilotArchive:
    def __init__(self, project, role, trial_id=None):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,150}", project) or role not in (
            "actor",
            "oracle",
            "nop",
            "verifier",
        ):
            raise TransferError("invalid exact pilot transfer scope")
        self.project, self.role = project, role
        self.trial_id = trial_id or project
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,150}", self.trial_id):
            raise TransferError("invalid exact trial identity")
        self.operation = None

    def _request(self, method, path, body=None):
        connection = _Connection()
        if self.operation:
            self.operation.track(connection)
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={"Content-Type": "application/x-tar"}
                if body is not None
                else {},
            )
            response = connection.getresponse()
            if self.operation:
                self.operation.track(response)
            if response.status == 404 and method == "GET" and "/archive?" in path:
                raw = response.read(8193)
                if len(raw) <= 8192:
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        body = {}
                    request_path = urlsplit(path)
                    requested = parse_qs(request_path.query).get("path", [])
                    requested_cid = request_path.path.split("/")[2]
                    expected_message = (
                        (
                            "Could not find the file "
                            + requested[0]
                            + " in container "
                            + requested_cid
                        )
                        if len(requested) == 1
                        else None
                    )
                    if (
                        isinstance(body, dict)
                        and body.get("message") == expected_message
                        and expected_message is not None
                    ):
                        connection.close()
                        error = MissingGuestPath("confirmed Docker archive path absent")
                        error.body_sha256 = hashlib.sha256(raw).hexdigest()
                        raise error
            if response.status != 200:
                raise TransferError("pilot Docker archive request failed")
            return connection, response
        except BaseException:
            connection.close()
            raise

    def _json(self, path):
        c, r = self._request("GET", path)
        try:
            data = r.read(1024**2 + 1)
            if len(data) > 1024**2:
                raise TransferError("Docker metadata limit exceeded")
            return json.loads(data)
        finally:
            c.close()

    def _container(self):
        quota()
        if self._json("/info").get("ID") != DAEMON:
            raise TransferError("wrong pilot daemon")
        rows = self._json(
            "/containers/json?"
            + urlencode(
                {
                    "all": "1",
                    "filters": json.dumps(
                        {
                            "label": [
                                "com.docker.compose.project=" + self.project,
                                "com.docker.compose.service=main",
                            ]
                        }
                    ),
                }
            )
        )
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not re.fullmatch("[0-9a-f]{64}", rows[0].get("Id", ""))
        ):
            raise TransferError("ambiguous pilot container")
        cid = rows[0]["Id"]
        item = self._json("/containers/" + cid + "/json")
        labels = item.get("Config", {}).get("Labels") or {}
        host = item.get("HostConfig", {})
        if (
            item.get("Id") != cid
            or labels.get("com.docker.compose.project") != self.project
            or labels.get("com.docker.compose.service") != "main"
            or item.get("State", {}).get("Running") is not True
            or item.get("State", {}).get("Paused") is not False
            or item.get("Mounts") != []
            or item.get("State", {}).get("Restarting") is True
            or host.get("Binds") not in (None, [])
            or host.get("Privileged") is not False
            or host.get("PidMode") == "host"
            or host.get("NetworkMode") == "host"
        ):
            raise TransferError("unsafe pilot container identity or mounts")
        if self.role != "verifier":
            exports.bind_actor(self.trial_id, cid, self.project, self.role)
        return cid

    def download(self, source, destination, directory=False):
        path = PurePosixPath(source)
        if not path.is_absolute() or ".." in path.parts or not path.name:
            raise TransferError("unsafe guest source path")
        within(destination, VOLUME / "exports")
        cid = self._container()
        try:
            c, r = self._request(
                "GET", "/containers/" + cid + "/archive?" + urlencode({"path": source})
            )
        except MissingGuestPath as missing:
            if self._container() != cid:
                raise TransferError("container changed during missing-path observation")
            exports.missing_receipt(
                {
                    "status": "missing",
                    "http_status": 404,
                    "response_body_sha256": missing.body_sha256,
                    "source_guest": source,
                    "trial_id": self.trial_id,
                    "container_id": cid,
                    "project": self.project,
                    "role": self.role,
                    "daemon_id": DAEMON,
                }
            )
            raise
        if self.operation:
            self.operation.track(c, r)
        try:
            entries = unpack(r, path.name)
        finally:
            c.close()
        # Revalidate identity/state before publishing into the host's bounded domain.
        if self._container() != cid:
            raise TransferError("pilot container changed during transfer")
        publisher = (
            exports.publish_agent_logs
            if directory and source == "/logs/agent"
            else publish
        )
        receipt = publisher(
            entries,
            path.name,
            destination,
            directory=directory,
            role=self.role,
            metadata={
                "daemon_id": DAEMON,
                "container_id": cid,
                "project": self.project,
                "source_guest": source,
                "trial_id": self.trial_id,
            },
            operation=self.operation,
        )
        exports.committed(
            destination, trial_id=self.trial_id, cid=cid, roles={self.role}
        )
        return receipt

    def upload(self, source, target, directory=False):
        data = pack(source, self.role)
        target = PurePosixPath(target)
        if not target.is_absolute() or ".." in target.parts:
            raise TransferError("unsafe guest target path")
        if self.role in ("actor", "nop") and any(
            p in target.parts for p in ("tests", "solution", "verifier")
        ):
            raise TransferError("private guest target forbidden for actor")
        cid = self._container()
        parent = target if directory else target.parent
        # Repack only our own bounded USTAR; preserve executable bits/empty dirs.
        if directory or target.name != Path(source).name:
            result = io.BytesIO()
            with (
                tarfile.open(fileobj=io.BytesIO(data), mode="r:") as original,
                tarfile.open(
                    fileobj=result, mode="w", format=tarfile.USTAR_FORMAT
                ) as archive,
            ):
                for entry in original:
                    if directory:
                        if entry.name.rstrip("/") == Path(source).name:
                            continue
                        entry.name = (
                            PurePosixPath(entry.name)
                            .relative_to(Path(source).name)
                            .as_posix()
                        )
                    else:
                        entry.name = target.name
                    archive.addfile(
                        entry, original.extractfile(entry) if entry.isfile() else None
                    )
            data = result.getvalue()
        c, r = self._request(
            "PUT",
            "/containers/"
            + cid
            + "/archive?"
            + urlencode({"path": str(parent), "noOverwriteDirNonDir": "1"}),
            data,
        )
        try:
            if r.read(4097):
                raise TransferError("unexpected archive upload response")
        finally:
            c.close()


class NoMountPilotEnvironment(DockerEnvironment):
    """Explicit opt-in Harbor adapter; does not change installed Harbor sources."""

    def __init__(
        self,
        *args,
        pilot_role=None,
        pilot_role_bindings=None,
        pilot_trial_id=None,
        **kwargs,
    ):
        if pilot_role_bindings is not None:
            if not isinstance(pilot_role_bindings, dict) or any(
                v not in ("actor", "oracle", "nop", "verifier")
                for v in pilot_role_bindings.values()
            ):
                raise TransferError("invalid exact session role bindings")
            selected = pilot_role_bindings.get(kwargs.get("session_id"))
            if selected is None or (pilot_role is not None and selected != pilot_role):
                raise TransferError("session role binding missing or conflicting")
            pilot_role = selected
        if (
            os.environ.get("DOCKER_HOST") != "unix://" + str(SOCKET)
            or os.environ.get("DOCKER_CONFIG") != str(VOLUME / "docker-config")
            or os.environ.get("BUILDX_CONFIG") != str(VOLUME / "buildx")
            or os.environ.get("DOCKER_CONTEXT")
            not in (None, "colima-rsi-navigation-pilot")
        ):
            raise TransferError("explicit isolated pilot endpoint/config required")
        if pilot_role not in ("actor", "oracle", "nop", "verifier"):
            raise TransferError("explicit pilot role required")
        mounts = kwargs.pop("mounts", []) or []
        for mount in mounts:
            item = mount.model_dump() if hasattr(mount, "model_dump") else mount
            if item.get("target") not in (
                "/logs/agent",
                "/logs/verifier",
                "/logs/artifacts",
            ):
                raise TransferError("only Harbor log mounts can be removed")
            within(item["source"], VOLUME / "exports")
        if kwargs.get("extra_docker_compose"):
            raise TransferError("extra Compose is outside pilot transfer scope")
        self._pilot_role = pilot_role
        super().__init__(*args, mounts=[], **kwargs)
        if self._uses_compose or self._is_windows_container:
            raise TransferError("only audited Linux Dockerfile task supported")
        source_allowed(self.environment_dir, pilot_role)
        if pilot_role == "verifier" and pilot_trial_id is None:
            raise TransferError("shared explicit trial identity required for verifier")
        self._archive = PilotArchive(self.session_id, pilot_role, pilot_trial_id)
        self._io_lock = asyncio.Lock()

    async def start(self, *args, **kwargs):
        await super().start(*args, **kwargs)
        await self._io(self._archive._container)
        await self.ensure_dirs(["/logs/agent", "/logs/verifier", "/logs/artifacts"])

    @property
    def capabilities(self):
        return super().capabilities.model_copy(
            update={"mounted": False, "stream": False}
        )

    async def _prepare_upload(self, source, target, directory):
        source_allowed(source, self._pilot_role)
        path = PurePosixPath(target)
        if not path.is_absolute() or ".." in path.parts:
            raise TransferError("unsafe guest target path")
        if self._pilot_role in ("actor", "nop") and any(
            x in path.parts for x in ("tests", "solution", "verifier")
        ):
            raise TransferError("private guest target forbidden")
        parent = path if directory else path.parent
        await self.exec(command="mkdir -p -- " + shlex.quote(str(parent)))

    async def _io(self, method, *args):
        async with self._io_lock:
            operation = exports.Operation()
            self._archive.operation = operation
            worker = asyncio.create_task(asyncio.to_thread(method, *args))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                operation.cancel()
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        operation.cancel()
                    except Exception as error:  # noqa: BLE001 -- record worker failure, preserve cancellation after join
                        operation.worker_error = type(error).__name__
                        break
                if worker.done() and not worker.cancelled():
                    error = worker.exception()
                    if error is not None:
                        operation.worker_error = type(error).__name__
                operation.quarantine()
                raise
            except BaseException:
                operation.quarantine()
                raise
            finally:
                operation.close()
                self._archive.operation = None

    async def upload_file(self, source_path, target_path):
        if self._pilot_role == "verifier" and Path(source_path).is_relative_to(
            VOLUME / "exports"
        ):
            source_path = exports.stage_submission(
                source_path, target_path, self._archive.trial_id
            )
        await self._prepare_upload(source_path, target_path, False)
        await self._io(self._archive.upload, source_path, target_path)

    async def upload_dir(self, source_dir, target_dir):
        if self._pilot_role == "verifier" and Path(source_dir).is_relative_to(
            VOLUME / "exports"
        ):
            source_dir = exports.stage_convention(
                source_dir, target_dir, self._archive.trial_id
            )
        elif Path(source_dir).is_relative_to(VOLUME / "exports"):
            source_dir = exports.stage_own_logs(
                source_dir, target_dir, self._archive.trial_id, self._pilot_role
            )
        await self._prepare_upload(source_dir, target_dir, True)
        await self._io(self._archive.upload, source_dir, target_dir, True)

    async def download_file(self, source_path, target_path):
        await self._io(self._archive.download, source_path, target_path)

    async def download_dir(self, source_dir, target_dir):
        await self._io(self._archive.download, source_dir, target_dir, True)

    async def service_download_file(self, source_path, target_path, *, service=None):
        if service not in (None, "main"):
            raise TransferError("sidecar transfer forbidden")
        await self.download_file(source_path, target_path)

    async def service_download_dir(self, source_dir, target_dir, *, service=None):
        if service not in (None, "main"):
            raise TransferError("sidecar transfer forbidden")
        await self.download_dir(source_dir, target_dir)
