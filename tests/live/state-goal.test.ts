import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {taskSession} from '../fixtures/task-session.ts';
import {verifyProviderCapacity} from '../../src/pi/model-capacity.ts';

test('真实 DeepSeek：Goal 更新与 State 读取，索引和尾部认知同步', {timeout:60_000},async t=>{
 const authPath=process.env.MEMWEAVE_DEEPSEEK_AUTH??join(homedir(),'.local/share/memweave-dev/pi-agent/auth.json');const original=await readFile(authPath);
 t.after(async()=>assert.ok(original.equals(await readFile(authPath))));
 const credential=(JSON.parse(original.toString()) as {deepseek?:{type?:string;key?:unknown}}).deepseek;assert.ok(credential?.type==='api_key'&&typeof credential.key==='string');
 const h=await taskSession(t,{verifyCapacity:verifyProviderCapacity});await h.runtime.setRuntimeApiKey('deepseek',credential.key);const model=h.runtime.getModel('deepseek','deepseek-flash');assert.ok(model);await h.session.setModel(model);h.session.setActiveToolsByName(['task_create','update_goal','state_read']);
 await h.session.prompt('集成测试第一步：只调用 task_create 创建任务，title=Goal verification，goal=验证初始目标，project_name=MemWeave，summary=初始目标验证，keywords=["初始"]。成功后回复 CREATED，不要更新 Goal。');
 const task=(await h.tasks.index.read())[0];assert.ok(task);assert.equal((await h.tasks.state.read(task)).version,1);
 await h.session.prompt(`用户明确调整同一任务的目标，请调用 update_goal：goal=验证更新后的目标，summary=目标更新验证，keywords=["目标更新"]，evidence使用本条真实用户消息的引用并说明用户修改要求。保持项目名不变。成功后调用 state_read，task_id=${task.task_id}。读取后回复 MEMWEAVE_GOAL_OK，不要重复调用。`);
 const current=await h.tasks.index.get(task.task_id),state=await h.tasks.state.read(current);assert.equal(state.version,2);assert.equal(state.goal,'验证更新后的目标');assert.equal(current.summary,'目标更新验证');assert.deepEqual(current.keywords,['目标更新']);assert.equal(current.project_name,'MemWeave');
 assert.deepEqual(h.diagnostics,[]);assert.deepEqual(h.errors,[]);assert.match(JSON.stringify(h.frames.at(-1)),/验证更新后的目标/);
 const final=h.session.agent.state.messages.at(-1);assert.ok(final?.role==='assistant'&&final.stopReason==='stop');assert.match(JSON.stringify(final.content),/MEMWEAVE_GOAL_OK/);
 const userEntries=h.manager.getEntries().filter(e=>e.type==='message'&&e.message.role==='user');assert.ok(userEntries.every(e=>e.type==='message'&&e.message.role==='user'&&!JSON.stringify(e.message.content).includes('# Symbolic State')));
 t.diagnostic(`${h.frames.length} real inference requests; native task_create, update_goal and state_read completed`);
});
