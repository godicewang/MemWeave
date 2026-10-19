# 技术知识库索引

`docs/specs/` 是当前五份已定稿规范的只读副本。实现前必须先阅读本索引，再阅读与任务对应的完整规范。

| 文档 | 权威范围 | 哪些任务必须读 |
|---|---|---|
| `specs/0.pi_long_task_agent_task_management_interface_v0_2_cn_updated.md` | Task/Session 关系、创建/查找/恢复/状态、索引元数据、跨 Task 引用 | Task 生命周期、索引、绑定、恢复 |
| `specs/1.1.pi_long_task_agent_rule_v1_3_final_cn_updated.md` | Rule 模板、config、热加载、Pi 接入、错误边界 | Rule、配置、启动与请求生命周期 |
| `specs/1.2.rule_v1_3_final_updated.md` | 模型实际接收的固定记忆协议 | 修改任何记忆行为、工具语义、上下文规则 |
| `specs/2.pi_long_task_agent_symbolic_state_v1_0_final_cn_updated.md` | Goal/Fact/Decision、state.json/state.md、State tools、memory_read、State 滑窗 | State、证据、原文读取、State 滑窗 |
| `specs/3.pi_long_task_agent_recent_window_v1_0_final_cn_updated.md` | 交互事件、N/B、预算、截断、提醒、窗口恢复 | Recent Window、上下文变换、回读和提交 |

## 规则

1. 跨模块功能必须读取所有关联文档；例如 `memory_read` 至少阅读 0、1.1、1.2、2、3。
2. 规范优先级不以编号或修改时间推断。出现冲突时遵守根目录 `AGENTS.md`：停止并询问用户。
3. `docs/specs/` 是规范副本，不是让 Codex 自动润色的材料。未经用户同意不得修改。
4. Pi API 必须以锁定的 v1.1.0 实际源码/类型核验；“文档说复用”不代表已通过集成测试。

## 发布资源边界

`AGENTS.md`、`docs/specs/`、`ARCHITECTURE.md`、`IMPLEMENTATION_PLAN.md` 是开发知识库，不是普通 Pi Package 的运行资源。Package 从同一仓库构建，但使用显式发布白名单。只有运行时真正需要的资源才进入发布产物。
