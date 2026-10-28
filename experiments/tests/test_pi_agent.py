import asyncio

from memweave_eval.pi_agent import ExperimentPi, PiExperimentOptions


def test_wrapper_keeps_native_pi_defaults_and_full_memweave_entry():
    options = PiExperimentOptions(
        version="1.4.0",
        node_version="24.22.0",
        variant="pi-memweave",
        package_path="/tmp/subject.tgz",
        package_sha256="b" * 64,
        auth_path="/tmp/auth.json",
        protocol="tb4",
        thinking="off",
    )
    assert options.version == "1.4.0"
    assert options.extension is None
    assert options.max_turns is None


def test_exec_preserves_child_failure_code_and_pro_budget(tmp_path):
    from harbor.agents.installed.pi import Pi

    calls = []

    async def capture(self, environment, command, **kwargs):
        calls.append(command)
        return object()

    # Test the public exec wrapper, no provider or container is used.
    from unittest.mock import patch

    agent = ExperimentPi(
        logs_dir=tmp_path,
        model_name="deepseek/deepseek-flash",
        version="1.4.0",
        node_version="24.22.0",
        variant="pi-native",
        package_path="/tmp/a.tgz",
        package_sha256="a" * 64,
        auth_path="/tmp/auth.json",
        protocol="swe-pro-v2",
    )
    with patch.object(Pi, "exec_as_agent", capture):
        asyncio.run(agent.exec_as_agent(object(), "pi --print --mode json x | tee log"))
    assert "pipefail" in calls[0]
    assert "timeout -k 30 2940" in calls[0]
    assert "system-prompt" not in calls[0]


def test_pro_network_probe_time_cannot_consume_patch_capture_reserve(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch

    import pytest
    from harbor.agents.installed.pi import Pi

    agent = ExperimentPi(
        logs_dir=tmp_path,
        model_name="deepseek/deepseek-flash",
        version="1.4.0",
        node_version="24.22.0",
        variant="pi-native",
        package_path="/tmp/p.tgz",
        package_sha256="a" * 64,
        auth_path="/tmp/auth.json",
        protocol="swe-pro-v2",
    )
    agent._agent_started = 100

    async def fail(self, env, command, **kwargs):
        assert "timeout -k 30 2925 " in command
        return SimpleNamespace(return_code=17)

    with (
        patch.object(Pi, "exec_as_agent", fail),
        patch("memweave_eval.pi_agent.time.monotonic", return_value=115),
        pytest.raises(RuntimeError, match="status 17"),
    ):
        asyncio.run(agent.exec_as_agent(object(), "pi --print --mode json x | tee log"))


def test_cached_cli_replaces_only_nvm_bootstrap_and_preserves_native_flags(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch

    from harbor.agents.installed.pi import Pi

    calls = []
    agent = ExperimentPi(version="1.4.0", logs_dir=tmp_path, model_name="deepseek/deepseek-flash",
                         node_version="24.22.0", variant="pi-native", package_path="/tmp/a",
                         package_sha256="a" * 64, auth_path="/tmp/auth", protocol="tb4")
    agent._asset_root = "/root/.local/share/memweave-eval"
    agent._experiment_home = "/root"

    async def capture(self, environment, command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(return_code=0)

    with patch.object(Pi, "exec_as_agent", capture):
        asyncio.run(agent.exec_as_agent(object(),
            '. ~/.nvm/nvm.sh; pi --print --mode json --provider deepseek --session-dir /logs/s test | tee log'))
    command, kwargs = calls[0]
    assert ".nvm" not in command
    assert "node/bin" in command
    assert "--provider deepseek --session-dir /logs/s test | tee log" in command
    assert kwargs["env"]["PI_CODING_AGENT_DIR"] == "/root/.pi/agent"


def test_warm_install_has_no_network_installer_or_auth_in_preparation(tmp_path):
    import json
    from types import SimpleNamespace
    from unittest.mock import patch

    from test_runtime_cache import archive

    from memweave_eval.runtime_cache import descriptor, materialize
    from memweave_eval.storage import file_digest

    desc = descriptor(kind="base", image="fixed")

    async def build(path):
        archive(path)

    asyncio.run(materialize(tmp_path, desc, "node", build, allow_create=True))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"cache": str(tmp_path), "entries": {"fixed": {"base": desc}}}))
    calls, uploads = [], []

    class Environment:
        task_env_config = SimpleNamespace(docker_image="fixed")
        default_user = None

        async def exec(self, command, **kwargs):
            calls.append(command)
            stdout = "/home/test\n/app\n" if "printf" in command else ""
            if "node --version" in command:
                stdout = "v24.22.0\n1.4.0\n"
            return SimpleNamespace(return_code=0, stdout=stdout, stderr="")

        async def upload_file(self, source, target):
            uploads.append(target)

    agent = ExperimentPi(version="1.4.0", logs_dir=tmp_path, model_name="deepseek/deepseek-flash",
        node_version="24.22.0", variant="pi-native", package_path="/missing/a",
        package_sha256="a" * 64, auth_path="/missing/private/auth.json", protocol="tb4",
        prepare_only=True, runtime_plan=str(plan), runtime_plan_sha256=file_digest(plan))
    with patch("memweave_eval.pi_agent.node_download", side_effect=AssertionError("no download")):
        asyncio.run(agent.install(Environment()))
    assert all("npm install" not in call and "curl" not in call for call in calls)
    assert not any(target.endswith("auth.json") for target in uploads)
    assert not any("/memory" in target or "/package" in target for target in uploads)
    setup = json.loads((tmp_path / "experiment-setup.json").read_text())
    assert setup["resources"]["base"]["cache_hit"]
    # A mismatched frozen identity must stop before a credential can be read.
    import pytest

    agent.options.prepare_only = False
    agent.options.runtime_objects = {}
    with pytest.raises(ValueError, match="frozen object"):
        asyncio.run(agent.install(Environment()))
