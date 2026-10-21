# 阶段 6：恢复、并发与发布准备验收

日期：2026-10-22。目标宿主 **Pi v1.3.0**，Node **24.22.0**、npm **11.19.1**。阶段 6 开发完成；公开 npm 发布、正式版本号和 Git release 不包含在本次执行中，当前保留 `private: true`、`0.0.0`。

## 交付范围与实现边界

本阶段补齐真实进程、安装产物和版本升级的验收，而非新增记忆机制。Task、State、Window、Rule 的规范、生产接口、持久化格式和核心源码均未改变。Package 增加普通用户可读的 `USER_GUIDE.md`，显式白名单继续排除开发规范、测试、凭据和运行数据。

新测试包括 `release-recovery.test.ts`（独立 Pi 进程与强杀恢复）、`combined-windows.test.ts`（并行工具与两套窗口）、`coexistence.test.ts`（reload 与共存边界）、分发 `release.test.ts`（临时 npm registry 升级）、真实模型 `release.test.ts`（归档产物重启后继续工作）。原有 Git 分发测试增加安装代码的业务恢复检查。

独立进程夹具通过实际 SDK 创建 Pi Session，加载对应安装位置的生产模块，只使用既有 memory 路径注入接口隔离到临时目录；未替换生产容量适配、请求生命周期或 Agent Loop。默认 manifest 的直接加载由独立 Package 测试覆盖。测试没有改用户 HOME、真实 memory 目录或全局 Pi 设置。

## 实际运行结果

| 命令／层级 | 观察结果 |
|---|---|
| `memweave-dev npm run check` | **126/126 通过**：43 单元、83 集成；资源一致性、两份 Rule 正文逐字比对、TypeScript strict 通过 |
| `memweave-dev npm run test:live` | **10/10 通过，32 次真实 DeepSeek 推理**；包含原有文字/视觉与新增归档恢复闭环 |
| `memweave-dev npm run test:distribution` | **3/3 通过**：真实 GitHub SSH、本地 npm 归档、临时 npm registry；供应商推理使用本机 HTTP 替身 |
| HTTPS 分发复测 | **未通过**：15 秒低速边界触发 `Operation too slow`；同次另外两项 npm 路径通过；未改全局 Git 配置 |
| 原生 `npm pack`（执行 prepack） | build/类型检查成功，44 个归档文件包含 USER_GUIDE；121 个仓库候选文件和全部归档文件按真实密钥字节扫描，零命中 |

真实推理分项：原生接入 2、Rule 2、Task 3、Goal/查询 5、State 管理 6、文字回读 3、Window 4、直接视觉 1、跨 Task 视觉 3、归档恢复 3，合计 32。Faux 与本机 HTTP 前置不混入真实推理次数。直接视觉测试只证明供应商能力，产品仍遵循默认附件 R、显式回读后才发送图片的规则。

本机 HTTP 和临时 registry 是可控故障/分发夹具，不能冒充真实 DeepSeek 或 npm 公网。真实凭据始终来自仓库外私有配置，测试核对 auth.json 前后字节一致。

## 恢复与独立提交证据

| 场景 | 验收内容 |
|---|---|
| 跨版本磁盘恢复 | 阶段 4 提交 `9868254e935a377e2a02aab487a78e2969d729a0` 创建 Task/State/引用；新进程加载当前 Runtime，恢复同一 Task、回读 U1、写入 v3，接通 Window；旧 State JSONL 前缀与原始消息保持不变 |
| 派生视图重建 | 删除测试 Task 的 state.md，再从持久化 State 恢复；原件仍可读，视图重建成功 |
| 多个 Pi 进程 | 两个独立 OS 进程、各自原生 Session，同时恢复同一 Task 并追加认知；无丢写，State v4；分支 N 分别为 8/12，全局默认仍为 6 |
| 强杀持锁进程 | 真正持有 Task 锁的子进程被 SIGKILL；Runtime 报 LOCK_OWNER_DEAD，不抢锁、不推理、不推进 State；仅人工清理临时测试锁后恢复成功 |
| 两套窗口并行 | 同一 assistant 并行调用 state_remain、state_append、recent_window_set，两种声明顺序均通过；两类提醒同帧，State 滑窗与 Window 各提交一次，新认知保留，提醒不写 Session |
| 磁盘失败与重试 | 常规整组回归覆盖实际 State 派生写失败、索引失败、Session 写失败后脏视图拒绝、Window 部分提交与稳定剩余批次；各自已提交部分独立保留，不伪成功或重复推进 |
| 分支与原生恢复 | 整组回归覆盖 Task/设置/Window 的磁盘重开、fork/tree、旧 compaction 祖先原件恢复，以及重开压缩时 Pi 自己写 context_edit 的反例 |
| 网络重试 | 生产适配的本机 503 重试复用 Rule/容量/Q/批次快照，下一逻辑请求才热更新；预算或准备失败时新增推理 HTTP 为零 |
| 归档产物＋真实模型 | 新进程执行当前 npm 归档解包后的代码，恢复已有 Task，真实 DeepSeek 回读精确 U1 范围并追加一个 Fact；旧消息及 State 前缀不变，state.md 可重建；原生 PackageManager 实际安装另由分发测试覆盖 |

这里的进程并发是**不同 Session 共享同一 Task**；不宣称多个进程可同时安全写同一原生 Session 文件。SIGKILL 测试证明死锁诊断与显式修复，没有承诺任意断电点自动修复所有文件或自动抢锁。

