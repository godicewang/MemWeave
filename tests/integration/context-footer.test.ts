import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import { FooterComponent, initTheme, type ExtensionContext, type ExtensionUIContext,
  type ReadonlyFooterDataProvider } from "@earendil-works/pi-coding-agent";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { registerMemweaveRuntime } from "../../src/extension/register.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import { nativeSession } from "../fixtures/native-session.ts";
import { registerContextFooter } from "../../src/pi/context-footer.ts";

type Factory = NonNullable<Parameters<ExtensionUIContext["setFooter"]>[0]>;
type Component = ReturnType<Factory>;
const strip = (s: string) => s.replace(/\x1b\[[0-9;]*m/g, "");
const data: ReadonlyFooterDataProvider = {
  getGitBranch: () => "main",
  getExtensionStatuses: () => new Map([["memweave", "MemWeave 已启用"]]),
  getAvailableProviderCount: () => 2,
  onBranchChange: () => () => {},
};

async function fixture(t: TestContext) {
  initTheme("dark", false);
  const root = await mkdtemp(join(tmpdir(), "memweave-footer-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root);
  await writeFile(paths.rule, await readFile(new URL("../../resources/rule.md", import.meta.url)));
  let ctx!: ExtensionContext, footer: Component | undefined, installs = 0, renders = 0, capacity = 1_048_576;
  const h = await nativeSession(t, [pi => {
    registerMemweaveRuntime(pi, { paths, verifyCapacity: async () => capacity }, {
      startup: async () => true, assertReady: () => {}, prepareInteractive: async () => {},
    });
    pi.on("message_end", (_e, context) => { ctx = context; });
  }]);
  const responses: Array<AssistantMessage | (() => AssistantMessage)> = [];
  const server = createServer(async (req, res) => {
    for await (const _chunk of req) { /* Consume actual outgoing request. */ }
    const next = responses.shift();
    const message = typeof next === "function" ? next() : next;
    assert.ok(message, "unexpected HTTP inference");
    if (message.stopReason === "error") { res.writeHead(503); res.end("fixture failure"); return; }
    res.writeHead(200, { "content-type": "text/event-stream" });
    const tool = message.content.find(p => p.type === "toolCall");
    const delta = tool ? { role: "assistant", tool_calls: [{ index: 0, id: tool.id, type: "function",
      function: { name: tool.name, arguments: JSON.stringify(tool.arguments) } }] } : { role: "assistant", content: "OK" };
    const send = (value: unknown) => res.write(`data: ${JSON.stringify(value)}\n\n`);
    send({ id: "footer", choices: [{ index: 0, delta, finish_reason: null }] });
    if (message.stopReason === "aborted") return; // Test aborts this real in-flight HTTP stream.
    send({ id: "footer", choices: [{ index: 0, delta: {}, finish_reason: tool ? "tool_calls" : "stop" }] });
    const u = message.usage;
    if (u.totalTokens) send({ id: "footer", choices: [], usage: { prompt_tokens: u.input + u.cacheRead + u.cacheWrite,
      completion_tokens: u.output, total_tokens: u.totalTokens, prompt_tokens_details: { cached_tokens: u.cacheRead } } });
    res.end("data: [DONE]\n\n");
  });
  await new Promise<void>(r => server.listen(0, "127.0.0.1", r));
  t.after(async () => { server.closeAllConnections(); await new Promise<void>(r => server.close(() => r())); });
  h.runtime.registerProvider("footer-http", { api: "openai-completions", apiKey: "fixture-only",
    baseUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`, models: [{ id: "probe", name: "Footer probe",
      reasoning: false, input: ["text"], contextWindow: 1_000_000, maxTokens: 1024,
      cost: { input: 0.1, output: 0.2, cacheRead: 0.01, cacheWrite: 0.1 } }] });
  const ui = {
    setFooter: (factory: Factory | undefined) => {
      footer?.dispose?.(); installs++;
      footer = factory?.({ requestRender: () => { renders++; } } as Parameters<Factory>[0],
        {} as Parameters<Factory>[1], data);
    },
    notify: () => {},
  } as unknown as ExtensionUIContext;
  await h.session.bindExtensions({ mode: "tui", uiContext: ui, onError: e => h.errors.push(e.error) });
  const lines = (width = 190) => { assert.ok(footer); return footer.render(width); };
  const stats = () => strip(lines()[1]!);
  // Deliberately make the native catalogue differ from verified provider capacity.
  await h.session.setModel(h.runtime.getModel("footer-http", "probe")!);
  return { ...h, paths, lines, stats, setResponses: (items: typeof responses) => { responses.splice(0, responses.length, ...items); },
    setCapacity: (value: number) => { capacity = value; }, get ctx() { return ctx; }, get installs() { return installs; },
    get renders() { return renders; } };
}

function answer(input: number, output = 7, cacheRead = 1024, cacheWrite = 0) {
  const m = fauxAssistantMessage("OK");
  m.usage = { input, output, cacheRead, cacheWrite, totalTokens: input + output + cacheRead + cacheWrite,
    cost: { input: 0.01, output: 0.001, cacheRead: 0.001, cacheWrite: 0, total: 0.012 } };
  return m;
}

test("native footer appearance is identical at all widths; context uses only last API response and verified capacity", async t => {
  const h = await fixture(t);
  assert.match(h.stats(), /\?\/1\.0M/);
  for (const [input, expected] of [[7903, "0.9"], [281374, "26.9"], [661211, "63.2"]] as const) {
    h.setResponses([() => {
      if (input === 281374) assert.match(h.stats(), /0\.9%\/1\.0M/);
      if (input === 661211) assert.match(h.stats(), /26\.9%\/1\.0M/);
      return answer(input);
    }]);
    await h.session.prompt("new user body ".repeat(2000));
    assert.match(h.stats(), new RegExp(`${expected.replace(".", "\\.")}%/1\\.0M`));
    const total = input + 7 + 1024;
    const baseline = new FooterComponent(new Proxy(h.session, { get(target, key) {
      if (key === "getContextUsage") return () => ({ tokens: total, contextWindow: 1_048_576, percent: total / 1_048_576 * 100 });
      return Reflect.get(target, key, target);
    } }), data);
    baseline.setAutoCompactEnabled(false);
    for (const width of [12, 40, 80, 190]) assert.deepEqual(h.lines(width), baseline.render(width));
  }
  assert.equal(h.session.model?.contextWindow, 1_000_000, "never change model catalogue");
  assert.equal(h.installs, 1, "do not steal the footer slot on every request");
  assert.ok(h.renders > 0);
  assert.deepEqual(h.errors, []);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /【本次预算快照/);
});

test("tool replies update the last request, while results and continuation preparation do not add estimates", async t => {
  const h = await fixture(t);
  h.setResponses([() => {
    const m = answer(410000, 65);
    m.content = [fauxToolCall("recent_window_set", { turns: 20, evict_turns: 4 })];
    m.stopReason = "toolUse";
    return m;
  }, () => {
    assert.match(h.stats(), /39\.2%\/1\.0M/);
    return answer(85926, 9);
  }]);
  await h.session.prompt("Change the recent window");
  assert.match(h.stats(), /8\.3%\/1\.0M/);
  const unchanged = h.stats();
  h.setResponses([() => { assert.equal(h.stats(), unchanged); return fauxAssistantMessage("failed", { stopReason: "error", errorMessage: "fixture" }); }]);
  await h.session.prompt("failed attempt with more input".repeat(1000));
  assert.match(h.stats(), /8\.3%\/1\.0M/);
  h.setResponses([fauxAssistantMessage("missing usage")]);
  await h.session.prompt("usage unavailable");
  assert.equal(h.stats().match(/\d+\.\d+%\/1\.0M/)?.[0], "8.3%/1.0M");
  await h.session.setModel({ ...h.session.model!, id: "different-model" });
  assert.match(h.stats(), /\?\/1\.0M/);
  assert.deepEqual(h.errors, []);
});

test("non-TUI/RPC paths never install a custom footer", async t => {
  const h = await nativeSession(t, [pi => { registerContextFooter(pi); }]);
  let installs = 0;
  await h.session.bindExtensions({ mode: "rpc", uiContext: { setFooter: () => { installs++; } } as unknown as ExtensionUIContext });
  await h.session.prompt("headless");
  assert.equal(installs, 0);
  assert.deepEqual(h.errors, []);
});

test("abort keeps the previous snapshot; changed capacity applies with the next response; tree/reload clear it", async t => {
  const h = await fixture(t);
  h.setResponses([answer(661211)]);
  await h.session.prompt("first completed response");
  assert.match(h.stats(), /63\.2%\/1\.0M/);
  h.setResponses([() => {
    assert.match(h.stats(), /63\.2%\/1\.0M/);
    setTimeout(() => void h.session.abort(), 10);
    return fauxAssistantMessage("partial", { stopReason: "aborted" });
  }]);
  await h.session.prompt("abort this response");
  assert.match(h.stats(), /63\.2%\/1\.0M/);
  h.setCapacity(524288);
  h.setResponses([() => { assert.match(h.stats(), /63\.2%\/1\.0M/); return answer(200000); }]);
  await h.session.prompt("new verified capacity");
  assert.match(h.stats(), /38\.3%\/524k/);
  const user = h.manager.getBranch().find(e => e.type === "message" && e.message.role === "user")!;
  await h.session.navigateTree(user.id, { summarize: false });
  assert.match(h.stats(), /\?\/1\.0M/);
  h.setResponses([answer(7903)]);
  await h.session.prompt("new branch");
  assert.match(h.stats(), /1\.7%\/524k/);
  await h.session.reload();
  assert.match(h.stats(), /\?\/1\.0M/);
  assert.deepEqual(h.errors, []);
});
