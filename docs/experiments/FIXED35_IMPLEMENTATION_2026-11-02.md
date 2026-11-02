# 固定35案例实施与本轮运行约定

用户于2026-11-02明确授权实现已确认的35案例、原生/插件对照、故障修复和报告。本轮从11:42:12 UTC起，总上限USD20，硬截止23:42:12 UTC。只扩展现有experiments系统，不改生产Rule、State、Window协议，不覆盖旧结果或账本，不push。

输入已由Library受支持流程下载到本机并校验：35案例JSON为1782a457cf58a9c9facb76b633d1f668c0bf5a36dcd461ced0a19792256e70b8；报告docx为2a7ee62167a322f88aa45b7940c7ed26184b2eaa76294963899ce535508fb908。原设计是研究稿，不当作已实现或已准入证据。清单与gold只在评估器侧，禁止进入actor挂载、提示、Task索引或工作目录。

## 交付及优先顺序

固定35个不同来源案例：TB4 12、SlopCode3、STATE5、Switch2、Interrupt3、MAB8、Marathon2。mp-checkpoint只占一个核心案例，同时属于五个长程候选。先实现来源/适用矩阵、可靠采集/重放/程序断言和新版聚合，再逐家族完成无费用准入、真正Pi CLI假provider/丢guard负例/真实小额canary，最后运行和持续监控。

沿用现有Harbor/Pi执行、软件缓存、请求准入、独立deadline、原始证据索引和report/campaign。新增来源适配使用固定上游原输入、接口、状态或verifier；必须逐题冻结actual selector、内容hash、工具链和资源。禁止以fixture、toy环境或参考解替代35道真实actor试验。能确定性恢复的采集解析错误统一重算两侧；改变actor所见内容/工具/环境或丢失不可恢复原始证据则使受影响配对失效并从冻结起点重跑，全部费用保留。

## 预算与时间

继续使用既有DeepSeek-Flash完整Pi配置，thinking off。2026-11-02重新核对官方峰值价input miss0.30/cache0.006/output1.20 USD/M，不依赖离峰优惠，不启用付费Search/Fetch。正式前冻结输出上限和每案例相同episode政策。

新独立budget_id为fixed35-20261102；预留1美元安全余量，实际准入上限19。两个变体各累计9美元，独立预检最多1美元；模拟用户、judge和其他辅助调用必须归属相应变体/案例并计入同一总账，不用另一变体未消费额度补贴。按最大收费原子预留，未知占用不释放。既有1M输入最坏预留可能使低episode额度提前拒绝，须在免费预检检出，不以实际平均费用代替最坏准入量。额度和时限不足时保留未完成范围，不保证无法保证的全成功。

TB-10原verifier最长7200秒：全局actor新请求截止不晚于20:20:12 UTC，Switch最终步骤实测配置为10000秒，因此采用更早截止；随后给最终交接、至少10000秒验证及报告留余量；辅助judge单列截止，不越过整体硬截止。只停止本run实际登记的容器/PID，查询失败重试和停止确认不可伪报成功。仅随本次runner绑定临时caffeinate，不改变全局电源/网络/安全设置。

## 资源与隔离

现有Docker VM12 CPU、44082655232字节内存。短题按实际资源调度，原生与插件资源一致，能并发则配对并发；LONG-05每臂24GiB不能两臂同时占48GiB，按同资源串行执行并记录时序。WDM每臂8CPU亦不能在12CPU上假称同时得到16CPU；不单方面降低一臂资源。原题接口/时间/资源需要适配时提前冻结并明确标DERIVED，原grader不偷偷放宽。

每个arm独立actor工作区、Pi Session、memory和应用环境；不得借用另一组答案。上游参考解只用于隔离控制容器，不进入actor镜像层或工作区。STATE完整Pi/MemWeave包含上游官方工具范围外的工具时明确记接口派生，原状态分/官方judge输出各保留原名。Interrupt的baseline/replay及60%实际索引在正式前冻结，不能各自按不同轨迹长度选择中断点。

## 采集和程序评分

每个case×metric冻结适用性、机会、检查点、断言ID、必需证据、失败条件、parser/gold版本。每检查点必要断言AND，明确单一确定性点不强拆；再按该指标的预登记机会聚合，绝不把整题所有不同指标AND成一个分。每个断言都有pass/fail/missing测试，缺字段不默认空列表或false。

