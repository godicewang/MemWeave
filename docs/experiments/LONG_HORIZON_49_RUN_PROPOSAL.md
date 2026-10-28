# 49题双变体并行执行与持续观察方案

2026-10-28。状态：用户已要求完整测试、原生/插件混合隔离并行、尽量10个真实解题实例、当前会话持续观察并写文件；资源、费用/整体时限和单题准入失败处置均已获用户确认；本文先于接线实现更新。

## 第一部分：目的、实际约束和已确认决定

本次固定使用已审查的49题（35 SWE Pro V2、14 TB 4.0），两个变体各一次，共98次真实Pi解题；Pro另有70次官方补丁重评分。原生与插件可在同一活动任务组内并行，每个Trial各有容器文件系统、Pi配置、Session和MemWeave记忆。官方任务、单题时限、资源、网络、评分方式及完整Pi/Rule/工具保持既有约定。

现有实现仍是单活动Job、变体顺序运行、并发最多2，并且不能执行定向目录。本轮请求已授权定向清单接线和双变体并发方向；具体资源安排不能靠修改数字绕过检查。

本机实测14 CPU、48 GiB物理内存，宿主卷剩余约473 GiB；专用Colima仍为8 CPU、16 GiB、120 GiB磁盘，当前无活动容器。每个SWE任务官方配置1 CPU、4 GiB，10个解题实例需40 GiB内存额度。TB含2–4 CPU、4–8 GiB任务，本机无法在所有TB组合上保持10个实际解题实例且不超额占用。

用户已批准扩容既有专用Colima为12 CPU、42 GiB内存、240 GiB虚拟磁盘；需要重启该虚拟机，保留已有镜像/卷、VZ/Rosetta、挂载及关闭SSH-agent转发的设置。物理机仅余6 GiB名义内存给macOS及其他程序，日常使用可能受影响；如宿主压力不允许，降低活动任务量并如实记录，不能伪造10并发。虚拟磁盘上限增加不代表立即占满，但扩盘不能原地缩小。

10并发定义为同一时间实际执行Agent解题的Trial数，不把网络sidecar、评分器、安装或空闲容器计入。优先在SWE阶段达到10，原生/插件尽量各5；随后按资源包络和未完成数量调节，TB通常低于10。即使请求10并发，仍须保留资源检查、原有隔离与官方单题额度。

用户已确认整批最多 **20美元、48小时（172800秒）**，从本次Campaign开始计时，覆盖准备、控制、全部解题、重评分及收尾。两个任务集与变体共用账本。采用DeepSeek峰时费率保守估算（输入miss/缓存hit/输出每百万token为0.3/0.006/1.2美元），同时保存Pi原生估算。响应完成后usage才可见，并发在途可能导致费用超出估算阈值，不将其声称为账单硬上限。达到阈值停止新模型工作、取消在途解题并采集补丁；有整体剩余时间时完成已采集补丁的无模型评分。整体到期后只做有界取消与证据收尾。

用户已确认某题无法通过镜像/官方控制准入时，保留49题计划，阻断该题的两个变体并明确记录原因，其余准入题继续；同档已审查候补只在模型前使用。无候补的槽位集中待用户处理，不自动减分母、换档、换集合或修官方题目。公共软件/凭据/观测或协议接线失败属于全局问题，仍须阻断相关模型运行。

提问依据：根AGENTS第2节、实验实现设计第3/9/11/12节、缓存设计的完整预检要求及49题清单的候补/执行边界。上述决定已确认；先更新设计，再写边界测试并实现。

## 第二部分：执行与观察接线

### 1 定向任务、冻结和分组

显式读取`long-horizon-49-v1.yaml`，核对完整ID、来源提交、指令/全任务哈希、难度和候补顺序。运行记录覆盖全部49×2计划行；目录理由和审查意见不进入Agent上下文。保持原子冻结、产物/代码/镜像摘要、凭据排除和无自动Trial重试。

使用Harbor 0.24.0公开Job/Trial配置，将两个变体配置放入相同的任务组，按官方资源上限安排组大小。Harbor继续拥有Trial、环境和Agent Loop调度；不自建通用调度服务，不patch核心或node_modules。是否能精确限制变体各5、逐任务/变体配对和用途记录，以本机真实API核验为准；无法等价实现时先讨论。

每个拟付费任务组在首次推理前完成来源/镜像/官方控制及双变体完整软件加载预检。复用不可变软件缓存，只复制到新实例。较大集合分组执行以限制镜像、内存与磁盘占用；组间不共享认知数据。并发变化及其原因保存为证据，不能只记录配置目标10而宣称实测10。

### 2 官方评分与隔离

SWE解题阶段离线且显式关闭verifier，只捕获该次补丁；由冻结官方PatchReplayAgent在全新沙箱评分。新任务组接线必须保留补丁和原尝试的一一对应，不能让多变体混合Job误把另一变体补丁用于重评分。TB保留原verifier模式、测试上传、资源与网络，不让评分容器接触另一变体的文件。

每题两个变体使用相同模型设置，沿用已验收的DeepSeek Flash、thinking off和同一完整候选包。候选包来自可核对的干净源码，实验开始后不边运行边修插件或改变Rule；观察发现的问题先记录，在本次成绩外另做修复讨论。

### 3 一个持续运行的观察器

不创建automation、cron或未来定时任务。在当前活动执行期间持续读取Job/Trial生命周期、容器实际状态、原生Session已完成usage、工具事件统计和错误，维护实时观察文件。当前助手会话循环查看新增异常与代表性原件，追加有证据的分析；监视进程本身不代替对badcase的判断。

需要先解决活跃Trial证据可见性：已核查Harbor Trial会把agent日志目录挂载到宿主，活跃Session原则上实时可见；仍需实际验证，不能从旧独立容器测试推断只在结束可见。优先使用Harbor公开日志/挂载/下载接口读取原生Session的增长，费用与取消共用Campaign账本。只派生计数、游标和原件引用，不另建完整聊天副本，不向模型增加观察工具、提示或记忆事件。读不到可靠用量时必须标未知，不能声称硬费用保证。

