import json
import subprocess
from pathlib import Path


def capture(root):
    module=Path(__file__).parents[1]/'src/memweave_eval/task_registry.mjs'
    code='import{captureTaskRegistry}from '+json.dumps(module.as_uri())+';console.log(JSON.stringify(captureTaskRegistry({root:process.argv[1],evidence:null})));'
    return json.loads(subprocess.check_output(['node','--input-type=module','-e',code,str(root)],text=True))


def test_registry_distinguishes_absent_partial_durable_and_redirected_objects(tmp_path):
    root=tmp_path/'memory'
    assert capture(root)['complete']and capture(root)['tasks']==[]
    folder=root/'workspace/tasks/task_test';folder.mkdir(parents=True)
    assert not capture(root)['complete']
    journal=folder/'state.json';journal.write_text('{"op":"update_goal","goal":"fixed goal"}\n')
    value=capture(root);assert value['complete']and value['tasks'][0]['task_id']=='task_test'
    assert value['tasks'][0]['version']==1 and value['tasks'][0]['goal_sha256']
    journal.write_text('{"op":"update_goal","goal":"fixed goal"}')
    assert not capture(root)['complete']
    journal.unlink();journal.symlink_to(tmp_path/'outside.json')
    assert not capture(root)['complete']


def test_duplicate_global_id_or_truncated_json_is_not_known_no_creation(tmp_path):
    for workspace in ['a','b']:
        folder=tmp_path/workspace/'tasks/task_same';folder.mkdir(parents=True)
        (folder/'state.json').write_text('{"op":"update_goal","goal":"goal"}\n')
    assert not capture(tmp_path)['complete']
    (tmp_path/'a/tasks/task_same/state.json').write_text('{"bad":\n')
    assert not capture(tmp_path)['complete']
