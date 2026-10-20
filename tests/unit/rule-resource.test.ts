import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const templatePath = "docs/specs/1.2.rule_v1_3_final_updated.md";

test("Rule 技术稿与独立模板逐字一致", async () => {
  const technical = await readFile(
    new URL("docs/specs/1.1.pi_long_task_agent_rule_v1_3_final_cn_updated.md", root),
    "utf8",
  );
  const template = await readFile(new URL(templatePath, root), "utf8");
  const embedded = technical.match(/^```md\n(# 长程任务记忆协议\n[\s\S]*?)^```$/m);

  assert.ok(embedded, "技术稿第 4 节应包含固定 Rule 正文");
  assert.equal(embedded[1]?.replace(/\n+$/, ""), template.replace(/\n+$/, ""));
});

test("发布 Rule 资源来自独立模板，正文不被构建改写", async () => {
  const template = await readFile(new URL(templatePath, root));
  const resource = await readFile(new URL("resources/rule.md", root));

  assert.deepEqual(resource, template);
});
