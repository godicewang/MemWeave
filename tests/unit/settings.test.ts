import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { SettingsManager } from "@earendil-works/pi-coding-agent";
import { afterEach, describe, expect, it } from "vitest";
import { isolateCompaction, CompactionDisabledError } from "../../src/pi/settings.js";
import { temporaryWorkspace } from "../fixtures/workspace.js";

const cleanup: Array<() => Promise<void>> = [];
afterEach(async () => { for (const remove of cleanup.splice(0)) await remove(); });

describe("per-instance compaction settings", () => {
  it("keeps global/project settings and a normal Pi instance unchanged", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const globalPath = join(workspace.agentDir, "settings.json");
    const projectPath = join(workspace.cwd, ".pi/settings.json");
    await writeFile(projectPath, '{"compaction":{"enabled":true}}');
    const before = await Promise.all([readFile(globalPath, "utf8"), readFile(projectPath, "utf8")]);
    const source = SettingsManager.create(workspace.cwd, workspace.agentDir, { projectTrusted: true });
    const isolated = isolateCompaction(source);
    const ordinary = SettingsManager.create(workspace.cwd, workspace.agentDir, { projectTrusted: true });
    expect(isolated.getCompactionEnabled()).toBe(false);
    expect(isolated.getCompactionSettings().enabled).toBe(false);
    expect(isolated.getSettings().compaction?.enabled).toBe(false);
    expect(ordinary.getCompactionEnabled()).toBe(true);
    expect(source.getCompactionEnabled()).toBe(true);
    expect(await Promise.all([readFile(globalPath, "utf8"), readFile(projectPath, "utf8")])).toEqual(before);
  });

  it("survives reload, unrelated saves, project overrides and attempted enabling", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const source = SettingsManager.create(workspace.cwd, workspace.agentDir, { projectTrusted: true });
    const isolated = isolateCompaction(source);
    isolated.applyOverrides({ compaction: { enabled: true } });
    isolated.setRetryEnabled(true);
    await isolated.flush();
    await writeFile(join(workspace.cwd, ".pi/settings.json"), '{"compaction":{"enabled":true}}');
    await isolated.reload();
    expect(isolated.getRetryEnabled()).toBe(true);
    expect(isolated.getCompactionEnabled()).toBe(false);
    expect(isolated.getCompactionSettings().enabled).toBe(false);
    expect(isolated.getSettings().compaction?.enabled).toBe(false);
    expect(() => isolated.setCompactionEnabled(true)).toThrow(CompactionDisabledError);
    expect(JSON.parse(await readFile(join(workspace.agentDir, "settings.json"), "utf8")).compaction.enabled).toBe(true);
  });

  it("is idempotent, returns detached views, and never persists a disabling operation", async () => {
    const workspace = await temporaryWorkspace();
    cleanup.push(workspace.cleanup);
    const settingsPath = join(workspace.agentDir, "settings.json");
    const before = await readFile(settingsPath, "utf8");
    const isolated = isolateCompaction(SettingsManager.create(workspace.cwd, workspace.agentDir));
    expect(isolateCompaction(isolated)).toBe(isolated);
    isolated.setCompactionEnabled(false);
    const view = isolated.getSettings();
    if (view.compaction) view.compaction.enabled = true;
    expect(isolated.getCompactionSettings().enabled).toBe(false);
    await isolated.flush();
    expect(await readFile(settingsPath, "utf8")).toBe(before);
  });
});
