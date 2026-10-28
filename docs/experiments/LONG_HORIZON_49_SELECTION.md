# MemWeave 长程公开任务子集：49题

2026-10-28。状态：**选题已冻结，环境准入待验证；本轮没有模型调用、拉取/构建任务镜像或运行官方控制。** 用户确认结构审查与四档预评级、SWE Pro V2 35题＋TB 4.0 14题。此文件及[完整机器清单](../../experiments/subsets/catalogs/long-horizon-49-v1.yaml)记录同一选择；原始任务和评分协议不变。

## 第一部分：实验目的与取舍

先前四道TB任务不能充分代表需要持续管理工程状态的工作。本专项选择需要调查代码/材料、建立跨模块解释、保持约束、联动修复并完成验证的任务。重点是原生Pi与MemWeave在连续工程执行中的差异，不预设插件一定更好，也不把运行慢或模型反复试错当成长程记忆压力。

| 任务集 | 简单 | 中等 | 难 | 超难 | 合计 |
|---|---:|---:|---:|---:|---:|
| SWE-bench Pro V2 | 5 | 5 | 10 | 15 | 35 |
| Terminal-Bench 4.0 | 2 | 2 | 4 | 6 | 14 |
| 合计 | 7 | 7 | 14 | 21 | **49** |

49是7的倍数，恰好满足1:1:2:3。两个集合各自保持这一比例，成绩仍分别报告。SWE覆盖全部11个公开仓库，含Ansible执行核心、Teleport事件/存储、邮件/协作客户端和数据索引等不同工作形态；TB覆盖发布、数据处理、协议修复、故障恢复和完整应用迁移。这是面向长程工作流的定向子集，通过率不能外推为官方全量成绩；同仓库、同子系统题目也不视为完全独立的随机样本。

**四档是本项目的结构预评级。** 冻结的TB 66题没有官方difficulty值，SWE 642题全部标为medium，不能把这些元数据映射成四档。标签既不宣称官方认证，也不是预测DeepSeek通过率。难度在运行前固定，之后不因两边得分/耗时修改；若后来有必要修订，必须产生新版本，原结果保留原分层。

简单档承担有界工程对照：有真实的输入/输出、状态或接口约束，但工作范围相对小，可能不会产生明显记忆压力。其余42题逐步增加跨层依赖、状态生命周期与验证责任；高难档35题是高负荷候选，尚不能称为已验证的长上下文任务。没有采用单纯查表helper、局部数组变换或仅因说明很长就定为超难的办法。

保留旧SWE的NodeBB帖子权限、Ansible WinRM认证和Flipt认证配置三题，分别为中等/中等/简单。此前审计已经暴露这三题结果，后续报告必须单列“历史锚点3题”和“新选SWE32题”，不能把它们说成新盲测。旧Element数组题不入49题，因为其核心是局部数组算法；既有失败与原件继续作为历史算法对照保留，不能删除。

旧TB四题均不计入本主集：Music和Roy主要依赖专业领域推断，Checkpoint主要涉及张量/权重重建；Production Planning虽有资料追踪，但组合优化求解占主导。这里依据任务内容解释适用性，没有用原先的0分、耗时或插件准备失败决定替换，也不把其6小时以上耗时当作“超难长记忆”标注。

本机边界保持不变：CPU任务，最多4 CPU、8192 MiB内存、32768 MiB存储的单任务筛选包络；不扩大GPU、特权或多容器权限。TB静态审查66题中45题符合现有筛选器，其余21题按当前执行器的最终排除标签分别为多容器待审11、CPU超包络5、GPU3、内存超包络2；每题仅计一个标签，并非独立资源条件计数。主选14题全部落在45题内，另核对了解题及原生评分环境的资源包络和Compose定义均符合本批静态边界；静态通过并不证明镜像可构建或评分可靠。

## 第二部分：方法、清单与执行边界

### 1 审查方法

先扫描642道SWE任务的公开标题/指令元数据及66道TB任务元数据，再精读进入主集、候补和本文排除例子的公开指令。没有声称逐字精读全部642题，没有查阅金标补丁、隐藏测试正文、HARD-51成绩、榜单或被测变体得分来决定新题。全目录字节哈希只用于冻结完整性，不用于推断答案或难度。

