# RSI 原题选择

## 2026-11-21 共用题池

原80题逐题保留来源与历史分组，补充原题另记来源。冻结参考插件的实测成绩决定通过组与未通过组，原生 Pi 单列。候选的三个批次分别抽 4、4、8 题，每批两组各半，同一候选内按题目身份去重。新节点优先抽近期少抽的题。每批相对参考插件净多过至少 1 题后进下一批。[现行技术方案](../RSI_TECHNICAL_DESIGN.md)

缺结果或只有基础设施证据的题先补插件标定。有正式时限终态的题保留实际耗时、有效尝试次数及官方评分。仅因环境问题耗尽预算的题进入环境清单。补题时沿用既有通过和有效失败的原件。

## 历史选择 v2（20 回归、20 训练、40 独立验证）

2026-11-14 用户已确认新的80题结构；设计总则见[RSI技术方案v3](../RSI_TECHNICAL_DESIGN.md)。本节为新版本选择规范，后文旧200题选择记录及[旧100题协议](RSI_100_ACTIVE_TIME_DESIGN.md)保留各自历史身份。本次只改文档，未选择、下载、运行或清理任何题目，旧wave27继续停止。

2026-11-15 用户补充确认：本次初始双臂基线中的20道回归与20道普通验证，必须从旧实验已有原生／插件正式完成结果的题目中选取，优先双臂均通过、相对简单且功能多样的40道不同原题，直接登记对应旧正式证据，不再运行这些题的准备验收或模型测试。新清单独立保存分组、精确原题／版本、双臂结果及原运行协议引用，旧账本和原始成绩不改写；历史引用与本轮新执行分开标记。普通验证逐题材料仍仅供维护／独立评测侧。本条只规定初始基线复用，不免除未来新候选按审批协议运行回归与独立验证；旧题成绩仍不得充作新20道难训练分数。

## 新题集与清单隔离

| 新集合 | 固定数量 | 用途 |
|---|---|---|
| 功能回归 | 20道简单题 | 基础功能与防退化门禁，审批后先执行 |
| 训练 | 20道难题 | 对进化Agent可见；固定同一组题反复研究和改进 |
| 独立验证 | 20道普通＋20道难，共40题 | 独立评测端保管，验证评分及逐题证据不回流进化Agent |

三组使用精确原题身份和完整内容摘要去重，互不重叠；回归与验证不得共用题目。新清单必须有独立版本、集合摘要、来源、原题路径／哈希、分组和资格证据，不能覆写旧`rsi-100-v1`／`rsi-200-v1`或把20／80直接解释为新20／20／40。新旧清单分开保存不代表已经决定具体原题是否可复选；新清单和标定尚未完成，任何旧分数均不得充作新训练标定。

每题沿用未修改的权威benchmark原题、资源和官方裁判，来源日期及硬件要求单列证据；磁盘空闲不足仅阻断资源准入，不能因此降配、缩分母或静默换题。元数据easy／medium／hard或专家时间代理只作来源标签，不能替代实测难度与功能资格。

## 两组难题各自的入选标定

先固定标定主体版本、候选池／选择顺序和评测协议，再进行题集入选标定。训练20难和验证20难须**分别**在每题最多三次有效尝试、首次通过即停的口径下低于50%，即各自最多9/20；不能合并为最多19/40，也不能把单次失败当作三次规则下未通过。标定结果和身份必须完整可追溯，不能据后续候选成绩重选难题。

这是**题集入选难度门槛，不是晋升阈值**。普通验证组和简单回归组的具体入选、功能资格标准仍须冻结，本文不另加50%门槛。网络／环境故障、资源等待及用户中断不占有效尝试，不能当能力失败或通过；全部20题保留分母，未完成或HOLD须先解决，不能删除后计算合格。

新训练集上须标定初始插件基线，并为后续候选保留同协议比较证据。旧题分、旧初始插件100题成绩、静态选择、oracle／NOP或环境准备通过均不等同于新训练基线。

## 可见性与反过拟合

训练题和获准训练失败证据可用于主动调研、搜索和机制分析；独立验证题库、评分、逐题证据、答案和裁判输出由评测端保管，不进入进化Agent的检索、上下文、缓存、共享经验或图摘要。选题、标定与访问暴露历史须留档，不能靠换题ID或改清单名隐去已经发生的暴露。

