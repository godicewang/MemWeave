"""Task-scoped shared-file IPC; evaluator data never enters the actor mount."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import secrets
import threading
import time


class DomainBackend:
    def __init__(self, environment, journal, exchange, metadata=None):
        self.environment, self.journal, self.exchange = environment, journal, exchange
        self.token = secrets.token_hex(32)
        self.metadata, self.calls = metadata or {}, []
        self.fatal_error=None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve_checked, daemon=True)

    def _serve_checked(self):
        try:self._serve()
        except Exception as error:  # noqa: BLE001 -- persist a fatal boundary status, never success.
            self.fatal_error=type(error).__name__
            self.stop.set()

    def _record(self, request):
        before = copy.deepcopy(self.environment.get_full_snapshot())
        name, args = request.get('name'), request.get('arguments')
        if not hmac.compare_digest(str(request.get('token', '')), self.token):
            return {'bridge_error': 'unauthorized'}
        if name not in self.environment.tool_handlers or not isinstance(args, dict):
            return {'bridge_error': 'unknown tool or invalid arguments'}
        try:
            result = self.environment.tool_handlers[name](args)
        except Exception as error:  # noqa: BLE001 -- external domain tool; preserve error type only.
            result = {'error': type(error).__name__}
        record = {**self.metadata, 'call_id': request.get('call_id'), 'name': name,
                  'arguments': args, 'result': result, 'timestamp': time.time(),
                  'before': before, 'after': copy.deepcopy(self.environment.get_full_snapshot())}
        self.calls.append(record)
        for target in [self.journal, self.journal.with_suffix('.mirror.jsonl')]:
            with target.open('a') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        return {'result': result}

    def _serve(self):
        completed = set()
        while not self.stop.is_set():
            for source in sorted((self.exchange / 'requests').glob('*.json')):
                if source.name in completed or source.is_symlink():
                    continue
                request = json.loads(source.read_text())
                expected = hashlib.sha256(str(request.get('call_id')).encode()).hexdigest()+'.json'
                if source.name != expected:
                    raise ValueError('IPC identity does not match tool call')
                response = self._record(request)
                target = self.exchange / 'responses' / source.name
                temporary = target.with_suffix('.partial')
                with temporary.open('x') as stream:
                    json.dump(response, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(target)
                completed.add(source.name)
            self.stop.wait(.01)

    def start(self):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        self.journal.touch(exist_ok=False)
        self.journal.with_suffix('.mirror.jsonl').touch(exist_ok=False)
        self.journal.with_suffix('.start.json').write_text(json.dumps({**self.metadata,
            'before': self.environment.get_full_snapshot(), 'timestamp': time.time()}))
        for name in ['requests', 'responses']:
            (self.exchange / name).mkdir(parents=True, exist_ok=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        self.journal.with_suffix('.end.json').write_text(json.dumps({**self.metadata,
            'complete': not self.thread.is_alive() and self.fatal_error is None,
            'fatal_error':self.fatal_error,'calls': len(self.calls),
            'sha256': hashlib.sha256(self.journal.read_bytes()).hexdigest(),
            'after': self.environment.get_full_snapshot(), 'timestamp': time.time()}))
