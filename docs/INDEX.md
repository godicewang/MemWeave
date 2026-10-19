# 技术知识库索引

`docs/specs/` 保存当前五份已定稿行为规范。实现前必须先阅读本索引，再阅读与任务对应的完整规范；只有经用户确认的设计变化才能增量同步，不能自行改写核心思想。

| 文档 | 权威范围 | 哪些任务必须读 |
|---|---|---|
| `specs/0.pi_long_task_agent_task_management_interface_v0_2_cn_updated.md` | Task/Session 关系、创建/查找/恢复/状态、索引元数据、跨 Task 引用 | Task 生命周期、索引、绑定、恢复 |
| `specs/1.1.pi_long_task_agent_rule_v1_3_final_cn_updated.md` | Rule 模板、config、热加载、Pi 接入、错误边界 | Rule、配置、启动与请求生命周期 |
| `specs/1.2.rule_v1_3_final_updated.md` | 模型实际接收的固定记忆协议 | 修改任何记忆行为、工具语义、上下文规则 |
| `specs/2.pi_long_task_agent_symbolic_state_v1_0_final_cn_updated.md` | Goal/Fact/Decision、state.json/state.md、State tools、memory_read、State 滑窗 | State、证据、原文读取、State 滑窗 |
| `specs/3.pi_long_task_agent_recent_window_v1_0_final_cn_updated.md` | 交互事件、N/B、预算、截断、提醒、窗口恢复 | Recent Window、上下文变换、回读和提交 |

## 接入与工程文档

| 文档 | 范围 | 哪些任务必须读 |
|---|---|---|
| `ARCHITECTURE.md` | 独立 SDK 宿主、Pi 适配层、资源/存储边界、未决契约 | 启动、Session 生命周期、跨模块集成 |
| `PACKAGING.md` | 应用管理 Pi 版本、锁定安装、发布白名单、兼容验收 | 依赖升级、构建、安装、发布 |
| `IMPLEMENTATION_PLAN.md` | 垂直切片顺序和阶段验收 | 所有开发任务 |

2026-10-20 确认的接入方式：MemWeave 自持 SDK 宿主，复用 Pi 原生循环与 Session，经 `src/pi/` 隔离版本差异；当前基线 v1.3.0，按应用需要升级并随新的 MemWeave 版本发布。该接入调整不改变上述五份规范的业务契约。Pi 版本、Rule v1.3、State/Window v1.0 是不同的版本标识，不能混用。

## 规则

1. 跨模块功能必须读取所有关联文档；例如 `memory_read` 至少阅读 0、1.1、1.2、2、3。
2. 规范优先级不以编号或修改时间推断。出现冲突时遵守根目录 `AGENTS.md`：停止并询问用户。
3. `docs/specs/` 是规范副本，不是让 Codex 自动润色的材料。未经用户同意不得修改。
4. Pi API 必须以应用锁定版本（当前 v1.3.0）的实际源码/类型核验；“文档说复用”不代表已通过集成测试。
5. 具体函数与等价接入细节可在适配层内调整；若影响核心设计、实际效果、业务接口、恢复或持久化语义，必须先与用户对齐并更新相关规范。
6. 固定模型模板 `specs/1.2.rule_v1_3_final_updated.md` 是实际运行资源的来源，其正文不因宿主或发布方式变化而添加工程说明；接入元数据写在本索引及技术方案中。

## 发布资源边界

`AGENTS.md`、`docs/specs/`、架构、发布方案和实现计划是开发知识库，不随普通应用整体安装。MemWeave 从同一仓库构建，使用显式发布白名单；仅从固定模板生成必要的默认 `rule.md` 等运行资源，不打包整个规格目录。用户数据、凭据、Session 与 State 不进入安装包。项目不设置独立的基线对照与评测阶段；单元、集成、恢复和真实模型功能验证仍须执行。
