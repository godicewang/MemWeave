# AGENTS.md — Pi Long Task Agent

## 1. 项目定位

本项目是在固定版本 Pi Agent SDK 之上构建的长程任务记忆 Runtime，不是 Pi 的 fork，也不是重新实现一套 Agent Loop。

第一阶段目标：Task 管理、Task 级 Symbolic State、基于 Pi Session 的 Recent Window、已知引用的原文读取、Rule 模板请求前渲染，以及可复现的基线与轻量评测。

第一阶段不实现子 Agent、task_fork、独立摘要 Agent、第二套全量 Session 存储、独立 Memory Operation Log 或通用 Workflow Engine。

## 2. 技术规范是实现的先决条件

开始任何模块实现前，必须先阅读 `docs/INDEX.md` 中映射到该模块的全部规范，再检查 Pi v1.1.0 的实际类型定义和源码。

`docs/specs/` 中的五份文档是当前行为契约：
- `0.*`：Task Management Interface v0.2
- `1.1.*`：Rule 技术方案 v1.3
- `1.2.*`：Rule 固定提示词模板 v1.3
- `2.*`：Symbolic State v1.0
- `3.*`：Recent Window v1.0

不得用 README、代码注释、旧草稿或模型推断静默覆盖规范。

### 必须追问的情况

遇到以下任一情况，必须停止相关实现并向用户提出具体问题：
1. 规范之间对行为、字段、接口、默认值、持久化格式或提交边界存在冲突；
2. 规范缺少实现必需的决定，且不能唯一推导；
3. Pi v1.1.0 实际 API 与规范假设不一致；
4. 存在多个会改变外部行为、恢复语义或数据格式的合理方案；
5. 需求目标、权限边界或验收标准不清楚。

问题必须说明：冲突文档和原文位置、对实现的影响、可选方案、推荐方案与理由。不得自行选方案后再将其表述为已定稿。

纯内部实现细节若不改变规范的外部行为，可选择最简单且可测试的方案，并在交付摘要中说明。

### 文档维护规则

- 未经用户明确同意，不修改 `docs/specs/` 中的定稿文档。
- 用户确认设计变化后，先更新相关规范，再实现代码。
- 若实现过程中发现规范错误或缺口，先报告并等待确认。
- 新工具、参数、持久化字段、事件类型、状态迁移都属于契约变更，必须先讨论。
- 已确认的变更只同步修改直接相关的文档，保持最小 diff。

## 3. 固定技术边界

- Pi 基线固定为 v1.1.0。优先使用 SDK 和扩展公开接口。
- 不修改 Pi 核心源码、不 fork Agent Loop，除非用户另行批准。
- 原始交互历史由 Pi Session 保存；禁止另建全量聊天副本。
- 源代码放在独立开发仓库，例如 `~/code/pi-long-task-agent/`。
- 运行时数据放在 `~/.pi/memory/`，不得写入业务项目仓库。
- `~/.pi/memory/config.json` 保存全局默认值；Session/分支运行时覆盖必须隔离，避免多个 Pi 进程互相覆盖设置。
- `rule.md` 独立维护并在请求准备阶段读取；仅支持白名单 `{{variable}}` 替换。禁止 eval、表达式、递归模板，禁止处理用户自己的 SYSTEM/APPEND 文本。
- 保留 Pi 原生 SYSTEM/APPEND/AGENTS 的发现、信任和优先级，不修改或静默屏蔽用户文件。
- 请求语义顺序为 Rule → Recent Window → State；State 和提醒是请求级临时内容，不写入 Session、不参与真实交互事件计数。
- 关闭本 Runtime 的自动 compaction；不得默认生成历史摘要兜底。
- 保留原生 tool call ID、arguments、tool result 配对、供应商要求的 reasoning/signature 字段和多模态结构。
- `memory_read` 读取已知引用；`task_find` 模糊查找 Task；`state_read` 只读取 State；`task_resume` 才切换当前 Task。
- State 类型仅 Goal / Fact / Decision，不新增 Plan、Hypothesis 或知识图谱。

## 4. 开发仓库、运行时与发布包的边界

本项目采用**一个开发仓库构建一个 Pi Package**，不维护第二份平行源码，也不把开发知识库作为普通用户的运行时资源。

