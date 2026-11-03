"""Isolated source-reference software controls, never real model performance."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .free_episode import FreeEpisodePi
from .pi_agent import PiExperimentOptions


class SlopFkOptions(PiExperimentOptions):
    slop_fk_source:str
    slop_fk_mode:Literal['positive','keep-old','late-correct','scoped-history']='positive'


class SlopFkFreePi(FreeEpisodePi):
    options_model=SlopFkOptions
    options:SlopFkOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('Slop source-reference controls require preparation mode without credentials')
        await super().install(environment)
        source=Path(self.options.slop_fk_source)/'database_migration/solutions'
        def card(value,lo=1,hi=None):return json.dumps({'r':'fk','v':value,'lo':lo,'hi':hi},separators=(',',':'))
        def append(value,lo,hi=None):return {'tool':'state_append','arguments':{'items':[{
            'type':'fact','content':card(value,lo,hi),'evidence':{'U'+str(1 if value=='OFF'else 3):'The supplied migration specification'}}]}}
        def modify(value,lo,hi=None):return {'tool':'modify_fact','arguments':{'archive':['F1'],
            'append_fact':{'content':card(value,lo,hi),'evidence':{'U'+str(1 if value=='OFF'else 3):'The supplied migration specification'}}}}
        stages={}
        for i in range(1,6):
            private=self._asset_root+'/evaluation/source-reference-fixture/checkpoint_'+str(i)
            for name in ('requirements.txt','migration_tool.py'):
                await self.upload_private(environment,(source/('checkpoint_'+str(i))/name).read_text(),private+'/'+name)
            actions=[]
            if i==1 and self.options.variant=='pi-memweave':
                actions.extend([{'tool':'task_create','arguments':{'title':'Migration source control',
                    'goal':'Implement the evolving migration tool from its supplied checkpoints',
                    'project_name':'Slop database migration','summary':'Offline source-reference control only',
                    'keywords':['migration','sqlite']}},append('OFF',1)])
            correction=[]
            if i==3 and self.options.variant=='pi-memweave':
                if self.options.slop_fk_mode=='keep-old':correction=[append('ON',3)]
                elif self.options.slop_fk_mode=='scoped-history':correction=[modify('OFF',1,2),append('ON',3)]
                else:correction=[modify('ON',3)]
            if self.options.slop_fk_mode!='late-correct':actions.extend(correction)
            actions.append({'tool':'bash','arguments':{'command':'cp '+private+'/migration_tool.py '+private+'/requirements.txt /workspace/'}})
            if self.options.slop_fk_mode=='late-correct':actions.extend(correction)
            actions.append({'text':'Offline source-reference checkpoint complete; no agent capability score claimed.'})
            stages[str(i)]=actions
        self._fk_scenario=self._asset_root+'/evaluation/slop-fk-control.json'
        await self.upload_private(environment,json.dumps({'stages':stages,'fixture_only':True}),self._fk_scenario)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_fk_scenario',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._fk_scenario)
        return await super().exec_as_agent(environment,command,**kwargs)