题ID、来源／数据集和仓库可用于去重、来源审计与账本关联，**不得作为候选针对性行为或参数的选择条件**；题干指纹、输入／答案特征同样禁止。禁止把针对单题或数据集的过拟合包装为通用规则。每项改动必须提供失败证据→通用Agent不变量→最小反例／排除竞争解释→机制改动→跨题族迁移、消融、防退化证据，分数上涨不替代通用性审查。

## 与审批及晋升的关系

固定新20题训练通过率严格大于当前最佳已验证插件基线，且通用性审查通过，才可提交绑定候选／基线／协议的审批；批准后先20题回归，再独立40题验证。回归失败后的修改必须重过训练和审批。只有验证通过的候选能登记真实收益和晋升；其他候选完整存档，可作父节点，比较基线不随父节点降低。

验证“普通组不退化、难组严格改善”仅为**待冻结建议默认值**，不是用户已确认的判定规则；回归判据、初始基线的已验证资格、验证复核／重验等同样须在正式协议中明确。文档不创建新可执行catalog或启动资格。

---

## 旧200题选择历史（以下标题和“当前”均指各自记录时点）

### RSI 原题选择 v1

**动态状态更新（2026-11-08，14:17 UTC恢复结束后）：** 当前4题已完整环境验收；原生真实结果为3通过、1题能力失败耗尽、196未启动，完整200基线未完成，插件真实尚未运行、基础双侧0/40。详见[最新真实恢复结果与结算](RSI_EXPERIMENT_RESULT_2026-11-08.md)。本文件为静态审计／选择规范，后文0/200、尚无完整准备等属于此前时点快照，不代表本次动态状态；历史正文、原题数据及分组规则未改。


#### 范围与状态

`experiments/subsets/rsi-200-v1.json` 固定 200 道未修改的官方原题：40 道基础回归**候选**、160 道能力题，身份不重叠。目录只保存来源、路径、标签、哈希和分组，不复制或改写题面、环境、答案、测试脚本，不增加判定 hook。

40 道候选尚未经过 Pi 原生和完整插件的配对资格验证，不能称为“两者都能通过的基础题”。只有在冻结的模型、宿主、插件和尝试规则下两边实际通过，才能进入正式回归门禁。元数据难度、选择成功、镜像可构建或离线单测通过均不构成资格证据。若候选未通过，应另行冻结替补清单并重新验证，不得运行中静默更换题目。

此文件属于实验控制面的私有输入，不得整份注入进化 Agent。被测 Pi 每次仅接收当题的原始输入；裁判、答案及能力题全集不得进入其上下文。

#### 当前清单（2026-11-08，取代后文历史数量）

本节及[逐题审计](RSI_TASK_AUDIT_2026-11-08.md)为当前状态；后文初始选择和2026-11-07替换保留为历史，不代表现行题单。

- 当前为46道Terminal-Bench 4＋154道SWE Pro V2：基础18＋22＝40，能力28＋132＝160。
- 根据完整逐题审计，从能力集移除存在官方裁判异常假通过风险的html-js-filter，恢复takens-embedding-lean。该次替换保留其他199条完整题目记录和分组。磁盘大小不再用于筛选，Takens的原始100GiB重叠声明只作为运行准入限制，不是实测占用。
- 随后将能力slot的element-web fe14847替换为同仓库、同medium标签的776ffa原题：旧oracle原始Jest为108/108，但负耗时后缀造成官方所需名称只匹配107项。新题保留官方Jest JSON裁判，未修补原题；本次其他199条对象完全不变，全部数量及覆盖不变。该次排除项为20，其中TB19、SWE裁判完整性1。新题原修复日期2022-10-13，benchmark逐文件新增日期2026-09-22，满足A口径。
- TB类别为Science13、Software11、ML8、Hardware5、Media4、Operations3、Security2；难度代理为easy17、medium168、hard15。难度不表示模型通过概率。
- 近1.5年按benchmark题目新增或实质更新判断，截止2025-05-08；原问题／修复日期另记。全部200题满足这个日期口径，原件哈希已核验，但实际环境和原生／插件能力资格仍待逐题验证。
- 固定TB66题中的20项当前排除原因是8项明确硬件不满足、10项当前多容器适配未接纳、1项裁判完整性风险、1项本机原裁判可靠性失败；连同SWE裁判完整性1项，合计排除21项，不能全部称为硬件不兼容。

