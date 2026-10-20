import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { registerRequestLifecycle } from "../../src/pi/request-lifecycle.ts";
import { createRuleRequestServices, type RuleServiceOptions } from "../../src/pi/rule-services.ts";
import type { PreparedRule } from "../../src/rule/prepare.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import { nativeSession } from "./native-session.ts";

export async function ruleSession(t: TestContext, register?: (pi: ExtensionAPI) => void, options: RuleServiceOptions = {}) {
  const frames: PreparedRule[] = [];
  const diagnostics: string[] = [];
  let services: ReturnType<typeof createRuleRequestServices>;
  const h = await nativeSession(t, [pi => {
    registerRequestLifecycle(pi, {
      prepare: (messages, ctx) => services.prepare(messages, ctx),
      report: error => { diagnostics.push(error instanceof Error ? error.message : "UNKNOWN"); },
    });
    register?.(pi);
  }]);
  const paths = options.paths ?? memoryPaths(join(h.root, "memory"));
  if (!options.paths) {
    await mkdir(paths.root);
    await writeFile(paths.config, JSON.stringify(DEFAULT_CONFIG));
    await writeFile(paths.rule, await readFile(new URL("../../resources/rule.md", import.meta.url)));
  }
  services = createRuleRequestServices({
    paths,
    verifyCapacity: async model => model.contextWindow,
    ...options,
    afterRule: async (prepared, ctx) => {
      frames.push(prepared);
      return options.afterRule ? options.afterRule(prepared, ctx) : prepared.messages;
    },
  });
  return { ...h, paths, frames, diagnostics };
}
