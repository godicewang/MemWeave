import asyncio

import pytest

from memweave_eval.free_episode import FreeEpisodePi


def test_free_cli_control_captures_original_memory_even_after_actor_error(monkeypatch):
    called=[];agent=object.__new__(FreeEpisodePi);agent._asset_root='/fixture'
    async def upload(*a,**kw):pass
    async def capture(*a,**kw):called.append('captured')
    async def fail(*a,**kw):raise RuntimeError('known actor failure')
    agent.upload_private=upload;agent.capture_memory_evidence=capture
    monkeypatch.setattr('memweave_eval.free_episode.Pi.run',fail)
    with pytest.raises(RuntimeError,match='known actor failure'):
        asyncio.run(agent.run('original instruction',None,None))
    assert called==['captured']and agent._evaluation_stage==1