现行清单规范化摘要：`f41ff5b844ca30889d64bf361fff630d6ddb7ca8847230a7a2533d302c342d82`。原题集合摘要：`01c53b6fefa1e63872510372a9743ee058487c113896d0e89820fff364b84542`。详细替换来源、逐题更新日期、环境证据和实际验收状态见[完整审计JSON](audits/rsi-200-2026-11-08.json)。

#### 固定上游

- Terminal-Bench 4.0：`https://github.com/harbor-framework/terminal-bench.git`，commit `452bf305c6daa62fc59061d22133a7cbc7c1572e`，原题目录 `tasks/`。官方版本介绍：https://www.tbench.ai/news/terminal-bench-4-0 ，官方基准列表：https://www.tbench.ai/benchmarks 。
- SWE-bench Pro V2：`https://github.com/scaleapi/SWE-bench_Pro-os.git`，commit `66f92766bba642462d4bbe5479e83f91f9211862`，原题目录 `v2/tasks/`。

来源配置沿用 `experiments/suites/terminal-bench-4.yaml` 与 `experiments/suites/swe-bench-pro-v2.yaml`。每条记录的 `original_path` 相对其固定 checkout 根目录；`sha256` 使用现有 `suites.task_digest`：按相对路径排序，将文件路径、NUL 分隔符、文件 SHA-256 二进制摘要追加到整体 SHA-256。包含题目树内所有普通文件，拒绝符号链接，不仅检查题面。

#### 数量与环境筛选

- 回归候选：Terminal-Bench 20，SWE-bench Pro 20。
- 能力题：Terminal-Bench 32，SWE-bench Pro 128。
- 共计：Terminal-Bench 52，SWE-bench Pro 148。

固定 TB4 checkout 有66题。当前 CPU、单容器运行适配范围排除14题，原题保持原样：

- 3题要求 GPU：`fp8-rmsnorm-gemm`、`jax-speedrun-gpu`、`math-eval-grader`。
- 11题有原生 Compose sidecar：`ctr-optimization`、`cumulative-layout-shift`、`freight-dispatch-shift`、`heat-pump-warranty`、`intrastat-meldung`、`kv-live-surgery`、`legacy-utility-triage`、`live-database-cutover`、`medical-claims-processing`、`nextjs-performance`、`payments-pipeline-fix`。其中包括 service 网络共享、多系统 sidecar、浏览器服务及 `SYS_PTRACE` 权限要求。当前适配器未接纳这些配置，不以删除 sidecar 或降配方式冒充原题。

筛选代码同时拒绝非 Linux 与多 step 原题；当前 TB4 固定来源没有多 step 题。SWE 来源642题，从中选择148题。选择不代表镜像已经下载、平台兼容已验收、所有运行依赖已经安装或资源容量足够；这些由环境准备与运行准入另外验证。

TB4仍保留7类：Science14、Software13、ML8、Hardware5、Security5、Media4、Operations3。Operations从原始9题减至3题，涉及业务系统 sidecar 的情境暂不覆盖，不能称为完整 TB4 排行榜成绩。SWE按原题的11个仓库分层，合计18个场景标签；仓库分层只是覆盖代理，不表示每个仓库是一个独立业务领域。

#### 难度与场景来源

SWE Pro V2 上游 `task.toml:metadata.difficulty` 在当前来源中统一为 `medium`，直接保留，不能解释为实测中等通过率。场景由上游 `category` 与原始实例 ID 中的仓库名组合，例如 `debugging/ansible__ansible`；提取到 commit SHA 前的完整仓库前缀，保留 owner 中的连字符。

TB4没有统一 `difficulty` 字段，使用上游 `metadata.expert_time_estimate_hours` 作透明的**选择难度代理**：

