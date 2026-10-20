import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { memoryPaths } from "../../src/storage/paths.ts";
import { atomicWrite, withLock } from "../../src/storage/files.ts";
import { StateStore } from "../../src/state/store.ts";

test("State batch is atomic, prefix preserving, idempotent and code-point limited", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-state-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root),
    store = new StateStore(paths);
  const task = { task_id: "task_test", workspace: "--test--" };
  await withLock(paths.taskLock(task), async () => {
    await store.initialize(task, "goal", "create");
    const before = await readFile(paths.state(task), "utf8");
    await assert.rejects(
      store.append(
        task,
        [
          { type: "fact", content: "ok", evidence: { U1: "user" } },
          {
            type: "decision",
            content: "bad",
            evidence: { F1: "not committed" },
          },
        ],
        "batch",
        100,
        new Set(["U1"]),
      ),
      /EVIDENCE/,
    );
    assert.equal(await readFile(paths.state(task), "utf8"), before);
    const items = [
      {
        type: "fact" as const,
        content: "😀".repeat(100),
        evidence: { U1: "user" },
      },
    ];
    assert.equal(
      (await store.append(task, items, "batch", 100, new Set(["U1"]))).version,
      2,
    );
    assert.equal(
      (await store.append(task, items, "batch", 100, new Set(["U1"]))).version,
      2,
    );
    assert.ok((await readFile(paths.state(task), "utf8")).startsWith(before));
    await assert.rejects(
      store.append(
        task,
        [{ ...items[0]!, content: "😀".repeat(101) }],
        "next",
        100,
        new Set(["U1"]),
      ),
      /CONTENT/,
    );
    const state = await store.read(task);
    assert.equal(state.facts[0]?.id, "F1");
    assert.equal(state.goal, "goal");
  });
});

test("filesystem locks serialize independent callers and release on error; failed replace preserves source", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-lock-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const lock = join(root, "lock"),
    file = join(root, "data");
  await atomicWrite(file, "old");
  let value = 0;
  await Promise.all(
    Array.from({ length: 12 }, () =>
      withLock(lock, async () => {
        const previous = value;
        await new Promise((r) => setTimeout(r, 2));
        value = previous + 1;
      }),
    ),
  );
  assert.equal(value, 12);
  await assert.rejects(
    withLock(lock, async () => {
      throw Error("expected");
    }),
    /expected/,
  );
  await withLock(lock, async () => {});
  await mkdir(join(root, "directory"));
  await assert.rejects(atomicWrite(join(root, "directory"), "invalid"));
  assert.equal(await readFile(file, "utf8"), "old");
});

test("independent Node processes serialize complete State batches without losing writes", async (t) => {
  const { execFile } = await import("node:child_process"),
    { promisify } = await import("node:util");
  const run = promisify(execFile);
  const root = await mkdtemp(join(tmpdir(), "memweave-process-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root),
    task = { task_id: "task_process", workspace: "--test--" },
    store = new StateStore(paths);
  await withLock(paths.taskLock(task), () =>
    store.initialize(task, "goal", "initial"),
  );
  const script = `
 import {memoryPaths} from ${JSON.stringify(new URL("../../src/storage/paths.ts", import.meta.url).href)};
 import {withLock} from ${JSON.stringify(new URL("../../src/storage/files.ts", import.meta.url).href)};
 import {StateStore} from ${JSON.stringify(new URL("../../src/state/store.ts", import.meta.url).href)};
 const paths=memoryPaths(process.argv[1]),task={task_id:'task_process',workspace:'--test--'},store=new StateStore(paths);
 await withLock(paths.taskLock(task),()=>store.append(task,[{type:'fact',content:process.argv[2],evidence:{U1:'user'}}],process.argv[2],100,new Set(['U1'])));
 `;
  await Promise.all(
    Array.from({ length: 4 }, (_, i) =>
      run(process.execPath, [
        "--input-type=module",
        "-e",
        script,
        root,
        `writer-${i}`,
      ]),
    ),
  );
  const state = await store.read(task);
  assert.equal(state.version, 5);
  assert.deepEqual(
    state.facts.map((f) => f.id),
    ["F1", "F2", "F3", "F4"],
  );
  assert.equal(new Set(state.facts.map((f) => f.content)).size, 4);
});
