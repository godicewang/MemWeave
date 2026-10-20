# Pi Package 发布层设计

## 目标

让 Pi 官方 CLI 用户通过 Pi Package 安装 MemWeave，并继续使用原生 `pi`。npm 与 Git 使用同一套扩展和 Runtime；SDK/二开复用可由相同核心模块适配，不另造平行实现。首个宿主验收目标为 Pi v1.3.0。发布适配不得改变已定稿的记忆核心方案。

## 原则

1. 一个 Git 仓库、一个源码真相源；Package 是构建产物，不是第二份源码。
2. npm 归档排除 `AGENTS.md`、`docs/specs/`、测试和内部计划；Git checkout 可包含开发资料，但不得将其自动作为运行资源或模型上下文加载。
3. 运行时状态放在 `~/.pi/memory/`，不写入 Package 安装目录。
4. 使用公开 Pi Package/Extension API；不 fork、不 patch Pi 核心、不修改用户 SYSTEM/APPEND、不更换用户 `agentDir`。用户明确设置的 Pi 压缩配置允许有约定范围内的副作用。
5. 兼容性以测试为准；未通过的版本标为未验证，不静默降级。
6. 核心记忆语义、工具 schema、事件模型和持久化格式不能为发布便利而改变。

## Package 入口与分发

使用显式 manifest，优先让 Pi 直接加载 TypeScript 源入口，避免 Git 安装依赖开发编译步骤。示意如下，正式包名和版本在发布前确定，当前尚无可安装产品：

```json
{
  "name": "memweave",
  "keywords": ["pi-package"],
  "pi": { "extensions": ["./src/extension/index.ts"] },
  "files": ["src/", "resources/", "README.md"],
  "peerDependencies": {
    "@earendil-works/pi-coding-agent": "*",
    "@earendil-works/pi-agent-core": "*",
    "@earendil-works/pi-ai": "*",
    "@earendil-works/pi-tui": "*",
    "typebox": "*"
  }
}
```

只声明实际导入的宿主 peer，按官方约定使用 `"*"`，不把这些包加入运行 `dependencies` 或捆绑第二份 SDK；开发依赖则精确使用 v1.3.0 并提交锁文件。peer 范围不代表所有宿主兼容；运行能力检查和矩阵决定支持范围。其他真实运行依赖正常声明，不依赖未声明的跨 Package 模块实例共享。

npm 与 Git 均使用 `pi install`，更新/移除使用原生 Package 命令；固定 npm 版本或 Git tag/commit 固定的是扩展代码，不锁住用户全局 Pi。项目安装通过 `--local` 限定声明作用域，项目资源受原生信任控制；Package 作用域与压缩配置作用域须分别说明，不因安装项目包而假装设置已关闭压缩。

固定 Rule 正文只生成必要的默认 `rule.md` 资源，不发布整份技术稿。npm `files` 白名单不控制 Git checkout；Git 发布 ref 中须包含生成并校验过的资源和可加载入口，不能要求用户先运行本项目开发构建，也不手工维护另一份模板。验收需确认包内 AGENTS/规范没有被加入用户提示。首次初始化不得覆盖已有 `~/.pi/memory/rule.md`。

## 用户已接受的四项副作用（2026-10-20）

| 项目 | 采用方式与影响范围 | 保留的限制 |
|---|---|---|
| 共享压缩设置 | 用户明确将有效 `compaction.enabled` 设为 false，优先受信任项目 `.pi/settings.json`；同配置范围其他 Pi 在读取设置后也受影响 | 不承诺仅当前进程关闭；不静默写全局配置；卸载/禁用后不自动恢复，避免覆盖其他进程或用户的新设置 |
| 压缩恢复记录 | 关闭自动压缩并通过 `session_before_compact` 取消手动压缩；若用户运行中重新开启，Pi 可能先写 `context_edit` 再触发取消 | 取消摘要不保证有效视图完全未变；不删除原生记录、不自动用摘要兜底，本扩展窗口裁剪仍只改变请求视图 |
| 用户控制宿主版本 | 使用宿主 Pi；用户升级宿主后，扩展也随之使用新引擎 | 不承诺包版本锁定引擎或任意新版可用；未验收组合明确诊断，不静默降级 |
| 扩展共存与缓存 | 保留原生 SYSTEM/APPEND/AGENTS；第三方组合与提示缓存按实际请求验收 | 强制整段 system 覆盖、自动整理、虚拟路由、动态工具声明不自动纳入支持；Rule 参数/正文变化可能使缓存前缀失效，不保证缓存命中率 |

