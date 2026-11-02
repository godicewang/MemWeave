import hashlib
import json
from pathlib import Path

import pytest

from memweave_eval.fixed35_adapters import mab_task, score_mab, sentence_chunks
from memweave_eval.fixed35_sources import mab_selector


def test_compound_selector_cannot_alias_reused_qa_id():
    a={'upstream_case_id':'Accurate_Retrieval/row=12/context_sha256='+'a'*64+'/qa_pair_id=q',
       'short_qa_id':'q','context_sha256':'a'*64,'data_revision':'b'*40}
    assert mab_selector(a)['row']==12
    with pytest.raises(ValueError):mab_selector(dict(a,context_sha256='c'*64))
    b=dict(a,upstream_case_id=a['upstream_case_id'].replace('row=12','row=13'))
    assert mab_selector(a)!=mab_selector(b)


def test_sentence_chunking_is_natural_and_deterministic():
    # Supply upstream-compatible tokenizer/sentences; no NLP download in unit tests.
    assert sentence_chunks(['a b','c','d e'],lambda s:s.split(),3)==['a b c','d e']
    assert sentence_chunks(['long sentence exceeds cap'],lambda s:s.split(),2)==['','long sentence exceeds cap']


def test_mab_host_gold_never_enters_actor_inputs(tmp_path):
    case={'pack_case_id':'MAB-01','source_revision':'a'*40,'benchmark':'MemoryAgentBench'}
    public={'context':'Original fact. New fact.','question':'Which value?',
            'selector':{'split':'Conflict_Resolution'}}
    private={'answers':['HiddenAnswer'],'qa_index':3}
    record=mab_task(case,public,private,['Original fact.','New fact.'],tmp_path)
    assert record['steps']==3
    task=Path(record['task_path'])
    assert all('HiddenAnswer' not in p.read_text() for p in task.rglob('*')if p.is_file())
    assert json.loads(Path(record['gold_path']).read_text())['answers']==['HiddenAnswer']
    assert 'answer' not in record['task_path']
    assert hashlib.sha256((task/'steps/query/instruction.md').read_bytes()).hexdigest()==record['query_sha256']


def test_native_substring_and_strict_and_action_are_distinct():
    assert score_mab('NewValue',['NewValue'],{'value':'NewValue'})['native_outcome']==100
    result=score_mab('OldValue or NewValue',['NewValue'],{'value':'OldValue'})
    assert result['native_outcome']==100 and result['strict_answer']==0 and result['typed_action']==0
    missing=score_mab(None,['NewValue'],None)
    assert missing['status']=='MISSING_EVIDENCE' and missing['native_outcome'] is None
    assert score_mab('',['NewValue'],{})['native_outcome']==0
