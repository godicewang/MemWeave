# 架构与文件系统

## 1. 三种位置，严格分开

- **开发仓库**：当前 MemWeave 仓库。保存唯一源码、测试和知识库，使用 Git 管理，与用户业务项目分开。
- **Pi 安装与会话**：沿用用户现有 Pi 安装、`agentDir`、扩展发现、信任和 Session 存储。MemWeave 作为 Package 扩展加载，首个验收目标为 v1.3.0；不持有独立 SDK 应用宿主，不复制或改写 Pi 核心源码。
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
├── pi/                      # 目标宿主公开 API、上下文/Session 与兼容诊断薄适配
└── storage/                 # 路径、原子写、JSONL、幂等辅助函数
tests/
├── unit/
├── integration/
└── fixtures/
scripts/                    # 开发构建、默认资源生成，不是运行时服务
resources/rule.md           # 从独立 Rule 模板生成并校验，支持 Git 安装
```

这是职责边界，不要求第一天创建每个文件。随实现逐步建立，避免空抽象层。模块之间通过明确的小接口交互，不直接改写彼此的内部文件格式。

当前已完成阶段 0–4：`extension/index.ts` 调用注册模块，统一接入生命周期、Rule 与 Task/State 快照，以及四个 Task 工具、五个 State 工具和 memory_read。引用解析、跨 Task R 别名及必要原件保存已落在 `memory/`；State schema/reducer/renderer、归档、活动窗口和批次恢复已接通；Recent Window 和完整 Q/X 预算仍待阶段 5。内部 `RequestServices` 没有新增持久化接口或独立服务。TypeScript 入口由宿主直接加载，实际证据见 `PHASE_0_VALIDATION.md` 至 `PHASE_4_VALIDATION.md`。

阶段 1 的内部接线为 `rule-services` → 配置读取/覆盖合并 → 容量快照 → `prepareRule` → 后续模块接口；运行路径统一由 `storage/paths.ts` 提供，文件只读。容量核验通过 Pi 公开认证接口与供应商模型列表取得精确值，当前真实验收 DeepSeek Flash；每次逻辑请求核验，供应商内部网络重试不重读。SDK 导入及原生 system 重放收敛于 `src/pi/`，不复制 Pi 重放算法。

阶段 2 在容量核验的异步步骤前捕获当前 Task/State/引用和分支配置，同一请求只使用该快照；原生 Session 文件按验证过的字节偏移增量读取，来源替换/截断时重新严格读取。Task 锁串行化跨进程认知写入与引用分配，全局索引锁避免不同 Task 互相覆盖；State 以保留旧前缀的原子替换提交，派生文件失败按部分完成报告。

阶段 3 在同一请求快照中计算批次，将定位写入 Pi custom 后才继续准备请求。工具沿来源 assistant 祖先链读取本请求定位，不能拿旧记录发起新滑动。并行工具独立提交；同一 Session 的增量读取按文件串行更新缓存，避免把合法追加误判成重复条目。Goal 发现元数据可从原生调用参数恢复，不给 State 事件增加索引字段。

阶段 4 的 memory_read 从原始 Session 条目回读，逐项校验来源、字符范围与预算。R 定位和必要 Bash 完整输出定位分别保存为 memweave.aliases.v1 / memweave.originals.v1，格式见 Task §9；不改 U/A/T 元数据。blobs 按 SHA-256 寻址并以流式复制、哈希核验和有限范围读取控制内存；Session 已有图片直接按内容块定位。Task 锁保护跨进程别名序列，R evidence 回到最终来源核验；读取不切换 Task、不改变认知版本。完整回读范围在原生工具 details 中标记，阶段 5 再接统一 X 预算。

2026-10-23 用户确认：完整回读的展示豁免持续到其后新增第 10 条真实消息，按 user/assistant/每条 toolResult 逐条计数；从当前 Pi 分支推导年龄，不新增持久化倒计时，不改变窗口范围或60% 总预算。state_read 增加按已知 F/D 查询历史认知的受控模式，1–50 项、默认 8000/上限 50000 字符；旧当前 State 查询保持，历史数据仍只来自 state.json，不将 F/D 塞入 memory_read，也不增加自有存储。详见 State §17、Recent Window §5.2。

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

每次正常主会话模型请求，在同一个 `context_with_system` 处理中读取 Rule、固定 Task/配置/State 快照，先渲染 Rule，再执行上述 Window/State 流程。预算使用实际渲染的有效 system 和工具声明，保留原生消息协议。程序生成的 Rule、State/Window 提醒只存在于请求视图，不写入 Pi Session。

请求快照同时固定实际模型容量 C_model 与 Agent 上限 `C = floor(C_model * 3 / 5)`；全部输入、输出预留、协议开销和安全余量共同受 C 约束，Q 的结构不变。容量核验收敛于 `src/pi/`，不改 Pi 全局目录；模型切换后重新计算，网络重试沿用原快照。Recent Window 缺省按模型自动计算 N/B（1M 档 200/40），显式配置优先，State 默认 500/100/100/20，字段含义以 Rule §3、State §7、Recent Window §5.1 为准；事件容量不能替代 token 校验。

```text
Pi 原生准备 → 普通 context 处理 → Pi 恢复 system/工具状态
  → MemWeave context_with_system：
      有效压缩配置/兼容检查 → 请求快照 → Rule 渲染与有界插入
      → window_select → window_allocate → window_render → state_insert
  → Pi 原生转换/供应商适配 → 主会话模型
