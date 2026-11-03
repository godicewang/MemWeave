import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from memweave_eval.pi_agent import ExperimentPi


def test_streaming_offsets_match_wc_without_following_links_or_counting_partial_lines(tmp_path):
    code=Path(__file__).parents[1]/'src/memweave_eval/session_positions.mjs'
    files={'session ü spaces.jsonl':'first\nsecond\nunfinished','other.jsonl':'汉字\n'*70000,'empty.jsonl':''}
    for name,body in files.items():(tmp_path/name).write_text(body)
    (tmp_path/'link.jsonl').symlink_to(tmp_path/'other.jsonl');(tmp_path/'folder.jsonl').mkdir()
    (tmp_path/'ignored.txt').write_text('not a Session\n')
    result=subprocess.run(['node',str(code),str(tmp_path)],text=True,capture_output=True,check=True,timeout=10)
    values=json.loads(result.stdout)
    assert set(values)==set(files)
    for name in files:
        count=subprocess.check_output(['wc','-l',str(tmp_path/name)],text=True).strip().split()[0]
        assert values[name]==int(count)
    absent=subprocess.run(['node',str(code),str(tmp_path/'missing')],text=True,capture_output=True,check=False,timeout=10)
    assert absent.returncode!=0 and not absent.stdout


@pytest.mark.parametrize('response,accepted',[('{"session.jsonl":2}',True),('{"session.jsonl":-1}',False),
    ('{"session.jsonl":true}',False),('null',False),('{"total":3}',False)])
def test_wrapper_validates_offsets_and_uses_only_existing_node_helper(tmp_path,response,accepted):
    agent=ExperimentPi(logs_dir=tmp_path,model_name='deepseek/deepseek-flash',version='1.4.0',node_version='24.22.0',
        variant='pi-native',package_path='/tmp/a',package_sha256='a'*64,auth_path='',protocol='fixed35',evaluation_deadline=2000000000)
    agent._asset_root='/trusted node'
    mock=AsyncMock(return_value=SimpleNamespace(stdout=response))
    with patch.object(agent,'exec_as_agent',mock):
        if accepted:assert asyncio.run(agent._session_positions(object()))=={'session.jsonl':2}
        else:
            with pytest.raises(ValueError):asyncio.run(agent._session_positions(object()))
    command=mock.call_args.args[1]
    assert command=="node '/trusted node/evaluation/session_positions.mjs' /logs/agent/pi/sessions"
