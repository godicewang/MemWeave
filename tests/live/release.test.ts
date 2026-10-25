import assert from "node:assert/strict";
import { access, readFile, rm } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  packArtifact,
  releaseFixture,
  releaseWorker,
  unpackArtifact,
} from "../fixtures/release.ts";

test(
  "real DeepSeek: npm artifact recovers persisted cognition and reads source after process restart",
  { timeout: 120_000 },
  async (t) => {
    const f = await releaseFixture(t),
      authPath = join(
        homedir(),
        ".local/share/memweave-dev/pi-agent/auth.json",
      );
    const authBefore = await readFile(authPath);
    t.after(async () => assert.ok(authBefore.equals(await readFile(authPath))));
    const artifact = await unpackArtifact(f.root, await packArtifact(f.root));
    const before = await releaseWorker({
      ...f.base,
      artifact,
      action: "create",
      label: "artifact-before",
    });
    const task = JSON.parse(await readFile(f.paths.index, "utf8"))[0],
      stateBefore = await readFile(f.paths.state(task), "utf8");
    const messagesBefore = (await readFile(before.sessionFile, "utf8"))
      .trimEnd()
      .split("\n")
      .map((line) => JSON.parse(line))
      .filter((entry) => entry.type === "message");
    await rm(f.paths.view(task));
    const after = await releaseWorker({
      ...f.base,
      artifact,
      sessionFile: before.sessionFile,
      taskId: before.taskId,
      action: "live",
      authPath,
      label: "artifact-live",
    });
    assert.equal(after.version, 3);
    assert.match(await readFile(f.paths.state(task), "utf8"), /GATE_artifact-live/);
    assert.ok(after.toolNames.includes("memory_read"));
    assert.ok(after.toolNames.includes("state_append"));
    assert.ok(
      (await readFile(f.paths.state(task), "utf8")).startsWith(stateBefore),
    );
    await access(f.paths.view(task));
    const messagesAfter = (await readFile(before.sessionFile, "utf8"))
      .trimEnd()
      .split("\n")
      .map((line) => JSON.parse(line))
      .filter((entry) => entry.type === "message");
    assert.deepEqual(
      messagesAfter.slice(0, messagesBefore.length),
      messagesBefore,
    );
    t.diagnostic(
      `Unpacked npm artifact, disk restart, source read and State append: ${after.requests} real DeepSeek requests; bootstrap used 3 local HTTP requests separately`,
    );
  },
);
