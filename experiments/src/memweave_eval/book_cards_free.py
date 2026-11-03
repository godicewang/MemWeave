"""Preparation-only selected book controls. Never accepts real credentials."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .fixed35_mab_cards import BOOKS
from .free_episode import FreeEpisodePi
from .pi_agent import PiExperimentOptions


class BookFreeOptions(PiExperimentOptions):
    book_gold_path:str
    answer_gold_path:str
    book_fixture_mode:Literal['positive','wrong-relation','late-record','window-loss-then-repair']='positive'


class BookCardFreePi(FreeEpisodePi):
    options_model=BookFreeOptions
    options:BookFreeOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('book control must be preparation-only without real credentials')
        await super().install(environment)
        gold=json.loads(Path(self.options.book_gold_path).read_text())
        answer=json.loads(Path(self.options.answer_gold_path).read_text())['answers'][0]
        identity=self.options.evaluation_case_id
        if identity not in BOOKS or gold['case_id']!=identity:raise ValueError('selected book fixture identity mismatch')
        import tomllib
        # The caller supplies only original/derived public task files here.
        config=self._evaluation_task_config
        task=Path(config['fixture_host_task'])
        steps=tomllib.loads((task/'task.toml').read_text())['steps']
        count=len(steps);self._book_query_stage=count
        stages={str(i):[{'text':'Context received.'}]for i in range(1,count+1)}
        card=dict(gold['card'])
        if self.options.book_fixture_mode=='wrong-relation':card['r']='mentions all these names'
        record={'tool':'state_append','arguments':{'items':[{'type':'fact',
            'content':json.dumps(card,separators=(',',':')),
            'evidence':{'U'+gold['source_stage_id']:gold['source_support'][:80]}}]}}
        if self.options.variant=='pi-memweave':
            stages['1'].insert(0,{'tool':'task_create','arguments':{'title':'Read the supplied book',
                'goal':'Retain important source narrative events for the later supplied question',
                'project_name':'MAB selected book control','summary':'Derived typed record protocol; offline scripted control',
                'keywords':['book','events']}})
            if self.options.book_fixture_mode!='late-record':
                stages[gold['source_stage_id']].insert(0,record)
            if self.options.book_fixture_mode=='window-loss-then-repair':
                if identity!='MAB-04' or count!=34:
                    raise ValueError('source-bound middle-loss control requires the selected 33-chunk book')
                for stage,archived,relation in ((29,'F1','mentions unrelated event'),(32,'F2',gold['card']['r'])):
                    changed=dict(gold['card'],r=relation)
                    stages[str(stage)].insert(0,{'tool':'modify_fact','arguments':{'archive':[archived],
                        'append_fact':{'content':json.dumps(changed,separators=(',',':')),
                            'evidence':{'U'+gold['source_stage_id']:gold['source_support'][:80]}}}})
        stages[str(count)]=[{'tool':'write','arguments':{'path':'/app/answer.json',
            'content':json.dumps({'value':answer})}},{'text':answer}]
        if self.options.variant=='pi-memweave'and self.options.book_fixture_mode=='late-record':
            stages[str(count)].insert(1,record)
        self._scenario_path=self._asset_root+'/evaluation/book-control.json'
        await self.upload_private(environment,json.dumps({'stages':stages,'fixture_only':True}),self._scenario_path)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_scenario_path',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._scenario_path)
        return await super().exec_as_agent(environment,command,**kwargs)

    async def run(self,instruction,environment,context):
        await super().run(instruction,environment,context)
        if self._evaluation_stage==self._book_query_stage:
            output=self.logs_dir/'fixed35-artifacts';output.mkdir(exist_ok=True)
            result=await self.exec_as_agent(environment,'test -f /app/answer.json',timeout_sec=10)
            exists=result.return_code==0
            (output/'answer-presence.json').write_text(json.dumps({'exists':exists,'fixture_only':True}))
            if exists:await environment.download_file('/app/answer.json',output/'answer.json')
