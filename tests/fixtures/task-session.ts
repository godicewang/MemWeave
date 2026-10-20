import { mkdtemp, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { TestContext } from "node:test";
import type {
  ExtensionAPI,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { registerMemweave } from "../../src/extension/register.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { memoryPaths, type MemoryPaths } from "../../src/storage/paths.ts";
import type { TaskService } from "../../src/task/service.ts";
import type { RequestMessages } from "../../src/pi/request-lifecycle.ts";
import type { CapacityVerifier } from "../../src/pi/model-capacity.ts";
import { nativeSession } from "./native-session.ts";
export async function taskSession(
  t: TestContext,
  options: {
    paths?: MemoryPaths;
    manager?: SessionManager;
    extra?: (pi: ExtensionAPI) => void;
    verifyCapacity?: CapacityVerifier;
  } = {},
) {
  const root = await mkdtemp(join(tmpdir(), "memweave-task-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = options.paths ?? memoryPaths(root);
  if (!options.paths) {
    await writeFile(paths.config, JSON.stringify(DEFAULT_CONFIG));
    await writeFile(
      paths.rule,
      await readFile(new URL("../../resources/rule.md", import.meta.url)),
    );
  }
  let tasks!: TaskService;
  const frames: RequestMessages[] = [],
    diagnostics: string[] = [];
  const h = await nativeSession(
    t,
    [
      (pi) => {
        tasks = registerMemweave(pi, {
          paths,
          verifyCapacity:
            options.verifyCapacity ?? (async (model) => model.contextWindow),
          observe: (messages) => {
            frames.push(structuredClone(messages));
          },
          report: (error) => {
            diagnostics.push(error instanceof Error ? error.message : "ERROR");
          },
        });
        options.extra?.(pi);
      },
    ],
    false,
    512,
    [],
    options.manager,
  );
  return {
    ...h,
    paths,
    get tasks() {
      return tasks;
    },
    frames,
    diagnostics,
  };
}
