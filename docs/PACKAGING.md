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

新 Pi 适配遵循 [Pi 新版本适配原则](specs/发布与适配/pi_version_update.md)：用户明确要求适配后，在不改变核心设计、功能与原则且无额外运行时副作用的范围内，Agent 自行完成核查、实现与验收；旧宿主尽量兼容，不作为硬性条件。涉及核心契约变化或新增副作用时先讨论，可主动提出新机制带来的优化建议。适配完成不等于授权 npm 发布，也不提前改变下文记录的当前兼容结果。

## 首次初始化调整（2026-10-24 用户确认）

用户已取消“不自动创建或覆盖用户文件”的通用约束，目标是在安装扩展后的命令行交互中，由用户回车确认后自动准备默认 `~/.pi/memory/rule.md` 并关闭 Pi 压缩。此次授权针对默认 Rule 与 `compaction.enabled` 的初始化，不扩大到用户 SYSTEM/APPEND/AGENTS、认证、Session 或 Task/State 数据。

安装 npm/Git Package 后，第一次在 Pi TUI 启用扩展时自动进入 `/memweave-setup`。原生确认框默认可回车确定，明确告知将直接替换已有 Rule，并在当前 Pi `agentDir` 的全局设置中关闭自动压缩。取消不写入；无交互界面不自动接受，不在 npm 安装脚本中弹窗。

确认后，在独立初始化锁内重新检查完成标记，读取包内默认模板，原子替换独立 Rule，通过公开 `SettingsManager` 合并写入全局 `compaction.enabled=false` 并核验写入，最后原子保存完成标记。写入顺序为 Rule → 全局压缩配置 → 完成标记；部分失败明确说明已提交阶段，不回滚其他进程或用户的更新。标记提交前失败可再次确认重试，标记已存在的并发初始化不得重复替换 Rule。

完成标记为 `~/.pi/memory/setup/<profile_key>.json`，正文 `{"version":2,"package_version":"<已应用的包版本>"}`；`profile_key` 使用项目既有 `stableId(resolve(agentDir))`，同名 `.lock` 互斥。标记以 Pi 配置目录区分实例，不包含对话、Task 或密钥。兼容旧 `{"version":1}`；首次加载新实现时，以当前包默认 Rule 覆盖并迁移标记。未知或损坏标记仍明确失败。

2026-10-24 用户进一步确认：后续升级 npm 包需要重新覆盖 Rule。已初始化后，每次扩展启动（含原生 reload）比较当前包 `package.json.version` 与标记；不同版本自动以当前包默认 Rule 覆盖，在同一锁内最后更新版本标记，不再次确认、不重写压缩或其他配置，不产生模型请求。该比较不依赖安装渠道，Git/本地包使用同一版本号规则；切换到不同版本同样对齐对应模板。同版本重启、reload 或新 Session 不覆盖日常编辑。相同版本修改默认模板不视为 npm 升级，发布时必须递增版本。

`/memweave-setup` 无参数，不是模型工具。首次启动通过公开命令分发进入其命令上下文；提交后使用公开 `ctx.reload()` 刷新当前 Pi 的设置，reload 后不再使用旧上下文。同版本已完成时该命令仅 reload；包版本变化时先对齐 Rule。确认取消后可用此命令重新发起；初始化或升级失败时取消主会话请求。无界面不自动接受首次初始化，但已有完成标记的升级仍自动执行。

全局关闭影响同一 Pi 配置范围内其他进程，它们读取新设置后生效；不改项目级设置。项目显式开启压缩仍可能覆盖全局 false，此时 reload 后按有效设置拒绝请求并诊断。卸载不删除完成标记、Rule、记忆或 Session，也不恢复压缩设置。

本节取代历史验收中的通用禁止及“优先项目级”的初始化选择；Rule 技术稿 §13 定义同一边界。首次切片通过 184 项检查及真实终端验证；升级增量通过 190 项常规测试及实际临时 npm registry 两版本安装/Rule 同步/恢复/卸载。详细范围见 SETUP_VALIDATION.md，不外推为 npm 公网发布或真实模型验证。

## Package 入口与分发

### 启动模式（2026-10-25 用户确认）

