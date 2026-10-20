# 架构与文件系统

## 1. 三种位置，严格分开

- **开发仓库**：建议 `~/code/pi-long-task-agent/`。保存源代码、测试和知识库，使用 Git 管理。
- **Pi 安装与会话**：沿用用户现有 Pi 安装、`agentDir`、扩展发现和 Session 存储。不得复制或改写 Pi 核心源码。构建后通过 Pi v1.1.0 支持的扩展配置指向项目构建入口；在阶段 0 用真实 SDK smoke test 锁定具体加载方式。
- **运行时记忆**：放在 `~/.pi/memory/`，不得放入业务项目仓库。

```text
~/.pi/memory/
├── config.json              # 全局默认配置
├── rule.md                  # 唯一固定 Rule 模板
├── index.json               # 跨工作区 Task 索引
├── <cwd_key>/
│   └── tasks/<task_id>/
│       ├── state.json       # 追加式 State 操作与演化记录
│       └── state.md         # 程序重建的当前 State
└── blobs/                   # 需跨会话保留的大输出/文件原件
```

`<cwd_key>` 沿用 Pi 的 workspace/cwd identity。原始交互仍由 Pi Session 保存，不复制到 memory 目录。

## 2. 建议源码目录

```text
src/
├── extension/index.ts       # 唯一扩展入口：生命周期、工具/hook 注册
├── config/                  # config schema、默认值、实例覆盖合并
├── rule/                    # rule.md 读取、白名单变量替换、请求 hook
├── task/                    # Task service、index store、Session/branch binding
├── state/                   # event store、reducer、renderer、State tools/window
├── window/                  # event index、selector、budget、renderer、lifecycle
├── memory/                  # U/A/T/R resolver、memory_read
├── pi/                      # Pi v1.1.0 API 和 SessionManager 薄适配
└── storage/                 # 路径、原子写、JSONL、幂等辅助函数
tests/
├── unit/
├── integration/
└── fixtures/
```

这是职责边界，不要求第一天创建每个文件。随实现逐步建立，避免空抽象层。模块之间通过明确的小接口交互，不直接改写彼此的内部文件格式。

## 3. 核心数据流

```text
Pi Session（唯一原始交互历史）
   ↓ Session Adapter
Window Event Index（用户事件 / assistant+全部工具结果事件）
   ↓ selector + budget + renderer
Recent Window 临时视图
   ↓ state_insert
当前 State（state.json 经 reducer 生成）
   ↓
本次模型请求

Agent Tool Calls
   ├── Task Service → index.json / 当前 Session-branch 绑定
   ├── State Tools → state.json → reducer → state.md
   └── memory_read → U/A/T/R Resolver → Pi Session 或 blobs
```

Rule 模板由请求准备层读取和渲染；Rule、Window 与 State 使用同一份请求配置快照。程序生成的 State/Window 提醒只存在于请求视图，不写入 Pi Session。

## 4. 持久化边界

- **Pi Session**：原始交互与分支，不被 Window 改写。
- **`index.json`**：Task 发现元数据，不是 State 事实源。
- **`state.json`**：Task 认知操作的追加式事实源；State 窗口滑动轨迹也记录在这里。
- **`state.md`**：可重建的当前 State，不是独立事实源。
- **`rule.md`**：固定自然语言模板；运行参数通过白名单占位符渲染，不写回参数。
- **`config.json`**：全局默认参数；Session/branch 覆盖值必须隔离保存。
- **`blobs/`**：仅保存确实需要跨会话保留、且不能可靠从 Session 取回的原件，不复制全部工具输出。

## 5. 编码前必须确认的规范缺口

Codex 不得擅自选方案，需先向用户提问：

1. **U/A/T 跨 Session 映射**：Task 可跨多个 Session，但 U/A/T 按 Task 编号且不另建映射文件；必须明确引用到 Pi entry 的映射保存在哪里。
2. **Recent Window 批次元数据**：规范允许 Pi custom entry 或 Session metadata，但没有唯一指定恢复/幂等的持久化位置。
3. **Session/branch 窗口覆盖值**：全局默认在 `config.json`，但实例覆盖值的具体持久化位置尚未定。
4. **Rule 热加载接入**：先做 spike，验证包装 `prepareRequest` 后下一次请求可更新 Rule，且不覆盖用户 SYSTEM/APPEND、不重复注入；若公开 API 不支持，先报告。
5. **并行工具提交**：验证同一 assistant 同时调用 `state_remain` 和 `state_append` 时的实际执行与提交时序，不可假设串行。


## 6. 发布与安装边界（仅适配层，不改变核心方案）

本项目只有一个 Git 开发仓库；Pi Package 是该仓库构建出来的发布产物，不是另一份需要手工同步的源码项目。

```text
pi-long-task-agent/                 # 唯一 Git 源
├── AGENTS.md                       # 开发规范，不随普通 Package 发布
├── docs/                           # 规范/知识库/计划，不随普通 Package 发布
├── src/                            # 唯一源码
├── tests/ scripts/           # 开发/验证资源，不随普通 Package 发布
└── package.json                    # 构建与 Pi Package 入口
          ↓ build
发布产物：Package 元数据 + 扩展运行代码 + 必要运行资源
```

发布层只负责声明扩展入口、构建可安装产物、定位 `~/.pi/memory/` 运行时资源、检测所需公开 API，并对宣称支持的 Pi 版本运行 smoke/integration tests。

发布层不得改变核心记忆方案，不得为兼容性修改工具参数、State 事件模型、Window 计数/截断规则、Rule 占位符协议或提交边界。兼容差异只能放在 `src/pi/` 与打包配置。

具体 manifest 字段、安装命令和文件白名单，应在阶段 0 根据 Pi v1.1.0 的实际文档/CLI 做最小验证后确定，不提前猜测字段，也不把开发目录整体直接发布。
