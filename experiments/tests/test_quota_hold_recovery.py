import json
import time
from unittest.mock import patch

import pytest

from memweave_eval.budget_guard import initialize
from memweave_eval.quota_service import apply_scoped


def test_pause_is_explicit_and_does_not_prevent_confirmed_settlement(tmp_path):
    ledger=tmp_path/'quota.json';initialize(ledger,19,time.time()+600)
    c={'token':'fixture','id_prefix':'episode:arm:','arm':'fixture','episode':'episode','deadline':time.time()+600,'max_output':128,'episode_budget':1.}
    reserve={'token':'fixture','operation':{'action':'reserve','id':'episode:arm:one','arm':'fixture','episode':'episode','max_output':128}}
    apply_scoped(ledger,c,reserve)
    with pytest.raises(ValueError,match='authority_admission_paused'):
        apply_scoped(ledger,c,dict(reserve,operation=dict(reserve['operation'],id='episode:arm:two')),admission_paused=True)
    result=apply_scoped(ledger,c,{'token':'fixture','operation':{'action':'settle','id':'episode:arm:one','input':10,'output':5,'cache_input':0}},admission_paused=True)
    assert result['status']=='settled'and len(json.loads(ledger.read_text())['requests'])==1


def test_recovery_record_is_bound_to_unchanged_old_identity(tmp_path):
    from memweave_eval.quota_authority import active_authority
    from memweave_eval.storage import atomic_json, file_digest
    original={'service_id':'original','container_id':'old','root':str(tmp_path),'ledger':'/private/quota.json','budget_id':'budget','image_id':'image','subbudgets_usd':{'cap':19}}
    atomic_json(tmp_path/'authority.json',original,immutable=True)
    assert active_authority(tmp_path)==original
    proof={'base_authority_sha256':file_digest(tmp_path/'authority.json'),'authority':dict(original,container_id='new')}
    atomic_json(tmp_path/'authority-recovery.json',proof,immutable=True)
    assert active_authority(tmp_path)['container_id']=='new'
    for changed in [{'service_id':'other'},{'ledger':'other'},{'subbudgets_usd':{'cap':30}}]:
        (tmp_path/'authority-recovery.json').write_text(json.dumps(dict(proof,authority=dict(proof['authority'],**changed))))
        with pytest.raises(ValueError,match='recovery identity'):active_authority(tmp_path)
    (tmp_path/'authority-recovery.json').write_text(json.dumps(dict(proof,base_authority_sha256='0'*64)))
    with pytest.raises(ValueError,match='base manifest'):active_authority(tmp_path)


def test_live_or_uncertain_writer_prevents_recovery(tmp_path):
    from memweave_eval.quota_authority import recover_authority
    from memweave_eval.storage import atomic_json
    original={'service_id':'original','container_id':'old','root':str(tmp_path),'ledger':'/private/quota.json','budget_id':'budget','image_id':'image'}
    atomic_json(tmp_path/'authority.json',original,immutable=True)
    for code,text in [(0,'old\n'),(1,'')]:
        from types import SimpleNamespace
        with patch('memweave_eval.quota_authority.subprocess.run',return_value=SimpleNamespace(returncode=code,stdout=text,stderr='')),pytest.raises(RuntimeError,match='writer absence'):
            recover_authority(tmp_path,{})
    assert not(tmp_path/'authority-recovery.json').exists()


def test_transient_config_disappearance_never_admits_or_silently_defaults(tmp_path):
    from pathlib import Path

    from memweave_eval.quota_service import serve, write_json
    for name in ['ledger','configs','channels']:(tmp_path/name).mkdir()
    initialize(tmp_path/'ledger/quota.json',19,time.time()+60)
    source=tmp_path/'configs'/('a'*32+'.json');source.write_text('{}')
    original=Path.read_text
    def read(path,*args,**kwargs):
        if path==source:source.unlink()
        return original(path,*args,**kwargs)
    def write(path,value):
        write_json(path,value)
        if path.name=='configuration-read-fault.json':(tmp_path/'stop').touch()
    with patch.object(Path,'read_text',read),patch('memweave_eval.quota_service.write_json',write):serve(tmp_path,'fixture')
    assert json.loads((tmp_path/'configuration-read-fault.json').read_text())['reason']=='private_config_temporarily_missing'
    assert json.loads((tmp_path/'ledger/quota.json').read_text())['requests']=={}
    assert json.loads((tmp_path/'service-exit.json').read_text())['reason']=='requested_stop'