观察包括：实际解题并发和各变体分布；模型是否继续返回；安装/容器/网络/解析/评分异常；模型与工具错误、重复调查、Task/State/Window活动和停止条件。程序频繁采样并按变化写入，助手持续复核；“一直观察”不等于保证逐毫秒人工理解每个token。监视停止、凭据泄漏或运行脱离可观察状态时应保留原件并停止相关在途工作，不能无人观察继续收费。

### 4 文件与报告

仓库外Campaign原件保持私有；持续追加`observations.md`、机器状态和事件/费用摘要，只引用Pi原生Session而不复制聊天。仓库`docs/experiments/`保存不含密钥/原始私聊的阶段观察、最终比较表和插件badcase报告。

最终按任务集、难度、变体及历史锚点/新题分组，列出全部计划的官方评分、执行/评分状态、输入/缓存/输出、已知费用及未知项、Agent/准备/评分/整体墙钟、模型/工具调用、记忆活动和证据引用。并发总墙钟不能由各Trial时间相加代替，未运行/准入失败不能作能力0分。报告区分目标并发、实际峰值和维持10个真实解题实例的时段。

badcase区分插件实现/接线错误、记忆使用/约束保持错误、两边共有的业务推理问题及基础设施失败。每条给出任务、变体/尝试、现象、原因证据与不确定性、对应原件；同步到`docs/DIFFICULT_CASES.md`，不把没有Window移动的失败直接归因为记忆遗忘，不为报告篡改官方评分。


### 5 本轮最小实现契约

新增严格`schema_version: 2` Campaign配置，复用subject/runtime/model/variants/limits/root；`catalog`路径与`catalog_sha256`指定冻结清单，execution固定一次重复、无重试、linux/amd64，concurrency为2–10。旧schema1及validate/run/report兼容。不能以随机seed近似定向ID。

启动冻结49×2全部计划、目录与源码摘要；按目录顺序分组（SWE最多5题双变体，TB按官方资源取整为题对），每组依次完成官方镜像、oracle/nop、双变体软件预检、不可变组锁、混合解题Job和官方评分。任务镜像/控制失败记blocked；公共软件/凭据/协议/观测失败全局停止。2026-10-28用户明确确认：有已审查的同集合、同档候补时，模型前按冻结顺序使用；候补不足才保留该槽位阻断。保留原题及失败候补的全部准入记录，不跨档/跨集合、不因模型结果换题。49个槽位ID保持不变，另记实际task_id/标题；对外表格明确显示S04→RS01等替换，不把替补成绩写成原题成绩。每组在首次推理前冻结新的实际计划版本。

原始Trial以(task_id,variant_id)唯一匹配。SWE按变体建立独立重放输入目录，只复制该Trial原始result.json与model.patch，记录源路径和SHA；缺补丁标明缺失，不伪造空补丁。每变体独立评分Job；解题完成即评分，减少止损时未评分结果。

持续观察增量读取原生Session完整JSONL行，保存偏移与去重ID，只输出usage/调用/错误统计和原件引用。统一费用用于所有Job；未完成尾行等待，非法完整行或原件缩短/替换属于观测错误并阻断模型。每秒检查停止条件，按变化或最长15秒写live.json、events.jsonl、observations.md；记录Docker状态和Trial阶段。实际解题峰值依据agent_execution有效区间与快照核验。当前助手持续复核并追加仓库内阶段观察。

组证据位于groups/<id>/，含runtime-assets和组锁；Campaign根保存experiment.lock.json、run.json、实时观察和总报告。离线报告保留全部98行，infra/blocked/not_run/unknown与官方0分分开。总墙钟取Campaign首尾差，不相加并发Trial时间。

实现核验补充：Harbor 0.24.0公开`Job.create`与`Job.add_hook(TrialEvent, callback)`提供真实agent-start/agent-end生命周期，观察器据此计数；不从“容器存在”猜解题并发。每个Job在独立子进程调用此公开API；父进程统一观察和止损。


### 6 已确认候补的实现与本轮窗口延续

S04 Navidrome镜像拉取发生unexpected EOF，用户已确认按冻结顺序使用SWE简单档RS01。旧run `20261028T104839Z-2121023e21`在任何模型推理前安全停止，费用0，原件和98行未完成报告保留；这不是任何变体的失败成绩或付费重试。Qutebrowser并行缓存已结束、退出0。

schema2增加可选`preflight_parent`，仅用于继承**未开始任何模型Job**的同清单、同候选、同runtime/model配置的已结束准备记录。它必须位于同运行根runs/，校验父证据索引、来源与模型调用为0；存在solve Job或Session usage即拒绝，不能作为付费续跑或重复尝试接口。新锁保存父run关键文件哈希、最初窗口起点/截止与0费用证明。费用仍20美元；新run时限取配置剩余额度与父窗口剩余时间的较小值，总截止不晚于2026-10-30 18:48:39 CST。

只继承父run中任务级镜像/控制阻断，以便本轮直接选择已确认的候补、不偷偷重试原题；不继承Session/Task/State、模型补丁或能力成绩。新题/候补仍做官方镜像及oracle/nop和双变体完整预检。首批同档候补消耗顺序全局唯一；候补自身失败继续下一项，耗尽则两变体同槽位blocked，其他合格槽位继续。公共软件/认证/观察失败全局停止。

每组group.lock保存实际任务与slot_task_id、候补来源及模型前actual_plan；主比较表仍49×2槽位，并列原题与actual_task_id/标题。另附每个被替换原题或失败候补的双变体阻断行，不把这些行混入模型通过率分母。模型启动后的成绩、耗时和记忆压力不能触发候补。

评分证据验收：最终run.json/live.json一并入索引；报告只接受索引覆盖的成绩原件。SWE有效成绩还必须核对原尝试、同变体handoff、原补丁/结果SHA、重放Job的source_job及副本SHA一致。缺源或错配标为未知/接线错误，不能作为能力0或成功。


### 7 用户最新优先级：先完成一题闭环

