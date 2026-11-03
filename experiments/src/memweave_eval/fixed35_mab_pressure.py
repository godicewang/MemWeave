"""Source-bound MAB pressure adaptation, frozen before any real outcomes.

Input segmentation and the generic recording grammar are shared by both arms.
Only the full product's explicit N/B differs from its normal defaults. This is
an adapted pressure study, never a same-window mechanism ablation.
"""
from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import toml

from .fixed35_mab import MAB_RELATIONS
from .storage import atomic_json, file_digest
from .suites import task_digest

VERSION='fixed35-mab-pressure-20261103-v2'
POLICY={
 'MAB-01':(512,2,1),'MAB-02':(2048,2,1),'MAB-03':(4096,20,4),
 'MAB-04':(4096,8,2),'MAB-05':(2048,2,1),
 'MAB-06':(4096,20,4),'MAB-07':(4096,20,4),'MAB-08':(4096,20,4)}
SUPPORT={
 'MAB-01':['188. The chief executive officer of Microsoft is Steve Jobs.'],
 'MAB-02':['475. Christianity was founded in the city of Taipei.',
    '1924. Bagratuni Dynasty is affiliated with the religion of Christianity.'],
 'MAB-03':['7164. cornerback is associated with the sport of field hockey.',
    '7774. field hockey was created in the country of Philippines.',
    '10906. Christian Abbiati plays the position of cornerback.'],
 'MAB-05':['4102. The New York Times was written in the language of Ancient Greek.']}


def bind_support(task:Path,needles):
    paths=sorted((task/'steps').glob('ingest-*/instruction.md'))
    bound=[]
    for needle in needles:
        matches=[p for p in paths if p.read_text().count(needle)==1]
        if len(matches)!=1 or sum(p.read_text().count(needle)for p in paths)!=1:
            raise ValueError('current knowledge support is missing or ambiguous')
        path=matches[0]
        bound.append({'stage_id':int(path.parent.name.removeprefix('ingest-')),
            'path':str(path),'sha256':file_digest(path),'support':needle})
    return bound


def derive_pressure_task(source:Path,case_id,chunks,answers,selector,output:Path,*,book_gold=None):
    from .fixed35_fact_cards import FACTS
    from .fixed35_fact_cards import PUBLIC_PROTOCOL as FACT_PROTOCOL
    from .fixed35_fact_cards import VERSION as FACT_VERSION
    from .fixed35_mab_cards import PUBLIC_PROTOCOL
    limit,n,b=POLICY[case_id]
    if not chunks or any(not isinstance(c,str)or not c.strip()for c in chunks):
        raise ValueError('nonempty natural source chunks required; no filler')
    if any(p.is_symlink()for p in source.rglob('*')):raise ValueError('redirected actor source rejected')
    target=output/'tasks'/case_id
    shutil.copytree(source,target)
    config=tomllib.loads((target/'task.toml').read_text())
    original_query=(target/'steps/query/instruction.md').read_bytes()
    shutil.rmtree(target/'steps');(target/'steps/query').mkdir(parents=True)
    (target/'steps/query/instruction.md').write_bytes(original_query)
    book=case_id not in MAB_RELATIONS
    names=[]
    for i,chunk in enumerate(chunks,1):
        name=f'ingest-{i:04d}';names.append(name)
        folder=target/'steps'/name;folder.mkdir()
        text='The following context is the '+('book excerpt'if book else'facts I have learned')+':\n'+chunk+'\nI will ask a question after all context has been provided.'
        if i==1:text+='\n\n'+(PUBLIC_PROTOCOL if book else FACT_PROTOCOL)+'\n'
        (folder/'instruction.md').write_text(text)
    config['steps']=[{'name':s}for s in [*names,'query']]
    config.setdefault('metadata',{})['derived_adapter']=VERSION
    (target/'task.toml').write_text(toml.dumps(config))
    support=bind_support(target,SUPPORT[case_id])if not book else bind_support(target,[book_gold['source_support']])
    last=max(support,key=lambda s:s['stage_id'])
    gold={'version':VERSION,'case_id':case_id,'answers':answers,'selector':selector,
        'action_observation':'workspace-content-v2','query_stage_id':str(len(chunks)+1),
        'source_instruction_path':last['path'],'source_instruction_sha256':last['sha256'],
        'source_instruction_paths':support,'literal_valid_after_stage':last['stage_id'],
        'eviction_protocol':'eligible-after-current-source-v3',
        'literal_memory':MAB_RELATIONS.get(case_id),
        'task_config':{'memory_config':{'recent_turns':n,'evict_turns':b},
            'answer_file':'/app/answer.json',
            'workspace':{'root':'/app','files':['answer.json'],'content_files':['answer.json']}},
        'scope':'Same source/query and segmentation across variants; native product compaction versus explicit MemWeave N/B pressure. '
            'Three real distinct post-source cuts are required, never inferred from round counts.',
        'policy_basis':'Natural supplied evidence only; smaller chunks on short pools create legitimate later source-reading boundaries, not filler or extra target hints.',
        'chunk_token_limit':limit,'task_sha256':task_digest(target),'source_task_sha256':task_digest(source),
        'source_query_sha256':file_digest(source/'steps/query/instruction.md'),
        'model_visible_changes':['source-only sentence chunk segmentation','generic event-card grammar'if book else'generic serial-fact grammar'],
        'not_formal_admission':True}
    if book:
        gold['typed_book_memory']=dict(book_gold,source_stage_id=str(last['stage_id']),
            source_instruction_path=last['path'],source_instruction_sha256=last['sha256'])
    else:gold['typed_fact_memory']={'version':FACT_VERSION,'facts':FACTS[case_id]}
    if case_id=='MAB-01':
        old=bind_support(target,['85. The chief executive officer of Microsoft is Satya Nadella.'])[0]
        gold['old_fact_control']={'card':{'s':'Microsoft','r':'chief executive officer','o':'Satya Nadella','n':85},
            'source':old}
    gold['window_contract']={'kind':'native-identity-plain-text-v1','recent_turns':n,'evict_turns':b,
        'max_source_bytes':4000000}
    private=output/'evaluator-only'/case_id/'pressure.json'
    atomic_json(private,gold,immutable=True)
    return {'case_id':case_id,'task_path':str(target),'contract_path':str(private),
        'contract_sha256':file_digest(private),'task_sha256':gold['task_sha256'],
        'history_chunks':len(chunks),'current_source_stage':last['stage_id'],'N':n,'B':b,
        'three_post_source_boundaries_not_yet_observed':True}
