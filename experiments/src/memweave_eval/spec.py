"""Strict, offline experiment inputs. No imports of Harbor or network clients here."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

REPOSITORY = Path(__file__).resolve().parents[3]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Subject(StrictModel):
    commit: Commit
    package: Path
    sha256: Digest


class Runtime(StrictModel):
    harbor_version: Literal["0.24.0"] = "0.24.0"
    pi_version: Literal["1.4.0"] = "1.4.0"
    node_version: Version


class Model(StrictModel):
    provider: Literal["deepseek"] = "deepseek"
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]+$")]
    api: Literal["openai-completions"] = "openai-completions"
    auth_profile: Literal["memweave-dev"] = "memweave-dev"
    thinking: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]


class Variant(StrictModel):
    id: Literal["pi-native", "pi-memweave"]
    memweave: StrictBool

    @model_validator(mode="after")
    def consistent(self):
        if self.memweave != (self.id == "pi-memweave"):
            raise ValueError("variant ID and MemWeave switch disagree")
        return self


class Execution(StrictModel):
    environment: Literal["docker"] = "docker"
    platform: Literal["linux/amd64", "linux/arm64"]
    concurrency: Annotated[int, Field(strict=True, ge=1, le=2)] = 2
    repetitions: PositiveInt = 1
    automatic_trial_retries: Literal[0] = 0


class Limits(StrictModel):
    max_cost_usd: Annotated[float, Field(strict=True, gt=0)]
    max_elapsed_seconds: PositiveInt


def outside_repository(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError("experiment root must be absolute")
    path = path.resolve()
    if path == REPOSITORY or REPOSITORY in path.parents:
        raise ValueError("runtime data must be outside the MemWeave repository")
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("runtime data must be outside Git working directories")
    return path


class Experiment(StrictModel):
    schema_version: Literal[1]
    experiment_id: Identifier
    suite: Path
    subset: Path
    subject: Subject
    runtime: Runtime
    model: Model
    variants: list[Variant]
    execution: Execution
    limits: Limits
    root: Path = Field(default_factory=lambda: Path.home() / ".local/share/memweave-experiments")

    @model_validator(mode="after")
    def check_contract(self):
        if sorted(v.id for v in self.variants) != ["pi-memweave", "pi-native"]:
            raise ValueError("exactly the native and MemWeave variants are required")
        self.root = outside_repository(self.root)
        return self


class Suite(StrictModel):
    schema_version: Literal[1] = 1
    id: Literal["terminal-bench-4", "swe-bench-pro-v2"]
    repository: str
    revision: Commit
    tasks_dir: str
    protocol: Literal["tb4", "swe-pro-v2"]

    @model_validator(mode="after")
    def official_source(self):
        expected = {
            "terminal-bench-4": (
                "https://github.com/harbor-framework/terminal-bench.git",
                "tasks",
                "tb4",
            ),
            "swe-bench-pro-v2": (
                "https://github.com/scaleapi/SWE-bench_Pro-os.git",
                "v2/tasks",
                "swe-pro-v2",
            ),
        }[self.id]
        if (self.repository, self.tasks_dir, self.protocol) != expected:
            raise ValueError("suite must retain its official source, task root and protocol")
        return self


class Subset(StrictModel):
    count: PositiveInt
    seed: Annotated[str, Field(min_length=1, max_length=200)]
    max_cpus: PositiveInt
    max_memory_mb: PositiveInt
    max_storage_mb: PositiveInt


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("YAML keys must be unique strings")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_yaml(path: Path) -> dict:
    try:
        if path.stat().st_size > 1_000_000:
            raise ValueError("configuration exceeds 1 MB")
        data = yaml.load(path.read_text(), Loader=UniqueLoader)
        if not isinstance(data, dict):
            raise TypeError("configuration must be a mapping")
        # Disallow recursive aliases and non-JSON scalars before model validation.
        import json

        json.dumps(data, allow_nan=False)
        return data
    except (yaml.YAMLError, RecursionError, TypeError) as exc:
        raise ValueError("invalid YAML configuration") from exc


def load_experiment(path: Path) -> tuple[Experiment, Suite, Subset]:
    path = path.resolve()
    spec = Experiment.model_validate(load_yaml(path))
    for name in ("suite", "subset"):
        setattr(spec, name, (path.parent / getattr(spec, name)).resolve())
    spec.subject.package = (path.parent / spec.subject.package.expanduser()).resolve()
    suite = Suite.model_validate(load_yaml(spec.suite))
    subset = Subset.model_validate(load_yaml(spec.subset))
    if suite.protocol == "swe-pro-v2" and spec.execution.platform != "linux/amd64":
        raise ValueError("Pro V2 requires its official linux/amd64 images")
    return spec, suite, subset
