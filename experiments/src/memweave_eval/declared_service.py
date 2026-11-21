"""Evaluator-owned binding of a task's original public auxiliary service."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

import yaml

from . import rsi_pilot_exports as exports
from . import rsi_pilot_transfer as transfer
from .rsi_pilot_transfer import TransferError
from .rsi_resources import ResourceAmounts


def _project_query(endpoint, project, **kwargs):
    label = {"label": ["com.docker.compose.project=" + project]}
    return endpoint + "?" + urlencode({**kwargs, "filters": json.dumps(label)})


def require_retired(query, daemon, project):
    if query("/info").get("ID") != daemon:
        raise TransferError("service retirement daemon differs")
    if query(_project_query("/containers/json", project, all="1")) != []:
        raise TransferError("task service project still owns a container")
    if query(_project_query("/networks", project)) != []:
        raise TransferError("task service project still owns a network")


@dataclass(frozen=True)
class DeclaredService:
    name: str
    declaration_sha256: str
    image: str
    image_id: str
    cpus: int
    memory_mb: int
    port: int

    def compose(self, path: Path) -> dict:
        if path.is_symlink() or not path.is_file():
            raise TransferError("missing original task service declaration")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.declaration_sha256:
            raise TransferError("original task service declaration changed")
        document = yaml.safe_load(raw)
        if set(document) != {"services"} or set(document["services"]) != {self.name}:
            raise TransferError("unexpected task service declaration")
        side = document["services"][self.name].copy()
        keys = {
            "build",
            "command",
            "init",
            "expose",
            "cpus",
            "mem_limit",
            "pids_limit",
            "read_only",
            "tmpfs",
            "cap_drop",
            "cap_add",
            "security_opt",
            "healthcheck",
        }
        if (
            set(side) != keys
            or side["expose"] != [str(self.port)]
            or side["cpus"] != f"${{CPUS:-{self.cpus}}}"
            or side["mem_limit"] != f"${{MEMORY:-{self.memory_mb}M}}"
        ):
            raise TransferError("unexpected task service options or resource defaults")
        del side["build"]
        side.update(
            image=self.image,
            pull_policy="never",
            cpus=self.cpus,
            mem_limit=f"{self.memory_mb}M",
            networks=["task-service"],
        )
        return {
            "services": {
                "main": {
                    "networks": ["default", "task-service"],
                    "depends_on": {self.name: {"condition": "service_healthy"}},
                },
                self.name: side,
            },
            "networks": {"default": {}, "task-service": {"internal": True}},
        }

    def reservation(self, actor, verifier):
        """Actor and service coexist. A physical retirement gate precedes grading."""
        return ResourceAmounts(
            max(actor["cpus"] + self.cpus, verifier["cpus"]) + 0.25,
            max(actor["memory_mb"] + self.memory_mb, verifier["memory_mb"]) + 128,
            actor["storage_mb"] + verifier["storage_mb"] + 1,
        )

    def observe(self, query, daemon, project, actor_id):
        if query("/info").get("ID") != daemon:
            raise TransferError("task service daemon differs")
        rows = query(_project_query("/containers/json", project, all="1"))
        ids = {row["Labels"].get("com.docker.compose.service"): row["Id"] for row in rows}
        if (
            len(rows) != 2
            or set(ids) != {"main", self.name}
            or ids["main"] != actor_id
            or not re.fullmatch("[0-9a-f]{64}", ids[self.name])
        ):
            raise TransferError("task and service do not own exactly two containers")
        side = query("/containers/" + ids[self.name] + "/json")
        host, config, state = side["HostConfig"], side["Config"], side["State"]
        labels = config["Labels"]
        image = query("/images/" + self.image_id + "/json")
        if (
            side["Id"] != ids[self.name]
            or side["Image"] != self.image_id
            or image["Id"] != self.image_id
            or (image["Os"], image["Architecture"]) != ("linux", "arm64")
            or labels.get("com.docker.compose.project") != project
            or labels.get("com.docker.compose.service") != self.name
            or state.get("Running") is not True
            or state.get("Health", {}).get("Status") != "healthy"
            or state.get("Restarting")
            or state.get("Paused")
            or config.get("Env") != image["Config"].get("Env")
            or config.get("Cmd") != ["python", "/srv/server.py"]
            or set(config.get("ExposedPorts", {})) != {f"{self.port}/tcp"}
        ):
            raise TransferError("task service image, command, environment or health differs")
        tmpfs = (host.get("Tmpfs") or {}).get("/tmp", "").split(",")
        if (
            host.get("Privileged") is not False
            or side["Mounts"]
            or host.get("Binds")
            or host.get("PortBindings")
            or host.get("PublishAllPorts")
            or host.get("NanoCpus") != self.cpus * 10**9
            or host.get("Memory") != self.memory_mb * 2**20
            or host.get("Init") is not True
            or host.get("ReadonlyRootfs") is not True
            or host.get("PidsLimit") != 128
            or set(host.get("Tmpfs") or {}) != {"/tmp"}
            or set(tmpfs) != {"rw", "noexec", "nosuid", "size=128m"}
            or set(host.get("CapDrop") or []) != {"ALL"}
            or {cap.removeprefix("CAP_") for cap in host.get("CapAdd") or []}
            != {"KILL", "SETGID", "SETUID"}
            or not (
                {"no-new-privileges", "no-new-privileges:true"} & set(host.get("SecurityOpt") or [])
            )
        ):
            raise TransferError("task service resource or isolation mismatch")
        networks = side["NetworkSettings"]["Networks"]
        if len(networks) != 1:
            raise TransferError("task service has an unexpected network")
        name, binding = next(iter(networks.items()))
        net = query("/networks/" + binding["NetworkID"])
        if (
            net["Id"] != binding["NetworkID"]
            or net["Name"] != name
            or net["Internal"] is not True
            or net["Labels"].get("com.docker.compose.project") != project
            or net["Labels"].get("com.docker.compose.network") != "task-service"
            or set(net["Containers"]) != {actor_id, side["Id"]}
        ):
            raise TransferError("task service requires a private two-member network")
        return {
            "daemon": daemon,
            "project": project,
            "actor_id": actor_id,
            "service_id": side["Id"],
            "service_image": self.image_id,
            "private_network_id": net["Id"],
            "private_port": self.port,
            "cpus": self.cpus,
            "memory_mb": self.memory_mb,
        }


NOISY_EVALUATOR = DeclaredService(
    name="public-evaluator",
    declaration_sha256="cebf0d678b0d404cc1e39cff6035f4641c5106b43d604f1faacae632cc46cb6f",
    image="rsi-public-noisy:original-service",
    image_id="sha256:3264c8226bde9a1258dbc055c803ccb6e71843b105442277914e0ffe693c1a75",
    cpus=4,
    memory_mb=4096,
    port=8080,
)


class DeclaredServiceEnvironment:
    """Mixin for the evaluator's existing frozen no-mount Harbor environment."""

    declared_service = NOISY_EVALUATOR
    _service_dir = None
    _service_retired = False

    @property
    def _environment_docker_compose_path(self):
        if self._service_dir is not None:
            return Path(self._service_dir.name) / "compose.json"
        return super()._environment_docker_compose_path

    def _validate_task_compose(self):
        if self._pilot_role == "verifier":
            return super()._validate_task_compose()
        if (
            self._pilot_role not in {"actor", "oracle", "nop"}
            or self._enable_egress_control
            or self.network_policy.network_mode.value != "public"
            or self.extra_docker_compose_paths
        ):
            raise TransferError("task service requires the declared public actor role")
        contents = self.declared_service.compose(super()._environment_docker_compose_path)
        self._service_dir = TemporaryDirectory(prefix="rsi-task-service-")
        self._environment_docker_compose_path.write_text(json.dumps(contents))

    def _service_receipt(self, name, value):
        path = (
            exports.VOLUME
            / "ledger/new80/observations"
            / self._archive.trial_id
            / (self._pilot_role + "-service-" + name + ".json")
        )
        data = exports.encoded(value)
        if path.is_file() and exports.read(path, exports.MAX_MARKER) == data:
            return
        exports.write_new(path, data)

    async def start(self, *args, **kwargs):
        if self._service_retired:
            raise TransferError("retired service requires a fresh trial")
        if self._service_dir is None:
            return await super().start(*args, **kwargs)
        api = self._archive
        image = await self._io(api._json, "/images/" + self.declared_service.image + "/json")
        if image.get("Id") != self.declared_service.image_id:
            raise TransferError("task service prebuilt image differs")
        try:
            await super().start(*args, **kwargs)
            actor_id = await self._io(api._container)
            proof = await self._io(
                self.declared_service.observe, api._json, transfer.DAEMON, api.project, actor_id
            )
            self._service_receipt("active", proof)
        except BaseException:
            await self.stop(delete=True)
            raise

    async def stop(self, delete):
        if self._service_retired:
            return
        if self._service_dir is None:
            return await super().stop(delete)
        api = self._archive
        await super().stop(delete)
        await self._io(require_retired, api._json, transfer.DAEMON, api.project)
        self._service_receipt(
            "retired",
            {
                "daemon": transfer.DAEMON,
                "project": api.project,
                "containers_and_networks_absent": True,
            },
        )
        self._service_retired = True
        self._service_dir.cleanup()
        self._service_dir = None
