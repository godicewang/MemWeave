# 工具摘要调整与失败场景复核

2026-10-26。已实施用户批准的 state_append 小改动；首次强制绑定、混合检索和旧现场恢复处于设计定稿阶段，见 [联合提案](TASK_BINDING_AND_RETRIEVAL_PROPOSAL.md)。**没有发布 npm。**

## 1. “漏记”具体指什么

它指应保存的续接信息没有进入 Task 的 Symbolic State，不表示 Pi Session 中的交互被删掉，也不表示 State 连 Goal 都没有。上一轮已按规则删除临时原始日志，所以无法复述旧失败样本的随机目标值和全部调用参数；本轮将目标固定后重新取得了完整脱敏轨迹。

测试任务是在临时目录修复组件超时配置。文件最初 timeout_ms=31，计时探针的 service_delay_ms=100，要求 target_timeout_ms=137。业务目标是精确设成 137，再观察本地探针实际通过。测试用户只要求修复、验证和简要交付，没有额外喊“必须调用 state_append”。完整 Pi 原生 System、4 个原生工具、11 个记忆工具、默认完整 Rule 和真实 DeepSeek Flash/off 全部生效。

本轮调整后固定样本 1 的实际顺序为：

```text
用户要求修复并实际验证
→ task_create + inspect_component（同一 assistant 返回的两项调用）
→ Task 初始 Goal 提交 v1；inspect 返回 31 / 100 / 137
→ set_component_timeout(137)，本地文件写入成功
→ verify_component() 返回 passed=true，实际值和目标均为137
→ assistant 交付“已完成并实际验证通过”
→ 无 state_append；State 仍为 v1、仅 Goal，无 F/D
```

该 Goal 原文为“按 inspect_component 要求把组件超时配置正确并实际验证通过”，没有实际参数或已验证结果。适合保存的一条事实是：“组件超时由31ms改为137ms，本地探针通过；服务延迟100ms、配置与目标一致。”证据应对应实际设置和探针结果，而非只引用目标或 assistant 自述。

把它判为应保留信息，是沿用 State §22 的阶段收尾契约：实际参数和已验证结果影响后续续接与核查；Goal 是待达成的目标，不能替代完成事实。将来这些交互移出 Recent Window 后，原文仍在 Pi Session，可额外回读；只是 State 没有直接保留结论。另两个基线样本甚至没有 task_create，属于整个 Task/State 流程被跳过，不能都描述为“已有 Task 但漏了一次写入”。

## 2. “受阻未保存失败边界”具体指什么

用例与上面相同，但测试故意令 verify_component 直接返回：

```json
{"passed":false,"reason":"fixture transport blocked; verification cannot complete","timeout_ms":137}
```

这是夹具预设的业务阻塞，不是这次 DeepSeek API 调用失败，也不是实际外部网络被阻断。工具本身成功执行，所以原生 isError=false；业务是否通过必须看 passed/reason。

调整后固定样本 2 的顺序：inspect → task_create → set(137) → verify 返回上述阻塞 → assistant 明确说明“配置已改、验证受阻、没有反复重试、端到端尚未验证”。**最终答复对阻塞的说明正确。** 失败在 State 仍只有 v1 Goal“将组件超时设为精确137ms并通过本地探针验证”，没有保存配置已改和验证未完成的区别。

适合保存的事实是：“超时已设为137ms；verify 因夹具预设 transport blocked 未完成，尚无端到端通过结果。”未来恢复时可避免重复修改配置，或把目标中的“通过验证”误当已经发生。没有要求把每次普通重试都写入；这个用例是在用户要求的调查/修复阶段结束时保留下一步所需边界。

## 3. 小改动与验证结果

候选 `737631e7154f613bc1de92e8f146ad5aa067f453`，Pi/AI 1.4.0，Node24.22.0，macOS arm64。修改只涉及工具展示元数据：

- state_append 的保存时机移到 description 开头，删掉旧位置的等价文字；参数、示例和限制保留。
- 提供一条 Pi 原生 promptSnippet，使它出现在默认 System 的工具摘要。未新增尾部提示、自动保存、阶段工作流、远程模型或持久化。
- 先同步 Rule 技术稿 §2.2 和 State §22；**固定 Rule 两份正文与包内资源逐字核对保持一致且未变**。
- 集成检查默认摘要、reload，以及用户自定义 SYSTEM 时保留原生替换行为和完整 Rule/工具 description。不是强行恢复默认 System。

固定每场景 3 个样本，修改前后都使用 target=137、delay=100，完整环境，保留原断言；达到样本数即结束，不重试到绿。

| 场景 | 修改前通过 | 修改后通过 |
|---|---:|---:|
| 成功交付：含业务、有效探针证据、无重复写入、移出/重启后续接检查 | 1/3 | 2/3 |
| 阻塞交付：保存失败边界，且不谎称通过 | 3/3 | 1/3 |
| 短问答：按当前旧契约不强制 Task/F/D | 3/3 | 3/3 |
| 合计 | 7/9 | 6/9 |

两组分别 36、38 次真实主会话请求，包含成功样本的后续追问/回读；场景执行路径不同，不能把差值当作新增审计开销。样本少、存在模型随机性，不能宣称该调整提升总体可靠性，亦不能据此认定一定造成退化。它补齐了客观展示缺口，但**没有解决漏记**。

