import test from "node:test";
import assert from "node:assert/strict";
import { rankTasks } from "../../src/task/search-rank.ts";
import { DEFAULT_SETTINGS } from "../../src/config/defaults.ts";

test("hybrid rank uses Goal/BM25, keywords and vector ranks, never auto-resumes", () => {
  const docs = [
    {
      task_id: "task_a",
      title: "orders",
      project_name: "P",
      summary: "old",
      keywords: ["orders"],
      goal: "修复支付超时",
      updated_at: "2026-01-01",
      vector: [1, 0],
    },
    {
      task_id: "task_b",
      title: "orders",
      project_name: "P",
      summary: "new",
      keywords: ["orders"],
      goal: "调整页面颜色",
      updated_at: "2026-02-01",
      vector: [0.1, 1],
    },
  ];
  const ranked = rankTasks(
    docs,
    "支付超时",
    [],
    [1, 0],
    DEFAULT_SETTINGS.task_search,
  );
  assert.equal(ranked[0]!.task_id, "task_a");
  assert.ok(ranked[0]!.score > ranked[1]!.score);
  assert.equal(ranked[0]!.ranks.semantic, 1);
  assert.equal(docs.length, 2);
  assert.equal(
    rankTasks([], "x", [], [1, 0], DEFAULT_SETTINGS.task_search).length,
    0,
  );
});

test("semantic retrieval bridges synonyms and lexical ranks do not pretend to have matched", () => {
  const ranked = rankTasks(
    [
      {
        task_id: "task_a",
        title: "checkout",
        project_name: "P",
        summary: "",
        keywords: [],
        goal: "payment requests expire",
        updated_at: "2026-01-01",
        vector: [1, 0],
      },
    ],
    "付款等待过久",
    [],
    [1, 0],
    DEFAULT_SETTINGS.task_search,
  );
  assert.equal(ranked[0]!.ranks.lexical, null);
  assert.equal(ranked[0]!.ranks.semantic, 1);
});
