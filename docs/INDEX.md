# 技术知识库索引

`docs/specs/` 是当前五份已定稿行为规范。实现前必须先阅读本索引，再阅读与任务对应的完整规范；设计不合理时主动提出，经用户确认后增量维护。

| 文档 | 权威范围 | 哪些任务必须读 |
|---|---|---|
| `specs/0.pi_long_task_agent_task_management_interface_v0_2_cn_updated.md` | Task/Session 关系、创建/查找/恢复/状态、索引元数据、跨 Task 引用 | Task 生命周期、索引、绑定、恢复 |
| `specs/1.1.pi_long_task_agent_rule_v1_3_final_cn_updated.md` | Rule 模板、config、热加载、Pi 接入、错误边界 | Rule、配置、启动与请求生命周期 |
| `specs/1.2.rule_v1_3_final_updated.md` | 模型实际接收的固定记忆协议 | 修改任何记忆行为、工具语义、上下文规则 |
| `specs/2.pi_long_task_agent_symbolic_state_v1_0_final_cn_updated.md` | Goal/Fact/Decision、state.json/state.md、State tools、memory_read、State 滑窗 | State、证据、原文读取、State 滑窗 |
| `specs/3.pi_long_task_agent_recent_window_v1_0_final_cn_updated.md` | 交互事件、N/B、预算、截断、提醒、窗口恢复 | Recent Window、上下文变换、回读和提交 |

## 工程文档与已确认接入方式

| 文档 | 权威范围 |
|---|---|
| `ARCHITECTURE.md` | 原生扩展的数据流、模块/存储边界、待确认契约 |
| `PACKAGING.md` | npm/Git 分发、宿主依赖、四项副作用及兼容验收 |
| `IMPLEMENTATION_PLAN.md` | 当前进度、阶段依赖、交付范围和进入条件 |

2026-10-20 确认：以原生 Pi 扩展和 Pi Package 交付，首个宿主验收目标 v1.3.0。Rule 渲染与 Window/State 在同一个 `context_with_system` 请求处理中组装；失败时主动取消。用户接受共享压缩设置、压缩恢复记录、宿主版本由用户决定及扩展共存/缓存限制，具体范围见 `PACKAGING.md`。这次接入调整不改变 Task/State 工具和持久化协议，也不改变 Window 计数、Q 公式与固定 Rule 正文。

同日另行确认容量与默认值：Agent 请求总预算 `C = floor(C_model / 2)`，包含输入及输出预留，定义见 Recent Window §5.1；Recent Window 默认 N=200、B=40；State 默认容量 2000、每批管理 200，单事件正文 100 字符与保留上限 20 不变。配置契约见 Rule 技术稿 §3，State 滑窗见 State §7；固定 Rule 两份副本同步更新默认值。N/B 默认值已确定，不再列为待确认项；持久化位置的既有缺口仍须单独确认。

## 规则

1. 跨模块功能必须读取所有关联文档；例如 `memory_read` 至少阅读 0、1.1、1.2、2、3。
2. 规范优先级不以编号或修改时间推断。出现冲突时遵守根目录 `AGENTS.md`：停止并询问用户。
3. `docs/specs/` 是规范副本，不是让 Codex 自动润色的材料。未经用户同意不得修改。
4. Pi API 必须以目标宿主（首个目标 v1.3.0）实际源码/类型核验；“文档说复用”不代表已通过集成测试；开发依赖锁不锁定用户的宿主 Pi。
5. Pi 引擎版本、Rule v1.3、State/Window v1.0 是不同版本标识。只调整接线不自动升级业务协议，未确认的默认值与持久化位置不得自行补定。

## 发布资源边界

`AGENTS.md`、`docs/specs/`、`ARCHITECTURE.md`、`IMPLEMENTATION_PLAN.md` 是开发知识库，不是普通 Pi Package 的运行资源。npm 归档使用发布白名单；Git checkout 可含开发资料，但 `pi` manifest 只加载扩展入口及必要资源。固定 Rule 资源从 `specs/1.2.rule_v1_3_final_updated.md` 生成，不能把整个规范目录注入模型。独立的基线与评测阶段已删除，功能、恢复、安装与真实模型验证仍保留。
