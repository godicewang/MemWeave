import http.client
import json
import ssl
import threading
import time

from memweave_eval.primary_transport import Authority, server_for


def fixture(tmp_path):
    from memweave_eval.budget_guard import initialize
    ledger=tmp_path/'quota.json';initialize(ledger,3,time.time()+90,arm_limits={'pi-native':1.5,'pi-memweave':1.5})
    secret='fixture-secret-never-in-actor'
    calls=[]
    def upstream(method,path,body,headers):
        assert headers['Authorization']=='Bearer '+secret;calls.append((method,path,body))
        if method=='GET':return 200,'application/json',[b'{"data":[]}']
        return 200,'text/event-stream',[b'data: {"model":"deepseek-flash","choices":[{"delta":{"content":"OK"}}]}\n\n',b'data: {"usage":{"prompt_tokens":100,"completion_tokens":2,"prompt_cache_hit_tokens":0}}\n\ndata: [DONE]\n\n']
    a=Authority(tmp_path,secret,{'cap-native':{'arm':'pi-native','episode':'run'},'cap-plugin':{'arm':'pi-memweave','episode':'run'}},upstream=upstream)
    s=server_for(a,'127.0.0.1',0);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
    return a,s,t,calls,secret


def request(server,path,body=None,cap='cap-native',method='POST'):
    c=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
    c.request(method,path,json.dumps(body).encode()if body is not None else None,headers={'Authorization':'Bearer '+cap,'Content-Type':'application/json'})
    response=c.getresponse();status=response.status;headers=dict(response.getheaders());raw=response.read();c.close();return status,headers,raw


def test_broker_alone_authorizes_and_settles_without_returning_the_provider_secret(tmp_path):
    a,s,t,calls,key=fixture(tmp_path)
    try:
        status,headers,raw=request(s,'/v1/chat/completions',{'model':'deepseek-flash','stream':True,'max_tokens':128,'messages':[]})
        assert status==200 and b'[DONE]'in raw and key.encode()not in raw
        identity=headers['X-Memweave-Request-Id'];receipt=request(s,'/v1/receipts/'+identity,method='GET')
        assert receipt[0]==200 and json.loads(receipt[2])['status']=='settled'and key.encode()not in receipt[2]
        assert len(calls)==1
    finally:s.shutdown();s.server_close();t.join(5);a.finalize()
    ledger=json.loads((tmp_path/'quota.json').read_text());assert len(ledger['requests'])==1
    terminal=json.loads((tmp_path/'transport-terminal.json').read_text());assert terminal['finalized']and len(next(e for e in terminal['entries']if e['arm']=='pi-native')['http_request_ids'])==1


def test_invalid_capability_or_unregistered_endpoint_model_dispatches_nothing(tmp_path):
    a,s,t,calls,key=fixture(tmp_path)
    try:
        for path,body,cap in [('/v1/chat/completions',{'model':'deepseek-flash','stream':True,'max_tokens':128},'bad'),('/debug/secret',{},'cap-native'),('/v1/chat/completions',{'model':'other','stream':True,'max_tokens':128},'cap-native')]:
            status,_,raw=request(s,path,body,cap);assert status in(401,403,400)and key.encode()not in raw
        assert not calls and not json.loads((tmp_path/'quota.json').read_text())['requests']
    finally:s.shutdown();s.server_close();t.join(5);a.finalize()


def test_stopped_broker_cannot_dispatch_even_when_actor_has_its_own_capability(tmp_path):
    a,s,t,calls,_key=fixture(tmp_path);(tmp_path/'STOP_REQUESTED').touch()
    try:
        assert request(s,'/v1/chat/completions',{'model':'deepseek-flash','stream':True,'max_tokens':128,'messages':[]})[0]==429
        assert not calls
    finally:s.shutdown();s.server_close();t.join(5);a.finalize()


def test_upstream_error_cannot_echo_key_even_across_chunks_or_headers(tmp_path):
    a,s,t,_calls,key=fixture(tmp_path)
    def upstream(*_args):
        data=('upstream debug '+key+' trailing').encode()
        at=data.index(key.encode())+7
        return 400,'text/plain; debug='+key,[data[:at],data[at:]]
    a.upstream=upstream
    try:
        status,headers,raw=request(s,'/v1/chat/completions',{'model':'deepseek-flash','stream':True,'max_tokens':128,'messages':[]})
        assert status==400 and key.encode()not in raw and key not in str(headers)
        assert b'[redacted]'in raw
        r=json.loads((tmp_path/'quota.json').read_text())['requests'];assert next(iter(r.values()))['status']=='reserved'
    finally:s.shutdown();s.server_close();t.join(5);a.finalize()


