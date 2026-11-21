"""Synthetic archives/HTTP metadata only; no real Docker or subprocesses."""

import asyncio
import copy
import io
import os
import tarfile

import pytest

from memweave_eval import rsi_pilot_stopped as stopped
from memweave_eval import rsi_pilot_transfer as transfer


@pytest.fixture(autouse=True)
def no_real_subprocess(monkeypatch):
    monkeypatch.setattr(
        stopped.subprocess,
        "run",
        lambda *a, **k: pytest.fail("real subprocess forbidden"),
    )


@pytest.fixture
def domain(tmp_path, monkeypatch):
    root = tmp_path / "quota"
    root.mkdir()
    for x in [
        "inputs/public",
        "inputs/subject",
        "inputs/solution",
        "inputs/tests",
        "inputs/submitted",
        "exports",
    ]:
        (root / x).mkdir(parents=True)
    monkeypatch.setattr(transfer, "VOLUME", root)
    monkeypatch.setattr(transfer.exports, "VOLUME", root)
    monkeypatch.setattr(
        transfer.exports,
        "quota",
        lambda: {"volume_uuid": "fixture", "volume_quota": 64 * 2**30},
    )
    monkeypatch.setattr(transfer, "SOCKET", root / "docker.sock")
    monkeypatch.setattr(
        transfer,
        "quota",
        lambda: {"volume_uuid": "fixture", "volume_quota": 64 * 2**30},
    )
    monkeypatch.setattr(
        transfer, "_Connection", lambda: pytest.fail("real socket forbidden")
    )
    for key, value in {
        "DOCKER_HOST": "unix://" + str(root / "docker.sock"),
        "DOCKER_CONFIG": str(root / "docker-config"),
        "BUILDX_CONFIG": str(root / "buildx"),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    return root


def archive(entries):
    target = io.BytesIO()
    with tarfile.open(fileobj=target, mode="w", format=tarfile.USTAR_FORMAT) as writer:
        for name, payload, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.size = len(payload)
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = "/etc/passwd"
            writer.addfile(info, io.BytesIO(payload))
    return target.getvalue()


def test_verifier_reward_bytes_survive_bounded_export(domain):
    data = archive(
        [
            ("verifier", b"", tarfile.DIRTYPE),
            ("verifier/reward.txt", b"1\n", tarfile.REGTYPE),
            ("verifier/reward.json", b'{"reward":0}', tarfile.REGTYPE),
        ]
    )
    rows = transfer.unpack(io.BytesIO(data), "verifier")
    result = transfer.publish(
        rows, "verifier", domain / "exports/verifier", directory=True, role="verifier"
    )
    assert (domain / "exports/verifier/reward.txt").read_bytes() == b"1\n"
    assert (domain / "exports/verifier/reward.json").read_bytes() == b'{"reward":0}'
    assert (
        result["visibility"] == "maintenance-only"
        and sum(x["bytes"] for x in result["files"]) == 14
    )


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "root/../escape",
        "root//empty",
        "root/./dot",
        "root\\escape",
        "other/file",
    ],
)
def test_unsafe_archive_names_never_publish(domain, name):
    with pytest.raises(transfer.TransferError):
        transfer.unpack(io.BytesIO(archive([(name, b"x", tarfile.REGTYPE)])), "root")
    assert list((domain / "exports").iterdir()) == []


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
        tarfile.XHDTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_SPARSE,
    ],
)
def test_special_or_extended_members_rejected(domain, kind):
    with pytest.raises(transfer.TransferError):
        transfer.unpack(io.BytesIO(archive([("root/a", b"", kind)])), "root")


