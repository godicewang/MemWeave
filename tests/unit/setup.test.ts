import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test, { type TestContext } from "node:test";
import { memoryPaths } from "../../src/storage/paths.ts";
import { completeSetup, isSetupComplete } from "../../src/storage/setup.ts";
import { disableGlobalCompaction, loadDefaultRule } from "../../src/pi/setup-settings.ts";

async function fixture(t: TestContext) {
  const root = await mkdtemp(join(tmpdir(), "memweave-setup-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(join(root, "memory"));
  const agentDir = join(root, "agent"), cwd = join(root, "business");
  await mkdir(agentDir); await mkdir(cwd);
  return { root, paths, agentDir, cwd };
}

test("first initialization replaces Rule, merges only global compaction and records completion per profile", async t => {
  const { paths, agentDir, cwd } = await fixture(t);
  await mkdir(paths.root);
  await writeFile(paths.rule, "CUSTOM RULE TO REPLACE");
  await writeFile(paths.config, '{"state_max_events":400}');
  const settings = { compaction: { enabled: true, reserveTokens: 1234 }, packages: ["unrelated"], extra: { preserve: true } };
  await writeFile(paths.setup(agentDir).settings, JSON.stringify(settings));
  await mkdir(join(cwd, ".pi"));
  const project = '{"compaction":{"enabled":true},"packages":["project-package"]}';
  await writeFile(join(cwd, ".pi/settings.json"), project);
  assert.equal(await isSetupComplete(paths, agentDir), false);
  await completeSetup(paths, agentDir, loadDefaultRule, () => disableGlobalCompaction(cwd, agentDir));
  assert.equal(await readFile(paths.rule, "utf8"), await loadDefaultRule());
  assert.deepEqual(JSON.parse(await readFile(paths.setup(agentDir).settings, "utf8")), {
    ...settings, compaction: { ...settings.compaction, enabled: false },
  });
  assert.equal(await readFile(join(cwd, ".pi/settings.json"), "utf8"), project);
  assert.equal(await readFile(paths.config, "utf8"), '{"state_max_events":400}');
  assert.deepEqual(JSON.parse(await readFile(paths.setup(agentDir).marker, "utf8")), { version: 1 });
  assert.equal(await isSetupComplete(paths, agentDir), true);
  assert.equal(await isSetupComplete(paths, join(agentDir, "another-profile")), false);
  await assert.rejects(readFile(paths.index), { code: "ENOENT" });
});

test("concurrent initialization commits once; completed setup preserves subsequent Rule edits", async t => {
  const { paths, agentDir } = await fixture(t);
  let writes = 0;
  const run = () => completeSetup(paths, agentDir, async () => "DEFAULT RULE", async () => { writes++; });
  await Promise.all([run(), run()]);
  assert.equal(writes, 1);
  await writeFile(paths.rule, "USER EDIT AFTER SETUP");
  await run();
  assert.equal(await readFile(paths.rule, "utf8"), "USER EDIT AFTER SETUP");
  assert.equal(writes, 1);
});

test("failed settings write reports partial Rule replacement and permits retry without completion", async t => {
  const { paths, agentDir, cwd } = await fixture(t);
  await writeFile(paths.setup(agentDir).settings, '{"private-value-that-must-not-be-logged":');
  await assert.rejects(completeSetup(paths, agentDir, loadDefaultRule, () => disableGlobalCompaction(cwd, agentDir)), error => {
    assert.ok(error instanceof Error);
    assert.match(error.message, /SETUP_FAILED.*global_compaction/);
    assert.doesNotMatch(error.message, /private-value-that-must-not-be-logged/);
    return true;
  });
  assert.equal(await readFile(paths.rule, "utf8"), await loadDefaultRule());
  assert.equal(await isSetupComplete(paths, agentDir), false);
  await writeFile(paths.setup(agentDir).settings, "{}");
  await completeSetup(paths, agentDir, loadDefaultRule, () => disableGlobalCompaction(cwd, agentDir));
  assert.equal(await isSetupComplete(paths, agentDir), true);
});

test("Rule failure leaves settings untouched; marker failure retains committed changes and retries safely", async t => {
  const { paths, agentDir } = await fixture(t);
  await mkdir(paths.rule, { recursive: true });
  let writes = 0;
  await assert.rejects(completeSetup(paths, agentDir, async () => "RULE", async () => { writes++; }), /SETUP_FAILED.*rule/);
  assert.equal(writes, 0);
  await rm(paths.rule, { recursive: true });
  await assert.rejects(completeSetup(paths, agentDir, async () => "RULE", async () => {
    writes++;
    await mkdir(paths.setup(agentDir).marker);
  }), /SETUP_FAILED.*completion/);
  assert.equal(writes, 1);
  assert.equal(await readFile(paths.rule, "utf8"), "RULE");
  await rm(paths.setup(agentDir).marker, { recursive: true });
  await completeSetup(paths, agentDir, async () => "RULE", async () => { writes++; });
  assert.equal(await isSetupComplete(paths, agentDir), true);
});

test("unknown, malformed and extra-field completion markers are rejected without overwriting anything", async t => {
  const { paths, agentDir } = await fixture(t);
  await mkdir(join(paths.root, "setup"), { recursive: true });
  for (const bytes of ["{", '{"version":2}', '{"version":1,"extra":true}', "[]"]) {
    await writeFile(paths.setup(agentDir).marker, bytes);
    await assert.rejects(isSetupComplete(paths, agentDir), /INVALID_SETUP_MARKER/);
    await assert.rejects(completeSetup(paths, agentDir, loadDefaultRule, async () => {}), /INVALID_SETUP_MARKER/);
    assert.equal(await readFile(paths.setup(agentDir).marker, "utf8"), bytes);
  }
  await assert.rejects(readFile(paths.rule), { code: "ENOENT" });
});
