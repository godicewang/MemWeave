# 指标v2补齐验收与原实验适配附记

本附录接续[原实验报告](MARATHON_REPORT_2026-11-01.md)，不修改原题成绩、v1金标、原始轨迹、reports或hash清单。有效run仍为`20261101T152354Z-726a528639`，模型运行冻结`2312aacba04df4d4afbbe74d7cda7657e24ca179`，原交付`1ff14e5d5b3a877cdd654cc953aef65b7b8e7520`保留在Git。v2无新增付费请求，不重新跑题或修被测答案。

## 补齐范围与覆盖矩阵

| 类型/指标 | 新增程序能力及测试 | 当前真实数据 | 边界 |
|---|---|---|---|
| P0逻辑操作恢复率 | 明确operation ID、首次失败、预先可恢复、到截止；在重试预算内由外部状态确认恢复 | 两组均unknown；原工具尝试337/369，明确映射0 | 相同工具/参数不构成重试，成功回执不证明外部状态；存储op_id不自动成为跨调用业务ID |
| P0重试负载 | 同operation首尝试外的尝试/全部明确映射尝试；重试耗时/费用缺值单列 | mapping coverage均0；不能填重试0 | 仅描述可映射的已观察尝试；覆盖率与未知必须同报 |
| P0 State最新版本 | 完整commit序列、expected task与同一序列prepare边界，检查交付唯一版本等于边界前最新版本 | 原生N/A；插件350请求unknown，已知分母0，覆盖率0 | 不把事件创建time当commit；不补造请求准备时间或独立绑定字段 |
| State已确认回执下界 | Session祖先和真实journal op_id关联实际请求可见写回执，交付版本不得低于同Task最大确认版本 | 原生N/A；插件347/347=1，3次无依赖N/A | 仅下界一致性；错误但已提交、并发或未观测提交都可能更高，**不是完整新鲜度通过** |
| P0引用机械保真 | ref/scope/版本/授权投影hash逐项比对；读取错误0，缺证据unknown | 双方N/A，无memory_read/state_read | 零调用不证明原本无需读取；截断按允许投影，不与全原文hash混用 |
| P0 Window机械保真 | 完整事件投影、顺序、scope、hash及call/result配对；只有预登记pending调用允许缺结果 | 原生335、插件350请求unknown | 原摘要缺预期事件投影及assistant调用ID，不能只凭Session猜真实请求保真 |
| C1–C8/S1–S2 | 不同wasm派生事实、检查点、谓词、失败变体；C8分三路，合计10个记忆案例 | 仅离线oracle验证，不新增本轮LLM行为分 | 不是通用自由文本语义解析，不以模型自述passed评分 |
| Task检索/恢复/路由 | T1排名、T2恢复当前约束、T3独立目标新建、T4简单插话不建；按受控业务投影判定 | 4例程序oracle验证；本题仍只有1次create，无find/resume实测 | 不把正确绑定当认知恢复，不强迫已知ID先搜索 |
| 原有Q1/Q2/Q3/Q6/Q7 | 原工具统计、State回执提交、Rule、资源/成本、F/D密度及节奏保留 | 原结果不变 | 不用新定义补原分 |
| 后续观测/实验 | 全进程累计资源I/O、账户实扣、多任务多seed与额外消融 | 未运行 | 非本轮无模型补齐目标 |
| 范围外能力 | 任意自然语言State的通用重要性/真值判官、模型内部阅读或因果采用推断 | 不承诺通用解析器 | 上版称“缺项”不应被解读为本次必须实现这些通用能力；采用案例专属gold与证据 |

`contract_metrics.py`是计算，`contract_evidence.py`读取原Pi/State/传输证据，`supplement_report.py`经既有report入口写新目录。全部条件率输出分子、已知分母、unknown、N/A、覆盖率；覆盖不足时不能将已知子集的1当总体1。

恢复率的合格操作须明确首次失败、可恢复、达到观察截止、重试预算与预期外部状态。重复attempt回执去重，冲突证据unknown；超预算/超截止的成功不刷恢复率。未到截止pending unknown；首次未失败或预先不可恢复N/A。