## 安装、升级与卸载

真实 GitHub SSH 测试从 `0fd7bc3395dcdf02f8b2d59231b5f80b2d9118eb` 安装，再将同一受管 checkout 更新至候选完整 commit；核对 HEAD、默认 manifest、单份处理器与开发 AGENTS 未被发现。更新后在独立 Pi 进程内创建/恢复真实 Task 数据；禁用、reload、移除后外置 State 与 Session 字节保持。

临时 registry 测试提供两份真实 npm 归档。旧快照仅在临时 checkout 标记为 `0.0.0-before`，通过 Pi 原生 PackageManager 安装并创建业务数据，再显式安装当前 `0.0.0`，重开原 Session、回读原文、追加 State、重建派生视图。实际 tarball 经 localhost registry 下载并核对 npm integrity；没有发布 npmjs.org。

验收确认 Pi v1.3.0 的升级差异：**Git 固定 ref 修改声明后可由 update 对齐；精确 npm 版本会被 update 跳过，需要显式 install 新版本。** 测试保留这一反例，用户指南分别说明，未修改 Pi 行为。

安装/禁用/卸载保持外置 config、rule、认证、SYSTEM/APPEND、Task 与 Session，压缩设置 false 不自动回滚。npm 白名单不包含 AGENTS/docs/tests/scripts；宿主 peer 不自动装入 Package，Git checkout 中开发文件也不成为业务上下文。

## 兼容矩阵与已知边界

| Pi v1.3.0 组合 | 结果与支持范围 |
|---|---|
| 普通主会话＋官方 DeepSeek Flash | 已验收；统一上下文、半额预算、原生工具、Task/State/Window 与原文回读闭环 |
| 普通 SYSTEM/APPEND/AGENTS、共享压缩设置 | 原生发现/信任保留；关闭、重开与手动取消对照通过；不保证取消摘要等于有效会话视图从未变化 |
| 多次 reload | 三次 reload 后 Task 绑定和单份 State 注入保持，每个事件只有一份处理器 |
| 动态工具描述/隐藏声明 | 受控 prepareLoadout 组合通过：描述变化进入后续请求及 R 预算，隐藏声明不发给模型，Rule 保留；不外推所有 MCP/codemode 组合 |
| 强制整段 system 覆盖 | **已验证不兼容**：Pi 在 context_with_system 后投影强制 system，Rule 丢失；这一组合不会被本测试误报为已取消或支持 |
| 虚拟模型路由 | 受控测试无法核验所选模型容量，主动取消，实际物理推理次数为零；不是虚拟路由成功支持证明 |
| 未核验 custom、用户 ! Bash 等历史表示 | 既有测试明确诊断，不静默丢弃后继续发送；普通 native Bash/read 工具已覆盖 |
| 自动整理历史、任意第三方/MCP/codemode | 未验收，不承诺共存或固定缓存命中率 |
| 其他 Pi 版本、其他提供方图片成本 | 不支持/未验收，不能由 peer 通配范围推断兼容 |

当前生产容量适配仍要求 OpenAI 兼容 models 元数据中的精确 context_window；Flash 已真实验证 1,048,576→524,288。文字预算是保守 UTF-8 字节估算，固定成本超限主动取消；既有未绑定 Task 图片边界保持，不借验收修改核心效果。

## 发布与清理

阶段 6 的退出条件是正常核心闭环、恢复、安装可复现及边界清楚，现已满足。`USER_GUIDE.md` 随 npm 归档提供首次配置、使用、备份恢复、更新、禁用卸载和故障说明；正式发布前还需确定版本、包名可用性与授权/许可等发布事项。本次未发布 npm、未创建 release/tag、未更改仓库可见性。

HTTPS 路径仍因本机网络失败未验收；成功路径是 SSH 与本地 npm/临时 registry。临时目录均由测试 after/finally 在成功和失败后清理，故障夹具和 registry 不常驻；私有认证不迁入仓库。初次夹具调试修正了嵌套 node:test 进程环境、TAP 诊断通道、虚拟目标测试认证和 npm 固定版本升级预期，均未据此放宽生产契约。

后续开发按实际需求继续，不新增已删除的阶段 7、基线评测或独立安装服务。完整分发候选 commit 与最终安全检查记录在本文件交付补记中。

## 交付补记

已推送实现提交 `79441833e79b5f89c36efcc2a17b77b242bea91d`。以 `MEMWEAVE_DISTRIBUTION_REF` 显式指定该提交，真实 GitHub SSH 安装/更新、安装代码业务恢复及其他两条分发路径 **3/3 通过**；该提交的默认 Git HEAD manifest/资源加载检查 **1/1 通过**。

交付复查补强本轮 assistant 成功结束断言，历史请求的错误仍原样保留；初次断言误把历史故障算作本轮失败，修正为只检查本次流事件后，最终 `npm run check` **126/126**、分发 **3/3** 通过。归档真实 DeepSeek 另做两次定向复核，各 3 次推理均通过；这 6 次另列，不混入前述整组 32 次。后续断言与报告补记未改变发布白名单内的生产代码、资源或包元数据，不需要重新定义兼容范围。

最终候选源码与归档的真实密钥字节扫描零命中；未提交 auth、用户 State 或 Session。HTTPS 失败路径的临时目录已清理，共享设置与仓库外私有配置保持原范围。