生产入口先注册原生启动选择/状态提示，交互式启动由既有 `/memweave-setup` 命令展示“启用 MemWeave / MemWeave 未启用”。本次选择只保留在当前原生实例的进程内存中，reload/切换 Session 延续，重启重新选择；不新增命令、模型工具、配置字段或 Session 记录。取消不写入并阻止请求，可重试该命令。

启用后才加载业务模块和注册记忆工具/hook，执行原初始化与宿主兼容检查；每次明确选择启用都会全局设 false，再原生 reload。未启用则全局设 true 并 reload，仅保留启动/状态接线，原生 Session、上下文、工具和手动/自动压缩正常工作，不读取记忆文件，也不执行记忆宿主版本拦截。设置失败先 abort，再诊断，未 reload 完成前不放行请求。项目显式设置仍优先；底部状态只显示“MemWeave 已启用／未启用”，不显示自动压缩状态。首次 Rule 确认和包版本升级覆盖规则不变；本节模式设置取代上文“已初始化后不再调整压缩”的交互启动限制。

两个模式共用原有配置目录；全局切换影响其他进程后续读取。本节取代下表“禁用后不自动恢复”中对启动框未启用模式的限制；通过原生 Pi 配置完全取消加载/卸载扩展仍无法执行恢复，保留原设置。原生模式压缩后的历史按 Pi 有效视图恢复，不保证重新启用记忆时得到压缩前完整历史。无界面保留旧行为，不自动选择或改写设置。完整契约见 Rule 技术稿 §14。

本机日常 Pi 改用正常官方全局安装及原生更新；固定开发依赖只用于显式开发/验证入口，不提供新的运行时安装器、版本管理器或两套模式目录。

2026-10-24 用户确认额外发布 GitHub Packages 镜像 `@godicewang/memweave@0.1.0`，npm 包名保持 `@godice/memweave`，主页推荐 npm。镜像从已发布 npm 归档生成，仅修改包名与发布 registry，运行文件不变；使用仅响应精确首发 tag 或手动运行的 Actions，不因普通 push 发布。认证、原归档校验与公开验收见 [GitHub Packages 首发](specs/发布与适配/github_packages.md)。本次不发布 npm 新版本。

使用显式 manifest，让 Pi 直接加载 TypeScript 源入口，避免 Git 安装依赖开发编译步骤。npm 包名为 `@godice/memweave`，首次版本为 `0.1.0`；原名称被他人占用，用户已明确确认 scoped 名称。只有用户主动要求才发布，默认连续增加补丁号并发布到 `next`，明确要求稳定版才使用 `latest`，完整规则见 [npm 发布规范](specs/发布与适配/npm.md)。当前首次发布验收见 [Pi 1.4.0 记录](PI_1_4_VALIDATION.md)，manifest 示意如下：

```json
{
  "name": "@godice/memweave",
  "keywords": ["pi-package"],
  "pi": { "extensions": ["./src/extension/index.ts"] },
  "files": ["src/**/*.ts", "resources/rule.md", "README.md", "USER_GUIDE.md"],
  "peerDependencies": {
    "@earendil-works/pi-coding-agent": "*",
    "@earendil-works/pi-ai": "*",
    "typebox": "*"
  }
}
```

只声明实际导入的宿主 peer，按官方约定使用 `"*"`，不把这些包加入运行 `dependencies` 或捆绑第二份 SDK；当前开发依赖精确使用 v1.4.0 并提交锁文件，保留经过验证的 v1.3.0。peer 范围不代表所有宿主兼容；运行能力检查和矩阵决定支持范围。其他真实运行依赖正常声明，不依赖未声明的跨 Package 模块实例共享。

npm 与 Git 均使用 `pi install`，更新/移除使用原生 Package 命令；固定 npm 版本或 Git tag/commit 固定的是扩展代码，不锁住用户全局 Pi。项目安装通过 `--local` 限定声明作用域，项目资源受原生信任控制；Package 作用域与压缩配置作用域须分别说明，不因安装项目包而假装设置已关闭压缩。

