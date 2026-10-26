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
