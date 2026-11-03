import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path

from memweave_eval.evidence_replay import read_object
from memweave_eval.fixed35_identity_window import grade_identity_windows, identity_window_checkpoint
from memweave_eval.session_originals import load_original_sessions, with_foreign_originals


def test_foreign_resume_from_real_pi_originals_and_http(tmp_path):
    out=tmp_path/'actual-foreign';fixture=Path(__file__).parent/'fixtures/foreign-resume-http.ts'
    run=subprocess.run(['node','--test',str(fixture)],text=True,capture_output=True,timeout=60,check=False,
        env=dict(os.environ,MEMWEAVE_LIFECYCLE_FIXTURE_OUTPUT=str(out)))
    assert run.returncode==0,run.stdout+run.stderr
    data=json.loads((out/'frames.json').read_text());originals=load_original_sessions(out/'trial')
    assert len(originals)==2 and data['full_rule_and_tools']and data['originals_unchanged']
    grades=[]
    for row in data['records']:
        boundary=row['prepared'];descriptors=boundary['source_messages']
        captured_rule=read_object(out/'trial/agent/request-content',boundary['expected_rule_template_ref'])
        assert captured_rule==(out/'memory/rule.md').read_bytes(),'collector must use the isolated test profile'
        source=[json.loads(read_object(out/'trial/agent/request-content',d['source_ref']))for d in descriptors]
        shape,descriptors,source,proof=with_foreign_originals(boundary['native_shape'],descriptors,source,originals,row['requested_at'])
        grade=identity_window_checkpoint(shape,descriptors,source,row['payload'],row['observed_window'],recent_turns=20,evict_turns=4)
        assert grade[0]is True,grade
        grades.append(grade)
        if proof:
            assert proof['source_session_id']==data['source_session_id']
            broken=deepcopy(row['payload']);broken['messages'].pop(1)
            assert identity_window_checkpoint(shape,descriptors,source,broken,row['observed_window'],recent_turns=20,evict_turns=4)[0]is False
    assert len(grades)==4
    whole=grade_identity_windows(out/'trial',['local-fixture-'+str(i)for i in range(1,5)],
        recent_turns=20,evict_turns=4,enabled=True)
    assert whole['value']==1 and whole['coverage']==1 and whole['denominator']==4,whole
    assert any(i.get('original_source_proof')for i in whole['items'])
