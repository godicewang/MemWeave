"""Only output-format software controls; no optical solution or real credential."""
from __future__ import annotations

import json
from typing import Literal

from .free_episode import FreeEpisodePi
from .pi_agent import PiExperimentOptions


class WdmOptions(PiExperimentOptions):
    wdm_fixture_mode:Literal['positive','gray','bad-geometry','absent']='positive'


class WdmArtifactFreePi(FreeEpisodePi):
    options_model=WdmOptions
    options:WdmOptions

    async def install(self,environment):
        if not self.options.prepare_only or self.options.auth_path:
            raise ValueError('WDM format controls require preparation mode without credentials')
        await super().install(environment)
        if self.options.evaluation_case_id!='LONG-02':raise ValueError('WDM control requires its source case')
        mode=self.options.wdm_fixture_mode
        meta={'design_region_size_um':[2.5,2.5],'design_grid_shape':[32,32],
            'input_waveguide_width_um':.4,'long_band_output':{'y_center_um':.6,'width_um':.4},
            'short_band_output':{'y_center_um':-.6,'width_um':.4},'fdtd_resolution':20}
        if mode=='bad-geometry':meta['long_band_output']['y_center_um']=-.6
        code='import json\nfrom pathlib import Path\nimport numpy as np\n'
        code+='Path("/app/meta.json").write_text('+repr(json.dumps(meta))+')\n'
        if mode!='absent':code+='np.save("/app/design.npy",np.full((32,32),'+('.5'if mode=='gray'else'0.')+',dtype=np.float64))\n'
        actions=[]
        if self.options.variant=='pi-memweave':
            actions.append({'tool':'task_create','arguments':{'title':'WDM artifact control',
                'goal':'Validate the output-format collector only; this is not a solved photonics task.',
                'project_name':'wdm-design','summary':'No optical score claimed','keywords':['wdm','control']}})
        actions.extend([{'tool':'bash','arguments':{'command':"python3 - <<'PY'\n"+code+'PY'}},
            {'text':'Output-format software control finished; optical design quality was not tested.'}])
        self._wdm_scenario=self._asset_root+'/evaluation/wdm-artifact-control.json'
        await self.upload_private(environment,json.dumps({'stages':{'1':actions},'fixture_only':True}),self._wdm_scenario)

    async def exec_as_agent(self,environment,command,**kwargs):
        if getattr(self,'_wdm_scenario',None):
            kwargs['env']=dict(kwargs.get('env')or{},MEMWEAVE_EVAL_SCENARIO_PATH=self._wdm_scenario)
        return await super().exec_as_agent(environment,command,**kwargs)
