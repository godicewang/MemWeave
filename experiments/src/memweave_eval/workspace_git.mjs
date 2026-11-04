// Read-only evaluator metadata for explicitly selected Switch worktrees.
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const sha=value=>createHash('sha256').update(value).digest('hex');

export function gitWorktrees(root,names,{timeoutMs=15000}={}) {
  if(!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>15000)throw Error('invalid_git_snapshot_timeout');
  const result={};
  for(const name of names??[]) {
    try {
      if(typeof name!=='string'||!/^w\d\d$/.test(name))throw Error('invalid_selected_worktree');
      const folder=path.resolve(root,name);
      if(fs.realpathSync(root)!==path.resolve(root)||fs.realpathSync(folder)!==folder)throw Error('redirected_selected_worktree');
      const git=(phase,args,maxBuffer=10485760)=>{
        const value=spawnSync('git',['-C',folder,'-c','core.fsmonitor=false','-c','core.untrackedCache=false',...args],
          {timeout:timeoutMs,maxBuffer,env:{...process.env,GIT_OPTIONAL_LOCKS:'0',GIT_TERMINAL_PROMPT:'0',
            GIT_CONFIG_NOSYSTEM:'1',GIT_CONFIG_GLOBAL:'/dev/null',GIT_CONFIG_COUNT:'0'}});
        if(value.status!==0) {
          const error=Error('git_snapshot_unavailable');
          error.diagnostic={phase,exit_code:value.status??null,signal:value.signal??null,
            error_code:value.error?.code??null,timeout_ms:timeoutMs,
            stderr_bytes:value.stderr?.length??0,stderr_sha256:sha(value.stderr??Buffer.alloc(0))};
          throw error;
        }
        return value.stdout;
      };
      const head=git('head',['rev-parse','HEAD']).toString('utf8').trim();
      if(!/^[a-f0-9]{40,64}$/.test(head))throw Error('invalid_git_head');
      const diff=sha(git('diff',['diff','--no-ext-diff','--no-textconv','--binary','HEAD','--']));
      const files=git('untracked',['ls-files','--others','--exclude-standard','-z']).toString('utf8').split('\0').filter(Boolean).sort();
      if(files.length>1000)throw Error('untracked_snapshot_count_limit');
      let bytes=0;const untracked={};
      for(const relative of files) {
        const filename=path.resolve(folder,relative);
        if(!filename.startsWith(folder+path.sep))throw Error('untracked_scope_escape');
        const stat=fs.lstatSync(filename);
        if(stat.isSymbolicLink())untracked[relative]={kind:'link',sha256:sha(fs.readlinkSync(filename))};
        else {
          if(!stat.isFile()||stat.size>1048576||(bytes+=stat.size)>8388608)throw Error('untracked_snapshot_size_limit');
          untracked[relative]={kind:'file',sha256:sha(fs.readFileSync(filename))};
        }
      }
      result[name]={status:'complete',version:'git-worktree-v1',head,diff_sha256:diff,
        untracked,projection_sha256:sha(JSON.stringify({head,diff,untracked}))};
    }catch(error) {
      result[name]={status:'incomplete',version:'git-worktree-v1',reason:error?.message??'git_snapshot_error',
        ...(error?.diagnostic?{diagnostic:error.diagnostic}:{})};
    }
  }
  return result;
}
