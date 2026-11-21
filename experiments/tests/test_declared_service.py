import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest
import yaml

from memweave_eval import declared_service as svc
from memweave_eval.rsi_pilot_transfer import TransferError


@pytest.fixture
def source(tmp_path):
    decl = {
        "services": {
            "public-evaluator": {
                "build": {"context": "${CONTEXT_DIR}/public_evaluator"},
                "command": ["python", "/srv/server.py"],
                "init": True,
                "expose": ["8080"],
                "cpus": "${CPUS:-4}",
                "mem_limit": "${MEMORY:-4096M}",
                "pids_limit": 128,
                "read_only": True,
                "tmpfs": ["/tmp:rw,noexec,nosuid,size=128m"],
                "cap_drop": ["ALL"],
                "cap_add": ["KILL", "SETGID", "SETUID"],
                "security_opt": ["no-new-privileges:true"],
                "healthcheck": {
                    "test": ["CMD", "python", "-c", "pass"],
                    "interval": "5s",
                    "timeout": "3s",
                    "retries": 20,
                },
            }
        }
    }
    path = tmp_path / "docker-compose.yaml"
    path.write_text(yaml.safe_dump(decl))
    spec = replace(
        svc.NOISY_EVALUATOR, declaration_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
    )
    return path, spec, decl


def test_service_overlay_preserves_original_limits_client_and_health(source):
    path, spec, original = source
    result = spec.compose(path)
    side = result["services"][spec.name]
    for key in (
        "command",
        "healthcheck",
        "init",
        "tmpfs",
        "read_only",
        "expose",
        "cap_add",
        "cap_drop",
    ):
        assert side[key] == original["services"][spec.name][key]
    assert side["image"] == spec.image and side["pull_policy"] == "never"
    assert side["cpus"] == 4 and side["mem_limit"] == "4096M"
    assert "build" not in side and "ports" not in side and "environment" not in side
    assert result["networks"]["task-service"] == {"internal": True}
    assert side["networks"] == ["task-service"]
    assert set(result["services"]["main"]["networks"]) == {"default", "task-service"}
    assert result["services"]["main"]["depends_on"][spec.name]["condition"] == "service_healthy"
    assert (
        spec.reservation(
            {"cpus": 4, "memory_mb": 4096, "storage_mb": 10240},
            {"cpus": 4, "memory_mb": 4096, "storage_mb": 1024},
        ).cpus
        == 8.25
    )


