from memweave_eval.primary_reconciliation import reconcile


def fixture():
    events=[{'event':e,'request_id':r}for r in ('one','two')for e in ('budget_reserved','request_ready','http_attempt','request_end')]
    ledger={'requests':{r:{'arm':'pi-native','episode':'run','status':'settled'}for r in ('one','two')}}
    terminal={'schema_version':'trusted-transport-terminal.v1','finalized':True,'entries':[{'arm':'pi-native','episode':'run','admitted_request_ids':['one','two'],'http_request_ids':['one','two'],'terminal_request_ids':['one','two']}]}
    return events,ledger,terminal


def test_full_trailing_request_deletion_is_detected_even_with_valid_json_and_hash():
    events,ledger,end=fixture()
    assert reconcile(events,ledger,end,arm='pi-native',episode='run')['status']=='observed'
    r=reconcile(events[:4],ledger,end,arm='pi-native',episode='run')
    assert r['status']=='invalid_missing'and r['missing_admitted_ids']==['two']and r['missing_http_ids']==['two']


def test_missing_terminal_wrong_arm_and_duplicate_events_never_pass():
    e,l,t=fixture();assert reconcile(e,l,None,arm='pi-native',episode='run')['status']=='missing'
    assert reconcile(e,l,t|{'finalized':False},arm='pi-native',episode='run')['status']=='missing'
    assert reconcile(e,l,t,arm='pi-memweave',episode='run')['status']=='missing'
    assert reconcile(e+[e[-1]],l,t,arm='pi-native',episode='run')['status']=='invalid'


def test_request_omitted_from_trusted_terminal_cannot_be_silently_excluded():
    e,l,t=fixture();t['entries'][0]['admitted_request_ids']=['one']
    assert reconcile(e,l,t,arm='pi-native',episode='run')['status']=='invalid'
    e,l,t=fixture();l['requests']['other']={'arm':'other','episode':'run','status':'reserved'}
    assert reconcile(e,l,t,arm='pi-native',episode='run')['status']=='observed'


def test_trusted_audit_complete_line_tail_deletion_fails_terminal_count_and_head():
    import hashlib
    import json

    from memweave_eval.primary_reconciliation import verify_audit
    events=[];previous='0'*64
    for n in range(1,4):
        e={'sequence':n,'previous_hash':previous,'event':'fixture'}
        previous=hashlib.sha256(json.dumps(e,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();events.append(e|{'event_hash':previous})
    terminal={'finalized':True,'audit_events':3,'audit_head':previous}
    assert verify_audit(events,terminal)['status']=='observed'
    assert verify_audit(events[:-1],terminal)['status']=='invalid_missing'
