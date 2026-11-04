"""Independent LONG-02 output-format checkpoint, not an optical-quality grader."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import struct
import subprocess
from pathlib import Path

from .evidence_replay import read_object
from .fixed35 import checkpoint_verdict
from .fixed35_business import case_events, execution_boundaries
from .storage import atomic_json, file_digest
from .suites import task_digest

VERSION='fixed35-wdm-artifact-20261103-v1'
CHECKS=['artifacts_present','metadata_schema','region_bounds','grid_bounds','width_bounds',
    'resolution_bounds','outputs_inside','outputs_opposite','output_gap','npy_float64',
    'array_shape_matches','finite_array_range','all_pixels_binary']


def inspect_npy(data):
    if len(data)>1048576:return {'status':'unsupported','reason':'array exceeds frozen parser cap'}
    if len(data)<10 or data[:6]!=b'\x93NUMPY':return {'status':'invalid','reason':'not a complete NPY header'}
    version=tuple(data[6:8])
    if version not in {(1,0),(2,0),(3,0)}:return {'status':'unsupported','reason':'unimplemented NPY version'}
    start=10 if version==(1,0)else 12
    try:
        length=int.from_bytes(data[8:start],'little')
        if length>16384:return {'status':'unsupported','reason':'header exceeds frozen parser cap'}
        header=ast.literal_eval(data[start:start+length].decode('utf8'if version==(3,0)else'latin1').strip())
        if not isinstance(header,dict)or set(header)!={'descr','fortran_order','shape'}:raise ValueError('invalid header')
        shape=header['shape'];dtype=header['descr']
        if type(header['fortran_order'])is not bool or not isinstance(shape,tuple)or len(shape)!=2 or any(type(n)is not int or n<1 for n in shape):
            raise ValueError('not a two dimensional array')
        if dtype not in {'<f8','=f8','>f8','|f8'}:return {'status':'invalid','reason':'array is not float64','dtype':dtype}
        count=math.prod(shape)
        if count>65536:return {'status':'invalid','reason':'array dimensions exceed source maximum'}
        raw=data[start+length:]
        if len(raw)<8*count:raise ValueError('array payload shorter than its declared shape')
        values=[v[0]for v in struct.iter_unpack('>d'if dtype=='>f8'else'<d',raw[:8*count])]
        return {'status':'complete','dtype':dtype,'native_float64':dtype!='>f8','shape':list(shape),
            'count':count,'trailing_bytes':len(raw)-8*count,'finite_count':sum(math.isfinite(v)for v in values),
            'range_count':sum(math.isfinite(v)and -1e-9<=v<=1+1e-9 for v in values),
            'binary_count':sum(v<.05 or v>.95 for v in values)}
    except (ValueError,TypeError,UnicodeError,SyntaxError,struct.error,OverflowError):
        return {'status':'invalid','reason':'malformed NPY header or data'}


def artifact_checkpoint(meta_bytes,array_bytes,*,complete):
    checks={k:None for k in CHECKS}
    if not complete:
        return checkpoint_verdict({'id':VERSION,'required_assertions':CHECKS},checks)
    checks['artifacts_present']=meta_bytes is not None and array_bytes is not None
    try:
        meta=json.loads(meta_bytes)if meta_bytes is not None else None
        if not isinstance(meta,dict):raise TypeError('metadata is not an object')
        if type(meta.get('input_waveguide_width_um'))not in (int,float)or type(meta.get('fdtd_resolution'))not in (int,float):
            raise ValueError('source requires numeric width and resolution fields')
        region=meta['design_region_size_um'];grid=meta['design_grid_shape']
        if not isinstance(region,list)or len(region)!=2 or not isinstance(grid,list)or len(grid)!=2:raise ValueError('invalid dimension pairs')
        long=meta['long_band_output'];short=meta['short_band_output']
        if not isinstance(long,dict)or not isinstance(short,dict):raise TypeError('invalid ports')
        def number(v):
            if type(v)is bool:raise ValueError('boolean is not a geometry number')
            value=float(v)
            if not math.isfinite(value):raise ValueError('nonfinite geometry')
            return value
        lx,ly=map(number,region);nx,ny=map(number,grid)
        wi,wl,ws=map(number,[meta['input_waveguide_width_um'],long['width_um'],short['width_um']])
        yl,ys=map(number,[long['y_center_um'],short['y_center_um']]);resolution=number(meta['fdtd_resolution'])
        checks.update(metadata_schema=True,region_bounds=2<=lx<=3.2 and 2<=ly<=3.2,
            grid_bounds=all(v.is_integer()and 32<=v<=256 for v in (nx,ny)),
            width_bounds=all(.3<=v<=.6 for v in (wi,wl,ws)),resolution_bounds=15<=resolution<=30,
            outputs_inside=abs(yl)+wl/2<=ly/2+1e-9 and abs(ys)+ws/2<=ly/2+1e-9,
            outputs_opposite=yl*ys<0,output_gap=abs(yl-ys)>=max(wl,ws)+.3-1e-9)
    except (ValueError,TypeError,KeyError,OverflowError):
        meta=None
        for key in CHECKS[1:9]:checks[key]=False
    array=inspect_npy(array_bytes)if array_bytes is not None else{'status':'invalid','reason':'array absent'}
    if array['status']=='complete':
        checks.update(npy_float64=array['native_float64'],array_shape_matches=array['shape']==[nx,ny]if meta is not None else False,
            finite_array_range=array['finite_count']==array['count']==array['range_count'],
            all_pixels_binary=array['binary_count']==array['count'])
    elif array['status']=='invalid':
        for key in CHECKS[9:]:checks[key]=False
    result=checkpoint_verdict({'id':VERSION,'required_assertions':CHECKS},checks)
    result.update(array_summary=array,scope='Geometry/NPY/binary output contract only; excludes minimum-feature DRC and optical performance')
    return result


def wdm_contract(case,source:Path,output:Path):
    revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if case['pack_case_id']!='LONG-02'or source.name!='wdm-design'or revision!=case['source_revision']or subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True):
        raise ValueError('selected WDM source pin differs')
    if '`design.npy`'not in(source/'instruction.md').read_text():raise ValueError('source artifact specification missing')
    result={'version':VERSION,'adapter_kind':'wdm-artifact-v1','case_id':'LONG-02','fixture_only':False,
        'source_revision':revision,'source_task_sha256':task_digest(source),
        'source_instruction_sha256':file_digest(source/'instruction.md'),
        'source_verifier_sha256':file_digest(source/'tests/test_state.py'),
        'required_assertions':CHECKS,'task_config':{'workspace':{'root':'/app','files':[],
            'artifact_files':{'meta.json':65536,'design.npy':1048576}}},
        'public_overlay':None,'not_formal_admission':True,
        'excluded_original_checks':['minimum-feature DRC','FDTD short/long band transmission and leakage']}
    output.mkdir(parents=True,exist_ok=False);atomic_json(output/'contract.json',result,immutable=True)
    return result


def grade_wdm_trial(trial,contract):
    if contract.get('version')!=VERSION or contract.get('case_id')!='LONG-02':raise ValueError('matching frozen WDM contract required')
    events,locations=case_events(trial);coverage=execution_boundaries(trial,events)
    ends=[e for e in events if e['event']in {'workspace_checkpoint','execution_terminated','execution_deadline_snapshot'}and e.get('phase')in {'agent_end','execution_terminated','execution_deadline_snapshot'}]
    terminal=ends[-1]if ends else None;artifacts=terminal.get('workspace',{}).get('artifacts',{})if terminal else{}
    complete=bool(terminal)and coverage['complete'];bodies={};proof={}
    for name in ('meta.json','design.npy'):
        receipt=artifacts.get(name,{})
        if receipt.get('status')=='absent':bodies[name]=None
        elif receipt.get('status')=='captured'and terminal:
            try:
                raw=read_object(locations[(terminal['producer_id'],terminal['sequence'])],receipt['ref'])
                if hashlib.sha256(raw).hexdigest()!=receipt.get('sha256')or len(raw)!=receipt.get('bytes'):raise ValueError('artifact receipt differs')
                bodies[name]=raw;proof[name]={'sha256':receipt['sha256'],'bytes':len(raw)}
            except (KeyError,ValueError,OSError,EOFError):complete=False
        else:complete=False
    result=artifact_checkpoint(bodies.get('meta.json'),bodies.get('design.npy'),complete=complete)
    return {'version':VERSION,'case_id':'LONG-02','checkpoint':result,'boundary_coverage':coverage,
        'collection_complete':result['collection_complete'],'artifact_proof':proof,
        'fixture_only':contract.get('fixture_only')is True or any(trial.rglob('cli-fake-upstream.jsonl'))}


def checkpoint_rows(behavior):
    point=behavior['checkpoint'];score=point['score'];assertions=point['assertions']
    known=sum(a['status']!='missing'for a in assertions.values())
    return [{'id':'F35.LONG02.output-format-v1','meaning':'Preserve the source geometry, array shape/type/range and fully binary pattern constraints in the final submitted artifacts',
        'applicability':'all','raw':None if score is None else score/100,
        'raw_formula':'AND of 13 source-bound output artifact assertions; excludes DRC and optical FDTD',
        'score':score,'score_formula':'100 * binary checkpoint outcome','unit':'binary checkpoint',
        'status':point['status'],'mapping_version':VERSION,'weights':{'common_product':0,'plugin_memory':0},
        'weight_reason':'Supplemental source-specific breakdown; the shared primary checkpoint is weighted once',
        'support_s':int(score==100),'support_f':int(score==0),'support_u':int(score is None),'support_n':1,
        'evidence_coverage':known/len(assertions),'collection_complete':point['collection_complete'],'assertions':assertions}]
