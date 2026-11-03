"""Actual Pi controls over selected Switch stages; never real credentials."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Literal

from .free_episode import FreeEpisodePi
from .pi_agent import PiExperimentOptions


class SwitchFreeOptions(PiExperimentOptions):
    switch_probe_contract_path:str
    switch_fixture_mode:Literal['positive','wrong-binding','wrong-audit','unnecessary-create','late-create']='positive'


class SwitchProbeFreePi(FreeEpisodePi):
    options_model=SwitchFreeOptions
    options:SwitchFreeOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('Switch control must be preparation-only without credentials')
        await super().install(environment)
        contract=json.loads(Path(self.options.switch_probe_contract_path).read_text())
        if contract['case_id']!=self.options.evaluation_case_id:raise ValueError('selected Switch control identity differs')
        task=Path(contract['task_path']);steps=tomllib.loads((task/'task.toml').read_text())['steps']
        routes={r['source_step']:r['goal_slot']for r in contract['source_component']['route_ledger']}
        labels={r['slot']:r for r in contract['route_labels']};first={r['first_source_step']:r for r in contract['route_labels']}
        probes={p['step']:p for p in contract['probes']};stages={};current=None
        late_step=contract['route_labels'][1]['first_source_step']
        from .fixed35_switch_probes import AUDIT_TAGS
        def restore(label):return [
            {'tool':'task_find','arguments':{'query':label,'limit':3}},
            {'tool':'task_resume','arguments':{'task_id':{'$task_route':label}}}]
        for index,step in enumerate(steps,1):
            name=step['name'];actions=[]
            if name in routes:
                slot=routes[name];label=labels[slot]['route_id']
                if self.options.variant=='pi-memweave':
                    if name in first:
                        if self.options.switch_fixture_mode=='late-create'and name==late_step:
                            actions.append({'tool':'write','arguments':{'path':'/work/'+slot+'/memweave_fixture_change.txt',
                                'content':'Offline first-mutation control; never part of a real solve.'}})
                        actions.append({'tool':'task_create','arguments':{'title':label,
                            'goal':'ROUTE '+label+'\nMaintain /work/'+slot+' source objective',
                            'project_name':'Switch source '+slot,'summary':(task/'steps'/name/'instruction.md').read_text()[:200],
                            'keywords':label.split('-')}})
                        actions.append({'tool':'memory_read','arguments':{'items':[{'$latest_user_origin':True}],
                            'max_total_chars':50000}})
                        actions.append({'tool':'state_append','arguments':{'items':[{'type':'fact',
                            'content':'AUDIT '+AUDIT_TAGS[contract['case_id']][slot],
                            'evidence':{'$latest_read_ref':'Audit tag from the observed source read for this work record'}}]}})
                    elif current!=slot:actions.extend(restore(label))
                current=slot;actions.append({'text':'Source objective retained; offline control only.'})
            elif name==contract['ephemeral_step']:
                if self.options.variant=='pi-memweave'and self.options.switch_fixture_mode=='unnecessary-create':
                    actions.append({'tool':'task_create','arguments':{'title':'Temporary arithmetic',
                        'goal':'ROUTE unnecessary-arithmetic\nCompute six multiplied by seven',
                        'project_name':'Temporary question','summary':'Intentionally wrong persistent creation control',
                        'keywords':['arithmetic']}})
                    current='arithmetic'
                actions.append({'text':'42'})
            elif name in probes:
                probe=probes[name];slot=probe['slot'];label=probe['route_id']
                if self.options.variant=='pi-memweave':
                    if self.options.switch_fixture_mode=='wrong-binding'and probe.get('search_requested',True):
                        actions.append({'tool':'task_find','arguments':{'query':label,'limit':3}})
                    elif current!=slot:
                        actions.extend(restore(label));current=slot
                    elif probe.get('search_requested',True):
                        actions.append({'tool':'task_find','arguments':{'query':label,'limit':3}})
                value=dict(probe['expected'])
                if self.options.switch_fixture_mode=='wrong-audit':value['audit_tag']='wrong-earlier-audit-tag'
                actions.extend([{'tool':'write','arguments':{'path':'/work/'+probe['filename'],
                    'content':json.dumps(value,separators=(',',':'))}},{'text':'Recall checkpoint written; offline control only.'}])
            else:actions.append({'text':'Offline control finished; no source solution or official score is claimed.'})
            stages[str(index)]=actions
        self._scenario_path=self._asset_root+'/evaluation/switch-probe-control.json'
        await self.upload_private(environment,json.dumps({'stages':stages,'fixture_only':True}),self._scenario_path)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_scenario_path',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._scenario_path)
        return await super().exec_as_agent(environment,command,**kwargs)
