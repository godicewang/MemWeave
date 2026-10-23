import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { StateStore } from "../../src/state/store.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import { withLock } from "../../src/storage/files.ts";
import { stateAdmission, stateSize } from "../../src/state/budget.ts";
import { conservativeCounter } from "../../src/window/tokens.ts";
import { prepareStateBatch } from "../../src/state/window.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";

test("State token trigger precedes count; rejected batch is atomic and committed retry bypasses changed admission", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-admission-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root),
    task = { task_id: "task_admission", workspace: "--test--" },
    store = new StateStore(paths);
  await withLock(paths.taskLock(task), async () => {
    const initial = await store.initialize(task, "goal", "init");
    const limit = stateSize(task.task_id, initial, conservativeCounter) + 80;
    const guard = stateAdmission(conservativeCounter, limit);
    const item = {
      type: "fact" as const,
      content: "small fact",
      evidence: { U1: "source" },
    };
    const one = await store.append(
      task,
      [item],
      "one",
      100,
      new Set(["U1"]),
      guard,
    );
    const batch = prepareStateBatch(task.task_id, one, DEFAULT_CONFIG, true);
    assert.ok(batch);
    assert.equal(batch.candidate_ids.length, 1);
    const bytes = await readFile(paths.state(task), "utf8");
    await assert.rejects(
      store.append(
        task,
        Array.from({ length: 20 }, () => item),
        "too-large",
        100,
        new Set(["U1"]),
        guard,
      ),
      /STATE_BUDGET_EXCEEDED/,
    );
    assert.equal(await readFile(paths.state(task), "utf8"), bytes);
    assert.equal(
      (
        await store.append(
          task,
          [item],
          "one",
          100,
          new Set(["U1"]),
          stateAdmission(conservativeCounter, 1),
        )
      ).version,
      one.version,
    );
    const reduced = await store.updateGoal(
      task,
      { goal: "g", summary: "s", keywords: ["g"], evidence: { U1: "source" } },
      "shorten",
      100,
      new Set(["U1"]),
      stateAdmission(conservativeCounter, 1),
    );
    assert.equal(reduced.goal, "g");
  });
});
