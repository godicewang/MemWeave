# MemWeave 使用指南

MemWeave 在原生 `pi` 内提供长程任务记忆。你仍使用 Pi 的界面、模型、工具与 Session；扩展管理 Task、结构化认知和请求中的近期窗口。

支持 **Pi v1.3.0 和 v1.4.0**，Node 最低版本为 **22.19.0**；本机测试使用 Node 24.22.0。其他 Pi 版本不在支持范围。真实模型验收使用官方 DeepSeek `deepseek-flash`，精确上下文容量 1,048,576 tokens，MemWeave 默认总预算为其中 60% 即 629,145，包含输出预留。

## 安装与首次启用

**开发版启动选择尚未发布到 npm 0.1.0。** 以下“启动模式”说明适用于当前仓库/本地安装；公网 0.1.0 仍沿用直接启用与首次初始化流程。

### 启动模式（当前仓库）

每次运行交互式 `pi` 会出现原生选择框，底部持续显示模式。选择“启用 MemWeave”后按下文首次初始化；以后启动会再次选择，但同版本不会重复覆盖 Rule。选择“MemWeave 未启用”则全局恢复自动压缩并原生 reload，不加载记忆工具/Rule/Window/State，正常使用 Pi 原生 Session、上下文与压缩。

两个模式共用原来的 `~/.pi/agent/` 配置、认证和 Session；不需要两套目录。本次选择在 reload、新建或切换 Session 后延续，退出进程后重新选择；运行中不提供切换。取消选择不写入设置且暂停请求，可用 `/memweave-setup` 重试。项目显式压缩配置仍优先；底部只显示“MemWeave 已启用／未启用”。全局切换会影响同配置范围其他进程后续读取；完全卸载/取消加载扩展时没有启动接线，仍需自行恢复压缩。

普通模式产生的原生压缩记录会保留，再启用记忆时不保证恢复压缩前完整有效历史。print/RPC/SDK 无界面调用保留既有记忆行为，不弹选择、不静默切换共享设置；首次初始化仍需交互确认或手动准备。

日常 Pi 建议用官方全局 npm 安装，`pi update` 更新宿主；`pi update --extensions` 更新非固定版本的扩展。MemWeave 不捆绑或锁定宿主，未验证宿主会在启用记忆时诊断，普通模式继续交给 Pi。固定开发环境应使用显式开发命令，避免占用日常 `pi`。

### 已发布 0.1.0 的安装

首版 npm 测试包为 `@godice/memweave@0.1.0`，渠道为 `next`。安装操作在你的**业务项目目录**运行，不要把 Package 安装目录当工作目录。

已有 Pi 1.3.0 或 1.4.0 时，直接安装扩展：

```sh
pi --version
pi install npm:@godice/memweave@0.1.0
pi list
pi
```

没有 Pi 时，先安装 Node.js 22.19.0 或以上，再运行 `npm install -g --ignore-scripts @earendil-works/pi-coding-agent@1.4.0`，然后执行上面的扩展安装与启动命令。只有其他 Pi 版本时，请按原安装方式切换到已支持版本并核验 `pi --version`；MemWeave 不自动升级或降级宿主。

以上默认是用户范围安装；仅在当前项目启用可使用 `pi install npm:@godice/memweave@0.1.0 --local`，项目声明受 Pi 原生信任控制。跟随测试渠道安装可使用 `pi install npm:@godice/memweave@next`；尚未提供稳定版时，不使用 `@latest`。使用公开 npm 包不需要 GitHub 仓库权限，也不需要用户构建开发 SDK。

Git 来源仍可使用 `pi install 'git:git@github.com:godicewang/MemWeave.git@<commit>' --local`，SSH 需要仓库读取权限。Pi 原生也支持 HTTPS Git 来源，但此前本机克隆遇到网络错误。已有本地 checkout 可使用 `pi install /absolute/path/to/MemWeave --local`，其运行依赖由 checkout 维护者准备。