采集关联run/case/arm/attempt/request/tool/op：原始usage及receipt、实际最终provider请求、Rule/State/Window/引用投影、工具参数结果、State版本变化、检索TopK、恢复动作、真实eviction和环境/verifier产物。请求准备/交付只证明外部事实，不证明模型阅读。评估侧内容证据与运行时记忆隔离；采用内容寻址去重和哈希回放验证，不能只保存最终state.md或摘要hash。

C4须三个真实驱逐及对应快照，中间遗失即失败，不以无意义填充凑驱逐。INT-04原任务是不同权威，另冻结equal-authority-conflict-v1。MAB身份严格包含split/row/context hash/QA-ID，八个context分别重置，不把同历史多问或多个checkpoint多算案例。

## 新计分版本与旧版本边界

新运行使用fixed35-v1聚合，旧normalized-20261102-v1及旧报告不改：每指标先在benchmark内对有效case均分，再跨有值benchmark等权宏平均。设计NA去分母，正常机会明确遗漏/错误为0；缺证据先作为采集故障定位修复，不能换名NA。确实无法修复的采集例外另表并剔除分母，且不得声称包采集验收通过。

插件宽表的“-”只对应冻结设计不适用，例外/未完成单列，不能装成“-”。共同对照仅取同题同指标共同有效mask，使用相同预冻结权重，保留覆盖和剔除原因。官方outcome、派生行为、工程/费用诊断分通道；86类原始诊断行无客观目标不制造能力分，旧题7个专属别名在无关新题不挪用，使用显式继任ID。

五个长程候选的本机资格目前0。只能按同一成功episode中>=1000个有真实响应、唯一ID的主任务模型调用计量；不累计重跑/HTTP失败重试/工具steps/模拟用户/judge/空usage。更高效成功不足1000不扣能力分。未满足五题资格如实保留未通过。

## 验证与真实阻塞

免费回归、日志截断/重排/重复、拒绝调用、断点、零机会、AND负例、同scope/版本/否定错误、guard丢失零上游、真实CLI采集、预算双进程锁、独立停止及全部source/actor隔离是付费准入门槛。当前会话无MemWeave State/Task专用工具，因此不能更新当前State；未通过Bash改写。其他采集与实验工程继续推进，不将该限制混作题目成绩。

### 环境与执行适配（真实模型运行前记录）

所有原生/插件使用Pi1.4.0默认系统提示与原生工具；插件使用未修改的生产归档5ed61de2…，额外评估hook不改生产协议。新增fixed35协议禁用旧Marathon第80返回进度插话。暂定普通case总actor1800秒、五个长程候选2700秒，多阶段按整case累计；这是总预算下的显式时间适配，不是原题8–10小时复现，不承诺五个千次资格。

MAB八个独立上下文使用原数据4096-token自然句子分块（2/9/67/33/17/33/33/33块），通过Harbor持久Session逐块输入，仅末尾查询所选QA。原始substring score独立保留，strict answer和answer.json写文件为DERIVED动作指标。答案只在evaluator-only目录。八题共用同一已验证、按ID冻结的Python容器；原MAB无Pi官方容器，故此为明确接口/环境适配。

STATE仍调用固定源码domain环境、用户模拟器、state-requirements判定与官方judge提示。完整Pi接口超出上游domain-only工具集合，标DERIVED；只公开domain schema与本case工具通道，task_summary/requirements和后续模拟器信息不进actor。临时HTTP回调因本机容器到Mac连接关闭未通过免费预检，改用已经验证的双向共享目录IPC，不修改网络/安全设置。通道只含真实工具请求及其返回，完整业务前后快照、模拟用户/官方judge输入输出只在actor挂载外的evaluator-only目录。模拟用户和judge使用相同原子总账、独立角色，不走默认Azure配置。官方LLM judge分与程序行为分分列。

Switch原始Dockerfile在排除/usr/sbin后调用useradd，实测构建127。独立副本仅改为现有/usr/sbin/useradd；原始checkout、指令、16步骤、grader和测试不变。TB-02/TB-09只准入按内容hash审查的本地服务Compose：无host ports、host mounts、特权或主机网络，不改系统设置。

本机Colima对/tmp挂载曾导致控制reward无法回传；失败控制保留v1，后续运行使用已做双向读写探针的原有共享实验目录。公共环境不沿用Pro的强制offline验收，按各题声明验证网络策略，不改实际策略。

