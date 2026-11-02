"""STATE simulator/judge transport; no default Azure client or secondary budget."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class GuardedAuxClient:
    def __init__(self, *, ledger, trace, evidence, auth, arm, case_id, run_id, deadline,
                 role, node='node', max_output=8192,episode_budget=None):
        if role not in {'user_simulator','official_judge','preflight'}:
            raise ValueError('unregistered auxiliary role')
        self.options={'ledger': str(ledger),'trace': str(trace),'evidence': str(evidence),'auth': str(auth),
                          'arm': arm,'case_id': case_id,'run_id': run_id,'deadline': deadline,'role': role}
        self.node,self.max_output=node,max_output
        self.episode_budget=episode_budget

    @property
    def provider_name(self):return 'deepseek'

    @property
    def model_name(self):return 'deepseek-flash'

    def _request(self,messages,max_tokens,temperature,json_mode):
        o=self.options
        env=dict(os.environ,MEMWEAVE_EVAL_LEDGER=o['ledger'],MEMWEAVE_EVAL_TRACE=o['trace'],
                 MEMWEAVE_EVAL_CONTENT_STORE=o['evidence'],MEMWEAVE_EVAL_CREDENTIAL_FILE=o['auth'],
                 MEMWEAVE_EVAL_VARIANT=o['arm'],MEMWEAVE_EVAL_BUDGET_ARM=o['arm'],
                 MEMWEAVE_EVAL_CASE_ID=o['case_id'],MEMWEAVE_EVAL_RUN_ID=o['run_id'],
                 MEMWEAVE_EVAL_DEADLINE=str(o['deadline']),MEMWEAVE_EVAL_ROLE=o['role'],
                 MEMWEAVE_EVAL_MAX_OUTPUT=str(self.max_output))
        env['MEMWEAVE_EVAL_EPISODE_BUDGET']=str(self.episode_budget or 0)
        payload={'messages':messages,'max_tokens':min(max_tokens,self.max_output),
                 'temperature':temperature,'json':json_mode}
        result=subprocess.run([self.node,str(Path(__file__).with_name('aux_request.mjs'))],
                              input=json.dumps(payload),text=True,capture_output=True,env=env,timeout=180,check=False)
        if result.returncode:
            # Provider errors can contain model content; diagnostic originals remain local.
            raise RuntimeError('Guarded auxiliary request failed; inspect local transport evidence')
        return json.loads(result.stdout)

    def complete_chat(self,messages,max_tokens=8192,temperature=None):
        return self._request(messages,max_tokens,temperature,False)['text']

    def complete_json(self,prompt,system_prompt=None,max_tokens=8192,reasoning_effort=None):
        messages=([{'role':'system','content':system_prompt}]if system_prompt else [])
        messages.append({'role':'user','content':prompt})
        return json.loads(self._request(messages,max_tokens,None,True)['text'])