1. **首次启动确认初始化。** 安装后启动交互式 `pi`，扩展会自动进入 `/memweave-setup` 的原生确认框。回车确认后，程序创建 memory 目录，**直接以包内默认模板替换 `~/.pi/memory/rule.md`，包括已有自定义内容**，并在当前 Pi 配置目录的全局 `settings.json` 中合并写入 `compaction.enabled=false`，随后自动 reload。

   取消不写入初始化文件；准备好后运行 `/memweave-setup` 可重新确认。没有交互界面时不自动接受；可先在交互式 Pi 中完成初始化，或按原有手动方式复制默认 Rule、合并关闭压缩并 reload/重启。初始化过程不向模型发送命令，不产生模型请求。

   **全局压缩设置影响同一配置范围内的其他 Pi**，它们读取新设置后生效，卸载后仍保留。项目显式 `compaction.enabled=true` 仍能覆盖全局 false；扩展不修改项目覆盖，若有效值仍开启，会明确诊断并取消请求，需要自行关闭该覆盖并 reload。手动 compaction 会被取消；运行中重新打开压缩时，Pi 可能先写入原生 `context_edit`，扩展不删除这些记录。

2. **按需配置运行参数。** `setup/<profile_key>.json` 在 memory 目录记录初始化及已应用包版本，正文为 `{"version":2,"package_version":"<包版本>"}`，兼容旧 v1 标记。**升级后首次启动或 reload 会自动以新包的默认 Rule 覆盖已有模板**，无需再次确认；同版本的重启/reload/新会话保留日常编辑。同版本完成后再次运行 `/memweave-setup` 只 reload。不同 Pi 配置目录各自首次确认；删除标记会使下次交互启动重新确认初始化。

   包内 `src/config/defaults.json` 集中保存默认值；可选的 `~/.pi/memory/config.json` 只填写需要覆盖的项，例如：

   ```json
   {
     "state_max_events": 400,
     "source_cache": { "max_entries": 4096 }
   }
   ```

   未创建文件、使用 `{}` 或未填某项时继承默认值，不自动生成或改写用户文件。N/B 省略时按模型自动计算；已有显式数值/分支覆盖优先。显式 B 不得大于有效 N。非法 JSON、未知字段和非法组合会取消请求。配置与模板每个逻辑请求读取，包括工具续跑；网络重试使用原快照。Agent 仍只通过 `recent_window_set` 设置当前分支 N/B，其他项由用户配置；不要修改 Package 内的默认文件来保存个人设置。

3. **在 Pi 中配置模型和认证。** 使用 Pi 自己的模型选择与私有认证配置，密钥不要放入项目、Rule 或聊天。当前生产容量适配要求 OpenAI 兼容 `/models` 提供唯一匹配模型的精确 `context_window`；仅有静态目录或“1M”显示名称不足以通过检查。DeepSeek Flash 已验收，不能由此推断所有 OpenAI 兼容供应商都可用。仓库的开发验证私有配置不随 Package 分发。

4. 初始化完成后，先用文字让模型创建 Task，例如：“为当前工作创建一个 Task，目标是完成……”。再进行正常工作。没有当前 Task 时不可写 State 或读取 Task 引用。

## 正常使用

Task 保存目标和当前认知，Pi Session 保存原始交互。你可直接向模型描述操作；工具由模型调用。

| 意图 | 工具与边界 |
|---|---|
| 新工作 | `task_create` 创建并绑定 Task，初始化 Goal |
| 查找旧任务 | `task_find` 模糊查找；查询本身不切换 Task |
| 继续旧任务 | `task_resume` 用明确 task_id，恢复认知并绑定当前 Session/分支 |
| 查看认知 | `state_read` 读取明确 Task；可用 event_ids 查询已知历史 F/D，`task_status` 查看状态；都不切换 Task |
| 保存认知 | `state_append` 保存 Fact/Decision，`update_goal` 更新目标，`modify_fact` 归档旧认知并写入修正 |
| 查证原文 | `memory_read` 读取已知 U/A/T/R；不会搜索或切换 Task |
| 调整近期范围 | `recent_window_set` 设置当前分支 N/B；省略 B 保留原值，非法组合拒绝 |

证据引用必须来自已存在的 Task 原件或认知，不能猜编号。同一 Task 的 State 在所有绑定它的 Session/分支间共享；回退聊天或切换 Task 不撤销认知、不自动暂停旧任务。当前没有暂停/完成工具，`latest_paused` 只恢复已存在的 paused 记录。

