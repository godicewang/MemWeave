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
    thinking: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None


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
    concurrency: Annotated[int, Field(strict=True, ge=1, le=4)] = 2
    repetitions: PositiveInt = 1
    automatic_trial_retries: Literal[0] = 0
    paired_concurrent: StrictBool = False

    @model_validator(mode='after')
    def capacity(self):
        if type(self) is Execution and self.concurrency>2 and (not self.paired_concurrent or self.concurrency!=4):
            raise ValueError('four instances require paired concurrent admission')
        return self


class Limits(StrictModel):
    max_cost_usd: Annotated[float, Field(strict=True, gt=0)]
    max_elapsed_seconds: PositiveInt


class Evaluation(StrictModel):
    primary_default: StrictBool = False
    primary_contract: Path | None = None
    gold: Path
    deadline_utc: str
    admission_budget_usd: Annotated[float, Field(strict=True, gt=0, le=29)]
    output_tokens: Annotated[int, Field(strict=True, gt=0, le=384000)] = 16384
    budget_id: Identifier
    arm_budget_usd: Annotated[float, Field(strict=True, gt=0)] = 12.0
    progress_after_returns: Annotated[int, Field(strict=True, ge=0)] = 80
    episode_budget_usd: Annotated[float,Field(strict=True,gt=0)] | None = None
    frozen_preparation: Path | None = None
    quota_backend: Literal['python','node'] = 'python'
    per_task_arm_caps: StrictBool = False
    resources: dict[str, Annotated[int, Field(strict=True,gt=0)]] | None = None
    sealed_tasks: list[Identifier] = Field(default_factory=list)
    finalization_reserve_seconds: Annotated[int,Field(strict=True,ge=1500)] = 1500
    control_expectations: dict = Field(default_factory=dict)
    canary_preflight: StrictBool = False
    agent_timeouts: dict[str, PositiveInt] = Field(default_factory=dict)
    budget_arm_limits: dict[str, Annotated[float,Field(strict=True,gt=0)]] | None = None

    @model_validator(mode="after")
    def deadline(self):
        from datetime import datetime
        value = datetime.fromisoformat(self.deadline_utc)
        if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
            raise ValueError('evaluation deadline must be explicit UTC')
        if 2*self.arm_budget_usd > self.admission_budget_usd:
            raise ValueError('equal arm budgets must fit the global admission budget')
        if self.budget_arm_limits and sum(self.budget_arm_limits.values())>self.admission_budget_usd:
            raise ValueError('registered budget arms exceed shared admission budget')
        if self.resources and (set(self.resources)-{'cpus','memory_mb','storage_mb'}):
            raise ValueError('unknown resource adaptation')
        if self.primary_default and (self.progress_after_returns!=0 or self.output_tokens!=384000 or self.resources or self.agent_timeouts or self.sealed_tasks):
            raise ValueError('primary_default forbids evaluation steering, sampling/time/resource overrides or sealed adapters; output_tokens384000 is admission ceiling only')
        return self


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
    evaluation: Evaluation | None = None
    root: Path = Field(default_factory=lambda: Path.home() / ".local/share/memweave-experiments")

    @model_validator(mode="after")
    def check_contract(self):
        if sorted(v.id for v in self.variants) != ["pi-memweave", "pi-native"]:
            raise ValueError("exactly the native and MemWeave variants are required")
        self.root = outside_repository(self.root)
        if self.evaluation and self.evaluation.admission_budget_usd >= self.limits.max_cost_usd:
            raise ValueError('admission limit must leave a safety reserve')
        if self.evaluation and self.evaluation.primary_default and self.model.thinking is not None:
            raise ValueError('primary_default requires Pi thinking default without evaluator override')
        return self