Slop使用额外冻结的官方runner af5a9cbc311605b5cceb80200ca9832bdff2d7b1及其uv.lock；只用eval-snapshot/tools入口运行题目测试，不直接pytest。其CLI依赖曾尝试初始化用户mini-swe-agent目录，被沙箱拒绝后经工具审批允许默认空目录初始化；没有创建凭据或修改网络/安全设置。

截至13:20 UTC仍无付费调用。已观察365项回归、TypeScript类型检查与Rule资源校验通过；MAB真实CLI假provider双臂并发及CAS重放通过。Mirror只作为原始证据恢复源；fixture通过不记为actor行为通过。

### 14:20 UTC实施检查点（尚未正式运行）

新增现有CLI的`fixed35 run`，仍调用Harbor的完整Pi而不另建Agent Loop。逐案例准入冻结task/运行时/gold/映射hash、评估器代码快照、两臂同资源/累计时间/额度；具备主机侧起跑屏障和随runner释放的临时caffeinate。多阶段采集按producer/sequence和request ID去重，累积Session副本须字节前缀一致，只选择最长原件用于统计，不能把Harbor归档复制当新调用。State在工具提交后及实际请求准备边界保存评估侧内容寻址证据；真实CLI两阶段免费测试已证明Session延续及这条采集链路。

自动单案例report同时导出原始口径、百分制、s/f/u/n、公式、原因和权重；旧fixture ID改用明确F35 ID，fixture不参与actor得分。研究映射仍需逐案例冻结为执行契约。空或遗漏完整期望集合不能通过采集验收；不存在证据不得用默认false/空列表充当已知情况。当前缺失仍阻止验收，修复及例外政策按上文处理。

MAB纠错适配使用预注册的有限实体/值字面关系与旧值失效、写入先后、首次动作共同检查，明确不是通用自由文本语义判断。MAB-03已核对真实链：Christian Abbiati→cornerback→field hockey→Philippines；不能误用较旧American football。MAB-01旧/新CEO都在原第一输入块；默认N=200不能保证三次驱逐。已提出仅隔离评测实例N=8/B=2与自然句子分块的派生压力配置请求，等待明确选择，尚未修改生产默认值或启动依赖该选择的正式MAB配对。

控制结果保留全部版本：Slop v1缺uv、v2 Docker SDK/CLI架构不一致产生125且collected=0，不能视为空解成功；v3统一采用官方SDK实际原生架构后，已观察前阶段reference全通过、nop真实零分，剩余仍运行。WebArena公开镜像下载中断/HTML门禁分别留原始错误；不绕过访问控制，标准HTTP Range恢复仅在服务明确支持时继续。

费用截至本检查点只有MAB环境两次真实canary USD0.000197208（峰值估算，非账单）；无正式benchmark actor。State专用工具仍不可用，未用Bash改State。

### 14:38 UTC：统一额度写入权威（付费门禁修复）

STATE canary两actor响应有完整HTTP200/usage/DONE，但原容器结算拒绝；原日志未保存底层异常，不能补猜异常类型。原6条真实请求均已对账，两个保守预留仅在独立CAS验证完整usage后精确结算，原失败轨迹不改，累计估算USD0.00227448。

进一步免费实测证明Mac与Docker VM直接共写同一文件时，两个内核的flock未提供全局互斥：最大0.61的模拟账本，host获准3条、VM获准1条，最后仅存2条。即使一次小型CLI并发试验通过，也不能据此宣称全局硬闸正确。修复采用同一Docker VM中的额度服务作为唯一新增实验账本写入者，复用既有budget_guard.change和原账本、公式、预留/幂等语义；Mac辅助请求与所有actor均通过分scope的文件IPC进行准入/结算，actor不再挂载可写全局账本。不给actor Docker socket，不把模型凭据交给额度服务，不改变系统网络/安全设置。只为本次私有实验通道创建必要访问权限，服务与channel随本轮生命周期管理。

新增IPC请求/响应须完整关联nonce、固定arm/episode/额度/截止和服务身份，缺服务、错误token、错误scope、重复/越界操作均在真实上游请求前拒绝。单VM权威保留操作审计、账本前后hash及心跳。先以独立模拟账本完成host/VM并发超额拒绝、无丢ID、非root真实Pi CLI和服务丢失零上游；再执行极短真实canary，不重复进行长正式运行。当前正式案例数仍0。

