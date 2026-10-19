import { readFile } from "node:fs/promises";

const specs = new URL("../docs/specs/", import.meta.url);
const technical = await readFile(new URL("1.1.pi_long_task_agent_rule_v1_3_final_cn_updated.md", specs), "utf8");
const template = await readFile(new URL("1.2.rule_v1_3_final_updated.md", specs), "utf8");
const copies = [...technical.matchAll(/^```md\r?\n(# 长程任务记忆协议\r?\n[\s\S]*?)^```/gm)];
if (copies.length !== 1 || copies[0][1].replace(/\r?\n+$/, "") !== template.replace(/\r?\n+$/, "")) {
  throw new Error("Rule 技术稿第 4 节与独立模板不一致，请同步两处正文。");
}
console.log("Rule template copies match.");
