import asyncio

import pytest

from memweave_eval.pair_barrier import paired_start


def test_paired_start_has_common_clock_and_rejects_reuse(tmp_path):
    async def run():
        return await asyncio.gather(*(paired_start(tmp_path, a) for a in ('pi-native','pi-memweave')))
    a,b=asyncio.run(run())
    assert a == b and a > 0
    with pytest.raises(FileExistsError):
        asyncio.run(paired_start(tmp_path,'pi-native'))


def test_absent_peer_fails_closed_before_requests(tmp_path):
    with pytest.raises(TimeoutError):
        asyncio.run(paired_start(tmp_path,'pi-native',timeout=.01))
