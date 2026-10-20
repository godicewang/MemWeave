# Vibe Coding 实现规划

## 总原则

不要一次性让 Codex 生成完整系统。按阶段交付可运行的垂直切片；每个阶段必须有测试、可恢复的数据行为和明确验收。开始任务前先读 `AGENTS.md` 与 `docs/INDEX.md` 指定的规范。规范冲突或缺少决定时，停止并询问用户。

## 阶段 0：建仓库与 Pi 接入 Spike

不实现业务功能，先确认技术入口：
- 建立独立 Git 仓库和 TypeScript strict 配置；固定 Pi v1.1.0 依赖。
- 建最小扩展入口，验证扩展加载、工具注册、`prepareRequest`、`context` 的实际调用时序。
- 验证只关闭本 Runtime 的 auto-compaction，不影响其他 Pi 实例。
- 验证 `rule.md` 请求前读取/渲染后，下一次请求可见新参数；原生 SYSTEM/APPEND 不丢失、不重复。
- 记录真实 API 类型、入口代码和可复现的 smoke test。

**验收：** Pi 可加载扩展；请求 hook 顺序有测试；不修改用户配置文件与 Pi 核心；失败时能阻断请求。

## 阶段 0 的发布侧补充验收

在不实现业务功能的前提下，增加纯发布验证：
- 从唯一开发仓库构建本地可安装/可加载的 Pi Package；
- 检查 Package 不含 `AGENTS.md`、`docs/specs/`、测试或运行时状态；
- 从干净 Pi 环境加载 Package，验证工具注册、扩展 hook 和 Rule 资源定位；
- 验证运行时数据仍写入 `~/.pi/memory/`，而非 Package 目录；
- 记录确切 Pi 版本、实际 manifest 字段、安装/加载命令和 smoke test 结果。

本阶段不要求发布到 npm 或公开注册表；先完成本地可重复构建和安装验证。manifest 依据 Pi v1.1.0 实际支持的机制确定。

## 阶段 1：配置与 Rule

- 实现 `config.json` schema、默认值和非法配置错误。
- 实现白名单 `{{name}}` 替换；未知变量、缺失值、未闭合占位符必须失败。
- 每次主会话请求准备时读取 Rule；Rule、Window 选择和预算使用同一份配置快照。
- 保留原生提示词发现与信任行为。
- 在覆盖值持久化位置尚未确认前，只实现接口与测试替身，不自行决定文件格式。

**验收：** 参数变更后下一次请求生效；模板错误阻断发送；reload 不重复 Rule；不同 Session 不互相污染。

## 阶段 2：Task 管理

实现 `task_create/find/resume/status`、全局索引元数据、当前 Session/branch Task 绑定。Agent 创建 Task 时生成项目名、摘要和关键词；Goal 改变时同步更新摘要/关键词。

**验收：** 一个 Session 可切换多个 Task；Task 可跨 Session 恢复；`task_find` 只发现不恢复；`task_resume` 明确切换；多 Pi 窗口不会通过共享的 `current_task` 互相切换。

## 阶段 3：Symbolic State 最小闭环

先实现 JSONL event store、schema validation、ID 生成、evidence 校验、reducer、`state.md` renderer，再注册 `state_append/update_goal/modify_fact/state_read/state_remain`。

接着实现 State 活动窗口：
- `state_remain` 只接受本批候选事件，保留数量同时受 1/10、KEEP_LIMIT、候选数量约束。
- `slide_window` 轨迹追加到 `state.json`。
- `batch_id` 幂等；持久化失败不推进活动窗口、不清除提醒。
- `state.md` 可从事件记录重建。

**验收：** 重建前后 State 一致；非法 evidence 被拒绝；同批重试不重复追加/滑动；失败后能恢复待处理批次。

## 阶段 4：Recent Window

实现完整交互事件索引、N/B 选择、统一正文截断、最新真实用户消息豁免、末尾 State 注入、两类临时提醒及 Recent Window 提交生命周期。

- 每条真实用户消息为独立事件。
- 一次 assistant 返回及其全部关联工具结果为一个完整事件。
- 提醒不进入 Session、不计入事件数。
- 为让模型检查待移出内容，提醒请求可以临时包含待移出批次。
- `state_append` 与 Window 滑动是独立提交；前者失败不伪造成功，也不重复推进后者。
- 扩大窗口必须从原始 Session 重新选取，不能拼接已截断文本。

**验收：** 工具调用/结果不拆分；边界正确；扩大窗口能恢复原文；失败重试不重复移动；原始 Session 未被改写。

## 阶段 5：`memory_read`

实现统一已知引用读取工具，支持批量 refs、字符 `offset`、单条 `limit`、总字符上限和完整性状态。底层复用 Pi SessionManager 与文件读取；不引入摘要模型。

**验收：** U/A/T/R 的映射正确；跨 Task 不会误读同编号；offset/limit 与总预算符合契约；一个无效引用不会掩盖其他成功结果；无原件时不谎称完整。

## 阶段 6：恢复、并发与端到端集成

测试重启、分支切换、多个 Pi 进程、配置覆盖、工具并行调用、磁盘写入失败、重复请求、状态重建和旧 Session 兼容边界。先解决 `ARCHITECTURE.md` 列出的待确认点，再做相应实现。

## 每个阶段的交付格式

- 修改文件与模块；
- 依据了哪些规范章节；
- 运行过的测试命令与真实结果；
- 未运行/未验证的测试；
- 新发现的规范冲突和待用户决定事项；
- 明确确认没有改动的无关文件。


## 发布准备（不改变核心实现）

核心功能通过集成测试后：
1. 从仓库源码生成可重复构建产物，不维护手工复制的第二套源码。
2. 对构建产物执行文件白名单检查，不包含开发规范、内部技术规格、测试、用户数据或秘密。
3. 验证安装、升级、禁用/卸载；卸载不得自动删除 `~/.pi/memory/` 中的用户记忆。
4. 对 Pi v1.1.0 做完整验收；后续版本逐版本建立兼容矩阵，只有通过测试才标记支持。
5. 若 Pi API 变化，先尝试只调整 `src/pi/`；若需要改变核心方案或已定稿协议，必须询问用户。