2026-10-28用户明确要求先完成一题“原生＋插件真实解题→官方评分→对照报告”，再扩到10并发；其余镜像准备可独立继续，不能让整组准备拖住已具备条件的题。非阻断框架完善后置。

先以首个S01 Flipt做bootstrap阶段，只执行该题的两次新模型尝试和新沙箱评分；此阶段plan为2行，并保留full_plan的98行总体计划。bootstrap完成并审计报告后才继续其余48题，不重复S01。schema2新增phase=bootstrap/full（默认full）；这是有明确范围的分阶段评测，不将1题报告冒充49题完成。总体20美元/原截止不变。

可选control_parent指向已完成历史run，仅复用官方oracle/nop控制，不复用Pi模型成绩。复用须程序核对来源提交/完整任务哈希、精确镜像ID与平台、Harbor版本、Docker服务版本、默认官方评分配置、oracle=1/nop=0且无异常、源结果SHA符合其证据索引；保存证明和控制结果副本。条件不符则照常重跑控制。此复用规则已存在于实现设计§12，当前仅补齐接线。S01具备相同条件；本轮新的模型解题及新沙箱评分不能由旧成绩代替。

当前单题闭环继续采用两个变体分别交接补丁、分别在新沙箱评分的已验证接线；评分并行优化后置，不阻挡真实解题。报告阶段完成后，再继续扩展其余任务的执行吞吐。


### 8 单题闭环之后：就绪题对流水线

S01 bootstrap已完成，双方真实解题及官方评分均1分，见单题报告。接下来的必要变更只处理剩余48题吞吐与同一窗口的阶段接线，不改插件、Rule、Pi模型/工具、官方任务或测试，不开发额外框架功能。

full阶段新增bootstrap_parent，必须是同根已完成的bootstrap、仅首个槽位两次真实尝试、完整官方评分和无损坏证据、相同清单/候选/模型/runtime及未改变的Pi适配和缓存代码。父阶段允许业务得0，但须真实模型响应、正常补丁捕获和完整评分，不能继承模型/基础设施失败。只读取并引用原结果，不向新Agent复制任何Session/Task/State，也不重跑S01。新阶段活动plan96行，总报告按full_plan合并98行；父结果明确标origin_run，原件仍在父run。preflight_parent仍只允许无模型准备记录，两者职责分开。

总额度仍20美元，新推理共用的可用余额是20减去已核验bootstrap费用0.03647958；原截止2026-10-30 18:48:39不变。账本同时记录继承金额、本阶段usage与合计；每个Job不能重获20美元。任何未知费用、父证据损坏/错配、重复计划都阻断继续。

每个任务槽位独立经历官方镜像/控制、双变体软件预检、实际计划锁、两次并行真实Pi解题、独立补丁交接和官方评分；不等待5题全部准备。主进程用最多5个题对工作槽执行Harbor Job，Trial、容器、超时、网络及清理由Harbor管理，不自建Agent Loop或通用工作流。已有镜像/软件缓存的题优先，排序只看准备状态和固定清单顺序，不看两变体成绩。为两套任务集都获得进展，初始就绪SWE波次后穿插TB，不把所有TB排到最后。

CPU、内存、存储按每个题对的两份官方Agent/评分器峰值包络（含可能的同档候补）做本机配额约束；最多10个真实解题实例，资源不足时减少，准备/评分/sidecar不充数。新建Dockerfile镜像串行控制；已缓存镜像的验证不排在慢构建之后。共享状态文件加进程内锁，软件对象仍用既有不可变缓存锁。公共软件、认证/协议或观察故障停止全部在途工作；单题镜像/官方控制失败按既定候补、耗尽后仅阻断该槽位。

同题两边补丁齐全时，在同一Harbor评分Job放两个官方PatchReplayAgent，分别指向自身交接目录，在两个新沙箱并行评分；集合不对称则仅对存在原补丁的一侧评分。报告从source_job识别评分变体并严格校验绑定，保留对bootstrap旧的独立评分Job格式兼容。此改变只减少评分排队。费用触限停止新推理、取消在途解题，整体时间有余额时完成已捕获补丁的无模型评分；时限到期则只做有界清理与证据收尾。


### 9 已确认的完整题对续跑

共享npm准备失败后，用户已确认采用[受限续跑方案](COMPLETED_PAIR_CONTINUATION_PROPOSAL.md)。schema2新增completed_parent，与bootstrap_parent互斥；只导入已结束阶段内双方正常真实解题、补丁与首次官方评分、已知usage费用均完整的题对，保留来源链。所有实际启动模型的题对必须完整，否则拒绝，不静默重试。传递原镜像／控制阻断与候补消耗，不复用认知数据。S01和S06跳过模型重跑，总计划98行保留；S06首次0/0不被诊断0/1替换。继承累计0.071684472美元及2026-10-30 18:48:39 CST原截止，非新增20美元或48小时。


### 10 已确认的Pi前探针故障与计费中断保留

用户确认[探针及中断恢复方案](INTERRUPTED_PHASE_RECOVERY_PROPOSAL.md)。S05因官方镜像缺curl在Pi之前失败，改用已安装固定Node内置HTTPS检查相同端点／超时／离线边界，并先保存脱敏结果，不装系统工具。仅这一份经SHA对审计的适配器等价变化允许继承父证据；其他适配变化仍拒绝。S03模型尝试及费用保留、官方原补丁评分1/0另标中断，不重新解题；中断归档可能早于后台最后Session写入，不称为最终状态。S05只有精确旧源码的Pi前探针异常、无Pi输出／Session／usage且原补丁为空时才可证明0模型，随后允许首次真实Pi；其他未知费用／半边模型尝试仍拒绝。98行、20美元及原截止不变，累计0.093063336美元。可靠观测和整体时限仍允许时，公共故障停止模型但允许官方无模型评分完成已捕获补丁。


### 11 2026-10-29用户要求持续完成49题