- easy：专家时间估计 ≤2小时。
- medium：>2且≤6小时。
- hard：>6小时。

这不是官方难度分类，也不是 Pi 或插件通过概率。每题保留 source/derived 标记、原字段、原值和转换规则。总体标签分布为 easy18、medium166、hard16。TB4场景直接取上游 `metadata.category`，不增删任务内容。

#### 可重复选择算法

种子固定为 `memweave-rsi-200-v1`，算法标识为 `sha256-stratified-round-robin-v1`：

1. 核验每个来源 checkout 的 HEAD 等于完整40位 commit，且无跟踪修改或未跟踪文件。
2. 枚举未修改原题，按上述环境条件记录排除原因；要求原始 `instruction.md`、`task.toml`、`tests/test.sh` 存在。
3. 按 `(scenario, difficulty)` 分层。层内按 SHA-256(`seed + NUL + suite_id + NUL + task_id`) 升序。
4. 按分层键字典序轮询抽取。每来源前20题为回归候选，其余进入能力题，TB4总配额52、SWE总配额148。
5. 固定两个集合，不根据模型表现挑能力题或事后改变比例。不宣称是全量源分布的随机无偏样本。

#### 离线接口与验证

`memweave_eval.rsi_catalog.load_catalog(path: Path) -> dict` 读取JSON，检查schema、未知字段、精确40/160数量、身份唯一和不重叠、来源URL、完整commit、路径及多场景/多难度覆盖。它不读取原题、运行测试或声明运行资格。

`validate_catalog(catalog: dict, cache: Path | None = None) -> dict` 返回数量、分布、规范化清单摘要与资格状态；传入cache后额外验证原始checkout、每题完整树哈希、标签和元数据来源。不传cache时 `sources_verified=false`，只检查结构。

`build_catalog(cache: Path, suite_paths: list[Path]) -> dict` 从固定、干净的本地原题缓存重建清单。不会下载、执行原题、调用模型或读凭据。调用方可将结果作为JSON保存，使用 `sort_keys`与紧凑JSON计算的摘要不依赖磁盘缩进。

测试入口：`PYTHONPATH=experiments/src experiments/.venv/bin/pytest experiments/tests/test_rsi_catalog.py`。测试创建离线、无害的临时Git来源，验证确定性、数量、分离、来源/内容篡改、路径逃逸、未知注入字段、错误资格声明和缺失缓存。测试不访问真实模型、Docker、网络或用户私有配置。真实缓存的200道原题完整性已另行核验；未运行这些题的真实模型测试。

#### 2026-11-07 本机资源替换（取代上述初始数量）

原始清单摘要为 `fcc2626c1b70f263fb28af4664bcb03b8873c65276090285d3e7e3fcfdae9da7`。按本机冻结资源检查排除5题，不降低原题资源。保留195题及原split；以同一确定性排序的SWE第149–153题依次填补原清单中的空位。当前47TB+153SWE：回归18TB+22SWE，能力29TB+131SWE。排除共19题。

整体保留7个TB类别和三档难度，easy18/medium168/hard14。Security失去medium覆盖，仅剩3道easy；Science减至12题、Software减至12题。没有声称基础题实测合格。固定资源排除不是按每次机器空闲量动态换题；清单身份以完整内容摘要为准，旧摘要的基线不能用于新题集。

