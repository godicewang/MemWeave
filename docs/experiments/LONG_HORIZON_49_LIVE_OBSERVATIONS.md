# 49题双变体实验：持续观察

2026-10-28。本文件由当前活动会话追加，不是定时任务输出。计划：SWE Pro V2 35题、TB 4.0 14题，各原生/完整MemWeave Pi一次；统一20美元/48小时止损。官方评分仍是二值reward，不把环境错误当0。

- 18:47 CST：已完成schema2定向清单、按题配对的混合Harbor Job、统一观察账本和分组评分接线；81项实验自动测试通过，Ruff与Python编译通过。软件准备和官方任务控制尚在验证，未发起付费解题。
- 专用Colima已由8核/16GiB/120GiB扩到12核/42GiB/240GiB；Docker实测12 CPU、44082647040 bytes内存。保留原VZ/Rosetta和隔离设置。
- 审计发现：官方PatchReplayAgent按task_name找补丁，混合变体Job不能直接作为重放来源。现按变体复制原始result.json与原补丁、记录SHA后分别交给官方评分器；没有修改官方评分器。
- 观察边界：Harbor公开生命周期hook记录解题开始/结束；原生Session挂载后增量读取完整usage行。只派生计数和引用，不增加模型提示、工具或聊天副本。费用以官方峰时费率保守估算；在途响应可能晚报usage，不能承诺账单硬上限。

后续每组的准入、并行、真实推理、评分与异常将在此继续记录；最终98行表和badcase报告另行生成。

- 18:48:39 CST：正式Campaign开始，run_id=`20261028T104839Z-2121023e21`，统一截止2026-10-30 18:48:39 CST；初始源码b63b24e，候选包仍为f3931ce3产物。首组S01–S05准备官方linux/amd64镜像，未开始模型推理，当前费用0。原件位于`~/.local/share/memweave-experiments/runs/20261028T104839Z-2121023e21/`。
- 18:49 CST：独立公共Job API空解验证正在原官方Flipt容器内运行Go编译，docker top显示编译进程持续推进；尚未出分，不提前声明通过。主机memory_pressure显示85% free指标（不是虚拟机内存配额），暂未见资源压力。

- 18:53 CST：核对历史同题Flipt控制，官方verifier耗时约9分31秒（oracle）、7分12秒（nop），当前独立空解验证仍在Go编译；尚无评分异常证据。14题TB的官方评分器CPU/内存均不高于对应Agent配置，仍以官方资源配额安排题对。当前实际解题并发0、费用0，准备/控制不计解题。

- 18:57 CST：公开Harbor Job API的真实Flipt空解控制已结束，官方reward=0、exception_info=null，耗时约11分07秒；完整start/environment-start/agent-start/agent-end/verification-start/end记录齐全。该结果验证空补丁不会误得分及生命周期接线，不是原生Pi能力成绩。没有模型调用。虚拟机Docker盘实测236GiB总量、37GiB已用、189GiB可用。

- 18:59 CST：S02 Vuls官方镜像已成功拉取并冻结为sha256:3347b76b458ed77cf1a4d77aaa3abc48c86a417f70c0e7717427473c1ad4fb36，linux/amd64；约十分钟的下载等待没有触发替换。当前进入S03 Open Library镜像准备。独立nop底层日志显示真实Go TestLoad及子测试执行并失败，官方reward=0；后续准入仍须oracle=1/nop=0成对通过。实际解题并发及费用仍为0。

- 19:08 CST：首组3/5官方镜像已冻结（Flipt、Vuls、Open Library），开始Navidrome；尚无准入失败、替换或付费推理。新增只读Session分析程序在仓库外analysis/long49，按原件路径汇总调用/工具错误、最大实际上下文输入、原生压缩、Window非空边界及积压；不修改Task、Session、补丁或评分，也不把仅有State写入当作记忆收益证明。