@pytest.mark.parametrize(
    "entries",
    [
        [("root/a", b"first", tarfile.REGTYPE), ("root/a", b"second", tarfile.REGTYPE)],
        [
            ("root/a", b"first", tarfile.REGTYPE),
            ("root/a/child", b"x", tarfile.REGTYPE),
        ],
        [
            ("root/a/child", b"x", tarfile.REGTYPE),
            ("root/a", b"first", tarfile.REGTYPE),
        ],
    ],
)
def test_duplicate_and_file_directory_conflicts(domain, entries):
    with pytest.raises(transfer.TransferError):
        transfer.unpack(io.BytesIO(archive(entries)), "root")


@pytest.mark.parametrize("corrupt", ["checksum", "truncated", "tail", "padding"])
def test_corrupt_archive_fails_before_publication(domain, corrupt):
    data = bytearray(archive([("root/a", b"one", tarfile.REGTYPE)]))
    if corrupt == "checksum":
        data[0] = 90
    elif corrupt == "truncated":
        data = data[:513]
    elif corrupt == "tail":
        data[-1] = 90
    else:
        data[515] = 90
    with pytest.raises(transfer.TransferError):
        transfer.unpack(io.BytesIO(data), "root")


@pytest.mark.parametrize("field", ["MAX_FILE", "MAX_DATA", "MAX_WIRE", "MAX_ENTRIES"])
def test_limits_enforced_on_download(domain, monkeypatch, field):
    monkeypatch.setattr(transfer, field, 1)
    with pytest.raises(transfer.TransferError):
        transfer.unpack(
            io.BytesIO(
                archive(
                    [
                        ("root/a", b"abc", tarfile.REGTYPE),
                        ("root/b", b"abc", tarfile.REGTYPE),
                    ]
                )
            ),
            "root",
        )


def test_stream_is_read_in_finite_chunks(domain):
    class Bounded(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 65536
            return super().read(min(size, 37))

    assert transfer.unpack(
        Bounded(archive([("root/file", b"abcd", tarfile.REGTYPE)])), "root"
    ) == {"root/file": b"abcd"}


@pytest.mark.parametrize(
    "role,folder",
    [
        ("actor", "tests"),
        ("actor", "solution"),
        ("actor", "submitted"),
        ("nop", "solution"),
        ("verifier", "solution"),
        ("oracle", "tests"),
    ],
)
def test_private_inputs_do_not_enter_wrong_role(domain, role, folder):
    path = domain / "inputs" / folder / "secret"
    path.write_bytes(b"secret")
    with pytest.raises(transfer.TransferError):
        transfer.pack(path, role)


def test_public_and_oracle_uploads_preserve_bytes(domain):
    p = domain / "inputs/public/environment"
    p.mkdir()
    (p / "file").write_bytes(b"input bytes")
    assert transfer.unpack(io.BytesIO(transfer.pack(p, "actor")), "environment") == {
        "environment/file": b"input bytes"
    }
    secret = domain / "inputs/solution/solve.sh"
    secret.write_bytes(b"oracle bytes")
    assert transfer.unpack(io.BytesIO(transfer.pack(secret, "oracle")), "solve.sh") == {
        "solve.sh": b"oracle bytes"
    }


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "oversized"])
def test_untrusted_upload_sources_rejected(domain, monkeypatch, kind):
    p = domain / "inputs/public/a"
    p.write_bytes(b"abc")
    if kind == "symlink":
        p.unlink()
        p.symlink_to(domain / "inputs/solution")
    elif kind == "hardlink":
        os.link(p, p.with_name("b"))
    else:
        monkeypatch.setattr(transfer, "MAX_FILE", 1)
    with pytest.raises(transfer.TransferError):
        transfer.pack(p, "actor")


def test_export_collision_does_not_publish_other_files(domain):
    dest = domain / "exports/phase"
    dest.mkdir()
    (dest / "b").write_bytes(b"old")
    with pytest.raises(transfer.TransferError):
        transfer.publish(
            {"root/a": b"new", "root/b": b"replace"},
            "root",
            dest,
            directory=True,
            role="actor",
        )
    assert not (dest / "a").exists() and (dest / "b").read_bytes() == b"old"


