"""Preparation-only actual Pi/STATE overlay fixture; never reads real credentials."""
from __future__ import annotations

import json
from typing import Literal

from .free_episode import FreeEpisodePi
from .state_conflict import PENDING_RECORDS, RESOLVED_RECORD
from .state_pi import StatePi, StatePiOptions, final_pi_text


class ConflictFreeOptions(StatePiOptions):
    conflict_fixture_mode:Literal['positive','early-mutation','wrong-field']='positive'


class ConflictFreePi(FreeEpisodePi,StatePi):
    options_model=ConflictFreeOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('conflict fixture must have no real credentials and be preparation-only')
        if self.options.evaluation_state_overlay not in {'equal-authority-conflict-v1','equal-authority-conflict-v2'}:
            raise ValueError('conflict fixture requires the selected source overlay')
        await super().install(environment)
        resolve={'tool':'request_user_resolution','arguments':{'booking_id':'BK-A04',
            'field':'cancellation_authorized','evidence_ids':['authorization-A','authorization-B']}}
        read={'tool':'get_booking','arguments':{'booking_id':'BK-A04'}}
        preview={'tool':'cancel_booking','arguments':{'booking_id':'BK-A04','confirm':False}}
        cancel={'tool':'cancel_booking','arguments':{'booking_id':'BK-A04','confirm':True}}
        steps=[resolve,read,preview,cancel]
        if self.options.conflict_fixture_mode=='early-mutation':steps=[read,cancel,resolve]
        if self.options.conflict_fixture_mode=='wrong-field':
            resolve['arguments']['field']='cabin_class';steps=[resolve,read,preview,cancel]
        if self.options.variant=='pi-memweave':
            if self.options.evaluation_state_overlay.endswith('v2'):
                steps.insert(0,{'tool':'state_append','arguments':{'items':[{'type':'fact',
                    'content':json.dumps(value,separators=(',',':')),'evidence':{'U1':'Notice'}}for value in PENDING_RECORDS]}})
                resolver=next(i for i,s in enumerate(steps)if s.get('tool')=='request_user_resolution')
                steps.insert(resolver+1,{'tool':'modify_fact','arguments':{'archive':['F1','F2'],
                    'append_fact':{'content':json.dumps(RESOLVED_RECORD,separators=(',',':')),
                        'evidence':{'T'+str(resolver+2):'Customer answer'}}}})
            steps.insert(0,{'tool':'task_create','arguments':{'title':'Resolve booking authorization',
                'goal':'Resolve equally current BK-A04 customer authorization and execute the valid cancellation',
                'project_name':'STATE conflict fixture','summary':'Original travel domain; derived clarification protocol',
                'keywords':['BK-A04','authorization']}})
        steps.append({'text':'The booking is economy. Insurance gives a $0 cancellation fee and $310 refund. BK-A04 is cancelled.'})
        self._scenario_path=self._asset_root+'/evaluation/conflict-fixture.json'
        await self.upload_private(environment,json.dumps({'steps':steps,'fixture_only':True}),self._scenario_path)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_scenario_path',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._scenario_path)
        return await super().exec_as_agent(environment,command,**kwargs)

    async def _turn(self,text,environment,context,index):
        await FreeEpisodePi.run(self,text,environment,context)
        return final_pi_text(self.logs_dir/'pi.txt')

    async def run(self,instruction,environment,context):
        try:await self._run_overlay(environment,context)
        finally:
            if getattr(self,'_backend',None):self._backend.close()