@pytest.mark.parametrize("change", ["modified", "ports", "volumes", "service", "link"])
def test_changed_or_unsafe_declaration_refused(source, change):
    path, spec, decl = source
    if change == "link":
        alias = path.with_suffix(".link")
        alias.symlink_to(path)
        path = alias
    else:
        if change == "service":
            decl["services"]["other"] = {"image": "unexpected"}
        elif change == "modified":
            decl["services"][spec.name]["command"] = ["changed"]
        else:
            decl["services"][spec.name][change] = ["80:80"]
        path.write_text(yaml.safe_dump(decl))
        if change != "modified":
            spec = replace(spec, declaration_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(TransferError):
        spec.compose(path)


def test_runtime_network_and_image_must_match_actual_docker(source):
    _, spec, _ = source
    project, actor, service, net = "trial__env", "a" * 64, "b" * 64, "c" * 64
    labels = {"com.docker.compose.project": project}
    rows = [
        {"Id": actor, "Labels": {**labels, "com.docker.compose.service": "main"}},
        {"Id": service, "Labels": {**labels, "com.docker.compose.service": spec.name}},
    ]
    network = {
        "Id": net,
        "Name": project + "_task-service",
        "Internal": True,
        "Labels": {**labels, "com.docker.compose.network": "task-service"},
        "Containers": {actor: {}, service: {}},
    }
    image = {
        "Id": spec.image_id,
        "Os": "linux",
        "Architecture": "arm64",
        "Config": {"Env": ["PATH=/bin"]},
    }
    item = {
        "Id": service,
        "Image": spec.image_id,
        "Mounts": [],
        "Config": {
            "Labels": rows[1]["Labels"],
            "Env": ["PATH=/bin"],
            "Cmd": ["python", "/srv/server.py"],
            "ExposedPorts": {"8080/tcp": {}},
        },
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "HostConfig": {
            "NanoCpus": 4_000_000_000,
            "Memory": 4096 * 2**20,
            "PidsLimit": 128,
            "Privileged": False,
            "ReadonlyRootfs": True,
            "Init": True,
            "Binds": None,
            "PortBindings": {},
            "PublishAllPorts": False,
            "CapDrop": ["ALL"],
            "CapAdd": ["KILL", "SETGID", "SETUID"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=128m"},
        },
        "NetworkSettings": {"Networks": {network["Name"]: {"NetworkID": net}}},
    }

    def query(path):
        if path.startswith("/containers/json?"):
            return rows
        if path == "/containers/" + service + "/json":
            return item
        if path == "/images/" + spec.image_id + "/json":
            return image
        if path == "/networks/" + net:
            return network
        if path == "/info":
            return {"ID": "daemon"}
        raise AssertionError(path)

    result = spec.observe(query, "daemon", project, actor)
    assert result["service_id"] == service and result["private_network_id"] == net
    assert "PATH" not in json.dumps(result)
    item["HostConfig"]["CapAdd"] = ["CAP_KILL", "CAP_SETGID", "CAP_SETUID"]
    assert spec.observe(query, "daemon", project, actor) == result
    for value, key, replacement in [
        (network, "Internal", False),
        (network, "Containers", {actor: {}, service: {}, "x": {}}),
        (item, "Image", "wrong"),
        (item["Config"], "Env", ["OTHER=value"]),
        (item["HostConfig"], "PortBindings", {"8080/tcp": [{}]}),
        (item["HostConfig"], "Tmpfs", {}),
        (item["HostConfig"], "Privileged", True),
    ]:
        old = deepcopy(value[key])
        value[key] = replacement
        with pytest.raises(TransferError):
            spec.observe(query, "daemon", project, actor)
        value[key] = old


def test_retirement_checks_project_networks_even_after_actor_exits():
    def query(path):
        return {"ID": "daemon"} if path == "/info" else []

    svc.require_retired(query, "daemon", "single__env")
    with pytest.raises(TransferError):
        svc.require_retired(
            lambda path: [{}] if path.startswith("/networks?") else query(path),
            "daemon",
            "single__env",
        )


def test_harbor_substitutes_only_the_registered_actor_service(source, monkeypatch):
    from types import SimpleNamespace

    from memweave_eval import rsi_pilot_transfer as transfer

    path, spec, _ = source
    monkeypatch.setenv("DOCKER_HOST", "unix://" + str(transfer.SOCKET))
    monkeypatch.setenv("DOCKER_CONFIG", str(transfer.VOLUME / "docker-config"))
    monkeypatch.setenv("BUILDX_CONFIG", str(transfer.VOLUME / "buildx"))
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(transfer, "source_allowed", lambda *_: None)

    def init(self, **kwargs):
        self.environment_dir = path.parent
        self._is_windows_container = False
        self.extra_docker_compose_paths = []
        self._enable_egress_control = False
        self.session_id = "physical__env"
        self._network_policy = SimpleNamespace(network_mode=SimpleNamespace(value="public"))

    monkeypatch.setattr(transfer.DockerEnvironment, "__init__", init)

    class OriginalService(svc.DeclaredServiceEnvironment, transfer.NoMountPilotEnvironment):
        declared_service = spec

    actor = OriginalService(pilot_role="actor")
    assert actor._environment_docker_compose_path != path
    assert json.loads(actor._environment_docker_compose_path.read_bytes()) == spec.compose(path)
    actor._service_dir.cleanup()
    for cls, kwargs in [
        (transfer.NoMountPilotEnvironment, {"pilot_role": "actor"}),
        (OriginalService, {"pilot_role": "actor", "extra_docker_compose": ["other.yaml"]}),
        (OriginalService, {"pilot_role": "verifier", "pilot_trial_id": "physical"}),
    ]:
        with pytest.raises(TransferError):
            cls(**kwargs)