- regression：`wdm-design`（SHA-256 `ce6a9809706cea24df2f83e7383679ac396c6ef160c78696dd9d18bdb552913d`）→ SWE `instance_future-architect__vuls-999529a05b202b0fd29c6fca5039a4c47a3766bb`（SHA-256 `0238c537af03bb4de8e0557ac91dd23a52893f97bd15cbc781ef850849f567c6`）。原因：actor+verifier require 16 CPU; frozen local budget is 11 CPU。
- regression：`shadow-relay`（SHA-256 `53e0b67b2b78aeabc99e8f297d061ebcadb06e65ec245f8e7387bfef1ee71a9b`）→ SWE `instance_gravitational__teleport-2bb3bbbd8aff1164a2353381cb79e1dc93b90d28-vee9b09fb20c43af7e520f57e9239bbcf46b7113d`（SHA-256 `07ede1b7d89ad5afba31840ebc07747d03df991d367290b93621595233d3f3af`）。原因：actor+verifier require 16 CPU; frozen local budget is 11 CPU。
- capability：`formal-crypto`（SHA-256 `b0bfa290dd184712e362e1641a87d41b0ca91c474d1105ec7a3bae1371b476ae`）→ SWE `instance_internetarchive__openlibrary-7bf3238533070f2d24bafbb26eedf675d51941f6-v08d8e8889ec945ab821fb156c04c7d2e2810debb`（SHA-256 `3b6735212966baa9186aa4c0dd09d0817d4c7b30c1a0a5d616788a24bd88eba0`）。原因：actor+verifier require 16 CPU; frozen local budget is 11 CPU。
- capability：`distributed-dedup`（SHA-256 `75e03fd070a886772caa2aa90a04c5f3cbda9e0feb6e78edaa730fc1229a1929`）→ SWE `instance_navidrome__navidrome-6b3b4d83ffcf273b01985709c8bc5df12bbb8286`（SHA-256 `7a01bdaf3ad7f60695aeb0e3dbc987cda91902656f985dfd8eecdfdc246a915d`）。原因：actor+verifier require 16 CPU; frozen local budget is 11 CPU。
- capability：`takens-embedding-lean`（SHA-256 `bfca44d2b41b58579853adef3e3da66fe32286ccde87f4016eff804ab2a5047f`）→ SWE `instance_protonmail__webclients-01b519cd49e6a24d9a05d2eb97f54e420740072e`（SHA-256 `5c9829ec511deb44b7d9aa10b1137e9b8e7d462f4cf1402be354a14ea369d2e5`）。原因：original requires 100 GiB disk; frozen local budget is 79.22 GiB。

新清单规范化摘要：`de7d9d9e23753d9ec53d0f7992365185a749735f20b7b2c020bd5cd18fe9bff3`。200题完整原题哈希已核验，未执行真实模型测试。

#### 2026-11-08 Element原裁判完整性替换

精确替换：`instance_element-hq__element-web-fe14847bb9bb07cab1b9c6c54335ff22ca5e516a-vnan` → `instance_element-hq__element-web-776ffa47641c7ec6d142ab4a47691c30ebf83c2e`。仍在capability / debugging/element-hq__element-web / medium原slot，非按模型成绩择优。776ffa原SHA256为`a5606828ec92b08b50ac3b10d28ccb334a078d28f9d7710e477311e2dd446f92`。

原1CPU/4096MiB、linux/amd64及3000秒agent/verifier限制不变；仅静态符合本机预算，Rosetta、Jest worker/RSS、JSON输出及原oracle/nop仍须实测。磁盘10240MiB只报告，不作筛选。新题脚本未显式指定maxWorkers=1，不沿用仓库级笼统描述。

变更前清单规范化摘要`9afae452e293636daf2eac2f9ca912a151ed953262c90ced0f8eafaeb7cc2942`、原题集摘要`5e3e51e2b00311c22afa2ac03e143db9d3718a35060aeb8856cd3ca226a1b65e`保留。v4两题完成、React超时及随后独立oracle诊断通过均属于旧题单/旧评测源码；新题单必须重新核验完整准备，不迁移或改写旧store收据。

#### 2026-11-08 React原裁判可靠性替换（当前）

能力slot的`react-lead-form`精确替换为官方SWE Pro V2 medium原题`instance_NodeBB__NodeBB-be43cd25974681c9743d424238b7536c357dc8d3-vf2cf3cbd463b7ad942381f1c6d077626485a1e9e`（Topic Linkbacks）。原题SHA256：`fb070a6dbc0bae9ece45309de8f2dd741a37ee5d6af49e8e9caada4d32477bc0`。其他199条完整对象和顺序、40/160分组、17易/168中/15难不变；TB Software由12降至11、NodeBB由15增至16，七个TB类别及既有场景保留。该题覆盖浏览器backlink helper、设置、模板、本地化及topic/post生命周期；相较React表单构建，直接前端构建覆盖减弱，仍属前端相关全栈任务。