### 15:49 UTC：额度权威与首个实际行为契约验收

单VM额度服务免费压力测试完成5轮、每轮80次host/VM并发准入，获准ID与账本逐一对应；非root UID10001真实Pi CLI正例及丢守卫/丢服务负例均完成，负例零上游POST。最终离线回归393项通过；TypeScript类型及Rule资源校验通过。服务隔离正式work+simulator每臂USD7.99、official judge每臂USD1，preflight共享USD1，继续受native/plugin各9、总19与用户20硬上限约束；历史canary不重置。judge额度不能被actor提前占用。

TB-04派生适配仅增加共同格式要求：若保存持久笔记，只读约束按`READ_ONLY <absolute path>`写明。原任务代码、只读文件、测试和原始reward不变。七个必需程序断言分别为三条活动State约束、三个文件hash保全，以及记录先于首个持久代码修改；缺证据不是false。对应正/负/缺失CAS夹具独立验证，夹具不算真实actor成绩。原verifier会恢复只读文件，因此另保留verifier前文件hash，避免原题reward掩盖只读约束破坏。原生只评价同样文件保全，不强制其使用State。

软件预检TB-04双臂已通过；其他失败版本保留。公开环境外网探针超时仅属诊断，模型端点仍须可达；声明offline的环境仍须通过严格断网检查，不改变实际网络策略。两Marathon镜像身份差异仍禁止加载凭据，未擅自放宽。

### 16:03 UTC：免费真实入口闭环与付费审批阻塞

TB-04真实Pi+假provider双臂并发完成，native2、plugin4次模拟请求全部CAS重放并结算；插件真实专用工具先create、再append三条READ_ONLY记录、再native write修改可变文件，七项AND实际采集评分100。native只读文件保全100，State专属设计NA。这是程序采集/判别验收，不是付费actor能力成绩。原始记录在实验根`tb04-launch-preflight-v2/free-result.json`。

发现Harbor egress sidecar与main共享网络hostname，旧hostname→docker inspect误认代理镜像。改用Harbor实际session的Compose project+service=main唯一ID，再核对inspect标签及原冻结image ID；不放宽镜像校验。`standard-runtime-v5`两Marathon题双臂软件预检均通过。Slop circuit_eval checkpoint8的旧reference有prior checkpoint5 collect-only退出2；原失败保留，v4原官方入口无改动重测reference566/566、nop0/566且两者infrastructure_failure=false。不能把v3失败改写成成功。

现有CLI新增`fixed35 pack-report MANIFEST --output NEW_DIR`，必须完整35个独立case与每case170个指标契约；全期望11900个arm单元格校验，缺整题也不能通过。导出plugin/native宽表、同有效共同指标对比、原始值/逐行公式/权重/s-f-u-n、按benchmark宏平均与加权点分/覆盖/区间。此入口存在与测试通过不表示35题已真实运行或所有case-specific gold已完成。

付费入口自动审批明确拒绝：目标为DeepSeek真实API，拟发送本批公开benchmark任务/代码/工具输出及本实验生成的State，费用归入已授权本轮USD20。自动审批认为还缺明确的payload、destination和spend授权。该调用未执行，未创建新的真实请求或正式run，不换入口重试，不以辅助judge绕过。需用户补充这三项明确授权后才可再次提交具体付费操作；当前仍只有原6条真实canary、USD0.00227448、零reserved。本段是阻塞记录，不是实验完成报告。

### 16:14 UTC：TB-04边界审计修复（正式仍未开始）

新评分器版本`fixed35-score-20261102-v2`、C3检查点v2。只有初始快照不再给保全分；必须核对Pi原始stdout中的所有工具调用/完成ID与CAS工具边界、agent_start/agent_end、每个完成工具的工作区快照。未找到修改分为完整结束且无观测修改机会、执行/边界不完整、观测修改但动作边界丢失，不能统记0。完整无修改机会使用明确的CONDITIONAL_NO_OPPORTUNITY，既不是设计NA也不是能力通过；原题结果独立保留。任何观测边界发现保护文件改动即为失败，末尾恢复不抹掉中途失败。指标只声称公开观测边界上的保全，不证明单个工具内部从未瞬态修改。

