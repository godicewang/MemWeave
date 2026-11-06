"""The RSI cleanup must leave no executable route into retired evaluations."""
import pytest

from memweave_eval.cli import main
from memweave_eval.pi_agent import PiExperimentOptions


def test_cli_has_only_offline_validation(capsys):
    with pytest.raises(SystemExit) as error:
        main(['--help'])
    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert '{validate}' in help_text
    for retired in ('score-report', 'score-cases', 'primary-review', 'finance-report'):
        assert retired not in help_text
    for command in ('run', 'report', 'score-cases'):
        with pytest.raises(SystemExit) as rejected:
            main([command, 'unused'])
        assert rejected.value.code == 2


def test_pi_adapter_has_no_task_overlay_or_progress_options():
    fields = PiExperimentOptions.model_fields
    for retired in ('evaluation_task_configs', 'evaluation_progress_after_returns',
                    'evaluation_task_timeouts', 'evaluation_sealed_tasks'):
        assert retired not in fields
