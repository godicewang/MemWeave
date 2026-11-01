import json,os,subprocess
from pathlib import Path
import pytest
POLICY=Path(__file__).parents[1]/'src/memweave_eval/sealed_bash_env.sh'

@pytest.fixture
def environment(tmp_path):
 runtime=tmp_path/'runtime';(runtime/'bin').mkdir(parents=True)
 executable=runtime/'bin/node';executable.write_text('#!/bin/sh\necho should-not-run\n');executable.chmod(0o755)
 return dict(os.environ,BASH_ENV=str(POLICY.resolve()),MEMWEAVE_EVAL_ASSET_ROOT=str(runtime.resolve()),
             MEMWEAVE_EVAL_TRACE=str(tmp_path/'trace.jsonl'),PATH=str(runtime/'bin')+':'+os.environ['PATH'])

@pytest.mark.parametrize('command',[
 'which python3 || true','command -v python3 || true','command -p -v python3 || true','type -a node',
 "printf '%s\\n' 'python|perl' | grep -E 'python|perl'", "printf '%s\\n' 'node python3 perl'",'echo python3',
 'env CHECK=python3 command -v python3 || true',"bash -c 'which python3 || true'",'command -v node',
 'for x in python3 perl node; do command -v "$x" || true; done',"bash -lc 'echo python3'",
 "cat > probe.c <<'EOF'\ntypedef struct Node node;\nnode *root;\nEOF\ntest -s probe.c",
])
def test_queries_literals_and_heredoc_are_not_interpreter_execution(tmp_path,environment,command):
 result=subprocess.run(['/bin/bash','-c',command],env=environment,cwd=tmp_path,capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 assert not Path(environment['MEMWEAVE_EVAL_TRACE']).exists()

@pytest.mark.parametrize('command',[
 'node -v',"'no'de -v",'env -u NODE_OPTIONS node -v','timeout -k 1 5 node -v',
 'command node -v','exec node -v',"bash -c 'node -v'",'which node; node -v',
 "cat > probe.c <<'EOF'\nnode *root;\nEOF\nnode -v",
])
def test_actual_injected_runtime_execution_is_rejected(tmp_path,environment,command):
 result=subprocess.run(['/bin/bash','-c',command],env=environment,cwd=tmp_path,capture_output=True,text=True)
 assert result.returncode==126,(result.stdout,result.stderr)
 assert 'should-not-run'not in result.stdout
 events=[json.loads(s)for s in Path(environment['MEMWEAVE_EVAL_TRACE']).read_text().splitlines()]
 assert events[-1]['event']=='sealed_tool_rejected'


def test_legal_c_helper_named_node_is_not_the_injected_runtime(tmp_path,environment):
 helper=tmp_path/'node';helper.write_text('#!/bin/sh\necho legal-helper\n');helper.chmod(0o755)
 result=subprocess.run(['/bin/bash','-c','./node'],env=environment,cwd=tmp_path,capture_output=True,text=True)
 assert result.returncode==0 and result.stdout=='legal-helper\n'
 assert not Path(environment['MEMWEAVE_EVAL_TRACE']).exists()

@pytest.mark.parametrize('command,output',[
 ('false; status=$?; printf "%s" "$status"','1'),
 ('if false; then node -v; else printf safe; fi','safe'),
 ('printf before; false || printf after','beforeafter'),
 ('value=$(printf data); printf "%s" "$value"','data'),
])
def test_allowed_shell_status_and_control_flow_are_preserved(tmp_path,environment,command,output):
 result=subprocess.run(['/bin/bash','-c',command],env=environment,cwd=tmp_path,capture_output=True,text=True)
 assert result.returncode==0 and result.stdout==output,result.stderr
 assert not Path(environment['MEMWEAVE_EVAL_TRACE']).exists()
