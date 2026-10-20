import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { SettingsManager } from "@earendil-works/pi-coding-agent";
import { fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { registerRequestLifecycle } from "../../src/pi/request-lifecycle.ts";
import { nativeSession } from "../fixtures/native-session.ts";

test("共享全局设置要在 reload 后读取，受信任项目配置可覆盖，禁用扩展不回滚设置", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-settings-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const agent = join(root, "agent"); const cwd = join(root, "workspace");
  await mkdir(agent); await mkdir(join(cwd, ".pi"), { recursive: true });
  const first = SettingsManager.create(cwd, agent, { projectTrusted: true });
  const second = SettingsManager.create(cwd, agent, { projectTrusted: true });
  first.setCompactionEnabled(false); await first.flush();
  assert.equal(second.getCompactionEnabled(), true);
  await second.reload(); assert.equal(second.getCompactionEnabled(), false);
  const settingsFile = join(agent, "settings.json");
  const persisted = await readFile(settingsFile, "utf8");
  await writeFile(join(cwd, ".pi/settings.json"), JSON.stringify({ compaction: { enabled: true } }));
  await second.reload(); assert.equal(second.getCompactionEnabled(), true);
  second.setProjectTrusted(false); assert.equal(second.getCompactionEnabled(), false);
  assert.equal(await readFile(settingsFile, "utf8"), persisted);
  const withoutExtension = SettingsManager.create(join(root, "another-workspace"), agent);
  assert.equal(withoutExtension.getCompactionEnabled(), false);
});

for (const kind of ["threshold", "overflow", "length"] as const) {
  test(`关闭自动压缩后 ${kind} 不生成摘要或恢复编辑`, async (t) => {
    let compactions = 0;
    const h = await nativeSession(t, [(pi) => {
      pi.on("session_before_compact", () => { compactions++; });
      registerRequestLifecycle(pi);
    }], false, kind === "threshold" ? 1_048_000 : 512);
    await h.session.prompt("seed history");
    const response = fauxAssistantMessage(kind, {
      stopReason: kind === "threshold" ? "stop" : kind === "overflow" ? "error" : "length",
      ...(kind === "overflow" ? { errorMessage: "maximum context length exceeded" } : {}),
    });
    h.faux.appendResponses([response]);
    await h.session.prompt(`${kind} `.repeat(1000));
    assert.equal(h.faux.state.callCount, 2);
    assert.equal(compactions, 0);
    assert.equal(h.manager.getBranch().filter(entry => ["compaction", "context_edit"].includes(entry.type)).length, 0);
  });
}

test("手动 compaction 由公开 hook 取消，不调用摘要模型", async (t) => {
  let hooks = 0;
  const h = await nativeSession(t, [(pi) => {
    pi.on("session_before_compact", () => { hooks++; });
    registerRequestLifecycle(pi);
  }]);
  await h.session.prompt("seed ".repeat(2000));
  h.faux.appendResponses([fauxAssistantMessage("RECENT")]);
  await h.session.prompt("recent ".repeat(2000));
  await assert.rejects(h.session.compact(), /cancelled/i);
  assert.equal(hooks, 1);
  assert.equal(h.faux.state.callCount, 2);
  assert.equal(h.manager.getBranch().filter(entry => entry.type === "compaction").length, 0);
});

for (const kind of ["threshold", "overflow", "length"] as const) {
test(`运行中重开压缩的反例 ${kind}：取消 hook 无法替代关闭自动压缩`, async (t) => {
  let hooks = 0;
  const h = await nativeSession(t, [(pi) => {
    pi.on("session_before_compact", () => { hooks++; });
    registerRequestLifecycle(pi);
  }], false, kind === "threshold" ? 1_048_000 : 512);
  await h.session.prompt("seed ".repeat(2000));
  h.faux.appendResponses([() => {
    h.settings.setCompactionEnabled(true);
    const response = fauxAssistantMessage("response", {
      stopReason: kind === "threshold" ? "stop" : kind === "overflow" ? "error" : "length",
      ...(kind === "overflow" ? { errorMessage: "maximum context length exceeded" } : {}),
    });
    return response;
  }]);
  await h.session.prompt("overflow after external setting change ".repeat(100));
  assert.equal(h.faux.state.callCount, 2);
  assert.equal(hooks, 1);
  assert.equal(h.manager.getBranch().filter(entry => entry.type === "context_edit").length, kind === "threshold" ? 0 : 1);
  assert.equal(h.manager.getBranch().filter(entry => entry.type === "compaction").length, 0);
});
}
