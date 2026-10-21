import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, chmod } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test, { type TestContext } from "node:test";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { memoryPaths, parentPath } from "../../src/storage/paths.ts";
import { withLock } from "../../src/storage/files.ts";
import { StateStore } from "../../src/state/store.ts";
import {
  prepareStateBatch,
  renderStateReminder,
} from "../../src/state/window.ts";
import { renderState } from "../../src/state/model.ts";

async function fixture(t: TestContext) {
  const root = await mkdtemp(join(tmpdir(), "memweave-window-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root),
    task = { task_id: "task_window", workspace: "--test--" },
    store = new StateStore(paths);
  await withLock(paths.taskLock(task), () =>
    store.initialize(task, "goal", "initial"),
  );
  return { paths, task, store };
}
const items = (count: number, prefix = "fact") =>
  Array.from({ length: count }, (_, i) => ({
    type: "fact" as const,
    content: `${prefix} ${i + 1}`,
    evidence: { U1: "user" },
  }));

test("default State window counts only active F/D: 2000 trigger, 200 candidates, 20 keep, overflow remains visible", async (t) => {
  const { paths, task, store } = await fixture(t);
  await withLock(paths.taskLock(task), async () => {
    let state = await store.append(
      task,
      items(1999),
      "first",
      100,
      new Set(["U1"]),
    );
    assert.equal(state.version, 2000);
    assert.equal(prepareStateBatch(task.task_id, state, DEFAULT_CONFIG), null);
    state = await store.append(
      task,
      items(1, "trigger"),
      "trigger",
      100,
      new Set(["U1"]),
    );
    const batch = prepareStateBatch(task.task_id, state, DEFAULT_CONFIG);
    assert.ok(batch);
    assert.equal(batch.candidate_ids.length, 200);
    assert.equal(batch.keep_limit, 20);
    assert.deepEqual(batch.evicted_range, { from: 2, to: 201 });
    const old = await readFile(paths.state(task), "utf8");
    await assert.rejects(
      store.remain(task, batch, batch.candidate_ids.slice(0, 21), "too-many"),
      /KEEP_LIMIT/,
    );
    await assert.rejects(
      store.remain(task, batch, ["F201"], "bad-range"),
      /CANDIDATE/,
    );
    assert.equal(await readFile(paths.state(task), "utf8"), old);
    state = await store.append(
      task,
      items(5, "overflow"),
      "overflow",
      100,
      new Set(["U1"]),
    );
    assert.equal(state.facts.length, 2005);
    assert.match(renderState(task.task_id, state), /F2005/);
    assert.equal(
      prepareStateBatch(task.task_id, state, DEFAULT_CONFIG)?.batch_id,
      batch.batch_id,
    );
    const keep = batch.candidate_ids.slice(0, 20);
    state = await store.remain(task, batch, keep, "slide");
    assert.equal(state.facts.length, 1825);
    assert.equal(state.facts[0]?.id, "F1");
    assert.equal(state.facts[20]?.id, "F201");
    assert.equal(state.goal, "goal");
    assert.ok((await readFile(paths.state(task), "utf8")).startsWith(old));
    const version = state.version;
    assert.equal(
      (await store.remain(task, batch, keep, "slide")).version,
      version,
    );
    assert.equal(
      (await store.remain(task, batch, keep, "another-call")).version,
      version,
    );
    await assert.rejects(
      store.remain(task, batch, [], "different-choice"),
      /ALREADY_COMMITTED/,
    );
    assert.deepEqual(await store.read(task), state);
  });
});

test("modify_fact atomically archives active or evicted entries; historical evidence and IDs survive", async (t) => {
  const { paths, task, store } = await fixture(t);
  await withLock(paths.taskLock(task), async () => {
    const config = {
      ...DEFAULT_CONFIG,
      state_max_events: 10,
      state_evict_batch: 2,
    };
    let state = await store.append(
      task,
      items(10),
      "facts",
      100,
      new Set(["U1"]),
    );
    const batch = prepareStateBatch(task.task_id, state, config)!;
    state = await store.remain(task, batch, [], "slide");
    assert.equal(state.facts.length, 8);
    const input = {
      archive: ["F1", "F3"],
      append_fact: {
        content: "corrected",
        evidence: { F1: "historical original", F3: "original" },
      },
    };
    state = await store.modifyFact(task, input, "modify", 100, new Set());
    assert.equal(state.facts.at(-1)?.id, "F11");
    assert.ok(!state.facts.some((f) => f.id === "F3"));
    assert.equal(
      (await store.modifyFact(task, input, "modify", 100, new Set())).version,
      state.version,
    );
    const before = await readFile(paths.state(task), "utf8");
    await assert.rejects(
      store.modifyFact(
        task,
        { ...input, archive: ["F1"] },
        "new-call",
        100,
        new Set(),
      ),
      /ARCHIVED/,
    );
    assert.equal(await readFile(paths.state(task), "utf8"), before);
    state = await store.append(
      task,
      [
        {
          type: "decision",
          content: "new decision",
          evidence: { F1: "archived but genuine source" },
        },
      ],
      "decision",
      100,
      new Set(),
    );
    assert.equal(state.decisions[0]?.id, "D1");
  });
});

test("mixed F/D reminders show boundaries without enumerating candidates; archiving a candidate invalidates old batch", async (t) => {
  const { paths, task, store } = await fixture(t);
  await withLock(paths.taskLock(task), async () => {
    const config = {
      ...DEFAULT_CONFIG,
      state_max_events: 10,
      state_evict_batch: 4,
    };
    let state = await store.append(
      task,
      items(10).map((e, i) => ({
        ...e,
        type: i % 2 ? ("decision" as const) : ("fact" as const),
      })),
      "mixed",
      100,
      new Set(["U1"]),
    );
    const batch = prepareStateBatch(task.task_id, state, config)!;
    const reminder = renderStateReminder(batch, state);
    assert.match(reminder, /F2/);
    assert.match(reminder, /D2/);
    assert.doesNotMatch(reminder, /F1.*D1.*F2.*D2/);
    await store.modifyFact(
      task,
      {
        archive: ["F1"],
        append_fact: { content: "replacement", evidence: { U1: "user" } },
      },
      "modify",
      100,
      new Set(["U1"]),
    );
    const before = await readFile(paths.state(task), "utf8");
    await assert.rejects(store.remain(task, batch, [], "stale"), /STALE/);
    assert.equal(await readFile(paths.state(task), "utf8"), before);
  });
});

test("failed State commit preserves batch identity and reminder; retry commits exactly once", async (t) => {
  const { paths, task, store } = await fixture(t);
  await withLock(paths.taskLock(task), async () => {
    const config = {
      ...DEFAULT_CONFIG,
      state_max_events: 10,
      state_evict_batch: 2,
    };
    const state = await store.append(
      task,
      items(10),
      "facts",
      100,
      new Set(["U1"]),
    );
    const batch = prepareStateBatch(task.task_id, state, config)!;
    const before = await readFile(paths.state(task), "utf8");
    const directory = parentPath(paths.state(task));
    await chmod(directory, 0o500);
    try {
      await assert.rejects(
        store.remain(task, batch, [], "retry"),
        /STATE_WRITE_FAILED/,
      );
    } finally {
      await chmod(directory, 0o700);
    }
    assert.equal(await readFile(paths.state(task), "utf8"), before);
    const restored = await store.read(task);
    assert.equal(
      prepareStateBatch(task.task_id, restored, config)?.batch_id,
      batch.batch_id,
    );
    assert.equal(
      renderStateReminder(batch, restored),
      renderStateReminder(batch, state),
    );
    const committed = await store.remain(task, batch, [], "retry");
    assert.equal(committed.version, state.version + 1);
    assert.equal(
      (await store.remain(task, batch, [], "retry")).version,
      committed.version,
    );
  });
});

test("Goal operations do not consume slots; small windows use the ratio bound and clamp candidate count", async (t) => {
  const { paths, task, store } = await fixture(t);
  await withLock(paths.taskLock(task), async () => {
    await store.updateGoal(
      task,
      {
        goal: "changed",
        summary: "summary",
        keywords: ["goal"],
        evidence: { U1: "user" },
      },
      "goal",
      100,
      new Set(["U1"]),
    );
    let state = await store.append(task, items(1), "one", 100, new Set(["U1"]));
    assert.equal(state.version, 3);
    const config = {
        ...DEFAULT_CONFIG,
        state_max_events: 1,
        state_evict_batch: 200,
      },
      batch = prepareStateBatch(task.task_id, state, config)!;
    assert.equal(batch.candidate_ids.length, 1);
    assert.equal(batch.keep_limit, 0);
    await assert.rejects(
      store.remain(task, batch, ["F1"], "invalid"),
      /KEEP_LIMIT/,
    );
    state = await store.remain(task, batch, [], "empty");
    assert.equal(state.facts.length, 0);
    assert.equal(state.goal, "changed");
    assert.equal(prepareStateBatch(task.task_id, state, config), null);
  });
});

test("atomic correction can archive decisions and facts without reusing either ID sequence", async (t) => {
  const { paths, task, store } = await fixture(t);
  await withLock(paths.taskLock(task), async () => {
    await store.append(
      task,
      [
        { type: "fact", content: "old fact", evidence: { U1: "user" } },
        { type: "decision", content: "old choice", evidence: { U1: "user" } },
      ],
      "initial-pair",
      100,
      new Set(["U1"]),
    );
    let state = await store.modifyFact(
      task,
      {
        archive: ["F1", "D1"],
        append_fact: {
          content: "corrected fact",
          evidence: { F1: "original", D1: "old choice" },
        },
      },
      "modify",
      100,
      new Set(),
    );
    assert.deepEqual(
      state.facts.map((e) => e.id),
      ["F2"],
    );
    assert.equal(state.decisions.length, 0);
    state = await store.append(
      task,
      [
        {
          type: "decision",
          content: "new choice",
          evidence: { D1: "historical choice" },
        },
      ],
      "new-choice",
      100,
      new Set(),
    );
    assert.equal(state.decisions[0]?.id, "D2");
    const previous = await readFile(paths.state(task), "utf8");
    await assert.rejects(
      store.modifyFact(
        task,
        {
          archive: ["F2", "F2"],
          append_fact: { content: "bad", evidence: { U1: "user" } },
        },
        "duplicate",
        100,
        new Set(["U1"]),
      ),
      /INVALID_MODIFY/,
    );
    assert.equal(await readFile(paths.state(task), "utf8"), previous);
  });
});
