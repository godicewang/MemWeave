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
