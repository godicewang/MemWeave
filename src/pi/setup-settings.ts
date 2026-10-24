import { readFile } from "node:fs/promises";
import { SettingsManager } from "@earendil-works/pi-coding-agent";
import { DEFAULT_CONFIG } from "../config/schema.ts";
import { renderRule } from "../rule/render.ts";

export async function loadDefaultRule(): Promise<string> {
  const bytes = await readFile(new URL("../../resources/rule.md", import.meta.url));
  const template = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  renderRule(template, DEFAULT_CONFIG);
  return template;
}

export async function disableGlobalCompaction(cwd: string, agentDir: string): Promise<void> {
  // Only global settings are involved. Never load or write untrusted project settings.
  const settings = SettingsManager.create(cwd, agentDir, { projectTrusted: false });
  if (settings.drainErrors().length) throw Error("SETUP_SETTINGS_INVALID: cannot read global Pi settings");
  const compaction = settings.getGlobalSettings().compaction;
  if (compaction !== undefined && (typeof compaction !== "object" || compaction === null || Array.isArray(compaction)))
    throw Error("SETUP_SETTINGS_INVALID: global compaction must be an object");
  settings.setCompactionEnabled(false);
  await settings.flush();
  if (settings.drainErrors().length) throw Error("SETUP_SETTINGS_WRITE_FAILED: global Pi settings were not reliably saved");
  const saved = SettingsManager.create(cwd, agentDir, { projectTrusted: false });
  if (saved.drainErrors().length || saved.getGlobalSettings().compaction?.enabled !== false)
    throw Error("SETUP_SETTINGS_UNVERIFIED: cannot verify global compaction.enabled=false");
}