每题保存四项1–4级结构注记：行为/模块边界、需持续保持的约束、生命周期耦合、验证面。1为局部/有界，2为少量关联路径，3为多层/多分支，4为跨子系统且相互制约。它们是人工审查注记，不是任务分数，也不相加冒充客观难度模型。

| 分层 | 审查含义 | 需要观察的区别 |
|---|---|---|
| 简单 | 有界修复或集成，主要约束可集中检查 | 插件接入开销、是否误用工具、常规交付是否退化 |
| 中等 | 多入口/多实体，需保持相同规则并验证有限生命周期 | 是否漏掉次要消费者、混淆对象身份或遗漏失败路径 |
| 难 | 多模块/多数据表示或多兼容分支，需系统调查与回归 | 是否保留早期证据和已确认约束、避免重复调查 |
| 超难 | 架构/接口迁移、多阶段不变量、异步/恢复/多产物共同约束 | 能否持续维护状态解释、完成联动更改并给出完整验证 |

“生命周期”指题目系统的业务/资源状态，不能直接等同于Agent已经经历长历史。后续须用原件检查真实执行过程：模型返回/工具事件量、逐请求输入峰值、原生压缩、插件窗口移动/回读与State使用，以及失约束、重复调查、恢复和验证的具体证据。缺失的观测标未知；调用了记忆工具也不自动证明它改善了结果。

### 2 SWE Pro V2：35题

下表短编号与机器清单一一对应；链接固定为原上游提交的Agent可见instruction.md。分级依据由“工作边界＋需保持的合同”组成，不含解题补丁或隐藏断言。

**简单**

| 编号／公开任务 | 项目／范围 | 结构预评级依据 |
|---|---|---|
| [S01 · Flipt：认证配置校验](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_flipt-io__flipt-c1fd7a81ef9f23e742501bfb26d914eb683262aa/instruction.md)（历史锚点） | flipt-io/flipt | 配置加载、GitHub/OIDC两类提供方与错误回执；保留字段校验、组织scope约束和精确错误归属 |
| [S02 · Vuls：Trivy包元数据转换](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_future-architect__vuls-7e91f5ef7e5712b1a3d7d5066ad6607e9debc21c/instruction.md) | future-architect/vuls | OS包、源包、漏洞及语言库结果四种表示；完整版本/架构与源包到二进制关联不能在转换中丢失 |
| [S03 · OpenLibrary：迁移版本后更新旧索引](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_internetarchive__openlibrary-03095f2680f7516fca35a58e665bf2a41f006273-v8717e18970bcdc4e0d2cea3b1527752b21e74866/instruction.md) | internetarchive/openlibrary | 变更日志、before/after记录与Solr更新键；兼顾新文档顶层键与旧关系删除后的失效索引 |
| [S04 · Navidrome：公共扩展查询与认证边界](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_navidrome__navidrome-23bebe4e06124becf1000e88472ae71a6ca7de4c/instruction.md) | navidrome/navidrome | 公共路由、参数检查和其余受保护路由；开放指定端点且保留其他端点认证；不能误用nil依赖 |
| [S05 · Qutebrowser：版本缓存与下载完成通知](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_qutebrowser__qutebrowser-01d1d1494411380d97cac14614a829d3a69cecaf-v2ef375ac784985212b1805e1d0431dc8f1b3c171/instruction.md) | qutebrowser/qutebrowser | 版本检测缓存、统一显示和逐项/整批通知；缓存失效后重新检测；完成通知次数和总量保持一致 |

**中等**

