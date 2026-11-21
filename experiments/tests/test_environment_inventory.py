import asyncio
import json

import pytest
from harbor.environments.base import ExecResult

from memweave_eval.environment_inventory import dependency_inventory


class Image:
    def __init__(self, *, pip="absent", packages=None, pip_error=False):
        self.pip = pip
        self.packages = [] if packages is None else packages
        self.pip_error = pip_error
        self.commands = []

    async def execute(self, *, command, user, timeout_sec):
        assert user == "root" and timeout_sec == 20
        self.commands.append(command)
        if command == "command -v python3":
            return ExecResult(stdout="/usr/bin/python3\n", return_code=0)
        if "find_spec" in command:
            return ExecResult(stdout=self.pip + "\n", return_code=0)
        if "-m pip" in command:
            if self.pip_error:
                return ExecResult(stdout="unexpected pip failure", return_code=1)
            assert self.pip == "present"
        else:
            assert "from importlib.metadata import distributions" in command
        return ExecResult(stdout=json.dumps(self.packages), return_code=0)


def test_missing_pip_uses_real_metadata_without_installing_or_trying_pip():
    image = Image()
    result = asyncio.run(dependency_inventory(image.execute))
    assert result == {"packages": [], "package_inventory_source": "importlib.metadata"}
    assert len(image.commands) == 3
    assert not any("-m pip" in c or "install" in c for c in image.commands)
    assert all("-B" in c for c in image.commands[1:])


def test_existing_pip_retains_original_distribution_names_and_versions():
    packages = [{"name": "pytest", "version": "9.1.1"}]
    image = Image(pip="present", packages=packages)
    assert asyncio.run(dependency_inventory(image.execute)) == {
        "packages": packages, "package_inventory_source": "pip",
    }


def test_absent_python_is_reported_explicitly():
    async def missing(**kwargs):
        assert kwargs["command"] == "command -v python3"
        return ExecResult(return_code=1)

    assert asyncio.run(dependency_inventory(missing)) == {
        "packages": None, "package_inventory_source": "python3-absent",
    }


def test_existing_broken_pip_cannot_turn_into_an_empty_inventory():
    image = Image(pip="present", pip_error=True)
    with pytest.raises(ValueError, match="dependency inventory failed"):
        asyncio.run(dependency_inventory(image.execute))
    assert not any("from importlib.metadata" in c for c in image.commands)


@pytest.mark.parametrize("packages", [[{"name": "pytest"}], ["pytest"], {"pytest": "9.1.1"}])
def test_invalid_distribution_metadata_is_rejected(packages):
    with pytest.raises(ValueError, match="invalid Python dependency inventory"):
        asyncio.run(dependency_inventory(Image(packages=packages).execute))