```

不包装 `session.agent.prepareRequest`，不改 `DefaultResourceLoader` 配置来挂载模板，不增加模型供应商 JSON 补丁。模板、配置或预算错误时，先通过公开 `ctx.abort()` 取消当前执行，再报告诊断；普通上下文 hook 的异常会被 Pi 捕获，不能仅靠 `throw` 或空消息阻断。取消可能留下原生错误条目，不等于业务操作成功。

此链路描述已验收的普通主会话路径；Pi 后续的强制 prompt/工具投影、虚拟模型路由和其他扩展仍可能影响最终请求。兼容验收须检查实际模型收到的内容，不以“本 hook 最后注册”代替证据；不承诺任意第三方组合兼容。

## 4. 持久化边界

- **Pi Session**：原始交互与分支，不被 Window 改写。
- **`index.json`**：Task 发现元数据，不是 State 事实源。
- **`state.json`**：Task 认知操作的追加式事实源；State 窗口滑动轨迹也记录在这里。
- **`state.md`**：可重建的当前 State，不是独立事实源。
- **`rule.md`**：固定自然语言模板；运行参数通过白名单占位符渲染，不写回参数。
- **`config.json`**：全局默认参数；Session/branch 覆盖值必须隔离保存。
- **`blobs/`**：仅保存确实需要跨会话保留、且不能可靠从 Session 取回的原件，不复制全部工具输出。

### Pi 压缩配置的共享边界

Pi 的 `settings.json` 与 MemWeave 的 `~/.pi/memory/config.json` 是不同配置。前者的 `compaction.enabled=false` 由用户明确选择作用范围，优先受信任的项目 `.pi/settings.json`；后者仍只管理记忆参数，不能用它假装关闭 Pi 压缩。

接受同一配置范围内其他 Pi 在读取设置后关闭自动压缩；禁用/卸载 Package 不自动恢复该值。运行中重新启用压缩时，Pi 可能在取消 hook 前追加恢复用 `context_edit`，改变有效会话视图。本扩展不主动用它实现窗口、不删除这些原生记录，也不把恢复记录当成新的认知证据；旧表示的支持边界沿用 Window §4.3。

## 5. 持久化决定与剩余确认项

2026-10-21 用户已批准 `PHASE_2_PROPOSAL.md`：U/A/T 定位使用 `memweave.references.v1` Pi custom 条目，index 只登记 Session 来源；绑定与六字段覆盖使用分支祖先链上的 `memweave.scope.v1`。State 为 Task 共享事件流，不随 Pi 分支回退。提交与输入边界已同步到 Task §8、State §14 和 Rule §3。

2026-10-22 用户批准阶段 5：Recent Window 边界与待处理批次仅保存于 Pi custom `memweave.window.v1`，不新增历史文件；积压多批在同一次请求合并提醒，当前 assistant 和工具完整结束后按序提交。窗口参数沿用 scope 覆盖；具体恢复协议见 Recent Window §13、`PHASE_5_PROPOSAL.md`。阶段 2 本身不承担 Window 裁剪。

2026-10-21 另行批准阶段 3：State 活动窗口只计 F/D，满窗继续正常载入新增认知、允许临时超容量；当前 Goal 常驻。State 批次请求定位使用 `memweave.state.request.v1` Pi custom 元数据，实际提交仍为既有 State slide_window，不混入阶段 5 的 Recent Window 批次设计。详情见 State §15、`PHASE_3_PROPOSAL.md`。

### 已确定接线、仍需验证的工程边界

- **Rule 热加载**：阶段 1 已用正式模块验证工具续跑、模板更新、原生 SYSTEM/APPEND/AGENTS、主动取消和 reload；后续接入 Task/State/Window 时持续回归。
- **并行工具提交**：验证同一 assistant 同时调用 `state_remain` 和 `state_append` 时的实际提交时序，保留独立提交/幂等契约，不假设串行。
- **真实请求成本**：普通模型先验收精确容量与60% 总上限；覆盖 Pi 静态模型目录和供应商容量不一致的诊断。虚拟路由、MCP/codemode 的动态声明及后置上下文变换逐组合检查实际模型容量与工具成本。无法满足既定预算时报告限制，不静默改变 Q。


## 6. 发布与安装边界（仅适配层，不改变核心方案）

本项目只有一个 Git 开发仓库；Pi Package 是该仓库构建出来的发布产物，不是另一份需要手工同步的源码项目。

```text
pi-long-task-agent/                 # 唯一 Git 源
├── AGENTS.md                       # 开发规范，不是运行资源
├── docs/                           # 规范/知识库/计划，不是运行资源
├── src/                            # 唯一源码
├── tests/ scripts/                 # 开发/验证资源，不进 npm 归档
└── package.json                    # 构建与 Pi Package 入口
          ↓ 生成/校验 Package
