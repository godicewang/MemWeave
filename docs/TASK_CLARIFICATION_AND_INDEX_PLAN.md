# 澄清接线与首次索引优化

2026-10-26，用户确认范围：删除task_find的initialize参数，增加Agent可调用的澄清工具，修复澄清被强制继续；在不影响检索效果的前提下优化首次索引。用户进一步确认：以task_create/task_resume调用作为绑定意图，调用失败且未绑定时才纠正；task_find只搜索。索引先独立验收提交，澄清接线随后实现。完成及真实测试另行记录，不在本文件预写通过结论。

两个切片现已分别实现；实际结果见[TASK_INDEX_BATCHING_VALIDATION.md](TASK_INDEX_BATCHING_VALIDATION.md)和[TASK_CLARIFICATION_VALIDATION.md](TASK_CLARIFICATION_VALIDATION.md)，包括仍暂缓的真实模型认知失败。本文件继续作为本轮已确认接线范围，不替代验收结果。

## 第一部分：目的、范围和取舍

澄清应让Agent真正停下来等用户选择，不能为了通过绑定检查猜任务。简单即时问答继续豁免，不新增问题分类模型；Task/State/窗口的核心数据与恢复语义保持。新增澄清工具及移除参数先同步直接规范，保留旧Session回执可读，不能因新版本不再接受参数而损坏旧历史。

首次索引目前逐Task通信并写派生记录，1000项冷调用本轮三次基线约19.7–20.1秒。优化只集中在TaskSearch和工具进度：少量文档一起送给同一个本地worker，模型内部仍逐条推理；独立派生文件小批并发写入，保留每项锁、原子替换及明确失败。预期减少通信/等待，不提高嵌入模型复杂度，不引入数据库，不承诺未测的加速倍数或总进程内存上限。

用户指定暂不处理的漏存阻塞、工具错误修正效率、两类窗口混淆，及本轮产物新增认知未满足的回归失败，已独立记录到[疑难case](DIFFICULT_CASES.md)。本轮不添加认知收尾状态提示、不改State工具报错或窗口提醒。

## 第二部分：实现和验收边界

### 索引垂直切片

- 预计修改：`src/task/search.ts`、`src/task/service.ts`、`src/extension/register.ts`及相关测试；按现有Embedder的texts数组接口通信，无须修改模型worker推理算法。
- 每块最多16个Task；变化文本合并通信。每项前缀/token限制、向量、截断标记、余弦及RRF顺序不变。每次最多4个独立派生写入；`allSettled`等待该组完成后再报告失败，不遗留后台写入。
- UI只使用原生工具partial update，最终返回仍是原候选数组。进度为准备及已完成/总数、更新文档数，不重复给模型发消息。
- 先测试：33个Task被有界合并，未变不重嵌入，单项失效仅重算该项；排名与逐条参考结果一致；取消和坏向量不假报完成；旧缓存/权威State损坏继续按原规则处理。
- 真实本地E5前后各3次冷索引、热查询；逐Task向量/截断标记哈希及多查询完整Top-k分数、通道排名必须相同。进程内存单独测，不把32MiB派生缓存冒充RSS上限。
- 相关类型检查、单测与Pi工具/Session集成；真实模型测试使用完整生产System、全部默认工具与当前完整Rule。临时性能脚本/产物仅留系统临时目录，验收后删除。

### 已确认的澄清与绑定接线

- 删除FindSchema中的initialize，新调用带旧字段按现有严格schema拒绝；旧Session调用保留原样，仅供既有v1失败回执来源校验。
- 当前真实输入实际调用task_create/task_resume才产生绑定意图；scope成功则继续，失败且未绑定才限制业务和有界纠正。task_find仅搜索，不额外强制绑定；没有进入Task的漏判仍按用户要求暂存case。
- task_clarify输入仅question必填非空，已绑定/未绑定都可用。使用公开AgentToolResult.terminate停止本轮；有UI通过原生input收集实际答复，非空时sendUserMessage followUp（不展开模板）形成新的真实输入。取消/无UI仅展示问题等待，不伪造选择或自动追加Goal。
- 澄清必须单独一批；混入其他工具/多个澄清调用，整批执行前拒绝，嵌套交互旁路拒绝。复用既有tool_call检查，不新增全历史缓存或暂停metadata。仅凭stopReason不足以判定澄清：核验实际单独调用及其非错误工具结果（question/status/原生调用ID匹配）后，不进入“最终答复未绑定”的纠正。
- 保留旧binding v1格式、固定回执正文和源核验，接受旧initialize来源及新创建/恢复来源；新门禁不读取旧标记。原始Session、State、resume/restart/window字段不改。
- 已核对当前Pi1.4.0实际类型及Pi1.3.0官方npm归档：工具terminate、input、sendUserMessage及工具执行模式可用。必须先测试旧回执重载、搜索不门禁、失败创建/恢复纠正、澄清零续跑、UI实际输入/取消、混合批次无副作用，再实现；真实模型用完整环境复测模糊恢复及用户选择后的正确恢复。
