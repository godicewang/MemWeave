# 阶段 6 安装验收与前置状态

> 本文是早期部分验收的历史记录。2026-10-22 阶段 6 开发和最终验收已完成，当前结论、兼容矩阵及发布边界见 [PHASE_6_VALIDATION.md](PHASE_6_VALIDATION.md)。下文当时的待办不再表示当前进度，HTTPS 失败与尚未公开发布的限制仍保留。

更新日期：2026-10-22。**阶段 6 部分安装验收完成，整体尚未完成。** 本记录最初覆盖阶段 0–1；后续阶段 2–5 已完成，见各阶段验收记录。2026-10-22 已对阶段 5 代码 ef73403 再次通过两项分发测试；本文不将安装测试等同于完整产品验收。

## 本轮实际完成

新增独立入口 `npm run test:distribution`，执行 `tests/distribution/install.test.ts`。测试使用 Pi v1.3.0 的公开 `DefaultPackageManager`、`DefaultResourceLoader` 和 `SettingsManager`；测试与 npm 缓存、包、配置哨兵均位于系统临时目录，成功和失败均清理。

| 项目 | 实际结果 |
|---|---|
| 远程 Git SSH 安装 | 从 GitHub 克隆真实仓库，固定到 `0fd7bc3395dcdf02f8b2d59231b5f80b2d9118eb`，manifest 入口可加载 |
| 固定 Git ref 更新 | 通过 Pi 公开更新 API 将同一受管 checkout 更新到 `f2432a3f49e8ed8016fc0a46a2bdfb7e20877830`，核对实际 HEAD 并重新加载 |
| npm 本地归档安装 | 从当前仓库打包，通过 Pi 的 `npm:memweave@file:<archive>` 来源实际安装并加载；不是仅解压归档 |
| 禁用、启用与 reload | 使用原生项目 Package 资源过滤禁用/启用，禁用时不加载扩展，重启用后恢复一份处理器 |
| 移除 Package | 调用原生移除 API，扩展和受管安装目录消失 |
| 用户文件保留 | 外置 config、rule、任务数据、私有认证和 SYSTEM/APPEND 哨兵字节保持；共享 compaction=false 设置保留 |
| 宿主与发布资源 | 未自动安装 pi-ai、coding-agent 或 typebox peer；npm 安装包不含 AGENTS、docs、tests 或 scripts；默认 Rule 完整一致 |
| 开发文档隔离 | Git checkout 虽含开发资料，包内 AGENTS 未进入业务上下文发现结果 |

以上是安装/加载与外置文件保留测试。任务数据使用哨兵验证文件未被覆盖，不代表已经验证 State 格式、重建或业务恢复。测试只执行本仓库已知代码与既有公开宿主 API，没有改动用户的真实 Pi 安装或配置。

## 实际命令与结果

```sh
npm run typecheck
npm run check
npm run test:distribution
```

- 类型检查、资源一致性与 **45 项常规测试通过**。
- 最终 **2 项独立分发测试通过**；分发测试包含真实 GitHub SSH 网络访问，不并入常规离线测试。
- 本轮不需要模型推理，未调用真实模型 API。阶段 1 的真实 DeepSeek 证据见 `PHASE_1_VALIDATION.md`；完整业务 DeepSeek 闭环仍待前置模块完成后验收。

Git 默认测试目标取运行时本地 `origin/main` 的完整 commit，可通过 `MEMWEAVE_DISTRIBUTION_REF=<40位commit>` 指定候选；默认使用本机已有的 GitHub SSH 通道，需要仓库读取权限。该变量只控制开发测试，不是新增运行时配置字段。

## 已观察到的失败与限制

首次以 HTTPS 来源克隆失败，Git 报 `Error in the HTTP2 framing layer`；另一次有 10 秒上限的 HTTPS 连通检查超时。失败目录已删除。随后用既有 SSH 通道完成安装和更新验收；没有修改用户全局 Git 网络配置。

可设置 `MEMWEAVE_DISTRIBUTION_TRANSPORT=https` 复测 HTTPS。**当前记录只证明本机 SSH 路径通过，不能把 HTTPS 失败写成成功或承诺其他机器网络可用。**

npm 测试使用本地归档文件来源，没有发布或从 npm registry 安装 MemWeave；当前 `private: true` 和 `0.0.0` 保持不变。未创建正式发布 tag，也未发布产品。

## 阶段 6 尚未满足的条件

| 前置/验收项 | 当前状态 |
|---|---|
| Task、引用与 Session/分支绑定 | 阶段 2 已批准、实现并验证，见 `PHASE_2_VALIDATION.md` |
| 完整 State 工具与 State 窗口 | 阶段 3 已完成，见 PHASE_3_VALIDATION.md |
| U/A/T/R 原文回读 | 阶段 4 已完成，见 PHASE_4_VALIDATION.md |
| Recent Window、完整 Q 预算与批次提交 | 阶段 5 已完成，见 PHASE_5_VALIDATION.md |
| 完整业务重启/恢复、多进程写入与独立提交点 | 依赖阶段 2–5，不能用本轮文件哨兵代替 |
| 真实 DeepSeek 业务闭环 | 阶段 2–5 闭环已通过；最新整组 9 项、29 次真实推理，不替代最终升级／兼容验收 |
| npm registry、正式发布和完整产品用户指南 | 待核心功能及完整验收完成 |
| 其他 Pi 版本、虚拟路由、第三方动态工具组合 | 未验证 |

阶段 2–5 已完成，下一步补齐阶段 6 的完整业务与发布验收。原有核心设计和四项已确认副作用边界保持不变。
