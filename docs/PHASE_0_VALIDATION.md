# 阶段 0 验收记录

日期：2026-10-20。环境：macOS arm64、Node v24.22.0、Pi v1.3.0、TypeScript v7.0.2。阶段 0 的原生接入可行性和最小 Package 验收已完成；正式记忆业务仍按阶段 1–6 实现。

## 交付范围

- `src/pi/request-lifecycle.ts`：同一 `context_with_system` 入口、目标宿主诊断、启动/逐请求有效压缩检查、手动压缩取消，以及先 `ctx.abort()` 再报告的失败边界。Pi 自行处理 reload 和 Session 生命周期；项目不替换原生请求准备函数。
- `src/pi/context-limit.ts`：从已经核验的精确 token 容量派生半额上限，拒绝未知、无效或展示字符串容量。
- `src/extension/index.ts`：接入以上生命周期保护，不注册生产业务工具，不自动修改 Pi 设置。
- 测试夹具通过内部 `RequestServices` 接口模拟配置快照、Rule 热读取、完整系统/工具成本、State 和提醒注入。该接口不新增持久化字段或模型工具。夹具不进入 Package，也不冒充阶段 1 的正式 Rule/config 或阶段 5 的 Window 算法。

## 实际验收证据

| 要求 | 结果与证据 |
|---|---|
| 独立 Package 与可重复资源 | strict 类型检查和构建通过；两份规范模板逐字一致，生成资源与独立模板字节一致 |
| 首次请求与工具自动续跑 | 原生 Agent Loop 完成工具调用及续跑；配置 200→240、Rule 文件热改在下一逻辑请求同时可见，记录的有效 system/工具成本随之更新 |
| 保留原生内容 | SYSTEM/APPEND/AGENTS 的原生信任与项目优先级通过；用户占位符不替换，来源文件内容不变；原生工具 ID、参数和结果配对保留 |
| 临时内容不持久化 | Session 文件包含真实工具结果，不包含注入的 Rule、State 或提醒；无第二份全量历史 |
| 错误请求主动取消 | 只 throw 的反例仍进入模型；模板、配置或预算失败经 `ctx.abort()` 后模型调用为零，即使报告函数再抛错也不发送 |
| 真实 HTTP 边界 | 原生 OpenAI 兼容提供方发出正常请求；无效/空/不可读模板及预算失败均无新增 HTTP 请求 |
| 网络重试 | 本机服务先返回 503 再成功，两个 HTTP 请求消息相同、只准备一次快照；下一逻辑请求读取更新后的 Rule/config |
| 压缩开关 | 关闭后 threshold/overflow/length 均无压缩调用、摘要或恢复编辑；手动压缩被 hook 取消，不增加模型请求 |
| 恢复记录副作用 | 运行中重开后，threshold 进入取消 hook；overflow/length 各先生成一条原生 `context_edit`，随后取消摘要；原生记录保留 |
| 共享配置范围 | 另一个 SettingsManager 在 reload 后读到全局 false；受信任项目 true 可覆盖，不受信任项目不覆盖；移除 Package 后压缩设置保留 |
| reload 与实例隔离 | 连续三次 reload 每请求只处理一次，新 Session 重新处理；两个实例共享模板但各自保留独立配置快照 |
| 模型精确容量 | DeepSeek 实际 `/models` 返回 1,048,576 tokens，半额为 524,288；Pi 静态目录为 1,000,000。差异已核实，真实测试显式传入核验值，不修改全局目录或宿主文件 |
| 本地与 npm 归档 | Pi manifest 可加载仓库与 npm 解包后的同一入口；归档只含 README、元数据、扩展/适配代码及 Rule 资源，不含开发文档、测试、依赖副本或凭据 |
| Git ref | 对代码提交 `740a89e` 的 `git archive HEAD` 解包后，入口和生成资源无需开发构建即可加载；后续同一测试持续检查 HEAD |
| 原生项目安装/移除 | `DefaultPackageManager.installAndPersist`/`removeAndPersist` 在隔离项目成功；移除并 reload 后扩展消失，用户压缩设置未回滚，包内 AGENTS 未注入上下文 |
| 真实 DeepSeek | 项目私有配置下完成 1 项真实测试：2 次主会话模型请求、1 次测试工具调用及自动续跑；随后预算失败取消且无新增模型请求；原私有配置字节不变 |

## 复现命令

```sh
npm ci --ignore-scripts
npm run build
npm run check
npm run test:live
```

常规检查包含 **5 项单元测试、19 项集成测试，共 24 项**；`test:live` 独立执行真实 DeepSeek，默认 `npm test` 不调用供应商。真实测试优先读取本机既有私有配置；其他开发机器可用 `MEMWEAVE_DEEPSEEK_AUTH` 指定仓库外的配置文件路径，变量只保存路径，不保存密钥。验证目录、临时 Session、压缩包和解包资源由测试在成功/失败时清理。

## 验证边界

- 本阶段验证正常主会话接入能力；未实现正式 Task/State 工具、完整 Rule/config 模块或 Recent Window 算法，不以测试夹具宣称这些业务已完成。
- 夹具按完整请求的字节数保守估算成本，用于接线、时序和取消验证；正式 token 计数、唯一 Q 和窗口分配留在后续模块。
- 精确容量核验与半额派生已通过；通用供应商元数据发现和实际业务快照接线仍属于后续模块，不以静态“1M”展示值替代核验。
- 仅 Pi v1.3.0 与上述提供方路径有证据。未验证其他 Pi 版本、其他真实供应商、强制整段提示覆盖、虚拟路由、MCP/codemode 动态工具及任意第三方扩展组合；不承诺固定提示缓存命中率。
- 本地安装/移除、npm 归档和 Git ref 文件已验证；正式 npm/Git 远程源发布、升级和完整恢复验收留在阶段 6。没有发布到 npm 或推送 GitHub，也没有独立安装器。

下一阶段：阶段 1 的正式配置与 Rule 模块。Task 引用映射、Window 批次和实例覆盖的持久化位置仍按 `ARCHITECTURE.md` 的既有未决项处理。
