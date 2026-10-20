# Pi Long Task Agent

本仓库用于在 Pi v1.1.0 SDK 上实现长程任务记忆 Runtime。

## 开始前

1. 阅读 `AGENTS.md`。
2. 阅读 `docs/INDEX.md` 和当前任务对应的 `docs/specs/`。
3. 先执行 `docs/IMPLEMENTATION_PLAN.md` 的阶段 0，确认 Pi 的真实扩展/API 接入方式。
4. 不要在阶段 0 前生成整套业务实现。

## 文档

- `docs/ARCHITECTURE.md`：代码与运行时文件的职责边界。
- `docs/IMPLEMENTATION_PLAN.md`：分阶段 Vibe Coding 计划。
- `docs/specs/`：五份已定稿技术规范的只读副本。

源代码仓库、Pi Session 和 `~/.pi/memory/` 运行时数据必须分开存放。

## 开发与发布分离

本仓库包含开发知识库和源码，但普通用户安装的是构建后的 Pi Package，不是整个仓库。`AGENTS.md`、`docs/specs/`、测试材料只服务于开发与审计，不进入默认发布产物。Package 必须由本仓库可重复构建，不能维护第二份手工同步的源码。

发布层只负责 Pi 扩展加载、Package 元数据、运行时资源定位和版本兼容检查；不得为发布便利改变已定稿的 Task、Rule、State、Recent Window 语义。