固定 Rule 正文只生成必要的默认 `rule.md` 资源，不发布整份技术稿。npm `files` 白名单不控制 Git checkout；Git 发布 ref 中须包含生成并校验过的资源和可加载入口，不能要求用户先运行本项目开发构建，也不手工维护另一份模板。验收需确认包内 AGENTS/规范没有被加入用户提示。首次初始化的写入边界按本文件“首次初始化调整”及后续用户确认执行。

## 用户已接受的四项副作用（2026-10-20）

| 项目 | 采用方式与影响范围 | 保留的限制 |
|---|---|---|
| 共享压缩设置 | 首次初始化及交互启动选择启用时合并写全局 `compaction.enabled=false`；启动框选择未启用时写 true；同配置范围其他 Pi 读取后也受影响 | 不承诺进程隔离；不改项目显式覆盖；完全取消加载/卸载扩展后不能自动恢复 |
| 压缩恢复记录 | 关闭自动压缩并通过 `session_before_compact` 取消手动压缩；若用户运行中重新开启，Pi 可能先写 `context_edit` 再触发取消 | 取消摘要不保证有效视图完全未变；不删除原生记录、不自动用摘要兜底，本扩展窗口裁剪仍只改变请求视图 |
| 用户控制宿主版本 | 使用宿主 Pi；用户升级宿主后，扩展也随之使用新引擎 | 不承诺包版本锁定引擎或任意新版可用；未验收组合明确诊断，不静默降级 |
| 扩展共存与缓存 | 保留原生 SYSTEM/APPEND/AGENTS；第三方组合与提示缓存按实际请求验收 | 强制整段 system 覆盖、自动整理、虚拟路由、动态工具声明不自动纳入支持；Rule 参数/正文变化可能使缓存前缀失效，不保证缓存命中率 |

MemWeave 在 Session 启动/恢复及每次请求前检查 `pi.getSettings()` 的有效压缩设置。初始化命令通过原生 reload 生效；手动修改后仍须 reload/重启，不能覆盖整个设置文件。项目设置可覆盖全局值，所以只写全局 false 不足以证明有效压缩已关闭。Package 不提供模型工具去修改 Pi 设置。

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
| v1.3.0 普通主会话＋官方 DeepSeek Flash | 本地、npm 归档、临时 registry 升级、GitHub SSH 固定 commit 安装/更新/禁用/移除通过；HTTPS 网络失败，npm 公网未发布 | 正式 Rule/Task/State/Window、60% 总 Q、原文/图片回读及真实模型通过 | 主动取消、HTTP 无发送、关闭/重开压缩对照及手动取消通过 | 独立进程共享 Task、重启、fork/tree、reload、旧快照数据升级、部分提交恢复与安装代码业务闭环通过 | 阶段 0–6 已验收；限制见 PHASE_6_VALIDATION.md |
| v1.4.0 普通主会话＋官方 DeepSeek Flash | 本地/归档加载、scoped 临时 registry 跨宿主升级与卸载通过；公网发布结果单列记录 | 190 项常规检查、完整上下文与预算；实际 npm 归档的真实 DeepSeek 回读/State 恢复通过 | 实际 HTTP 取消与压缩保护回归通过；真实 PTY 回车初始化、合并全局设置与 reload 通过 | 旧产品在真实 1.3.0 上创建，当前产品在 1.4.0 恢复；原始消息与数据保留 | 见 PI_1_4_VALIDATION.md；不外推任意提供方/第三方组合 |
| v1.3.0 受控动态描述/隐藏声明 | 同一宿主 | 实际工具描述变化进入后续 R 预算，隐藏声明不发送，Rule 保留 | 普通保护保留 | prepareLoadout 受控组合通过 | 不外推任意 MCP/codemode |
| v1.3.0 强制整段 system 覆盖 | 同一宿主 | Pi 的后置投影会覆盖 Rule | 不宣称能自动阻止这类覆盖 | 已保留不兼容反例 | 不兼容 |
| v1.3.0 虚拟模型路由 | 同一宿主 | 受控测试容量无法核验 | 主动取消，物理推理为零 | 只验证拒绝，未验证可用路由 | 不支持 |
| v1.3.0 自动整理历史/任意第三方上下文变换 | 未逐组合验收 | 未验证 | 未验证 | 未验证 | 不宣称支持 |
| 其他 Pi 版本 | 未验证 | 未验证 | 未验证 | 未验证 | 不宣称支持 |

