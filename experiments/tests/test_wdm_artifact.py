import json
import struct
from copy import deepcopy

import pytest

from memweave_eval.wdm_artifact import artifact_checkpoint, inspect_npy


def npy(values=None, *, shape=(32,32), dtype='<f8', version=(1,0)):
    values=values or [0.]*(shape[0]*shape[1])
    header=repr({'descr':dtype,'fortran_order':False,'shape':shape}).encode()+b'\n'
    return b'\x93NUMPY'+bytes(version)+struct.pack('<H',len(header))+header+b''.join(struct.pack('<d',v)for v in values)


def meta():
    return {'design_region_size_um':[2.5,2.5],'design_grid_shape':[32,32],
        'input_waveguide_width_um':.4,'long_band_output':{'y_center_um':.6,'width_um':.4},
        'short_band_output':{'y_center_um':-.6,'width_um':.4},'fdtd_resolution':20}


def test_independent_array_reader_has_strict_binary_edges_no_pickle_and_bounded_headers():
    assert inspect_npy(npy())['binary_count']==1024
    values=[0.]*1024;values[0]=.05;values[1]=.95
    assert inspect_npy(npy(values))['binary_count']==1022
    assert inspect_npy(npy(dtype='|O'))['status']=='invalid'
    assert inspect_npy(npy()[:-1])['status']=='invalid'
    assert inspect_npy(npy()+b'trailing')['trailing_bytes']==8,'np.load reads the first complete array'
    assert inspect_npy(npy(version=(4,0)))['status']=='unsupported'
    one=npy();length=int.from_bytes(one[8:10],'little')
    two=one[:6]+b'\x02\x00'+struct.pack('<I',length)+one[10:]
    assert inspect_npy(two)['shape']==[32,32]
    assert inspect_npy(b'not numpy')['status']=='invalid'
    values[0]=float('nan')
    assert inspect_npy(npy(values))['finite_count']==1023


def test_checkpoint_has_separate_mandatory_geometry_and_array_checks():
    result=artifact_checkpoint(json.dumps(meta()).encode(),npy(),complete=True)
    assert result['score']==100 and len(result['assertions'])>=10
    changes=[('design_region_size_um',[1.,2.5]),('design_grid_shape',[33,32]),
        ('input_waveguide_width_um',.2),('fdtd_resolution',31),
        ('long_band_output',{'y_center_um':-.7,'width_um':.4}),
        ('long_band_output',{'y_center_um':2,'width_um':.4}),
        ('long_band_output',{'y_center_um':.05,'width_um':.4})]
    for key,value in changes:
        changed=deepcopy(meta());changed[key]=value
        assert artifact_checkpoint(json.dumps(changed).encode(),npy(),complete=True)['score']==0
    values=[0.]*1024;values[0]=.5
    assert artifact_checkpoint(json.dumps(meta()).encode(),npy(values),complete=True)['score']==0
    assert artifact_checkpoint(b'{"design_grid_shape":',npy(),complete=True)['score']==0
    text=json.dumps(meta());duplicate=text[:-1]+',"fdtd_resolution":20}'
    assert artifact_checkpoint(duplicate.encode(),npy(),complete=True)['score']==100,'match original json.load last-value semantics'
    wrong=meta();wrong['input_waveguide_width_um']='0.4'
    assert artifact_checkpoint(json.dumps(wrong).encode(),npy(),complete=True)['score']==0
    assert artifact_checkpoint(json.dumps(meta()).encode(),None,complete=True)['score']==0
    missing=artifact_checkpoint(json.dumps(meta()).encode(),npy(),complete=False)
    assert missing['score']is None and not missing['collection_complete']
    assert artifact_checkpoint(json.dumps(meta()).encode(),npy(version=(4,0)),complete=True)['score']is None


def test_derived_report_row_preserves_support_and_has_no_duplicate_weight():
    from memweave_eval.wdm_artifact import checkpoint_rows
    row,=checkpoint_rows({'checkpoint':artifact_checkpoint(json.dumps(meta()).encode(),npy(),complete=True)})
    assert row['score']==100 and row['support_s']==row['support_n']==1
    assert row['weights']=={'common_product':0,'plugin_memory':0}and row['evidence_coverage']==1
    row,=checkpoint_rows({'checkpoint':artifact_checkpoint(None,None,complete=False)})
    assert row['score']is None and row['support_u']==1 and row['evidence_coverage']==0


@pytest.mark.parametrize('bad',[None,[],True,{'design_region_size_um':['NaN',2.5]}])
def test_invalid_observed_metadata_does_not_become_unknown_or_crash(bad):
    assert artifact_checkpoint(json.dumps(bad).encode(),npy(),complete=True)['score']==0


def test_terminal_evidence_absence_and_missing_store_are_different(tmp_path,monkeypatch):
    from memweave_eval.wdm_artifact import VERSION, grade_wdm_trial
    event={'event':'workspace_checkpoint','phase':'agent_end','producer_id':'p','sequence':1,
        'workspace':{'artifacts':{'meta.json':{'status':'absent'},'design.npy':{'status':'absent'}}}}
    monkeypatch.setattr('memweave_eval.wdm_artifact.case_events',lambda trial:([event],{('p',1):tmp_path}))
    monkeypatch.setattr('memweave_eval.wdm_artifact.execution_boundaries',lambda trial,events:{'complete':True})
    contract={'version':VERSION,'case_id':'LONG-02'}
    assert grade_wdm_trial(tmp_path,contract)['checkpoint']['score']==0
    event['workspace']['artifacts']['meta.json']={'status':'captured','ref':{}}
    assert grade_wdm_trial(tmp_path,contract)['checkpoint']['score']is None
    event['workspace']['artifacts']['meta.json']={'status':'incomplete'}
    assert grade_wdm_trial(tmp_path,contract)['collection_complete']is False


def test_corrupt_evidence_object_never_becomes_an_absent_file_failure(tmp_path,monkeypatch):
    from memweave_eval.wdm_artifact import VERSION, grade_wdm_trial
    event={'event':'workspace_checkpoint','phase':'agent_end','producer_id':'p','sequence':1,
        'workspace':{'artifacts':{name:{'status':'captured','ref':{}}for name in ('meta.json','design.npy')}}}
    monkeypatch.setattr('memweave_eval.wdm_artifact.case_events',lambda trial:([event],{('p',1):tmp_path}))
    monkeypatch.setattr('memweave_eval.wdm_artifact.execution_boundaries',lambda trial,events:{'complete':True})
    def broken(*a):raise EOFError('truncated gzip')
    monkeypatch.setattr('memweave_eval.wdm_artifact.read_object',broken)
    result=grade_wdm_trial(tmp_path,{'version':VERSION,'case_id':'LONG-02'})
    assert result['checkpoint']['score']is None and not result['collection_complete']
