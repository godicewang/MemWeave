"""Replay pinned protected integration outcomes; notes never prove code quality."""
from __future__ import annotations

import importlib.util
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .fixed35 import checkpoint_verdict
from .storage import file_digest

VERSION='fixed35-kubernetes-source-20261104-v1'


def grade_evidence(data):
    expected=data['expected_manifest'];manifest=data.get('manifest');metrics=data.get('metrics')
    if not isinstance(expected,list)or not expected:raise ValueError('frozen protected manifest required')
    threshold=sum(int(line.split()[1])for line in expected)
    if threshold<=0:raise ValueError('positive protected source threshold required')
    issues=[];counts={};parsed=data.get('parsed');metrics=metrics if isinstance(metrics,dict)else{}
    integer_keys=['passed','passed_raw_uncapped','failed','ignored','agent_unit_passed_uncounted','min_passed_for_reward']
    valid=all(type(metrics.get(k))is int and metrics[k]>=0 for k in integer_keys)
    valid &= metrics.get('scoring_mode')=='binary'and metrics.get('counted_suite')=='protected_integration_tests'
    if not valid:issues.append('invalid_or_missing_original_metrics')
    manifest_ok=isinstance(manifest,list)and Counter(manifest)==Counter(expected)
    if not manifest_ok:issues.append('protected_manifest_missing_or_changed')
    rewards=[data.get('reward'),data.get('reported_reward'),metrics.get('reward')]
    reward_known=all(type(v)in (int,float)and math.isfinite(v)and v in (0,1)for v in rewards)
    if not reward_known or len(set(rewards))!=1:issues.append('original_reward_missing_or_mismatch')
    reward=rewards[0]if reward_known and len(set(rewards))==1 else None
    phase=metrics.get('phase');build_failure=phase=='build_failed'and metrics.get('build_status')=='failed'
    complete=phase=='complete'and metrics.get('build_status')=='passed'
    if not (complete or build_failure):issues.append('original_verifier_not_completed')
    if valid and (metrics['min_passed_for_reward']!=threshold or metrics['passed']>threshold
            or metrics['passed_raw_uncapped']<metrics['passed']):issues.append('protected_threshold_or_cap_mismatch')
    if complete:
        if data.get('raw_log_present')is not True or data.get('terminal_summary')is not True:
            issues.append('raw_cargo_or_terminal_evidence_missing')
        mapping={'integration_passed':'passed','integration_passed_raw':'passed_raw_uncapped',
            'integration_failed':'failed','integration_ignored':'ignored',
            'unit_passed_uncounted':'agent_unit_passed_uncounted'}
        if not isinstance(parsed,dict)or type(parsed.get('structure_ok'))is not bool \
                or any(type(parsed.get(k))is not int or parsed[k]<0 or parsed[k]!=metrics.get(v)
                    for k,v in mapping.items()):issues.append('raw_parser_metrics_mismatch')
        structure=parsed.get('structure_ok')if isinstance(parsed,dict)else None
        acceptance=bool(structure and valid and metrics['failed']==0 and metrics['passed']>=threshold)
        if reward is not None and reward!=int(acceptance):issues.append('original_reward_contradiction')
    else:
        structure=None;acceptance=False
        if build_failure and (data.get('build_log_present')is not True or not valid or
                any(metrics.get(k)!=0 for k in integer_keys[:-1])or reward!=0):
            issues.append('build_failure_evidence_incomplete')
    denominator=max(metrics['passed']+metrics['failed'],threshold)if valid else None
    fraction=metrics['passed']/denominator if denominator else None
    partial=metrics.get('partial_score')
    if type(partial)not in (int,float)or not math.isfinite(partial)or fraction is None \
            or abs(partial-fraction)>1e-12:issues.append('original_partial_mismatch')
    consistent=not issues
    checks={'complete_original_evidence':True if consistent else None,
        'protected_source_build_available':not build_failure if complete or build_failure else None,
        'protected_integration_structure':structure if complete else False if build_failure else None,
        'all_protected_integration_tests_passed':acceptance if complete or build_failure else None}
    point=checkpoint_verdict({'id':'F35.SOURCE.LONG-04.original-protocol','required_assertions':list(checks)},checks)
    if valid:counts={'passed':metrics['passed'],'failed':metrics['failed'],'ignored':metrics['ignored'],
        'total':denominator,'required':threshold,'raw_uncapped_passed':metrics['passed_raw_uncapped'],
        'uncounted_agent_unit_passed':metrics['agent_unit_passed_uncounted']}
    return {'version':VERSION,'adapter_kind':'kubernetes-source-v1','case_id':'LONG-04',
        'native_metrics':{'passed':metrics['passed'],'total':denominator}if consistent else None,
        'original_reward':reward,'original_metrics':metrics,'source_counts':counts,
        'unexecuted_protected_tests':threshold if build_failure and consistent else None,
        'checkpoints':{},'whole_protocol':point,'collection_complete':consistent and point['collection_complete'],
        'evidence_issues':issues,'scope':'Pinned original protected integration multiset and per-binary caps; unit/doc tests excluded. Partial denominator max(passed+failed, protected threshold). No memory adoption claim.'}


