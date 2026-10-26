import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, mkdir, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { memoryPaths, parentPath } from "../../src/storage/paths.ts";
import { DEFAULT_SETTINGS } from "../../src/config/defaults.ts";
import { LocalEmbedding } from "../../src/task/embedding.ts";

test("local E5 communication batches equal singleton vectors exactly, including bounded long passages", { timeout: 180000 }, async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-e5-batch-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root);
  if (process.env.MEMWEAVE_EMBEDDING_MODELS) {
    await mkdir(parentPath(paths.models), { recursive: true });
    await symlink(process.env.MEMWEAVE_EMBEDDING_MODELS, paths.models, "dir");
  }
  const embedding = new LocalEmbedding(paths), settings = DEFAULT_SETTINGS.task_search;
  t.after(() => embedding.dispose());
  const texts = Array.from({ length: 16 }, (_, i) => i === 7
    ? "Goal: 支付去重\nSummary: " + "保持长文档截断和最终分隔符。".repeat(500)
    : `Goal: ${i % 2 ? "修复登录状态失效" : "prevent duplicate payments"}\nTitle: 工作 ${i} ✅`);
  const singles = [];
  for (const text of texts) singles.push(await embedding.embed([text], "passage", settings));
  const batch = await embedding.embed(texts, "passage", settings);
  assert.deepEqual(batch.vectors, singles.map((item) => item.vectors[0]));
  assert.deepEqual(batch.truncated, singles.map((item) => item.truncated[0]));
  assert.equal(batch.truncated[7], true);
  const query = await embedding.embed(["付款重复记账"], "query", settings);
  assert.equal(query.vectors[0]!.length, 384);
  await assert.rejects(embedding.embed([texts[7]!], "query", settings), /TASK_SEARCH_QUERY_TOO_LONG/);
  t.diagnostic("real local E5 Q8, 16 singleton passages versus one communication batch; exact vectors/truncation and query rejection; zero remote model API");
});