class Suite(StrictModel):
    schema_version: Literal[1] = 1
    id: Literal["terminal-bench-4", "swe-bench-pro-v2", "swe-marathon"]
    repository: str
    revision: Commit
    tasks_dir: str
    protocol: Literal["tb4", "swe-pro-v2", "swe-marathon"]

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
            "swe-marathon": (
                "https://github.com/abundant-ai/swe-marathon.git", "tasks", "swe-marathon",
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
    task_ids: list[Identifier] | None = None

    @model_validator(mode='after')
    def fixed_tasks(self):
        if self.task_ids is not None and (len(self.task_ids) != self.count or len(set(self.task_ids)) != self.count):
            raise ValueError('fixed task IDs must match count without duplicates')
        return self


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
    if spec.evaluation:
        spec.evaluation.gold = (path.parent / spec.evaluation.gold).resolve()
        if spec.evaluation.primary_contract:
            spec.evaluation.primary_contract=(path.parent/spec.evaluation.primary_contract).resolve()
        if spec.evaluation.frozen_preparation:
            spec.evaluation.frozen_preparation=(path.parent/spec.evaluation.frozen_preparation).resolve()
    suite = Suite.model_validate(load_yaml(spec.suite))
    subset = Subset.model_validate(load_yaml(spec.subset))
    validate_primary_inputs(spec,suite,subset)
    if suite.protocol == "swe-pro-v2" and spec.execution.platform != "linux/amd64":
        raise ValueError("Pro V2 requires its official linux/amd64 images")
    if suite.protocol == 'swe-marathon' and (
        not spec.evaluation or not spec.execution.paired_concurrent or not subset.task_ids
    ):
        raise ValueError('Marathon requires fixed cases, request admission and concurrent pairs')
    if (spec.evaluation and spec.evaluation.per_task_arm_caps
            and subset.count*len(spec.variants)*spec.evaluation.arm_budget_usd>spec.evaluation.admission_budget_usd):
        raise ValueError('all task-arm allocations must fit the new shared budget')
    return spec, suite, subset


def validate_primary_inputs(spec,suite,subset):
    if not spec.evaluation or not spec.evaluation.primary_default:return
    import json

    from .primary_report import validate_contract

    if not spec.evaluation.primary_contract:
        raise ValueError('primary_default requires an approved frozen primary_contract before running')
    contract=validate_contract(json.loads(spec.evaluation.primary_contract.read_text()))
    if spec.model.id!='deepseek-flash':raise ValueError('primary authority pricing and endpoint are frozen for deepseek-flash')
    price=contract.get('pricing',{})
    if (price.get('currency')!='USD' or price.get('requested_model_id')!='deepseek-flash'
            or price.get('per_million_tokens')!={'input':.3,'cache_read':.006,'output':1.2}):
        raise ValueError('primary contract price must match trusted authority peak USD tariff')
    if contract.get('source_commit')!=suite.revision:
        raise ValueError('primary source revision and scoring contract disagree')
    if subset.task_ids!=[contract.get('task_name')]or subset.count!=1 or spec.execution.repetitions!=1:
        raise ValueError('primary_default admits exactly the reviewed first-case pair')
    if not spec.execution.paired_concurrent or spec.execution.concurrency!=2:
        raise ValueError('primary_default requires concurrent native/plugin arms')
    primary_actor_seconds(spec)


def primary_actor_seconds(spec):
    """Only an explicit case-versioned authorization may shorten task time."""
    if not spec.evaluation or not spec.evaluation.primary_default:return None
    import json
    c=json.loads(spec.evaluation.primary_contract.read_text());p=c.get('execution_policy')
    if p is None:return None
    a=c.get('budget_authorization')or{};seconds=p.get('actor_seconds')if isinstance(p,dict)else None
    if (type(seconds)is not int or not 0<seconds<=28800 or p.get('source_actor_seconds')!=28800
            or p.get('kind')!='authorized_symmetric_time_adaptation' or not p.get('reason')
            or c.get('case_id')!='TB-01' or c.get('formal_run_allowed')is not True
            or not a.get('evidence_reference')or type(a.get('maximum_run_seconds'))is not int
            or seconds>a['maximum_run_seconds']or spec.limits.max_elapsed_seconds>a['maximum_run_seconds']):
        raise ValueError('explicit case-versioned symmetric time authorization required')
    return seconds


def require_primary_authorization(spec,*,now=None):
    """A reviewed score design does not itself authorize new model expenditure."""
    if not spec.evaluation or not spec.evaluation.primary_default:return
    import json
    import time
    from datetime import datetime

    c=json.loads(spec.evaluation.primary_contract.read_text());a=c.get('budget_authorization')
    if c.get('formal_run_allowed')is not True or not isinstance(a,dict):
        raise ValueError('primary paid run blocked: new explicit budget and time authorization required')
    try:
        dates=[datetime.fromisoformat(a[k])for k in ('start_utc','deadline_utc')]
        if any(d.tzinfo is None for d in dates):raise ValueError('timezone')
        start,end=(d.timestamp()for d in dates)
        deadline=datetime.fromisoformat(spec.evaluation.deadline_utc).timestamp()
    except (ValueError,KeyError,TypeError):raise ValueError('explicit authorized UTC window required')from None
    maximum=a.get('maximum_usd')
    if (type(maximum)not in(int,float)or not 0<maximum< float('inf')or not a.get('evidence_reference')
            or end<=start or not start<=(time.time()if now is None else now)<end
            or deadline>end or spec.evaluation.admission_budget_usd>maximum
            or spec.limits.max_cost_usd>maximum):
        raise ValueError('primary config exceeds or lacks the recorded budget/window authorization')
