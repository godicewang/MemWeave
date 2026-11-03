"""Known source-value controls through the real isolated portal and Pi tools."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .free_episode import FreeEpisodePi
from .pi_agent import PiExperimentOptions
from .warranty_pi import WarrantyEvidenceMixin


class WarrantyOptions(PiExperimentOptions):
    warranty_gold_path:str
    warranty_fixture_mode:Literal['positive','late-card','wrong-then-repair','no-submit']='positive'


class WarrantyFreePi(WarrantyEvidenceMixin,FreeEpisodePi):
    options_model=WarrantyOptions
    options:WarrantyOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:raise ValueError('warranty control requires preparation-only without credentials')
        await super().install(environment)
        gold=json.loads(Path(self.options.warranty_gold_path).read_text())
        if gold['case_id']!='TB-02':raise ValueError('selected warranty fixture identity differs')
        payloads={k:{field:value for field,value in v.items()if field in {
            'action','basis_code','covered_parts_eur','covered_labor_eur','evidence_refs'}}for k,v in gold['expected_cases'].items()}
        private=self._asset_root+'/evaluation/warranty-reference-fixture'
        await self.upload_private(environment,json.dumps(payloads),private+'/decisions.json')
        code='''import json,sys,urllib.request
from pathlib import Path
payload=json.loads(Path(__file__).with_name('decisions.json').read_text())[sys.argv[1]]
if len(sys.argv)>2:payload['covered_parts_eur']+=1
request=urllib.request.Request('http://warranty-portal:8000/claims/'+sys.argv[1]+'/decision',
    data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(request,timeout=20) as response:print(response.read().decode())
'''
        await self.upload_private(environment,code,private+'/submit.py')
        actions=[]
        if self.options.variant=='pi-memweave':actions.append({'tool':'task_create','arguments':{
            'title':'Warranty queue software control','goal':'Resolve the supplied warranty queue with claim-scoped business evidence',
            'project_name':'heat-pump-warranty','summary':'Isolated known-value evaluator control only','keywords':['warranty','claims']}})
        for identity in sorted(payloads):
            record=None
            if self.options.variant=='pi-memweave'and identity in gold['memory_claims']:
                card=json.dumps({'c':identity,'b':payloads[identity]['basis_code'],'q':'claim-only'},separators=(',',':'))
                if len(card)>100:raise ValueError('fixture record exceeds unchanged public 100-character policy')
                record={'tool':'state_append','arguments':{'items':[{'type':'fact','content':card,'evidence':{'U1':'Claim-specific decision from the supplied business task; software control only'}}]}}
            if record and self.options.warranty_fixture_mode!='late-card':actions.append(record)
            command='python3 '+private+'/submit.py '+identity
            if self.options.warranty_fixture_mode=='wrong-then-repair'and identity=='CLM-2601':command=command+' wrong\n'+command
            actions.append({'tool':'bash','arguments':{'command':command}})
            if record and self.options.warranty_fixture_mode=='late-card':actions.append(record)
        actions.append({'text':'Known-value software control finished; this is not a model capability result.'})
        if self.options.warranty_fixture_mode=='no-submit':actions=actions[-1:]
        self._warranty_scenario=self._asset_root+'/evaluation/warranty-control.json'
        await self.upload_private(environment,json.dumps({'stages':{'1':actions},'fixture_only':True}),self._warranty_scenario)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_warranty_scenario',None):kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._warranty_scenario)
        return await super().exec_as_agent(environment,command,**kwargs)
