import assert from "node:assert/strict";
import { mkdtemp, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { memoryPaths } from "../../src/storage/paths.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { nativeSession } from "../fixtures/native-session.ts";

test("Pi native loader executes formal Task/State modules using host SDK and typebox", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-task-loaded-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root);
  await writeFile(paths.config, JSON.stringify(DEFAULT_CONFIG));
  await writeFile(
    paths.rule,
    await readFile(new URL("../../resources/rule.md", import.meta.url)),
  );
  const entry = join(root, "extension.ts");
  await writeFile(
    entry,
    `
 import {registerMemweave} from ${JSON.stringify(fileURLToPath(new URL("../../src/extension/register.ts", import.meta.url)))};
 import {memoryPaths} from ${JSON.stringify(fileURLToPath(new URL("../../src/storage/paths.ts", import.meta.url)))};
 export default pi=>registerMemweave(pi,{paths:memoryPaths(${JSON.stringify(root)}),verifyCapacity:async model=>model.contextWindow});
 `,
  );
  const h = await nativeSession(t, [], false, 512, [entry]);
  const views: string[] = [];
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("task_create", {
        title: "Loaded Task",
        goal: "Verify native loader",
        project_name: "MemWeave",
        summary: "Native package verification",
        keywords: ["loader"],
      }),
    ]),
    (context) => {
      views.push(JSON.stringify(context.messages));
      return fauxAssistantMessage([
        fauxToolCall("state_append", {
          items: [
            {
              type: "fact",
              content: "User requests loader verification",
              evidence: { U1: "user" },
            },
          ],
        }),
      ]);
    },
    (context) => {
      views.push(JSON.stringify(context.messages));
      return fauxAssistantMessage("done");
    },
  ]);
  await h.session.prompt("Verify the actual loaded extension");
  assert.equal(h.faux.state.callCount, 3);
  assert.deepEqual(h.errors, []);
  const tasks = JSON.parse(await readFile(paths.index, "utf8")) as Array<{
    task_id: string;
    workspace: string;
    state_version: number;
  }>;
  assert.equal(tasks[0]?.state_version, 2);
  assert.match(views[0] ?? "", /\[U1\]/);
  assert.match(views[1] ?? "", /F1 User requests loader verification/);
  assert.doesNotMatch(
    await readFile(h.manager.getSessionFile()!, "utf8"),
    /# Symbolic State/,
  );
  const task = tasks[0]!;
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("update_goal", {
        goal: "Updated native Goal",
        summary: "Updated loader verification",
        keywords: ["updated"],
        evidence: { U2: "user adjustment" },
      }),
    ]),
    fauxAssistantMessage([
      fauxToolCall("modify_fact", {
        archive: ["F1"],
        append_fact: {
          content: "Corrected loader fact",
          evidence: { U2: "user requests correction" },
        },
      }),
    ]),
    fauxAssistantMessage([
      fauxToolCall("state_read", { task_id: task.task_id }),
    ]),
    fauxAssistantMessage("all modules loaded"),
  ]);
  await h.session.prompt(
    "Adjust Goal and correct the existing loader fact, then read State",
  );
  assert.deepEqual(h.errors, []);
  const updated = JSON.parse(await readFile(paths.index, "utf8")) as Array<{
    state_version: number;
    summary: string;
  }>;
  assert.equal(updated[0]?.state_version, 4);
  assert.equal(updated[0]?.summary, "Updated loader verification");
  await writeFile(
    paths.config,
    JSON.stringify({
      ...DEFAULT_CONFIG,
      state_max_events: 1,
      state_evict_batch: 1,
    }),
  );
  h.faux.setResponses([
    fauxAssistantMessage([fauxToolCall("state_remain", { event_ids: [] })]),
    fauxAssistantMessage("native batch handled"),
  ]);
  await h.session.prompt(
    "Handle the prepared State batch without retaining entries",
  );
  assert.deepEqual(h.errors, []);
  const finalIndex = JSON.parse(await readFile(paths.index, "utf8")) as Array<{
    state_version: number;
  }>;
  assert.equal(finalIndex[0]?.state_version, 5);
});