| 编号／公开任务 | 项目／范围 | 结构预评级依据 |
|---|---|---|
| [S06 · NodeBB：跨API的帖子读取权限](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_NodeBB__NodeBB-f2082d7de85eb62a70819f4f3396dd85626a0c0a-vd59a5728dfc977f44533186ace531248c2917516/instruction.md)（历史锚点） | NodeBB/NodeBB | posts API、两个HTTP控制器与权限调整后的内容；原文/摘要、删除帖例外与拒绝回执需一致 |
| [S07 · Ansible：WinRM认证参数与凭据缓存](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_ansible__ansible-e22e103cdf8edc56ff7d9b848a58f94f1471a263-v1055803c3a812189a1133297f7f5468579283f86/instruction.md)（历史锚点） | ansible/ansible | 配置优先级、subprocess/pexpect两条认证路径；显式参数优先、委派默认值、单次调用和独立凭据缓存 |
| [S08 · Element：录音前清理已有播放](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_element-hq__element-web-459df4583e01e4744a52d45446e34183385442d6-vnan/instruction.md) | element-hq/element-web | 预录制工厂、录音对象、播放Store与PiP视图；依赖注入贯穿调用链；先pause/clear，再创建录音 |
| [S09 · Teleport：设备注册后入库失败](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_gravitational__teleport-32bcd71591c234f0d8b091ec01f1f5cbfdc0f13c-vee9b09fb20c43af7e520f57e9239bbcf46b7113d/instruction.md) | gravitational/teleport | 注册/登记两阶段、结果对象与集成测试环境；部分成功时保留已注册设备、错误分类和并发安全限额开关 |
| [S10 · Proton Drive：共享成员与邀请隔离](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_protonmail__webclients-d8ff92b414775565f496b830c9eb6cc5fa9620e6/instruction.md) | protonmail/webclients | 成员Store、内/外邀请Store和shareId消费者；替换与增量语义不能混淆；各share互不污染 |

**难**

| 编号／公开任务 | 项目／范围 | 结构预评级依据 |
|---|---|---|
| [S11 · NodeBB：用户/群组图片全生命周期清理](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_NodeBB__NodeBB-8168c6c40707478f71b8af60300830fe554c778c-vf2cf3cbd463b7ad942381f1c6d077626485a1e9e/instruction.md) | NodeBB/NodeBB | 群组、用户、socket入口、账号删除与本地文件；数据库字段与头像/封面文件一致；远程资源和ENOENT语义保留 |
| [S12 · Ansible：Collection清单构建策略](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_ansible__ansible-d2f80991180337e2be23d6883064a67dcbaeb662-vba6da65a0f3baefda7a058ebbd0a8dcafb8512f5/instruction.md) | ansible/ansible | galaxy配置、旧walk、新Manifest路径与归档条目；兼容优先级、指令先后、内部链接和摘要；不安装被禁止的依赖 |
| [S13 · Element：分析组件隐私状态与异步跟踪](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_element-hq__element-web-4c6b0d35add7ae8d58f71ea1711587e31081444b-vnan/instruction.md) | element-hq/element-web | SDK配置、DNT、匿名等级、identify/capture及调用方；初始化/启用状态和匿名优先级统一；所有异步调用按约定完成 |
| [S14 · Vuls：仅保留运行中内核的软件包组](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_future-architect__vuls-e1fab805afcfc92a2a615371d0ec1e667503c254-v264a82e2f4818e30f5a25e4da53b27ba119f62b5/instruction.md) | future-architect/vuls | Debian/Ubuntu解析、源包归一化与CVE结果；保留按源名和版本的分组身份；查找重命名不能改输出身份 |
| [S15 · Teleport：旧会话录像回放兼容](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_gravitational__teleport-c1b1c6a1541c478d7777a48fca993cc8206c73b9/instruction.md) | gravitational/teleport | AuditLog、LegacyHandler、磁盘索引与上传器；有旧解包记录时不下载；错误传播、正常下载和清空上传器后回放都要成立 |
| [S16 · Teleport：慢审计扇出不阻塞活动会话](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_gravitational__teleport-e6681abe6a7113cfd2da507f05581b7bdf398540-v626ec2a48416b10a88641359a169d99e935ff037/instruction.md) | gravitational/teleport | AuditWriter、AsyncEmitter、流恢复与取消上下文；背压/丢弃边界、已接受事件、恢复和关闭分别验证 |
| [S17 · OpenLibrary：可复用搜索Scheme与查询安全](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_internetarchive__openlibrary-7f6b722a10f822171501d027cad60afe53337732-ve8c8d62a2b60610a3c4631f5f23ed866bada9818/instruction.md) | internetarchive/openlibrary | 公共Scheme、work/author/subject变换及Solr请求；别名、引号、布尔运算、ISBN和转义在多入口保持语义 |
| [S18 · Navidrome：播放列表持久化与查询重构](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_navidrome__navidrome-d21932bd1b2379b0ebca2d19e5d8bae91040268a/instruction.md) | navidrome/navidrome | 轨道重写、聚合统计、仓储接口与SmartPlaylist查询；删除旧接口并迁移所有生产调用；过滤/排序/上限一致 |
| [S19 · Proton Mail：提取移动邮件业务流程](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_protonmail__webclients-dfe5604193d63bfcb91ce60d62db2f805c43bf11/instruction.md) | protonmail/webclients | 通知文案、权限拒绝、定时邮件和退订提示及原hook；消息/会话分支、不可撤销、记住偏好和异步持久化不能相互覆盖 |
| [S20 · Qutebrowser：版本表示与ELF失败边界](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_qutebrowser__qutebrowser-394bfaed6544c952c6b3463751abab3176ad4997-vafb3e8e01b31319c66c4e666b8a3b1d8ba55db24/instruction.md) | qutebrowser/qutebrowser | 版本值对象、库文件解析、后端报告与初始化开关；未知来源显示、32/64位结构和各种解析异常的统一边界 |

