# MemWeave

MemWeave 是复用 Pi 底层能力的独立长程任务记忆应用：通过适配层使用 Pi 原生 Agent Loop、Session、模型/工具及交互界面，在其上实现 Task、Symbolic State、Recent Window 和 Rule。

当前接入基线为 Pi v1.3.0。Pi 版本由 MemWeave 应用锁定；后续按需要适配、验收并发布新的 MemWeave 版本，用户全局 Pi 的升级不自动替换应用引擎。

## 开始前

1. 阅读 `AGENTS.md`。
2. 阅读 `docs/INDEX.md` 和当前任务对应的 `docs/specs/`。
3. 先执行 `docs/IMPLEMENTATION_PLAN.md` 的阶段 0，完成 SDK 宿主、实例隔离与应用入口的接入验收。
4. 不要在阶段 0 前生成整套业务实现。

## 文档

- `docs/ARCHITECTURE.md`：代码与运行时文件的职责边界。
- `docs/PACKAGING.md`：应用版本、锁定依赖、安装和发布验收。
- `docs/IMPLEMENTATION_PLAN.md`：分阶段 Vibe Coding 计划。
- `docs/specs/`：五份已定稿技术规范；未经确认不得更改核心设计或行为契约。

源代码仓库、Pi Session 和 `~/.pi/memory/` 运行时数据必须分开存放。

## 开发与发布分离

本仓库包含开发知识库和源码；普通用户安装构建后的 MemWeave 应用，在业务工作目录运行 `memweave`，无需自行匹配全局 Pi 版本。`AGENTS.md`、`docs/specs/`、测试和评测材料不进入默认发布产物。发布必须从本仓库可重复生成，不能维护第二份手工同步的源码。

宿主与适配层负责 SDK 接线、每实例 compaction 隔离、资源定位和兼容检查；不得为发布便利改变已定稿的工具协议、记忆语义、窗口规则或存储格式。完整 Runtime 当前采用 SDK 应用入口，普通 Pi Package 仅保留为未来有条件的渠道。

目前仓库处于规范与接入准备阶段，尚未实现上述应用命令。Pi v1.3.0 的临时可行性验证范围与待完成验收见 `docs/PACKAGING.md`，不代表完整产品已通过测试。