def test_linked_export_path_rejected(domain):
    (domain / "exports/linked").symlink_to(
        domain / "inputs/public", target_is_directory=True
    )
    with pytest.raises(transfer.TransferError):
        transfer.publish(
            {"a": b"x"}, "a", domain / "exports/linked/a", directory=False, role="actor"
        )


@pytest.fixture
def api(domain, monkeypatch):
    backend = transfer.PilotArchive("exact-project", "actor")
    cid = "a" * 64
    meta = {
        "Id": cid,
        "Config": {
            "Labels": {
                "com.docker.compose.project": "exact-project",
                "com.docker.compose.service": "main",
            }
        },
        "State": {"Running": True, "Paused": False},
        "Mounts": [],
        "HostConfig": {
            "Privileged": False,
            "PidMode": "",
            "NetworkMode": "exact-project_default",
        },
    }

    def query(path):
        if path == "/info":
            return {"ID": transfer.DAEMON}
        if path.startswith("/containers/json?"):
            return [{"Id": cid}]
        return copy.deepcopy(meta)

    monkeypatch.setattr(backend, "_json", query)
    return backend, meta


@pytest.mark.parametrize(
    "problem",
    [
        "wrong_id",
        "wrong_project",
        "wrong_service",
        "paused",
        "stopped",
        "mount",
        "privileged",
        "host_pid",
        "host_network",
    ],
)
def test_live_container_identity_and_mounts_fail_closed(api, problem):
    backend, meta = api
    if problem == "wrong_id":
        meta["Id"] = "b" * 64
    elif problem == "wrong_project":
        meta["Config"]["Labels"]["com.docker.compose.project"] = "other"
    elif problem == "wrong_service":
        meta["Config"]["Labels"]["com.docker.compose.service"] = "sidecar"
    elif problem == "paused":
        meta["State"]["Paused"] = True
    elif problem == "stopped":
        meta["State"]["Running"] = False
    elif problem == "mount":
        meta["Mounts"] = [{"Type": "bind", "Source": "/host"}]
    elif problem == "privileged":
        meta["HostConfig"]["Privileged"] = True
    elif problem == "host_pid":
        meta["HostConfig"]["PidMode"] = "host"
    else:
        meta["HostConfig"]["NetworkMode"] = "host"
    with pytest.raises(transfer.TransferError):
        backend._container()


def test_wrong_daemon_and_ambiguous_container_rejected(api, monkeypatch):
    backend, _ = api
    monkeypatch.setattr(backend, "_json", lambda _: {"ID": "old-daemon"})
    with pytest.raises(transfer.TransferError):
        backend._container()


def test_harbor_adapter_is_opt_in_and_reports_no_mounts(domain, monkeypatch):
    calls = []

    def init(self, *args, **kwargs):
        calls.append(kwargs)
        self._is_windows_container = False
        self._enable_egress_control = False
        self.environment_dir = domain / "inputs/public"
        self.extra_docker_compose_paths = []
        self.session_id = "exact-project"

    monkeypatch.setattr(transfer.DockerEnvironment, "__init__", init)
    monkeypatch.setattr(
        transfer.NoMountPilotEnvironment, "_uses_compose", property(lambda _: False)
    )
    env = transfer.NoMountPilotEnvironment(
        pilot_role="actor",
        mounts=[{"source": str(domain / "exports/log"), "target": "/logs/agent"}],
    )
    assert (
        calls[0]["mounts"] == []
        and env.capabilities.mounted is False
        and env.capabilities.stream is False
    )
    with pytest.raises(transfer.TransferError):
        transfer.NoMountPilotEnvironment(
            pilot_role="actor",
            mounts=[{"source": str(domain / "exports/log"), "target": "/etc/private"}],
        )
    with pytest.raises(transfer.TransferError):
        transfer.NoMountPilotEnvironment()
    monkeypatch.setenv("DOCKER_HOST", "unix:///old.sock")
    with pytest.raises(transfer.TransferError):
        transfer.NoMountPilotEnvironment(pilot_role="actor")