增加初始快照而已、完整无修改、丢修改call、缺末尾、缺工具后快照、先修改后恢复六类CAS与独立Pi日志测试。已有真实CLI免费原件在v2只读重算：native common100，plugin C3/common100；分别1/3个工具边界、末尾证据齐全，不覆写v1原件。通用collection现将transport结算完整与execution边界完整分列，两者均完整才通过；不能仅凭HTTP结算声称业务证据完整。

Switch原评分器符号链接复制基础设施的独立修正版v4控制完成reference reward1、nop reward0，均无exception，旧失败版本不改。Slop与Switch环境控制通过仅说明可评估，不替代尚待完成的行为gold和正式双臂实验。

保守调度容量为11CPU/38GiB。普通TB-04每臂900秒仅用于本题派生短预算与显式READ_ONLY格式约束，不宣称原8小时无提示自然记忆复现；五长程仍为独立2700秒计划。WDM与Ruby按原资源必须逐臂顺序，其他题仅在资源允许时双臂同时运行。所有五长程若耗满保守排程约315分钟，已不足以保证在20:20 actor截止前全部完成，不能靠统一15分钟、凑调用或fixture得分补齐。本轮所有未执行/未适配项须原样列出。

成功长程API调用资格额外要求：唯一主actor请求、HTTP2xx、DONE、正input/output usage、有assistant内容或工具调用、正常stop/tool_calls结束且无provider error；无工具schema的压缩/辅助调用、零usage占位与失败请求不计。HTTP尝试总数和usage assistant返回R仍按各自原口径另列，不用资格数替代。达到千次仍须该episode原题成功，不能累积重跑凑数。

截至16:21 UTC最终免费回归410项通过，受影响Ruff、TypeScript typecheck、Rule资源逐字校验、git diff --check通过。新增pack-report完整35题集成测试验证11900单元格和双臂同分母，重复/缺整行/不完整证据不能通过；不可采集例外必须有原因及修复记录，共同分母两臂同步剔除并单列，绝不写为`-`。正式模型执行仍被审批阻塞，没有新增付费请求或实验成绩。

### 等待明确数据外发授权期间的独立工程

继续免费工作，不重试被拒绝的DeepSeek请求。Slop actor采用官方固定renderer的8/5/5个公开阶段，完整Pi与同一持久Session/工作区，每阶段按官方snapshot忽略规则交接源码；隐藏测试/solutions不进入actor。独立官方eval-snapshot后评分保留所有阶段与回归，整题主分为全阶段AND，partial为阶段通过率等权均值；缺报告/infra_failure不当0。为官方SDK没有资源字段的问题，仅在单次eval进程对本次Docker SDK/CLI创建注入两臂相同2CPU/8192MiB与本次run标签，不修改上游源码/断言；实际HostConfig写入审计，独立watchdog只清理该标签。资源适配须重新控制验收。

公平调度使用现有case runner，工作池11CPU/38000MiB，资源只按冻结任务及verifier上限预留。普通可承载配对同时跑，WDM/Ruby不可双开则顺序；顺序臂起跑顺序按case ID哈希事先固定，报表仍固定native/plugin顺序。最迟起跑时间同时考虑整case actor预算、顺序第一臂verifier时间、两臂setup和容器硬截止；不在临近截止时只给第二臂缩水预算。队列默认仅dry-run，显式执行还必须有ADMITTED状态及与冻结评估器、软件plan一致的已结算真实canary证据。缺服务/缺授权/缺真实证据均不得加载真实运行入口。

STATE后置评分改为现有配对runner的host阶段：StatePi.run只完成真实actor/模拟用户轨迹并保存原件，退出Harbor actor超时范围后再调用原官方score_one与Task/UX judge。仍使用同一VM权威、同一arm、独立judge episode/截止和已预留子预算，不能因actor用完时间而取消本应保留的评分时间。原轨迹不改，评分写独立host-only文件；原官方LLM judge与程序化行为分继续分列。domain事件增加当前conversation turn/stage关联，仅评估侧字段，不进模型上下文，不改变产品State/工具协议。

### 18:37 UTC：离线恢复与业务评分补齐

