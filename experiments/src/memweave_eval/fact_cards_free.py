"""No-credential CLI fixtures for selected serial facts and real evictions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .free_episode import FreeEpisodePi
from .pi_agent import PiExperimentOptions


class FactFreeOptions(PiExperimentOptions):
    fact_gold_path:str
    fact_fixture_mode:Literal['positive','keep-obsolete']='positive'


class FactCardFreePi(FreeEpisodePi):
    options_model=FactFreeOptions
    options:FactFreeOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('fact controls require preparation-only and no real credentials')
        await super().install(environment)
        gold=json.loads(Path(self.options.fact_gold_path).read_text())
        if gold['case_id']!=self.options.evaluation_case_id:raise ValueError('source-bound fact identity differs')
        count=int(gold['query_stage_id']);self._fact_query_stage=count
        stages={str(i):[{'text':'Context received.'}]for i in range(1,count+1)}
        pending=[]
        old=gold.get('old_fact_control')
        if old:pending.append((old['source']['stage_id'],old['card'],old['source'],True))
        for fact in gold['typed_fact_memory']['facts']:
            serial=fact['card']['n']
            source=[s for s in gold['source_instruction_paths']if s['support'].startswith(str(serial)+'. ')]
            if len(source)!=1:raise ValueError('current fact support is ambiguous')
            pending.append((source[0]['stage_id'],fact['card'],source[0],False))
        if self.options.variant=='pi-memweave':
            stages['1'].insert(0,{'tool':'task_create','arguments':{'title':'Read supplied serial facts',
                'goal':'Maintain the current supplied factual relations for the later question',
                'project_name':'MAB source-bound fact control','summary':'Offline typed serial facts; no real provider',
                'keywords':['serial','facts']}})
            current={}
            for next_fact,(stage,card,support,_is_old)in enumerate(sorted(pending,key=lambda p:(p[0],not p[3])),1):
                content=json.dumps(card,separators=(',',':'))
                fact={'content':content,'evidence':{'U'+str(stage):support['support'][:80]}}
                key=card['s'],card['r'];prior=current.get(key)
                step=({'tool':'modify_fact','arguments':{'archive':[prior],'append_fact':fact}}
                    if prior and self.options.fact_fixture_mode!='keep-obsolete'else
                    {'tool':'state_append','arguments':{'items':[dict(fact,type='fact')]}})
                stages[str(stage)].insert(-1,step);current[key]='F'+str(next_fact)
        stages[str(count)]=[{'tool':'write','arguments':{'path':'/app/answer.json',
            'content':json.dumps({'value':gold['answers'][0]})}},{'text':gold['answers'][0]}]
        self._scenario_path=self._asset_root+'/evaluation/fact-control.json'
        await self.upload_private(environment,json.dumps({'stages':stages,'fixture_only':True}),self._scenario_path)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_scenario_path',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._scenario_path)
        return await super().exec_as_agent(environment,command,**kwargs)

    async def run(self,instruction,environment,context):
        await super().run(instruction,environment,context)
        if self._evaluation_stage==self._fact_query_stage:
            output=self.logs_dir/'fixed35-artifacts';output.mkdir(exist_ok=True)
            result=await self.exec_as_agent(environment,'test -f /app/answer.json',timeout_sec=10)
            exists=result.return_code==0
            (output/'answer-presence.json').write_text(json.dumps({'exists':exists,'fixture_only':True}))
            if exists:await environment.download_file('/app/answer.json',output/'answer.json')