MemWeave 在 Session 启动/恢复及每次请求前检查 `pi.getSettings()` 的有效压缩设置。用户须合并修改既有配置并按 Pi 原生方式 reload/重启，不能覆盖整个设置文件；项目设置可覆盖全局值，所以只写全局 false 不足以证明已关闭。Package 不提供新的模型工具去修改 Pi 设置。

模板、配置、预算或已知兼容检查失败时，先调用 `ctx.abort()` 再报告。`context`/`context_with_system` 的异常会被 runner 捕获；`throw` 和返回 `[]` 都不是阻断机制。取消可能表现为原生错误条目，不应当作业务完成或自动重试理由。保障针对已验收的正常主会话链路，不涵盖其他扩展自行发出的模型调用。

用户配置/凭据、Session 与 `~/.pi/memory/` 不随升级或卸载删除；共享压缩值也不自动回滚。不开发独立安装器、应用版本激活器或自建 TUI；不因副作用放宽而 fork、patch Pi 或修改核心记忆协议。

## 本地实现顺序

1. 核对 v1.3.0 的 Package、`context_with_system`、取消、有效设置、Session 及工具类型。
2. 建立一个最小原生扩展和 manifest，以模型测试替身验证请求组装、工具续跑、主动取消及 compaction 恢复反例。
3. 在系统临时目录验证本地目录和 npm 归档解包后的同一入口可直接加载，检查资源白名单/peer 和 Git ref 的必要文件；不要求先公开发布或搭建自制安装服务。
4. 功能开发中持续维护加载测试；核心闭环完成后，再从干净环境完整验收真正的 npm/Git 安装、启用、reload、恢复、升级、禁用/卸载及用户文件保留，采用目标 Pi 实际支持的源语法。
5. 完成兼容矩阵及用户安装/共享设置/卸载说明后，再发布 npm 或 Git tag，不把临时 spike 当作产品交付。

## 兼容矩阵

| Pi / 路径 | Package 安装 | Rule/Window/State 组装 | 主动取消与压缩 | Session/共存 | 状态 |
|---|---|---|---|---|---|
| v1.3.0 普通主会话 | 本地项目安装/移除、npm 归档解包和 Git HEAD 入口已验证；远程安装待阶段 6 | 单入口组装夹具、资源一致性与真实 DeepSeek 工具续跑通过；正式业务待实现 | 主动取消、HTTP 无发送、关闭/重开压缩对照及手动取消已通过 | reload、新 Session、双实例、原生提示信任通过；完整业务恢复/高级共存待测 | 阶段 0 通过，尚非完整产品兼容声明 |
| v1.3.0 虚拟路由 / 动态工具 / 第三方上下文变换 | 待测 | 最终模型容量、工具成本和提示覆盖需逐组合检查 | 待测 | 待测 | 不预先宣称支持 |
| 其他 Pi 版本 | 未验证 | 未验证 | 未验证 | 未验证 | 不宣称支持 |

编译通过不等于版本兼容。每个宣称支持的版本必须通过 smoke/integration tests。

模型兼容验收还须核验实际容量：Agent 总预算为精确模型容量的一半（含输出预留），不能仅依赖“1M”等展示名称或过期的宿主目录值。模型切换、容量冲突诊断及最终请求成本按 Recent Window §5.1 验收；不通过时不得静默使用完整模型容量。默认 Recent Window 200/40、State 2000/200 的加载与窗口行为在功能测试中覆盖，不因 npm/Git 渠道而改变。

当前阶段 0 的 24 项常规检查和独立真实 DeepSeek 冒烟已通过，证据见 `PHASE_0_VALIDATION.md`。验证使用系统临时目录并清理，私有配置仍在仓库外且字节不变；未执行正式 npm/Git 远程源发布、升级或完整业务恢复。旧 SDK 应用与早期临时测试不能直接替代当前 Package 证据，加载测试、替身/本机 HTTP 和真实模型结果分别记录。

依据：[v1.3.0 Packages](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/packages.md)、[Extensions](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/extensions.md)、[扩展类型](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/extensions/types.ts)、[runner](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/extensions/runner.ts)、[settings](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/settings-manager.ts)、[压缩/恢复](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/agent-session.ts)。
