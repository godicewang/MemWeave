"""Actual multi-step Pi CLI with a local provider, never reads real credentials."""
from __future__ import annotations

import json
import time

from harbor.agents.installed.pi import Pi

from .pi_agent import ExperimentPi


class FreeEpisodePi(ExperimentPi):
    async def install(self, environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('free episode requires preparation mode without credentials')
        await super().install(environment)
        await self.upload_private(environment,json.dumps({'deepseek':{'type':'api_key','key':'fixture-only'}}),
            self._asset_root+'/evaluation/private-auth.json')
        await self.upload_private(environment,json.dumps({'deepseek':{'type':'api_key','key':'memweave-evaluation-guard-placeholder'}}),
            self._experiment_home+'/.pi/agent/auth.json')
        await self.upload_private(environment,json.dumps({'schema_version':1,'maximum_usd':10.,
            'deadline':self.options.evaluation_deadline,'requests':{},'exposure_usd':0.,'arm_limits':{}}),
            '/logs/agent/cli-probe-quota.json')

    async def run(self,instruction,environment,context):
        self._agent_started=time.monotonic()
        self._evaluation_stage=getattr(self,'_evaluation_stage',0)+1
        await self.upload_private(environment,instruction,self._asset_root+'/evaluation/instruction.md')
        await Pi.run(self,instruction,environment,context)
