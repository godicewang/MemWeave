import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { StateStore } from "../../src/state/store.ts";
import { SnapshotCache, stateSnapshot } from "../../src/state/snapshot-cache.ts";
import { reduceState } from "../../src/state/model.ts";
import { atomicWrite, withLock } from "../../src/storage/files.ts";
import { memoryPaths } from "../../src/storage/paths.ts";

test("State cache checks actual files, isolates all mutable results and detects replacement/corruption", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-state-cache-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root), a = new StateStore(paths), b = new StateStore(paths);
  const task = { workspace: "test", task_id: "task_cache" }, file = paths.state(task);
  await a.initialize(task, "goal", "init");
  const item = { type: "fact" as const, content: "fact", evidence: { U1: "user" } };
  await a.append(task, [item], "one", 100, new Set(["U1"]));
  item.evidence.U1 = "caller changed";
  const returned = await a.read(task);
  returned.entries.get("F1")!.evidence.U1 = "changed";
  returned.events[0]!.op_id = "changed";
  returned.events.push(returned.events[0]!);
  returned.facts[0]!.archived = true;
  assert.deepEqual(await a.read(task), await b.read(task));
  const original = await readFile(file, "utf8");
  await withLock(paths.taskLock(task), () => b.append(task, [{ ...item, evidence: { U1: "user" } }], "two", 100, new Set(["U1"])));
  assert.equal((await a.read(task)).version, 3);
  const prefixChanged = original.replace('"goal":"goal"', '"goal":"else"');
  await atomicWrite(file, prefixChanged);
  assert.equal((await a.read(task)).goal, "else");
  await atomicWrite(file, original.split("\n")[0]! + "\n");
  assert.equal((await a.read(task)).version, 1);
  for (const bad of [original.slice(0, -1), original + "bad\n", original + "\n" + original.split("\n")[0]! + "\n"]) {
    await atomicWrite(file, bad);
    await assert.rejects(a.read(task), /CORRUPT_STATE/);
  }
  // Original parser accepts trailing whitespace, but never an empty interior record.
  await atomicWrite(file, original + "\n");
  assert.equal((await a.read(task)).version, 2);
  const external = await b.initialize(task, "unused", "init");
  assert.equal(external.version, 2);
  await atomicWrite(file, original + "\n" + original.split("\n")[0]! + "\n");
  await assert.rejects(a.read(task), /CORRUPT_STATE/);
  await atomicWrite(file, original);
  await writeFile(file, Buffer.from([0xff]));
  await assert.rejects(a.read(task));
  await rm(file);
  await assert.rejects(a.read(task), /STATE_MISSING/);
  await atomicWrite(file, original);
  assert.deepEqual(await a.read(task), reduceState(original.trimEnd().split("\n").map((line) => JSON.parse(line))));
});
test("guard failure/mutation cannot poison cache; retries still compare committed inputs", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-state-guard-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root), store = new StateStore(paths), task = { workspace: "test", task_id: "task_guard" };
  await store.initialize(task, "goal", "init");
  const item = { type: "fact" as const, content: "fact", evidence: { U1: "user" } }, before = await readFile(paths.state(task), "utf8");
  await assert.rejects(store.append(task, [item], "one", 100, new Set(["U1"]), (_task, next, previous) => {
    next.events[0]!.op_id = "poison";
    previous!.goal = "poison";
    throw Error("guard rejected");
  }), /guard rejected/);
  assert.equal(await readFile(paths.state(task), "utf8"), before);
  assert.equal((await store.read(task)).goal, "goal");
  const success = await store.append(task, [item], "one", 100, new Set(["U1"]));
  success.events[1]!.op_id = "caller changed";
  assert.equal((await store.append(task, [item], "one", 100, new Set(["U1"]))).version, 2);
  await assert.rejects(store.append(task, [{ ...item, content: "different" }], "one", 100, new Set(["U1"])), /OPERATION_INPUT_MISMATCH/);
});
test("snapshot cache is bounded by LRU count and estimated bytes, and skips oversized entries", () => {
  const event = { op: "update_goal" as const, op_id: "init", time: "t", goal: "g", evidence: {} };
  const snapshot = stateSnapshot(JSON.stringify(event) + "\n", reduceState([event]));
  const cache = new SnapshotCache(2, snapshot.estimatedBytes * 2);
  cache.set("a", snapshot); cache.set("b", snapshot);
  assert.equal(cache.get("a"), snapshot);
  cache.set("c", snapshot);
  assert.equal(cache.get("b"), undefined);
  assert.equal(cache.size, 2);
  assert.equal(cache.bytes, snapshot.estimatedBytes * 2);
  cache.set("big", { ...snapshot, estimatedBytes: snapshot.estimatedBytes * 3 });
  assert.equal(cache.get("big"), undefined);
  assert.equal(cache.size, 2);
  cache.delete("a"); cache.delete("c");
  assert.equal(cache.bytes, 0);
  const bytesOnly = new SnapshotCache(4, snapshot.estimatedBytes * 2);
  bytesOnly.set("a", snapshot); bytesOnly.set("b", snapshot); bytesOnly.set("c", snapshot);
  assert.equal(bytesOnly.size, 2);
  assert.equal(bytesOnly.get("a"), undefined);
});
test("failed State replacement invalidates cache; caller mutation during guard cannot diverge file and cached result", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-state-failure-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root), store = new StateStore(paths), task = { workspace: "test", task_id: "task_write_failure" };
  await store.initialize(task, "goal", "init");
  const file = paths.state(task), before = await readFile(file, "utf8");
  const item = { type: "fact" as const, content: "fact", evidence: { U1: "original" } };
  await assert.rejects(store.append(task, [item], "one", 100, new Set(["U1"]), async () => {
    await rm(file);
    await mkdir(file);
  }), /STATE_WRITE_FAILED/);
  await assert.rejects(store.read(task));
  await rm(file, { recursive: true });
  await atomicWrite(file, before);
  await store.append(task, [item], "one", 100, new Set(["U1"]), () => {
    item.evidence.U1 = "changed externally";
  });
  const disk = await new StateStore(paths).read(task), cached = await store.read(task);
  assert.deepEqual(cached, disk);
  assert.equal(cached.facts[0]!.evidence.U1, "original");
});
