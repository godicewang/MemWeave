# MemWeave 使用指南

MemWeave 在原生 `pi` 内提供长程任务记忆。你仍使用 Pi 的界面、模型、工具与 Session；扩展管理 Task、结构化认知和请求中的近期窗口。

目前已验收 **Pi v1.3.0**，Node 最低版本为 **22.19.0**；本机测试使用 Node 24.22.0。其他 Pi 版本不在支持范围。真实模型验收使用官方 DeepSeek `deepseek-flash`，精确上下文容量 1,048,576 tokens，MemWeave 总预算为其中一半 524,288，包含输出预留。

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

2. **准备运行文件。** 首次创建 `~/.pi/memory/`，在其中创建下列 `config.json`，并将安装包的 `resources/rule.md` 复制为 `~/.pi/memory/rule.md`。通过 `pi list` 确认安装位置。已有配置和模板应先备份、检查，不能直接覆盖。

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

   六个字段都必须是正整数，B 不得大于 N，不接受额外字段。配置与模板每个逻辑请求读取，包括工具续跑；网络重试使用原快照。模板仅替换这六个变量，不执行表达式。缺失或非法会取消推理，不会自动生成文件。

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

**两类窗口各自处理。** Recent Window 默认保留 200 个交互事件，每批移出 40 个；一条用户消息算一个，一次 assistant 加其全部工具结果算一个。超限时先提醒，正常执行当前 assistant 和工具，可靠结束后提交边界；多个积压批次可同次处理。State 默认 2000 个活动 Fact/Decision，Goal 常驻；满窗提醒管理最早 200 个，最多保留 20 个，由 `state_remain` 提交。提醒期间新认知照常可见，允许暂时超过容量。两种提醒可能同时出现，提交互相独立。

`recent_window_set({"turns": 8, "evict_turns": 2})` 仅调整当前分支；下一请求重新选取原始历史。扩大窗口能恢复该范围的原文，但显示仍受统一预算约束。Rule → Recent Window → State 是请求语义顺序；State 和提醒不写入 Session、不计交互事件。固定内容放不下时会取消，文字使用保守 UTF-8 字节估算，可能早于模型 tokenizer 拒绝。

## 原文与图片

`memory_read` 使用 Unicode 码点 offset/limit，默认总正文预算 8000 字符，上限 50000。例如：

```json
{ "items": [{ "ref": "U3", "offset": 0, "limit": 1000 }], "max_total_chars": 5000 }
```

跨 Task 的 U/A/T 必须同时提供来源 `task_id`，成功时返回当前 Task 可复用的 R。每项独立报告来源、范围、原件完整性和截断状态。

完整回读结果在其后新增不足 10 条真实消息时保持完整呈现；用户、assistant、每条工具结果各计一条，不计结果本身、system、State 或提醒。第 10 条到来后恢复普通窗口预算；不是 10 轮对话。插话按新用户消息计数，不立即取消保护；重启/分支依据原始记录恢复年龄。结果若已被 Recent Window 正常移出，不会额外常驻；完整呈现仍受半额预算，放不下时取消请求。期限内重复呈现会增加输入量。

追溯已知历史认知用 `state_read`，例如：

```json
{"task_id":"task_known","event_ids":["F1","D2"],"max_total_chars":8000}
```

一次 1–50 项，默认 8000、最多 50000 字符，按 Unicode 码点合计正文与证据引用/解释。返回原正文、证据、归档/活动状态；未知 ID 或预算不足逐项说明，不能把截断内容当成完整依据。历史查询的完整结果享有同样的 10 条消息期限。旧的 `{task_id}` 调用仍返回当前 State，不能单独加 max_total_chars；查询不会恢复 Task 或改变认知。

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

本次默认 Rule 增加了历史 F/D 查询和 10 条消息的回读期限说明。升级 Package 不会覆盖 `~/.pi/memory/rule.md`；请先备份，再对照包内 `resources/rule.md` 合并这两处协议说明，保留自己的定制内容。

将来采用 npm 固定版本时，需要 `pi install npm:<包名>@<新版本> --local` 显式安装新版本；Pi v1.3.0 的 update 会跳过精确 npm 版本，即使手动改了声明也不会据此重装。已通过临时 registry 验证这一差异，尚未向 npm 公网发布。

使用 `pi config --local` 禁用或重新启用扩展，再 reload；移除使用：

```sh
pi remove '<pi list 中的完整来源>' --local
```

卸载移除受管 Package 和安装声明；`~/.pi/memory/`、Pi Session、认证、用户 SYSTEM/APPEND/AGENTS 和共享压缩设置保留。需要恢复压缩时由用户自行合并修改有效设置。

## 常见诊断与兼容范围

| 情况 | 处理 |
|---|---|
| 配置或 Rule 缺失/非法 | 检查运行目录、六个字段和模板白名单，修复后重新请求 |
| 有效自动压缩仍开启 | 检查受信任项目设置是否覆盖了全局配置，reload/重启 |
| `MODEL_CAPACITY_UNVERIFIED` | 检查模型、认证和精确容量端点；不使用静态显示值绕过 |
| 预算超限 | 减少完整回读范围或输入，检查超大工具声明/输出预留；不通过截短 State 绕过 |
| 来源 Session/blob 缺失或损坏 | 从备份恢复原件；摘要不能替代原文 |
| 未支持的 Pi 版本/消息表示 | 使用验收宿主与普通工具链；保留诊断，不能静默丢弃历史 |

普通 SYSTEM/APPEND/AGENTS 的发现、信任与内容保留。原生普通 Bash/read、受控动态工具描述和隐藏声明已测试。第三方扩展**强制整段 system 覆盖**会在 MemWeave hook 后覆盖 Rule，明确不兼容；虚拟路由的受控测试因无法核验容量而取消，尚不支持。自动整理历史、任意 MCP/codemode 组合、第三方 custom 消息、用户 `!` Bash 表示、其他模型图片费用和其他 Pi 版本不在当前验收范围。不能由某个受控组合通过推断任意第三方兼容或固定缓存命中率。
