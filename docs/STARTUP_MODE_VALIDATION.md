# 启动模式与本机 Pi 入口验收

## 目的与行为

2026-10-25 用户确认：交互式启动可选择启用 MemWeave 或“MemWeave 未启用”；未启用默认恢复全局自动压缩，使用原生 Session 和接口。两种模式共用已有 Pi 配置/认证/Session，不创建两套模式目录。行为契约先更新 Rule 技术稿 §14、PACKAGING.md 和 AGENTS.md，再实现。

默认规则模板、Task/State/Window 接口和持久化格式不变。没有发布新版本，npm/GitHub 的 0.1.0 仍是原启动流程；本机安装当前仓库开发版。

## 技术接线

- `src/extension/launcher.ts` 使用原生 `/memweave-setup`、select、setStatus 和命令上下文 reload。启用后才动态加载记忆注册模块；未启用只保留启动/关闭事件接线，不注册记忆工具、请求变换或压缩取消 hook。
- `src/pi/setup-settings.ts` 合并写全局压缩值并重新读取核验，不改项目设置或其他字段；设置写入失败、取消或尚未完成 reload 时主动 abort 请求。
- 进程内弱映射保存原生 SessionManager 对应的选择；reload 复用该对象。真实 `/new` 会替换对象，因此通过原生 shutdown 的目标 Session 路径向新实例一次性传递选择；resume/fork 同样处理。不保留旧 ExtensionContext，不写入聊天或初始化标记。
- `registerMemweaveRuntime` 复用既有初始化与请求检查，解决启动事件快照不会自动调用后注册处理器的问题。无界面保持原来的记忆行为，不弹选择框或静默切换共享配置。
- 首次 Rule 确认、版本变化覆盖一次和同版本保留编辑均沿用原协议。启用/未启用的全局压缩切换独立于模板版本同步。

## 已执行的开发自测

使用 Node 24.22.0、Pi 1.4.0：`npm run check` 200/200 通过，包含新增 10 项原生模式集成；`npm run build` 通过，固定 Rule 与资源一致。

新增用例覆盖普通模式原生请求、无记忆工具/hook、真实自动和手动 compaction 及其 Session 记录；启用/初始化/同版本 Rule 保留、共享设置恢复；选择取消后阻断与重试、设置损坏、项目显式覆盖、无界面兼容、独立实例、原生 new/resume/fork 替换。

真实 CLI PTY 从磁盘生产入口启动，在系统临时目录隔离 HOME 和 agentDir：普通模式全局 true、不创建 memory；重新启动再次选择，启用确认后生成 Rule 和标记、全局 false、底部状态正确；原生 reload 与 `/new` 保持模式。首次发现 `/new` 会替换 SessionManager，已修复并补真实 AgentSessionRuntime 集成。此 PTY 未配置认证，不将界面验收算作真实模型调用。

候选 `ffa088895c6e872f60bc795ab46c4eb1a85f3817` 的完整测试已完成：Pi 1.4.0 上 `npm run test:release -- --full` 通过 200 项常规回归、5 项入口/归档测试、3 项 npm/Git 分发测试、1 项真实 DeepSeek 产物恢复用例（3 次真实模型请求）。Git 分发明确使用该候选，独立进程通过新的 launcher 路径恢复 Task/原文/State。

另在系统临时目录克隆同一候选，依赖链接到真实 Pi 1.3.0，运行 `npm run test:release`：200 项回归和 5 项入口/归档测试通过，类型与构建通过。它是基础入口，不冒充该旧宿主上的完整发布门槛。两个宿主生成的 60 文件归档 sha512 一致。详见 `../发布测试/执行记录/2026-10-25_启动模式.md`。

从本机真实全局 Package 声明再启动 Pi 1.4.0，选择未启用后使用官方 DeepSeek Flash 完成 1 次真实请求，返回 NATIVE_MODE_OK；核验原生 Session 用户/assistant 消息、无 MemWeave custom 记录及认证文件哈希不变。该次调用与产物冒烟的 3 次分开计数，测试 Session 随后清理。日常配置的既有默认模型保持不变，全局压缩现为 true，用户下次启动可以自行选择启用记忆。

## 本机入口调整

正常全局安装官方 Pi 1.4.0；`~/.local/bin/pi` 从固定开发依赖改为链接 `/opt/homebrew/bin/pi`。默认仍使用 `~/.pi/agent/`，全局 Package 来源为当前开发仓库，`pi list` 确认只有一个 MemWeave 来源。已有默认模型和认证保留。

固定开发依赖仍为 1.3.0，显式 `memweave-dev pi` 和 `memweave-pi` 保留。原入口及修改前 Pi 设置备份位于仓库外 `~/.local/share/memweave-dev/migration-2026-10-25/`，不包含新运行时安装器。

只读原生配置检查确认安装方式 npm、可生成全局 self-update 命令。实际 `pi update` 已不再报告非全局安装限制，但访问 `https://pi.dev/api/latest-version` 超时，未完成在线版本查询；不能声称在线自更新成功。npm registry 查询与官方全局安装已成功，可按已支持版本使用 `npm install -g --ignore-scripts @earendil-works/pi-coding-agent@1.4.0`。宿主未来升级不代表记忆兼容范围自动扩大。

## 边界

全局压缩切换影响同目录其他进程后续读取；项目显式配置仍优先。完全卸载/取消加载扩展时没有恢复接线。普通模式的原生压缩可能改变有效历史，再启用记忆不承诺得到压缩前完整历史。没有修改 Pi 源码、业务 cwd、SYSTEM/APPEND/AGENTS、认证或已有 Session 数据；未验证其他宿主和第三方任意组合。
