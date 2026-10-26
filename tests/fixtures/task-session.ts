import { mkdtemp, writeFile, readFile, rm, mkdir, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { TestContext } from "node:test";
import type {
  ExtensionAPI,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { registerMemweave } from "../../src/extension/register.ts";
import { registerLauncher } from "../../src/extension/launcher.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { memoryPaths, parentPath, type MemoryPaths } from "../../src/storage/paths.ts";
import { TaskService } from "../../src/task/service.ts";
import type { RequestMessages } from "../../src/pi/request-lifecycle.ts";
import type { CapacityVerifier } from "../../src/pi/model-capacity.ts";
import { nativeSession } from "./native-session.ts";
import type { Embedder } from "../../src/task/embedding.ts";
import { imageReserve } from "../../src/pi/window-budget.ts";
import type { WindowBudget } from "../../src/pi/window-service.ts";
export async function taskSession(
  t: TestContext,
  options: {
    paths?: MemoryPaths;
    manager?: SessionManager;
    extra?: (pi: ExtensionAPI) => void;
    verifyCapacity?: CapacityVerifier;
    fullEnvironment?: boolean;
    embedder?: Embedder;
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
  const models=process.env.MEMWEAVE_EMBEDDING_MODELS;
  if(options.fullEnvironment&&models){
    await mkdir(parentPath(paths.models),{recursive:true});
    try{await symlink(models,paths.models,"dir");}catch(error){if((error as NodeJS.ErrnoException).code!=="EEXIST")throw error;}
  }
  let tasks!: TaskService;
  const frames: RequestMessages[] = [],
    budgets: WindowBudget[] = [],
    diagnostics: string[] = [];
  const h = await nativeSession(
    t,
    [
      (pi) => {
        const runtimeOptions = {
          paths,
          ...(!options.fullEnvironment || options.embedder ? {embedder:options.embedder??(async(texts:string[])=>({vectors:texts.map(text=>{const v=Array<number>(384).fill(0);for(const c of text)v[c.codePointAt(0)!%384]!+=1;return v;}),truncated:texts.map(()=>false)}))} : {}),
          imageCost: (model, image) =>
            model.provider === "memweave-test"
              ? 2048
              : imageReserve(model, image),
          observeBudget: (budget) => {
            budgets.push(budget);
          },
          verifyCapacity:
            options.verifyCapacity ?? (async (model) => model.contextWindow),
          observe: (messages) => {
            frames.push(structuredClone(messages));
          },
          report: (error) => {
            diagnostics.push(error instanceof Error ? error.message : "ERROR");
          },
        } satisfies Parameters<typeof registerMemweave>[1];
        if (options.fullEnvironment) {
          // Read-only test inspection; business calls run in the production launcher runtime.
          tasks = new TaskService(paths, pi);
          registerLauncher(pi, { ...runtimeOptions, setupAgentDir: join(root, "agent") });
          let registered = false;
          pi.on("session_start", () => {
            if (!registered) { registered = true; options.extra?.(pi); }
          });
        } else {
          tasks = registerMemweave(pi, runtimeOptions);
          options.extra?.(pi);
        }
      },
    ],
    false,
    512,
    [],
    options.manager,
    options.fullEnvironment ?? false,
  );
  return {
    ...h,
    paths,
    get tasks() {
      return tasks;
    },
    frames,
    budgets,
    diagnostics,
  };
}
