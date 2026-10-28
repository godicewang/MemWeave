import json
import subprocess
from types import SimpleNamespace

from memweave_eval.campaign import ObservationService


def test_inventory_explicitly_disables_size_but_keeps_json_metadata(tmp_path, monkeypatch):
    service = ObservationService(tmp_path)
    service.observer = SimpleNamespace(tick=lambda: {"estimated_cost_usd": 0.25})
    row = {"ID": "abc", "Names": "owned-trial-main", "State": "running", "Labels": "trial=owned"}

    def query(command, **kwargs):
        assert command[:2] == ["docker", "ps"]
        assert "--size=false" in command, "full JSON otherwise implicitly asks snapshotter sizes"
        assert command[-1] == "{{json .}}"
        service.halt.set()
        return json.dumps(row) + "\n"

    monkeypatch.setattr(subprocess, "check_output", query)
    service.run()
    assert service.error is None
    assert service.status["estimated_cost_usd"] == 0.25
    assert json.loads((tmp_path / "containers.json").read_text())["containers"] == [row]


def test_inventory_failure_is_unknown_and_still_stops_observation(tmp_path, monkeypatch):
    service = ObservationService(tmp_path)
    service.observer = SimpleNamespace(tick=lambda: {"estimated_cost_usd": 0.25})

    def failure(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "check_output", failure)
    service.run()
    assert service.error and "CalledProcessError" in service.error
    assert not (tmp_path / "containers.json").exists()
