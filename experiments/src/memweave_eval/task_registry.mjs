// Evaluation-only durable object inventory. Never writes runtime memory or prompts.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {contentEvidence} from './content_evidence.mjs';
const digest=value=>createHash('sha256').update(value).digest('hex');

export function captureTaskRegistry({root=path.join(os.homedir(),'.pi','memory'),evidence=contentEvidence()}={}){
  const tasks=[],errors=[];let index=null;
  try{
    if(!fs.existsSync(root))return {version:'fixed35-task-registry-v1',complete:true,tasks:[],errors:[]};
    if(fs.lstatSync(root).isSymbolicLink())throw Error('redirected_memory_root');
    const indexFile=path.join(root,'index.json');
    if(fs.existsSync(indexFile)){
      if(fs.lstatSync(indexFile).isSymbolicLink())throw Error('redirected_task_index');
      const raw=fs.readFileSync(indexFile);JSON.parse(raw.toString('utf8'));
      index={sha256:digest(raw),ref:evidence?.put(raw)??null};
    }
    for(const workspace of fs.readdirSync(root,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){
      if(!workspace.isDirectory())continue;
      const folder=path.join(root,workspace.name,'tasks');
      if(!fs.existsSync(folder))continue;
      if(fs.lstatSync(folder).isSymbolicLink())throw Error('redirected_task_directory');
      for(const task of fs.readdirSync(folder,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){
        if(!/^task_[A-Za-z0-9_-]+$/.test(task.name))continue;
        const journal=path.join(folder,task.name,'state.json');
        if(!task.isDirectory()||!fs.existsSync(journal)||fs.lstatSync(journal).isSymbolicLink()){
          errors.push({workspace:workspace.name,task_id:task.name,reason:'partial_or_redirected_task'});continue;
        }
        const raw=fs.readFileSync(journal,'utf8');
        if(!raw.endsWith('\n')){errors.push({task_id:task.name,reason:'incomplete_journal'});continue;}
        const rows=raw.trimEnd().split('\n').map(line=>JSON.parse(line));
        const goal=rows.filter(row=>row.op==='update_goal').at(-1)?.goal;
        if(typeof goal!=='string'||!goal.trim()){
          errors.push({task_id:task.name,reason:'durable_goal_missing'});continue;
        }
        tasks.push({workspace:workspace.name,task_id:task.name,version:rows.length,
          journal_sha256:digest(raw),journal_ref:evidence?.put(raw)??null,goal_sha256:digest(goal)});
      }
    }
    if(new Set(tasks.map(t=>t.task_id)).size!==tasks.length)errors.push({reason:'duplicate_global_task_id'});
  }catch(error){errors.push({reason:'registry_read_failed',error_class:error?.name??'Error'});}
  return {version:'fixed35-task-registry-v1',complete:errors.length===0,tasks,errors,index};
}
