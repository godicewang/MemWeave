import { resolve } from "node:path";
import {
  createAgentSessionRuntime,
  createAgentSessionServices,
  createAgentSessionFromServices,
  createCodemodeExtension,
  createToolSearchExtension,
  createMcpExtension,
  getAgentDir,
  SessionManager,
  SettingsManager,
  VERSION,
  type CreateAgentSessionFromServicesOptions,
  type CreateAgentSessionRuntimeFactory,
  type CreateAgentSessionServicesOptions,
  type ExtensionError,
} from "@earendil-works/pi-coding-agent";
import { createMemWeaveExtension } from "../extension/index.js";
import { RequestController, type RequestPipeline } from "./requests.js";
import { isolateCompaction } from "./settings.js";
import { PI_VERSION } from "./version.js";
import { resolveHeadlessProjectTrust } from "./trust.js";

type SessionOptions = Omit<CreateAgentSessionFromServicesOptions, "services" | "sessionManager" | "sessionStartEvent">;
export interface MemWeaveHostOptions<Frame> extends SessionOptions {
  cwd?: string;
  agentDir?: string;
  sessionManager?: SessionManager;
  modelRuntime?: CreateAgentSessionServicesOptions["modelRuntime"];
  resourceLoaderOptions?: CreateAgentSessionServicesOptions["resourceLoaderOptions"];
  resourceLoaderReloadOptions?: CreateAgentSessionServicesOptions["resourceLoaderReloadOptions"];
  settingsManagerFactory?: (cwd: string, agentDir: string) => SettingsManager;
  pipeline?: (target: { cwd: string; sessionManager: SessionManager }) => RequestPipeline<Frame>;
  onExtensionError?: (error: ExtensionError) => void;
}

/** All Session replacements use this same factory; Pi still owns the native agent loop and storage. */
export async function createMemWeaveHost<Frame = unknown>(options: MemWeaveHostOptions<Frame> = {}) {
  if (VERSION !== PI_VERSION) throw new Error(`MemWeave requires Pi ${PI_VERSION}; loaded ${VERSION}.`);
  const cwd = resolve(options.cwd ?? options.sessionManager?.getCwd() ?? process.cwd());
  const agentDir = options.agentDir ? resolve(options.agentDir) : getAgentDir();
  const sessionManager = options.sessionManager ?? SessionManager.create(cwd);
  const createRuntime: CreateAgentSessionRuntimeFactory = async (target) => {
    const report = options.onExtensionError ?? ((error: ExtensionError) => {
      console.error(`[${error.extensionPath}] ${error.event}: ${error.error}`);
    });
    const requests = new RequestController(options.pipeline?.(target));
    const settingsManager = isolateCompaction(
      options.settingsManagerFactory?.(target.cwd, target.agentDir)
      ?? SettingsManager.create(target.cwd, target.agentDir, { projectTrusted: false }),
    );
    const loader = options.resourceLoaderOptions ?? {};
    const services = await createAgentSessionServices({
      cwd: target.cwd, agentDir: target.agentDir, settingsManager,
      ...(options.modelRuntime ? { modelRuntime: options.modelRuntime } : {}),
      resourceLoaderReloadOptions: {
        resolveProjectTrust: ({ extensionsResult }) => resolveHeadlessProjectTrust({
          cwd: target.cwd, agentDir: target.agentDir, settings: settingsManager,
          extensions: extensionsResult, report,
        }),
        ...options.resourceLoaderReloadOptions,
      },
      resourceLoaderOptions: {
        ...loader,
        extensionFactories: [
          { name: "codemode", factory: createCodemodeExtension(), builtin: true, replaceable: true },
          { name: "tool-search", factory: createToolSearchExtension(), builtin: true, replaceable: true },
          { name: "mcp", factory: createMcpExtension(), builtin: true, replaceable: true },
          ...loader.extensionFactories ?? [],
          { name: "memweave", factory: createMemWeaveExtension(requests) },
        ],
      },
    });
    const validateRuntime = () => {
      const errors = services.resourceLoader.getExtensions().errors;
      const diagnostics = services.diagnostics.filter((diagnostic) => diagnostic.type === "error");
      if (errors.length || diagnostics.length) {
        throw new Error("Pi runtime could not load its configured resources:\n" + [
          ...errors.map((error) => `${error.path}: ${error.error}`),
          ...diagnostics.map((diagnostic) => diagnostic.message),
        ].join("\n"));
      }
    };
    validateRuntime();
    const result = await createAgentSessionFromServices({
      services, sessionManager: target.sessionManager,
      ...(target.sessionStartEvent ? { sessionStartEvent: target.sessionStartEvent } : {}),
      ...(options.model ? { model: options.model } : {}),
      ...(options.thinkingLevel ? { thinkingLevel: options.thinkingLevel } : {}),
      ...(options.scopedModels ? { scopedModels: options.scopedModels } : {}),
      ...(options.tools ? { tools: options.tools } : {}),
      ...(options.excludeTools ? { excludeTools: options.excludeTools } : {}),
      ...(options.noTools ? { noTools: options.noTools } : {}),
      ...(options.customTools ? { customTools: options.customTools } : {}),
    });
    requests.install(result.session.agent, validateRuntime);
    try {
      // An error binding also makes native reload emit session_start for a headless host.
      await result.session.bindExtensions({
        mode: "print",
        onError: report,
      });
    } catch (error) {
      try {
        await result.session.abort();
        await result.session.extensionRunner.emit({ type: "session_shutdown", reason: "quit" });
      } finally { result.session.dispose(); }
      throw error;
    }
    return { ...result, services, diagnostics: services.diagnostics };
  };
  const runtime = await createAgentSessionRuntime(createRuntime, { cwd, agentDir, sessionManager });
  const dispose = runtime.dispose.bind(runtime);
  let disposal: Promise<void> | undefined;
  runtime.dispose = () => disposal ??= (async () => {
    await runtime.session.abort();
    await dispose();
  })();
  return runtime;
}
