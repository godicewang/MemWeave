import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

export async function temporaryWorkspace() {
  const root = await mkdtemp(join(tmpdir(), "memweave-test-"));
  const cwd = join(root, "workspace");
  const agentDir = join(root, "agent");
  await mkdir(join(cwd, ".pi"), { recursive: true });
  await mkdir(agentDir);
  await writeFile(join(agentDir, "settings.json"), JSON.stringify({
    compaction: { enabled: true, reserveTokens: 1024, keepRecentTokens: 512 },
    cacheWarming: { enabled: false },
    retry: { enabled: false },
  }));
  return { root, cwd, agentDir, cleanup: () => rm(root, { recursive: true, force: true }) };
}