- Git 仓库是唯一开发源，包含 `AGENTS.md`、`docs/specs/`、设计文档、测试、评测和源码。
- Pi Package 是由仓库构建出的发布产物，只包含用户运行所需的扩展入口、必要运行时资源及 Package 元数据。
- `AGENTS.md`、`docs/specs/`、`IMPLEMENTATION_PLAN.md`、测试代码和评测材料默认不进入普通用户安装包。
- `~/.pi/memory/` 是运行时数据目录，与 Git 仓库、Pi Package 安装目录分离。
- 不因发布或兼容性要求修改 Task、State、Recent Window、Rule 的既定语义、接口或持久化协议。
- 不为每个 Pi 版本复制业务实现；差异只允许收敛在 `src/pi/` 适配层及 Package 元数据/构建配置。
- 优先使用 Pi 公开的扩展/Package 接口。禁止 fork Pi、patch `node_modules`、复制 Pi 核心源码或静默降低功能。
- 未验证的 Pi 版本不得宣称兼容；若公开 API 缺失或语义变化，先报告用户。
- 发布构建必须从当前仓库可重复生成；不手工维护另一份 Package 源码树。

默认发布：扩展运行代码、Package 必需元数据、必要运行时资源和用户安装说明。
默认不发布：`AGENTS.md`、`docs/specs/`、内部方案文档、测试/评测、开发脚本、用户数据、密钥、Session 或 State 文件。

## 5. 模块职责

| 模块 | 负责 | 不负责 |
|---|---|---|
| `src/extension/` | Pi 扩展入口、生命周期、工具/hook 注册 | 实现所有业务逻辑 |
| `src/config/` | 配置 schema、默认值、校验、全局默认与实例覆盖 | 改写 Rule |
| `src/rule/` | `rule.md` 请求前读取、变量白名单替换、模板校验 | Window 选取、State 业务逻辑 |
| `src/task/` | Task 创建/查找/恢复/状态、索引、当前绑定 | 保存全量消息、State reducer |
| `src/state/` | State tools、追加事件记录、reducer、state.md、State 窗口轨迹 | Pi Session 历史选取 |
| `src/window/` | 完整交互事件索引、窗口选取、预算、截断、待处理批次与提醒 | 长期事实维护 |
| `src/memory/` | `memory_read`、U/A/T/R 解析、原件读取适配 | 模糊 Task 发现、修改 State |
| `src/pi/` | Pi v1.1.0 API 适配、SessionManager 封装、请求 hook 适配 | 新增业务规则 |
| `src/storage/` | 路径、原子写、JSONL 追加、幂等工具 | Task/State 语义 |
| `tests/unit/` | schema、reducer、窗口算法、模板函数测试 | 依赖真实供应商 |
| `tests/integration/` | Pi Session、extension hook、工具流程集成测试 | 取代单元测试 |
| `eval/` | 基线配置、对照实验与结果汇总 | 生产运行时状态 |

跨模块交互必须通过清晰的小接口，不允许直接改写其他模块的私有文件格式。

## 6. 文档优先的开发流程

每个开发任务必须：
1. 阅读 `docs/INDEX.md` 指定的规范文档及相关章节。
2. 核对 Pi v1.1.0 的实际 API/类型，不能只依赖记忆或最新版文档。
3. 列出要改文件、接口影响和验收测试；发现歧义先追问。
4. 先写可验证边界的测试，再实现。
5. 只做完成任务所需的最小修改，不顺手重构无关模块。
6. 运行相关单测、类型检查；涉及 Pi hook/Session/工具时运行集成测试。
7. 检查 Session 未被改写、临时提示未持久化、窗口计数正确、重试不会重复提交。
8. 汇报修改文件、真实运行过的测试与结果、未验证部分和风险。

不得声称测试通过，除非实际执行并观察到通过结果。Mock 测试与真实 Pi/模型集成必须分开报告。

## 7. 实现顺序

遵循 `docs/IMPLEMENTATION_PLAN.md`。每阶段先完成一个可运行的垂直切片再继续；不要同时改动 Rule、State、Window 的持久化契约。

## 8. 代码质量

- TypeScript 严格模式；所有外部输入做 schema 校验。
- 文件写入要处理部分失败、进程并发和重试幂等。
- 时间、ID、路径生成集中封装，业务模块不自行拼路径。
- 运行时路径只由 `src/storage/paths.ts` 提供。
- 错误要可诊断，不吞异常、不返回伪成功。
- 公开工具的描述、参数、返回示例与规范一致。
- 不为了“可扩展”提前创建抽象层；仅在真实调用边界上模块化。
