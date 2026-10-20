import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { getCurrentSystemPrompt } from "@earendil-works/pi-ai";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import { nativeSession } from "../fixtures/native-session.ts";

test("Pi 原生扩展加载器实际执行正式模块：schema、system 重放及热读取可用", async t => {
  const root = await mkdtemp(join(tmpdir(), "memweave-loaded-rule-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root);
  await writeFile(paths.config, JSON.stringify(DEFAULT_CONFIG));
  await writeFile(paths.rule, await readFile(new URL("../../resources/rule.md", import.meta.url)));
  const entry = join(root, "extension.ts");
  const source = (name: string) => JSON.stringify(fileURLToPath(new URL(`../../src/pi/${name}.ts`, import.meta.url)));
  // Only the composition/known test capacity differs; Pi's loader evaluates every production module.
  await writeFile(entry, `
    import {registerRequestLifecycle} from ${source("request-lifecycle")};
    import {createRuleRequestServices} from ${source("rule-services")};
    export default function(pi) {
      registerRequestLifecycle(pi, createRuleRequestServices({
        paths: ${JSON.stringify(paths)}, verifyCapacity: async model => model.contextWindow,
      }));
    }
  `);
  const h = await nativeSession(t, [], false, 512, [entry]);
  const prompts: string[] = [];
  for (const recent_turns of [200, 240]) {
    await writeFile(paths.config, JSON.stringify({ ...DEFAULT_CONFIG, recent_turns }));
    h.faux.setResponses([context => {
      prompts.push(getCurrentSystemPrompt(context.messages));
      return fauxAssistantMessage("OK");
    }]);
    await h.session.prompt("loaded module request");
  }
  assert.equal(h.faux.state.callCount, 2); assert.equal(prompts.length, 2);
  assert.match(prompts[0] ?? "", /200/); assert.match(prompts[1] ?? "", /240/);
  for (const prompt of prompts) {
    assert.match(prompt, /NATIVE_SYSTEM/); assert.match(prompt, /NATIVE_APPEND \{\{untouched\}\}/);
    assert.equal(prompt.split("<pi_long_task_rule>").length - 1, 1);
  }
  assert.deepEqual(h.errors, []);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /pi_long_task_rule/);
});
