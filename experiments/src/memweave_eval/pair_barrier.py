"""Host-side paired start; setup time does not consume one actor's case clock."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from .storage import atomic_json

ARMS = ('pi-native', 'pi-memweave')


async def paired_start(root: Path | None, arm: str, *, timeout=180.):
    if root is None:
        return time.time()
    if arm not in ARMS:
        raise ValueError('invalid paired arm')
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root/(arm+'.ready.json'), {'ready_at': time.time()}, immutable=True)
    stop = time.monotonic()+timeout
    while time.monotonic() < stop:
        files = [root/(a+'.ready.json') for a in ARMS]
        if all(f.exists() for f in files):
            release = max(json.loads(f.read_text())['ready_at'] for f in files)
            try:
                atomic_json(root/'release.json', {'start_unix': release}, immutable=True)
            except FileExistsError:
                pass
            return json.loads((root/'release.json').read_text())['start_unix']
        await asyncio.sleep(.1)
    raise TimeoutError('paired setup did not reach start barrier; no actor request permitted')