def grade_trial(trial,contract,*,fixture_control=False):
    if contract.get('case_id')!='LONG-04'or contract.get('adapter_kind')!='kubernetes-source-v1' \
            or contract.get('parser_path')not in contract.get('source_hashes',{}):
        raise ValueError('pinned original Kubernetes parser identity required')
    for source,digest in contract['source_hashes'].items():
        if file_digest(Path(source))!=digest:raise ValueError('Kubernetes source gold changed')
    rp=trial/'result.json';original=json.loads(rp.read_text())if rp.is_file()else{}
    agent=original.get('config',{}).get('agent',{})
    fixture=bool(fixture_control or agent.get('name')in {'oracle','nop'}or
        agent.get('import_path')in {'memweave_eval.resource_control:ResourceOracle','memweave_eval.resource_control:ResourceNop'}or
        agent.get('kwargs',{}).get('prepare_only')is True)
    if fixture and not fixture_control:raise ValueError('source controls require fixture-control')
    verifier=trial/'verifier';files={}
    def read(name):
        path=verifier/name
        if path.is_symlink()or not path.resolve().is_relative_to(trial.resolve()):
            raise ValueError('redirected original Kubernetes artifact')
        if not path.is_file():return None
        files[str(path)]=file_digest(path);return path.read_text(errors='replace')
    text=read('metrics.json')
    try:metrics=json.loads(text)if text else None
    except ValueError:metrics=None
    reward_text=read('reward.txt')
    try:reward=float(reward_text)if reward_text is not None else None
    except ValueError:reward=None
    manifest=read('expected_integration_sections.txt');cargo=read('test_output.log')
    stdout=read('test-stdout.txt');build=read('build.log');parsed=None
    if cargo is not None and manifest is not None:
        path=Path(contract['parser_path']);spec=importlib.util.spec_from_file_location('fixed35_original_k8s_parser',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        counts,sections=module.parse(cargo.splitlines());names=[];caps=defaultdict(list)
        for line in manifest.splitlines():
            parts=line.split()
            if len(parts)!=2:raise ValueError('invalid protected source manifest')
            names.append(parts[0]);caps[parts[0]].append(int(parts[1]))
        parsed={'integration_passed':module.capped_passed(sections,caps),
            'integration_passed_raw':counts['integration']['passed'],
            'integration_failed':counts['integration']['failed'],
            'integration_ignored':counts['integration']['ignored'],
            'unit_passed_uncounted':counts['unit']['passed'],
            'structure_ok':not module.check_structure(counts,sections,names)}
    result=grade_evidence({'expected_manifest':contract['expected_manifest'],
        'manifest':manifest.splitlines()if manifest is not None else None,'metrics':metrics,
        'parsed':parsed,'reward':reward,'reported_reward':(original.get('verifier_result')or{}).get('rewards',{}).get('reward'),
        'raw_log_present':cargo is not None,'terminal_summary':'=== Summary (protected integration tests only) ==='in (stdout or''),
        'build_log_present':bool(build)})
    result.update(fixture_only=fixture,artifacts=dict(files,**{str(rp):file_digest(rp)}if rp.is_file()else{}))
    return result


def checkpoint_rows(result):
    point=result['whole_protocol']
    return [{'id':point['checkpoint_id'],'meaning':result['scope'],'applicability':'all',
        'raw':point['score']/100 if point['score']is not None else None,'score':point['score'],
        'status':point['status'],'raw_formula':'AND(original manifest, replayed protected cargo counts/structure, matching reward, completed source protocol)',
        'score_formula':'100 if every required assertion passes; known rejection0; missing original evidence explicit',
        'mapping_version':VERSION,'weights':{'common_product':0,'plugin_memory':0},
        'weight_reason':'Original source protocol supplement; no duplicate child weighting',
        'support_s':sum(a['status']=='pass'for a in point['assertions'].values()),
        'support_f':len(point['failed_assertions']),'support_u':len(point['missing_assertions']),
        'support_n':len(point['assertions']),'collection_complete':point['collection_complete']}]
