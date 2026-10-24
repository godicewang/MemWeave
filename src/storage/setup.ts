import { Type } from "typebox";
import { Check } from "typebox/value";
import { atomicWrite, readOptional, withLock } from "./files.ts";
import type { MemoryPaths } from "./paths.ts";

const packageVersionSchema = Type.String({ minLength: 1, maxLength: 256, pattern: "^\\S+$" });
const legacySchema = Type.Object({ version: Type.Literal(1) }, { additionalProperties: false });
const currentSchema = Type.Object({ version: Type.Literal(2), package_version: packageVersionSchema }, { additionalProperties: false });
type SetupMarker = { version: 1 } | { version: 2; package_version: string };

export function assertPackageVersion(value: unknown): asserts value is string {
  if (!Check(packageVersionSchema, value)) throw Error("SETUP_PACKAGE_VERSION_INVALID: package.json must provide a version");
}

export async function isSetupComplete(paths: MemoryPaths, agentDir: string): Promise<boolean> {
  return await readMarker(paths, agentDir) !== undefined;
}

async function readMarker(paths: MemoryPaths, agentDir: string): Promise<SetupMarker | undefined> {
  let text: string | undefined;
  try { text = await readOptional(paths.setup(agentDir).marker); }
  catch { throw Error("SETUP_MARKER_READ_FAILED: cannot read initialization marker"); }
  if (text === undefined) return undefined;
  let value: unknown;
  try { value = JSON.parse(text); }
  catch { throw Error("INVALID_SETUP_MARKER: invalid initialization marker JSON"); }
  if (Check(legacySchema, value) || Check(currentSchema, value)) return value;
  throw Error("INVALID_SETUP_MARKER: unknown initialization marker format");
}

/** The applied package version is committed last; concurrent loads apply each current version once. */
export async function completeSetup(
  paths: MemoryPaths, agentDir: string, loadTemplate: () => Promise<string>,
  disableCompaction: () => Promise<void>, packageVersion: string,
): Promise<void> {
  assertPackageVersion(packageVersion);
  const setup = paths.setup(agentDir);
  await withLock(setup.lock, async () => {
    const marker = await readMarker(paths, agentDir);
    if (marker?.version === 2 && marker.package_version === packageVersion) return;
    let stage = "template", rule = "unchanged", global = "unchanged";
    try {
      const template = await loadTemplate();
      if (!template.trim()) throw Error("INVALID_RULE: bundled Rule is empty");
      stage = "rule";
      await atomicWrite(paths.rule, template);
      rule = "replaced";
      if (!marker) {
        stage = "global_compaction";
        await disableCompaction();
        global = "disabled";
      }
      stage = "completion";
      await atomicWrite(setup.marker, JSON.stringify({ version: 2, package_version: packageVersion }) + "\n");
    } catch (error) {
      // Do not expose parser excerpts or arbitrary user settings in diagnostics.
      const code = error instanceof Error && /^(?:SETUP_|INVALID_RULE|COMMIT_DURABILITY_UNCERTAIN)/.test(error.message)
        ? error.message.split(":")[0] : "WRITE_FAILED";
      throw Error(`SETUP_FAILED: stage=${stage}; Rule=${rule}; global_compaction=${global}; ${code}; ` +
        "the current stage may be partially committed; retry /memweave-setup after fixing the cause");
    }
  });
}