严格新鲜度不接受State JSONL的`time`充当提交边界：`StateStore`构造事件时生成time，之后才commit。可见回执下界独立用真实op_id和实际请求tool_call_id关联，不拿State交付版本自身当金标，不推断全局最新或模型采用。

严格State及机械引用/Window支持版本化评估contract bundle的显式边界、gold和投影输入。它们属于模型上下文之外的评估字段，不改产品State schema。旧轨迹缺字段已有可执行unknown路径，不能为使数字好看补造数据。

## 有区别的版本化案例

gold：`experiments/cases/wasm-memory-task-v2.json`。正例、负例、缺证据分别为`experiments/fixtures/wasm-memory-task-v2/{positive,negative,missing}.json`。各例用途、内容、谓词或检查点不同，不再将同一夹具仅更换C标签。

| 案例 | 固定检查 | 独立负例 |
|---|---|---|
| C1 transient-baseline | 一次性baseline=1931输出驱逐后保留并用于比较 | 值压成193 |
| C2 allowed-crate-exception | 外部依赖禁令与serde/serde_json例外同时保全并正确应用 | 丢例外 |
| C3 before-dependent-edit | return无效模块关键失败在依赖修改前记录 | 到终答位置才补记 |
| C4 three-window-checkpoints | 三个不同窗口点各验驱逐、保护约束和未决下一步 | 中间点把未决误记完成 |
| C5 correct-before-action | 旧Decision失效、更正Fact有效，纠正先于动作并采用B | 旧Decision仍active；不强迫两工具原子化 |
| C6 version-and-project | v1复现、v2部署、不同项目分别保持范围并正确行动 | 将v2方案套到v1 |
| C7 implicit-runtime-offline | 按阶段/scope审计网络事件，禁止runtime外网，不误伤声明允许的build变体 | 增加runtime外网事件 |
| C8 missing | 保留缺值、澄清先行，权威答复先于依赖动作 | 未澄清 |
| C8 conflict | 保留同权威冲突，澄清后按授权值行动 | 略过冲突澄清 |
| C8 reliable-known | 已知时执行且无多余阻塞 | 无必要澄清 |
| T1 retrieval-ranking | 相关/最佳集合固定，召回与最佳首位分开 | 最佳已入围但未排首位 |
| T2 current-task-restore | 绑定正确后还验请求当前约束与首个动作 | 绑定正确却执行旧步骤 |
| T3 independent-goal-create | 唯一持久ID、正确Goal/scope投影、截止前创建绑定 | 独立目标continue且未建档 |
| T4 ephemeral-interruption | 128bit=16bytes回答完成、不建档且原Goal/约束/下一步不变 | 回答128bytes |

T2的请求/动作、T3的持久Task Goal/scope、T4的答案/保护投影由case适配计算布尔断言，不要求Agent提供passed标志。case规范化字段不成为产品Goal/Fact/Decision字段，不宣称可自动解析任意真实Goal文本。

14例均真实通过既有`score-cases` CLI：独立正例全1、负例全0、缺证据全unknown。C1/C2/C4/C6/C7另有明确的边界前正确快照、写入先于驱逐、驱逐后依赖动作；负例保持这些前置条件正确，只破坏后续保留或采用。前置检查失败时应定位到边界前失败，不能称遗忘；完整案例仍记失败，不把真实性能失败删出。

这证明程序oracle及受控适配，不证明LLM已具备相应能力。案例在原实验结束后开发，尤其从失败症状派生的开发案例不用于改原分或证明泛化。

## 原实验额外输入与effective context附记

原题起点、官方instruction/verifier和镜像保持，但正式运行有共同额外用户消息，因此称**同题adapted产品对照**，不称官方榜单原样运行。

