import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path

from memweave_eval.evidence_replay import read_object
from memweave_eval.fixed35_identity_window import identity_window_checkpoint


def test_real_pi_http_restart_and_config_reset_are_independently_graded(tmp_path):
    output=tmp_path/'actual-pi';fixture=Path(__file__).parent/'fixtures/restart-http.ts'
    env=dict(os.environ,MEMWEAVE_LIFECYCLE_FIXTURE_OUTPUT=str(output))
    result=subprocess.run(['node','--test',str(fixture)],env=env,text=True,capture_output=True,timeout=60,check=False)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads((output/'frames.json').read_text());assert len(data['records'])==5
    assert data['original_messages_unchanged']and data['full_rule_and_builtin_memory_tools']
    checks=[]
    for i,row in enumerate(data['records']):
        prepared=row['prepared'];descriptors=prepared['source_messages']
        source=[json.loads(read_object(output/'request-content',d['source_ref']))for d in descriptors]
        limits={'recent_turns':30,'evict_turns':2}if i==4 else{'recent_turns':3,'evict_turns':1}
        grade=identity_window_checkpoint(prepared['native_shape'],descriptors,source,row['payload'],
            row['observed_window'],**limits)
        assert grade[0]is True,(i,grade)
        checks.append(grade)
        if i==3:
            broken=deepcopy(prepared['native_shape'])
            restart=next(e for e in broken['branch_ledger']if e.get('custom_type')=='memweave.restart.v1')
            restart['data']['seed_event_ids']=[]
            assert identity_window_checkpoint(broken,descriptors,source,row['payload'],row['observed_window'],**limits)[0]is False
            broken.pop('branch_ledger')
            assert identity_window_checkpoint(broken,descriptors,source,row['payload'],row['observed_window'],**limits)[0]is None
    assert len(checks)==5
