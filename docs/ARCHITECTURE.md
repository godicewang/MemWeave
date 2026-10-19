# 架构与文件系统

## 1. 开发、安装与运行数据，严格分开

- **开发仓库**：MemWeave 的唯一 Git 源，保存源代码、测试、评测配置和知识库，与业务项目分开。
- **应用安装**：存放构建后的 MemWeave 及其锁定 Pi SDK 依赖，不依赖全局 `pi` 命令。当前接入基线为 v1.3.0；用户升级全局 Pi 不替换应用内部引擎。
- **Pi 配置与会话**：沿用用户实际的 `agentDir`、凭据、受信任资源发现和 Session 存储；尊重 `PI_CODING_AGENT_DIR` 等原生定位方式。安装应用不复制凭据，不为 compaction 隔离另建配置 profile，不改写 Pi 核心源码。
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

### 1.1 独立宿主与 Pi 适配层

```text
memweave CLI / 原生交互界面接线
    ↓
src/pi/：SDK 宿主工厂、实例设置、请求/Session/UI 生命周期
    ├── MemWeave Runtime：Rule / Task / State / Window / memory_read
    └── 固定版本 Pi：AgentSession / Agent Loop / SessionManager / 模型与工具
```

宿主使用公开 SDK 创建并持有原生 Session，在同一资源加载链内注册 MemWeave 扩展工厂。`src/extension/` 负责工具/hook 注册，业务模块负责各自规则；Pi 的具体类型和调用差异收敛在 `src/pi/`，不为多个版本复制业务代码，也不把适配层做成通用 Agent 框架。

v1.3.0 可从公开的 `createAgentSession()`、`AgentSessionRuntime` 及其工厂接口接入；原生 `InteractiveMode` 用于复用 TUI。具体组合属于可调整的接入细节，不将某个函数名冻结为业务契约。启动、新建/恢复 Session、分支变化、资源 reload 和 Session 实例替换后，必须重新核对绑定、请求包装与订阅，做到幂等安装、正确释放。所有入口都必须经过同一宿主工厂，不能切换后回到裸 Pi。

保留原生 SYSTEM/APPEND/AGENTS、skills、工具、模型与信任行为。SDK 不会自动装载 CLI 的 codemode、tool_search、MCP 内置扩展；需要这些能力时用 Pi 公开工厂及原有配置接线，不自行实现替代品。保持原生发现不等于承诺任意第三方扩展兼容：若扩展覆盖已预算上下文、强制重写 system 或另行摘要，应明确报告冲突，不静默禁用用户资源。

当前首个实现切片为无界面 SDK 宿主。Pi 1.3.0 的裸 SDK 默认信任项目，CLI 信任解析则未从包根导出；`src/pi/trust.ts` 通过公开的资源加载回调、信任存储和扩展类型接通无界面流程，不使用私有导入。已有信任决定和扩展优先级保持一致，未知项目的 `ask` 在无界面时不授权；交互式确认界面及完整 TUI 仍须后续接入验收。

### 1.2 实例级 compaction 与请求失败隔离

宿主向原生 Session 和 ResourceLoader 注入同一个每实例 SettingsManager 适配对象。普通设置继续按 Pi 原生配置/信任/保存行为工作；只有本 Runtime 的 compaction 有效读取固定为关闭，reload、其他设置保存、受信任项目覆盖和重新创建 Session 都不能使它重新开启。不能调用会改写共享配置的压缩 setter，也不能仅依赖一次 `applyOverrides()`。手动压缩取消与发送前组装成功检查仍需保留，具体约束见 Recent Window §2.2、§10.3。

这样是在 Pi 进入自动阈值、overflow/length 恢复分支前关闭压缩；单靠 `session_before_compact` 取消摘要，仍可能先产生恢复用 `context_edit`，不满足本项目的历史/窗口隔离要求。预算失败须在发送边界阻断，不能指望扩展处理器抛异常自动停止网络请求。

## 2. 建议源码目录

