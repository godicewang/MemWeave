"""Trusted evaluation-only HTTP transport. Never installed or mounted in Actor.

The service owns the provider credential, atomic quota and independent audit.
Actor capabilities grant only bounded requests for one registered run/arm.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import http.client
import json
import re
import signal
import ssl
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .budget_guard import change
from .storage import atomic_json


def _encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def _content_type(value):
    kind=value.split(';',1)[0].strip().lower()
    return kind if kind in {'application/json','text/event-stream'}else'application/octet-stream'


def _summary(payload,body):
    messages=payload.get('messages',[]);states=[]
    for m in messages:
        content=m.get('content')
        text=content if isinstance(content,str)else'\n'.join(p.get('text','')for p in content if isinstance(p,dict)and p.get('type')=='text')if isinstance(content,list)else''
        if text.startswith('# Symbolic State'):
            task=re.search(r'task_id: (\S+)',text);version=re.search(r'state_version: (\d+)',text)
            states.append({'sha256':hashlib.sha256(text.encode()).hexdigest(),'task_id':task.group(1)if task else None,'version':int(version.group(1))if version else None})
    return {'payload_sha256':hashlib.sha256(body).hexdigest(),'payload_bytes':len(body),'model':payload.get('model'),
        'max_output':payload.get('max_tokens',payload.get('max_completion_tokens')),'message_count':len(messages),
        'tool_names':[t.get('function',{}).get('name')for t in payload.get('tools',[])if isinstance(t,dict)],'state_blocks':states}


class Authority:
    def __init__(self,root,credential,capabilities,*,upstream=None,require_vm=False,unknown_limit=2):
        self.root=Path(root);self.ledger=self.root/'quota.json';self.secret=credential;self.capabilities=capabilities
        self.lock=threading.RLock();self.stopping=threading.Event();self.active=0;self.sequence=0;self.head='0'*64
        self.admitted={};self.http=set();self.ended=set();self.closed=False;self.uncertain=set();self.unknown_limit=unknown_limit
        self.local=threading.local()
        self.lease=(self.root/'authority.lock').open('a');fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if require_vm and sys.platform!='linux':raise ValueError('authority must run in trusted Linux container')
        if not isinstance(credential,str)or not credential:raise ValueError('credential required')
        if (self.root/'transport-audit.jsonl').exists():raise ValueError('new authority audit required; do not silently restart a completed attempt')
        self.upstream=upstream or self._real_upstream

    def log(self,event):
        with self.lock:
            self.sequence+=1;value={'sequence':self.sequence,'previous_hash':self.head,'timestamp':time.time(),**event}
            self.head=hashlib.sha256(_encoded(value)).hexdigest();value['event_hash']=self.head
            with(self.root/'transport-audit.jsonl').open('ab')as f:f.write(_encoded(value)+b'\n');f.flush();__import__('os').fsync(f.fileno())

    def principal(self,header):
        token=header.removeprefix('Bearer ')if isinstance(header,str)and header.startswith('Bearer ')else''
        found=next((v for k,v in self.capabilities.items()if hmac.compare_digest(k,token)),None)
        if found is None:return None
        phase=self.root/'phase.json'
        policy=json.loads(phase.read_text())if phase.is_file()else{}
        if policy and policy.get('episode')!=found['episode']:return None
        return {**found,**({'episode_budget':policy['episode_budget']}if 'episode_budget'in policy else{})}

    def _real_upstream(self,method,path,body,headers):
        identity=getattr(self.local,'request_id',None)if method=='POST'else None
        stage='tls_connect';connection=None
        def diagnostic(event,**fields):
            if identity:self.log({'event':event,'request_id':identity,'stage':stage,**fields})
        try:
            for attempt in range(1,4):
                remaining=json.loads(self.ledger.read_text())['deadline']-time.time()
                if remaining<=0 or self.stopping.is_set()or(self.root/'STOP_REQUESTED').exists():raise TimeoutError('authority deadline or stop')
                connection=http.client.HTTPSConnection('api.deepseek.com',timeout=min(10,remaining))
                try:connection.connect();break
                except (ssl.SSLEOFError,ConnectionResetError,TimeoutError)as error:
                    connection.close();diagnostic('tls_handshake_error',attempt=attempt,error_class=type(error).__name__,http_content_sent=False)
                    if attempt==3 or self.stopping.wait(.25*attempt):raise
            remaining=json.loads(self.ledger.read_text())['deadline']-time.time()
            if remaining<=0 or self.stopping.is_set()or(self.root/'STOP_REQUESTED').exists():raise TimeoutError('authority deadline or stop')
            connection.sock.settimeout(remaining)
            stage='request_send';connection.request(method,path,body,headers)
            stage='response_headers';response=connection.getresponse()
        except (OSError,TimeoutError)as error:
            diagnostic('upstream_stage_error',error_class=type(error).__name__)
            if connection:connection.close()
            raise
        def chunks():
            try:
                while not self.stopping.is_set():
                    data=response.read1(65536)
                    if not data:break
                    yield data
            except (OSError,TimeoutError)as error:
                if identity:self.log({'event':'upstream_stage_error','request_id':identity,'stage':'stream_read','error_class':type(error).__name__})
                raise
            finally:response.close();connection.close()
        return response.status,response.getheader('Content-Type','application/octet-stream'),chunks()

    def receipt(self,identity,principal):
        record=json.loads(self.ledger.read_text())['requests'].get(identity)
        if not record or record.get('arm')!=principal['arm']or record.get('episode')!=principal['episode']:return None
        return {k:record.get(k)for k in ('status','charge_usd','input','output','cache_input','max_output')}

    def begin(self,principal,identity,payload,body):
        output=payload.get('max_tokens',payload.get('max_completion_tokens'))
        if payload.get('model')!='deepseek-flash'or payload.get('stream')is not True or type(output)is not int or not 0<output<=384000:
            raise ValueError('registered streamed model and bounded output required')
        if not isinstance(payload.get('messages'),list):raise TypeError('messages required')
        if self.stopping.is_set():raise TimeoutError('stopped')
        if len(self.uncertain)>=self.unknown_limit:
            (self.root/'STOP_REQUESTED').touch();raise TimeoutError('unknown-charge risk threshold reached')
        if not isinstance(identity,str)or not identity or len(identity)>200:raise ValueError('invalid request identity')
        try:
            reservation=change(self.ledger,{'action':'reserve','id':identity,'arm':principal['arm'],'episode':principal['episode'],
                'max_output':output,'max_requests':principal.get('request_limit'),'episode_budget':principal.get('episode_budget')})
        except ValueError as error:raise TimeoutError('quota admission rejected')from error
        with self.lock:self.admitted[identity]=dict(principal);self.active+=1
        self.log({'event':'budget_reserved','request_id':identity,'arm':principal['arm'],'episode':principal['episode'],'charge_usd':reservation['charge_usd']})
        self.log({'event':'request_ready','request_id':identity,'arm':principal['arm'],'episode':principal['episode'],**_summary(payload,body)})
        return reservation

    def stream(self,identity,principal,body):
        self.log({'event':'http_attempt','request_id':identity,'arm':principal['arm'],'episode':principal['episode']})
        with self.lock:self.http.add(identity)
        self.local.request_id=identity
        return self.upstream('POST','/chat/completions',body,{'Authorization':'Bearer '+self.secret,'Content-Type':'application/json','Accept-Encoding':'identity'})

    def finish(self,identity,usage,done,model=None):
        settled=False
        if done and isinstance(usage,dict):
            try:
                record=change(self.ledger,{'action':'settle','id':identity,'input':usage['input'],'output':usage['output'],
                    'cache_input':usage.get('cache_hit')if usage.get('cache_hit')is not None else 0})
                settled=True;self.log({'event':'budget_settled','request_id':identity,'charge_usd':record['charge_usd']})
            except (KeyError,ValueError,OSError,TimeoutError):self.log({'event':'settlement_rejected','request_id':identity})
        self.log({'event':'request_end','request_id':identity,'usage':usage,'stream_done':done,'settled':settled,'response_model':model})
        with self.lock:
            self.ended.add(identity);self.active-=1
            if not settled:
                self.uncertain.add(identity)
                if len(self.uncertain)>=self.unknown_limit:(self.root/'STOP_REQUESTED').touch()

    def finalize(self):
        with self.lock:
            if self.closed:return
            if self.active:raise ValueError('cannot certify terminal while upstream requests remain active')
            self.log({'event':'authority_terminal'});requests=json.loads(self.ledger.read_text())['requests'];entries=[]
            groups={(v['arm'],v['episode'])for v in self.capabilities.values()}
            for arm,episode in sorted(groups):
                admitted={i for i,r in requests.items()if r.get('arm')==arm and r.get('episode')==episode}
                entries.append({'arm':arm,'episode':episode,'admitted_request_ids':sorted(admitted),
                    'http_request_ids':sorted(admitted&self.http),'terminal_request_ids':sorted(admitted&self.ended)})
            atomic_json(self.root/'transport-terminal.json',{'schema_version':'trusted-transport-terminal.v1','finalized':True,
                'audit_events':self.sequence,'audit_head':self.head,'entries':entries},immutable=True)
            atomic_json(self.root/'quota.final.json',json.loads(self.ledger.read_text()),immutable=True)
            self.closed=True;fcntl.flock(self.lease,fcntl.LOCK_UN);self.lease.close()


def server_for(authority,host,port):
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def respond(self,status,value,identity=None,reservation=None):
            data=_encoded(value);self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            if identity:self.send_header('X-Memweave-Request-Id',identity);self.send_header('X-Memweave-Reserved-Usd',str(reservation['charge_usd']))
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            p=authority.principal(self.headers.get('Authorization'))
            if p is None:return self.respond(401,{'error':'capability_rejected'})
            if self.path.startswith('/v1/receipts/'):
                r=authority.receipt(unquote(self.path[len('/v1/receipts/'):]),p)
                return self.respond(200 if r else 404,r or {'error':'receipt_missing'})
            if self.path not in ('/models','/v1/models'):return self.respond(403,{'error':'endpoint_rejected'})
            if authority.stopping.is_set()or(authority.root/'STOP_REQUESTED').exists():return self.respond(429,{'error':'stopped'})
            try:
                status,kind,chunks=authority.upstream('GET','/models',None,{'Authorization':'Bearer '+authority.secret,'Accept-Encoding':'identity'})
                data=b''.join(chunks)
                if len(data)>2_000_000:raise ValueError('metadata size')
                data=data.replace(authority.secret.encode(),b'[redacted]');self.send_response(status);self.send_header('Content-Type',_content_type(kind));self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                try:
                    metadata=json.loads(data);matches=[m for m in metadata.get('data',[])if isinstance(m,dict)and m.get('id')=='deepseek-flash']
                    authority.log({'event':'model_metadata','arm':p['arm'],'episode':p['episode'],
                        'models':[{k:m.get(k)for k in ('id','name','context_window','max_output_tokens')}for m in matches]})
                except (ValueError,AttributeError):pass
            except (OSError,ValueError,TimeoutError):self.respond(502,{'error':'metadata_transport'})
        def do_POST(self):
            p=authority.principal(self.headers.get('Authorization'))
            if p is None:return self.respond(401,{'error':'capability_rejected'})
            if self.path not in ('/chat/completions','/v1/chat/completions'):return self.respond(403,{'error':'endpoint_rejected'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=64_000_000:raise ValueError('body size')
                body=self.rfile.read(length);payload=json.loads(body)
                if not isinstance(payload,dict):raise TypeError('payload')
                supplied=self.headers.get('X-Memweave-Request-Id');identity=supplied or p['episode']+':'+p['arm']+':'+str(uuid.uuid4())
                if not identity.startswith(p['episode']+':'+p['arm']+':')and supplied:raise ValueError('request scope')
                reservation=authority.begin(p,identity,payload,body)
            except (ValueError,TypeError):return self.respond(400,{'error':'request_or_admission_rejected'})
            except (OSError,TimeoutError):return self.respond(429,{'error':'quota_or_deadline'})
            usage=None;done=False;pending=b'';secret_pending=b'';sent=False;client_open=True;response_model=None
            def send(data):
                nonlocal client_open
                if not data or not client_open:return
                try:self.wfile.write(f'{len(data):X}\r\n'.encode()+data+b'\r\n');self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):client_open=False
            def redact(data,final=False):
                nonlocal secret_pending
                secret_pending+=data;key=authority.secret.encode();keep=0 if final else len(key)-1
                if len(secret_pending)<=keep:return b''
                # Preserve a possible split credential at each chunk boundary.
                cutoff=len(secret_pending)-keep;prefix=secret_pending[:cutoff];tail=secret_pending[cutoff:]
                while prefix and any((prefix+tail).find(key,start)>=0 and (prefix+tail).find(key,start)<len(prefix)<(prefix+tail).find(key,start)+len(key)for start in [max(0,len(prefix)-len(key)+1)]):
                    cutoff-=1;prefix=secret_pending[:cutoff];tail=secret_pending[cutoff:]
                secret_pending=tail;return prefix.replace(key,b'[redacted]')
            try:
                status,kind,chunks=authority.stream(identity,p,body);authority.log({'event':'http_response','request_id':identity,'status':status})
                self.send_response(status);self.send_header('Content-Type',_content_type(kind));self.send_header('Transfer-Encoding','chunked');self.send_header('X-Memweave-Request-Id',identity);self.send_header('X-Memweave-Reserved-Usd',str(reservation['charge_usd']));self.end_headers();sent=True
                for chunk in chunks:
                    pending+=chunk
                    while b'\n'in pending:
                        line,pending=pending.split(b'\n',1)
                        if line.startswith(b'data:'):
                            value=line[5:].strip()
                            if value==b'[DONE]':done=True
                            else:
                                try:
                                    item=json.loads(value);u=item.get('usage')
                                    if isinstance(item.get('model'),str):response_model=item['model'].replace(authority.secret,'[redacted]')
                                    if isinstance(u,dict)and type(u.get('prompt_tokens'))is int and type(u.get('completion_tokens'))is int:
                                        usage={'input':u['prompt_tokens'],'output':u['completion_tokens'],'cache_hit':u.get('prompt_cache_hit_tokens')}
                                except (ValueError,AttributeError):pass
                    # Settle before forwarding DONE, so the client's receipt is ready.
                    if done:
                        authority.finish(identity,usage,True,response_model);send(redact(chunk));send(redact(b'',True));break
                    send(redact(chunk))
                    if authority.stopping.is_set():break
                if not done:authority.finish(identity,usage,False,response_model)
                if client_open:
                    send(redact(b'',True));self.wfile.write(b'0\r\n\r\n');self.wfile.flush()
            except (OSError,TimeoutError,ValueError,KeyError)as error:
                authority.log({'event':'http_error','request_id':identity,'error_class':type(error).__name__})
                if identity not in authority.ended:authority.finish(identity,usage,False,response_model)
                if not sent:self.respond(502,{'error':'upstream_transport'},identity,reservation)
                self.close_connection=True
    return ThreadingHTTPServer((host,port),Handler)


def main():
    config=json.loads(sys.stdin.readline());root=Path(config['control']);fixture=config.get('fixture')is True
    authority=Authority(root,config['api_key'],config['capabilities'],require_vm=True,unknown_limit=16 if fixture else 2)
    watchdog=subprocess.Popen([sys.executable,str(Path(__file__).with_name('container_deadline.py')),
        str(__import__('os').getpid()),str(json.loads(authority.ledger.read_text())['deadline']+3),str(root/'authority-hard-stop.jsonl')],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    if fixture:
        counts={}
        def upstream(method,path,body,headers):
            if headers.get('Authorization')!='Bearer '+authority.secret:raise ValueError('fixture authorization')
            if method=='GET':return 200,'application/json',[_encoded({'data':[{'id':'deepseek-flash','name':'DeepSeek V4.1 Flash','context_window':1048576,'max_output_tokens':384000}]})]
            payload=json.loads(body);identity=threading.get_ident();counts[identity]=counts.get(identity,0)+1
            if any('HANG-TRANSPORT-FIXTURE'in str(m.get('content',''))for m in payload['messages']):
                def hang():
                    while not authority.stopping.wait(.1):pass
                    return
                    yield b''
                return 200,'text/event-stream',hang()
            # A task-create is requested only when that tool is available and not yet used.
            called={t.get('function',{}).get('name')for m in payload['messages']for t in m.get('tool_calls',[])}
            if any('Derived evaluation protocol TB01-capsule.v1'in str(m.get('content',''))for m in payload['messages']):
                from .tb01_capsules import GOLD, NOTE
                values=[dict(v)for v in GOLD.values()]
                if any('TB01CAPSULE_NEGATIVE'in str(m.get('content',''))for m in payload['messages']):values[0]['by']='id'
                has_state=any(t.get('function',{}).get('name')=='state_append'for t in payload.get('tools',[]))
                reads=sum(t.get('function',{}).get('name')==('state_read'if has_state else'read')for m in payload['messages']for t in m.get('tool_calls',[]))
                tool=None;arguments={}
                if has_state and 'task_create'not in called:
                    tool='task_create';arguments={'title':'capsule probe','goal':'Implement original parity task with saved constraints','project_name':'TB01','summary':'offline capsule control','keywords':['capsule']}
                elif ('state_append'if has_state else'write')not in called:
                    tool='state_append'if has_state else'write'
                    arguments={'items':[{'type':'fact','content':json.dumps(v,separators=(',',':')),'evidence':{'U1':'original requirements'}}for v in values]}if has_state else{'path':NOTE,'content':'\n'.join(json.dumps(v,separators=(',',':'))for v in values)+'\n'}
                elif reads==0 or 'bash'in called and reads==1:
                    tool='state_read'if has_state else'read'
                    if has_state:
                        import re
                        candidates=[re.search(r'"task_id"\s*:\s*"([^"]+)"',str(m.get('content','')))for m in payload['messages']if m.get('role')=='tool']
                        task=next((m[1]for m in candidates if m),None)
                        if task is None:raise ValueError('fixture task binding missing')
                        arguments={'task_id':task}
                    else:arguments={'path':NOTE}
                elif 'bash'not in called:
                    tool='bash';arguments={'command':"for p in evaluate scheduler scoring generation byte_stops; do printf '\\n# offline capsule fixture edit\\n' >> /app/evalbench/$p.py; done"}
                delta={'role':'assistant','tool_calls':[{'index':0,'id':'capsule-'+str(len(payload['messages'])),'type':'function','function':{'name':tool,'arguments':json.dumps(arguments)}}]}if tool else{'role':'assistant','content':'Offline capsule control complete.'}
                frames=[{'model':'deepseek-flash','choices':[{'index':0,'delta':delta,'finish_reason':None}]},{'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'if tool else'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':2,'prompt_cache_hit_tokens':0}}]
                return 200,'text/event-stream',[b''.join(b'data: '+_encoded(f)+b'\n\n'for f in frames)+b'data: [DONE]\n\n']
            create=any(t.get('function',{}).get('name')=='task_create'for t in payload.get('tools',[]))and 'task_create'not in called
            read=not create and 'read'not in called
            tool='task_create'if create else'read'if read else None
            arguments={'title':'broker probe','goal':'Verify isolated transport','project_name':'probe','summary':'offline broker verification','keywords':['probe']}if create else{'path':'/app/evalbench/evaluate.py'}
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'broker-'+tool,'type':'function','function':{'name':tool,'arguments':json.dumps(arguments)}}]}if tool else{'role':'assistant','content':'OK'}
            frames=[{'model':'deepseek-flash','choices':[{'index':0,'delta':delta,'finish_reason':None}]},{'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'if tool else'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':2,'prompt_cache_hit_tokens':0}}]
            return 200,'text/event-stream',[b''.join(b'data: '+_encoded(f)+b'\n\n'for f in frames)+b'data: [DONE]\n\n']
        authority.upstream=upstream
    server=server_for(authority,'0.0.0.0',0)
    atomic_json(root/'broker-ready.json',{'port':server.server_address[1],'pid':__import__('os').getpid(),'fixture':fixture},immutable=True)
    def stop(*args):
        authority.stopping.set();(root/'STOP_REQUESTED').touch();threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def deadline():
        limit=json.loads(authority.ledger.read_text())['deadline']
        if not authority.stopping.wait(max(0,limit-time.time())):stop()
    threading.Thread(target=deadline,daemon=True).start()
    try:server.serve_forever(poll_interval=.1)
    finally:
        authority.stopping.set();server.server_close();authority.finalize()
        if watchdog.poll()is None:watchdog.terminate();watchdog.wait(timeout=5)


if __name__=='__main__':main()
