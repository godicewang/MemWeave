# MemWeave 应用发布与 Pi 版本管理

## 目标

让 GitHub 用户一次安装 MemWeave，即可在业务目录通过 `memweave` 使用长程记忆能力，无需匹配全局 Pi 版本。应用自持 SDK 宿主，在适配层内复用固定版本 Pi 的循环、Session、模型/工具与原生 TUI；后续其他入口复用同一 Runtime。发布适配不得改变已定稿的记忆核心方案。

## 原则

1. 一个 Git 仓库、一个源码真相源；应用发布产物及安装清单从该仓库生成，不是第二份源码。
2. `AGENTS.md`、`docs/specs/`、测试、评测和内部实现计划默认不进入普通应用；固定模板仅导出必要的默认 `rule.md` 运行资源。
3. 运行时状态放在 `~/.pi/memory/`，不写入应用安装目录。配置/凭据与 Session 继续使用用户的 Pi 原生路径，不为隔离压缩切换 `agentDir`。
4. 优先使用公开 Pi SDK/Extension/UI API；不 fork、不 patch Pi 核心、不修改用户 SYSTEM/APPEND。
5. 兼容性以测试为准；未通过的版本标为未验证，不静默降级。
6. 核心记忆语义、工具 schema、事件模型和持久化格式不能为发布便利而改变。

## Pi 版本由应用选择

- 当前接入基线为 `@earendil-works/pi-coding-agent@1.3.0`。每个 MemWeave 版本记录其 SDK 精确版本、完整依赖锁、构建环境和兼容验收结果；不同应用版本可按需要选择不同 Pi 版本，不追随上游每次更新。
- 用户全局 `pi` 的版本和 `pi update` 不决定 MemWeave 的引擎。安装不能覆盖用户全局 Pi；应用自身的升级/恢复指引也必须指向 MemWeave，不能把用户带回未装 Runtime 的裸 Pi。
- 升级顺序：核对目标版本公开类型/源码与变更 → 调整 `src/pi/` 和依赖/构建配置 → 跑类型、生命周期、协议保真及端到端验收 → 发布新的 MemWeave 版本。没有必要时继续使用已验证版本。
- 核心 Pi 包保持一致版本与单一模块实例，避免工具类型、provider 注册表重复；不使用 `latest`、`^` 等范围声明当前引擎兼容性。依赖解析结果以锁文件和安装验收为准，不维护按 Pi 版本复制的业务实现。
- 锁定引擎不能消除外部变化：第三方扩展、共享配置以及被其他 Pi 版本写过的 Session 仍须兼容检查。原生 Session 格式版本与 SDK 版本分开记录；遇到不支持的格式/能力明确报错，不静默修改数据或降低功能。

## 正式分发与锁定安装

首期正式渠道采用 GitHub Release 的锁定应用安装产物：同一次构建生成运行代码、必要资源、版本信息、校验值及最小安装 manifest/`package-lock.json`。安装在独立的版本目录或暂存目录使用已验证的 Node/npm 与 `npm ci` 还原依赖，检查成功后再切换 `memweave` 入口；失败保留原可用版本。具体安装路径、支持平台与 Node/npm 版本经阶段 0 的干净环境验收后写入用户指南，不提前宣称已实现。