| 其他验证 | 实际结果 |
|---|---|
| 修改前新增边界检查 | 观察到默认摘要和 description 前置断言失败，再实现 |
| `memweave-dev npm run check` | 249/249，类型/资源检查通过 |
| 精确 Pi 1.3.0 临时环境，完整环境相关集成 | 3/3，默认摘要/reload、自定义 SYSTEM 和完整提示拒绝反例通过；不是全部旧宿主发布流程 |
| `memweave-dev npm run test:live` | **21/23**：交付 F/D 缺失、reload 后连续取消输入优先级失败；后者回答 KEEP_SECOND_EXPECT，期望 KEEP_THIRD_EXPECT。其余21项含重开、视觉、真实产物恢复通过 |
| `memweave-dev npm run test:release -- --full` | **249 常规＋5 入口/产物＋3 分发＋1 真实产物恢复全部通过**；固定候选737631e的SSH Git分发；真实产物恢复3次DeepSeek请求 |

完整自动入口通过不能抵消真实专项失败。没有新版本号、npm publish、dist-tag 或用户本机插件更新。归档68文件，integrity：

`sha512-SsDkfN+psyej5vNetC8jwvBwQ0tPUg30Mdq1HQaG/qWEP4LmztsbXO6NDgRAK39rQfm+plkAT23N+WGQUMLijQ==`

短问答结果对应本轮受测候选。用户曾暂时要求所有首次输入均绑定，随后明确保留简单即时问答豁免，并由Agent自主判断有意义的任务才进入检索/创建或恢复；联合提案按最终要求维护。不能拿本轮结果声称新混合检索/初始化流程已通过。

## 4. 为什么 Task 绑定必须提前

还有一类与之相关的证据风险：先 inspect/set/verify、后 task_create 的一个基线阻塞样本，将三条事实都写成 evidence=T1，却分别解释为三个业务工具。在当前首次绑定规则下，早先未绑定的工具不自动归属后来新建的 Task；T1 实际可成为 task_create 回执。

本轮额外以原生 Pi + Faux 进行了一个确定性控制实验（0次真实API）：先inspect/verify，再create，再将“verify受阻”以T1写入。核对源条目得到 **T1=task_create**，程序仍能接受该存在的引用。此结果说明“引用存在”不能证明“语义支持”。不将这个替身实验冒充真实模型验证，也没有因此新增语义审查 Agent。

因此，首次业务前绑定很有价值：它使业务工具从开始就获得正确 Task 来源，减少事后编造或错认编号的机会。但它仍不能保证模型不写错证据，也不能代替后续重要认知判断。后续候选验收既看有没有条目，也要核对正文与真实来源。

## 5. 图片格式失败的原因与建议

上一轮失败的具体输出是 `"left":"circle red"`，测试期待 `"left":{"shape":"circle","color":"red"}`。对应样本的图片出站及字节/hash检查已通过，识别出的图形和颜色也正确；这是对象结构未满足检查，不能归因于没收到图片。

测试指令只写“Each spatial key must have shape and color”，没有给嵌套对象类型或示例。这留下了语义空隙；自由生成的模型又不会自动受测试中的 TypeScript assert 约束。证据支持的原因是**输出契约表达不够明确，加上模型格式遵循不稳定**，不能声称已从模型内部定位唯一原因。

推荐只在视觉测试/实际调用任务的要求中给出明确、无答案的结构：

```json
{"code":"<8 digits>","left":{"shape":"<shape>","color":"<color>"},"middle":{"shape":"<shape>","color":"<color>"},"right":{"shape":"<shape>","color":"<color>"}}
```

继续严格检查，不填入正确图形、颜色或数字，不放宽成字符串也算通过。将附件送达/字节、识别、引用调用及JSON结构分开诊断。若某应用确需机器消费输出，再在该应用层使用模型支持且已验证的结构约束/校验；不为所有MemWeave会话强制JSON，也不加入全局自动补格式模型调用。本轮**未修改视觉提示/断言或产品图片流程**；本次视觉两项通过不表示历史格式、OCR或CROSS_TASK_R_NOT_ALLOWED已修复。

## 6. 重开未创建 Task 的原因与建议

用例先建旧Task，再向同一Pi Session注入26000条合成原生用户记录，执行/memweave-restart。命令不调用模型，只保存近期种子、退出旧绑定；reload后用户明确要求建立“订单批次校验”的新目标。失败样本没有task_create，scope.task_id仍为null；并不是程序把刚创建的Task删掉，也不是清空了旧State。

推荐与普通首次绑定共用门禁/失败纠正，避免单独再加一套重开提示：pending restart且目标明确时必须走task_create；业务前确认已绑定；直接答复不算成功，系统回执后最多一次纠正。沿用稳定候选ID和已有部分提交恢复，不丢种子、不恢复旧State、不自动从相似任务接管。目标不明确时仍不能编造Goal。详细新增回执、纠正成本及恢复索引方案在联合提案中，尚未开发。

临时脚本、固定样本、合成Session/State、图片、下载的测试宿主、归档与日志在收尾删除；认证原件保持仓库外且原字节未变。本文仅保留不含密钥的结论。