编译通过不等于版本兼容。每个宣称支持的版本必须通过 smoke/integration tests。

模型兼容验收还须核验实际容量：基础规划为精确模型容量的 60%，额外最多 20%，实际分池和各层预留见 ELASTIC_BUDGET_DESIGN.md（含输出预留），不能仅依赖“1M”等展示名称或过期的宿主目录值。模型切换、容量冲突诊断及最终请求成本按 Recent Window §5.1 验收；不通过时不得静默使用完整模型容量。Recent Window 缺省按模型计算（1M 档 200/40）、State 默认 500/100 的加载与窗口行为在功能测试中覆盖，不因 npm/Git 渠道而改变。

阶段 0 的历史证据见 `PHASE_0_VALIDATION.md`；阶段 1 已通过累计 45 项常规检查及 2 项独立真实 DeepSeek 测试，证据见 `PHASE_1_VALIDATION.md`。SDK 使用根导出的公开重放函数，避免 v1.3.0 扩展加载器对子路径的别名解析限制；npm 归档与当前代码 Git commit 均已重新加载验证。生产 peer 仅声明实际导入的 coding-agent、pi-ai 和 typebox，不捆绑另一份 SDK。

阶段 1 的生产容量适配每次逻辑请求读取 OpenAI 兼容 `/models` 的精确 `context_window`，已验收 DeepSeek Flash；不支持的 API、缺失/不唯一容量或元数据失败均取消。HTTP 兼容形状不代表其他供应商已验收。当时验收的 Runtime 在必需运行模板缺失时诊断，未实现自动初始化；该历史行为不再构成禁止首次初始化的设计约束，调整授权见本文件“首次初始化调整”。当前手动试用准备方式见随包提供的 USER_GUIDE.md。

2026-10-21 又完成 2 项独立分发测试：通过真实 GitHub SSH 验证固定 commit 安装与 ref 更新，另通过 Pi 原生 PackageManager 实际安装 npm 本地归档，并检查禁用/移除、外置文件与宿主 peer。首次 HTTPS 克隆因 HTTP/2 网络错误失败；该路径未通过。详情和复现入口 `npm run test:distribution` 见 `PHASE_6_READINESS.md`。

上述是早期安装证据。2026-10-22 阶段 6 已补齐安装代码业务恢复、旧快照跨版本升级、独立进程与临时 registry；最终 126 项常规、10 项真实 DeepSeek（32 次推理）、3 项独立分发通过，见 PHASE_6_VALIDATION.md。HTTPS 复测低速超时，未改全局 Git 网络设置。

Pi v1.3.0 的固定来源升级须区分：Git 更改声明 ref 后可通过原生 update 对齐；精确 npm 版本会被 update 跳过，需要显式 install 新版本，不能只改设置后宣称已升级。两种原生行为都有测试，用户操作见 USER_GUIDE.md。

验证使用系统临时目录并清理，私有配置留在仓库外。本机 HTTP/临时 registry 与真实 DeepSeek 分开记录。用户已授权首次发布 `@godice/memweave@0.1.0` 到 `next`，采用 MIT（godice）；公网实际结果及安装验证以 PI_1_4_VALIDATION.md 为准，准备完成不等于已发布，不自动创建 Git release 或变更稳定渠道。旧 SDK 应用与早期测试不能代替当前 Package 证据。

依据：[v1.3.0 Packages](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/packages.md)、[Extensions](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/extensions.md)、[扩展类型](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/extensions/types.ts)、[runner](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/extensions/runner.ts)、[settings](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/settings-manager.ts)、[压缩/恢复](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/agent-session.ts)。

2026-10-23 新预算切片：随包携带 DeepSeek V4.1 tokenizer 数据、原始许可和固定版本纯 JS 运行依赖 @huggingface/tokenizers@0.2.0。不捆绑 Pi/TypeBox peer，不要求用户安装 Python/Rust；安装需正常解析 npm 运行依赖。真实模型与分发记录见 CONTEXT_BUDGET_VALIDATION.md；不扩大第三方后置覆盖/虚拟路由的兼容承诺。
