import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { taskSession } from "../fixtures/task-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";

test(
  "真实 DeepSeek：State 满窗提醒、移除、事实原子修正和读取",
  { timeout: 60_000 },
  async (t) => {
    const authPath =
        process.env.MEMWEAVE_DEEPSEEK_AUTH ??
        join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json"),
      original = await readFile(authPath);
    t.after(async () => assert.ok(original.equals(await readFile(authPath))));
    const credential = (
      JSON.parse(original.toString()) as {
        deepseek?: { type?: string; key?: unknown };
      }
    ).deepseek;
    assert.ok(
      credential?.type === "api_key" && typeof credential.key === "string",
    );
    const h = await taskSession(t, { verifyCapacity: verifyProviderCapacity });
    await writeFile(
      h.paths.config,
      JSON.stringify({
        ...DEFAULT_CONFIG,
        state_max_events: 10,
        state_evict_batch: 2,
      }),
    );
    await h.runtime.setRuntimeApiKey("deepseek", credential.key);
    const model = h.runtime.getModel("deepseek", "deepseek-flash");
    assert.ok(model);
    await h.session.setModel(model);
    h.session.setActiveToolsByName([
      "task_create",
      "state_append",
      "state_remain",
      "modify_fact",
      "state_read",
    ]);
    await h.session.prompt(
      '这是完整State工具集成测试，请严格依序执行，每一步读到成功结果后再做下一步，不要并行：1.task_create，title=State window verification，goal=验证State窗口与修正，project_name=MemWeave，summary=窗口管理验证，keywords=["窗口"]。2.state_append一次创建10条fact，正文依次为“用户要求验证条目1”至“用户要求验证条目10”，evidence均使用本条真实用户消息的U1，说明用户明确要求。3.收到State窗口管理提醒后调用state_remain，event_ids=[]，不保留候选。4.modify_fact归档F3，同时新增Fact“用户要求修正第三条测试认知”，evidence为U1并说明本次用户要求修正。5.调用state_read读取刚创建的task_id。6.回复MEMWEAVE_STATE_WINDOW_OK。不要额外新增State条目，不要重建Task，不要重复以上操作。',
    );
    const tasks = await h.tasks.index.read();
    assert.equal(tasks.length, 1);
    const task = tasks[0]!,
      state = await h.tasks.state.read(task);
    assert.equal(state.version, 13);
    assert.equal(state.facts.length, 8);
    assert.equal(state.facts.at(-1)?.id, "F11");
    assert.equal(state.facts.at(-1)?.content, "用户要求修正第三条测试认知");
    assert.equal(state.events.filter((e) => e.op === "slide_window").length, 1);
    assert.equal(state.events.filter((e) => e.op === "modify_fact").length, 1);
    assert.ok(
      h.frames.some((frame) =>
        JSON.stringify(frame.at(-1)).includes("State 窗口管理"),
      ),
    );
    assert.deepEqual(h.diagnostics, []);
    assert.deepEqual(h.errors, []);
    const final = h.session.agent.state.messages.at(-1);
    assert.ok(final?.role === "assistant" && final.stopReason === "stop");
    assert.ok(
      final.content.some((block) => block.type === "text" && block.text.trim()),
    );
    const results = h.manager
      .getEntries()
      .filter(
        (entry) =>
          entry.type === "message" && entry.message.role === "toolResult",
      );
    for (const name of [
      "task_create",
      "state_append",
      "state_remain",
      "modify_fact",
      "state_read",
    ])
      assert.ok(
        results.some(
          (entry) =>
            entry.type === "message" &&
            entry.message.role === "toolResult" &&
            entry.message.toolName === name &&
            !entry.message.isError,
        ),
        `successful ${name} result required`,
      );
    assert.doesNotMatch(
      await readFile(h.paths.view(task), "utf8"),
      /State 窗口管理/,
    );
    const users = h.manager
      .getEntries()
      .filter((e) => e.type === "message" && e.message.role === "user");
    assert.equal(users.length, 1);
    assert.ok(
      users.every(
        (e) =>
          e.type === "message" &&
          e.message.role === "user" &&
          !JSON.stringify(e.message.content).includes(
            "【State 窗口管理｜临时提醒】",
          ),
      ),
    );
    t.diagnostic(
      `${h.frames.length} real inference requests; all State tools through native Pi; test capacity 10/2, default 2000/200 separately covered by unit tests`,
    );
  },
);