React最近四次同原题控制出现两次原900秒verifier挂起（v4首轮Vitest、v5第二轮Vitest），其间有通过。这里记录已观察的本机原裁判可靠性失败，不宣称全局损坏、硬件硬失败或Rosetta根因；没有进入Pi/model尝试。未改原资源、时限、测试或parser，不循环重试到通过。

NodeBB独立原oracle/nop各执行一次：104/104必需项通过、reward=1；98/104通过，恰缺6个F2P、reward=0。最初旁路观察误认Harbor egress sidecar为主镜像，原oracle已正常完成，后续仅取证纠正，没有重跑oracle。权威证据为`/Users/godice/.local/share/memweave-experiments/diagnostics/nodebb-linkbacks-original-controls-20261108T091408Z-b0943d1d/final-summary.json`及同目录ACCEPTANCE.md、oracle-reconciled.json、nop-continuation-summary.json、final-checksums.json。

原配置1CPU/4096MiB/10240MiB、linux/amd64、agent/verifier3000秒/build1800秒，Mocha JSON与同容器Redis均未改。磁盘不是选题过滤条件。缓存原图inspect.Id与官方OCI manifest为`sha256:9a949c3505b8b11e51d7613d4a50d4ea6f7759ca6be00937f4ff97af5d3a348f`；inspect.Size=900215099字节不是实际独占磁盘或下载量。该候补尚无软件payload、完整Pi/插件准备或真实模型成绩。

固定来源`66f92766bba642462d4bbe5479e83f91f9211862`；逐题文件新增commit`31a20c751b0bd56db6510ce7d4d3c269c5b7c72b`、日期2026-09-22T19:19:43Z符合A口径；原修复2021-09-29T16:26:15Z单独披露，不称近期缺陷。全部200原件和日期已复核。

前catalog文件/规范化/题集摘要依次为`0770b803362fa2a633d58ca579a98c1ba5c8c36eea8c7b9e62b682f396bb9509`、`f6c84d3f43a25638acb4f26bb5466173aee639f2a96777088373fbbd4be11132`、`75034f8ee5a1e7aab0939a6eaedcdc3859d3cab05a9aa4898dc41f6ab01912d8`；现依次为`ff8fdeacd03243bea38c4aaba588c1e32d78bd788f012fed93567298fb57431c`、`f41ff5b844ca30889d64bf361fff630d6ddb7ca8847230a7a2533d302c342d82`、`01c53b6fefa1e63872510372a9743ee058487c113896d0e89820fff364b84542`。验证策略数据`experiments/src/memweave_eval/rsi_selection_policy.json`摘要`4f86e7d353bdf89fd74058a37151e2d93d0371a08abe8ea3a7c6a82d0cb50103`，确定性builder与当前catalog完全相等。快照和199条不变证明在`/Users/godice/.local/share/memweave-experiments/analysis/react-nodebb-selection-20261108T110840Z`。

v5两题完成与React失败仍是旧catalog/旧评测源码证据；新身份完整准备未重验，不迁移旧收据，不把独立控制当正式prepared。模型基线0/200、基础双侧资格0/40不变；原html→takens、Element替换历史及全部旧store/诊断保留。

#### 已批准的一次性初始分组校准（2026-11-08）

以完整原生200和当前冻结插件全200的真实官方结果建立初始40/160，校准不用于晋升。双方通过交集中的40基础须至少覆盖两个场景及两个不同难度，确定性尽量均衡场景／难度／来源，以原catalog顺序作tie-break，报告实际覆盖及与原候选差异。不要求全部标签、交叉格或固定来源比例；不足就报告，不凑数，不因贪心遗漏误报不可行。交集数量／覆盖不足就报告，不凑数。冻结绑定双侧完整证据和前后catalog摘要，原200身份、原件及顺序不变，后续不按候选表现重选。当前数据不足，尚未生成或冻结合格40；历史候选分组保留直至证据齐全。详见[实验模块校准契约](RSI_EXPERIMENT_MODULE.md)。

40基础与剩余160能力均保留至少两个场景和两个难度，选择时同时验证补集，不把历史难度计数固定成配额；来源全覆盖不作硬门槛。若可行选择存在，不能因均衡贪心抽尽稀有标签而误报不足。
