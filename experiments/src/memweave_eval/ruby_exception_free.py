"""Actual Pi/local-provider controls for one derived clause, never an app solution."""
from __future__ import annotations

import json
from typing import Literal

from .free_episode import FreeEpisodePi
from .pi_agent import PiExperimentOptions
from .ruby_exception import BAN, EXCEPTION


class RubyExceptionOptions(PiExperimentOptions):
    ruby_exception_mode:Literal['positive','drop-exception','forbidden-lock','late-record']='positive'


class RubyExceptionFreePi(FreeEpisodePi):
    options_model=RubyExceptionOptions
    options:RubyExceptionOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('Ruby exception controls require preparation mode without credentials')
        if self.options.evaluation_case_id!='LONG-05':
            raise ValueError('Ruby exception control requires the selected source case')
        await super().install(environment)
        mode=self.options.ruby_exception_mode
        cards=[{'s':'rj','ban':list(BAN)}]
        if mode!='drop-exception':cards.append({'s':'rj','except':EXCEPTION})
        bodies=[json.dumps(value,separators=(',',':'))for value in cards]
        if any(len(body)>100 for body in bodies):raise ValueError('control card exceeds the existing prompt target')
        record=[{'tool':'state_append','arguments':{'items':[{'type':'fact','content':body,
            'evidence':{'$latest_read_ref':'The supplied public dependency constraint and SQLite exception.'}}for body in bodies]}}]
        actions=[]
        if self.options.variant=='pi-memweave':
            actions=[{'tool':'task_create','arguments':{'title':'Ruby dependency exception control',
                'goal':'Implement the Rust journal while preserving its explicit dependency ban and SQLite exception.',
                'project_name':'RubyJournal','summary':'Offline clause oracle control, not task completion',
                'keywords':['rust','sqlite','dependency']}},
                {'tool':'memory_read','arguments':{'items':[{'$latest_user_origin':True}],'max_total_chars':50000}}]
            if mode!='late-record':actions+=record
        names=['rj-rust',EXCEPTION]+(['magnus']if mode=='forbidden-lock'else[])
        lock='version = 4\n'+''.join('[[package]]\nname = '+json.dumps(n)+'\nversion = "1.0.0"\n'for n in names)
        actions.extend([{'tool':'write','arguments':{'path':'/app/rj-rust/Cargo.toml',
            'content':'[package]\nname="rj-rust"\nversion="1.0.0"\nedition="2021"\n'}},
            {'tool':'write','arguments':{'path':'/app/rj-rust/Cargo.lock','content':lock}}])
        if self.options.variant=='pi-memweave'and mode=='late-record':actions+=record
        actions.append({'text':'Offline clause control finished; the original application remains unimplemented.'})
        self._ruby_scenario=self._asset_root+'/evaluation/ruby-exception-control.json'
        await self.upload_private(environment,json.dumps({'stages':{'1':actions},'fixture_only':True}),self._ruby_scenario)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_ruby_scenario',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._ruby_scenario)
        return await super().exec_as_agent(environment,command,**kwargs)
