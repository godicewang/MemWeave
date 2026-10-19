# Pi Package 发布层设计

## 目标

让 Pi 官方 CLI 用户可通过 Package 机制安装本项目，同时让 SDK/二开用户复用同一套 Runtime。发布适配不得改变已定稿的记忆核心方案。

## 原则

1. 一个 Git 仓库、一个源码真相源；Package 是构建产物，不是第二份源码。
2. `AGENTS.md`、`docs/specs/`、测试、评测和内部实现计划默认不进入普通 Package。
3. 运行时状态放在 `~/.pi/memory/`，不写入 Package 安装目录。
4. 优先使用公开 Pi Package/Extension API；不 fork、不 patch Pi 核心、不修改用户 SYSTEM/APPEND。
5. 兼容性以测试为准；未通过的版本标为未验证，不静默降级。
6. 核心记忆语义、工具 schema、事件模型和持久化格式不能为发布便利而改变。

## 本地实现顺序

1. 核对 Pi v1.1.0 官方 Package 文档及当前 CLI/SDK 类型。
2. 建立最小 manifest 和扩展入口，做本地构建、安装/加载 smoke test。
3. 检查构建产物，仅包含运行必需资源。
4. 从干净 Pi 环境验证启用、禁用和重启。
5. 测试通过后，再决定 npm/Git 等正式分发渠道。

## 兼容矩阵

| Pi 版本 | Package 可安装 | 扩展可加载 | 工具注册 | Rule/Context hook | Session 恢复 | 状态 |
|---|---|---|---|---|---|---|
| v1.1.0 | 待测 | 待测 | 待测 | 待测 | 待测 | 未验证 |

编译通过不等于版本兼容。每个宣称支持的版本必须通过 smoke/integration tests。