**两类窗口各自处理。** Recent Window 缺省 N/B 按模型计算，1M 档为 200/40；一条用户消息算一个，一次 assistant 加其全部工具结果算一个。超限时先提醒，正常执行当前 assistant 和工具，可靠结束后提交边界；多个积压批次可同次处理。State 默认 500 个活动 Fact/Decision，Goal 常驻；达到条数或 token 管理线时提醒管理最早 100 个候选，最多保留 20 个，由 `state_remain` 提交。提醒期间新认知照常可见，允许暂时超过容量。两种提醒可能同时出现，提交互相独立。

`recent_window_set({"turns": 8, "evict_turns": 2})` 仅调整当前分支；下一请求重新选取原始历史。扩大窗口能恢复该范围的原文，但显示仍受统一预算约束。Rule → Recent Window → State 是请求语义顺序；State 和提醒不写入 Session、不计交互事件。固定内容放不下时会取消，官方 DeepSeek Flash 使用匹配的 V4.1 tokenizer；其他未匹配组合明确使用保守估算。预算快照与 State 位于末尾。

## 原文与图片

`memory_read` 使用 Unicode 码点 offset/limit，默认总正文预算 8000 字符，上限 50000。例如：

```json
{ "items": [{ "ref": "U3", "offset": 0, "limit": 1000 }], "max_total_chars": 5000 }
```

跨 Task 的 U/A/T 必须同时提供来源 `task_id`，成功时返回当前 Task 可复用的 R。每项独立报告来源、范围、原件完整性和截断状态。

默认情况下，完整回读结果在其后新增不足 10 条真实消息时保持完整呈现；用户、assistant、每条工具结果各计一条，不计结果本身、system、State 或提醒。第 10 条到来后恢复普通窗口预算；不是 10 轮对话。插话按新用户消息计数，不立即取消保护；重启/分支依据原始记录恢复年龄。结果若已被 Recent Window 正常移出，不会额外常驻；完整呈现仍受 60% 总预算，放不下时取消请求。期限内重复呈现会增加输入量。

追溯已知历史认知用 `state_read`，例如：

```json
{"task_id":"task_known","event_ids":["F1","D2"],"max_total_chars":8000}
```

一次 1–50 项，包内默认 8000、最多 50000 字符，按 Unicode 码点合计正文与证据引用/解释。返回原正文、证据、归档/活动状态；未知 ID 或预算不足逐项说明，不能把截断内容当成完整依据。历史查询的完整结果享有同样的 10 条消息期限。旧的 `{task_id}` 调用仍返回当前 State，不能单独加 max_total_chars；查询不会恢复 Task 或改变认知。

图片默认显示附件 R，模型显式读取后才在上述生命周期内完整发送，可能在多个请求中重复发送，期限后恢复附件引用。**先用文字创建或恢复 Task，再发送图片。** 未绑定 Task 的图片会取消请求，原件仍在 Session；可另开文字 Session 建立 Task。图片不支持字符切片，单次返回合计不超过 10 MiB；当前仅核验官方 DeepSeek Flash 图片预算，每张保守预留 2048 tokens。识别可能出错，不承诺 OCR 准确率，也无法恢复 Pi 保存前缩放或省略的原图。

原生 Bash 的必要完整输出按需保存到 `~/.pi/memory/blobs/`；历史上已丢失的输出只能返回可得片段。不要删除仍被引用的原件。

## 重启、备份与并发

- 要恢复同一聊天，使用 Pi 原生 `pi --session <path-or-id>`；磁盘恢复会继续 Task 绑定、引用编号和分支设置。`task_resume` 在新聊天中只恢复认知，不载入旧 Task 全部聊天，不重放外部操作或改变 cwd。
- 备份时同时保留 `~/.pi/memory/` 和其 Task 注册过的 Pi Session 原件。`state.md` 可由 `state.json` 重建，`state.json`、index、blobs 和 Session 不能当缓存删除。
- 不同 Pi 进程可通过各自 Session 共享同一 Task，写入使用进程锁；Recent Window 设置互相隔离。**多个进程同时写同一 Session 文件未验收。**
- 磁盘失败可能出现“State 已提交、派生视图或索引未更新”；不要据此重复制造新认知。保留原文件并按诊断恢复，幂等重试会识别已提交操作。Session 元数据未可靠落盘时，需从磁盘重新打开，单纯 `/reload` 不能修复脏内存。
- 首次初始化顺序是 Rule → 全局压缩设置 → 完成标记；后续版本更新只写 Rule → 版本标记，不改其他设置。`SETUP_FAILED` 报告阶段与已提交内容，失败不推进版本标记；修复后 reload/重启或运行 `/memweave-setup` 重试。首次尚未提交完成标记时仍须确认，既有初始化的升级不重新确认；标记已记录当前版本时不重复覆盖。损坏或未知格式标记明确报错，原生 reload 失败可重试命令或重启。
- 强杀进程可能留下 `write.lock` 或 `index.lock`。`LOCK_OWNER_DEAD` 会阻止后续写入，不自动抢占。先备份，核对锁内 owner PID 和所有写入者已退出，再人工移除对应锁目录；不能按等待时长盲删活锁。

