"""A scoped tool-only endpoint. Task gold and simulator protocol stay host-only."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class DomainBackend:
    def __init__(self,environment,journal,metadata=None):
        self.environment,self.journal=environment,journal
        self.token=secrets.token_hex(32)
        self.calls=[]
        self.metadata=metadata or {}
        self.lock=threading.RLock()
        owner=self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass

            def do_POST(self):
                if self.path!='/tool' or not hmac.compare_digest(
                    self.headers.get('Authorization',''),'Bearer '+owner.token):
                    self.send_error(403);return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=1_000_000:raise ValueError('size')
                    request=json.loads(self.rfile.read(size))
                    name,args=request['name'],request['arguments']
                    if name not in owner.environment.tool_handlers or not isinstance(args,dict):
                        raise ValueError('unknown tool or arguments')
                    with owner.lock:
                        before=copy.deepcopy(owner.environment.get_full_snapshot())
                        result=owner.environment.tool_handlers[name](args)
                        record={**owner.metadata,'call_id':request['call_id'],'name':name,'arguments':args,'result':result,
                                'timestamp':time.time(),'before':before,
                                'after':copy.deepcopy(owner.environment.get_full_snapshot())}
                        owner.calls.append(record)
                        for path in [owner.journal,owner.journal.with_suffix('.mirror.jsonl')]:
                            with path.open('a')as stream:
                                stream.write(json.dumps(record,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
                    data=json.dumps(result).encode()
                    self.send_response(200);self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                except (KeyError,ValueError,TypeError):self.send_error(400)
        self.server=ThreadingHTTPServer(('0.0.0.0',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)

    def start(self):
        self.journal.parent.mkdir(parents=True,exist_ok=True)
        self.journal.touch(exist_ok=False)
        self.journal.with_suffix('.mirror.jsonl').touch(exist_ok=False)
        self.journal.with_suffix('.start.json').write_text(json.dumps({**self.metadata,
            'before':self.environment.get_full_snapshot(),'timestamp':time.time()}))
        self.thread.start()
        return self.server.server_port

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        self.journal.with_suffix('.end.json').write_text(json.dumps({**self.metadata,
            'complete':True,'calls':len(self.calls),'sha256':hashlib.sha256(self.journal.read_bytes()).hexdigest(),
            'after':self.environment.get_full_snapshot(),'timestamp':time.time()}))
