import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { getCurrentSystemMessage, getSystemMessageText, Type } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, ProjectTrustStore, SessionManager, SettingsManager, type ExtensionFactory } from "@earendil-works/pi-coding-agent";
import { afterEach, describe, expect, it } from "vitest";
import { createMemWeaveHost, type RequestPipeline } from "../../src/pi/index.js";
import { temporaryWorkspace } from "../fixtures/workspace.js";
import { assistant, fakeProvider } from "../fixtures/provider.js";

const cleanup: Array<() => Promise<void>> = [];
afterEach(async () => {
  const errors: unknown[] = [];
  for (const remove of cleanup.splice(0).reverse()) {
    try { await remove(); } catch (error) { errors.push(error); }
  }
  if (errors.length) throw new AggregateError(errors, "Fixture cleanup failed");
});
const identity: RequestPipeline<null> = {
  async prepare(request) { return { frame: null, messages: request.context.messages }; },
  async transform(messages) { return messages; },
};

async function fixture(pipeline: () => RequestPipeline<null> = () => identity, extensions: ExtensionFactory[] = []) {
  const workspace = await temporaryWorkspace();
  cleanup.push(workspace.cleanup);
  const provider = await fakeProvider();
  const host = await createMemWeaveHost({
    ...workspace, ...provider, pipeline,
    sessionManager: SessionManager.inMemory(workspace.cwd),
    resourceLoaderOptions: { extensionFactories: extensions },
  });
  cleanup.push(() => host.dispose());
  return { workspace, provider, host };
}

