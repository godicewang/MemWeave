import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, mkdir, readFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { memoryPaths, parentPath } from "../../src/storage/paths.ts";
import { DEFAULT_SETTINGS } from "../../src/config/defaults.ts";
import {
  LocalEmbedding,
  ensureEmbeddingModel,
} from "../../src/task/embedding.ts";

test(
  "local model lifecycle control: shutdown during resource preparation never resurrects a worker",
  { timeout: 180000 },
  async (t) => {
    const root = await mkdtemp(join(tmpdir(), "memweave-e5-lifecycle-"));
    t.after(() => rm(root, { recursive: true, force: true }));
    const assets = memoryPaths(join(root, "assets")),
      paths = memoryPaths(join(root, "runtime")),
      settings = DEFAULT_SETTINGS.task_search;
    if (process.env.MEMWEAVE_EMBEDDING_MODELS) {
      await mkdir(parentPath(assets.models), { recursive: true });
      await symlink(
        process.env.MEMWEAVE_EMBEDDING_MODELS,
        assets.models,
        "dir",
      );
    }
    const manifest = await ensureEmbeddingModel(assets, settings);
    for (const item of manifest.files) {
      if (item.file === "config.json") continue;
      await mkdir(parentPath(paths.modelFile(item.file)), { recursive: true });
      await symlink(assets.modelFile(item.file), paths.modelFile(item.file));
    }
    const config = await readFile(assets.modelFile("config.json"));
    let start!: () => void, release!: () => void;
    const started = new Promise<void>((resolve) => {
        start = resolve;
      }),
      blocked = new Promise<void>((resolve) => {
        release = resolve;
      });
    t.mock.method(globalThis, "fetch", async (input: unknown) => {
      assert.ok(String(input).endsWith("/config.json"));
      start();
      await blocked;
      return new Response(config);
    });
    const embedding = new LocalEmbedding(paths);
    t.after(() => embedding.dispose());
    const pending = embedding.embed(["shutdown control"], "query", settings);
    await started;
    const stopped = embedding.dispose();
    release();
    await assert.rejects(pending, /TASK_EMBEDDING_STOPPED/);
    await stopped;
    const active = new LocalEmbedding(assets);
    t.after(() => active.dispose());
    assert.equal(
      (await active.embed(["active shutdown"], "query", settings)).vectors[0]!
        .length,
      384,
    );
    await active.dispose();
    await assert.rejects(
      active.embed(["must stay closed"], "query", settings),
      /TASK_EMBEDDING_STOPPED/,
    );
    t.diagnostic(
      "public model resources only; one controlled fetch barrier; no model API request and no reduced Agent prompt used as plugin acceptance",
    );
  },
);
