# SWE-Marathon 本机并发对照与指标落地报告

2026-11-01。正式有效配对 `20261101T152354Z-726a528639`，原始证据位于 `/Users/godice/.local/share/memweave-experiments/runs/20261101T152354Z-726a528639/`。这是单题、单次、带共同进度询问的产品对照，不是官方榜单成绩，也不支持普遍提升结论。

## 实际结果

本次原生 Pi 完成原题，MemWeave 少通过 8 项 MVP 验证断言；双方 SIMD 全部通过。两组均正常终止，没有基础设施异常或预算耗尽，不为提高成绩重跑。新指标同时发现两组都在过程中改变过禁止修改的 `src/main.rs`，因此业务得分与行为检查分别保留。

| 项目 | 原生 Pi | 完整 MemWeave |
|---|---:|---:|
| 原题 binary reward | 1 | 0 |
| 原题通过/总断言 | 31,767/31,767 | 31,759/31,767 |
| MVP | 8,448/8,448 | 8,440/8,448 |
| SIMD | 23,319/23,319 | 23,319/23,319 |
| HTTP 尝试/已结算 | 335/335 | 350/350 |
| usage 对象 assistant 返回 R | 335 | 350 |
| Agent 墙钟秒 | 2,649.098327 | 2,479.426518 |
| verifier 秒 | 33.266613 | 39.433976 |
| Trial 总秒 | 2,702.151301 | 2,542.061654 |
| 输入 token，含 cache | 64,297,067 | 39,650,542 |
| 已确认 cache-hit 输入 | 64,145,024 | 38,587,648 |
| cache-miss 输入 | 152,043 | 1,062,894 |
| 输出 token | 199,119 | 163,193 |
| 按峰值价及确认缓存估算 USD | 0.669425844 | 0.746225688 |
| HTTP 耗时 p50/p95，秒 | 2.473/6.6267 | 2.103/5.878 |
| Pi 进程 CPU 秒，含自身不含全部子工具 | 153.601289 | 222.682412 |
| Pi 进程峰值 RSS，KiB | 659,648 | 910,644 |
| Docker 采样峰值内存，约 GiB | 1.050 | 1.204 |
| Docker 采样峰值 CPU，100%=一核 | 390.83% | 287.99% |

正式配对准备到完成为 2,884.977532 秒（48分04.98秒）。两解题Job的实际区间并集为2,702.406633秒；自动报表的`solve_job_seconds=5244.745231`是并发两Job耗时之和，不是墙钟。原生 Agent 区间 `15:27:04.849240Z–16:11:13.947567Z`；插件区间 `15:27:08.321828Z–16:08:27.748346Z`，实际重叠 2,479.426518 秒。不是先后运行。用户预算计时从 `12:40:38Z` 开始；正式流程在 `16:11:59.090430Z` 完成，耗时约3小时31分21秒，随后进行无模型验收、失败定位与文档收尾，未等到12小时用满。

插件本次输入总量较少，但 cache-miss 输入较多，费用增加 `0.076799844 USD`（约11.47%）。这是计费项的算术分解，尚不能将缓存差异因果归于某个插件模块。插件提前约169.67秒结束且未全过，不能据此称任务效率提升。两组均有2次 `length` 返回，均有1次正常 `stop`；其余分别332/347次 `toolUse`。无 error/aborted 返回或实际 compaction 事件。

## 固定条件与三题选择

