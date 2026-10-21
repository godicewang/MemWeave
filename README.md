# MemWeave — Pi Long Task Agent

本仓库用于构建运行在原生 Pi 内的长程任务记忆扩展，以 Pi Package 经 npm 或 Git 分发。用户继续使用 `pi`，复用原生循环、界面与 Session。首个兼容验收目标为 Pi v1.3.0，宿主版本由用户安装决定。

## 开始前

1. 阅读 `AGENTS.md`。
2. 阅读 `docs/INDEX.md` 和当前任务对应的 `docs/specs/`。
3. 复现 `docs/PHASE_0_VALIDATION.md` 中的接入检查，再按实施计划推进当前阶段。
4. 每个阶段按验收范围开发，不提前生成整套业务实现。

## 文档

- `docs/ARCHITECTURE.md`：代码与运行时文件的职责边界。
- `docs/PACKAGING.md`：分发方式、宿主依赖、已接受的副作用与兼容边界。
- `docs/IMPLEMENTATION_PLAN.md`：分阶段 Vibe Coding 计划。
- `docs/specs/`：五份已定稿行为规范，设计调整须先讨论确认。

源代码仓库、Pi Session 和 `~/.pi/memory/` 运行时数据必须分开存放。

已确认的默认设计：Agent 总预算为实际调用模型最大上下文的一半（按 token 向下取整，含输出预留）；Recent Window 容量为 200 个事件、每批移出 40 个；State 容量为 2000 个事件、每批管理 200 个，沿用最多保留 20 个的规则。配置读取、校验和请求上限派生已实现；窗口裁剪、完整 token 预算及 State 管理按后续阶段实现。

## 开发与发布分离

本仓库是唯一源码。npm 归档仅包含扩展运行代码、必要资源和用户说明；Git 安装会克隆仓库，但开发知识库和测试不得作为运行资源或模型上下文加载。两种渠道使用同一扩展入口，不维护第二份平行实现。

发布层只负责 Pi 扩展加载、Package 元数据、运行时资源定位和版本兼容检查；不得为发布便利改变已定稿的 Task、Rule、State、Recent Window 语义。

Rule 热读取、Window 预算和 State 注入统一使用 `context_with_system`；模板或预算错误主动取消请求。自动压缩由用户明确关闭，优先项目级设置，同配置范围内的普通 Pi 也会受影响；卸载扩展不自动恢复该设置。压缩恢复记录、宿主升级及第三方扩展组合的限制见 `docs/PACKAGING.md`。

## 当前进度

阶段 0–3 已完成。当前入口提供四个 Task 工具，以及 `state_append`、`update_goal`、`modify_fact`、`state_read`、`state_remain` 五个 State 工具，并在每次请求末尾注入当前 Task 的 State。Task 可跨 Session 恢复，U/A/T 编号从 Pi 元数据继续；批量提交、归档、窗口恢复、重试和并发均有测试。详情见[阶段 3 验收记录](docs/PHASE_3_VALIDATION.md)和[阶段 2 验收记录](docs/PHASE_2_VALIDATION.md)。

启用开发入口前，须明确按 Pi 原生方式关闭有效自动压缩，优先受信任项目的 `.pi/settings.json`。扩展检查 Pi v1.3.0 与压缩设置；准备失败先取消再报告，卸载不恢复设置，具体范围见 `docs/PACKAGING.md`。

State 窗口只计活动 F/D，Goal 常驻；默认到 2000 时提醒管理最早 200 个、最多保留 20 个。提醒期间正常载入新增认知，允许临时超量；只在可靠提交后移除未保留候选。下一步为阶段 4 的完整原文回读；Recent Window 裁剪和完整 token 预算仍属阶段 5。旧 SDK 应用保留在 Git 历史中。

阶段 6 的部分安装验收也已完成：GitHub SSH 固定 commit 安装/更新、npm 本地归档安装、禁用/reload 和卸载通过；外置用户文件与共享压缩设置保留。HTTPS 克隆遇到网络错误，npm registry 和完整业务验收尚未完成，见[安装验收与前置状态](docs/PHASE_6_READINESS.md)。

## 运行文件

启动所需的 `~/.pi/memory/config.json` 和 `~/.pi/memory/rule.md` 不会自动创建或覆盖。首次试用时，在该目录创建下列配置，并将安装包内 `resources/rule.md` 的内容复制为 `rule.md`；已有合法配置和自定义模板应保留。安装包目录只提供默认模板，不保存运行数据。

