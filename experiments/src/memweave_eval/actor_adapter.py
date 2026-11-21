"""Trusted Harbor actor bindings, independent of task, environment and verifier."""

import runpy
import sys
from dataclasses import dataclass
from pathlib import Path

from harbor.models.trial.config import TrialConfig

from .storage import file_digest


@dataclass(frozen=True)
class ActorAdapter:
    native: str
    plugin: str
    installer: str

    def entry(self, variant: str, *, asset_only: bool = False) -> str:
        if type(asset_only) is not bool:
            raise ValueError("asset_only must be a boolean")
        if variant == "pi-memweave":
            return self.installer if asset_only else self.plugin
        if variant == "pi-native" and not asset_only:
            return self.native
        raise ValueError("unsupported actor variant or installation mode")

    def agent(self, model: str, options: dict, *, allowed_hosts: list[str] | None = None) -> dict:
        entry = self.entry(options["variant"], asset_only=options.get("asset_only", False))
        agent = {"import_path": entry, "model_name": model, "kwargs": options}
        if allowed_hosts is not None:
            agent["extra_allowed_hosts"] = allowed_hosts
        return agent

    def bind_trial(self, trial: TrialConfig, *, previous: "ActorAdapter") -> TrialConfig:
        """Replace only a known host-side driver on a new, not-yet-started actor trial."""
        agent = trial.agent
        if agent.name is not None or "variant" not in agent.kwargs:
            raise ValueError("only a registered actor trial can be rebound")
        variant = agent.kwargs["variant"]
        asset_only = agent.kwargs.get("asset_only", False)
        if previous.entry(variant, asset_only=asset_only) != agent.import_path:
            raise ValueError("trial does not reference the expected actor binding")
        if asset_only and (not trial.install_only or not trial.verifier.disable
                           or agent.kwargs.get("prepare_only") is not True
                           or agent.kwargs.get("auth_path") or agent.kwargs.get("evaluation_broker_client")):
            raise ValueError("installation-only trial has incompatible model or verifier authority")
        entry = self.entry(variant, asset_only=asset_only)
        if entry == agent.import_path:
            return trial
        return trial.model_copy(update={"agent": agent.model_copy(update={"import_path": entry})})


_EXPERIMENT_PI = "memweave_eval.pi_agent:ExperimentPi"
RSI_PI = ActorAdapter(native=_EXPERIMENT_PI, plugin=_EXPERIMENT_PI, installer=_EXPERIMENT_PI)
PAIRED_PI = ActorAdapter(native="native_agent:NativePi", plugin="pilot_paid:PaidPi",
                         installer="pilot_runtime:PilotPi")
PAIRED_RUNTIME = ActorAdapter(native=PAIRED_PI.native,
                              plugin="memweave_eval.paired_runtime:PairedPi",
                              installer=PAIRED_PI.installer)


def run_paired_worker(entry: Path, expected_sha256: str, arguments: list[str], *,
                      adapter: ActorAdapter = PAIRED_RUNTIME) -> None:
    """Run a maintainer-selected, frozen legacy entry in its dedicated worker process."""
    from harbor.trial.trial import Trial

    if entry.is_symlink() or not entry.is_file() or file_digest(entry) != expected_sha256:
        raise ValueError("registered paired worker changed")
    original = Trial.__dict__["create"]
    create = Trial.create

    async def create_trial(cls, config):
        if config.agent.name is None and config.source_trial is None and "variant" in config.agent.kwargs:
            config = adapter.bind_trial(config, previous=PAIRED_PI)
        return await create(config)

    argv, search_path = sys.argv, sys.path
    try:
        Trial.create = classmethod(create_trial)
        sys.argv = [str(entry), *arguments]
        sys.path = [str(entry.parent), *search_path]
        runpy.run_path(str(entry), run_name="__main__")
    finally:
        sys.argv, sys.path = argv, search_path
        Trial.create = original