重连后先核实不确定写入：`fixed35_state_behavior.py`未落盘，未重复追加。前一完整离线回归418项通过。本轮加入五个分别定义的STATE程序判据：原state_requirements逐字段AND、非目标实体逐domain边界保全、INT-01先澄清后目标回复再return/refund、INT-02仅取消已明确耳机且保护未明确配件、INT-03转return后不再exchange、INT-04先读权威booking再取消、INT-05先报57/150两项费用再观察撤回意图且所有观测状态不变。INT-05没有原state_requirements，不能由空AND或无操作得到100；先改后恢复仍失败。语句判据明确限定为版本固定英文解析规则，不声称通用意图理解，也不替代原官方LLM judge。

新增`fixed35 state-contract INT-0N --source PINNED_SOURCE --output NEW_JSON`离线冻结组件，交由逐题完整契约的`state_business`引用；`adapter_kind=state-business-v1`接入现有report，官方LLM分和程序分分列。domain双日志、起末快照、call_id、case/arm/run身份、提交前后链和末尾hash完整性均核对；缺失/损坏不变成0或成功。已验证正例、负例、缺证据及report贯通；这些全部是程序实现验收，不是模型成绩。

多阶段report现在从全部真实actor request_id计算State请求准备版本一致性及provider交付保真，不再只取最大的一份阶段日志。复制事件去重，冲突副本拒绝；缺request_ready保留unknown机会并阻止采集验收。该交付保真不等于独立Window选择策略正确，更不证明模型使用记忆。引用/Window独立gold、Switch Task实际查回/路由、Interrupt环境和其余业务gold仍需完成，不把框架存在写作35题全部适配。

恢复完整回归时发现一项测试自身竞态：故障测试直接写JSON，后台线程可能先读到空文件，得到JSONDecodeError而非预期identity ValueError。测试改为与真实IPC相同的partial→rename发布，不改运行时错误处理。最终本阶段全量427项通过、受影响Ruff/TypeScript/Rule资源校验通过。Slop受资源限制的控制因断线中断，v3六项通过；退出容器已归档清理，v4复用六项已核验控制继续其余30项，不改旧结果。

真实模型外发确认仍待用户回复，禁止重试被拒绝请求。费用仍6 settled、USD0.00227448、reserved0；正式配对0。固定原截止不延期，后续排程仍须满足两臂完整同预算及验证余量，不能以短demo代替35题或长程资格。

### 20:04 UTC：Task/引用与原始验证器离线验收

当前评分入口版本为`fixed35-score-20261102-v3`。本节是实现进度，不是35题实验完成报告。真实DeepSeek仍未重试，正式配对仍为0；累计只有本轮先前6次已结算canary，峰值价格估算USD0.00227448、未结算预留0，所有本节模型响应均来自假provider，模拟账本金额不计真实费用。

Task评估侧在agent起末及每个工具前后记录持久Goal/journal与index的hash/CAS、绑定及版本。部分创建、重定向路径、缺快照都不能默认作空清单；创建后删除仍算发生过创建。检索以查询当时语料与原始顺序/原始分数判定，后创建目标不得进入召回gold。T2要求正确绑定、真实HTTP请求中的State版本及独立业务动作检查，不能用预期注入元数据代替实际交付。T4保护预先指定的Goal/F/D投影，允许无关笔记变化，并可AND随后返回工作的独立动作检查。

真实Pi CLI免费五阶段夹具完成：先结束A，再结束独立B，查回恢复A，回答一次短问题，再返回A。原生9、插件12次模拟provider返回，各自一个Session；Task T1/T2/T3/T4和返回动作检查均通过。加入实际`memory_read(U1)`后另一个版本为原生9、插件13次模拟返回，引用源于工具调用前公开Session绑定与原始记录，校验Task范围、不可变entry/session、Unicode范围、内容和截断标志。读取真实原件的完整范围1/1通过。以上不是模型行为能力成绩，不属于35题数量。正例前还保留两个负夹具：未完成交互中即切换再恢复A返回`RESUME_SOURCE_MISSING`，不修改插件恢复契约来迁就夹具。

免费原件暴露两处离线解析缺陷：State实际content是文本part数组；公开`tool_result`的content在顶层而`tool_execution_end`在result内。两处均通过实际SDK形状回归修复，仅重算同一CAS，首版错误分析仍保留。Task CLI可通过`--action-evidence`关联多项独立程序断言；fixture标记必须保留，实际case report拒绝fixture Task契约。引用实现目前仅覆盖已知完整U/A纯文本请求范围；state_read历史项、图片、多模态、缺原件的其他Session及token池裁剪仍需相应独立oracle，不能据此宣称引用全类型或Window选择策略已经全部验收。

