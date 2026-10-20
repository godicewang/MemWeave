import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const source = new URL("docs/specs/1.2.rule_v1_3_final_updated.md", root);
const destination = new URL("resources/rule.md", root);
const args = process.argv.slice(2);
assert.ok(args.length === 0 || (args.length === 1 && args[0] === "--check"),
  "Usage: node scripts/sync-rule.mjs [--check]");

const template = await readFile(source);
if (args[0] === "--check") {
  assert.deepEqual(await readFile(destination), template,
    "Rule resource is out of date; run npm run resources:sync");
  console.log("Rule resource matches the specification template.");
} else {
  await mkdir(new URL("resources/", root), { recursive: true });
  await writeFile(destination, template);
  console.log("Generated resources/rule.md from the specification template.");
}
