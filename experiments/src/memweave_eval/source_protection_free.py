"""Known-good/bad actual Pi controls; private answers never reach real runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .free_episode import FreeEpisodePi
from .pi_agent import PiExperimentOptions


class ProtectionOptions(PiExperimentOptions):
    protection_contract_path:str
    protection_fixture_mode:Literal['positive','late-write','change-restore']='positive'


class ProtectionFreePi(FreeEpisodePi):
    options_model=ProtectionOptions
    options:ProtectionOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('protection control requires preparation mode without credentials')
        await super().install(environment)
        contract=json.loads(Path(self.options.protection_contract_path).read_text())
        case=contract['case_id']
        if case!=self.options.evaluation_case_id:raise ValueError('source protection control identity differs')
        protected={'LONG-03':'/app/work/alpine.qcow2','LONG-04':'/app/Cargo.toml',
            'TB-08':'/app/data/incidents/parity-2026-10/manifest.json'}[case]
        mutable={'LONG-03':'/app/work/OVMF_VARS.fd','LONG-04':'/app/crates/common/src/lib.rs',
            'TB-08':'/app/parityctl/__init__.py'}[case]
        bodies=[json.dumps(g,separators=(',',':'))for g in contract['record_gold']]
        if any(len(body)>100 for body in bodies):raise ValueError('control record exceeds the unchanged prompt policy target')
        record=[{'tool':'state_append','arguments':{'items':[{'type':'fact','content':body,
            'evidence':{'$latest_read_ref':'The original source instruction defines this immutable material.'}}for body in bodies]}}]
        actions=[]
        if self.options.variant=='pi-memweave':
            actions=[{'tool':'task_create','arguments':{'title':'Source protection control',
                'goal':'Implement the original source task while preserving its declared immutable source materials.',
                'project_name':case,'summary':'Offline oracle control, not task completion','keywords':['source','protection']}},
                {'tool':'memory_read','arguments':{'items':[{'$latest_user_origin':True}],'max_total_chars':50000}}]
            if self.options.protection_fixture_mode!='late-write':actions+=record
        if self.options.protection_fixture_mode=='change-restore':
            code='from pathlib import Path\np=Path('+repr(protected)+')\nb=p.read_bytes()\nPath("/tmp/f35-source-backup.bin").write_bytes(b)\np.write_bytes(bytes([b[0]^1])+b[1:])\n'
            actions.extend([{'tool':'bash','arguments':{'command':"python3 - <<'PY'\n"+code+'PY'}},
                {'tool':'bash','arguments':{'command':"python3 - <<'PY'\nfrom pathlib import Path\nPath("+
                    repr(protected)+').write_bytes(Path("/tmp/f35-source-backup.bin").read_bytes())\nPY'}}])
        if case=='LONG-03':code='from pathlib import Path\np=Path('+repr(mutable)+')\nb=p.read_bytes();p.write_bytes(bytes([b[0]^1])+b[1:])\n'
        else:code='from pathlib import Path\np=Path('+repr(mutable)+')\nwith p.open("a")as f:f.write("\\n// offline control\\n"if p.suffix==".rs"else"\\n# offline control\\n")\n'
        actions.append({'tool':'bash','arguments':{'command':"python3 - <<'PY'\n"+code+'PY'}})
        if self.options.variant=='pi-memweave'and self.options.protection_fixture_mode=='late-write':actions+=record
        actions.append({'text':'Offline source-protection control finished. No original task score is claimed.'})
        self._scenario_path=self._asset_root+'/evaluation/source-protection-control.json'
        await self.upload_private(environment,json.dumps({'stages':{'1':actions},'fixture_only':True}),self._scenario_path)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_scenario_path',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._scenario_path)
        return await super().exec_as_agent(environment,command,**kwargs)