用户明确授权：继续监督至49个题对实验完成；适配性、缓存、实验环境提案由执行者酌情批准，问题修复后继续；取消整批时间和token额度限制。美元上限另行询问，在未明确答复前保留原20美元费用保护，累计历史估算0.093063336美元不清零。此授权取代旧48小时截止，不放宽官方单题资源／解题／评分时限，不改题目、测试、生产插件、Pi工具或Rule。

schema2增加completion_mode=window/all_tasks（旧默认window）及unlimited_cost布尔（默认false，仅在用户明确取消美元上限后启用）。all_tasks不设整体墙钟截止，账本仍记录首个起点、所有阶段与费用。环境与协议错误修复后恢复，不以blocked占位冒充49题完成。正常结束但官方0分属于完成，不因分数重跑。模型中断、缺失有效评分等基础设施失败保留原件，完整题对恢复运行单列，与原首次中断／历史补丁评分分开；不按成绩选取最佳尝试。S03因此进入完整题对恢复，旧中断费用与1/0补丁结果保留。S01、S06已有正常模型对照不重跑；S06评分不稳定单列限制。

此前无模型镜像／控制阻断在all_tasks恢复中重新准入，不永久排除任务；原已确认S04→RS01的绑定保留。已拉取的官方预制镜像按原引用、同仓库RepoDigest与linux/amd64核验后直接冻结复用，缺失才拉取。TB按未修改官方Dockerfile预建、记录context与镜像摘要，正式任务仍使用原资源／评分定义；准备失败继续排查并恢复，不修改测试获得分数。

准备代码变化只影响安装／缓存／镜像接线，必须逐项记录新旧SHA及代码等价性检查；真实Pi调用、完整候选、提示／工具／补丁和官方协议不变。已计费结果只在证据、候选／模型身份与费用可验证时继承。对恢复题从主比较中移出旧中断行，置于historical_attempts，仍纳入总费用；新对照不覆盖旧记录。所有98行正常完成后再做最终汇报，不创建定时任务。


### 12 已审议：musl镜像兼容与准备故障隔离

S09已实测Alpine3.20/musl1.2.5，官方GNU Node24.22二进制缺fcntl64，尚未进入Pi。按用户2026-10-29自主修复授权，为musl任务提供Agent私有GNU运行库：从已冻结的干净Ubuntu官方任务镜像只导出明确列出的系统运行库和许可，保留官方Node原始二进制，以独立GNU loader包装入口，并以私有启动兼容文件恢复正常node路径的process.execPath／argv[0]，确保fork子进程沿用同一入口；不覆盖官方系统libc，不设置全局LD_LIBRARY_PATH，不改业务仓库、Pi JS或插件。原生和插件使用相同Node24.22与私有库，子进程和onnx本地embedding均须真实验收。源码／库／归档摘要记录；patchelf原型失败已留证，不用于正式入口，配置、Session和认知仍独立。

GNU镜像的准备路径保持此前02776f5相同组件与字节规则，显式沿用已审计GNU准备recipe 214780dd31b908ff78644ee5fd1a62fa4f82dd22afcb28f038a47d0998a32823，保留原对象身份与实际生成来源，不将旧对象伪装成新对象；musl单独标记ABI和新recipe。每题仍完整加载核验，正式Trial不创建缺失缓存。

已在多镜像通过的共用代码，若某一镜像的软件准备失败，先标该题preparation_failed并记录具体原件，不取消其他已准入模型；全批结束后修复并继续该题。认证、模型协议、候选不一致、观测／账本不可信仍全局阻断。避免把Alpine单镜像问题变成无关TB／SWE中断。此变更取代旧“任何软件预检错误即联动取消所有题”的实现，不放宽准入；失败题不得进入模型。

TB正常结束的原始Trial状态scored可继承，和Pro completed_patch分别判断；公共故障取消的双方整对重跑，原正常单侧成绩作为历史保留。真实预算耗尽和未完成评分分开报告，不将无评分或基础设施异常写为能力0分。

最终无模型验收：`analysis/long49/s09-musl-final-recipe-acceptance-20261029/acceptance.json`通过；原生4个工具、插件16个工具及384维本地embedding，双方Node24.22／Pi1.4及timeout+pipefail CLI壳通过，模型端点401、普通外网阻断，模型请求0。118项实验自动检查、Ruff及编译通过。AST核对相比02776f5仅ExperimentPi.install变化，run／exec_as_agent等模型执行方法完全相同；生产源码与冻结f3931ce不变。

### 13 美元上限取消

2026-10-29用户明确答复“取消20美元上限，持续运行至49题完成”。后续阶段unlimited_cost=true，继承所有历史费用、正常结果及中断记录，不再以20美元停止。已启动且冻结的171721阶段继续现有试验；其费用保护尚未触及，若触及则保留收尾证据并以无限费用授权恢复，不结束整批目标、不为修改活跃锁而破坏证据。整批时间及token限制已取消；官方单题资源与时限、凭据隔离和评分可靠性要求不变。

### 14 环境恢复候选：独立准备QEMU，不在活跃试验切换

S14控制长期停在Go1.22.12驱动等待多个vet僵尸，S08另外两次基础命令git／rm退出139。尚未证明Rosetta是唯一根因；按用户环境自主修复授权，先准备可回退的QEMU amd64用户态工具作为后续诊断／恢复候选，不切换当前活跃阶段。仅作用专用Colima虚拟机的binfmt，不修改macOS的Rosetta安装、官方镜像／测试／单题预算或生产插件。QEMU通常慢于Rosetta，可能增加验证时间，故须分别记录运行阶段与同题两侧一致的仿真器，比较时间时不混淆。

