# MemWeave 使用指南

MemWeave 在原生 `pi` 内提供长程任务记忆。你仍使用 Pi 的界面、模型、工具与 Session；扩展管理 Task、结构化认知和请求中的近期窗口。

目前已验收 **Pi v1.3.0**，Node 最低版本为 **22.19.0**；本机测试使用 Node 24.22.0。其他 Pi 版本不在支持范围。真实模型验收使用官方 DeepSeek `deepseek-flash`，精确上下文容量 1,048,576 tokens，MemWeave 默认总预算为其中 60% 即 629,145，包含输出预留。

## 安装与首次启用

当前可从 Git 安装开发快照，需具备仓库读取权限；尚未向 npm 公网发布，`0.0.0` 不是正式发行版。安装操作在你的**业务项目目录**运行，不要把 Package 安装目录当工作目录。

```sh
# SSH 通道需要 GitHub 读取权限；将 <commit> 换成要使用的完整提交 ID
pi install 'git:git@github.com:godicewang/MemWeave.git@<commit>' --local
pi list
```

Pi 原生支持 HTTPS Git 来源，但本机的首次 HTTPS 克隆遇到 HTTP/2 网络错误；SSH 路径已验收。项目安装声明写入 `.pi/settings.json`，需先通过 Pi 的项目信任检查。也可用 `pi install /absolute/path/to/MemWeave --local` 安装本地 checkout；两者直接加载 TypeScript，不需要用户构建 SDK 或运行独立安装器。

1. **关闭有效自动压缩。** 在已有 `.pi/settings.json` 中合并以下字段，保留其中的 packages 和其他设置，再按 Pi 原生方式 reload 或重启。不要用这个片段覆盖整个文件。

   ```json
   { "compaction": { "enabled": false } }
   ```

   扩展不会替你静默改设置。同配置范围的其他 Pi 也会受影响，禁用和卸载后此设置仍保留。手动 compaction 会被取消；运行中重新打开压缩时，Pi 可能先写入原生 `context_edit`，扩展不删除这些记录。

2. **准备运行文件。** 首次创建 `~/.pi/memory/`，将安装包的 `resources/rule.md` 复制为 `~/.pi/memory/rule.md`。通过 `pi list` 确认安装位置。已有模板应先备份、检查，不能直接覆盖。

   包内 `src/config/defaults.json` 集中保存默认值；可选的 `~/.pi/memory/config.json` 只填写需要覆盖的项，例如：

   ```json
   {
     "state_max_events": 400,
     "source_cache": { "max_entries": 4096 }
   }
   ```

   未创建文件、使用 `{}` 或未填某项时继承默认值，不自动生成或改写用户文件。N/B 省略时按模型自动计算；已有显式数值/分支覆盖优先。显式 B 不得大于有效 N。非法 JSON、未知字段和非法组合会取消请求。配置与模板每个逻辑请求读取，包括工具续跑；网络重试使用原快照。Agent 仍只通过 `recent_window_set` 设置当前分支 N/B，其他项由用户配置；不要修改 Package 内的默认文件来保存个人设置。

3. **在 Pi 中配置模型和认证。** 使用 Pi 自己的模型选择与私有认证配置，密钥不要放入项目、Rule 或聊天。当前生产容量适配要求 OpenAI 兼容 `/models` 提供唯一匹配模型的精确 `context_window`；仅有静态目录或“1M”显示名称不足以通过检查。DeepSeek Flash 已验收，不能由此推断所有 OpenAI 兼容供应商都可用。仓库的开发验证私有配置不随 Package 分发。

4. 启动 `pi` 或在已有会话中执行 `/reload`。先用文字让模型创建 Task，例如：“为当前工作创建一个 Task，目标是完成……”。再进行正常工作。没有当前 Task 时不可写 State 或读取 Task 引用。

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
- 强杀进程可能留下 `write.lock` 或 `index.lock`。`LOCK_OWNER_DEAD` 会阻止后续写入，不自动抢占。先备份，核对锁内 owner PID 和所有写入者已退出，再人工移除对应锁目录；不能按等待时长盲删活锁。

## 更新、禁用和卸载

升级前备份运行数据和 Session。固定 Git commit 的声明不会因 `pi update --extensions` 自动跳到新提交；按 Pi 原生 Package 配置将来源更新为新 commit，再执行该命令并重启或 reload。也可用 `pi install '<新来源>' --local` 按原生方式更新同一包。`pi list` 确认只保留一个有效 MemWeave 来源，避免重复加载。不要用无参数 `pi update` 来代替包更新，它还可能更新宿主 Pi。

本项目已验收阶段 4 快照创建的数据升级到当前 Runtime；这不是任意旧版本迁移或新格式向旧版本降级的保证。需要回滚时保留原始备份，并先核对数据格式兼容性。

默认 Rule 包含历史 F/D 查询及回读期限说明，并已增加四个策略占位符（见下文配置参数）。升级 Package 不会覆盖 `~/.pi/memory/rule.md`；请先备份，再对照包内 `resources/rule.md` 合并这两处协议说明，保留自己的定制内容。

将来采用 npm 固定版本时，需要 `pi install npm:<包名>@<新版本> --local` 显式安装新版本；Pi v1.3.0 的 update 会跳过精确 npm 版本，即使手动改了声明也不会据此重装。已通过临时 registry 验证这一差异，尚未向 npm 公网发布。

使用 `pi config --local` 禁用或重新启用扩展，再 reload；移除使用：

```sh
pi remove '<pi list 中的完整来源>' --local
```

卸载移除受管 Package 和安装声明；`~/.pi/memory/`、Pi Session、认证、用户 SYSTEM/APPEND/AGENTS 和共享压缩设置保留。需要恢复压缩时由用户自行合并修改有效设置。

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
