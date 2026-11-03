import json
import subprocess
from pathlib import Path


def snapshot(root,selectors,**options):
    module=Path(__file__).parents[1]/'src/memweave_eval/tree_projection.mjs'
    script='import {treeProjection}from MODULE;console.log(JSON.stringify(treeProjection(ROOT,OPTIONS)));'
    script=script.replace('MODULE',json.dumps(str(module))).replace('ROOT',json.dumps(str(root))).replace(
        'OPTIONS',json.dumps(dict(selectors=selectors,**options)))
    result=subprocess.run(['node','--input-type=module','-e',script],text=True,capture_output=True,check=True,timeout=10)
    return json.loads(result.stdout)


def test_selected_contract_inventory_hashes_all_files_and_detects_added_deleted_and_changed(tmp_path):
    (tmp_path/'crates/a/tests').mkdir(parents=True);(tmp_path/'crates/a/src').mkdir()
    (tmp_path/'Cargo.toml').write_text('provided')
    (tmp_path/'crates/a/tests/a.rs').write_text('test')
    (tmp_path/'crates/a/src/a.rs').write_text('mutable code')
    selectors={'names':['Cargo.toml'],'segments':['tests'],'suffixes':[]}
    first=snapshot(tmp_path,selectors);assert first['status']=='complete'and first['file_count']==2
    assert snapshot(tmp_path,selectors)['projection_sha256']==first['projection_sha256']
    (tmp_path/'crates/a/src/a.rs').write_text('legitimate implementation')
    assert snapshot(tmp_path,selectors)['projection_sha256']==first['projection_sha256']
    (tmp_path/'crates/a/tests/extra.inc').write_text('new protected fixture')
    assert snapshot(tmp_path,selectors)['projection_sha256']!=first['projection_sha256']
    (tmp_path/'crates/a/tests/extra.inc').unlink();(tmp_path/'Cargo.toml').write_text('changed')
    assert snapshot(tmp_path,selectors)['projection_sha256']!=first['projection_sha256']
    (tmp_path/'Cargo.toml').unlink()
    assert snapshot(tmp_path,selectors)['projection_sha256']!=first['projection_sha256']


def test_missing_limits_and_links_are_not_silently_accepted(tmp_path):
    selectors={'names':[],'segments':[],'suffixes':[]}
    assert snapshot(tmp_path/'absent',selectors)['status']=='absent'
    (tmp_path/'file').write_text('abc');(tmp_path/'link').symlink_to('/etc/passwd')
    result=snapshot(tmp_path,selectors)
    assert result['status']=='complete'and result['file_count']==2
    assert result['entries'][1]['kind']=='symlink'and 'content_sha256'not in result['entries'][1]
    assert snapshot(tmp_path,selectors,maxFiles=1)['status']=='incomplete'
    assert snapshot(tmp_path,selectors,maxBytes=1)['status']=='incomplete'
    (tmp_path/'target').mkdir();(tmp_path/'target/ignored').write_text('build artifact')
    assert snapshot(tmp_path,selectors)['projection_sha256']==result['projection_sha256']
