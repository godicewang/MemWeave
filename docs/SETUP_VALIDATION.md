# 首次启用初始化验收（2026-10-24）

## 范围与已确认行为

安装后第一次在 Pi TUI 启用 MemWeave，原生 `/memweave-setup` 命令弹出默认可回车接受的确认框。确认后直接替换已有独立 Rule，通过宿主公开 SettingsManager 合并关闭全局自动压缩，提交完成标记，再通过命令上下文原生 reload。安装脚本不负责交互。

完成标记为 `~/.pi/memory/setup/<stableId(resolve(agentDir))>.json`，当前正文 `{"version":2,"package_version":"<已应用包版本>"}`，兼容旧 v1，同名 `.lock` 互斥。包版本变化时自动更新默认 Rule，同版本 reload/新 Session 保留日常编辑；同版本再次运行命令仅 reload。取消不写入；无界面不默认接受首次初始化，已有初始化的升级仍自动执行。项目显式覆盖按有效值诊断，不改项目设置。

## 实际执行

环境：macOS arm64、开发 Node v24.22.0、宿主 Pi v1.3.0。

| 检查 | 结果与证据 |
|---|---|
| 测试先行 | 新增测试在实现前实际因缺少 setup 模块失败；实现后新增 12 项通过 |
| `memweave-dev npm run check` | Rule 资源一致、TypeScript 类型检查通过；升级增量后 190 项单元/集成测试全部通过，0 跳过 |
| 写入边界 | 替换已有 Rule，保留其他全局设置、compaction 子字段、项目覆盖与 config.json；不生成 Task/Session 副本 |
| 幂等与并发 | 同一配置实例的并行初始化只提交一次，完成后保留用户后续 Rule 编辑；不同 agentDir 标记隔离 |
| 失败恢复 | Rule、全局配置、完成标记写入失败分别验证；部分提交明确诊断，完成前可确认重试；未知/损坏标记拒绝 |
| 请求边界 | 等待确认、取消、初始化失败、reload 失败均阻止主会话推理；初始化命令不成为真实消息，不调用模型 |
| 设置刷新 | 原生 AgentSession/扩展加载器执行命令，公开命令上下文调用真实 session.reload；设置从 true 变为 false，处理器不重复 |
| 项目覆盖 | 全局关闭后项目 true 保留，按有效设置取消推理并给出 COMPACTION_ENABLED |
| 本地/归档入口 | Package 加载测试确认命令注册与资源白名单；同一入口用于本地、npm 归档和 Git HEAD |

首次切片新增 12 项测试，完成时累计 184 项通过；升级增量再新增 6 项，当前 `tests/unit/setup.test.ts` 为 8 项、`tests/integration/setup.test.ts` 为 10 项，累计 190 项通过。集成测试使用真实 Pi v1.3.0 原生加载器、设置、Session 和 reload，确认 UI 使用测试替身，模型为 Faux，不将其表述为真实供应商 API 验证。

提交代码后，另通过 `memweave-dev npm exec -- node --test tests/integration/package-load.test.ts` 复查本地、npm 归档、当前 Git HEAD 和安装/移除，4 项全部通过。最初直接用 `node --test` 单独复查时，3 项因缺少测试要求的 `npm_execpath` 失败；这是调用方式错误，改用 npm 环境后通过，未据此修改 Runtime。

## 真实终端验证

以下为首次切片的实际终端验证，当时标记格式为 v1；包升级增量的当前验证另见下一节，不将历史终端结果冒充本次升级测试。

另外通过真实 PTY 启动本机 Pi v1.3.0，使用系统临时目录中的独立 Pi 配置、memory 路径和显式扩展入口。没有复用用户运行数据或认证，没有更改 HOME；开启离线模式并保持无模型配置。

1. 原生界面显示初始化确认，选中 `Yes`；实际发送一次回车。
2. 观察到原生 `Reloaded keybindings, extensions, skills, prompts, themes, and context files`，自动压缩状态标记消失。
3. 实际读取磁盘：Rule 与包内默认模板逐字一致，全局 enabled=false，reserveTokens 等其他值保留，完成标记为 version=1。
4. 修改该隔离 Rule，退出后用独立 Pi 进程再次启动：未再出现初始化确认，磁盘编辑内容保留，全局压缩仍关闭。
5. 两个 PTY 进程正常退出，临时验证文件删除。

该验证覆盖真实终端交互，不含真实模型推理。界面显示“无模型”的提示不影响初始化完成；模型认证仍由 Pi 原生配置。

## npm 包升级 Rule 同步增量

用户后续明确要求升级 npm 包重新覆盖 Rule。实际增量结果：

- 先补测试，旧实现出现 6 项失败，观察到旧自定义 Rule 未被替换及标记缺少包版本；实现后通过。
- 从包自身 package.json 读取并校验版本，按运行实例固定，版本改变或旧 v1 标记时锁内更新 Rule，最后提交 v2 标记。同版本跳过模板读取/写入；升级不重新确认，也不再次修改压缩配置。
- 新增单测验证版本变化覆盖自定义 Rule、并发只更新一次、旧标记迁移、失败不推进版本且可重试。原生集成验证 reload 更新、无界面迁移、不产生初始化模型请求、保留其他设置，以及升级失败时主动取消推理。
- 实际运行 `memweave-dev npm exec -- node --test tests/distribution/release.test.ts`：1 项通过。临时本机 npm registry 经真实 Pi PackageManager 安装 `0.0.0-before`、升级到当前 `0.0.0`；独立 Pi 进程从实际安装包读取版本，自动把旧自定义 Rule 替换为新归档资源，标记正确写入 `0.0.0`，未创建或改写升级阶段的 Pi 全局配置。
- 同一分发测试仍验证 Task/State/Session 恢复及原始记录保留、配置/认证保留、卸载保留升级后的 Rule；使用 7 次本机 HTTP 模型替身请求，不调用真实供应商，也不向 npm 公网发布。

发布者必须递增 package.json.version；同版本替换默认模板不视为 npm 升级。比较按版本相等性，加载另一版本（含回退或 Git/本地渠道）也对齐其默认模板，不在本轮新增通用版本迁移系统。

## 实现文件与未验证范围

- `src/extension/setup.ts`：确认、命令分发、首次启动和请求准入、原生 reload。
- `src/pi/setup-settings.ts`：包内模板定位与校验、宿主全局配置合并和核验。
- `src/storage/setup.ts`、`paths.ts`：标记 schema、路径、原子提交、并发锁及部分失败。
- `src/pi/request-lifecycle.ts`、`src/extension/register.ts`：接入已有唯一生命周期。

本切片不修改模型记忆协议正文、Task/State/Window 持久化格式、模型工具 schema、宿主源码或发布元数据。未新增真实 DeepSeek API 测试，未向 npm 公网发布，也未重新宣称其他宿主版本、Windows/Linux 终端或第三方强制提示覆盖组合兼容。

卸载保留 Rule、完成标记、记忆、Session 和全局压缩设置。全局 false 不覆盖项目 true；其他已运行的 Pi 需读取新设置后才受影响。SIGKILL 可能留下初始化锁，沿用既有人工核验锁所有者的恢复规则，不自动抢占。