def test_sidecar_files_never_transfer(domain, monkeypatch):
    obj = object.__new__(transfer.NoMountPilotEnvironment)
    with pytest.raises(transfer.TransferError):
        asyncio.run(
            obj.service_download_dir("/data", domain / "exports/x", service="sidecar")
        )


def test_download_mock_archive_to_receipt_preserves_raw_files(api, domain, monkeypatch):
    backend, _ = api

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connections = []
    data = archive([("solver.py", b"print(1)\n", tarfile.REGTYPE)])

    def request(*args):
        c = Connection()
        connections.append(c)
        return c, io.BytesIO(data)

    monkeypatch.setattr(backend, "_request", request)
    receipt = backend.download("/root/results/solver.py", domain / "exports/solver.py")
    assert (domain / "exports/solver.py").read_bytes() == b"print(1)\n"
    assert (
        receipt["container_id"] == "a" * 64 and receipt["daemon_id"] == transfer.DAEMON
    )
    assert (domain / "exports/.rsi-transfer-solver.py.json").is_file()
    assert all(c.closed for c in connections)


def test_identity_change_after_download_does_not_publish(api, domain, monkeypatch):
    backend, _ = api
    calls = []

    def container():
        calls.append(None)
        return "a" * 64 if len(calls) == 1 else "b" * 64

    monkeypatch.setattr(backend, "_container", container)
    monkeypatch.setattr(
        backend,
        "_request",
        lambda *args: (
            type("C", (), {"close": lambda self: None})(),
            io.BytesIO(archive([("solver.py", b"x", tarfile.REGTYPE)])),
        ),
    )
    with pytest.raises(transfer.TransferError):
        backend.download("/root/solver.py", domain / "exports/solver.py")
    assert list((domain / "exports").iterdir()) == []


def test_upload_directory_matches_copy_children_semantics(api, domain, monkeypatch):
    backend, _ = api
    folder = domain / "inputs/public/tree"
    folder.mkdir()
    (folder / "file").write_bytes(b"data")
    (folder / "nested").mkdir()
    (folder / "nested/a").write_bytes(b"nested")
    requests = []

    def request(method, path, body=None):
        requests.append((method, path, body))
        return type("C", (), {"close": lambda self: None})(), io.BytesIO()

    monkeypatch.setattr(backend, "_request", request)
    backend.upload(folder, "/root/target", directory=True)
    assert requests[0][0] == "PUT" and "path=%2Froot%2Ftarget" in requests[0][1]
    with tarfile.open(fileobj=io.BytesIO(requests[0][2])) as result:
        assert sorted(result.getnames()) == ["file", "nested", "nested/a"]
        assert result.extractfile("nested/a").read() == b"nested"


def test_upload_rename_matches_official_file_copy(api, domain, monkeypatch):
    backend, _ = api
    p = domain / "inputs/public/original"
    p.write_bytes(b"solver")
    calls = []
    monkeypatch.setattr(
        backend,
        "_request",
        lambda m, p, b: (
            calls.append(b) or type("C", (), {"close": lambda self: None})(),
            io.BytesIO(),
        ),
    )
    backend.upload(p, "/root/results/solver.py")
    assert transfer.unpack(io.BytesIO(calls[0]), "solver.py") == {
        "solver.py": b"solver"
    }


def test_expired_stream_is_not_published(domain, monkeypatch):
    values = iter([0, 61])
    monkeypatch.setattr(transfer.time, "monotonic", lambda: next(values))
    with pytest.raises(transfer.TransferError, match="deadline"):
        transfer.unpack(io.BytesIO(archive([("a", b"x", tarfile.REGTYPE)])), "a")


