import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

from memweave_eval.evidence_replay import replay_content


@pytest.mark.parametrize('order',['before','after'])
def test_signal_observation_is_separate_and_preserves_native_exit(tmp_path,order):
    source=Path(__file__).parents[1]/'src/memweave_eval/terminal_capture.mjs'
    workspace=tmp_path/'work';workspace.mkdir();(workspace/'proof.txt').write_text('actual evidence')
    home=tmp_path/'home';home.mkdir();store=tmp_path/'evidence'
    native="process.on('SIGTERM',()=>{queueMicrotask(()=>queueMicrotask(()=>process.exit(143)));});"
    install='installTerminalCapture();installTerminalCapture();'
    script='import {installTerminalCapture}from '+json.dumps(source.as_uri())+';'+(
        install+native if order=='before'else native+install)+"console.log('READY');setInterval(()=>{},1000);"
    env=dict(os.environ,HOME=str(home),MEMWEAVE_EVAL_CONTENT_STORE=str(store),MEMWEAVE_EVAL_DEADLINE='1',
        MEMWEAVE_EVAL_WORKSPACE=json.dumps({'root':str(workspace),'files':['proof.txt']}),
        MEMWEAVE_EVAL_INVOCATION_ID='invocation',MEMWEAVE_EVAL_STAGE_ID='1')
    process=subprocess.Popen(['node','--input-type=module','-e',script],env=env,stdout=subprocess.PIPE,text=True)
    try:
        assert process.stdout.readline().strip()=='READY'
        process.send_signal(signal.SIGTERM);assert process.wait(timeout=10)==143
    finally:
        if process.poll()is None:process.kill();process.wait()
    rows=replay_content(store)['events'];assert len(rows)==1
    event=rows[0];assert event['event']==event['phase']=='execution_terminated'
    assert event['capture_status']=='CAPTURED'and event['execution_invocation_id']=='invocation'
    assert event['registry']['complete']and event['workspace']['files']['proof.txt']
    assert event['signal']=='SIGTERM'and event['owner_pid']==process.pid