MAB八题已生成evaluator-only v2组件，公共问题/原上下文字节不改。四道纠错题允许正确推导结论或完整多跳链：Bagratuni→Christianity→Taipei、Christian Abbiati→cornerback→field hockey→Philippines均不能误判为过时链。仍是有限规范化字面解析，不是通用自由文本语义证明。首个文件变化按实际工具后CAS取证，支持Bash写文件；前置State须来自同一动作前边界，最终改对不能抹掉首次错误。没有采到必要文件内容则缺证据，不能推断失败或成功。

Slop资源控制v5完成18阶段×reference/nop共36项，实际HostConfig均为2CPU/8192MiB，已确认停止。发现上游database_migration的checkpoint_1测试`test_foreign_keys_disabled_during_drop_column`明确只限1–2阶段，而runner在3–5仍将它的skip计入total。固定源测试hash为`59568d555215b985f90da89e3a9d072565c6fd1fc73c826a214b8207cc148f9c`。本包按已确认的“全部适用测试”另列派生严格分，仅排除这一个已证条件不适用项；原86/87、原始严格0和全部原JSON不改，未知skip不自动排除。派生严格分不冒充上游默认可配置pass_policy或官方榜单分。

无调用的工具只有在完整独立Pi执行日志确认后，才记录attempts=0；成功/错误率分母0为无机会，不给100。execute()未开始时没有执行耗时分母；日志不完整仍是unknown，不能补0。新的完整离线回归454项通过，`npm run check`资源/类型/单元/集成共276项通过，受影响Ruff与diff检查通过；live真实API、官方付费judge及发布验收未运行。

|家族|数量|已完成的无付费部分|尚未完成／未准入|
|---|---:|---|---|
|TB4|12|全部原题reference/nop与双臂完整Pi软件预检；TB-04 C3及已知约束指标贯通|其余11题的具体业务gold、故障/恢复/引用/跨窗机会与完整指标适用契约|
|Slop|3|全部18公开阶段持久Session/源码交接、官方入口与36项资源控制、后评分接线|逐阶段State重要结论/纠错/保全gold及正式配对准入|
|STATE|5|原domain程序控制5/5；逐题业务AND、公开工具IPC、host后置官方judge入口|INT-04同权威冲突overlay；State层纠错/及时性gold；新额度权威下真实actor/辅助请求canary|
|Switch|2|原题控制与复制symlink修复；T1–T4真实工具采集/程序提取器的免费验证|两个选题实际检索种子、阶段用户意图overlay与首个关键业务动作oracle/完整actor接线|
|Interrupt|3|固定选择/原源码保留|官方资产下载不完整/访问门禁；浏览器环境、60%回放协议、具体业务检查点均未准入|
|MAB|8|固定split/row/context/QA；原QA与文件动作；四个有限字面纠错组件；两臂CLI|书籍专属有价值信息gold、三次真实驱逐及快照；隔离压力Window参数仍未确认|
|Marathon|2|原起点、原验证器正反控制及双臂完整Pi软件预检|长程业务/记忆gold与完整执行；Ruby配对资源须顺序|

通用缺项还包括Q2受控无效输入/原子性/幂等机会的全包调度、Q3独立的完整渲染Rule预期、Q4完整Window选择/所有引用类型的gold，以及若干S1/S2跨窗口语义检查点。不能以通用函数/fixture存在视为这些选题已实现或测得通过。

五个本项目千次成功资格仍为0（NOT_RUN），不把mock、HTTP重试、模拟用户、judge或输入token折算千次。按冻结公平调度，WDM最迟完整配对起跑18:26:12 UTC、Ruby16:46:12，均已过；普通1800秒与TB-04的900秒计划也须遵守相应最迟起跑，不能缩短另一臂或擅自延长20:20:12模型截止/23:42:12用户硬截止。当前35题全包不能在原条件下交付真实分数；剩余实现与权限阻塞分别列明，而不把所有未完成都归因于授权。

## 21时后的适用矩阵与汇总契约修正