```text
src/
├── cli/                     # MemWeave 命令、参数、启动退出与界面接线
├── extension/index.ts       # 宿主内扩展工厂：生命周期、工具/hook 注册
├── config/                  # config schema、默认值、实例覆盖合并
├── rule/                    # rule.md 读取、白名单变量替换、请求 hook
├── task/                    # Task service、index store、Session/branch binding
├── state/                   # event store、reducer、renderer、State tools/window
├── window/                  # event index、selector、budget、renderer、lifecycle
├── memory/                  # U/A/T/R resolver、memory_read
├── pi/                      # 锁定 Pi 的宿主、设置、Session/请求/UI 薄适配
└── storage/                 # 路径、原子写、JSONL、幂等辅助函数
tests/
├── unit/
├── integration/
└── fixtures/
eval/
├── configs/
├── runs/
└── README.md
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

原生请求准备先运行，再由适配层准备 Rule 和共享 frame；`context` 中的 Window/State 组装消费该 frame，不再次读取一份可能已变化的配置或 State。最终仍由 Pi 转换消息、编码供应商协议并执行循环；宿主的发送检查只验证组装状态，不另加预算算法。

## 4. 持久化边界

- **Pi Session**：原始交互与分支，不被 Window 改写。
- **`index.json`**：Task 发现元数据，不是 State 事实源。
- **`state.json`**：Task 认知操作的追加式事实源；State 窗口滑动轨迹也记录在这里。
- **`state.md`**：可重建的当前 State，不是独立事实源。
- **`rule.md`**：固定自然语言模板；运行参数通过白名单占位符渲染，不写回参数。
- **`config.json`**：全局默认参数；Session/branch 覆盖值必须隔离保存。
- **`blobs/`**：仅保存确实需要跨会话保留、且不能可靠从 Session 取回的原件，不复制全部工具输出。

## 5. 编码前必须确认的规范缺口

以下前三项会决定业务持久化/恢复契约，仍须在相关实现前向用户确认；本次 SDK 宿主调整不替它们作决定：

1. **U/A/T 跨 Session 映射**：Task 可跨多个 Session，但 U/A/T 按 Task 编号且不另建映射文件；必须明确引用到 Pi entry 的映射保存在哪里。
2. **Recent Window 批次元数据**：规范允许 Pi custom entry 或 Session metadata，但没有唯一指定恢复/幂等的持久化位置。
3. **Session/branch 窗口覆盖值**：全局默认在 `config.json`，但实例覆盖值的具体持久化位置尚未定。

接入方案已确认，以下属于继续验收的实现问题，不需为等价函数选择重复征求批准：

- **Rule 与生命周期**：v1.3.0 临时验证已覆盖请求前热加载及原生提示保留；项目实现还须验证完整 TUI、reload、新建/切换 Session、失败恢复与网络重试。
- **并行工具提交**：验证同一 assistant 同时调用 `state_remain` 和 `state_append` 时的实际执行与提交时序，不可假设串行。若发现必须改变两个批次独立提交的既定语义，先报告用户。


## 6. 发布与安装边界（仅适配层，不改变核心方案）

本项目只有一个 Git 开发仓库；MemWeave 应用是该仓库构建出来的发布产物，不是另一份需要手工同步的源码项目。

```text
MemWeave/                          # 唯一 Git 源
├── AGENTS.md                       # 开发规范，不随普通应用发布
├── docs/                           # 规范/知识库/计划，不随普通应用发布
├── src/                            # 唯一源码
├── tests/ eval/ scripts/           # 开发/验证资源，不随普通应用发布
└── package.json / 依赖锁            # 应用构建、命令入口与锁定依赖
          ↓ build
发布产物：MemWeave 入口 + Runtime/适配层 + 必要运行资源 + 安装元数据/依赖锁
```

发布层负责构建可安装应用、锁定 Pi 运行依赖、定位运行资源、检测所需公开 API，并对应用/Pi 组合运行 smoke/integration tests。用户在业务目录运行 `memweave`；无需手动安装对应 Pi 版本或修改整个工作区的压缩设置。

发布层不得改变核心记忆方案，不得为兼容性修改工具参数、State 事件模型、Window 计数/截断规则、Rule 占位符协议或提交边界。兼容差异只能放在 `src/pi/` 与依赖/打包配置。

具体安装元数据、命令和白名单由阶段 0 根据锁定 SDK 与实际安装测试确定；版本管理及验收见 `PACKAGING.md`。普通 Pi Package 不是当前完整 Runtime 的主入口；只有未来公开 API 能满足同样的实例隔离和请求验收时才考虑，不维护第二套或削弱版实现。
