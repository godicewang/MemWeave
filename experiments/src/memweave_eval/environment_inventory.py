"""Read distributions from an original task image without installing packages."""

import json
import re
import shlex

_PIP_LIST = "python3 -B -m pip list --format=json --disable-pip-version-check"
_PIP_AVAILABLE = (
    "python3 -B -c 'from importlib.util import find_spec; "
    'print("present" if find_spec("pip") is not None else "absent")\''
)
_METADATA = """
import json
from importlib.metadata import distributions

packages = [{"name": dist.metadata["Name"], "version": dist.version}
            for dist in distributions()]
print(json.dumps(sorted(packages, key=lambda package: (package["name"].lower(),
                                                      package["version"]))))
"""


async def dependency_inventory(exec_command):
    """Use real interpreter/module probes; preserve failures and absent Python."""
    async def run(command):
        return await exec_command(command=command, user="root", timeout_sec=20)

    interpreter = await run("command -v python3")
    if interpreter.return_code == 1 and not interpreter.stdout and not interpreter.stderr:
        return {"packages": None, "package_inventory_source": "python3-absent"}
    path = (interpreter.stdout or "").strip()
    if interpreter.return_code or interpreter.stderr or not re.fullmatch(r"/[^\s]+", path):
        raise ValueError("Python interpreter probe failed")

    pip_probe = await run(_PIP_AVAILABLE)
    pip_state = (pip_probe.stdout or "").strip()
    if pip_probe.return_code or pip_probe.stderr or pip_state not in ("present", "absent"):
        raise ValueError("Python pip availability probe failed")
    if pip_state == "absent":
        result = await run("python3 -B -c " + shlex.quote(_METADATA))
        source = "importlib.metadata"
    else:
        result = await run(_PIP_LIST)
        source = "pip"
    if result.return_code:
        raise ValueError("Python dependency inventory failed")
    try:
        packages = json.loads(result.stdout)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid Python dependency inventory") from error
    if not isinstance(packages, list) or any(
        not isinstance(package, dict)
        or any(not isinstance(package.get(key), str) or not package[key] for key in ("name", "version"))
        for package in packages
    ):
        raise ValueError("invalid Python dependency inventory")
    return {"packages": packages, "package_inventory_source": source}
