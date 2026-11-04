import json
import time
from types import SimpleNamespace

import pytest

from memweave_eval.slop_eval_entry import scoped_exec


@pytest.mark.parametrize('code,text,redacted',[(0,'fine',False),(2,'ImportError: missing helper',False),
    (2,'Authorization: Bearer private-value',True)])
def test_runtime_diagnostic_does_not_change_source_result_or_resource_audit(tmp_path,code,text,redacted):
    audit=tmp_path/'containers.jsonl';result=SimpleNamespace(exit_code=code,stdout=text,stderr='')
    _,execute=scoped_exec(lambda *a,**k:result,lambda *a:[],run_id='unit',cpus=1,memory_mb=4096,
        expected_image='unit',audit=audit,client=None,deadline=time.time()+10)
    assert execute(SimpleNamespace())is result
    record=json.loads(audit.with_name('containers-runtime.jsonl').read_text())
    assert record['exit_code']==code and len(record['stdout_sha256'])==64
    assert not audit.exists(),'resource proof retains its existing schema'
    if code==0:assert 'failure_tail'not in record
    else:
        assert record['failure_tail_redacted']==redacted
        if redacted:assert 'private-value'not in record['failure_tail']
        else:assert text in record['failure_tail']