## 更新、禁用和卸载

升级前备份运行数据和 Session。固定 Git commit 的声明不会因 `pi update --extensions` 自动跳到新提交；按 Pi 原生 Package 配置将来源更新为新 commit，再执行该命令并重启或 reload。也可用 `pi install '<新来源>' --local` 按原生方式更新同一包。`pi list` 确认只保留一个有效 MemWeave 来源，避免重复加载。不要用无参数 `pi update` 来代替包更新，它还可能更新宿主 Pi。

本项目已验收阶段 4 快照创建的数据升级到当前 Runtime；这不是任意旧版本迁移或新格式向旧版本降级的保证。需要回滚时保留原始备份，并先核对数据格式兼容性。

**升级 npm 包会覆盖 `~/.pi/memory/rule.md` 的自定义内容。** 扩展从实际安装包的 `package.json.version` 判断版本；加载不同版本时自动对齐该包默认模板，旧 v1 标记首次加载也会覆盖并迁移。需要保留的定制内容请在升级前自行备份；config.json、Task/State、Session 和压缩设置不因模板升级重置。Git/本地包共用版本规则，同版本修改包内模板不会触发升级同步；开发新协议时也要递增包版本。

采用 npm 固定版本时，需要 `pi install npm:@godice/memweave@<新版本>` 显式安装新版本；项目安装继续加 `--local`。Pi v1.3.0/1.4.0 的 update 会跳过精确 npm 版本，即使手动改了声明也不会据此重装。跟随测试渠道时使用原来源 `npm:@godice/memweave@next`，更新后重启或 reload，并用 `pi list` 确认生效来源。

使用 `pi config --local` 禁用或重新启用扩展，再 reload；移除使用：

```sh
pi remove '<pi list 中的完整来源>' --local
```

卸载移除受管 Package 和安装声明；`~/.pi/memory/`（含初始化完成标记）、Pi Session、认证、用户 SYSTEM/APPEND/AGENTS 和共享压缩设置保留。重新安装同版本保留 Rule，加载不同版本自动对齐该版本默认 Rule。开发版可在卸载前重新启动并选择“MemWeave 未启用”恢复全局压缩；已经完全卸载时须自行合并修改有效设置。

## 常见诊断与兼容范围

| 情况 | 处理 |
|---|---|
| 配置非法或 Rule 缺失/非法 | 检查运行目录、字段和模板白名单（用户配置文件可以缺省），修复后重新请求 |
| 有效自动压缩仍开启 | 检查受信任项目设置是否覆盖了全局配置，reload/重启 |
| `MODEL_CAPACITY_UNVERIFIED` | 检查模型、认证和精确容量端点；不使用静态显示值绕过 |
| State 准入超限 | 先按提醒整理、缩短新增；已有过大 State 可用较大模型整理；拒绝的增长没有写入 |
| 预算超限 | 减少完整回读范围或输入，检查超大工具声明/输出预留；不通过截短 State 绕过 |
| 来源 Session/blob 缺失或损坏 | 从备份恢复原件；摘要不能替代原文 |
| 未支持的 Pi 版本/消息表示 | 使用验收宿主与普通工具链；保留诊断，不能静默丢弃历史 |

普通 SYSTEM/APPEND/AGENTS 的发现、信任与内容保留。原生普通 Bash/read、受控动态工具描述和隐藏声明已测试。第三方扩展**强制整段 system 覆盖**会在 MemWeave hook 后覆盖 Rule，明确不兼容；虚拟路由的受控测试因无法核验容量而取消，尚不支持。自动整理历史、任意 MCP/codemode 组合、第三方 custom 消息、用户 `!` Bash 表示、其他模型图片费用和其他 Pi 版本不在当前验收范围。不能由某个受控组合通过推断任意第三方兼容或固定缓存命中率。