def test_two_terminal_unknowns_stop_new_dispatch_without_releasing_reservations(tmp_path):
    a,s,t,_calls,_key=fixture(tmp_path);calls=[]
    def upstream(*args):calls.append(args);return 200,'text/event-stream',[b'no usage and no done\n']
    a.upstream=upstream
    body={'model':'deepseek-flash','stream':True,'max_tokens':128,'messages':[]}
    try:
        assert request(s,'/v1/chat/completions',body)[0]==200
        assert request(s,'/v1/chat/completions',body)[0]==200
        assert request(s,'/v1/chat/completions',body)[0]==429 and len(calls)==2
        assert (tmp_path/'STOP_REQUESTED').is_file()
        assert all(r['status']=='reserved'for r in json.loads((tmp_path/'quota.json').read_text())['requests'].values())
    finally:s.shutdown();s.server_close();t.join(5);a.finalize()


def test_only_tls_handshake_is_retried_before_exactly_one_http_request(tmp_path,monkeypatch):
    a,s,t,_calls,_key=fixture(tmp_path);connections=[];sent=[]
    class Connection:
        def __init__(self,*args,**kwargs):connections.append(self);self.sock=self
        def connect(self):
            if len(connections)<3:raise ssl.SSLEOFError('fixture handshake only')
        def settimeout(self,_timeout):pass
        def request(self,*args):sent.append(args)
        def getresponse(self):return self
        def getheader(self,*_args):return 'text/event-stream'
        @property
        def status(self):return 200
        def read1(self,_size):return b''
        def close(self):pass
    monkeypatch.setattr(http.client,'HTTPSConnection',Connection);monkeypatch.setattr(a.stopping,'wait',lambda _seconds:False)
    try:
        a.local.request_id='fixture';status,_,chunks=a._real_upstream('POST','/chat/completions',b'{}',{})
        assert list(chunks)==[]and status==200 and len(connections)==3 and len(sent)==1
        events=[json.loads(x)for x in(tmp_path/'transport-audit.jsonl').read_text().splitlines()]
        assert [e['http_content_sent']for e in events if e['event']=='tls_handshake_error']==[False,False]
    finally:s.shutdown();s.server_close();t.join(5);a.finalize()


def test_error_after_http_send_is_never_automatically_retried(tmp_path,monkeypatch):
    import pytest

    a,s,t,_calls,_key=fixture(tmp_path);connections=[];sent=[]
    class Connection:
        def __init__(self,*args,**kwargs):connections.append(self);self.sock=self
        def connect(self):pass
        def settimeout(self,_timeout):pass
        def request(self,*args):sent.append(args)
        def getresponse(self):raise ssl.SSLEOFError('fixture after HTTP send')
        def close(self):pass
    monkeypatch.setattr(http.client,'HTTPSConnection',Connection)
    try:
        a.local.request_id='fixture'
        with pytest.raises(ssl.SSLEOFError):a._real_upstream('POST','/chat/completions',b'{}',{})
        assert len(connections)==len(sent)==1
        last=json.loads((tmp_path/'transport-audit.jsonl').read_text().splitlines()[-1]);assert last['stage']=='response_headers'
    finally:s.shutdown();s.server_close();t.join(5);a.finalize()


def test_stop_during_handshake_prevents_http_content_dispatch(tmp_path,monkeypatch):
    import pytest

    a,s,t,_calls,_key=fixture(tmp_path);sent=[]
    class Connection:
        def __init__(self,*args,**kwargs):pass
        def connect(self):(tmp_path/'STOP_REQUESTED').touch()
        def request(self,*args):sent.append(args)
        def close(self):pass
    monkeypatch.setattr(http.client,'HTTPSConnection',Connection)
    try:
        with pytest.raises(TimeoutError):a._real_upstream('POST','/chat/completions',b'{}',{})
        assert sent==[]
    finally:s.shutdown();s.server_close();t.join(5);a.finalize()
