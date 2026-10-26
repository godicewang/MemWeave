# 首次 Task 绑定、混合检索与近期现场恢复

2026-10-26。**2026-10-26 用户已批准，进入实现；完成情况与实际验收另行记录。** 用户最终确认：简单即时问答不创建 Task；是否属于有意义的任务由 Agent 自主判断，需要时进入检索，收到 Top-k 后选择创建或恢复；旧 Task 恢复 State 和近期 Window；采用本机嵌入。早先“所有首次输入均强制绑定”的中间要求已被最新指示取代。用户要求先定稿模型、缓存与恢复设计。本文确定新增接线/配置/持久化边界；先同步直接相关规范，再按垂直切片实现。用户同时要求撤回未显示收益的工具摘要优化，视觉只验兼容、能力结果另记。

## 第一部分：目的、范围和取舍

### 要解决什么

目前模型可以完成业务工具操作却不建立 Task；也可能建立 Task 后只有 Goal，没有保存验证结果。首次绑定改进解决前一个问题，并让后续工具从开始就拥有可追溯的 Task 引用；**它不能单独保证 Agent 保存每条重要新认知**，更不能证明写入的证据在语义上一定正确。

推荐使用同一条路径：由当前 Agent 判断用户是否提出了值得持续维护的任务；简单算术、时间、当前模型/插件信息等直接回答，不创建 Task，也不需要额外分类工具。需要 Task 且尚未绑定时，使用 task_find 发现候选，再选择 task_create 或 task_resume。已有绑定的同目标续作直接继续，不每轮搜索/创建；目标不明先澄清，不伪造占位 Goal。

为区别“只查找 Task”与“已决定建立任务现场”，建议 task_find 新增可选 initialize=true 标记，默认false保持原发现语义。Agent 目标明确且决定进入任务时才填写true；返回仍是候选，不自动建Task。程序只对当前输入已经显式initialize的流程检查绑定；restart仅准备现场，目标明确后仍由Agent声明初始化；普通未触发初始化的回答不一律失败。若初始化后直接答复却未绑定，系统给出失败回执，最多纠正一次；仍失败就停止。已流式显示的原答复不隐藏/删除。**Agent 未进入初始化的错误判断仍可能漏掉Task，这是保留自主判断的取舍，不能宣称程序识别所有实质问题。**

### 检索方式

用本地词项检索和语义向量分别召回，再融合候选，避免只数关键词命中。Goal 作为重要检索字段；标题、摘要、项目和关键词提供其他线索。向量只用于 Task 发现，不向量化全部聊天或 F/D，不自动恢复最高分任务，不增加独立决策 Agent。

