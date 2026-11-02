"""Explicit derived Pi task adapters; source outcomes retain their original names."""
from __future__ import annotations

import hashlib
import re
import shutil
import string
from pathlib import Path

import toml

from .storage import atomic_json


def sentence_chunks(sentences, encode, limit=4096):
    """Exact upstream MAB greedy sentence packing, including oversized-sentence edge."""
    chunks, current, count = [], [], 0
    for sentence in sentences:
        size = len(encode(sentence))
        if count+size > limit:
            chunks.append(' '.join(current))
            current, count = [sentence], size
        else:
            current.append(sentence)
            count += size
    if current:
        chunks.append(' '.join(current))
    return chunks


def mab_chunks(public, nltk_data: Path):
    import nltk
    import tiktoken
    nltk.data.path.insert(0,str(nltk_data))
    encoder = tiktoken.encoding_for_model('gpt-4o-mini')
    return sentence_chunks(nltk.sent_tokenize(public['context']),
                           lambda text:encoder.encode(text,allowed_special={'<|endoftext|>'}))


def mab_task(case, public, private, chunks, output: Path):
    if not chunks:
        raise ValueError('MAB must ingest real source history')
    task=output/'actor-tasks'/case['pack_case_id']
    task.mkdir(parents=True,exist_ok=False)
    (task/'environment').mkdir()
    (task/'environment/Dockerfile').write_text(
        'FROM python:3.12.12-slim-bookworm\n'
        'RUN apt-get update && apt-get install -y --no-install-recommends '
        'bash ca-certificates curl git ripgrep coreutils util-linux && rm -rf /var/lib/apt/lists/*\n'
        'WORKDIR /app\n')
    names=[]
    book=public['selector']['split']=='Accurate_Retrieval'
    for i,chunk in enumerate(chunks):
        name=f'ingest-{i+1:04d}';names.append(name)
        folder=task/'steps'/name;folder.mkdir(parents=True)
        # Template text is upstream's public memorize template, not a gold hint.
        text=('The following context is the '+('book excerpt' if book else 'facts I have learned')+
              ':\n'+chunk+'\nI will ask a question after all context has been provided.')
        (folder/'instruction.md').write_text(text)
    query=task/'steps/query';query.mkdir(parents=True)
    text=('Based on the context you memorized, complete the task below:\n\n'+public['question'])
    if not book:
        text=('Each fact has a serial number; newer facts have larger serial numbers. '
              'Resolve conflicting facts using the newest serial number. Answer only from the supplied '
              'knowledge pool rather than real-world facts.\n'+text)
    text+=('\n\nEvaluation action overlay (identical for both variants): also save your single chosen '
           'answer in /app/answer.json as {"value": "your answer"}. Do not put alternative guesses in '
           'that value. Your final reply should contain only the answer.')
    (query/'instruction.md').write_text(text)
    names.append('query')
    config={'schema_version':'1.4','multi_step_reward_strategy':'final',
            'metadata':{'category':'memory','derived_adapter':'fixed35-mab-pi-v1',
                        'source_revision':case['source_revision']},
            'agent':{'timeout_sec':1800},
            'environment':{'build_timeout_sec':900,'cpus':2,'memory_mb':4096,'storage_mb':10240},
            'verifier':{'timeout_sec':30},'steps':[{'name':name}for name in names]}
    (task/'task.toml').write_text(toml.dumps(config))
    # This family has a host-side official QA scorer, not a fictitious Harbor reward.
    (task/'tests').mkdir();(task/'tests/test.sh').write_text('exit 1 # host QA scoring required\n')
    gold=output/'evaluator-only'/case['pack_case_id']/'gold.json'
    gold.parent.mkdir(parents=True)
    atomic_json(gold,private,immutable=True)
    record={'case_id':case['pack_case_id'],'task_path':str(task),'gold_path':str(gold),
            'steps':len(names),'history_chunks':len(chunks),'native_scoring':'MAB substring_exact_match',
            'derived_scoring':['strict_answer','typed_action'],
            'query_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'source_context_sha256':hashlib.sha256(public['context'].encode()).hexdigest(),
            'model_visible_adaptations':['full Pi tools and defaults','incremental ingestion via persistent Pi Session',
                                        'final typed answer file action'],'grader_location':'host_evaluator_only'}
    return record


def normalize_mab(value):
    # Byte-for-byte algorithm of the pinned MAB normalize_answer (utils/eval_other_utils.py).
    value=value.lower()
    value=''.join(c for c in value if c not in string.punctuation)
    return ' '.join(re.sub(r'\b(a|an|the)\b',' ',value).split())


def score_mab(prediction, answers, action):
    if not isinstance(answers,list) or not answers or any(not isinstance(a,str)for a in answers):
        raise ValueError('MAB requires published nonempty answer alternatives')
    if prediction is None:
        return {'status':'MISSING_EVIDENCE','native_outcome':None,'strict_answer':None,'typed_action':None}
    if not isinstance(prediction,str):
        raise TypeError('invalid prediction')
    targets={normalize_mab(a)for a in answers}
    normalized=normalize_mab(prediction)
    return {'status':'SCORED','native_outcome':100*int(any(a in normalized for a in targets)),
            'strict_answer':100*int(normalized in targets),
            'typed_action':None if action is None else 100*int(isinstance(action,dict)
                and set(action)=={'value'} and isinstance(action['value'],str)
                and normalize_mab(action['value']) in targets),
            'scoring_version':'fixed35-mab-pi-v1'}


def switch_build_adapter(source:Path,output:Path):
    """Repair only a verified executable lookup defect, without modifying the pin."""
    shutil.copytree(source,output)
    dockerfile=output/'environment/Dockerfile'
    old=dockerfile.read_text()
    marker='RUN useradd -m -s /bin/bash agent'
    if old.count(marker)!=1:
        raise ValueError('pinned Switch build repair no longer matches')
    new=old.replace(marker,'RUN /usr/sbin/useradd -m -s /bin/bash agent')
    dockerfile.write_text(new)
    return {'adaptation':'explicit path to existing useradd omitted by upstream PATH',
            'source_dockerfile_sha256':hashlib.sha256(old.encode()).hexdigest(),
            'derived_dockerfile_sha256':hashlib.sha256(new.encode()).hexdigest(),
            'model_visible_path_unchanged':True,'official_instructions_and_verifier_unchanged':True}
