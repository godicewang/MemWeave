import test from "node:test";
import assert from "node:assert/strict";
import { writeFile, appendFile } from "node:fs/promises";
import {
  fauxAssistantMessage as answer,
  fauxToolCall as call,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { TaskSearch } from "../../src/task/search.ts";
import { DEFAULT_SETTINGS } from "../../src/config/defaults.ts";
import type { Embedder } from "../../src/task/embedding.ts";
test("derived vectors survive reopening; F/D do not re-embed but Goal updates do; corrupt authority never hides behind cache", async (t) => {
  let passages = 0,
    queries = 0;
  const embed: Embedder = async (texts, kind) => {
    if (kind === "passage") passages += texts.length;
    else queries += texts.length;
    return {
      vectors: texts.map(() => [1, ...Array<number>(383).fill(0)]),
      truncated: texts.map(() => false),
    };
  };
  const h = await taskSession(t, { embedder: embed });
  h.faux.setResponses([
    answer([
      call("task_create", {
        title: "Payment",
        goal: "支付超时",
        project_name: "P",
        summary: "payment latency",
        keywords: ["payment"],
      }),
    ]),
    answer("ready"),
  ]);
  await h.session.prompt("修复支付");
  const task = (await h.tasks.index.read())[0]!;
  const found = await h.tasks.find({ query: "付款等待过长" });
  assert.equal(found[0]!.goal, "支付超时");
  assert.equal(passages, 1);
  h.faux.setResponses([
    answer([
      call("state_append", {
        items: [
          { type: "fact", content: "存在超时", evidence: { U1: "用户要求" } },
        ],
      }),
    ]),
    answer("saved"),
  ]);
  await h.session.prompt("save observation");
  await h.tasks.find({ query: "payment" });
  assert.equal(passages, 1);
  const reopened = new TaskSearch(h.paths, h.tasks.state, embed);
  await reopened.find(
    await h.tasks.index.read(),
    { query: "payment" },
    DEFAULT_SETTINGS.task_search,
  );
  assert.equal(passages, 1);
  reopened.close();
  h.faux.setResponses([
    answer([
      call("update_goal", {
        goal: "支付重试策略",
        summary: "payment retry",
        keywords: ["retry"],
        evidence: { U1: "目标细化" },
      }),
    ]),
    answer("updated"),
  ]);
  await h.session.prompt("目标细化为支付重试策略");
  await h.tasks.find({ query: "retry" });
  assert.equal(passages, 2);
  assert.equal(queries, 4);
  await writeFile(h.paths.search(task.task_id).data, "broken cache");
  const rebuilt = new TaskSearch(h.paths, h.tasks.state, embed);
  await rebuilt.find(
    await h.tasks.index.read(),
    { query: "retry" },
    DEFAULT_SETTINGS.task_search,
  );
  assert.equal(passages, 3);
  rebuilt.close();
  const location = h.paths.search(task.task_id).data;
  const { readFile } = await import("node:fs/promises");
  const derived = JSON.parse(await readFile(location, "utf8"));
  derived.goal = "silently modified";
  await writeFile(location, JSON.stringify(derived));
  const checked = new TaskSearch(h.paths, h.tasks.state, embed);
  const result = await checked.find(
    await h.tasks.index.read(),
    { query: "retry" },
    DEFAULT_SETTINGS.task_search,
  );
  assert.equal(passages, 4);
  assert.notEqual(result[0]!.goal, "silently modified");
  checked.close();
  await appendFile(h.paths.state(task), "corrupt primary\n");
  await assert.rejects(h.tasks.find({ query: "retry" }), /CORRUPT_STATE/);
});