原题来源：[abundant-ai/swe-marathon](https://github.com/abundant-ai/swe-marathon/tree/dd4d2bbc8d2ec8bb22fc4a4261d3b0c827faa2a4/tasks/wasm-simd)，提交 `dd4d2bbc8d2ec8bb22fc4a4261d3b0c827faa2a4`，task SHA256 `ce36e2b62e2d72ecade093b23fd9e02fd8e53392c1f66e705fba60188e65e458`。从官方未完成 Rust 骨架开始，未使用完成 checkpoint。原 instruction、verifier、测试和 Dockerfile 保持原样。

| 候选 | 原时间/资源 | 验证及长程依赖 | 事前取舍 |
|---|---|---|---|
| zstd-decoder | 5h；4CPU/16GiB/20GiB | C从零实现，RFC、熵表/重复偏移/字典；6公开及37隐藏样本 | 密封环境无解释器，现有 Python 额度准入不能直接复用，需额外实现，过程诊断较少 |
| rust-c-compiler | 10h；同资源 | GCC差分、约780样本，类型/ABI/代码生成长期依赖 | 10h不能为12h总期限保留可靠预检、故障重跑和收尾时间，另有x86 ABI/strace适配 |
| wasm-simd | 5h；同资源 | 骨架解码/执行/内存/控制流与约250条SIMD操作，分类规范断言和渐进验证 | 原环境已有Rust/Python；可复用准入、观测和隔离；参考解1/空解0已验证，选择它 |

三题比较在正式模型结果前固定。wasm与zstd同为5h，选择并非仅凭时长。完整事前说明见 [接线设计](MARATHON_METRICS_DESIGN.md)。

- 产品源码检查点 `207d746babd80b2381f04688d8d576c73429af30`，已保留此前State运行时余量、Rule及统计改动。归档 SHA256 `5ed61de2eb9d8096cf063fb519c4b54c8f63b09cd518c00e4d228d1bed92f022`。
- 实验首版本地提交 `7288e8b583ca4a7734cedae3b769e28af0e31059`；修复后正式冻结 `2312aacba04df4d4afbbe74d7cda7657e24ca179`。锁保存源码文件hash、包/题目/镜像/gold/config/软件对象；本次不推送或发布。
- 正式原题镜像 `sha256:6155c28fdbb32f944799fe39d18e80521583633efdab5d37c5c74ca285977749`；两组使用其同一运行时缓存镜像。早期免费构建39fb…不是最终冻结镜像。只复用软件和原始镜像，不复用第一轮解题overlay、State或Session。
- Harbor0.24.0、Pi1.4.0、Node24.22.0，Mac上本机Colima/Docker，linux/amd64仿真；每组4CPU、16GiB内存、20GiB磁盘，原题Agent上限18000秒、verifier1200秒。本次实际约41–44分钟，不声称完成了5小时或多会话长期记忆验收。
- 两组 `deepseek/deepseek-flash`、thinking disabled、请求显式输出上限16384。实际回包model为`deepseek-flash`；官方当日目录路由为DeepSeek-V4.1-Flash-1017，不把别名回包当作不可变权重证明。
- 原生为完整Pi默认System/4原生工具、无记忆业务、自动压缩开启；插件为完整候选包、完整Rule/16工具、自动压缩关闭。请求中Rule计数分别始终0/1，无未替换模板。两组实际均未压缩。这是原生产品基线，不是同窗口移除State的机制消融。
- 每组第80个usage返回后只发送一次共同公开steer：“请简短汇报进度，然后继续完成刚才的任务。”不重述约束、不提供答案。两个工作区、Session、记忆、认证均隔离，未向一组暴露另一组产物或金标。

正式前同一镜像参考解31,767/31,767、reward1；空解1,931/31,767、reward0，均无异常。原镜像里`if.json`、`simd_narrow.json`缺失，两组与控制均相同；保持原评分分母31,767，不补题，也不宣称覆盖整个WebAssembly规范。

## 插件实际State指标

R是Session内usage为对象的assistant返回，含零占位、error/aborted的定义不变；本轮实际无后两类。HTTP尝试独立来自最终传输边界。本轮335/350刚好与R一致，不将这种巧合推广到重试或compaction。

| 指标 | 实际值及口径 |
|---|---|
| state_append | 尝试11，成功10，失败1，未知0；成功率90.9091% |
| 回执/真实提交矩阵 | 成功且提交10，错误且未提交1；其余0，未知0 |
| 新增F/D / 当前有效F/D | 24 / 24；真实JSONL落地op_id去重，不把10个批次当24个事件；Goal不计入 |
| F/D密度 | 24/350=0.0685714，约1:14.58，落在用户参考闭区间0.05–0.10，无比例预警 |
| 成功写批次所在R位置 | `[8,30,103,137,177,188,200,240,311,343]` |
| 内部间隔 | `[22,73,34,40,11,12,40,71,32]` |
| 均值/总体CV/最大内部间隔 | 37.2222 / 0.568467 / 73次返回；首段8、尾段7 |
| 同返回合并后版本 | 与本轮原批次间隔相同；无同返回多批 |
| 其他写工具 | task_create 1/1成功；modify_fact/update_goal/state_remain均0次，成功率N/A |
| 实际State交付 | 347个请求含State版本/hash，最初未建Task的请求另列；不是“模型采用率” |

唯一追加失败是`items.2`多出`T1`属性，Pi schema拒绝；不是长度失败。没有为改善指标修改被测答案，也不将本题成功率与旧49题审计作因果对比。全部成功State写入都发生于终答前，证明存在过程记录；这不证明24条都值得记。CV没有预设优劣阈值，低CV与目标密度均不能证明记忆质量。

原生没有State能力，State专属成功率、密度和均匀度为N/A，不当0分。缺历史HTTP轨迹仍unknown；新HTTP统计和Session-only字段分列。收尾仅澄清Markdown中旧“请求数未知”的说明，评分定义和本轮JSON数值未变。

## 工具与行为检查

| 工具 | 原生错误/尝试 | 插件错误/尝试 |
|---|---:|---:|
| bash | 12/321（3.7383%） | 12/351（3.4188%） |
| write | 2/15（13.3333%） | 2/4（50%） |
| edit | 0/1 | 0次，N/A |
| read | 0次，N/A | 0/2 |
| state_append | N/A | 1/11（9.0909%） |
| task_create | N/A | 0/1 |

以上是原生isError回执统计，包含参数错误及业务测试失败，不直接等同基础设施缺陷。两组使用工具的机会不同，不据低样本write比率或bash差值下插件可靠性因果结论。执行耗时p50/p95、错误诊断类别和未知数保留于JSON；未执行的schema拒绝没有durationMs，不补0。

| 冻结案例 | 原生 | 插件 | 证据与边界 |
|---|---:|---:|---|
| 保护spec.rs/main.rs字节不变 | 0 | 0 | 初始hash均匹配，之后main.rs发生变化；原verifier评分前恢复原文件，不抹掉过程中违规 |
| 仅允许serde/serde_json依赖 | 1 | 1 | 每个工作区检查点的Cargo解析与依赖集合 |
| 存在公开规范测试全过记录 | 1 | 1 | 本地公开测试输出；不是最终全套正确性的替代，保护文件失败也须同时看到 |
| 早期Cargo失败的来源关联保留代理 | N/A | N/A | 本题未触发指定的早期manifest失败；不拿任意失败冒充触发 |
| 原指令驱逐后的State保护与动作 | N/A | 0 | 插件实际驱逐后150个请求，后续源代码改变且main.rs保护失败；State表达投影前后均unknown |

插件首次确认驱逐在`15:47:58.155Z`，trace第1419行。main.rs第一次变化早在`15:31:54.674Z`（第382行）；原生为`15:32:39.744Z`（第307行）。因此跨窗口案例整体0是明确的保护失败，不是已证明“驱逐导致遗忘”。State前/后保护表达均不可由冻结规则可靠判定，保留unknown；不因已有另一个false而掩盖这两个未知子断言。不推断模型内部读过、服从或依赖了State。

## 八项原题失败定位

原verifier仅给文件汇总。结束后将已保存、未经修复的最终插件Rust工件复制到同一官方镜像，在`--network none`、180秒上限的独立容器中重放四个公开文件，无模型请求，未重新启动benchmark或改写原结果。8项均为`expected error, got ok`，计数与原verifier完全一致；诊断容器已移除。

| 准确标识 | 类型 | 实际行为 | 诊断日志行 |
|---|---|---|---:|
| return.wast:315 | assert_invalid | 应拒绝却接受 | return.log:65 |
| return.wast:324 | assert_invalid | 应拒绝却接受 | return.log:66 |
| return.wast:351 | assert_invalid | 应拒绝却接受 | return.log:69 |
| return.wast:360 | assert_invalid | 应拒绝却接受 | return.log:70 |
| return.wast:369 | assert_invalid | 应拒绝却接受 | return.log:71 |
| br.wast:484 | assert_invalid | 应拒绝却接受 | br.log:79 |
| br_if.wast:593 | assert_invalid | 应拒绝却接受 | br_if.log:109 |
| br_table.wast:1261 | assert_invalid | 应拒绝却接受 | br_table.log:159 |

日志在正式根目录`reports/diagnostic/`。已证实失败落在MVP无效模块拒绝/验证行为，不是SIMD规范断言失败。具体validator代码分支尚未通过最小化或执行跟踪隔离；没有记忆因果消融，不能说这8项因State、窗口或一次追加失败所致。本轮不修被测方案。

## 覆盖矩阵：实现、测试、正式覆盖分开

| 指标组 | 已实现/测试 | 本题真实覆盖 | 仍缺少或不适用 |
|---|---|---|---|
| Q1工具错误、耗时 | 原pi.txt按call_id start/end/isError/duration；正反/缺结果测试 | 两组全部工具回执及分位数 | 通用逻辑操作恢复率、每类业务失败与基础设施故障的完美分类未实现；不以相邻成功当恢复 |
| Q2更新契约 | State回执/提交2x2、真实op_id；产品原子性/幂等单测保留 | 10提交/1无提交错误 | 故障注入无效输入接受率未成为本题通用报表；不能宣称所有多文件事务承诺 |
| Q3Rule | 实际请求system hash、Rule块数、模板残留；完整Pi加载和产品模板测试 | 350请求Rule1、335请求Rule0，残留0 | 不以块数证明每条语义完整或模型服从；未形成全部Rule契约的数值总分 |
| Q4Window/引用 | 消息角色/hash/tool ID、原指令可见性；产品窗口/回读测试 | 插件200请求可见、150请求已驱逐 | 本轮无memory_read；全部引用内容保真、所有事件完整性的独立运行评分未实现 |
| Q5恢复/隔离 | 现有产品测试；规范化Task恢复端到端/条件率及缺证据夹具 | 隔离新容器/新Session，各1Task创建；未触发查回/重启 | 不能把既有产品测试当本题跨重启恢复或全部scope语义覆盖 |
| Q6资源与费用 | 原usage/phase、HTTP耗时、PiCPU/RSS、Docker采样、全局/arm准入 | 两组连续量及全任务费用链 | 完整存储I/O、全部子进程累计CPU、真实tokenizer分块占比、账户实扣账单未接入；bytes不称tokens |
| Q7密度/节奏 | 累计F/D、批次/事件区分、闭区间、CV、首尾、缺字段/幂等/零单次写测试 | 24F/D、10批、R350，全部可定位 | 不能靠密度或均匀度判价值；无通用CV门槛 |
| Q8交付可观测 | 最终HTTP payload摘要、State版本/hash、Rule计数、request_id与额度结算 | 685/685链完整；插件347State请求 | hash不能重建完整真实请求；未实现所有commit→request新鲜度的独立违约率，也不证明采用 |
| S1及时保留/保真，C1–C4 | 受控规范化事实字段、否定/单位/scope、顺序、驱逐谓词；正反/缺证据参数化测试 | 实际中途10批；驱逐发生，保护案例失败，表达子断言unknown | 不是通用自由文本语义解析器；不是八个完整长任务场景均已落地实测；语义精确率/污染/长期曲线需专属adapter与gold |
| S2纠错/适用/采用，C5–C8 | 旧项失效、矛盾active、动作字段、澄清先行的受控谓词测试 | 未触发modify_fact和规范化反证/弃权案例 | 无法从本题发布纠错及时率、错误采用率或版本隔离收益 |
| S3任务收益 | 原奖励/分类通过数、成本/时长/失败保留、成对比较 | 原生1/插件0，成本差+0.076799844 | n=1不能推广，未做State机制消融/负对照；无独立case簇区间证据 |
| S4查回相关性/排序 | Hit@K、Recall宏平均、BestTop1、最佳已入围条件Top1；去重/有效K/空结果测试，score-cases入口 | 本题不触发task_find；N/A | 需要真实检索gold与原轨迹adapter，不能以规范化输入测试宣称检索质量 |
| Task恢复 | 全部合格意图分母、正确绑定条件子集、当前版本/动作断言；缺证据测试 | 本题无task_resume；N/A | 完整真实恢复案例与可见候选归因仍需专门adapter；绑定不等于认知恢复 |
| Task新建/复用/简单不建 | route允许集、创建精确/召回、去重ID、deadline、完成且保护、误拆/重复建档；正反/null测试 | 只观察1个持久Task，未预注册完整语义路由机会 | 不凭这1次创建给新建精确率；T1–T4公式和谓词验证不等于四组端到端模型案例 |

因此交付的是已连通的连续遥测、固定wasm行为adapter以及规范化案例评分原语与夹具；**尚非报告中全部Q/S指标和全部C1–C8/T1–T4端到端案例的完整实现**。C1–C8标签目前共用同一组合成事实/动作谓词夹具，不是八种独立业务场景。缺项明确保留，不能包装成全部已测。开发夹具不作为泛化证据；本题只有同一业务oracle的原生产品基线，没有额外Oracle State/负对照付费组。

## 预算、无效尝试与停止证据

价格来源：[DeepSeek官方价格](https://api-docs.deepseek.com/quick_start/pricing/)，2026-11-01核验。使用峰值miss输入0.30、确认hit输入0.006、全部completion输出1.20 USD/M；reasoning不重复加。实际时段可能折扣，未读取账户账单，以下不是实际实扣。Search/Fetch未启用，未购买收费环境。

| 阶段 | 确认usage/请求 | 已确认峰值估算USD | 未知保守预留USD |
|---|---:|---:|---:|
| 首次失效尝试141259Z… | 147个usage，另2个中断请求 | 0.316410276 | 1.521600000 |
| 两组真实短canary | 每组1个HTTP200，输出上限128 | 0.000310104 | 0 |
| 有效正式配对152354Z… | 685/685 HTTP结算 | 1.415651532 | 0 |
| 全任务合计 | 836条账本记录，834结算/2未知 | 1.732371912 | 1.521600000 |

保守敞口合计 **3.253971912 USD**，低于授权30；全局准入29、累计arm各12不变，新配对两组共同剩余额度固定11.056019388。未知预留是首轮各1个请求按1M输入+384K输出峰值上界0.7608，未当账单或退款。账本未清空重置，未把一组余额转给另一组。模型准入停止00:15:38、宿主清理兜底00:38:38、用户硬截止00:40:38；实际提前完成。

首轮 `20261101T141259Z-b33204deca` 在真实CLI中被HTTP dispatcher替换预加载fetch，导致守卫漏接，已作废。仅SDK假传输预检未覆盖CLI初始化顺序，这是预检缺陷。发现后精确暂停、保存原件并终止两个本run容器，Running=false；不把它的输出混入有效配对。其回执和费用均保留。早期软停止只匹配node未命中CLI进程名pi，后改为可信容器身份和独立PID截止。

修复后在CLI扩展工厂重挂守卫，发送前检查身份、失效先abort；SDK仅持无效占位key，真实既有key只有已准入传输读取，不新建长期凭据。真实CLI正例、故意丢失守卫负例（上游0请求）、PID截止、双容器额度锁、真实1请求canary均通过，才新建干净配对。两组有效run request_id全部对应reserve→request-ready→HTTP200→usage结算→end，186个原始工件hash全部匹配。正式与诊断容器均已移除。

## 入口、复现与文件

沿用现有系统：`runner.py:472`读取实验配置，`:681`并发分支提交两个Harbor Job；`pi_agent.py`运行实际Pi CLI及完整候选包；公共`checkpoint_observer.ts`记录工具边界并一次steer；`fetch_guard.mjs:68`记录最终传输/额度；`report.py:197`读原始证据，`:317–324`接工程及wasm行为；JSON/CSV/Markdown同一流程输出。没有第二套Agent Loop或独立评测宿主。

入口配置为`experiments/configs/marathon-wasm.yaml`；题库/子集为`experiments/suites/swe-marathon.yaml`、`experiments/subsets/wasm-simd.yaml`；冻结gold为`experiments/cases/wasm-simd-v1.json`。定义和范围见[有价值指标](../../experiments/有价值指标.md)。

只读重算本次结果，无模型请求：

```sh
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli report \
  /Users/godice/.local/share/memweave-experiments/runs/20261101T152354Z-726a528639
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli score-cases GOLD.json EVIDENCE.json
```

正式运行使用的命令（记录用途，**本次已完成，不再次执行来挑成绩**）：

```sh
PATH=/Users/godice/.local/share/memweave-experiments/tools/native/bin:$PATH \
DOCKER_HOST=unix:///Users/godice/.colima/memweave-eval/docker.sock \
DOCKER_CONFIG=/Users/godice/.local/share/memweave-experiments/tools/docker-config \
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli run \
  experiments/configs/marathon-wasm.yaml
```

正式根目录包含`experiment.lock.json`、`run.json`、`case-gold.json`、`evidence-index.json`、原Harbor Trial/Session/State归档及verifier/artifacts；`reports/results.json`、`trials.csv`、`comparison.csv`、`report.md`为自动报表；`reports/final-audit.json`为可导出机器审计（685请求链、全部指标、8失败ID、源代码hash和费用），`quota-final.snapshot.json`为不含凭据的最终账本快照。

失效原件另存首轮run的`harbor/emergency/`、`invalidation.json`和清理证据。真实canary位于`preflights/marathon-20261101-paid-canary/`。全部在本机私有实验目录，未加入Git，不复制认证文件到报告。原始model trace未修改。

新增/修改集中于实验侧：工程统计、State提交诊断、行为公式/谓词、wasm adapter、共同观察器、传输/准入/截止、既有runner/spec/Pi/report/CLI接线、配置/gold/测试和文档。完整文件清单由本地实现提交diff和最终审计`reports/implementation-files.json`给出。产品`src/`、`resources/`、`docs/specs/`在本次实验改造中没有变化。

## 验证记录与未运行项

| 检查 | 真实观察到的结果 |
|---|---|
| `PYTHONPATH=experiments/src experiments/.venv/bin/python -m pytest experiments/tests`，冻结前 | 254 passed；`/tmp/memweave-marathon-20261101/pytest-repaired-final.log` |
| 同一测试加`-q`，收尾显示说明修改后 | 254项全部通过、退出0；`pytest-closeout-approved.log`；默认沙箱首次4项loopback绑定失败保留`pytest-closeout.log`，不是代码测试断言失败，正常权限流程重跑通过 |
| Node24 `node --test experiments/tests/pi-guard.test.ts` | 3/3通过；`pi-guard-closeout.log`，含真实SDK取消/重试、实际Pi压缩替身和共同steer |
| `ruff check experiments/src/memweave_eval experiments/tests`、`git diff --check` | 通过 |
| Node24 `MEMWEAVE_TEST_NPM_CACHE=/Users/godice/.npm npm_config_offline=true npm run check` | 资源一致性/TypeScript/产品276项通过；`npm-check-offline.log`；产品之后未变，未重复付费发布验收 |
| 完整候选包实际Pi+假provider、两容器同时烟测 | 两组时间重叠8.772509秒，原生4工具/Rule0，插件16工具/Rule1/State v1，输出上限均16384，真实请求0 |
| 修复后真实CLI丢守卫负例/独立PID截止 | 正例链完整；负例upstream0；实际Pi PID被截止，非仅通用假进程 |
| 双容器额度锁/故障停止 | 单个获准[0,2]；查询/kill短故障重试并确认；未影响无关容器 |
| 两组真实canary与有效正式链 | 2个canary及685正式请求均HTTP200、准确一次结算；186个原始证据hash全部匹配 |

更早免费预检的`/tmp`未共享导致reward回收失败、首次未缓存兼容安装超时、首轮真实CLI守卫失效均保留，不能作为通过记录。未运行完整发布流程、推送、npm发布、额外付费负对照/多seed/多任务实验，也未将产品测试替身宣称为全部真实模型记忆行为验证。