建议本地模型为 **Xenova/multilingual-e5-small 的 Q8 ONNX 版本**，基于 intfloat 的多语言 E5。模型卡提供 Transformers.js 加载方式；转换仓库、原模型与运行库均单独记录来源。[模型卡](https://huggingface.co/Xenova/multilingual-e5-small)、[原模型](https://huggingface.co/intfloat/multilingual-e5-small)。原提案时尚未下载；当前已按固定 revision 在本机实际运行，具体正确性、资源和兼容数据见本轮验收记录。

按 2026-10-26 官方仓库文件元数据，Q8 权重 118,308,185 bytes，加分词资源约 135 MB；推理库安装空间另计。首次使用需下载一次，此后本地运行，不向远程发送目标或查询、不新增远程嵌入 API。代价是首次等待、推理依赖及本机 CPU/内存；不能用缓存大小冒充整个进程内存上限。

### 恢复什么

恢复已有 Task 时，用最新 State 和选定旧现场继续；保留本次恢复输入与后续工具过程。来源默认为该 Task 最近使用的已登记 Session 的当前分支，**仅选择属于该 Task 的完整事件**，避免该 Session 后来切到别的 Task 时混入其业务。多候选任务含义不清由 Agent 询问；候选选择由 Agent 作出。

旧聊天只作为请求视图引用，不拷贝进当前 Session、不重新编号，不产生第二套聊天数据库。来源缺失、损坏、压缩后无法验证时明确失败，不拿摘要代替。选定的旧现场在恢复时固定，其他进程随后追加消息不会悄悄改变它。长期 State 仍按原共享设计读取最新提交。

### 新副作用与兼容范围

- 简单问答不创建 Task、不增加分类模型或分类工具。Task工具仅在Agent认为需要时调用；混合检索不每轮后台运行。
- 显式初始化开始后、绑定完成前限制业务工具，包括第三方工具；不能借bash/read绕过这一阶段。未声明初始化的普通问答不进入门禁；用户显式shell/原生命令保留宿主权限。这是执行流程约束，不是安全沙盒。
- 发生违规回答时，新增可见失败回执及最多一次纠正推理。首次选择不明确不会自动恢复相似任务。
- 新增可重建的检索缓存、模型文件以及恢复/失败的轻量 Pi 元数据；旧 Task、State、引用、Window v1 提交点保持，不承诺旧扩展理解新恢复记录。
- 不引入 Elasticsearch、独立向量服务、HNSW、重排模型或后台总结任务。首版 Task 元数据规模先用精确向量比较，实测后才讨论更复杂索引。

## 第二部分：推荐接线、数据与验收

### A. 首次绑定与有界纠正

1. 未绑定分支的 task_find({query,keywords?,limit?,initialize:true}) 表示Agent明确进入初始化；普通调用默认initialize=false只发现，不切换或强制绑定。标记从当前真实输入的原生调用/结果核验，不新增初始化数据库。initialize声明生效后，仅允许task_find、state_read、task_status、task_create、task_resume；其他模型工具返回TASK_BINDING_REQUIRED，绑定后开放。未经验证的工具旁路不宣称覆盖。
2. 完整Rule保留简单即时问答豁免，明确由Agent判断是否需要Task；只查历史或需澄清时可以普通task_find，不填写initialize。目标明确且需要任务时才显式初始化。已有有效绑定则复用，独立新目标创建新Task。task_find不自动切换，task_resume才切换，检索分数不决定绑定。
3. 显式 /memweave-restart 仍表示准备**新** Task，保留种子，不因旧任务相似而自动恢复旧 State。用户明确要求回到旧任务才走恢复流程。新目标明确时先task_find initialize=true声明初始化，再task_create；候选不能改变本次新Task意图；目标未定先澄清。
4. Pi 1.3.0/1.4.0 公开 agent_before_settle 可以请求继续，但原生源码要求原始上下文末尾不是 assistant，或存在待发送消息。仅返回 continue=true 不能在最终 assistant 答复后启动纠正。因此建议追加一条可见原生 custom_message 失败回执，再让原生循环继续；不 fork Loop、不伪造 user 或 toolResult、不删除旧答复。
5. 提议 custom_message 类型 memweave.task.binding.v1，details={version:1,trigger_user_entry_id,rejected_assistant_entry_id,attempt:1,reason:"TASK_BINDING_REQUIRED"}；正文是固定程序失败说明。没有用户目标、事实或聊天副本，不分配 U/A/T，不计真实事件，不可作 evidence。Window 仅接受当前祖先链上与原件逐字段一致的自有回执，经专用薄适配展示/预算；不能借此放行任意第三方 custom 消息。该消息需要保留在原生 Session，这是新增边界。
6. 纠正计数属于当前真实输入，自动工具续跑不重置；中断/错误不强行继续，网络重试不产生新回执。reload/重启从轻量回执定位同一输入，不能将同一违规再次纠正一遍。默认最多一次；仍失败时明确停止，不以部分 Task/Goal 提交伪称完成。
7. 程序不根据问号、句长、正则或额外模型推理区分问题性质，只执行Agent已显式声明的初始化。目标或候选不明时，Agent可先普通查询并澄清；误声明initialize后又无法绑定，最多纠正一次再停止，不猜造Goal。显式restart仍有已确认的新Task意图，但当前输入目标未明时不自动触发门禁/失败纠正，先等待澄清，不能因相似候选自动恢复旧State。

### B. 多路召回与配置

词项通道复用无依赖的 MiniSearch 7.2.0（BM25+ 系算法）进行字段加权：Goal 3、title 2、keywords 2、summary 1、project_name 1；中文等语言使用 Intl.Segmenter 分词。另有显式关键词匹配通道和多语言向量余弦通道。每路先取候选，最终用加权 RRF 合并：

```text
score(task) = Σ weight[channel] / (60 + rank[channel](task))
```

默认三路权重为词项 0.45、向量 0.45、显式关键词 0.10；每路候选 50，最终 Top-k 默认 5，调用显式 limit 优先。通道未召回该 Task 则贡献 0；相关性并列才用更新时间/task_id 稳定排序，更新时间不盖过相关性。无关键词信号时不虚构该通道命中。RRF 使用各路名次，避免直接相加尺度不同的 BM25 分数和余弦分数；该思路有主流检索系统的公开实现依据，具体权重是本项目待验收初值。[OpenSearch RRF](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/rrf/)、[MongoDB 混合检索](https://www.mongodb.com/docs/vector-search/hybrid-search/hybrid-search-overview/)。不安装这些服务。

模型使用固定 revision 761b726dd34fb83930e26aab4e9ac3899aa1fa78；Q8 文件 sha256=f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193。实施时再核验来源、许可证、所有必需资源哈希和运行库精确稳定版本。E5 按原模型要求使用 query:/passage: 前缀、mean pooling 和 L2 归一化，输出 384 维；输入最多 512 模型 token。查询过长明确提示缩短，不默默漏掉用户后半段；文档优先完整 Goal、标题、关键词，摘要只使用余量并记录索引范围。索引范围不改变原 Task 内容。

提议新增全局配置组，仍放包内 defaults.json 与用户 config.json 两层中，不增加 Agent 通用配置工具：

| 配置组 | 推荐初值 |
|---|---|
| task_binding.max_corrections | 1；允许 0–3，0 表示违规直接失败，不表示豁免绑定 |
| task_search.default_limit / candidates_per_channel / rrf_constant | 5 / 50 / 60 |
| task_search.channel_weights | lexical=0.45、semantic=0.45、keywords=0.10；正数合计 1 |
| task_search.field_weights | Goal/title/keywords/summary/project=3/2/2/1/1 |
| task_search.embedding | 固定模型标识/revision/Q8；首版不接受任意远程模型执行代码 |
| task_search.cache_max_bytes / model_idle_ms / model_timeout_ms | 32 MiB 派生缓存驻留估算预算 / 60000ms 空闲释放 / 180000ms 下载及单次推理超时 |

task_find 保留 query/keywords/limit，并新增可选initialize（默认false，仅标记已决定开始初始化，不自行创建），仍返回数组；候选增加goal、workspace、融合分数和各通道排名，帮助Agent判断；分数不是“恢复正确概率”。默认不限定当前工作区，但明确展示 workspace，不把异工作区结果自动恢复。没有相关候选或候选不适用时创建新 Task；不把 Top-1 当确定答案。

### C. 模型与派生缓存

新增路径全部由 src/storage/paths.ts 提供。建议模型资源放 ~/.pi/memory/models/，派生记录放 ~/.pi/memory/search/v1/。源数据仍是 index.json 加对应唯一 State；派生行仅包含 task_id、当前 Goal/发现元数据、来源版本/指纹、模型 revision 和向量。可删除重建，不能用派生值覆盖 State，不保存全部 F/D 或交互历史。

按内容指纹复用向量，仅 Goal/发现字段或模型 revision 改变时重算；普通 F/D 追加不能导致全部任务重新嵌入。旧任务首次查询时按需建立索引，未更新/缺失的 Goal 来源仍须核验，不能把旧缓存误当现值。写派生文件使用锁与原子替换；失败只影响检索/缓存，不能回滚已提交 State 或伪称已索引。

每个 Pi 进程最多一个本地嵌入工作线程，按需启动、查询串行，空闲 60s 释放；初版不额外缓存查询向量。缓存驻留 32 MiB 上限不包含模型权重/原生推理内存或 Pi 历史；超限使用分块读取/精确比较，不抛弃旧 Task。磁盘按每 Task 当前派生记录维护，更新替换，不为每次查询/版本追加无限文件；同模型只保留当前资源，升级清理仅限可重建模型/派生资源，不删除用户 State 或 Session。

模型下载、校验或推理失败，task_find 明确失败，不静默冒充完整混合检索，也不触发自动恢复。模型权重不能跟随 npm 包内嵌；安装依赖、首次下载和离线使用须在用户安装说明写清。运行库/模型实际内存、耗时和平台支持待专项验证，不凭模型文件大小承诺 RSS。

### D. 旧 Window 恢复定位

建议新增轻量 Pi custom memweave.resume.v1：

```text
{task_id, source_session_id, source_anchor_entry_id,
 seed_event_ids, target_anchor_entry_id, recent_turns, evict_turns}
```

source_session_id 必须已登记在目标 Task；source_anchor 固定当时可验证的原生分支，seed 为该 Task 最近 N 个完整事件，角色及工具配对整体保存。target_anchor 标定本次恢复过程开始之前的当前位置。字段只存 ID 和参数，不存正文、文件路径副本、长期 State 或新编号。

恢复在 Task 切换前核验来源并准备定位，再提交既有 scope；部分写入失败按明确阶段报告，重试同一恢复调用不得重复切换或换一批种子。新增元数据只能由原工具调用、原件和目标 Task 共同核验；不接受正文自行声明来源。成功后请求视图为旧种子加本次恢复输入/工具及后续交互，去重后仍受 N/B、分池和完整事件规则约束；提醒和提交保持独立，不因恢复重放业务操作。

恢复时不取旧会话的全量积压，不携带旧 pending；超过 N 时按新现场的既有 prepare/commit 规则处理。源种子被滑出后只剩当前会话近期过程。fork/tree/reload 使用祖先链定位；缺失/损坏立即取消，不自动换到另一个来源。扩大 N 时只能在已固定的原分支补取可核验目标事件，不能受来源文件随后切分支影响。新建 Task 与显式 restart 保留原有语义，不用 resume 元数据冒充 restart。

### E. 定稿后开发/验收顺序

1. 先同步 Task §8/10/11、Rule 技术稿与两份固定模板、State 冷启动/收尾及 Window 恢复章节；校验模板逐字一致。
2. 完成首次绑定门禁/有界纠正垂直切片：简单问答不创建Task、不增加分类调用，有意义任务的显式初始化、新目标、已有绑定、普通只读发现、明确续作、目标不明、错误/取消、门禁、纠正上限及双宿主。确认失败回执不成为用户事件或证据。
3. 完成本地混合检索：真实模型/固定本地样本比较纯词项与混合 Top-k；同义表达、中英文、同关键词不同 Goal、跨工作区、多任务、缓存失效、离线下载失败及并发。确认 Agent 选择而非程序自动恢复。
4. 完成旧 Window：单/多 Session、同 Session 后续其他 Task、分支切换、来源丢失/损坏、压缩表示、原件/引用、多模态、部分提交与重试；旧原始消息和 State 不被改写。
5. 全程使用完整发布提示/环境与真实 DeepSeek 检查业务/认知；另行测本机嵌入的冷/热耗时、内存与磁盘。最后双宿主、完整发布入口和相关真实专项；测试失败继续停止发布，不用前一轮元数据小改动的结果替代。

## 实现选择补充（授权调研范围内）

检索词项引擎复用 MiniSearch 7.2.0，不自行维护 BM25 实现；无传递依赖，支持字段加权与 Intl.Segmenter 自定义分词。融合仍为既定加权RRF。嵌入运行时采用 ONNX Runtime CPU 1.30.0＋项目已有 @huggingface/tokenizers，省去 Transformers.js 的浏览器/图像依赖；相同E5 Q8、query/passage前缀、mean pooling及L2归一化。三个本机对照样本与Transformers.js参考向量最大绝对差约2.56e-8；不据此承诺所有任务检索质量。[MiniSearch](https://github.com/lucaong/minisearch)、[ONNX Runtime Node](https://onnxruntime.ai/docs/get-started/with-javascript/node.html)。