```json
{
  "recent_turns": 200,
  "evict_turns": 40,
  "state_max_events": 2000,
  "state_event_max_chars": 100,
  "state_evict_batch": 200,
  "state_keep_limit": 20
}
```

六个字段均为必填正整数，`evict_turns` 不能超过 `recent_turns`；不接受额外字段。模板只展开这六个白名单变量，不处理用户提示中的占位符。修改配置或模板在下次逻辑请求（含工具续跑）生效，供应商内部网络重试沿用原快照；文件缺失或非法时停止本次推理。

当前容量适配通过 Pi 公开接口解析所选模型的认证与端点，每次逻辑请求读取 OpenAI 兼容 `/models` 的精确 `context_window`，不缓存、不改宿主模型目录。已真实验收 DeepSeek Flash：1,048,576 → 524,288；未提供精确容量的供应商/API 会明确诊断并取消，不能据 peer 通配符推断兼容。完整输入/输出预算与裁剪在阶段 5 接通。

Task 创建后，程序在同一 memory 目录维护 `index.json` 和 `<cwd_key>/tasks/<task_id>/state.json`（JSONL 认知事件）及可重建的 `state.md`。引用与分支绑定写入 Pi 原生 custom 元数据；没有第二套聊天文件。State 与临时引用头只加入模型请求，原始消息正文不改写。

同一 Task 的 State 在所有绑定它的 Session/分支间共享；回退聊天不撤销认知。Task 切换不自动暂停其他任务；本阶段没有暂停/完成工具，`latest_paused` 仅恢复已存在的 paused 记录。来源 Session 删除/损坏时明确失败；不要把这些文件作为可随意清理的缓存。写盘失败会说明已提交部分；Session 元数据未落盘时须从磁盘重新打开 Session，普通扩展 reload 不会修复脏内存。进程被强杀可能留下锁，需确认写入者退出后清理；不会自动抢占。

## 骨架与开发命令

```text
src/
├── extension/index.ts       Pi Package 扩展入口、生命周期保护和 Rule 接线
├── config/                 配置与校验
├── rule/                   Rule 读取与渲染
├── task/                   Task 生命周期
├── state/                  Symbolic State
├── window/                 Recent Window
├── memory/                 引用与原文回读
├── pi/                     请求生命周期、兼容诊断与上下文半额上限
└── storage/                路径与存储基础能力
resources/rule.md           从独立模板生成，提交以支持 Git 安装
scripts/                    开发构建脚本
tests/
├── unit/                   纯逻辑与资源一致性
├── integration/            Pi 与 Package 集成
├── live/                   单独执行的真实 DeepSeek 冒烟
└── fixtures/               隔离 Session 与请求测试夹具
```

Node 最低版本与目标 Pi 一致，为 22.19.0；本机验证使用 `.node-version` 中的 24.22.0。开发依赖精确固定 Pi v1.3.0，生产使用宿主 peer。安装和验证命令：

```sh
npm ci --ignore-scripts
npm run build
npm run check
# 独立执行分发检查，包含 GitHub 网络访问并需要仓库读取权限
npm run test:distribution
# 独立执行真实 DeepSeek API 验证
npm run test:live
```

`build` 生成默认 Rule 资源并做类型检查；Pi 直接加载 TypeScript，不生成第二套应用或捆绑宿主。`resources:check` 检查生成资源是否过期；`test:unit` 与 `test:integration` 可分别执行。常规测试使用替身与本机 HTTP，在系统临时目录中创建 Session、安装、打包和解包，成功/失败时均清理，不调用真实模型 API。`test:live` 使用仓库外既有 DeepSeek 私有配置，详情见验收记录。

`test:distribution` 默认使用既有 GitHub SSH 通道，Git 候选取本地 `origin/main`；可用 `MEMWEAVE_DISTRIBUTION_REF=<完整commit>` 指定已推送候选，用 `MEMWEAVE_DISTRIBUTION_TRANSPORT=https` 复测 HTTPS。该组测试独立于常规检查，npm 路径验证的是本地归档实际安装，尚未验证 registry 发布。

当前版本为 `0.0.0`，`private: true` 用于防止开发骨架被误发布到 npm；正式包名、版本与发布验收在交付前确定。不要手改 `resources/rule.md`，应维护规范中的两份一致模板后执行 `npm run resources:sync`。密钥继续使用仓库外的私有配置。
