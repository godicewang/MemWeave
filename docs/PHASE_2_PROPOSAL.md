# 阶段 2 持久化与恢复方案（已确认）

日期：2026-10-21。用户已明确同意本草案；下列决定同步到直接相关规范后实施。

## 第一部分：目的、范围与取舍

这次补齐“任务如何跨会话续接、记忆如何可靠保存”的基础能力。实现四个 Task 工具和最小 State 写入，让下一次模型请求能看到当前任务认知；不会提前开启历史裁剪或完整 State 窗口管理。

引用和任务绑定保存在 Pi 自己的会话元数据中，任务索引只登记来源位置。优点是继续复用 Pi 的历史和分支，不保存第二份聊天；代价是这些来源 Session 文件不能随意删除，丢失时必须报错。不同分支共享同一 Task 的 State，所以回退聊天不会撤销已提交认知。创建或恢复任务会将其标记为 active，但切换任务不会自动暂停其他会话仍在使用的任务。

State 整批原子提交，重试不会重复记账；代价是目前每批提交需要重写日志文件，长期日志可能增加写入成本。State 提交后若索引、展示文件或 Session 绑定失败，会明确报告部分完成，不能把跨文件操作伪装成一个全有或全无的事务。

## 第二部分：技术细节

## 需要补齐的契约

- `ARCHITECTURE.md` §5、`IMPLEMENTATION_PLAN.md` 阶段 2 进入条件明确要求先确认引用定位、Task 绑定与实例覆盖位置。
- Task 规范 §1/§5 支持一个 Task 跨多个 Session，但没有定义引用登记、当前分支绑定和状态迁移的持久化方式。
- State 规范 §4/§5/§9 要求 Task 级编号、批量提交和证据校验，但未明确版本递增单位及批量重试的提交标识。

以下三组决定已确认。实现仍保持 Task 级 State、Pi Session 唯一原始历史、Rule → Recent Window → State，以及 Goal / Fact / Decision 三类认知。

## 1. 引用定位：Pi custom 条目＋索引中的 Session 来源登记

推荐把 U/A/T 的定位元信息保存为 Pi 原生 `custom` 条目；Task 索引只增加少量 Session 来源定位，不保存消息正文或逐消息映射。另一方案是在 `state.json` 中增加引用登记操作，但会让认知事件流同时承担会话定位职责，因此不推荐。

确认结构：

```json
{
  "customType": "memweave.references.v1",
  "data": {
    "task_id": "task_xxx",
    "source_session_id": "pi-session-id",
    "bindings": [
      {"ref": "U1", "entry_id": "native-user-entry-id"},
      {"ref": "A1", "entry_id": "native-assistant-entry-id"},
      {"ref": "T1", "entry_id": "native-tool-result-entry-id", "tool_call_id": "native-tool-call-id"}
    ]
  }
}
```

`index.json` 使用 Task 对象数组；沿用既有任务字段，并增加 `updated_at` 与 `sessions: [{session_id, file}]`。`workspace` 与 State 路径仍沿用 Pi 的 cwd identity。索引只负责发现与来源登记，不成为 State 事实源。

引用分配前持有 Task 级写锁，检查该 Task 已登记的 Session 引用，再继续各自的 U/A/T 编号。fork 复制的既有引用按原来源去重，不重新编号；新增消息才取新编号。重启从已提交条目恢复，不靠进程变量。正常运行可缓存并增量核验，不能每轮重建全部历史。来源文件缺失/损坏时明确诊断，不以空历史重置计数。

只在确认工具结果已存在后承认 T 证据；State 和 Rule 不分配 U/A/T。阶段 2 提供引用展示与存在性校验，完整 `memory_read` 工具仍在阶段 4 实现。

## 2. Task 绑定和配置覆盖：随 Pi 分支继承；State 由 Task 共享

推荐统一保存在另一个原生 custom 类型中：

```json
{
  "customType": "memweave.scope.v1",
  "data": {
    "task_id": "task_xxx",
    "overrides": {"recent_turns": 200, "evict_turns": 40}
  }
}
```

读取当前分支祖先链上最后一条有效记录；`task_id: null` 表示无绑定，`overrides` 只允许已有六个配置字段。分支内覆盖优先于全局默认；切换 Task 不自动重置该分支的窗口设置。配置设置工具仍按后续阶段实现，本阶段不新增设置工具。

