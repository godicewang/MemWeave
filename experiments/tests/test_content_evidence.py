import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from memweave_eval.evidence_replay import replay_content


def test_content_store_is_opt_in_exact_and_replayable(tmp_path):
    module=Path(__file__).parents[1]/'src/memweave_eval/content_evidence.mjs'
    script="""
import fs from 'node:fs';
import {contentEvidence} from MODULE;
if(contentEvidence('')!==null)throw Error('not opt in');
const store=contentEvidence(ROOT);
const wire=JSON.stringify({messages:[{role:'user',content:'证据≤200'}, {role:'tool',tool_call_id:'t',content:'x'}]});
const ref=store.put(wire);store.event('request_ready',{request_id:'r',payload_ref:ref});
store.event('provider_receipt',{request_id:'r',stream_done:true,usage:{input:8,output:2}});
if(JSON.stringify(store.put(wire))!==JSON.stringify(ref))throw Error('not dedup');
fs.writeFileSync(ROOT+'/test.json',JSON.stringify({wire,ref}));
""".replace('MODULE',json.dumps(module.as_uri())).replace('ROOT',json.dumps(str(tmp_path)))
    subprocess.run(['node','--input-type=module','-e',script],check=True,capture_output=True,text=True)
    meta=json.loads((tmp_path/'test.json').read_text())
    wire=gzip.decompress((tmp_path/meta['ref']['object']).read_bytes())
    assert wire.decode()==meta['wire']
    assert hashlib.sha256(wire).hexdigest()==meta['ref']['sha256']
    entries=[json.loads(line)for p in tmp_path.glob('producer-*.jsonl')if '.mirror.'not in p.name for line in p.read_text().splitlines()]
    assert [e['sequence']for e in entries]==[1,2]
    assert entries[1]['previous_sha256']==entries[0]['event_sha256']
    assert len(list((tmp_path/'objects').glob('*.gz')))==1
    replay=replay_content(tmp_path,expected_request_ids=['r'])
    assert replay['requests']['r']['messages'][0]['content']=='证据≤200'
    assert replay['duplicate_records_deduplicated']==2
    primary=next(p for p in tmp_path.glob('producer-*.jsonl')if '.mirror.'not in p.name)
    original=primary.read_bytes()
    # Physical reordering and duplicate extraction are repaired without editing originals.
    primary.write_bytes(b'\n'.join(reversed(original.splitlines()))+b'\n'+original.splitlines()[0]+b'\n')
    assert len(replay_content(tmp_path)['events'])==2
    primary.write_bytes(original[:-12])
    assert replay_content(tmp_path)['repair'] is not None
    primary.write_bytes(original)
    obj=tmp_path/meta['ref']['object'];obj.write_bytes(gzip.compress(b'wrong'))
    with pytest.raises(ValueError,match='hash'):
        replay_content(tmp_path)