研究包明确是设计材料：`proposed_case_ids`是建议覆盖点，不是穷尽的负面适用性清单。旧生成器将未列入建议的单元格标为`DESIGN_NA`，这一实现错误已修复；原有v1工件保留，不作为新版准入契约使用。新版`fixed35-research-assignments-20261102-v2`遵循以下规则：

- 原题结果、通用工具/费用/请求遥测、Rule、Window/State交付和节奏观测覆盖全部35个Pi episode；这只是测量适用性，不宣称已实现或实际调用过工具。完整证据证明机会/分母为0时，才由对应公式报告条件无机会。
- 其余已建议的case机会标`PLANNED`；尚未编写具体机会的标`DESIGN_UNRESOLVED`，不能写为`-`。245个明确旧题专属单元格（7行×35题）保留真正的设计不适用。
- 5950个case×metric单元格中，3673个计划测量、2032个设计待完成、245个旧题专属不适用。按角色另分2695个有评分含义的单元格、3010个原始诊断单元格、245个旧题专属项。两组口径不是实现完成率；不能声称2032个缺口都是不同的新功能，也不能要求每个原始计数成为能力分。

`fixed35 sources`现在同时生成明确`DRAFT_NOT_ADMITTED`的逐题草稿和`pack-draft.json`；可经`pack-report`生成35题全矩阵的未运行视图，但不得启动这些草稿。正式准入拒绝草稿、未解决设计以及旧版错误NA矩阵。原生插件专属项仍在原生侧结构性不适用；两臂共有指标使用相同有效交集和权重。

汇总端另修复了两条错误路径：结果不能把冻结的`PLANNED`或`DESIGN_UNRESOLVED`降级成`DESIGN_NA`；加载实际报告时，必须匹配冻结的文件hash、case ID、契约hash/版本、报告schema/evaluator版本、逐指标mapping版本与完整的双臂指标集合。新case报告评分器为`fixed35-score-20261102-v4`，整包汇总为`fixed35-pack-20261102-v2`。混用旧报告会报错；旧版本及原始报告不被覆盖。

同时移除与题目无关的45分钟episode准入上限。新准入读取冻结且hash核验过的`task.toml`，episode必须为有限正数且不超过其中agent时限；既有公平资源调度、actor截止、验证和清理预留继续生效。这不授予本轮延期，也不自动把派生短预算变成原题完整时长。

新增`fixed35 switch-contract`、`switch-final`把INT-06/07绑定到锁定Switch-SWE源码：分别16、19个源阶段，记录每阶段目标工作区、返回点、最新约束点、独立的源响应ID/评分器ID，以及原F2P/P2P测试和保护文件。最终交付检查包含严格JSON、正确源响应ID、非空分析及unified-diff路径形状；原业务测试作为另一个检查点，分别对F2P、P2P和原评分器正常完成作AND。补丁形状不等于可应用或功能正确；源业务测试不等于Task恢复或记忆采用。这些组件不新增历史分数或权重，不把源响应ID当作MemWeave Task ID。

Switch源相关性槽位和路由台账已明确，但实际Task检索种子、Goal语义绑定、首次关键业务动作恢复、简单插话overlay和完整actor接线仍未完成。通用真实Pi假provider的T1–T4工具证明仍只算程序协议预检，不能倒填为这两道选题或模型的行为成绩。

截至本节封存准备，35道正式配对仍为0；新增真实模型请求为0。最后账本仍为6笔已结算、USD0.00227448、0笔预留。外发审批未确认、冻结actor截止已过；同时存在上述实际实现缺口，因此不能交付承诺的全数字插件表或公平实测比较表。草稿表里的`NOT_RUN`/`DESIGN_UNRESOLVED`明确表示任务未完成，不以夹具分数、条件满分或`-`掩盖。

最终离线候选：`PYTHONPATH=experiments/src experiments/.venv/bin/python -m pytest experiments/tests --junitxml=/tmp/memweave-35-20261102/tests-v4-seal.xml`实测483项通过；`npm run check`实测资源检查、TypeScript、单元和集成276项通过；受影响Ruff及`git diff --check`通过。最初默认沙箱运行的4个localhost HTTP fixture因bind权限报错，按工具审批流程运行同一套离线测试后全部通过；没有更改网络/安全设置或绕过真实模型请求拒绝。产品`src/`、资源、prompt和预算实现无本阶段改动；真实模型/官方付费judge、完整35题正式实验和发布验收未运行。
