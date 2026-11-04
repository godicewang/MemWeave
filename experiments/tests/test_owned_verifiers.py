import json
from types import SimpleNamespace

import pytest

from memweave_eval.owned_verifiers import running_containers
from memweave_eval.storage import file_digest


def fixture(root):
    task=root/'task';task.mkdir();(task/'task.toml').write_text(
        '[environment]\ndocker_image="actor-tag"\n[verifier]\nenvironment_mode="separate"\n'
        '[verifier.environment]\ndocker_image="verifier-tag"\n')
    admission=root/'admission.json';admission.write_text(json.dumps({'case_id':'TB-01','task_path':str(task)}))
    (root/'experiment.lock.json').write_text(json.dumps({'admission_sha256':file_digest(admission)}))
    trial=root/'harbor/tb-01-pi-native/task__abc';trial.mkdir(parents=True)
    config=trial/'config.json';config.write_text(json.dumps({'trial_name':trial.name,'task':{'path':str(task)},
        'agent':{'kwargs':{'variant':'pi-native','evaluation_case_id':'TB-01',
            'evaluation_run_id':'fixed35-formal:'+root.name+':TB-01'}}}))
    return config


@pytest.mark.parametrize('mode',['pass','foreign-project','wrong-image','query-failed','inspect-failed',
    'wrong-case','changed-admission','redirected-config'])
def test_unlabelled_verifier_requires_frozen_trial_project_and_image(tmp_path,mode):
    config=fixture(tmp_path)
    if mode=='wrong-case':
        data=json.loads(config.read_text());data['agent']['kwargs']['evaluation_case_id']='TB-02';config.write_text(json.dumps(data))
    elif mode=='changed-admission':(tmp_path/'admission.json').write_text('{}')
    elif mode=='redirected-config':
        raw=config.read_text();config.unlink();p=tmp_path/'elsewhere.json';p.write_text(raw);config.symlink_to(p)
    calls=[]
    def command(args):
        calls.append(args)
        if args[0]=='ps':
            if any('label=org.memweave.eval.run='in a for a in args):return SimpleNamespace(returncode=0,stdout='actor\n')
            if mode=='query-failed':return SimpleNamespace(returncode=1,stdout='')
            return SimpleNamespace(returncode=0,stdout='verifier\n')
        assert args==['inspect','verifier']
        if mode=='inspect-failed':return SimpleNamespace(returncode=1,stdout='')
        d={'Id':'verifier','State':{'Running':True},'Config':{'Image':'foreign-tag'if mode=='wrong-image'else'verifier-tag',
            'Labels':{'com.docker.compose.project':'foreign'if mode=='foreign-project'else'task__abc__verifier__trial',
                'com.docker.compose.service':'main'}}}
        return SimpleNamespace(returncode=0,stdout=json.dumps([d]))
    result=running_containers(tmp_path,tmp_path.name,command)
    if mode=='pass':assert result['complete']and set(result['identities'])=={'actor','verifier'}
    else:
        assert not result['complete']and result['identities']is None
        assert result['actor_identities']==['actor']
    assert not any(args[0]in ['kill','exec','stop','rm']for args in calls)


def test_ordinary_labelled_control_remains_supported_without_formal_admission(tmp_path):
    result=running_containers(tmp_path,'control',lambda args:SimpleNamespace(returncode=0,stdout='actor\n'))
    assert result['complete']and result['identities']==result['actor_identities']==['actor']


def test_shared_verifier_never_creates_an_extra_project_query(tmp_path):
    fixture(tmp_path);(tmp_path/'task/task.toml').write_text('[environment]\ndocker_image="actor-tag"\n[verifier]\nenvironment_mode="shared"\n')
    calls=[]
    def command(args):calls.append(args);return SimpleNamespace(returncode=0,stdout='actor\n')
    result=running_containers(tmp_path,tmp_path.name,command)
    assert result['complete']and result['identities']==['actor']and len(calls)==1


def test_baseline_query_timeout_is_unconfirmed_not_an_empty_success(tmp_path):
    import subprocess
    def command(args):raise subprocess.TimeoutExpired(args,15)
    result=running_containers(tmp_path,'control',command)
    assert not result['complete']and result['identities']is result['actor_identities']is None
