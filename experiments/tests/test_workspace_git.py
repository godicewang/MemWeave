import json
import subprocess
from pathlib import Path


def test_actual_worktree_hash_catches_tracked_untracked_and_restored_changes(tmp_path):
    repo=tmp_path/'w01';repo.mkdir()
    def git(*args):return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True)
    git('init');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
    (repo/'app.py').write_text('original\n');git('add','app.py');git('commit','-m','fixture')
    module=Path(__file__).parents[1]/'src/memweave_eval/workspace_git.mjs'
    def snapshot():
        script='import {gitWorktrees} from MODULE;console.log(JSON.stringify(gitWorktrees(ROOT,["w01"])));'
        result=subprocess.run(['node','--input-type=module','-e',script.replace('MODULE',json.dumps(module.as_uri())).replace('ROOT',json.dumps(str(tmp_path)))],
            check=True,capture_output=True,text=True,timeout=15)
        return json.loads(result.stdout)['w01']
    original=snapshot();assert original['status']=='complete'
    (repo/'app.py').write_text('modified\n');changed=snapshot()
    assert changed['projection_sha256']!=original['projection_sha256']
    (repo/'app.py').write_text('original\n');assert snapshot()['projection_sha256']==original['projection_sha256']
    (repo/'new.py').write_text('first\n');new=snapshot()
    (repo/'new.py').write_text('second\n');assert snapshot()['projection_sha256']!=new['projection_sha256']
    (repo/'new.py').unlink();assert snapshot()['projection_sha256']==original['projection_sha256']
    (repo/'secret-link').symlink_to(tmp_path/'not-readable-secret')
    assert snapshot()['status']=='complete'
    (tmp_path/'w02').symlink_to(repo,target_is_directory=True)
    result=subprocess.run(['node','--input-type=module','-e','import {gitWorktrees} from '+json.dumps(module.as_uri())+';console.log(JSON.stringify(gitWorktrees('+json.dumps(str(tmp_path))+',["w02"])));'],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout)['w02']['status']=='incomplete'
