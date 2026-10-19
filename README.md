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

本仓库包含开发知识库和源码；普通用户安装构建后的 MemWeave 应用，在业务工作目录运行 `memweave`，无需自行匹配全局 Pi 版本。`AGENTS.md`、`docs/specs/` 和测试不进入默认发布产物。发布必须从本仓库可重复生成，不能维护第二份手工同步的源码。

宿主与适配层负责 SDK 接线、每实例 compaction 隔离、资源定位和兼容检查；不得为发布便利改变已定稿的工具协议、记忆语义、窗口规则或存储格式。完整 Runtime 当前采用 SDK 应用入口，普通 Pi Package 仅保留为未来有条件的渠道。

目前已建立全部模块目录，并实现阶段 0 的 SDK 宿主和锁定安装切片：Pi 版本检查、每实例 compaction 隔离、无界面项目信任接线、请求准备/组装/发送检查、原生 Session 生命周期复用，以及可重复构建、安装与版本回切。`memweave` 当前提供帮助、版本和安装管理，尚未连接交互式 TUI 和长程记忆业务。配置/Rule、Task、State、Window、memory_read 目录暂未实现业务逻辑。

## 本地开发

当前验证环境为 Node.js 24.22.0、npm 11.19.1；在仓库根目录执行：

```sh
npm ci --ignore-scripts
npm run check
node dist/cli/index.js --version
```

本机已配置的独立工具链可通过 `memweave-dev npm run check` 使用。普通测试运行真实 Pi SDK 与模型测试替身，不发起供应商请求；真实 DeepSeek 验证单独运行，凭据保存在仓库外：

```sh
MEMWEAVE_LIVE_AGENT_DIR=/path/to/private/pi-agent npm run test:live
```

开发入口与边界见 `src/pi/README.md`；当前兼容证据和剩余阶段 0 验收见 `docs/PACKAGING.md`。基础切片通过测试不代表完整记忆产品已经完成。

生成本地安装产物：`npm run release:build -- --out <不存在的新目录>`。当前仅验收 macOS arm64、Node 24.22.0、npm 11.19.1；安装、更新、回切和卸载见 [安装指南](docs/INSTALL.md)。尚未发布 GitHub Release。