def test_quota_failure_blocks_before_socket_or_export(domain, monkeypatch):
    monkeypatch.setattr(
        transfer, "quota", lambda: (_ for _ in ()).throw(ValueError("quota differs"))
    )
    with pytest.raises(ValueError):
        transfer.PilotArchive("exact-project", "actor")._container()
    with pytest.raises(ValueError):
        transfer.publish(
            {"x": b"y"}, "x", domain / "exports/x", directory=False, role="actor"
        )
    assert list((domain / "exports").iterdir()) == []


def test_export_write_failure_removes_only_new_payloads(domain, monkeypatch):
    original = transfer.os.open
    calls = []

    def open_once(path, *args, **kwargs):
        calls.append(path)
        if len(calls) > 1:
            raise OSError("synthetic quota full")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(transfer.os, "open", open_once)
    with pytest.raises(OSError):
        transfer.publish(
            {"root/a": b"a", "root/b": b"b"},
            "root",
            domain / "exports/out",
            directory=True,
            role="actor",
        )
    assert not (domain / "exports/out").exists()


def test_public_upload_preserves_executable_file_and_empty_directory(
    api, domain, monkeypatch
):
    backend, _ = api
    p = domain / "inputs/public/payload"
    p.mkdir()
    script = p / "run.sh"
    script.write_bytes(b"#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    (p / "empty").mkdir()
    calls = []
    monkeypatch.setattr(
        backend,
        "_request",
        lambda m, p, b: (
            calls.append(b) or type("C", (), {"close": lambda self: None})(),
            io.BytesIO(),
        ),
    )
    backend.upload(p, "/opt/payload", directory=True)
    with tarfile.open(fileobj=io.BytesIO(calls[0])) as output:
        assert output.getmember("run.sh").mode == 0o755
        assert output.getmember("empty").isdir()
        assert output.extractfile("run.sh").read() == script.read_bytes()


def test_separate_harbor_environment_uses_exact_inherited_role_bindings(
    domain, monkeypatch
):
    def init(self, *args, **kwargs):
        self._is_windows_container = False
        self._enable_egress_control = False
        self.extra_docker_compose_paths = []
        self.session_id = kwargs["session_id"]
        self.environment_dir = kwargs["environment_dir"]

    monkeypatch.setattr(transfer.DockerEnvironment, "__init__", init)
    monkeypatch.setattr(
        transfer.NoMountPilotEnvironment, "_uses_compose", property(lambda _: False)
    )
    bindings = {"actor-session": "actor", "verifier-session": "verifier"}
    actor = transfer.NoMountPilotEnvironment(
        pilot_role_bindings=bindings,
        pilot_trial_id="shared-trial",
        session_id="actor-session",
        environment_dir=domain / "inputs/public",
    )
    verifier = transfer.NoMountPilotEnvironment(
        pilot_role_bindings=bindings,
        pilot_trial_id="shared-trial",
        session_id="verifier-session",
        environment_dir=domain / "inputs/tests",
    )
    assert actor._archive.role == "actor" and verifier._archive.role == "verifier"
    with pytest.raises(transfer.TransferError):
        transfer.NoMountPilotEnvironment(
            pilot_role_bindings=bindings,
            session_id="other",
            environment_dir=domain / "inputs/public",
        )
    with pytest.raises(transfer.TransferError):
        transfer.NoMountPilotEnvironment(
            pilot_role_bindings=bindings,
            pilot_role="actor",
            session_id="verifier-session",
            environment_dir=domain / "inputs/tests",
        )


def test_moby_ordinary_pax_format_without_extensions_is_accepted(domain):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w", format=tarfile.PAX_FORMAT) as stream:
        header = tarfile.TarInfo("solver.py")
        header.mtime = 1700000000
        header.size = 1
        stream.addfile(header, io.BytesIO(b"x"))
    assert transfer.unpack(io.BytesIO(data.getvalue()), "solver.py") == {
        "solver.py": b"x"
    }
