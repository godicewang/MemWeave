import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  fauxAssistantMessage as answer,
  fauxToolCall as call,
} from "@earendil-works/pi-ai/providers/faux";
import { productionTaskSession } from "../fixtures/production-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { scopeOf } from "../../src/pi/session-memory.ts";
import { RESUME_TYPE } from "../../src/task/resume-window.ts";

test(
  "real Flash autonomously exempts arithmetic, selects hybrid Top-k and restores the old native Task window",
  { timeout: 180000 },
  async (t) => {
    const source = await productionTaskSession(t);
    const goals = [
      "修复支付接口重复扣款并验证幂等键",
      "优化终端界面的主题颜色",
      "排查前端构建缓存失效",
      "编写多语言翻译字典",
      "压缩数据库备份文件",
    ];
    for (const [i, goal] of goals.entries()) {
      source.faux.setResponses([
        answer([
          call("task_create", {
            title: `Work ${i}`,
            goal,
            project_name: "MemWeave",
            summary: goal,
            keywords: [i === 0 ? "payment" : "engineering"],
          }),
        ]),
        answer("created"),
      ]);
      await source.session.prompt(`建立工作目标：${goal}`);
      if (i === 0) {
        source.faux.setResponses([
          answer("已确认测试环境别名为 SABLE_71，幂等键保留24小时。"),
        ]);
        await source.session.prompt(
          "当前支付工作约定：测试环境别名 SABLE_71；幂等键保留24小时。暂不执行业务操作。",
        );
      }
    }
    const originalTasks = await source.tasks.index.read(),
      target = originalTasks.find((v) => v.keywords.includes("payment"))!;
    const original = await readFile(source.paths.state(target)),
      sourceMessages = source.manager
        .getBranch()
        .filter((e) => e.type === "message");
    const authPath =
        process.env.MEMWEAVE_DEEPSEEK_AUTH ??
        join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json"),
      auth = await readFile(authPath);
    t.after(async () => assert.ok(auth.equals(await readFile(authPath))));
    const key = (
      JSON.parse(auth.toString()) as { deepseek?: { key?: unknown } }
    ).deepseek?.key;
    assert.equal(typeof key, "string");
    const h = await productionTaskSession(t, {
      paths: source.paths,
      verifyCapacity: verifyProviderCapacity,
    });
    await h.runtime.setRuntimeApiKey("deepseek", key as string);
    const model = h.runtime.getModel("deepseek", "deepseek-flash");
    assert.ok(model);
    await h.session.setModel(model);
    await h.session.prompt("12×7是多少？");
    assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
    assert.equal((await h.tasks.index.read()).length, 5);
    await h.session.prompt(
      "我们之前做过防止同一笔付款重复记账的工作。请找到并继续那个任务，恢复之前的认知和近期讨论，告诉我之前约定的测试环境别名和幂等键保留时长。不要执行文件或外部业务操作。",
    );
    assert.equal(scopeOf(h.manager.getBranch()).task_id, target.task_id);
    const calls = h.manager
      .getBranch()
      .flatMap((e) =>
        e.type === "message" && e.message.role === "assistant"
          ? e.message.content.filter((p) => p.type === "toolCall")
          : [],
      );
    assert.ok(
      calls.some(
        (c) =>
          c.type === "toolCall" &&
          c.name === "task_find" &&
          (c.arguments as { initialize?: boolean }).initialize === true,
      ),
    );
    assert.ok(
      calls.some((c) => c.type === "toolCall" && c.name === "task_resume"),
    );
    assert.ok(
      h.manager
        .getBranch()
        .some((e) => e.type === "custom" && e.customType === RESUME_TYPE),
    );
    assert.ok(
      h.frames.some((frame) => JSON.stringify(frame).includes("SABLE_71")),
    );
    const final = h.session.agent.state.messages.at(-1);
    assert.ok(final?.role === "assistant" && final.stopReason === "stop");
    const text = JSON.stringify(final.content);
    assert.match(text, /SABLE_71/);
    assert.match(text, /24/);
    assert.equal((await h.tasks.index.read()).length, 5);
    assert.deepEqual(
      source.manager.getBranch().filter((e) => e.type === "message"),
      sourceMessages,
    );
    // The model may legitimately save a new Fact after restoring the old dialogue.
    assert.ok(
      (await readFile(source.paths.state(target)))
        .subarray(0, original.length)
        .equals(original),
    );
    assert.deepEqual(h.diagnostics, []);
    assert.deepEqual(h.errors, []);
    t.diagnostic(
      "five real native Tasks arranged with a scripted provider; arithmetic, initialization, local hybrid lookup, selection and restored-window answer used real Flash and the complete production prompt/tools",
    );
  },
);
