import pytest
from harbor.models.trial.config import AgentConfig, TrialConfig

from memweave_eval.actor_adapter import PAIRED_PI, RSI_PI, ActorAdapter


@pytest.mark.parametrize(
    ("variant", "asset_only", "entry"),
    [
        ("pi-native", False, "native_agent:NativePi"),
        ("pi-memweave", False, "pilot_paid:PaidPi"),
        ("pi-memweave", True, "pilot_runtime:PilotPi"),
    ],
)
def test_paired_protocol_selects_only_the_actor(variant, asset_only, entry):
    options = {"variant": variant, "asset_only": asset_only}
    config = PAIRED_PI.agent("deepseek/deepseek-flash", options)
    assert AgentConfig.model_validate(config).import_path == entry
    assert config == {"import_path": entry, "model_name": "deepseek/deepseek-flash",
                      "kwargs": options}


def test_future_driver_uses_same_task_and_trusted_guards(tmp_path):
    agent = RSI_PI.agent("deepseek/deepseek-flash", {
        "variant": "pi-memweave", "package_sha256": "a" * 64,
        "evaluation_broker_client": "/private/one-scoped-client",
    }, allowed_hosts=["memweave-broker.internal"])
    config = TrialConfig.model_validate({
        "task": {"path": str(tmp_path)}, "agent": {**agent, "override_timeout_sec": 37},
    })
    successor = ActorAdapter(native=RSI_PI.native, plugin="maintainer_sdk:SdkActor",
                             installer=RSI_PI.installer)
    rebound = successor.bind_trial(config, previous=RSI_PI)
    expected = config.model_dump()
    expected["agent"]["import_path"] = "maintainer_sdk:SdkActor"
    assert rebound.model_dump() == expected
    assert config.agent.import_path == RSI_PI.plugin
    assert RSI_PI.bind_trial(config, previous=RSI_PI) is config


@pytest.mark.parametrize("name", ["oracle", "nop"])
def test_actor_cannot_replace_official_control(tmp_path, name):
    config = TrialConfig.model_validate({"task": {"path": str(tmp_path)}, "agent": {"name": name}})
    with pytest.raises(ValueError):
        PAIRED_PI.bind_trial(config, previous=PAIRED_PI)


def test_unknown_actor_or_wrong_registered_arm_rejected(tmp_path):
    with pytest.raises(ValueError):
        RSI_PI.agent("deepseek/deepseek-flash", {"variant": "experimental"})
    with pytest.raises(ValueError):
        PAIRED_PI.agent("deepseek/deepseek-flash", {"variant": "pi-native", "asset_only": True})
    config = TrialConfig.model_validate({
        "task": {"path": str(tmp_path)},
        "agent": {"import_path": PAIRED_PI.plugin, "kwargs": {"variant": "pi-native"}},
    })
    with pytest.raises(ValueError):
        PAIRED_PI.bind_trial(config, previous=PAIRED_PI)


@pytest.mark.parametrize("override", [
    {"install_only": False},
    {"kwargs": {"prepare_only": False}}, {"kwargs": {"auth_path": "/private/auth.json"}},
    {"kwargs": {"evaluation_broker_client": "/private/client"}},
])
def test_install_binding_has_no_model_or_verifier_authority(tmp_path, override):
    options = {"variant": "pi-memweave", "asset_only": True, "prepare_only": True, "auth_path": ""}
    options.update(override.get("kwargs", {}))
    raw = {"task": {"path": str(tmp_path)}, "install_only": True, "verifier": {"disable": True},
           "agent": PAIRED_PI.agent("test/model", options)}
    raw.update({k: v for k, v in override.items() if k != "kwargs"})
    config = TrialConfig.model_validate(raw)
    with pytest.raises(ValueError, match="install"):
        PAIRED_PI.bind_trial(config, previous=PAIRED_PI)


def test_harbor_install_trial_keeps_verification_disabled(tmp_path):
    options = {"variant": "pi-memweave", "asset_only": True, "prepare_only": True}
    config = TrialConfig.model_validate({"task": {"path": str(tmp_path)}, "install_only": True,
                                         "agent": PAIRED_PI.agent("test/model", options)})
    assert config.verifier.disable
    assert PAIRED_PI.bind_trial(config, previous=PAIRED_PI) is config


def test_operator_can_change_new_jobs_without_changing_historical_qualification(tmp_path):
    from test_rsi_runtime import config as rsi_config
    from test_spec import configuration

    from memweave_eval.rsi_runtime import build_single_job
    from memweave_eval.runner import build_job_config
    from memweave_eval.spec import Experiment

    successor = ActorAdapter(RSI_PI.native, "integration:FutureDriver", RSI_PI.installer)
    spec = rsi_config(tmp_path)
    single = build_single_job(spec, tmp_path, "new", tmp_path, "tb4", variant="pi-memweave",
                              adapter=successor)
    pooled = build_job_config(Experiment.model_validate(configuration(tmp_path)), tmp_path, "new",
                              [tmp_path], variant="pi-memweave", adapter=successor)
    assert single["agents"][0]["import_path"] == pooled["agents"][0]["import_path"] == successor.plugin
    control = build_single_job(spec, tmp_path, "official", tmp_path, "tb4", control="oracle",
                               adapter=successor)
    assert control["agents"] == [{"name": "oracle"}]
    assert RSI_PI.entry("pi-memweave") == "memweave_eval.pi_agent:ExperimentPi"


def test_frozen_worker_uses_the_registered_binding_and_restores_harbor(tmp_path, monkeypatch):
    from harbor.trial.trial import Trial

    from memweave_eval.actor_adapter import PAIRED_RUNTIME, run_paired_worker
    from memweave_eval.storage import file_digest

    calls = []

    async def capture(cls, config):
        calls.append(config)

    monkeypatch.setattr(Trial, "create", classmethod(capture))
    entry = tmp_path / "worker.py"
    entry.write_text(
        "import asyncio, sys\n"
        "from harbor.models.trial.config import TrialConfig\n"
        "from harbor.trial.trial import Trial\n"
        "cfg = TrialConfig.model_validate_json(open(sys.argv[1]).read())\n"
        "asyncio.run(Trial.create(cfg))\n"
    )
    trial = TrialConfig.model_validate({"task": {"path": str(tmp_path)},
                                        "agent": PAIRED_PI.agent("test/model", {"variant": "pi-memweave"})})
    config = tmp_path / "trial.json"
    config.write_text(trial.model_dump_json())
    future = ActorAdapter(PAIRED_PI.native, "integration:FutureDriver", PAIRED_PI.installer)
    run_paired_worker(entry, file_digest(entry), [str(config)], adapter=future)
    assert calls == [future.bind_trial(trial, previous=PAIRED_PI)]
    assert Trial.create.__func__ is capture
    run_paired_worker(entry, file_digest(entry), [str(config)])
    assert calls[-1] == PAIRED_RUNTIME.bind_trial(trial, previous=PAIRED_PI)
    expected = trial.model_dump()
    expected['agent']['import_path'] = PAIRED_RUNTIME.plugin
    assert calls[-1].model_dump() == expected
    with pytest.raises(ValueError, match="changed"):
        run_paired_worker(entry, "0" * 64, [str(config)], adapter=future)