后续只有在当前模型／评分阶段关闭并索引证据后，才可记录现有binfmt、固定工具镜像digest／版本，暂时禁用该VM的Rosetta注册并注册QEMU amd64；先验S14官方oracle/nop、完整双侧SDK／embedding与网络隔离，成功后恢复剩余题。失败则保留无模型证据并恢复原注册，继续诊断；绝不在同一题对中途混用仿真器或按成绩切换。当前步骤只拉取工具并封存摘要，不执行privileged注册。依据：[Lima多架构文档](https://lima-vm.io/docs/config/multi-arch/)、[binfmt上游](https://github.com/tonistiigi/binfmt)。

### 15 Public OCI blob preloading (approved under environment autonomy)

The S10 manifest contains 5654 MiB of compressed layers; its largest layer is 2516 MiB. Host and VM probes of the same 4 MiB range measured 0.148 and 0.123 MiB/s. Add a preparation-only utility in experiments/tools/: fetch exact public GHCR blobs with bounded range concurrency, verify complete SHA256 and size, import the unchanged manifest/config/compressed layers as an OCI archive, then retain normal official admission. No task, Dockerfile, score, model call, or task resource changes.

Use up to 32 workers and 4 MiB ranges, disk-backed partial files, a per-blob lock and atomic verified publication. Require HTTP 206, exact Content-Range and body length; reject unsupported ranges, damaged caches and any final digest mismatch. Public anonymous tokens and signed redirect URLs stay in memory and never enter logs/CLI/manifests. Persist only canonical public references and digests. Generated OCI archives contain verified blobs and layout/index metadata only. Test range boundaries, corruption, ignored ranges and cache reuse against a local HTTP fixture before a real S10 import. Tool source is separate from the frozen inference adapter; active trials continue unchanged. References: https://github.com/opencontainers/image-spec/blob/main/image-layout.md and https://github.com/opencontainers/distribution-spec/blob/main/spec.md .

S19的4MiB可选预加载触发片段大小／120秒的组合保护而失败，原日志未区分两者，不能确定唯一原因；未准入，最终由标准Docker pull取得。准备助手可调用既有fetch_blob的chunk_size=1MiB，保持相同120秒保护、精确206/Content-Range、最终SHA和32路上限，并记录调用脚本SHA／实际片长。先用一个真实公开多片blob验证完整digest。S21–S35可按固定顺序只预取到主机内容缓存、不立即load，避免挤占VM中五个SWE题对的磁盘预留；后续按需导入必须使用已验证的原manifest/config/layers，继续原正式准入。此为有限准备进程，不产生模型调用，不创建定时任务。

### 16 Docker registry transport repair

After all paid solves and grades of phase171721 finished, the phase closed with14 normal pairs and complete evidence. Multiple public registry HEAD requests returned EOF. Read-only probes confirmed the host system proxy and VM shell use the existing credential-free proxy, while DockerInfo reports no daemon HTTP/HTTPS proxy. Configure only this dedicated VM daemon to use the same VM proxy and restart Docker after owned preparation clients stop; preserve the previous daemon config and rollback path. No host proxy settings, task container proxy environment, allowlist, Dockerfile or score is changed. Verify DockerInfo, public manifest/pull access and original-image controls before the unlimited continuation. Continue all historical fees and primary scores.

Docker daemon proxy settings follow https://docs.docker.com/engine/daemon/proxy/ . OCI layout was checked against the upstream image-layout specification; a real canonical ghcr.io local fixture import preserved RepoDigest exactly. Unqualified OCI fixture names do not resolve normally in this engine and are not supported by the preparation CLI. All CLI image references are fully qualified GHCR names.

### 17 Cache-ready ordering correction

The classifier previously returned cold rank3 for every Dockerfile task, even when the exact official main/verifier contexts were already prebuilt; initial interleaving then placed5 missing SWE images ahead of those ready TB tasks. This conflicts with the confirmed ready-pair priority. Under the environment autonomy authorization, recognize deterministic local formal/prewarm tags for both official contexts as advisory readiness, then interleave suites within each readiness rank rather than putting cold SWE ahead of warm TB. Derive tags from the frozen slot ordinal, role, platform and unchanged context SHA. Every task still passes original build/admission/controls and complete dual software checks before inference; readiness never substitutes for provenance or changes tasks, reserve order, budgets, scores or model settings. The zero-inference182559 preparation phase is retained; continue its14 inherited normal pairs and fees after this small scheduling correction.

### 18 已完成题镜像的有界回收

240 GiB专用虚拟盘需要容纳后续官方大镜像，镜像常驻会压低按官方资源计算的并发容量。按用户环境自主修复授权，只回收双方正常解题并完成首次官方评分、绑定核验通过的题对所用可重建任务镜像；保留全部补丁、Session、评分、哈希、来源、软件缓存和费用。镜像以后需要诊断时按原来源／Dockerfile及冻结摘要恢复，绝不从解过题的实例制作模板。

先从实时对照的原件路径和group lock生成明确镜像ID清单，记录标签／digest／大小；排除任何活动或尚存容器引用的ID，以及未完成任务组的ID。只对清单内本实验标签或明确官方任务来源标签逐项删除，不执行全局image/system prune，不删卷或容器，不触碰活动构建。删除前再次核对容器引用；保存操作回执和磁盘前后状态。此操作不改变已冻结证据或任务资源，也不放宽调度配额。

本地Dockerfile生成、无法按公开registry digest重新拉取的镜像，在后续回收前先保存仓库外的完整镜像归档、归档SHA及原ID／标签，并核对归档含原manifest。已完成题与未完成题共用同一镜像ID时仍保留该镜像。回收不删除软件对象或构建缓存；恢复时必须核对原ID，不接受近似重建替换冻结环境。

某槽位已按冻结候补完成正常题对时，该槽位原题无模型准入失败所留下的镜像也可回收，前提是记录原失败、实际候补绑定和公开不可变RepoDigest，并确认不被任何未完成题或容器引用。原题不重新进入抽题，也不把候补成绩当作原题成绩。

### 19 有限的无模型软件预热

冷SDK安装串行时间可能长于解题，使目标10个真实解题实例难以重叠。按已批准“其余准备可继续”和环境自主处理的范围，允许仓库外有限辅助进程对下一批已拉取的SWE官方镜像预热既有软件对象，首批只S16–S20、逐题串行、最多一个准备容器；缺镜像或正式组已开始则跳过。只调用现有prepare_only与完整SDK／embedding／网络探针，无认证、模型或官方评分，不代替该题正式oracle/nop及双侧准入。

为控制背景负载，辅助准备Compose单独限0.25 CPU／1 GiB，0模型软件预热不计解题并发；记录与付费试验重叠、资源及耗时。正式解题／评分的原资源、单题预算和不可变软件核验保持不变，不能拿辅助准备时间当官方解题耗时。缓存仍按原镜像ID／版本／配方分键、原子发布并受既有对象锁保护；不跨镜像挪用安装树，不修改当前冻结适配器。失败只留诊断并让正式准入自行验证；这不是正常0分重跑，也不增加后台定时任务。

### 20 已退出的历史无模型控制容器

发现141814阶段S08 nop与171721阶段T07 oracle留下两个exited容器，均已停止、所属阶段已结束，没有Pi模型Session。它们仍占用镜像引用，阻止有界回收。按环境自主处理授权，逐个核对Compose工作目录／绑定日志路径、原Trial的oracle或nop身份、阶段结束及无Session证据；保存脱敏元数据和仓库外rootfs归档及SHA，绑定日志／原评分留在原位置，再以不带force的docker rm删除这两个明确ID。运行中容器、模型试验、其他容器和卷均不动；重新检查状态发生变化即跳过。此为一次性清理，不增加常驻清理器或定时任务；§18的镜像回收程序仍不自行删除容器。

### 21 在真实解题与评分均结束的间隙刷新调度

S16–S20的软件已准备好，但183257阶段的冻结队列以启动时的冷缓存状态排序；现FIFO又会让装不下的重题挡住可容纳的轻题。按环境自主处理授权，只有在当前所有真实解题及官方评分都完成、尚无新模型Job的安全间隙，才结束该控制阶段、保存原件并立即用既有completed_parent受限续跑刷新缓存就绪顺序。所有正常0分／1分、候补、费用均继承；新模型入口、提示、工具、预算和候选不变。不为调度取消在途模型或未完成评分，也不提前结束整个49题目标。

停阶段前检查两次run.json：T05／T07已finished，所有solve/regrade Job均属于finished组，且无其他solving/regrading组；核验唯一控制PID和命令。必要时仅短暂停住控制进程以消除新派发竞争，复核失败立即恢复；确认安全后发送SIGINT并恢复，由既有收尾保存无模型准备的中断和已完成结果。只读等待每次有界、保持当前会话观察，不创建定时器／自动任务。若始终没有安全间隙，则当前阶段继续运行。

若此时仍有多组待跑，在阶段关闭后先增验队列边界，再将内部资源等待从严格FIFO改为“按等待顺序选当前资源能容纳的第一个题对”；CPU／内存／磁盘三项仍全部检查，整题对包络和10实例上限不变。此为有限49任务的内部顺序调整，不新增配置／持久化字段，也不修改Pi适配器；不在活跃冻结阶段改源码。完成对应测试和实验回归、提交后续跑；已完成控制仅在现有严格身份检查通过时复用。若仅剩零星受阻题，则直接按当前实现恢复，不做非必要完善。

S21缓存的首次离线导入验证暴露Docker containerd的身份口径：Id是OCI manifest／index摘要，不是旧存储后端的config摘要。首次只导入amd64子manifest，完整rootfs与配置均一致，但本辅助程序的config==Id断言失败，未作为准入完成。为保留官方完整身份，后续离线导入同时保存原registry index及其全部子manifest／attestation，按原index摘要核对Docker Id；额外小blob也独立SHA校验。只替换尚未进入正式组的S21该次准备标签，不动任何活跃冻结别名；记录首次不合格检查和最终完整身份。此为缓存导入校验修正，不放宽原镜像或官方控制标准。

§19同样的有限无模型准备扩到S21–S22：只在原index完整导入身份验收通过后逐题预热，仍最多一个0.25 CPU／1GiB准备容器、无认证、无模型，并跳过已开始正式组。其余S23–S35暂只做主机blob预取，不将下载或SDK预热冒充正式准入。

### 22 单侧模型前故障与首次有效结果保留

目的与范围：S16插件在Node网络探针总超时前没有启动Pi，而原生已在真实解题。现实现等整组结束后把“该侧无模型”当公共故障，会取消其他无关在途题；整对续跑又会浪费已完成侧并可能覆盖其首次0分。按用户已明确授予的实验环境／适配自主修复权限，在阶段关闭后修正这两个实验接线边界，保留所有第一次有效结果，生产插件不改。新配置仍用completed_parent，不另建重试服务或恢复Pi Session。

技术与验收：
- Pro固定端点、相同无凭据Node程序及每次连接／总超时保持不变。仅model端点无响应且外网严格阻断的传输失败，最多执行三次同样的完整探针；每次原结果留在network-probe.json。外网可达、意外HTTP、程序／schema／凭据问题不以重试绕过。仍须最终严格通过才启动Pi，官方单题时限不延长，新增探针耗时单列。
- 精确证明某侧在Pi前失败（已批准适配器及探针SHA、确切异常、失败探针、无Session／pi.txt／usage、空捕获补丁及空agent_result）才认定该侧0模型费用；缺证仍全局拒绝，不能把一般provider错误或未知费用当零。已跑侧正常结束先补齐其首次官方评分；独立任务继续，该组记未完成。
- closed full阶段续跑按(task,variant)保留第一次完整有效解题＋首次官方评分，包括正常0；正常Pro解题已结束且有原补丁但尚无评分时，只为该原补丁补首次无模型官方评分。仅缺失、精确模型前失败或基础设施取消的侧进入新实例首次有效解题，所有原中断和费用留历史。绝不以另一侧分数、诊断重评或更好的补丁择优。
- 部分题对固定原actual task／候补、原镜像／平台／候选／模型和工具；新阶段仍先验证双方完整SDK与官方控制。原件在原目录保持不变，group lock显式引用继承的原result／patch／Session路径及哈希；报告只沿已校验父证据链解析，拒绝任意外部路径、重复key、缺哈希和源补丁不一致。完整首次评分不重评；缺失侧和缺失评分的阶段计划精确列出，不把继承的模型次数算本阶段新解题。
- 先写边界测试覆盖单侧无模型、正常0不重跑、已完成Pro仅评分、取消侧独立恢复、候补固定、费用去重及篡改拒绝；检查初次与继承报告均全49槽位、最终无重复98行。实际不合格探针与中断均保留。只有这些检查通过、代码提交后才开启下阶段；本次活跃冻结源码不热改。

续跑的新解题实例只使用原任务初始材料与相同冻结软件，不读取任何旧解题Session、State、已产补丁、评分反馈或旁观事后诊断。上述继承路径仅供控制器／离线报告与必要的PatchReplay评分器读取；不得注入新Agent上下文或放宽容器挂载。

§22内部证据字段（不新增CLI参数）：`network-probe.json.attempts`保存每次相同探针的完整无凭据判定与`elapsed_seconds`，顶层仍保存最终判定；`bootstrap_lineage.retained_primary_attempts`保存只缺首次评分的Pro原件行及result／patch／group lock摘要和原镜像；阶段`plan.operation`区分`solve`与`score_only`，已正常评分侧只走既有included_keys继承。group lock的`inherited_primary`列出本组继承原件，新推理计划不含它们；组状态`incomplete`表示某侧严格证明Pi前失败，其余组可继续。缺字段的旧阶段保持既有解释，不重新解释历史评分；阶段计划总行数与新增真实解题次数分别报告。

每个已注册solve Job还必须用其冻结agents清单与实际result中的(task,variant)逐一对齐，不能因为允许部分题对而忽略一个已派发却缺原件的侧；缺原件／未知费用仍拒绝继续。单侧续跑Job只声明该次真正需要的Agent，评分-only不声明模型Job。

### 23 容器观察显式关闭可写层Size计量

204027阶段21:19 UTC因docker ps全JSON查询返回snapshotter.Usage/lstat ENOENT而保护性关闭；Docker随后的普通查询正常，VM有约40GiB available、磁盘约100GiB空闲，没有本次VM OOM证据。上游已记录同一问题：全字段JSON隐式请求可写层Size，临时文件删除与计量走访相遇可导致整次列表失败（[Moby #53920](https://github.com/moby/moby/issues/53920)，其说明也给出显式size=false的调用方规避方式）。

按环境自主修复授权，仅在现有观察命令加--size=false；保留JSON结构、ID／标签／状态等元数据和15秒频率，Size不再作为实时测量。资源准入仍用原CPU／内存／VM文件系统余量，Session用量观察及其他Docker／解析错误仍失败停止，不用错误冒充空列表。先增测试再修改；以无模型文件增删容器验证旧调用与修复调用，记录失败率。所有正常首分、S22官方0及费用继承，S14插件／S23两侧正常原补丁只补缺失首次评分，S14原生基础设施取消则保留历史后补齐；不重启VM、不改模型／候选／官方任务或评分协议。

§19有限无模型软件预热继续按小批扩至S23–S25：原index身份验收通过且正式组尚未开始时才执行，每次仍一个0.25 CPU／1GiB容器，未带认证，不调用模型，不替代正式控制／双侧准入。后续S26–S35仍先仅主机blob预取；是否导入按实际磁盘余量和在途任务判断。本批预热与付费阶段重叠须记录，不纳入真实解题并发。

### 24 部分题对复用原始Dockerfile构建身份

46b54b48d8阶段无新模型调用即被身份检查阻断：T07各层均命中缓存、运行manifest与config摘要和旧日志相同，但BuildKit每次导出新的attestation，使index／Docker Id变化。不得放宽已确认的两侧原镜像一致要求。按环境自主修复授权，部分题对从已哈希核验的原group lock读取preparations；先核对完整任务源、平台、每个角色的官方Dockerfile／context摘要、来源和不可变image Id，再复用原图，只重设本实验冻结别名，不重新build。所有角色均先校验通过才设标签；缺原图／上下文变化仍阻断，不以近似重建替换。正式oracle／nop、双侧软件检查和独立实例仍保留。

T07旧index虽已不在Docker image列表，原blob仍在专用VM的containerd内容目录。仅只读导出原index与其递归描述符，逐blob核对SHA／大小，制作仓库外OCI归档；用Docker load恢复，断言Id与旧group lock完全一致。不得直接修改containerd数据库或内容，不从解过题容器导出模板，不修改／补造attestation。若任何原blob缺失则保留阻断并报告，不能悄悄换新图。归档SHA、源group lock及旧build日志摘要、原件路径和恢复回执全部保存。该归档可供以后精确恢复，不算新的能力样本。

实现只增prepare_task内部可选冻结准备记录及题对续跑接线，无新用户CLI参数，不改Pi、模型、工具、Task／State／Window持久化。先测完整角色／上下文／平台／Id变化拒绝和禁止build，再做真实T07两角色恢复验证。允许实验适配器等价表精确列出此次旧／新images.py摘要，其他未审查改变仍拒绝续跑。无模型关闭阶段的费用与全部53条首次评分／3条待首评继续继承。

§24恢复实测补充：旧index及可执行manifest仍在，旧in-toto证明layer有一份不可读，首次全描述符导出明确失败并保留。允许再验证Docker官方`load --platform linux/amd64`的定向导入：原index字节和SHA不变，只导出其amd64可执行子图，逐个校验config及全部文件层；非运行unknown/unknown attestation子图缺失明确记录，不补造。仍要求Docker最终Id等于原index、原平台和完整执行子图一致；若Id变化或任何执行blob缺失则拒绝，不能改为只比较近似文件系统。归档／回执必须称平台子图归档，不声称全部attestation已恢复。此为精确原身份恢复的有限验证，不改变任务或能力结果。

§19下一批有限预热只扩至S26–S28，沿用同样的完整原index导入验收、未进入正式组检查、单准备容器0.25 CPU／1GiB、无认证／无模型及对象锁；尚未导入的题先完成有空间保护的原图导入才进入预热。不得为赶并发改任务预算或把准备计入解题峰值；后续S29–S35仍先主机预取。本批只提前软件准备，正式准入仍逐项执行。

### 25 两条历史FreeCAD闲置构建缓存的精确回收

当前VM余量不足五个SWE题对的官方磁盘包络；普通已完成镜像清理已用尽，未触及构建缓存。只读buildx du发现2026-10-26的两条FreeCAD/micromamba安装缓存：yj00d3ony0hv8exc8tcnr25l1约4.602GB、y1ifm0o4yjzkcco0dg1735gyn约3.203GB，均immutable、reclaimable、unshared，最后使用两天前；本49题无FreeCAD任务。按环境自主修复授权，将这两条精确ID回收列为§18“不删构建缓存”的唯一例外，不做全局prune，不删任何其他缓存、镜像、卷或容器。

先保存完整du及history元数据，确认没有活跃构建；分别用同一组id／inuse=false／shared=false／mutable=false过滤器只读查询，必须恰为预定一条且描述与原值一致，随后才以同样过滤器执行buildx prune。回收前后余量、退出状态与du差异入仓库外回执。若过滤结果或状态变化则跳过，不扩大范围。此操作仅使这两条历史安装步骤将来需重算，不承诺其历史缓存按字节恢复；当前49题官方图、SDK对象、源及全部试验原件不变，不改变解题／评分资源。过滤语义依据[Docker官方prune文档](https://docs.docker.com/reference/cli/docker/buildx/prune/)：多条件按AND，不使用容量阈值清理。

§25执行结果：本机Buildx对精确id单条件返回预期记录，加inuse=false后返回空列表，与du的Reclaimable=true表现不一致。保护检查已在任何prune前拒绝，未删除任何构建缓存。按“非阻断完善后置”保持当前模型继续；不移除过滤器扩大回收范围，本次例外未实际执行。原元数据与有限失败保存在old-freecad-cache-reclaim-20261029，不宣称已释放这部分空间。

§19继续小批扩到S29–S31：仍先逐题核对完整原index／文件层／配置、受VM余量保护，导入完成后且正式组尚未开始才做同样的单容器0.25 CPU／1GiB无认证软件预热；不改变正式准入。S23双方首评完成后，按§18回收其无容器引用、已在主机保留完整原OCI blob的官方图，回执批次7；给后续准备腾出余量。S32–S35保持主机预取，未完成组和活动图不回收。

§25过滤兼容性已用只读调用核清：本机把false布尔字段视为缺失，等号false不匹配；使用官方支持的`!=true`（inuse/shared/mutable）与同一精确ID组合后，恰返回原定记录，原metadata仍明确Reclaimable=true、Shared=false、Mutable=false。按环境自主授权，只将三条否定条件改为!=true，候选ID不扩大；再次保存历史／du并检查完全一致、无活动构建，才执行这两条精确回收，前后记录集合差必须仅在两个固定ID内。这是先前保护拒绝后的有限兼容修正，不是移除ID或扩大清理范围。S18图回收因还有容器引用已被拒绝，未删除该图或容器。

§25最终回执：同一精确ID及否定条件执行后，两次均Total:0B，du前后集合差为空，未实际删除或释放缓存。不能把只读可回收估计当成实际释放量，不进一步扩大范围。本机du／prune在该记录上的行为差异保留给后续排查，不阻断当前模型。

### 26 当前并发瓶颈记录（未实施候选）

现有最多5个题对工作线程先等待整对资源，T07／T08等重题的等待会占线程；即便更轻的后续SWE能装下，也可能尚未取得线程。§21的资源队列“首个可容纳”没有解决线程池外层排队，故当前真实峰值不能归因于硬件一项。保持在途冻结阶段不热改、不取消模型。若自然关闭后仍需补测，再考虑增加有界待调度线程并给资源池增加独立实例额度（仍最多10真实解题，CPU／内存／磁盘不放宽）；先测试、文档定稿、提交再进入下阶段。若本阶段已完成全部49题则后置，不为这个完善重新运行任何正常样本。本段是观察和候选，不是已实施或已验收能力。

§20同样的归档后清理扩到一个明确的已退出软件预检容器：5ce26d4db6875e660e9aa98648a20a66c1e2fe5535ea85aaf53f28fe2c49dba8，属于已关闭46b54b48d8阶段g18/runtime-preflight-pi-memweave，非本阶段模型实例。先核对prepare_only=true、auth_path为空、无Session／pi.txt及原批准适配器SHA、阶段closed和容器exited，再保存脱敏metadata、完整rootfs归档及SHA，复查仍exited后仅docker rm该ID（不force）。原软件预检日志／阶段原件留原位，不删其仍healthy的旧sidecar；不触及活跃或已解题的模型容器。归档会与本阶段重叠，耗时单列，0模型。完成后才允许重新尝试§18的S18已完成图回收；不以cleanup命令成功推断释放量，实测df。

### 27 官方单题预算结束与基础设施取消分别记录

核验固定上游v2/README.md第78行明确“50-minute budget per task (in-sandbox timeout, so a partial patch is still captured and graded)”，locked_codex.py等包装也预留60秒捕获。用户取消的是整批时间／费用上限，不是官方单题预算。若本轮实际触发已冻结Pi包装的in-sandbox截止，必须保留该首次尝试和其预算内补丁，只补首次官方评分；不能当公共环境取消后再解题择优。解题未自然结束、原exception和工具等待单列，官方patch reward与交付终止情况分别报告。

仅精确证明RuntimeError为冻结包装的`Pi exited with status 124; see native output`、Agent阶段达到原2940秒运行／捕获边界（含原网络检查）、网络检查通过、真实Pi正用量、补丁捕获／原镜像／首次评分交接完整，才按“官方预算结束的首次尝试”解释。普通provider错误、任意exit124、未满预算、框架取消或不完整补丁仍不能套用。没有官方reward则仍留空，不自行把超时填0。本阶段执行代码冻结，不热改；若实际触发后报告／续跑接线误分类，只在已关闭阶段按上述上游原协议修正解释与相应测试，源补丁和首分不改、模型不重跑；不增Pi运行时副作用或CLI参数。未触发时不为这一边界重跑或造样本。
