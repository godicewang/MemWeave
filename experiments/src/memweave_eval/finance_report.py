"""Versioned read-only financial supplement; never overwrites a frozen report."""
import csv
import io
import json
from pathlib import Path
from .finance_metrics import attach_finance,attach_pair_columns,context_from_lock,finance_summary,finance_markdown,FINANCE_COLUMNS
from .storage import atomic_json,contained,file_digest


def generate_finance_supplement(root:Path,output:Path):
    root,output=root.resolve(),output.resolve()
    if output.exists()or output==root or root in output.parents and not output.is_relative_to(root/'supplements'):
        raise ValueError('financial supplement requires a new independent output directory')
    source=root/'reports/results.json';lock_path=root/'experiment.lock.json'
    index_path=root/'evidence-index.json'
    index=json.loads(index_path.read_text())
    for item in index['files']:
        if file_digest(contained(root,item['path']))!=item['sha256']:
            raise ValueError('original evidence hash mismatch')
    delivery=root/'reports/delivery-index.json'
    if delivery.exists():
        expected=next((f['sha256']for f in json.loads(delivery.read_text())['files']if f['path']=='reports/results.json'),None)
        if expected!=file_digest(source):raise ValueError('original report hash mismatch')
    original=json.loads(source.read_text());lock=json.loads(lock_path.read_text())
    rows=original['trials']
    inputs={str(source):file_digest(source),str(lock_path):file_digest(lock_path)}
    for row in rows:
        paths=row.get('session_sources')or[]
        agent=contained(root,str(Path(paths[0]).parents[2]))if paths else None
        if agent and (agent/'request-trace.jsonl').is_file():
            inputs[str(agent/'request-trace.jsonl')]=file_digest(agent/'request-trace.jsonl')
        attach_finance(row,context_from_lock(lock),agent)
    summary=finance_summary(rows);attach_pair_columns(rows,summary)
    provenance={'version':'finance-20261101-v1','original_run':root.name,'inputs':inputs,
                'evaluator_files':{p.name:file_digest(p)for p in [Path(__file__),Path(__file__).with_name('finance_metrics.py')]},
                'raw_index_sha256':file_digest(index_path),'raw_files_verified':len(index['files']),
                'original_reports_modified':False,'scope':'valid formal pairs only; operational ledger costs remain separate'}
    atomic_json(output/'results.json',{'provenance':provenance,'summary':summary,'trials':rows},immutable=True)
    out=io.StringIO();fields=['task_id','variant_id','finance_estimated_usd',*FINANCE_COLUMNS]
    writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    (output/'trials.csv').write_text(out.getvalue())
    (output/'report.md').write_text('# 缓存与配对费用补充\n\n'+'\n'.join(finance_markdown(rows,summary))+'\n')
    if any(file_digest(Path(p))!=h for p,h in inputs.items()):raise ValueError('original financial evidence changed')
    return {'output':str(output),'summary':summary,'provenance':provenance}