- 19:11 CST：当前组Navidrome准备期间，用独立受限进程并行预拉取同组Qutebrowser原官方linux/amd64镜像；只温热Docker缓存，不改任务定义/镜像内容，正式prepare_task仍核对镜像并执行全部控制。命令、task.toml哈希与完整拉取日志保存在Campaign preparation-overlap/，无凭据、无模型。未提前缓存其他未活动组，避免不受控磁盘增长。

- 19:17:14 CST：S04 Navidrome官方GHCR镜像拉取失败：short read（expected 58,698,298 bytes, received 36,303,808），unexpected EOF。原始日志在groups/g01/preparation/该完整任务ID/main.log；目前原生/插件均无模型尝试，不能计能力0分或插件badcase。同档RS01存在；因旧选题§5允许同档候补、新执行§5却写首批不自动使用，两处边界尚未完全对齐，已向用户集中提问；候补未启用，其他原题准备继续。

- 19:33:50 CST：用户已明确同意按冻结顺序使用同集合/同档候补；S04将使用RS01，原题阻断证据保留。旧准备run在19:21:33安全停止，模型请求0、费用0、Docker无残留活动容器。新接线按49槽位保存actual_task_id，并另列原题/失败候补双变体阻断行。86项自动检查、Ruff及Python编译通过；另以两份内容不同的历史NodeBB原补丁调用冻结上游PatchReplayAgent查找逻辑，两次均匹配自身SHA，未调用模型、未重评或新增能力成绩。
- 窗口延续只接受已结束、无任何模型Job/Session的同清单/候选/runtime准备run，已核验父索引；继承S04镜像阻断以直接启用RS01，不重复尝试原题。整批仍20美元、截止不晚于2026-10-30 18:48:39 CST。此前时间全部保留在整体墙钟，既无模型重复尝试也无预算重置。
- 评分可信度补强：最终run/live纳入证据索引，未入索引新增成绩拒绝；SWE评分还核对原尝试、同变体交接清单、原/副本补丁与结果SHA及评分Job source_job。该接线防错测试不是真实Pi能力成绩。完整Pi/插件加载和任务控制仍在每组模型前真实执行。

- 19:35:10 CST：继续run=`20261028T113356Z-c96781a690`，实验接线提交a96dff8已推送。新run的window_started_at仍为2026-10-28 18:48:39，window_deadline_at仍为2026-10-30 18:48:39；不是新增48小时。已复用此前成功下载的镜像；首组按原S01/S02/S03、S04→RS01、S05做准入。当前尚无模型调用；模型准备、费用观察和官方评分仍使用真实隔离容器。

- 19:49:06 CST：用户要求先单题完整闭环。已安全停止仍无模型调用的整组准备run 20261028T113356Z-c96781a690；RS01官方镜像另行缓存已成功（退出0），不再阻挡S01。单题bootstrap仅S01原生/插件两次新解题，报告明确阶段2行/总体98行。S01历史oracle1/nop0的任务哈希、镜像ID、Harbor/Docker服务与平台、官方评分配置及源结果哈希已程序核验匹配，可复用控制；两变体解题与新沙箱评分全部重跑。87项自动检查及控制复用正/反例通过。非阻断优化后置，费用/原始截止不变。

- 19:56:18 CST：S01两变体已真实进入DeepSeek解题：原生Session开始19:54:30、插件19:54:34，实测峰值2，非SDK/API哨兵。完整加载预检分别发现4个原生工具、16个完整插件工具且model_requests=0；随后才交付私有认证并真实解题。19:55:45观测到25次真实模型返回，已知峰时估算0.02501238美元；插件已task_create并调用read/edit/bash，未提前声明解出或记忆收益，仍需官方新沙箱评分。

- 20:00:58 CST：两变体仍在真实Go构建/测试，docker top显示原生和插件各自容器内有持续更新的compile/vet进程，不是模型API无响应。插件18次返回后执行全库go build＋config go vet；原生主要针对config包做go test并给命令900秒上限。插件此前工具错误为读取不存在oidc.yml及一次无变化edit，循环已继续；暂不当作插件实现故障或记忆丢失。官方分数仍待新沙箱。