**超难**

| 编号／公开任务 | 项目／范围 | 结构预评级依据 |
|---|---|---|
| [S21 · NodeBB：权限类型贯穿数据/API/模板/复制](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_NodeBB__NodeBB-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed/instruction.md) | NodeBB/NodeBB | 权限注册、插件默认、用户/群组载荷、模板及分类复制；前缀键、插入顺序、默认type与按类型复制全链一致 |
| [S22 · Ansible：委派与循环只计算一次](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_ansible__ansible-42355d181a11b51ebfc56f6f4b3d9c74e01cb13b-v1055803c3a812189a1133297f7f5468579283f86/instruction.md) | ansible/ansible | TaskExecutor、Worker、VariableManager与Task父层次；依赖构造、原对象合并、去旧缓存和弃用提示跨阶段对齐 |
| [S23 · Ansible：迭代器与线性策略的阶段顺序](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_ansible__ansible-d6d2251929c84c3aa883bad7db0f19cc9ff0339e-v30a923fb5c164d6cd18280c02422f75e611e8fb2/instruction.md) | ansible/ansible | PlayIterator、多host锁步、roles/blocks/rescue/always；清除伪noop但保留失败恢复和规范阶段顺序 |
| [S24 · Element：广播状态贯穿事件/缓存/UI](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_element-hq__element-web-fe14847bb9bb07cab1b9c6c54335ff22ca5e516a-vnan/instruction.md) | element-hq/element-web | 状态事件确认、Recording模型、Store、视图与barrel导出；监听/卸载、默认状态、同步停止和UI响应全链一致 |
| [S25 · Flipt：审计配置到RPC/OTel/Sink全链](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_flipt-io__flipt-e50808c03e4b9d25a6a78af9c61a3b1616ea356b/instruction.md) | flipt-io/flipt | 配置及默认值、事件编码、中间件、Exporter和所有Sink；成功变更恰有一条事件；默认值、字段名和非变更请求需兼容 |
| [S26 · Flipt：独立Evaluator并迁移服务调用](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_flipt-io__flipt-f1bc91a1b999656dbdb2495ccb57bf2105b84920/instruction.md) | flipt-io/flipt | 存储/规则接口、SQL读取、typed条件、分桶与Server；删除旧Evaluate职责、注入新接口并保持排序/边界/结构错误 |
| [S27 · Vuls：OVAL修复状态贯穿检测报告](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_future-architect__vuls-ef2be3d6ea4c0a13674aaab08b182eca4e2b9a17-v264a82e2f4818e30f5a25e4da53b27ba119f62b5/instruction.md) | future-architect/vuls | 匹配返回元组、模块流身份、多个发行版与gost退役；新增fix-state逐调用传播；旧族行为和依赖API必须兼容 |
| [S28 · Teleport：wal2json消息到后端事件](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_gravitational__teleport-005dcb16bacc6a5d5890c4cd302ccfd4298e275d-vee9b09fb20c43af7e520f57e9239bbcf46b7113d/instruction.md) | gravitational/teleport | SQL取流、列值类型、identity回退、动作到后端事件；缺列/NULL/空值不可混淆；改键必须先delete后put |
| [S29 · Teleport：并发多游标扇出缓冲](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_gravitational__teleport-bb562408da4adeae16e025be65e170959d1ec492-vee9b09fb20c43af7e520f57e9239bbcf46b7113d/instruction.md) | gravitational/teleport | 固定环、慢游标积压、可取消读取、时钟和GC回收；每游标顺序、wait计数、宽限期和关闭/回收不可相互破坏 |
| [S30 · OpenLibrary：类型化增量索引与批次状态](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_internetarchive__openlibrary-322d7a46cdc965bfabbf9500e98fde098c9d95b2-v13642507b4fc1f8d234172bf8129942da2c2ca26/instruction.md) | internetarchive/openlibrary | works/authors/books更新器、预加载、重定向与Solr提交；孤立版本、删除/重定向次序、状态隔离和错误回执一致 |
| [S31 · Navidrome：播放偏移贯穿所有流式调用](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_navidrome__navidrome-812dc2090f20ac4f8ac271b6ed95be5889d1a3ca/instruction.md) | navidrome/navidrome | API/MediaStreamer/FFmpeg接口、全部生产调用与命令模板；offset原样传递、零值兼容和参数位置；不修改官方维护的mock |
| [S32 · Proton Mail：外部加密与过期设置重构](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_protonmail__webclients-6e1873b06df6529a469599aa1d69d3b18f7d9d37/instruction.md) | protonmail/webclients | Composer状态、表单、菜单、保存往返、快捷键和FeatureFlag；28天与7天默认不串用；保存不丢密码，移除同步清过期 |
| [S33 · Qutebrowser：抽离Qt参数与环境初始化](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_qutebrowser__qutebrowser-de4a1c1a2839b5b49c3d4ce21d39de48d24e2091-v2ef375ac784985212b1805e1d0431dc8f1b3c171/instruction.md) | qutebrowser/qutebrowser | 配置载入、应用入口、Qt版本分支、argv和环境；参数有序、版本映射和环境变量必须在Qt启动前生效 |
| [S34 · Tutanota：桌面下载/打开与失败清理](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_tutao__tutanota-51818218c6ae33de00cbea3a4d30daac8c34142e-vc4e41fd0029957297843cb9dec4a25c7c756f029/instruction.md) | tutao/tutanota | 网络Client、request/response/文件流、临时文件和Shell；监听/关闭/清理恰一次；可执行文件确认与错误传播保留 |
| [S35 · Tutanota：集中熵管理并迁移Worker调用](https://github.com/scaleapi/SWE-bench_Pro-os/blob/66f92766bba642462d4bbe5479e83f91f9211862/v2/tasks/instance_tutao__tutanota-f3ffe17af6e8ab007e8d461355057ad237846d9d-vbc0d9ba8f0071fbe982809910959a6ff8884dbbf/instruction.md) | tutao/tutanota | Facade/DI、Login、Collector、Worker启动与旧RPC移除；位数/时间双门槛、leader/登录条件、失败处理和全部消费者一致 |


### 3 Terminal-Bench 4.0：14题

**简单**

| 编号／公开任务 | 项目／范围 | 结构预评级依据 |
|---|---|---|
| [T01 · 漂移告警流水线修复](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/embedding-drift-monitor/instruction.md) | TB软件工程任务 | 统计/距离工具、窗口与告警去抖；校准正常场景、真实漂移和跨窗口告警状态 |
| [T02 · 会话事件窗口修复](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/session-window-debug/instruction.md) | TB软件工程任务 | 会话合并、晚到事件、水位线与清理；按DESIGN保持全局最小水位线、已触发会话保留和晚到合并 |

**中等**

| 编号／公开任务 | 项目／范围 | 结构预评级依据 |
|---|---|---|
| [T03 · 航运调度多模块修复](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/cargo-flight-dispatch/instruction.md) | TB软件工程任务 | navigation、aircraft、dispatch与四类业务数据；统一角度/单位、燃油/载重/风限制和单环行程 |
| [T04 · 发布流水线与公开来源策略](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/bun-sourcemap-leak/instruction.md) | TB软件工程任务 | 构建脚本、客户端/服务器产物、source map和manifest；保留运行行为与公开映射，同时移除私有来源和路径 |

**难**

| 编号／公开任务 | 项目／范围 | 结构预评级依据 |
|---|---|---|
| [T05 · 跨CSV一致且受内存约束的匿名化](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/data-anonymization/instruction.md) | TB软件工程任务 | policy、历史记录、有效期合并与跨租户链接；实体标识跨文件/传递合并一致；行列顺序、seed与64MB约束保留 |
| [T06 · 多来源知识图谱及查询一致性](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/ontology-kg-querying/instruction.md) | TB软件工程任务 | 三类本体、成员提交、统一图与两个SPARQL查询；来源三元组保留、最新冲突优先、实体去重和跨关系条件一致 |
| [T07 · 恢复训练数据链路](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/pretrain-shard-corruption/instruction.md) | TB软件工程任务 | 数据分片/索引、训练入口、检查点与验证损失；恢复准确原始样本，不能换配方/删样本/改入口或伪造结果 |
| [T08 · 修复流式推理协议](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/vllm-deepseek-streaming/instruction.md) | TB软件工程任务 | vLLM源码中的响应分段及工具调用输出路径；修复错误分段与tool-call JSON损坏，具体触发路径需调查 |

**超难**

| 编号／公开任务 | 项目／范围 | 结构预评级依据 |
|---|---|---|
| [T09 · 批量评测与逐样本语义保持](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/batched-eval-parity/instruction.md) | TB软件工程任务 | 提示构造、fewshot、评分/校准、生成停止、packed缓存与指标；多输入布局、精确schema、顺序与性能路径同时成立 |
| [T10 · 崩溃后数据可见性与压缩](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/mvcc-lsm-compaction/instruction.md) | TB软件工程任务 | 事故报告、C++ MVCC/LSM、崩溃复现与新增回归；修复可见性且保留真实压缩，不能永久保留所有旧版本 |
| [T11 · 统一提交与多账本原子更新](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/react-lead-form/instruction.md) | TB软件工程任务 | React表单、submitLead、schema/policy/calendar及多个输出账本；不可变审计、去重/提升、时间和失败回滚同时成立 |
| [T12 · 黑盒生产行为与审计重建](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/risk-scorer-replay/instruction.md) | TB软件工程任务 | 迁移说明、运营摘要、manifest选材、探针和CSV/JSON/SQLite；以探针确定行为后独立实现；最终不能依赖诊断二进制 |
| [T13 · VBA业务应用等价迁移](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/vba-userform-port/instruction.md) | TB软件工程任务 | 表单/代码/表数据/工作簿元数据到React/FastAPI/SQLite；保留校验、计算、增删保存和表单行为，满足启动合同 |
| [T14 · WAL并发提交和恢复次序](https://github.com/harbor-framework/terminal-bench/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/wal-recovery-ordering/instruction.md) | TB软件工程任务 | 提交、segment持久化、crash snapshot、恢复与读取接口；全局持久前缀、去重/缺口、深拷贝和并发可见性同时成立 |

### 4 特别保留的判别场景

- **跨层一致性**：S21权限类型从注册一直传到API、模板和复制；S22委派依赖贯穿Task/Worker/变量管理；S31播放偏移贯穿全部生产调用。
- **状态与故障恢复**：S23多host失败/rescue顺序，S16慢审计流的恢复和关闭，T10 MVCC崩溃、T14 WAL持久前缀。
- **持续的业务约束**：S32加密/过期/保存往返，T11表单到多账本原子更新，T13跨技术栈保留旧业务行为。
- **调查和证据累积**：T12生产黑盒探针与独立重建，T07恢复准确训练样本，T06多来源本体合并和直接查询。

这些是希望观察的行为，不是额外发给Agent的提示。只将原官方任务指令送入任务，目录、分级、审查意见和未来配对结果不能挂进Agent工作区或追加到system/user提示。

### 5 排除与候补

主清单没有纳入以下已审查候选，原因不是被测系统的解题表现：

| 候选 | 处理理由 |
|---|---|
| SWE Vuls `36456cb1` WpVulnDB searchCache | 实际仅要求map查找helper，标题中的缓存不能证明长程复杂性 |
| SWE Proton `c8117f44` public-session恢复 | 需求主体收敛为localStorage编号工具函数，标题强于实际任务边界 |
| SWE Navidrome `29bc17ac` typed cache | 主要验收面为新的局部缓存接口；没有把描述中的全库迁移愿景当作已要求的范围 |
| SWE Qutebrowser `cf06f4e3` live stderr | 同一stdout单块场景的消息次数要求存在2/3次歧义；不在本轮修题或查看隐藏测试来猜官方解释 |
| SWE Proton `e65cc5f3` mailbox retry | 需求和接口描述对stale时的in-flight状态不一致；本批优先选择更清楚的公开合同 |
| TB freight-dispatch-shift、intrastat-meldung、nextjs-performance等 | 很有长程工作流价值，但现有多容器权限准入未完成；本轮不突破已确认边界 |
| 纯证明、专业化学/音乐、GPU训练与科学仿真 | 不仅因为题难就纳入；专业推断或计算时间可能掩盖记忆管理差异 |

冻结5个候补：SWE各档1题（RS01 NodeBB字段投影、RS02 Navidrome SSE隔离、RS03 Ansible Worker IO、RS04 Flipt OCI/ECR），TB难档1题（RT01 SGLang流顺序）。完整ID、证据哈希、预评级和单档顺序在机器清单。TB简单/中等/超难档暂不凑候补：没有符合当前长程目标且审查充分的同档候补时，模型前暂停该槽位并对齐新候选，不自动塞入专业推断题，也不跨集合/跨档替换来保住数量。

只有镜像/官方控制等模型前准入失败才能按同集合、同档顺序替补；公共软件缓存或双变体加载失败先修公共接线，不换题。替补发生前须留准入失败证据并生成新的实际计划版本。模型开始后，低分、长时间或未触发记忆机制都不能成为替换理由。旧运行始终保留。

### 6 与实验执行系统的衔接

`experiments/subsets/catalogs/long-horizon-49-v1.yaml` 是已冻结的审查清单，**不是当前CLI的Subset输入**。旧输入仅接受count/seed/资源包络；把count改成35或14仍会抽出别的题，不能冒充本清单。按用户本轮确认，本次只提交选题、完整ID/哈希和设计，不修改运行器；后续执行接线必须显式消费这份清单并逐项校验，不能通过搜索seed凑题。

执行前仍需官方Dockerfile/镜像构建与冻结、oracle=1/nop=0、全部变体软件缓存及完整Pi加载预检；SWE保持离线解题/捕获补丁/全新沙箱重评分，TB保持原verifier、资源、网络和8小时单题时限。49题静态入选不代表49题已通过这些准入步骤，也不代表所有镜像可同时放入本机120 GiB磁盘。

完整一次配对是98次模型解题，另有官方控制、软件预检和70次Pro补丁重评分。按官方单题上限机械相加，仅解题Agent的串行上限是282小时20分（并非预计实际时长）；原20美元/8小时冒烟窗口已结束，本清单不包含新的付费授权。实际运行需另定分批计划、费用和整体时限，不缩短官方单题预算，不为赶进度抽掉超难题。

后续成绩分任务集、分四档报告，并保留计划行、基础设施失败和缺失；SWE历史3题另列。21题超难存在两边均失败的地板风险，不能只看总通过率解释记忆能力。即使结构上适合长程，若轨迹没有足够的历史/状态压力，本轮只能说明该工作流上的代理表现，不能声称证明了长窗口/回读机制收益。确认实际压力的诊断不能用于事后挑成功样本。

### 7 证据与校验

来源继续锁定TB `452bf305c6daa62fc59061d22133a7cbc7c1572e` 与SWE `66f92766bba642462d4bbe5479e83f91f9211862`。清单保存49个主选和5个候补的完整任务ID、解题/评分资源、公开指令SHA256、全目录SHA256、证据位置、人工依据和准入状态；未复制隐藏测试、参考解或完整官方题目正文。`upstream_task_verifier_mode` 仅记录Harbor对上游task配置的解析：不能拿SWE的默认shared值覆盖已经确认的“解题关闭评分、独立Job全新沙箱重评分”协议。

校验结果见 [静态核对记录](selections/long-horizon-49-v1.audit.json)。校验只读现有源码数据，逐项核对ID唯一性、比例、11仓库、解题/评分资源包络、官方协议字段、源哈希和旧题标注；不构建镜像、运行模型或改评分。静态校验与真实环境/评分验收严格分开。


2026-10-28执行授权补记：用户随后已授权本清单全部49题双变体执行，整批20美元/48小时止损、专用Colima扩容及10并发峰值目标。选题冻结时的“未运行”描述保留其历史含义；运行器schema2按本清单哈希直接执行，不采用随机抽样。任务级准入失败保留原槽位并继续其他合格题，详见[执行方案](LONG_HORIZON_49_RUN_PROPOSAL.md)。
