"""Whole-episode request-boundary contracts, including every actual stage once."""
from __future__ import annotations

from .contract_metrics import provider_projection_integrity, state_freshness


def delivery_metrics(records, actor_request_ids, *, enabled,confirmed_receipts=None,request_payloads=None):
    ready={}
    for row in records:
        if row.get('event')!='request_ready' or row.get('request_id')not in actor_request_ids:
            continue
        identity=row['request_id']
        if identity in ready and ready[identity]!=row:
            raise ValueError('conflicting request-ready copies')
        ready[identity]=row
    # A missing boundary is an explicit unknown opportunity, never removed.
    requests=[ready.get(i,{'request_id':i})for i in sorted(actor_request_ids)]
    n=len(requests)
    from .contract_evidence import causal_state_minimum, request_receipt_floor
    floor=causal_state_minimum(requests,confirmed_receipts,enabled=enabled)if request_payloads is None else \
        request_receipt_floor(requests,request_payloads,confirmed_receipts,enabled=enabled)
    template_known=all(type(r.get('unresolved_template'))is bool for r in requests)
    state_known=all(isinstance(r.get('state_blocks'),list)for r in requests)
    return {'request_ids':sorted(actor_request_ids),'ready_request_ids':sorted(ready),
        'complete':set(ready)==set(actor_request_ids),
        'state_latest_at_prepare':state_freshness([],requests,enabled=enabled),
        'state_confirmed_receipt_lower_bound':floor,
        'provider_delivery_integrity':provider_projection_integrity(requests),
        'engineering':{'http_attempts':n,'request_ready':len(ready),
            'request_ready_coverage':len(ready)/n if n else None,
            'state_delivered_requests':sum(bool(r['state_blocks'])for r in requests)if state_known else None,
            'unresolved_template_requests':sum(r['unresolved_template']for r in requests)if template_known else None},
        'scope':'all actual actor HTTP requests across all stages, request_id deduplicated; '
            'provider delivery is not an independent window-selection oracle or model adoption'}
