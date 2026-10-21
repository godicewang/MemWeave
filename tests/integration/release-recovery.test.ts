import assert from "node:assert/strict";
import { readFile, rm } from "node:fs/promises";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import test from "node:test";
import {
  releaseFixture,
  releaseWorker,
  repository,
  sourceArtifact,
} from "../fixtures/release.ts";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
test(
  "a previous release creates real Task data; an independent upgraded Pi process restores State, originals and Window",
  { timeout: 60000 },
  async (t) => {
    const h = await releaseFixture(t),
      old = await sourceArtifact(h.root, "9868254");
    const a = await releaseWorker({
      ...h.base,
      artifact: old,
      action: "create",
      label: "before",
    });
    assert.equal(a.version, 2);
    assert.equal(a.window, false);
    const task = (
      JSON.parse(await readFile(h.paths.index, "utf8")) as {
        task_id: string;
        workspace: string;
      }[]
    )[0]!;
    const before = await readFile(h.paths.state(task));
    const original = SessionManager.open(a.sessionFile)
      .getBranch()
      .filter((e) => e.type === "message");
    await rm(h.paths.view(task));
    const b = await releaseWorker({
      ...h.base,
      artifact: repository,
      action: "recover",
      label: "after",
      sessionFile: a.sessionFile,
    });
    assert.equal(b.taskId, a.taskId);
    assert.equal(b.version, 3);
    assert.equal(b.window, true);
    assert.equal(b.settings, 4);
    const state = await readFile(h.paths.state(task));
    assert.ok(state.subarray(0, before.length).equals(before));
    assert.match(
      await readFile(h.paths.view(task), "utf8"),
      /Source user requested release recovery verification/,
    );
    const restored = SessionManager.open(b.sessionFile).getBranch();
    for (const entry of original)
      assert.deepEqual(
        restored.find((e) => e.id === entry.id),
        entry,
      );
  },
);
test(
  "two independent native Pi processes share Task cognition while keeping Window settings and Session scopes separate",
  { timeout: 60000 },
  async (t) => {
    const h = await releaseFixture(t),
      a = await releaseWorker({
        ...h.base,
        artifact: repository,
        action: "create",
        label: "seed",
      });
    const [b, c] = await Promise.all([
      releaseWorker({
        ...h.base,
        artifact: repository,
        action: "concurrent",
        label: "worker-b",
        taskId: a.taskId,
        turns: 8,
      }),
      releaseWorker({
        ...h.base,
        artifact: repository,
        action: "concurrent",
        label: "worker-c",
        taskId: a.taskId,
        turns: 12,
      }),
    ]);
    assert.equal(b.settings, 8);
    assert.equal(c.settings, 12);
    assert.notEqual(b.sessionFile, c.sessionFile);
    const task = (
      JSON.parse(await readFile(h.paths.index, "utf8")) as {
        task_id: string;
        workspace: string;
        sessions: unknown[];
      }[]
    )[0]!;
    const state = await readFile(h.paths.state(task), "utf8");
    assert.equal(state.trimEnd().split("\n").length, 4);
    assert.match(state, /worker-b concurrent observation/);
    assert.match(state, /worker-c concurrent observation/);
    assert.equal(task.sessions.length, 3);
    assert.equal(
      JSON.parse(await readFile(h.paths.config, "utf8")).recent_turns,
      6,
    );
  },
);
test(
  "SIGKILL leaves a diagnosed lock; installed Runtime neither steals it nor advances State, then resumes after explicit repair",
  { timeout: 60000 },
  async (t) => {
    const h = await releaseFixture(t),
      a = await releaseWorker({
        ...h.base,
        artifact: repository,
        action: "create",
        label: "seed",
      });
    const task = (
      JSON.parse(await readFile(h.paths.index, "utf8")) as {
        task_id: string;
        workspace: string;
      }[]
    )[0]!;
    const bytes = await readFile(h.paths.state(task)),
      lock = h.paths.taskLock(task);
    const owner = spawn(
      process.execPath,
      [
        fileURLToPath(new URL("../fixtures/lock-worker.ts", import.meta.url)),
        lock,
      ],
      { stdio: ["ignore", "pipe", "pipe"] },
    );
    t.after(() => {
      if (owner.exitCode === null && owner.signalCode === null)
        owner.kill("SIGKILL");
    });
    await new Promise<void>((resolve, reject) => {
      owner.stdout.on("data", (chunk) => {
        if (String(chunk).includes("LOCK_READY")) resolve();
      });
      owner.on("error", reject);
      owner.on("exit", () => reject(Error("lock fixture exited before ready")));
    });
    owner.kill("SIGKILL");
    await once(owner, "exit");
    const blocked = await releaseWorker({
      ...h.base,
      artifact: repository,
      action: "blocked",
      label: "blocked",
      sessionFile: a.sessionFile,
    });
    assert.equal(blocked.requests, 0);
    assert.equal(blocked.version, 2);
    assert.ok(bytes.equals(await readFile(h.paths.state(task))));
    assert.equal(await readFile(`${lock}/owner`, "utf8"), String(owner.pid));
    assert.throws(() => process.kill(owner.pid!, 0));
    await rm(lock, { recursive: true }); // Explicit repair, confined to this disposable fixture.
    const restored = await releaseWorker({
      ...h.base,
      artifact: repository,
      action: "recover",
      label: "repaired",
      sessionFile: a.sessionFile,
    });
    assert.equal(restored.version, 3);
    assert.ok(restored.requests > 0);
  },
);