- 20:04:37 CST：当前活动bootstrap run为20261028T114908Z-6fe6754177，源码32b3a33已推送；范围仅S01两变体（full_plan仍98行），完成本题官方评分与报告前不进入10并发。此前“已有软件缓存”需细化：本镜像第一次Pi base安装约2分钟，插件addon约2分钟；Node下载与embedding公共缓存命中，随后正式Trial复用本次密封归档。当前仍2个真实Pi实例在编译/测试，已知估算费用0.028136664美元；官方评分未出。

- 20:12:26 CST：补核发现原生也有grep不存在marshal/*.yml的命令输出，但因后接head/其他管道而Pi isError=false；插件读取不存在oidc.yml则isError=true。因此“原生工具错误0/插件2”仅是Pi标志计数，不能等同全部命令失败或比较稳定性。插件另有一次edit无变化告警。两边都已选择全库go build，不能将全库验证范围只归到插件；先前过程差异仅为执行先后。官方新沙箱最终成绩仍独立核验，不用这些工具退出码推断通过。

- 20:19:36 CST：两变体解题均正常结束并捕获补丁：原生1035.733秒、插件1164.935秒；原生15次API返回，插件27次；费用分别0.01236864与0.02411094美元，合计0.03647958。当前已进入原生官方新沙箱评分，未扩展任务。插件两次State超长失败后第三次成功，已按既定JSONL核对归档仅Goal/F1/D1三条并补入MW-002；无Window移动，不能归为遗忘。其他普通工具错误保留到审计表，不只比较isError计数。

- 20:40:48 CST：S01闭环完成，原生/插件官方均1分、评分无异常、TestLoad必需项均1/1，最终报告complete=true、invalid_evidence=[]。阶段49分20秒；累计费用0.03647958美元，剩余额度约19.96352美元，原48小时截止不变。报告写入BOOTSTRAP_S01_REPORT_2026-10-28.md，MW-002补充了最终官方结果。后续扩展只执行其余48题，不重跑S01。

- 21:24:34 CST：剩余48题改为最多5个独立题对Harbor流水线，CPU/内存/存储峰值限流；缓存就绪优先、穿插TB，不等整组。S06两变体完整软件缓存已无模型准备成功。95项实验自动检查、Ruff、编译及真实S01父结果导入/官方双评分Agent配置校验通过；父费用0.03647958已锁定，新增推理可用19.96352042，原截止不变。S01不会再次提交给模型；最终比较仍98行，带origin_run区分父源。仅实验接线改动，生产src/resources/package文件与f3931ce3完全相同。

- 21:28:46 CST：活动full run=20261028T132435Z-f172223f56，接线8b0a645；继承S01已完成两行与0.03647958美元，只对剩余48题新增96次解题。5个题对工作槽已启动，S06先就绪，其他g02/03/04/05仍控制/软件预检时它已完成配对真实解题，45次模型返回，新增约0.035204892美元，目标“就绪不等整组”已有实测证据；截至13:27:15 UTC解题峰值2，未冒称10。总截止仍2026-10-30 18:48:39 CST。

- 21:38 CST：配对流水线因g05插件无模型预检中的npm ECONNRESET安全停止；已结束run=20261028T132435Z-f172223f56，无活动付费解题。新增S06两侧均正常产补丁，首次官方新沙箱评分0/0；S01仍为1/1。新增费用0.035204892、整批累计0.071684472美元；其余预检失败/取消不计能力0分。
- 21:47 CST：只读审计S06首次评分：原生必需项116/117，失败为新用户编辑时限；插件84项通过但3个before hook报no-privileges／too-many-posts，导致后续必需项未执行。官方补丁与测试补丁均应用成功、变体交接SHA一致。将相同冻结补丁逐个在新沙箱串行重评（模型请求0），结果原生仍0、插件1。保留首次0/0，不作择优计分；插件评分稳定性存疑，尚无跨容器共享Redis证据，也不能归为插件记忆缺陷。完整原件：analysis/long49/s06-sequential-score-audit/audit.json。
- 21:48 CST起：串行无凭据、无模型恢复g05/g03/g04软件缓存；每题仍重新完整SDK加载。共享软件错误不触发任务候补。后续续跑接口待用户按AGENTS第2节确认；镜像准备和原件分析可独立继续。

- 22:05 CST：用户已确认受限续跑并保留首次评分。新入口completed_parent已先写设计再实现；真实父记录验证导入S01/S06共4行，累计0.071684472美元与原截止不变，原来源run保留，S06首次0/0未被诊断替换。第二轮同补丁串行新沙箱诊断（逆序先插件）两边均1，说明原生首次0同样存在稳定性疑点；两次诊断均模型请求0。原件analysis/long49/s06-sequential-score-audit-2/audit.json，不挑最高分改表。
- 22:07 CST：99项实验自动检查、Ruff通过；续跑拒绝不完整题对／未核算费用，报告能合并已结束但整批未完成的父阶段，只导入核验题对。S03完整双变体无凭据软件恢复通过，进入S04→RS01缓存恢复。S07/S08官方镜像已预拉取成功；S09仍下载。S05独立同镜像npm诊断已明确看到onnxruntime-common包下载一次ECONNRESET后npm自身重试成功，onnxruntime-node大包仍下载中，尚未判定修复。

- 22:18:14 CST：受限续跑run=20261028T141814Z-e1cf21ad6a已启动，接线8a1fe25；活动计划94行、总体98行，继承S01／S06共4行及0.071684472美元，新推理余额19.928315528美元，原截止不变。最多5个题对工作槽。S03／S04→RS01完整软件缓存已就绪；独立S05预检仍在收尾，控制器有界等同对象写者，不重复安装或排住已密封题。
- 22:18 CST：S07官方镜像准入遭GHCR HEAD EOF，同档RS02遭manifest TLS handshake timeout，按冻结顺序耗尽该档候补后保留两变体blocked；不是能力0。虽然S07此前预拉取成功，当前冻结实现仍对预制镜像执行远端pull核验，缓存层并不消除这次远端故障；不在已冻结运行中改接线或改任务，明确列为实验基础设施限制。T01既有官方600秒构建超时阻断继承，其余题继续。

- 22:21:53 CST：续跑阶段安全停止，原因g05两变体在Pi之前的Pro网络探针失败。逐项查证官方Qutebrowser镜像只有bash，没有curl／wget，故硬编码curl检查无法执行；不是API认证或能力失败。源代码在super().run之前抛出该精确异常，两Trial无Pi输出／Session／usage。S03原生正常、插件在最后assistant stop后仍被联动取消；补丁分别2274／6398字节已捕获，新增31次usage返回、费用0.021378864，累计0.093063336美元。S03原结果和取消状态保留，另做无模型官方原补丁评分，不重新解题。
- 22:27 CST：已向用户集中对齐探针修复（固定Node内置HTTPS，相同网络边界）、跨这一处接线等价变更的来源链、已计费中断题保留不重跑与已证实Pi前失败的首次真实解题边界；未改核心插件／Rule或开始新付费运行。提案INTERRUPTED_PHASE_RECOVERY_PROPOSAL.md；其余原官方镜像预拉取仍继续。

- 22:30 CST更正：精确原件时间表明，S03插件CancelledError发生14:21:42.365 UTC，State成功14:21:43.429、最终assistant stop为14:21:47.051，均在取消之后。此前“最后答复后仍被取消”顺序判断错误。finally快照中的state.json只有Goal，与快照先于后台继续写State相符，不能称为插件持久化丢写。捕获补丁官方新沙箱分数原生1／插件0、两侧评分无异常；保留中断标记，不替换原件或作为正常完成比较。独立评分原件analysis/long49/s03-interrupted-patch-grading/audit.json。

- 22:43 CST：Node探针在原S05官方镜像的两个真实Harbor隔离环境验收通过：模型端点401，example.com在原Agent网络策略下ECONNRESET；两侧完整SDK加载成功，原生4工具／插件16工具，插件embedding384维，模型请求0、无凭据。此输运诊断显式部署先前密封的同版本软件，不发布或伪造新缓存身份；正式下一阶段仍按变化后的新配方键重新完整准备。原件analysis/long49/node-probe-real-acceptance/acceptance.json。109项实验自动检查、Ruff及编译通过。
- 源码等价性仅放行已批准旧pi_agent SHA 67b9481b…→2599b4fb…及固定network_probe SHA 57a62831…，Pi调用／捕获代码不变；其他适配差异仍拒绝。真实父记录验证继承6行原尝试、累计0.093063336美元，S03明确中断／不参与正常配对比较；S05两侧按精确旧异常、无Pi输出／Session／usage及空补丁证明0模型，可首次真实解题。公共模型故障仍全局停止新模型，可靠观测和原时限有余额时允许无模型官方评分完成原补丁。

- 22:45:05 CST：新阶段run=20261028T144505Z-36cd22f224，接线31346ea已推送；活动计划92行、总体98行。继承S01／S03／S06六行原模型尝试及0.093063336美元，新推理余额19.906936664美元，原截止不变。S03中断补丁分数另表1/0，不改原取消状态；S05已证实旧尝试无Pi，才列入新阶段首次真实解题。当前新配方软件准备开始，未用旧对象改头换面绕过完整预检。

- 23:05:05 CST：当前阶段已结束，新增模型0、费用0，累计仍0.093063336美元，98行报告invalid_evidence=[]。S05准备再次ECONNRESET，已确认串行化不能消除大包重复下载。只从本机npm内容缓存选取公开onnxruntime-node@1.30.0原tar，113507888字节，SHA-512与锁文件一致，SHA256 6e3390d6…，未复制任何其他缓存或npmrc。独立network=none新官方镜像中，offline cache add后按原URL＋SSRI取回相同SHA，验证通过（首轮调用底层读取库误给父目录导致ENOTCACHED，改为_cacache后通过，失败原件保留）。提案PUBLIC_NPM_ARCHIVE_CACHE_PROPOSAL.md待用户确认；不擅自发布新缓存契约。进一步同镜像全安装＋384维向量验证无模型进行中。

- 23:15:01 CST：独立npm公开归档断网取回验证已通过，恢复SHA256与原tar一致，无模型。完整安装＋实际本地embedding兼容验证仍在进行；缓存契约接入仍等待用户确认。另发现npm一次Date.now差为-29ms；对宿主arm64 Node23与官方NodeBB amd64 Node22各采15秒，均未观察到时钟回退。因此只保留瞬时现象，不将S06不稳定唯一归因于虚拟机时钟。S03评分交接原件／副本／result哈希与父索引逐一复核，两变体各匹配自身，见analysis/long49/s03-interrupted-patch-grading/binding-audit.json。

- 23:15:52 CST：公开tar预热后的完整安装约4分钟退出0，LocalEmbedding实际384维，模型0、无凭据，无新软件对象伪装。原件seeded-npm-full-install/result.json。正式缓存接入仍待确认；本阶段所有付费Job已结束，累计0.093063336美元不变。

## 2026-10-29：用户授权持续完成全部49题

- 用户已同意公开归档缓存，适配／缓存／实验环境提案由执行者酌情审议并修复继续；取消整批时间和token额度限制。美元上限已另行询问，待答复前继续保留20美元费用保护。疑难文档只记录有证据的实际现象、原因与限制，不把建议当作修复或把环境错误当作插件能力失败。
- 00:21:55 CST：run=20261028T162155Z-9b88cd6f75，接线02776f5已推送；completion_mode=all_tasks，整体deadline=null，仍保留官方单题时限与资源。活动94行／总体98行；S01／S06原正常4行继承，S03两条中断移入historical_attempts并恢复完整题对，旧1/0补丁结果仍单列。历史费用0.093063336美元不清零。
- 缓存接入与生产归档安装已完成，113项实验自动检查、Ruff、编译通过；真实S05双变体完整SDK／网络与embedding预检通过，NPM安装后候选77个文件与原npm归档逐字一致。原生工具4、插件16、embedding384维，预检模型请求0。正式Pi调用／提示／工具／候选资源保持原版本。
- 00:24:59 CST：S05已进入新阶段双变体解题，S07已通过镜像和控制准入。已核验的官方RepoDigest镜像直接复用，消除仅因远端HEAD故障永久阻断的情况；失败旧原件保留。T01在analysis/long49/t01-original-prebuild-20261029按未修改官方Dockerfile独立预建，尚未声称准入／评分通过，无模型。

### 2026-10-29 01:14:24 CST

已审计7个正常题对；S03、S05原生1／插件0，S06保留首次不稳定0／0；其他4题两边1。旧S08取消后补丁评分1／1、T01插件正常1／原生取消均不算正常题对，保留后恢复。总估算费用0.443876028美元。S09 Alpine导致GNU Node fcntl64缺符号，私有GNU loader原型已通过完整双SDK、embedding384、网络探针；固定最终recipe及CLI超时壳再验。单镜像准备故障隔离和TB scored续跑边界118项实验测试通过，Ruff／编译通过。生产候选未变。

### 2026-10-29 01:18:20 CST

修复191146f已锁定并启动run `20261028T171721Z-1962af9075`，继承14个正常结果、84个待运行结果、历史6行及全部0.443876028美元。最终musl原生／插件验收通过，双方CLI、完整SDK、embedding及隔离网络正常，0模型。并行准入S08／S09／S10／S13／S14；仅将真实Pi生命周期计入解题峰值。S05额外原样类／属性描述符探针：注入SIP_VERSION_STR=6.7，原生返回6.7、插件返回None，证明遗漏单元素tuple缺陷；仅独立依赖桩，不冒充完整Qt测试或增加模型样本，原件analysis/long49/s05-sip-static-replay.json。

- 01:21:43 CST：[('g08', 'preparing'), ('g13', 'software_preflight'), ('g14', 'preparing'), ('g10', 'preparing'), ('g09', 'preparing')]；本阶段模型返回0。S08 oracle在测试重置git checkout处报Segmentation fault，官方必需156项过155，缺RoomPreviewBar rejecting message；没有Pi能力分数，准入证据保留。S13 oracle1/nop0已核验。

- 01:29:35 CST：S13正常解题并官方评分1／1，累计8／49正常题对；S09 oracle1/nop0、musl双侧完整预检通过后真实解题。S13插件Task goal109超100一次，随后同批bash被TASK_BINDING_REQUIRED拒绝，均可恢复；没有窗口移动，不称长程记忆收益。S14官方控制Go1.22.12父进程等待、多个vet僵尸，宿主exe为Rosetta，暂不推定Rosetta根因；等待官方预算／退出并保留限制。T02原Dockerfile双镜像预建成功。

- 01:33:50 CST：S09双方正常解题、agent_settled，进入两份新沙箱官方评分；T01双方真实解题，模型返回累计122，本阶段已测峰值3；总估算美元0.545172804。T02／T03官方原始双Dockerfile已预建，后续辅助预建用独立memweave-eval-prewarm标签，不写正式冻结tag；正式任务仍按原Dockerfile构建／命中原层。已核对并删除旧已结束run141814的孤立egress sidecar，未触碰活动容器。

- 2026-10-29 01:34:42 CST 人工复核快照：{"run": "20261028T171721Z-1962af9075", "groups": [["S08", "preparing"], ["S13", "finished"], ["S14", "preparing"], ["S10", "preparing"], ["S09", "regrading"], ["T01", "solving"]], "model_responses": 122, "active": {}, "peak": 3, "total_estimated_usd": 0.545172804, "stop": null, "finished_at": null}。

- 2026-10-29 01:35:29 CST 人工复核快照：{"run": "20261028T171721Z-1962af9075", "groups": [["S08", "preparing"], ["S13", "finished"], ["S14", "preparing"], ["S10", "preparing"], ["S09", "regrading"], ["T01", "solving"]], "model_responses": 122, "active": {}, "peak": 3, "total_estimated_usd": 0.545172804, "stop": null, "finished_at": null}。

- 2026-10-29 01:36:02 CST 用户明确取消20美元上限；已准备unlimited_cost=true的后续续跑配置，继承当前阶段原件。当前冻结阶段继续，不原地改锁。后续至49正常题对完成，所有费用继续累计。

- 2026-10-29 01:36:02 CST 人工复核快照：{"run": "20261028T171721Z-1962af9075", "groups": [["S08", "preparing"], ["S13", "finished"], ["S14", "preparing"], ["S10", "preparing"], ["S09", "regrading"], ["T01", "solving"]], "model_responses": 122, "active": {}, "peak": 3, "total_estimated_usd": 0.545172804, "stop": null, "finished_at": null}。

- 2026-10-29 01:36:48 CST 人工复核快照：{"run": "20261028T171721Z-1962af9075", "groups": [["S08", "preparing"], ["S13", "finished"], ["S14", "preparing"], ["S10", "preparing"], ["S09", "finished"], ["T01", "finished"], ["S11", "preparing"], ["S12", "preparing"]], "model_responses": 122, "active": {}, "peak": 3, "total_estimated_usd": 0.545172804, "stop": null, "finished_at": null}。

- 2026-10-29 01:38:49 CST 人工复核快照：{"run": "20261028T171721Z-1962af9075", "groups": [["S08", "preparing"], ["S13", "finished"], ["S14", "preparing"], ["S10", "preparing"], ["S09", "finished"], ["T01", "finished"], ["S11", "preparing"], ["S12", "preparing"]], "model_responses": 122, "active": {}, "peak": 3, "total_estimated_usd": 0.545172804, "stop": null, "finished_at": null}。

- 2026-10-29 01:39:49 CST 人工复核快照：{"run": "20261028T171721Z-1962af9075", "groups": [["S08", "preparing"], ["S13", "finished"], ["S14", "preparing"], ["S10", "preparing"], ["S09", "finished"], ["T01", "finished"], ["S11", "software_preflight"], ["S12", "preparing"]], "model_responses": 122, "active": {}, "peak": 3, "total_estimated_usd": 0.545172804, "stop": null, "finished_at": null}。

- 2026-10-29 01:40:48 CST 人工复核快照：{"run": "20261028T171721Z-1962af9075", "groups": [["S08", "preparing"], ["S13", "finished"], ["S14", "preparing"], ["S10", "preparing"], ["S09", "finished"], ["T01", "finished"], ["S11", "software_preflight"], ["S12", "preparing"]], "model_responses": 122, "active": {}, "peak": 3, "total_estimated_usd": 0.545172804, "stop": null, "finished_at": null}。

- 2026-10-29 01:41:45 CST 人工复核：模型返回122，在途{}，峰值3，累计估算$0.545173，停止原因None。

- 2026-10-29 01:42:57 CST 人工复核：S11:software_preflight→solving；模型返回122，在途{'pi-native': 1, 'pi-memweave': 1}，峰值3，累计估算$0.545173，停止原因None。

- 2026-10-29 01:43:41 CST 人工复核：模型返回158，在途{'pi-native': 1, 'pi-memweave': 1}，峰值3，累计估算$0.579547，停止原因None。

- 2026-10-29 01:44:49 CST 人工复核：模型返回190，在途{'pi-native': 1, 'pi-memweave': 1}，峰值3，累计估算$0.605885，停止原因None。

- 2026-10-29 01:45:00 CST 人工复核：模型返回197，在途{'pi-native': 1, 'pi-memweave': 1}，峰值3，累计估算$0.611929，停止原因None。

- 2026-10-29 01:46:05 CST 人工复核：S08:preparing→software_preflight；模型返回208，在途{'pi-native': 1}，峰值3，累计估算$0.621636，停止原因None。

- 2026-10-29 01:46:50 CST 人工复核：模型返回209，在途{'pi-native': 1}，峰值3，累计估算$0.622158，停止原因None。

- 2026-10-29 01:47:41 CST 人工复核：S10:preparing→blocked；T02:未开始→preparing；模型返回212，在途{'pi-native': 1}，峰值3，累计估算$0.623540，停止原因None。

- 2026-10-29 01:49:17 CST 人工复核：S11:solving→regrading；S12:preparing→software_preflight；T02:preparing→software_preflight；模型返回216，在途{}，峰值3，累计估算$0.627228，停止原因None。

- 2026-10-29 01:50:59 CST 人工复核：S08:software_preflight→preparation_failed；S11:regrading→finished；S15:未开始→preparing；S16:未开始→preparing；模型返回216，在途{}，峰值3，累计估算$0.627228，停止原因None。

- 2026-10-29 01:55:03 CST 人工复核：S12:software_preflight→solving；模型返回228，在途{'pi-native': 1, 'pi-memweave': 1}，峰值3，累计估算$0.636950，停止原因None。

- S11原样清理函数探针已完成：官方起始镜像默认Node18.20.8，12次重复结果稳定；普通8文件两边清0，带时间戳8文件原生清0／插件残留8。仅明确依赖桩，不冒充全NodeBB／Pi重跑；对应官方插件账号删除4文件残留。已写MW-011场景G；原生群组封面失败另因待核，两个官方0分保留。S08候补软件阶段rm清理命令退出139，未开始模型；继续其他题、后续修复恢复。

- 2026-10-29 01:56:04 CST 人工复核：模型返回273，在途{}，峰值3，累计估算$0.666708，停止原因None。

- 2026-10-29 01:57:15 CST 人工复核：S12:solving→regrading；模型返回273，在途{}，峰值3，累计估算$0.666708，停止原因None。

- 2026-10-29 01:59:49 CST 人工复核：S12:regrading→finished；T02:software_preflight→solving；模型返回273，在途{}，峰值3，累计估算$0.666708，停止原因None。

- 2026-10-29 02:01:39 CST 人工复核：模型返回323，在途{'pi-native': 1, 'pi-memweave': 1}，峰值3，累计估算$0.713794，停止原因None。

- 2026-10-29 02:03:22 CST 人工复核：模型返回360，在途{'pi-memweave': 1}，峰值3，累计估算$0.750353，停止原因None。

- 2026-10-29 02:05:02 CST 人工复核：模型返回397，在途{'pi-memweave': 1}，峰值3，累计估算$0.787446，停止原因None。

- 2026-10-29 02:07:08 CST 人工复核：T02:solving→finished；T03:未开始→preparing；S17:未开始→preparing；模型返回423，在途{}，峰值3，累计估算$0.821563，停止原因None。

- 2026-10-29 02:12:28 CST 人工复核：S14:preparing→blocked；S15:preparing→blocked；S16:preparing→blocked；T03:preparing→software_preflight；S18:未开始→blocked；T04:未开始→blocked；S19:未开始→blocked；S20:未开始→blocked；T05:未开始→blocked；S21:未开始→blocked；S22:未开始→blocked；T06:未开始→blocked；S23:未开始→blocked；S24:未开始→blocked；模型返回423，在途{}，峰值3，累计估算$0.821563，停止原因None。

- 2026-10-29 02:14:53 CST 人工复核：T03:software_preflight→solving；模型返回442，在途{'pi-native': 1, 'pi-memweave': 1}，峰值3，累计估算$0.840354，停止原因None。

- 2026-10-29 02:18:23 CST 人工复核：T03:solving→finished；T07:未开始→preparing；S25:未开始→preparing；模型返回470，在途{}，峰值3，累计估算$0.901430，停止原因None。

- Phase171721 closed after all paid solves/grades ended:14 normal pairs, no invalid_evidence, total estimated USD0.90142992. Remaining35 require continuation; no normal0 is rerun for a higher score. The phase closed to repair common daemon registry EOFs. Range utility has6 new boundary tests; all124 experiment tests pass and Ruff passes. A real Docker OCI import fixture preserved its exact manifest digest, RepoDigest, linux/amd64 platform and filesystem digest; no Agent/model ran. The fixture was removed. Real public S10 preload is next.