2026-10-23 预算调整：Agent 使用模型总容量的 60%，State 默认 500 条/每批候选 100/正文 100 字符。State 12.5%、Window 37.5%、系统工具 15%、输出 10%、最新输入 5%、完整回读 10%、协议 5%、安全 5%。config.json 省略 N/B 才按模型自动计算，已有显式数值不覆盖。输出上限落实到请求；末尾 State 附实际预算快照。State 达到 token 管理线会提前提醒，超准入预算的增长在提交前拒绝。详见开发仓库 docs/CONTEXT_BUDGET_DESIGN.md。

## 配置参数

优先级为包内默认值 → 用户部分覆盖 → 当前 Session/分支的既有六字段覆盖。嵌套对象逐项合并，不会因只改一项丢失同组默认值；现有合法六字段文件直接兼容。仅已有的 N/B 工具写分支设置，新增策略不写入 Session 配置格式。删除全局显式 N/B 不会删除已有分支设置。

| 配置键 | 默认值 | 含义及约束 |
|---|---|---|
| recent_turns / evict_turns | 自动 | 正整数，B≤N；缺省按模型预算计算 |
| state_max_events / state_event_max_chars | 500 / 100 | 活动认知条数、每条正文 Unicode 字符上限 |
| state_evict_batch / state_keep_limit | 100 / 20 | 每批候选数、最多保留数；保留仍受 1/10 比例限制 |
| context_budget.model_percent | 60 | 占模型容量百分比，可降低但不得超过 60 |
| context_budget.parts_percent | 见下表 | 正数，最多两位小数，八项合计 100 |
| window_auto.min_events / max_events / event_step | 20 / 200 / 10 | 自动窗口最小/最大事件数、向下取整步长；min≤max |
| window_auto.messages_per_event / tokens_per_message | 2 / 256 | 计算自动 N 的规划值，不改变事件定义或实际逐请求 Q |
| window_auto.evict_percent | 20 | 缺省 B 占有效 N 的百分比，向上取整，0<值≤100 |
| state_policy.token_warning_percent | 80 | 完整 State 达到规划预算的此百分比时提醒管理 |
| read.lifetime_messages | 10 | 完整回读保留期限，按其后的真实逐条消息计数 |
| read.default_total_chars | 8000 | 两种回读工具未传 max_total_chars 时的默认值，1–50000；调用显式值优先 |
| source_cache.max_entries / max_bytes | 8192 / 16777216 | 来源定位缓存条数与估算 bytes 限额，可缩小/置 0 禁用，不可增大超过既定上限 |
| model_metadata_timeout_ms | 15000 | 模型容量元数据查询超时毫秒，1–2147483647，不改变 Pi 推理重试 |

| parts_percent 子键 | state | window | output | system | user | read | protocol | safety |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 默认百分比 | 12.5 | 37.5 | 10 | 15 | 5 | 10 | 5 | 5 |

自动 N 使用 `floor(C×window%)/(messages_per_event×tokens_per_message)`，向下取整到 event_step 后限制在 min/max；自动 B 按有效 N×evict_percent 向上取整。已有显式 N/B 优先。预算分区整数余数仍归普通 Window，安全/输出不借出，实际成本扣除、State 提交准入和唯一 Q 规则保持一致。

默认 Rule 增加四个纯数值占位符：`{{agent_context_percent}}`、`{{state_token_warning_percent}}`、`{{read_lifetime_messages}}`、`{{read_default_total_chars}}`，加上原六项共十项；不支持表达式、嵌套配置路径或任意变量。六变量旧模板在原默认策略下仍可用。改变对应策略而旧模板缺少相应占位符时，会报 `RULE_CONFIG_MISMATCH` 并取消；备份后将兼容默认模板合并到独立 `rule.md` 再重试。扩展不会自动覆盖你的模板。仅调整缓存、超时、自动窗口规则或既有六字段，无须因此更新模板。

配置不是密钥存储：模型/API/认证继续使用 Pi 私有配置。缓存限额变化仅清理本实例的定位缓存；State、Session、原件及当前 Task 不会被配置文件直接删除。
