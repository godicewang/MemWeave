import { Type } from "typebox";
import { Check } from "typebox/value";
import { atomicWrite, readOptional, withLock } from "./files.ts";
import type { MemoryPaths } from "./paths.ts";

const markerSchema = Type.Object({ version: Type.Literal(1) }, { additionalProperties: false });

export async function isSetupComplete(paths: MemoryPaths, agentDir: string): Promise<boolean> {
  let text: string | undefined;
  try { text = await readOptional(paths.setup(agentDir).marker); }
  catch { throw Error("SETUP_MARKER_READ_FAILED: cannot read initialization marker"); }
  if (text === undefined) return false;
  let value: unknown;
  try { value = JSON.parse(text); }
  catch { throw Error("INVALID_SETUP_MARKER: invalid initialization marker JSON"); }
  if (!Check(markerSchema, value)) throw Error("INVALID_SETUP_MARKER: unknown initialization marker format");
  return true;
}

/** The marker is the last commit. A concurrent or later invocation never replaces Rule twice. */
export async function completeSetup(
  paths: MemoryPaths, agentDir: string, loadTemplate: () => Promise<string>,
  disableCompaction: () => Promise<void>,
): Promise<void> {
  const setup = paths.setup(agentDir);
  await withLock(setup.lock, async () => {
    if (await isSetupComplete(paths, agentDir)) return;
    let stage = "template", rule = "unchanged", global = "unchanged";
    try {
      const template = await loadTemplate();
      if (!template.trim()) throw Error("INVALID_RULE: bundled Rule is empty");
      stage = "rule";
      await atomicWrite(paths.rule, template);
      rule = "replaced";
      stage = "global_compaction";
      await disableCompaction();
      global = "disabled";
      stage = "completion";
      await atomicWrite(setup.marker, '{"version":1}\n');
    } catch (error) {
      // Do not expose parser excerpts or arbitrary user settings in diagnostics.
      const code = error instanceof Error && /^(?:SETUP_|INVALID_RULE|COMMIT_DURABILITY_UNCERTAIN)/.test(error.message)
        ? error.message.split(":")[0] : "WRITE_FAILED";
      throw Error(`SETUP_FAILED: stage=${stage}; Rule=${rule}; global_compaction=${global}; ${code}; ` +
        "the current stage may be partially committed; retry /memweave-setup after fixing the cause");
    }
  });
}