构建锁与安装锁都必须对应本次产物；不能认为仓库中提交了 `package-lock.json`，普通 `npm install -g` 就会按同一传递依赖树安装。npm 渠道可作为后续便利入口，但仍须证明安装结果受控；不能依赖 npm v12 已忽略的 `npm-shrinkwrap.json` 作为跨 npm 版本保证。[npm 锁文件说明](https://docs.npmjs.com/cli/v12/configuring-npm/package-lock-json/)

第一阶段不开发通用自动更新系统；先完成可重复安装、版本切换、失败恢复和卸载。回切应用版本不等于回退数据格式；降级前检查 Session/State 的兼容性，不能自动重写历史。卸载应用不自动删除用户配置、凭据、Session 或 `~/.pi/memory/`，升级也不覆盖用户维护的 `rule.md`。

默认发布白名单：CLI、Runtime、Pi 适配层及宿主内扩展代码，必要运行资源，安装/版本/依赖元数据，用户说明与依赖许可材料。默认排除开发知识库、测试/评测、开发脚本、用户数据和密钥。发布产物必须从当前仓库重建，不维护另一份手工更新的发布源码树。

## 与普通 Pi Package 的关系

当前完整 Runtime 以独立 SDK 应用交付，内部仍使用原生扩展工厂注册工具与 hook；这不要求用户把 MemWeave 安装进全局 Pi。普通 Pi Package 仅作为未来有条件的渠道：公开宿主 API 必须同时满足 compaction 实例隔离、请求前渲染、失败阻断和相同恢复语义，再从同一源码生成产物，不维护功能削弱的平行版本。

应用的 SDK 运行依赖和普通扩展的宿主 peer dependency 是不同角色，不能混用两者的 manifest 或以一个扩展包假装锁定外部 Pi。相关原生边界参见 [Pi v1.3.0 SDK](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/sdk.md) 与 [Pi Package 依赖约定](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/packages.md#declare-dependencies)。

## 本地实现顺序

1. 核对应用锁定 Pi v1.3.0 的公开 SDK、Runtime、SettingsManager、扩展及 UI 类型。
2. 建立最小 SDK 宿主、`memweave` 入口与内部扩展工厂，验证请求链、实例压缩隔离和生命周期重绑。
3. 检查构建产物，仅包含运行必需资源。
4. 从干净安装环境验证锁定依赖、启动、重启、升级失败恢复和卸载；同时验证已有 Pi 用户的原生资源与信任行为。
5. 完成原生 TUI 接线、Session 新建/切换/恢复、reload 和所有恢复/更新提示的入口检查，再发布 GitHub Release；npm 等便利渠道单独验收。

## 兼容矩阵

| 应用 / Pi 组合 | SDK 请求链 | compaction 实例隔离 | 完整 TUI / Session 生命周期 | 锁定应用安装 | 状态 |
|---|---|---|---|---|---|
| MemWeave 0.1.0-dev.0 基础切片 / v1.3.0 | 项目 SDK 集成及 DeepSeek 冒烟通过 | 项目双实例/恢复路径测试通过 | 待接入与验收 | 待验收 | 开发中，尚未发布 |
| 其他 Pi 版本 | 未完成本方案验收 | 未验证 | 未验证 | 未验证 | 不宣称支持 |

### 现有证据与未验证范围（2026-10-20）

当前仓库已落地无界面 SDK 宿主基础切片，测试入口为 `npm run check` 和显式配置私有目录后的 `npm run test:live`。普通集成测试执行真实 Pi SDK、使用模型测试替身，覆盖请求失败/续跑、工具协议保真、Session 替换/reload、临时注入不持久化、阈值/overflow/length 压缩隔离，以及相同 cwd/agentDir 下普通 Pi 与 MemWeave 的并行恢复差异。DeepSeek 冒烟单独执行真实请求，并核对私有设置未改变。

构建提供 `--help`/`--version` 开发入口，可通过 `npm pack --dry-run --json` 检查应用文件白名单；这不等于 GitHub Release 的锁定安装、完整 TUI 或记忆业务已验收。当前应用未对外发布，正式配置/Rule 与 Task/State/Window 仍按阶段计划实现。

仓库外临时 spike 已基于实际 Pi v1.3.0 执行 28 项检查（包含失败路径和反例），并完成 5 次真实 DeepSeek 主会话 API 请求。已检查 SDK 请求前 Rule 热更新、工具续跑、原生提示保留、协议字段传递、错误阻断，以及每实例设置适配在 reload/项目覆盖/无关设置保存后的压缩隔离；双实例与压缩恢复反例使用测试替身，不是供应商压力测试。临时夹具、Session 和构建物已删除。

早期临时扩展包也曾完成安装/加载验证，但不能据此声称 MemWeave 应用的锁定安装、完整 TUI、全部恢复路径、真实网络重试或业务功能已通过。项目尚未实现 Task/State/Window 完整闭环；阶段 0 仍需将相应接入断言落为项目中可复现的测试。

编译或一次 hook 成功不等于版本兼容。每个宣称支持的应用/Pi 组合必须通过对应的 smoke/integration tests，并区分静态核对、测试替身与真实模型结果。真实模型验证继续使用私有 DeepSeek 配置，发布产物不包含开发者凭据。
