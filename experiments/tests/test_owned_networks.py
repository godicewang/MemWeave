import json

import pytest

from memweave_eval.owned_networks import cleanup_networks


def trial(tmp_path, *, finished=True, name='source__ABC123'):
    root=tmp_path/'fixed35-current';root.mkdir()
    (root/'campaign.json').write_text(json.dumps({'schema_version':1,'budget_id':root.name}))
    p=root/'formal-case'/'harbor'/'job'/name/'result.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'trial_name':name,'finished_at':'2026-11-04T01:00:00Z'if finished else None}))
    return root,p


def docker(*,attached=False,changed=False,fail=False,foreign=False):
    calls=[];inspects=0
    def run(args):
        nonlocal inspects
        calls.append(args)
        if fail:raise RuntimeError('daemon unavailable')
        if args[1:3]==['network','ls']:return 'abc123def456\n'if '__env'in args[-3]else''
        if args[1:3]==['network','inspect']:
            inspects+=1
            return json.dumps([{'Id':'abc123def456','Name':'owned_default',
                'Labels':{'com.docker.compose.project':'foreign'if foreign else'source__abc123__env'},
                'Containers':{'c':{}}if attached or(changed and inspects==2)else{}}])
        if args[1:3]==['network','rm']:return 'abc123def456\n'
        raise AssertionError(args)
    return run,calls


def test_default_is_dry_run_and_finished_trial_proves_exact_project(tmp_path):
    root,p=trial(tmp_path);run,calls=docker()
    result=cleanup_networks(root,execute=False,command=run)
    assert result['empty_candidates']==1 and result['removed']==0
    assert result['rows'][0]['trial_sha256'] and result['rows'][0]['trial_path']==str(p)
    assert not any(c[1:3]==['network','rm']for c in calls)


def test_execution_rechecks_empty_ownership_and_only_removes_exact_id(tmp_path):
    root,_=trial(tmp_path);run,calls=docker();events=[]
    result=cleanup_networks(root,execute=True,command=run,observe=events.append)
    assert result['removed']==1
    assert [c for c in calls if c[1:3]==['network','rm']]==[['docker','network','rm','abc123def456']]
    assert sum(c[1:3]==['network','inspect']for c in calls)==2
    assert [e['status']for e in events]==['REMOVE_INTENT','REMOVED']


@pytest.mark.parametrize('mode',['attached','changed','foreign'])
def test_attached_foreign_and_racing_attachment_never_removed(tmp_path,mode):
    root,_=trial(tmp_path);run,calls=docker(**{mode:True})
    result=cleanup_networks(root,execute=True,command=run)
    assert result['removed']==0
    assert not any(c[1:3]==['network','rm']for c in calls)


def test_unfinished_trial_is_not_a_cleanup_target(tmp_path):
    root,_=trial(tmp_path,finished=False);run,calls=docker()
    assert cleanup_networks(root,execute=True,command=run)['removed']==0
    assert calls==[]


@pytest.mark.parametrize('name',['foreign; rm -rf','../bad','x y'])
def test_untrusted_trial_identity_rejected_before_docker(tmp_path,name):
    root,p=trial(tmp_path);x=json.loads(p.read_text());x['trial_name']=name;p.write_text(json.dumps(x))
    run,calls=docker()
    with pytest.raises(ValueError):cleanup_networks(root,execute=True,command=run)
    assert calls==[]


def test_result_symlink_and_daemon_failure_do_not_become_success(tmp_path):
    root,p=trial(tmp_path);original=p.with_name('saved.json');p.rename(original);p.symlink_to(original)
    run,calls=docker()
    with pytest.raises(ValueError):cleanup_networks(root,execute=True,command=run)
    p.unlink();original.rename(p);run,calls=docker(fail=True)
    with pytest.raises(RuntimeError):cleanup_networks(root,execute=True,command=run)
    assert not any(c[1:3]==['network','rm']for c in calls)
