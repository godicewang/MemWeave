import json
import subprocess
from pathlib import Path


def capture(root,items):
    module=Path(__file__).parents[1]/'src/memweave_eval/artifact_snapshot.mjs'
    script='import{artifactSnapshot}from MODULE;console.log(JSON.stringify(artifactSnapshot(ROOT,ITEMS,bytes=>({bytes:bytes.length}))));'
    script=script.replace('MODULE',json.dumps(str(module))).replace('ROOT',json.dumps(str(root))).replace('ITEMS',json.dumps(items))
    return json.loads(subprocess.check_output(['node','--input-type=module','-e',script],text=True,timeout=10))


def test_bounded_artifact_evidence_preserves_absence_and_rejects_escape_links_and_oversize(tmp_path):
    (tmp_path/'meta.json').write_bytes(b'{}')
    good=capture(tmp_path,{'meta.json':100,'design.npy':100})
    assert good['meta.json']['status']=='captured' and good['meta.json']['ref']=={'bytes':2}
    assert good['design.npy']['status']=='absent'
    assert capture(tmp_path,{'meta.json':1})['meta.json']['status']=='incomplete'
    (tmp_path/'link').symlink_to(tmp_path/'meta.json')
    assert capture(tmp_path,{'link':100})['link']['status']=='incomplete'
    (tmp_path/'dir').mkdir();(tmp_path/'parent').symlink_to(tmp_path/'dir')
    assert capture(tmp_path,{'parent/file':100})['parent/file']['status']=='incomplete'
    assert capture(tmp_path,{'../other':100})['../other']['status']=='incomplete'
    assert capture(tmp_path,{'meta.json':1048577})['meta.json']['status']=='incomplete'