- 各组第80个usage对象assistant返回后，公共观察器调用`sendUserMessage(...,{deliverAs:'steer'})`，只一次，不周期。准确消息为“请简短汇报进度，然后继续完成刚才的任务。”，不重述保护限制或答案。原生case_input为`15:36:48.399Z`，实际Session用户消息`15:36:52.940Z`；插件分别为`15:34:06.528Z`和`15:34:06.678Z`，各确认一次。
- 原题外插件组还有产品完整Rule、12个记忆工具schema、请求级State/预算/Window提醒；原生只保留4原生工具。共同观察器不注册业务工具；gold、额度账本、传输hash和评分结果不进入模型上下文。未提供参考答案或另一组产物。
- 两组模型元数据contextWindow均1,000,000，HTTP输出上限均16,384。原生不使用MemWeave N/B，自动压缩开启，独立新settings只覆盖enabled；Pi1.4默认reserveTokens16,384、keepRecentTokens20,000。
- 插件自动压缩关闭，实际持久Window参数recent_turns=200、evict_turns=40。基础预算600,000，最多额外200,000弹性容量，之后仍按冻结实现扣必需成本与分池，800,000不是纯Window可用输入。不能把本次产品比较称同窗口移除State消融。
- 实际compaction均0；单请求输入峰值原生286,858、插件184,183 token。插件原指令在201及之后共150请求不再可见，原生335请求始终可见。这是上下文机制差异，不单独证明State内容收益。

原实验插件main.rs首次变化`15:31:54.674Z`，早于指令驱逐`15:47:58.155Z`；原跨窗检查的0仅说明驱逐后仍不满足保护约束，不能隔离为遗忘。新增前置正确案例不用于给这个原运行补分。

## 版本与复现

v2需显式新目录，已有目录拒绝覆盖，原reports/原始证据路径禁止作为v2输出；不调用v1生成器。记录原lock/report/raw-index hash、原186个工件验收、evaluator提交及模块hash、gold/fixture hash和可选contract bundle hash。

```sh
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli report \
  /Users/godice/.local/share/memweave-experiments/runs/20261101T152354Z-726a528639 \
  --metrics-version 2 \
  --output /Users/godice/.local/share/memweave-experiments/runs/20261101T152354Z-726a528639/supplements/p0-cases-v2-20261101
```

该目录输出`metrics.json`、`metrics.csv`、`report.md`、`case-fixture-validation.json`、`artifact-index.json`。重复验收选另一个新目录，不覆盖旧目录。

```sh
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli score-cases \
  experiments/cases/wasm-memory-task-v2.json \
  experiments/fixtures/wasm-memory-task-v2/positive.json
# positive换成negative、missing，预期全0、全unknown。
```

按原评分器重算需冻结源码与独立run副本，不将当前HEAD对原目录默认执行report：

```sh
frozen_dir=$(mktemp -d /tmp/memweave-v1-source.XXXXXX)
replay_parent=$(mktemp -d /tmp/memweave-v1-replay.XXXXXX)
git archive 2312aacba04df4d4afbbe74d7cda7657e24ca179 | tar -x -C "$frozen_dir"
cp -R /Users/godice/.local/share/memweave-experiments/runs/20261101T152354Z-726a528639 "$replay_parent/run"
PYTHONPATH="$frozen_dir/experiments/src" experiments/.venv/bin/python -m memweave_eval.cli \
  report "$replay_parent/run"
```

原目录保持不变。2312aac Markdown还有旧“请求数未知”说明，1ff14e5只澄清该文案，核心分数一致。以上是离线复现说明，本补齐阶段没有重新生成原目录v1文件。

## 验收

- P0正/反/缺数据：显式ID、回执去重冲突、外部状态、预算/截止、不可恢复/空机会；State正确/陈旧/错Task/缺边界；引用错scope/版本/hash；Window缺消息/逆序/错scope/hash。
- 用真实形状Session、稳定op_id和JSONL测试下界适配；v2报表测试源hash损坏拒绝、已有输出拒绝、v1文件不变及原分保留。独立案例实际执行既有CLI三次，每次14例。
- `PYTHONPATH=experiments/src experiments/.venv/bin/python -m pytest experiments/tests`：**270 passed**，日志`/tmp/memweave-marathon-20261101/pytest-v2-final.log`；loopback按正常权限流程运行，无模型请求。
- Ruff全实验目录、git diff检查通过。产品src/资源/规范及Node守卫未改，原276产品检查和3项Node守卫记录保留，不宣称又做付费验证。

本轮承诺的P0计算及有区别程序案例已补齐，当前真实数据不可测的项目仍不可测。范围外的通用语义/因果判官不再冒充通用功能承诺，也不将离线oracle通过当成LLM实测通过。