- `/tree` 回退恢复目标分支绑定/覆盖，fork 继承分叉点的记录；普通新 Session 不继承其他 Session 的当前 Task。
- 分支切换后追加本扩展自己的 scope 记录，锚定恢复后的叶子；不改写原始消息。
- **State 始终由 Task 共享。回退 Pi 分支不会撤销已提交的 Fact/Decision；要试不同方向仍使用同一个 Task 的演化记录。** 另一方案是按分支保存 State 快照，会改变既定的 Task 级 State，故不推荐。
- 切换前已归属旧 Task 的消息/工具保持原归属，后续交互归属新 Task。首次创建 Task 时，可把本次尚未归属任何 Task 的触发用户消息及创建这一轮的 assistant/工具关联到新 Task；不吸收全部未绑定历史，也不把旧 Task 的消息重新编号。
- `task_resume` 只加载目标认知和更改绑定，保留当前恢复过程，不批量载入目标 Task 的旧聊天，不切换 cwd。

## 3. 提交、版本和任务状态

推荐的最小实现约定：

- 初始 Goal 作为既有 `update_goal` 记录写入，初始 `state_version=1`。版本按成功提交的 State 操作记录计数；一批新增多个 F/D 时各自为一个操作，不把一次批量调用误当成一条事件。
- 沿用既有 `op_id`：根据 Task、Pi Session、来源 assistant entry ID、原生 tool call ID 和条目序号生成稳定标识；不能假设单个 tool call ID 在不同轮次间永不重复。同一原生调用重试不重复追加；新的工具调用不是旧事务的自动重放。
- 在 Task 写锁下完整校验 evidence/输入，再以原子替换提交“原 JSONL＋本批新记录”；旧记录字节保持不变，不保存 State 快照，不新增事务日志。优先保证整批提交；长日志写入成本后续按实测优化。
- `state.json` 为认知提交点，`state.md` 与索引中的版本是可重建信息。派生写入或绑定失败须明确说明已提交部分、失败阶段和 Task ID，不把失败当成成功，也不撤销已经提交的认知。Pi Session 写入失败后停止相关流程，不能仅以其内存视图存在条目判断已落盘。
- Task 创建/恢复将目标设为 `active`；切换、关闭或回退 Session 不自动把共享 Task 改为 `paused`，避免影响其他仍在使用它的 Session。`task_status.running` 仅表示当前 Pi 实例是否正在执行该 Task，不冒充跨进程运行注册表。
- **当前规范没有暂停/完成工具。阶段 2 不擅自增加新工具；`latest_paused` 支持查询和恢复已有 paused 记录，但本阶段不会自动产生暂停状态。** 若希望本阶段具备主动暂停/完成入口，应另行确认工具与状态迁移后纳入实现。

为避免实现时继续追问琐碎输入细节，建议同时明确：`task_create` 的 title/goal/project_name/summary/keywords 必填且非空，context 可选；`task_find` 的 query 必填、keywords 默认为空数组、limit 默认为 5 且为正整数；`task_status` 的 task_id 按现有示例必填；`task_resume` 两种输入互斥；`state_append` 为非空批量，正文按 Unicode 码点校验已有字符上限，不截断保存。字段名称与现有工具保持一致。同一轮存在多个 Task 切换调用，或混合 Task 切换与 State 写入时，拒绝冲突调用，避免依赖并行执行顺序决定归属。

## 已执行的 Pi v1.3.0 临时验证

只使用公开 SessionManager，代码从标准输入执行，Session/故障夹具放在系统临时目录；结束后均删除。未调用真实模型 API，未触碰用户 Session/私有配置。

实际确认：

1. 当前分支可恢复祖先上的 custom 绑定，其他分支记录仍完整保留。
2. **仅调用 `branch()` 移动内存叶子不保证重启恢复该叶子。** 追加自有 custom 锚定后，重开 Session 可恢复正确绑定。
3. fork 继承分叉点 custom 记录；两个 Session 的绑定可独立保存。
4. custom 元数据不会进入 `buildSessionContext()` 的模型消息。
5. **Session 追加写入失败可能已改变 Pi 内存视图。** 故障后重新打开磁盘 Session，没有那个失败条目；“内存里能查到”不能作为持久化成功证据。
6. 两个 Session 的既有 U1/U2 定位可以从 custom 条目重建；fork 复制的 U1 按原来源去重后，下个用户编号为 U3，原始消息仍可由来源 Session entry 读取。

这些结果只验证 Pi 接入能力，不表示阶段 2 业务已经实现。

## 实现与验收范围

先增量同步直接相关规范/架构，再实现 storage、State schema/reducer/renderer、引用与绑定适配、四个 Task 工具及 `state_append`。验证创建 → 证据 → 保存 → 下一请求 State → 重启/跨 Session 恢复，并覆盖整批失败、同调用重试、分支和双实例隔离。真实模型闭环继续复用仓库外既有 DeepSeek 配置。

Recent Window 裁剪、完整 State 滑窗和原文读取工具按既有阶段推进。阶段 2 完成相关验证后形成清晰 commit，并按重要里程碑规则统一 push。