发布产物：Package 元数据 + 扩展运行代码 + 必要运行资源
```

发布层只负责声明扩展入口、构建可安装产物、定位 `~/.pi/memory/` 运行时资源、检测所需公开 API，并对宣称支持的 Pi 版本运行 smoke/integration tests。

发布层不得改变核心记忆方案，不得为兼容性修改工具参数、State 事件模型、Window 计数/截断规则、Rule 占位符协议或提交边界。兼容差异只能放在 `src/pi/` 与打包配置。

manifest 使用公开的 `pi.extensions`，优先指向可直接加载的 `src/extension/index.ts`。npm 归档白名单排除开发资料；Git 安装可克隆出这些资料，但只按 manifest 加载运行入口，不改变 cwd 或把包内 AGENTS 加入用户上下文。两种渠道不要求用户自行编译，实际产物仍须阶段 0 验收。

宿主依赖采用官方 peer 约定，开发依赖锁用于复现测试，不控制用户宿主。安装、更新、移除和 TUI 由 Pi 负责；本项目不另建安装器或 TUI。共享配置、恢复记录、宿主版本和扩展共存四项副作用见 `PACKAGING.md`。

本次预算适配使用匹配的 DeepSeek V4.1 tokenizer；仅在公开 before_provider_request 对齐输出上限。统一上下文处理器仍是唯一业务组装入口。末尾 State 附计费的预算快照；State 的 token 管理与提交准入见 CONTEXT_BUDGET_DESIGN.md，不增加持久化协议。

2026-10-24 来源核验：src/pi/source-verification.ts 保存有界原生位置提示（最多 8192 项、约 16 MiB），命中也比较本次快照中的完整消息；miss 批量补查，必要时才读取 Pi 原生投影。Session/分支/reload 清空，不保存正文、投影、通过结论或磁盘缓存。预算与各模块持久化协议不变，见 SOURCE_VERIFICATION.md。
