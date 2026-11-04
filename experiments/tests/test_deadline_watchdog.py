import json
from types import SimpleNamespace

from memweave_eval.deadline_watchdog import monitor


def test_query_and_kill_failures_retry_until_positive_stop_confirmation(tmp_path, monkeypatch):
    import memweave_eval.deadline_watchdog as module

    clock = [0]
    queries = [0]
    kills = [0]

    def run(args, **_):
        assert args[0] == "docker"
        if args[1] == "ps":
            assert "label=org.memweave.eval.run=owned" in args
            queries[0] += 1
            if queries[0] == 1:
                return SimpleNamespace(returncode=1, stdout="")
            return SimpleNamespace(returncode=0, stdout="our-container\n" if kills[0] < 2 else "")
        if args[1] == "kill":
            assert args[2] == "our-container"
            kills[0] += 1
            return SimpleNamespace(returncode=1 if kills[0] == 1 else 0, stdout="")
        raise AssertionError(args)

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monitor(tmp_path, "owned", -1, -1)
    records = [
        json.loads(line)
        for line in (tmp_path / "harbor/deadline-watchdog.jsonl").read_text().splitlines()
    ]
    assert records[0]["containers"] is None
    assert records[-1]["confirmed_stopped"] is True
    assert kills[0] == 2


def test_hard_deadline_unconfirmed_is_explicit_alert_before_recovery(tmp_path, monkeypatch):
    import memweave_eval.deadline_watchdog as module

    count = [0]

    def run(*_args, **_kwargs):
        count[0] += 1
        return SimpleNamespace(returncode=1 if count[0] < 3 else 0, stdout="")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.time, "time", lambda: 200)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monitor(tmp_path, "owned", 0, 1)
    assert json.loads((tmp_path / "stop-unconfirmed.json").read_text())["status"] == "ALERT"


def test_model_cutoff_targets_actor_and_hard_cutoff_also_targets_owned_unlabelled_verifier(tmp_path,monkeypatch):
    import memweave_eval.deadline_watchdog as module
    clock=[0];killed=[];executed=[]
    def owned(*_):
        return {'complete':True,'identities':[]if len(killed)==2 else['actor','verifier'],
            'actor_identities':['actor']if len(killed)<2 else[],'verifier_proofs':[]}
    def run(args,**_):
        if args[1]=='exec':executed.append(args[2]);return SimpleNamespace(returncode=0,stdout='')
        if args[1]=='kill':killed.append(args[2]);return SimpleNamespace(returncode=0,stdout='')
        raise AssertionError(args)
    monkeypatch.setattr(module,'running_containers',owned)
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr(module.time,'time',lambda:clock[0])
    monkeypatch.setattr(module.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    module.monitor(tmp_path,'run',0,1)
    assert executed==['actor']and set(killed)=={'actor','verifier'}


def test_external_observer_does_not_accept_legacy_stop_marker_or_overwrite_its_log(tmp_path,monkeypatch):
    import memweave_eval.deadline_watchdog as module
    (tmp_path/'.watchdog-stop').touch();(tmp_path/'harbor').mkdir()
    old=tmp_path/'harbor/deadline-watchdog.jsonl';old.write_text('preserved\n')
    monkeypatch.setattr(module,'running_containers',lambda *_:{'complete':True,'identities':[],
        'actor_identities':[],'verifier_proofs':[]})
    module.monitor(tmp_path,'run',-1,-1,'.watchdog-stop-external','external.jsonl')
    assert old.read_text()=='preserved\n'
    assert json.loads((tmp_path/'harbor/external.jsonl').read_text())['confirmed_stopped']