describe("native Pi host integration", () => {
  it("uses an explicitly supplied SessionManager's cwd for initial resource discovery", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const provider = await fakeProvider();
    const host = await createMemWeaveHost({ ...provider, agentDir: workspace.agentDir, pipeline: () => identity,
      sessionManager: SessionManager.inMemory(workspace.cwd) });
    cleanup.push(() => host.dispose());
    expect(host.cwd).toBe(workspace.cwd);
  });

  it("reports extension load failures instead of silently starting without them", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const provider = await fakeProvider();
    await expect(createMemWeaveHost({ ...workspace, ...provider, pipeline: () => identity,
      sessionManager: SessionManager.inMemory(workspace.cwd),
      resourceLoaderOptions: { extensionFactories: [() => { throw new Error("extension-load-fixture"); }] },
    })).rejects.toThrow(/extension-load-fixture/);
    expect(provider.calls).toHaveLength(0);
  });

  it("blocks a request if an extension fails during resource reload", async () => {
    let broken = false;
    const { host, provider } = await fixture(() => identity, [() => {
      if (broken) throw new Error("reload-load-fixture");
    }]);
    await host.session.prompt("before reload");
    broken = true;
    await host.session.reload();
    await host.session.prompt("after failed reload");
    expect(provider.calls).toHaveLength(1);
    expect(host.session.agent.state.errorMessage).toContain("reload-load-fixture");
  });

  it("refuses to send without a configured request pipeline", async () => {
    const { host, provider } = await fixture();
    await host.session.prompt("native loop");
    expect(provider.calls).toHaveLength(1);
    // A new host cannot implicitly opt into an unprepared, bare Pi request.
    const blocked = await createMemWeaveHost({
      cwd: host.cwd, agentDir: host.services.agentDir, modelRuntime: provider.modelRuntime,
      model: provider.model, sessionManager: SessionManager.inMemory(host.cwd),
    });
    cleanup.push(() => blocked.dispose());
    await blocked.session.prompt("must not send");
    expect(provider.calls).toHaveLength(1);
    expect(blocked.session.agent.state.errorMessage).toMatch(/pipeline/i);
  });

  it.each(["prepare", "transform"] as const)("blocks %s failures and clears the previous successful frame", async (failure) => {
    let fail = false;
    const { host, provider } = await fixture(() => ({
      async prepare(request) {
        if (fail && failure === "prepare") throw new Error("invalid rule fixture");
        return identity.prepare(request);
      },
      async transform(messages) {
        if (fail && failure === "transform") throw new Error("budget fixture exceeded");
        return messages;
      },
    }));
    await host.session.prompt("success");
    fail = true;
    await host.session.prompt("failure");
    expect(provider.calls).toHaveLength(1);
    expect(host.session.agent.state.errorMessage).toMatch(/fixture/);
    fail = false;
    await host.session.prompt("recovered");
    expect(provider.calls).toHaveLength(2);
  });

  it("rejects changes made after its final assembled context", async () => {
    const late: ExtensionFactory = (pi) => {
      pi.on("context_with_system", (event) => ({ messages: [...event.messages,
        { role: "user", content: "unbudgeted", timestamp: Date.now() }] }));
    };
    const { host, provider } = await fixture(() => identity, [late]);
    await host.session.prompt("should block");
    expect(provider.calls).toHaveLength(0);
    expect(host.session.agent.state.errorMessage).toMatch(/after.*assembl/i);
  });

  it("keeps injected request content out of the Session, including after reload/new/resume", async () => {
    let requests = 0;
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const provider = await fakeProvider();
    const host = await createMemWeaveHost({
      ...workspace, ...provider,
      sessionManager: SessionManager.create(workspace.cwd, join(workspace.root, "sessions")),
      pipeline: () => ({
        async prepare(request) { requests++; return { frame: null, messages: request.context.messages }; },
        async transform(messages) { return [...messages, { role: "custom", customType: "fixture-state",
          content: "transient-state-fixture", display: false, timestamp: Date.now() }]; },
      }),
    });
    cleanup.push(() => host.dispose());
    await host.session.prompt("one");
    const saved = host.session.sessionFile;
    expect(saved).toBeTruthy();
    await host.session.reload();
    await host.session.prompt("two");
    await host.newSession();
    expect(host.session.autoCompactionEnabled).toBe(false);
    await host.session.prompt("three");
    await host.switchSession(saved!);
    await host.session.prompt("four");
    expect(requests).toBe(4);
    expect(provider.calls).toHaveLength(4);
    expect(await readFile(saved!, "utf8")).not.toContain("transient-state-fixture");
    expect(provider.calls.every((call) => JSON.stringify(call).includes("transient-state-fixture"))).toBe(true);
  });

  it("cancels manual compaction and never changes shared compaction settings", async () => {
    const { host, workspace, provider } = await fixture();
    const path = join(workspace.agentDir, "settings.json");
    const before = await readFile(path, "utf8");
    await host.session.prompt("seed " + "history ".repeat(2000));
    await host.session.prompt("recent " + "current ".repeat(1000));
    await expect(host.session.compact()).rejects.toThrow(/cancel/i);
    expect(() => host.session.setAutoCompactionEnabled(true)).toThrow(/compaction/i);
    await host.session.settingsManager.flush();
    expect(await readFile(path, "utf8")).toBe(before);
    expect(SettingsManager.create(workspace.cwd, workspace.agentDir).getCompactionEnabled()).toBe(true);
    expect(provider.calls).toHaveLength(2);
    expect(host.session.sessionManager.getEntries().some((entry) => entry.type === "compaction")).toBe(false);
  });

  it("preserves native SYSTEM/APPEND priority and user placeholders across reload", async () => {
    const { workspace, provider, host } = await fixture();
    await writeFile(join(workspace.agentDir, "SYSTEM.md"), "global-role-fixture");
    await writeFile(join(workspace.agentDir, "APPEND_SYSTEM.md"), "global-append-{{untouched}}");
    await host.session.reload();
    await host.session.prompt("one");
    const first = getCurrentSystemMessage(provider.calls[0]!.messages);
    expect(first && getSystemMessageText(first)).toContain("global-role-fixture");
    expect(first && getSystemMessageText(first)).toContain("global-append-{{untouched}}");
    expect(await readFile(join(workspace.agentDir, "APPEND_SYSTEM.md"), "utf8")).toBe("global-append-{{untouched}}");
    await writeFile(join(workspace.cwd, ".pi/SYSTEM.md"), "project-role-fixture");
    await writeFile(join(workspace.cwd, ".pi/APPEND_SYSTEM.md"), "project-append-fixture");
    const trust = new ProjectTrustStore(workspace.agentDir);
    trust.set(workspace.cwd, true);
    await host.session.reload();
    await host.session.prompt("trusted project");
    const trusted = getCurrentSystemMessage(provider.calls[1]!.messages);
    expect(trusted && getSystemMessageText(trusted)).toContain("project-role-fixture");
    expect(trusted && getSystemMessageText(trusted)).toContain("project-append-fixture");
    expect(trusted && getSystemMessageText(trusted)).not.toContain("global-role-fixture");
    trust.set(workspace.cwd, false);
    await host.newSession();
    await host.session.prompt("untrusted project");
    const untrusted = getCurrentSystemMessage(provider.calls[2]!.messages);
    expect(untrusted && getSystemMessageText(untrusted)).toContain("global-role-fixture");
    expect(untrusted && getSystemMessageText(untrusted)).not.toContain("project-append-fixture");
  });

  it("respects a global project_trust extension before saved trust decisions", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    await writeFile(join(workspace.cwd, ".pi/APPEND_SYSTEM.md"), "trusted-by-extension");
    new ProjectTrustStore(workspace.agentDir).set(workspace.cwd, false);
    const provider = await fakeProvider();
    const host = await createMemWeaveHost({ ...workspace, ...provider, pipeline: () => identity,
      sessionManager: SessionManager.inMemory(workspace.cwd),
      resourceLoaderOptions: { extensionFactories: [(pi) => {
        pi.on("project_trust", () => ({ trusted: "yes", remember: false }));
      }] },
    });
    cleanup.push(() => host.dispose());
    await host.session.prompt("trust extension fixture");
    expect(JSON.stringify(provider.calls)).toContain("trusted-by-extension");
    expect(new ProjectTrustStore(workspace.agentDir).get(workspace.cwd)).toBe(false);
  });

  it.each(["ask", "always", "never"] as const)("preserves the headless %s trust policy for unknown projects", async (policy) => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const settingsPath = join(workspace.agentDir, "settings.json");
    const settings = JSON.parse(await readFile(settingsPath, "utf8")) as Record<string, unknown>;
    settings.defaultProjectTrust = policy;
    await writeFile(settingsPath, JSON.stringify(settings));
    await writeFile(join(workspace.cwd, ".pi/APPEND_SYSTEM.md"), "unknown-project-fixture");
    const provider = await fakeProvider();
    const host = await createMemWeaveHost({ ...workspace, ...provider, pipeline: () => identity,
      sessionManager: SessionManager.inMemory(workspace.cwd) });
    cleanup.push(() => host.dispose());
    await host.session.prompt("headless trust fixture");
    expect(JSON.stringify(provider.calls).includes("unknown-project-fixture")).toBe(policy === "always");
    expect(new ProjectTrustStore(workspace.agentDir).get(workspace.cwd)).toBeNull();
  });

  it("does not share prepared frames between concurrently running hosts", async () => {
    const one = await fixture(() => ({ ...identity,
      async transform(messages) { return [...messages, { role: "user", content: "instance-one", timestamp: 1 }]; } }));
    const two = await fixture(() => ({ ...identity,
      async transform(messages) { return [...messages, { role: "user", content: "instance-two", timestamp: 1 }]; } }));
    await Promise.all([one.host.session.prompt("one"), two.host.session.prompt("two")]);
    expect(JSON.stringify(one.provider.calls)).toContain("instance-one");
    expect(JSON.stringify(one.provider.calls)).not.toContain("instance-two");
    expect(JSON.stringify(two.provider.calls)).toContain("instance-two");
    expect(JSON.stringify(two.provider.calls)).not.toContain("instance-one");
  });

  it("aborts and settles a pending preparation before disposing the host", async () => {
    let entered!: () => void;
    const started = new Promise<void>((resolve) => { entered = resolve; });
    const { host, provider } = await fixture(() => ({ ...identity,
      async prepare(_request, signal) {
        entered();
        await new Promise<void>((_resolve, reject) => {
          signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
        });
        throw new Error("unreachable");
      },
    }));
    const prompt = host.session.prompt("abort fixture");
    await started;
    await host.dispose();
    await prompt;
    expect(provider.calls).toHaveLength(0);
    expect(host.session.agent.state.isStreaming).toBe(false);
    await host.dispose();
  });

  it.each(["length", "overflow", "threshold"])("does not enter automatic %s compaction or persist recovery edits", async (kind) => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const provider = await fakeProvider((model) => {
      const message = assistant(model);
      if (kind === "length") message.stopReason = "length";
      if (kind === "overflow") {
        message.stopReason = "error";
        message.errorMessage = "maximum context length exceeded";
      }
      if (kind === "threshold") {
        message.usage.input = 4000;
        message.usage.totalTokens = 4001;
      }
      return message;
    });
    const host = await createMemWeaveHost({ ...workspace, ...provider,
      pipeline: () => identity, sessionManager: SessionManager.inMemory(workspace.cwd) });
    cleanup.push(() => host.dispose());
    let compactEvents = 0;
    host.session.subscribe((event) => { if (event.type === "compaction_start") compactEvents++; });
    await host.session.prompt("large original input " + "x".repeat(8000));
    expect(provider.calls).toHaveLength(1);
    expect(compactEvents).toBe(0);
    expect(host.session.sessionManager.getEntries().filter((entry) => entry.type === "compaction" || entry.type === "context_edit")).toEqual([]);
  });

  it("isolates recovery from an ordinary Pi session sharing cwd, agentDir and settings", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const settingsPath = join(workspace.agentDir, "settings.json");
    const before = await readFile(settingsPath, "utf8");
    const response = (model: Parameters<typeof assistant>[0], index: number) => {
      const message = assistant(model);
      if (index === 0) { message.stopReason = "error"; message.errorMessage = "maximum context length exceeded"; }
      return message;
    };
    const guarded = await fakeProvider(response);
    const ordinary = await fakeProvider(response);
    const host = await createMemWeaveHost({ ...workspace, ...guarded, pipeline: () => identity,
      sessionManager: SessionManager.inMemory(workspace.cwd) });
    cleanup.push(() => host.dispose());
    const settingsManager = SettingsManager.create(workspace.cwd, workspace.agentDir);
    const resourceLoader = new DefaultResourceLoader({ ...workspace, settingsManager,
      extensionFactories: [(pi) => { pi.on("session_before_compact", () => ({ cancel: true })); }] });
    await resourceLoader.reload();
    const native = await createAgentSession({ cwd: workspace.cwd, agentDir: workspace.agentDir,
      modelRuntime: ordinary.modelRuntime, model: ordinary.model, settingsManager, resourceLoader,
      sessionManager: SessionManager.inMemory(workspace.cwd) });
    await native.session.bindExtensions({});
    cleanup.push(async () => { await native.session.abort(); native.session.dispose(); });
    await Promise.all([host.session.prompt("guarded input"), native.session.prompt("native input")]);
    expect(host.session.autoCompactionEnabled).toBe(false);
    expect(native.session.autoCompactionEnabled).toBe(true);
    expect(host.session.sessionManager.getEntries().filter((entry) => entry.type === "context_edit")).toHaveLength(0);
    expect(native.session.sessionManager.getEntries().filter((entry) => entry.type === "context_edit")).toHaveLength(1);
    expect(await readFile(settingsPath, "utf8")).toBe(before);
  });

  it("prepares a fresh shared frame for tool continuation without persisting request-only rules", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const rulePath = join(workspace.root, "rule-fixture.txt");
    await writeFile(rulePath, "first-rule-fixture");
    const provider = await fakeProvider((model, index) => {
      const message = assistant(model, index === 0
        ? [{ type: "toolCall", id: "hot_fixture", name: "hot_fixture", arguments: {} }]
        : [{ type: "text", text: "done" }]);
      if (index === 0) message.stopReason = "toolUse";
      return message;
    });
    const frames: string[] = [];
    const host = await createMemWeaveHost({ ...workspace, ...provider,
      sessionManager: SessionManager.inMemory(workspace.cwd),
      pipeline: () => ({
        async prepare(request) {
          const frame = await readFile(rulePath, "utf8");
          const system = getCurrentSystemMessage(request.context.messages);
          if (!system) throw new Error("Missing native system fixture");
          return { frame, messages: [{ ...system, sections: { ...system.sections,
            addendum: `${system.sections?.addendum ?? ""}\n${frame}` } },
          ...request.context.messages.filter((message) => message.role !== "system")] };
        },
        async transform(messages, frame) { frames.push(frame); return messages; },
      }),
      customTools: [{ name: "hot_fixture", description: "Fixture", label: "Fixture",
        parameters: Type.Object({}),
        async execute() {
          await writeFile(rulePath, "second-rule-fixture");
          return { content: [{ type: "text", text: "changed fixture" }], details: {} };
        } }],
    });
    cleanup.push(() => host.dispose());
    await host.session.prompt("continue fixture");
    expect(frames).toEqual(["first-rule-fixture", "second-rule-fixture"]);
    expect(JSON.stringify(provider.calls[0])).toContain("first-rule-fixture");
    expect(JSON.stringify(provider.calls[1])).toContain("second-rule-fixture");
    expect(JSON.stringify(host.session.sessionManager.getEntries())).not.toContain("-rule-fixture");
  });

  it("reuses native tool execution and preserves call IDs, arguments and reasoning signatures", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const argumentsValue = { value: "keep-json" };
    const provider = await fakeProvider((model, index) => {
      const message = assistant(model, index === 0 ? [
        { type: "thinking", thinking: "protected fixture", thinkingSignature: "signature-fixture" },
        { type: "toolCall", id: "call_fixture", name: "echo_fixture", arguments: argumentsValue },
      ] : [{ type: "text", text: "done" }]);
      if (index === 0) message.stopReason = "toolUse";
      return message;
    });
    let executed = 0;
    const host = await createMemWeaveHost({
      ...workspace, ...provider, pipeline: () => identity,
      sessionManager: SessionManager.inMemory(workspace.cwd),
      customTools: [{ name: "echo_fixture", description: "Fixture", label: "Fixture",
        parameters: Type.Object({ value: Type.String() }),
        async execute(_id, args) { executed++; return { content: [{ type: "text", text: (args as { value: string }).value }], details: {} }; } }],
    });
    cleanup.push(() => host.dispose());
    await host.session.prompt("use fixture tool");
    expect(executed).toBe(1);
    expect(provider.calls).toHaveLength(2);
    expect(JSON.stringify(provider.calls[1])).toContain("signature-fixture");
    const toolResult = provider.calls[1]!.messages.find((message) => message.role === "toolResult");
    expect(toolResult?.role === "toolResult" && toolResult.toolCallId).toBe("call_fixture");
    const response = provider.calls[1]!.messages.find((message) => message.role === "assistant");
    expect(response?.role === "assistant" && response.content).toContainEqual({ type: "toolCall",
      id: "call_fixture", name: "echo_fixture", arguments: argumentsValue });
  });
});
