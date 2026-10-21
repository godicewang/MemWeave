import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { memoryPaths } from "../../src/storage/paths.ts";
import { withLock } from "../../src/storage/files.ts";
import { StateStore } from "../../src/state/store.ts";

test("Goal updates validate evidence/content and replay without duplicate events or extra metadata fields", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-goal-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root),
    task = { task_id: "task_goal", workspace: "--test--" },
    store = new StateStore(paths);
  await withLock(paths.taskLock(task), async () => {
    await store.initialize(task, "initial", "initial");
    const before = await readFile(paths.state(task), "utf8");
    await assert.rejects(
      store.updateGoal(
        task,
        {
          goal: "next",
          summary: "summary",
          keywords: ["test"],
          evidence: { U9: "missing" },
        },
        "next",
        100,
        new Set(["U1"]),
      ),
      /EVIDENCE/,
    );
    assert.equal(await readFile(paths.state(task), "utf8"), before);
    const input = {
      goal: "new goal",
      summary: "new summary",
      keywords: ["new"],
      evidence: { U1: "user change" },
    };
    assert.equal(
      (await store.updateGoal(task, input, "next", 100, new Set(["U1"])))
        .version,
      2,
    );
    assert.equal(
      (await store.updateGoal(task, input, "next", 100, new Set(["U1"])))
        .version,
      2,
    );
    const state = await store.read(task);
    assert.equal(state.goal, "new goal");
    assert.deepEqual(Object.keys(state.events[1]!).sort(), [
      "evidence",
      "goal",
      "op",
      "op_id",
      "time",
    ]);
  });
});
