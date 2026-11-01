import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { getCurrentSystemPrompt, getSystemMessageText } from "@earendil-works/pi-ai";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";

const stateReviewRules = [
  "1. **执行前与完成前核对 State**：执行任务前，以及完成任务、提交最终结果前，必须仔细查阅当前 State，核对目标、有效约束、已有结论和未解决问题。后续行动应优先遵守其中有效约束；若与用户最新指令或可靠新证据冲突，先澄清或修正，不盲从旧记录。",
  "2. **先纠正 State，再继续行动**：发现可靠反证，或新结论推翻、修正或取代已有结论时，必须先通过 State 专用工具及时更新或取代过时、错误的记录，保留必要的证据及演化关系，再执行依赖该结论的后续操作。不得只追加新结论，却让相互矛盾的旧结论继续保持有效。",
  "State 并不是只在完成任务后记录。执行过程中，应及时通过现有 State 工具记录对后续行动有价值的执行约束、重要中间结论、关键失败或踩坑及其适用条件，保留必要证据，不能仅在任务完成时做总结性记录。已覆盖或没有重要变化时不重复写入，不强制记录每一步操作。",
];

test("stage guidance reaches the effective system/tools but ordinary turn completion creates no automatic cognition", async (t) => {
  const h = await taskSession(t);
  const providerSystems: string[] = [];
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", {
    title: "stage", goal: "verify delivery", project_name: "MemWeave", summary: "phase", keywords: ["phase"],
  }, { id: "create" })]), context => {
    providerSystems.push(getCurrentSystemPrompt(context.messages));
    return fauxAssistantMessage("Please clarify the remaining requirement.");
  }]);
  await h.session.prompt("start ongoing work");
  const system = h.frames.at(-1)![0]!;
  assert.ok(system.role === "system");
  assert.match(getSystemMessageText(system), /先验业务、再验记忆/);
  assert.match(getSystemMessageText(system), /turn_end.*不等于阶段完成/);
  assert.equal(providerSystems.length, 1);
  for (const rule of stateReviewRules) {
    assert.equal(providerSystems[0]!.split(rule).length - 1, 1, "完整规则须在实际模型请求中恰好出现一次");
  }
  assert.match(providerSystems[0]!, /决定发生变化时，先通过 `modify_fact` 原子归档不再有效/);
  const tools = h.session.getAllTools();
  assert.match(tools.find((tool) => tool.name === "state_append")!.description, /stage.*result/);
  assert.match(tools.find((tool) => tool.name === "task_create")!.description, /Short.*Q&A/);
  const task = (await h.tasks.index.read())[0]!, state = await h.tasks.state.read(task);
  assert.equal(state.version, 1); assert.equal(state.facts.length + state.decisions.length, 0);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /先验业务、再验记忆|pi_long_task_rule|执行前与完成前核对 State|先纠正 State，再继续行动|State 并不是只在完成任务后记录/);
});
