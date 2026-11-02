"""Pinned STATE harness around actual Pi CLI; all application/gold state stays host-side.

This is explicitly a derived full-Pi interface, not the stock STATE tool-only agent.
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

from .aux_client import GuardedAuxClient
from .domain_backend import DomainBackend
from .pi_agent import ExperimentPi, PiExperimentOptions


def final_pi_text(path):
    final=''
    for line in path.read_text().splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        message=value.get('message',{})
        if value.get('type')=='message_end' and message.get('role')=='assistant':
            text='\n'.join(p['text']for p in message.get('content',[])if p.get('type')=='text')
            if text:final=text
            elif any(p.get('type')=='toolCall' and p.get('name')=='task_clarify'for p in message.get('content',[])):
                final='\n'.join(p.get('arguments',{}).get('question','')for p in message['content']if p.get('name')=='task_clarify')
    return final


class StatePiOptions(PiExperimentOptions):
    state_source_path:str
    state_selector:str
    evaluation_host_ledger:str
    state_evaluator_output:str
    evaluation_judge_deadline:float


class StatePi(ExperimentPi):
    options_model=StatePiOptions
    options:StatePiOptions

    async def install(self,environment):
        if not self.options.prepare_only:
            hard=json.loads(Path(self.options.evaluation_host_ledger).read_text())['deadline']
            if not self.options.evaluation_deadline <= self.options.evaluation_judge_deadline <= hard:
                raise ValueError('STATE judge deadline must follow actor cutoff and remain within global quota deadline')
        await super().install(environment)
        self._private_output=Path(self.options.state_evaluator_output).resolve()/self.logs_dir.parent.name
        mounted=self.logs_dir.resolve()
        if self._private_output==mounted or mounted in self._private_output.parents:
            raise ValueError('STATE evaluator artifacts must be outside actor-mounted logs')
        self._private_output.mkdir(parents=True,exist_ok=False)
        (self.logs_dir/'state-evaluator-link.json').write_text(json.dumps({'host_only_path':str(self._private_output)}))
        source=Path(self.options.state_source_path)
        sys.path.insert(0,str(source))
        from state_bench.domain import get_domain_config
        from state_bench.env_loader import load_task_environment
        from state_bench.schemas import TaskDefinition
        domain_name,task_id=self.options.state_selector.split('/',1)
        self._domain=get_domain_config(domain_name)
        self._state_task=TaskDefinition.load(source/'state_bench/domains'/domain_name/'tasks'/(task_id+'.json'))
        self._state_data,_=load_task_environment(self._domain,self._state_task)
        self._state_environment=self._domain.environment_class(self._state_data.deep_copy(),now=self._state_task.now)
        self._backend=DomainBackend(self._state_environment,self._private_output/'domain-events.jsonl',
            self.logs_dir/'domain-exchange',{
            'run_id':self.options.evaluation_run_id,'case_id':self.options.evaluation_case_id,
            'arm':self.options.variant})
        self._backend.start()
        self._evaluation_domain_descriptor=self._asset_root+'/evaluation/domain.json'
        self._evaluation_extra_extensions=[self._asset_root+'/evaluation/domain_tools.ts']
        descriptor={'exchange':'/logs/agent/domain-exchange','token':self._backend.token,
                    'tools':self._domain.tool_schemas,
                    'system_prompt':self._domain.agent_system_prompt.format(now=self._state_task.now,user_id=self._state_task.user_id)}
        if self.options.prepare_only:
            descriptor['probe']=({'name':'get_customer','arguments':{'customer_id':self._state_task.user_id}}
                if domain_name=='customer_support' else
                {'name':'get_user_details','arguments':{'user_id':self._state_task.user_id}})
        await environment.upload_file(Path(__file__).with_name('domain_tools.ts'),self._evaluation_extra_extensions[0])
        await self.upload_private(environment,json.dumps(descriptor),self._evaluation_domain_descriptor)
        await self.exec_as_agent(environment,'test -d /logs/agent/domain-exchange/requests && test -d /logs/agent/domain-exchange/responses',timeout_sec=20)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_evaluation_domain_descriptor',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_DOMAIN_DESCRIPTOR=self._evaluation_domain_descriptor)
        return await super().exec_as_agent(environment,command,**kwargs)

    async def _turn(self,text,environment,context,index):
        self._resume=index>0
        try:
            await super().run(text,environment,context)
            return final_pi_text(self.logs_dir/'pi.txt')
        finally:self._resume=False

    async def run(self,instruction,environment,context):
        try:
            if self.options.prepare_only or self.options.evaluation_canary:
                return await super().run(instruction,environment,context)
            from state_bench.agents.base import BaseAgent
            from state_bench.orchestrator import run_task
            from state_bench.scoring import TaskRequirementsJudge, UXQualityJudge
            from state_bench.scripts.score import score_one
            loop=asyncio.get_running_loop();owner=self
            from .pair_barrier import paired_start
            self._episode_started_unix=await paired_start(
                Path(self.options.evaluation_pair_barrier)if self.options.evaluation_pair_barrier else None,
                self.options.variant)
            episode_deadline=min(self.options.evaluation_deadline,self._episode_started_unix+
                self.options.evaluation_task_timeouts.get(self._evaluation_task_id,1800))
            class Agent(BaseAgent):
                def __init__(self):super().__init__();self.turn_index=0;self.partial=[]
                def act(self,conversation):
                    before=len(owner._backend.calls)
                    self.partial.append(copy.deepcopy(conversation[-1]))
                    try:
                        text=asyncio.run_coroutine_threadsafe(owner._turn(conversation[-1]['content'],
                            environment,context,self.turn_index),loop).result(timeout=1800)
                    except Exception:
                        calls=[{k:r[k]for k in ('name','arguments','result')}for r in owner._backend.calls[before:]]
                        self.partial.append({'role':'assistant','content':final_pi_text(owner.logs_dir/'pi.txt')
                            if (owner.logs_dir/'pi.txt').exists()else '', 'tool_calls':calls})
                        raise
                    self.turn_index+=1
                    calls=[{k:r[k]for k in ('name','arguments','result')}for r in owner._backend.calls[before:]]
                    self.partial.append({'role':'assistant','content':text,'tool_calls':calls})
                    return text,calls,[{'role':'assistant','content':text}]
            def client(role):
                return GuardedAuxClient(ledger=self.options.evaluation_host_ledger,
                    trace=self._private_output/(role+'-transport.jsonl'),evidence=self._private_output/(role+'-content'),
                    auth=self.options.auth_path,arm=self.options.variant,case_id=self.options.evaluation_case_id,
                    run_id=self.options.evaluation_run_id,
                    deadline=self.options.evaluation_judge_deadline if role=='official_judge' else episode_deadline,role=role,
                    max_output=self.options.evaluation_output_tokens,episode_budget=self.options.evaluation_episode_budget)
            actor=Agent();initial=copy.deepcopy(self._state_environment.get_full_snapshot())
            try:
                trajectory=await asyncio.to_thread(run_task,self._state_task,self._state_data,
                    self._state_task.user_id,None,self._domain,actor,self._state_environment,
                    {'interface':'DERIVED full Pi and MemWeave tools; official domain backend unchanged'},client('user_simulator'))
            except Exception as error:  # noqa: BLE001 -- preserve partial evidence and an explicit unclassified stop.
                from state_bench.schemas import StateDiff, Trajectory
                from state_bench.scoring import compute_efficiency
                calls=[{k:r[k]for k in ('name','arguments','result')}for r in self._backend.calls]
                # Preserve actual partial work, not an invented successful transcript.
                trajectory=Trajectory(task_id=self._state_task.task_id,user_id=self._state_task.user_id,
                    task_summary=self._state_task.task_summary,conversation=actor.partial,
                    state_diff=StateDiff.compute(initial,self._state_environment.get_full_snapshot()),
                    efficiency=compute_efficiency(actor.partial,calls),
                    metadata={'interface':'DERIVED full Pi; actual partial episode',
                              'stop_classification':'UNCLASSIFIED_ACTOR_OR_HARNESS_ERROR'},error=type(error).__name__)
            original=self._private_output/'state-trajectory-original.json';trajectory.save(original)
            judge=client('official_judge')
            task_judge=TaskRequirementsJudge(judge,self._domain.prompts_dir,self._domain.judge_system_prompt)
            ux_judge=UXQualityJudge(judge,self._domain.prompts_dir,self._domain.judge_system_prompt)
            scored=await asyncio.to_thread(score_one,original,
                Path(self.options.state_source_path)/'state_bench/domains'/self._domain.name/'tasks',
                task_judge,ux_judge,self._private_output/'state-official-scores.json')
            (self._private_output/'state-scoring-status.json').write_text(json.dumps(scored))
        finally:
            if getattr(self,'_backend',None):self._backend.close()
