import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { productionTaskSession as taskSession } from "../fixtures/production-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";

test(
  "真实 DeepSeek：正式 Task/State 工具与自动注入闭环",
  { timeout: 60_000 },
  async (t) => {
    const authPath =
      process.env.MEMWEAVE_DEEPSEEK_AUTH ??
      join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
    const original = await readFile(authPath);
    t.after(async () => {
      assert.ok(original.equals(await readFile(authPath)));
    });
    const credential = (
      JSON.parse(original.toString()) as {
        deepseek?: { type?: string; key?: unknown };
      }
    ).deepseek;
    assert.ok(
      credential?.type === "api_key" && typeof credential.key === "string",
      "private DeepSeek configuration required",
    );
    const h = await taskSession(t, { verifyCapacity: verifyProviderCapacity });
    await h.runtime.setRuntimeApiKey("deepseek", credential.key);
    const model = h.runtime.getModel("deepseek", "deepseek-flash");
    assert.ok(model);
    await h.session.setModel(model);

    await h.session.prompt(
      '这是 MemWeave 集成测试。请先调用 task_create 创建一个任务：title 为 Phase2 verification，goal 为 验证任务记忆闭环，project_name 为 MemWeave，summary 为 验证Task与State，keywords 为 ["验证"]。读取创建结果和自动提供的 State 后，再调用 state_append 保存一条 fact，content 为 用户要求验证任务记忆闭环，evidence 使用本次用户请求的 U1 并简要说明。不要在同一批调用里创建并写入 State。保存后回复 MEMWEAVE_PHASE2_OK，不再调用工具。',
    );
    assert.deepEqual(h.diagnostics, []);
    assert.deepEqual(h.errors, []);
    const tasks = await h.tasks.index.read();
    assert.equal(tasks.length, 1);
    const task = tasks[0]!,
      state = await h.tasks.state.read(task);
    assert.equal(state.version, 2);
    assert.equal(state.facts.length, 1);
    assert.ok(state.facts[0]?.evidence.U1);
    assert.ok(h.frames.length >= 3);
    assert.match(
      JSON.stringify(h.frames.at(-1)),
      /F1 用户要求验证任务记忆闭环/,
    );
    const final = h.session.agent.state.messages.at(-1);
    assert.ok(final?.role === "assistant" && final.stopReason === "stop");
    assert.match(JSON.stringify(final.content), /MEMWEAVE_PHASE2_OK/);
    assert.doesNotMatch(
      await readFile(h.manager.getSessionFile()!, "utf8"),
      /# Symbolic State|pi_long_task_rule/,
    );
    t.diagnostic(
      `${h.frames.length} real inference requests; task_create and state_append completed through native Pi loop`,
    );
  },
);
