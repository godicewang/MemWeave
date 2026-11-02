# SWE-Marathon 两题原生 Pi / MemWeave 对照报告

实验：`marathon-next-20261101`。本次共完成两题、四个有效正式试验。两题两组原题二元分均为0；细分通过数为compiler原生563/894、插件500/894，zstd原生12/43、插件7/43。两题插件合计峰值估算费用为原生44.5780%，质量结果同时较低。本报告保留失败，不把低费解释成同等质量节省；每题每组仅一次，是预算和资源适配产品对照。

## 结果与停止原因

| 任务 | 组 | 通过数 | 原题二元分 | 停止情况 | Agent 秒 | 验证秒 |
|---|---|---|---|---|---|---|
| rust-c-compiler | pi-memweave | 500/894 | 0.0 | 终答仍列未解决项 | 9782.39 | 435.26 |
| rust-c-compiler | pi-native | 563/894 | 0.0 | 额度准入停止后验证 | 8346.97 | 327.06 |
| zstd-decoder | pi-memweave | 7/43 | 0.0 | task_clarify 等待用户 | 342.70 | 22.82 |
| zstd-decoder | pi-native | 12/43 | 0.0 | 18000秒上限；归档后原镜像验证 | 18002.77 | 21.57 |

zstd 原生实际 AgentTimeoutError 为18000秒上限；独立PID停止事件01:25:25.054 UTC，Agent阶段含约2.77秒收集收尾至01:25:25.505。模型最后请求20:27:31 UTC后没有新请求，未追加解题时间。源码归档21,981字节，5个普通构建输入/业务binary哈希交接、source_bytes_modified=false；原干净镜像验证01:25:37.234–01:25:58.802，trial结束01:25:58.802，run结束01:25:59.732，cleanup confirmed_stopped=true。实际原生zstd Agent阶段超时属于性能失败，计入结果；Bash有1个未返回结果，错误率unknown，不能填0。

四臂 Agent 区间累加为 36474.835 秒，重叠区间并集墙钟为 20778.968 秒；截至本报告首次生成，自用户授权起实际经过 27640.957 秒。累加时长不能冒充并发墙钟。

compiler 原生在冻结的 episode 准入额度生效后停止新请求；插件正常终答时仍列出尚未解决的问题，两臂均未完成全部测试。compiler 原生首个额度拒绝为 21:57:58.319 UTC，共4个本地拒绝，未派发上游；它们形成4个零 usage 的 assistant 错误占位。

zstd 插件最后调用 task_clarify，问题为“Task goal is bound; no clarification needed to proceed.”；真实回执 status=waiting_for_user 并停止本轮，随后评测。进程正常结束不能解释成业务任务完成。本轮没有人工补答、修模型答案或为提高成绩重跑。

完整原始失败条目在交付 `verifier-failures.csv`，每行保留来源与原 stdout 行号。compiler 原生331项失败（compile101/run25/rc205），插件394项（compile73/run59/rc262）。这些分类来自原验证器，不猜测记忆因果。

## 新增缓存与配对费用口径

主缓存利用率=cache-hit input / total input；总输入已经包含缓存。辅助占比=cache-hit input/(input+completion)。以下由供应商原始 HTTP usage 计算，汇总先加 token 再除。缺失 unknown，显式0有效，零分母 N/A，负值或缓存大于输入 invalid。

| 任务 | 组 | HTTP M | usage 对象返回 R | 总输入 token | 缓存输入 token | 输出 token | 缓存/输入 | 缓存/全部 token | 峰值估算 USD |
|---|---|---|---|---|---|---|---|---|---|
| rust-c-compiler | pi-memweave | 887 | 887 | 70769624 | 68488448 | 251375 | 96.7766% | 96.4341% | 1.396933488 |
| rust-c-compiler | pi-native | 1290 | 1294 | 472497684 | 472103168 | 360504 | 99.9165% | 99.8403% | 3.383578608 |
| zstd-decoder | pi-memweave | 75 | 75 | 5566331 | 5427200 | 48272 | 97.5005% | 96.6622% | 0.132228900 |
| zstd-decoder | pi-native | 18 | 18 | 575912 | 540544 | 27393 | 93.8588% | 89.5971% | 0.046725264 |

按token加权的总汇总：

| 汇总范围 | 任务臂数 | 输入总量 | 缓存输入总量 | 输出总量 | 缓存/输入 | 缓存/全部 | 状态 |
|---|---|---|---|---|---|---|---|
| pi-memweave | 2 | 76335955 | 73915648 | 299647 | 96.8294% | 96.4508% | scored |
| pi-native | 2 | 473073596 | 472643712 | 387897 | 99.9091% | 99.8273% | scored |
| 全部四臂 | 4 | 549409551 | 546559360 | 687544 | 99.4812% | 99.3569% | scored |

M 是实际模型 HTTP 尝试，包含实际发送的供应商重试/原生压缩请求，工具调用不是 M。R 包含零占位/error/aborted，不能当成功推理数。旧 State 字段 model_request_attempts 仍只依据 Session，实际 M 使用 transport/engineering 字段。

| 匹配任务 | 插件/原生费用比 | 相对原生百分比 | 相对增减 |
|---|---|---|---|
| rust-c-compiler | 0.412856815 | 41.2857% | -58.7143% |
| zstd-decoder | 2.829923016 | 282.9923% | 182.9923% |

估算费用分解（同一冻结峰值价格）：

| 任务 | 组 | 未缓存输入 USD | 缓存输入 USD | 输出 USD |
|---|---|---|---|---|
| rust-c-compiler | pi-memweave | 0.684352800 | 0.410930688 | 0.301650000 |
| rust-c-compiler | pi-native | 0.118354800 | 2.832619008 | 0.432604800 |
| zstd-decoder | pi-memweave | 0.041739300 | 0.032563200 | 0.057926400 |
| zstd-decoder | pi-native | 0.010610400 | 0.003243264 | 0.032871600 |

两题总体比（匹配任务成本之和相除）为 **0.445780445**，即原生的 **44.5780%**；没有平均两个任务比值。

compiler 插件费用比41.2857%，对应原题通过数500/894，原生为563/894；费用与质量应同时判断，不能解释成同等质量下节省58.7%。缓存比例高也不意味着累计缓存输入成本低。

价格按冻结官方峰值保守口径：cache-miss 输入0.30、cache-hit 输入0.006、输出1.20 USD/M；费用是估算，不是账户账单，不假定周末/离峰折扣。来源：[DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)。请求 deepseek-flash；官方映射快照为 DeepSeek-V4.1-Flash-1017，具体配置与来源在各 lock。未启用收费 Search/Fetch。

## State、工具和请求交付

| 任务 | append成功/尝试 | 失败 | 累计新增F/D | 当前有效F/D | F/D/R | 诊断 | 成功批次 | 内部间隔均值R | CV | 最大间隔R | 首段R | 尾段R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rust-c-compiler | 14/16 | 2 | 22 | 15 | 0.024803 | too_sparse | 20 | 45.4211 | 0.7634 | 119 | 11 | 13 |
| zstd-decoder | 1/1 | 0 | 2 | 2 | 0.026667 | too_sparse | 1 | 样本不足 | 样本不足 | 样本不足 | 14 | 61 |

F/D 按实际 journal 累计新增 Fact/Decision 条目数：含 modify_fact 创建的新 Fact，不含 Goal/归档/重复幂等；批次和条目分别统计。密度[0.05,0.10]仅是用户指定诊断区间。均匀度用成功批次位置的内部间隔总体 CV；至少两个内部间隔，单次写入不报告完美均匀。首尾单列，没有新增任意 CV 达标门槛。

compiler append 两次失败分别为额外 type2 字段和缺 type，属于执行前 schema 拒绝，均未落地；不是内容长度失败。modify_fact 6/6 成功；20次成功逻辑写批次均提交，两次错误均未提交。模型在第11至874个返回之间多次写入；这说明存在过程记录，不能单凭次数证明记住了应记的信息。

| 任务 | 组 | State版本一致性 | 实际provider交付投影 | 独立Window gold | 引用 | 逻辑op映射覆盖 |
|---|---|---|---|---|---|---|
| rust-c-compiler | pi-memweave | 884/884; unknown=0; N/A=3 | 887/887; unknown=0; N/A=0 | unknown | not_applicable | 0.0 |
| rust-c-compiler | pi-native | 0/0; unknown=0; N/A=1 | 1290/1290; unknown=0; N/A=0 | unknown | not_applicable | 0.0 |
| zstd-decoder | pi-memweave | 73/73; unknown=0; N/A=2 | 75/75; unknown=0; N/A=0 | unknown | not_applicable | 0.0 |
| zstd-decoder | pi-native | 0/0; unknown=0; N/A=1 | 18/18; unknown=0; N/A=0 | unknown | not_applicable | 0.0 |

State 指标只核验准备边界的 Task/版本及唯一交付块，不证明模型阅读或采用。provider 投影一致性不代替独立 Window 选取 gold；本轮独立事件投影证据不足，保留 unknown。没有引用读取机会则 N/A。普通工具没有明确业务 operation ID，不能凭相同参数猜重试；逻辑恢复率/重试负载保留 unknown。

逐工具尝试、错误分类、未知结果、p50/p95/max execute 耗时、请求延时、Pi CPU/RSS在 `metrics.json`。验证前 schema 拒绝没有 execute 耗时，不补0。Docker资源采样仍保留于各 run 的 deadline-watchdog.jsonl；Pi进程资源不冒充所有子进程累计资源。

## 两类指标的实现与实测覆盖

| 能力 | 实现/验证 | 本轮覆盖及边界 |
|---|---|---|
| 缓存、费用比、加权总汇总 | 既有report/campaign JSON、CSV、Markdown、finance-report入口；正负/缺失/0/invalid测试 | 四臂供应商usage及峰值估算；运营费用另表 |
| 工具可靠性、State提交/密度/节奏 | 工程/State模块，确定性单测与真实轨迹 | 连续量已测；schema拒绝与提交分开 |
| Rule/State请求准备和实际交付 | 实际Pi CLI假provider、真实canary及请求边界metadata | 版本/投影已测；不宣称语义采用 |
| 逻辑恢复、引用和Window机械保真 | 明确op/gold/投影的程序断言及正反缺证据测试 | 无op映射unknown；无引用机会N/A；独立Window gold缺失unknown |
| 固定业务检查点 | 原验证器保留；Makefile保护与规范public命令回执 | zstd Makefile实际校验；public检查仅冻结规范完整命令及成功回执，未匹配不等同从未测试 |
| 跨窗约束保留 | 版本化保守clause proxy及实际驱逐metadata | compiler确认指令驱逐但proxy证据不全，unknown；zstd插件未确认驱逐，unknown；均不是采用率 |
| C1-C8与Task T1-T4 | 14个有区别的固定案例，现有score-cases CLI正例全1/负例全0/缺证据unknown | 本轮免费复验oracle，未追加LLM跑题；不是14种自然行为已实测 |
| Task检索/排名/恢复/创建路由 | 受控gold与四条独立Task路径，检索条件分母/创建deadline测试 | 单题鲜活任务无find/resume机会；create计数不当准确率 |
| 通用开放语义和因果判官 | 不承诺通用自由文本重要性/真值/模型内部读取判定 | 不由State注入、写入次数或最终得分推断因果 |

C1-C8/Task案例及定义见[指标v2验收](METRICS_V2_REPORT_2026-11-01.md)；本次没有用事后新断言改写原分。

## 冻结条件、环境适配与异常历史

- 官方任务固定 dd4d2bbc8d2ec8bb22fc4a4261d3b0c827faa2a4，原始起点和原验证器不换版本。compiler 的 task.toml/题面780连续分描述与实际验证器binary/894不一致，报告实际输出。
- 每臂2CPU、8192MiB、20480MiB；原任务4CPU/16GiB。四臂并发容量在本机12核约41GiB VM免费预检通过，同题并发。compiler实际9h上限（原10h），zstd5h；共同预算说明及实际 timer 提前告知。全局模型截止04:45:13，用户硬截止05:50:13 UTC。
- 同模型/thinking off/输出16384。完整Pi默认system/原生工具；full插件包commit207d746babd80b2381f04688d8d576c73429af30，SHA256 5ed61de2eb9d8096cf063fb519c4b54c8f63b09cd518c00e4d228d1bed92f022。
- 原生自动压缩开启；插件关闭压缩，完整Rule/State/Recent Window与基础60%加最多20%弹性容量。属于完整产品差异。公共进度提示在第80个usage对象返回后仅一次：“请简短汇报进度，然后继续完成刚才的任务。”，真实触发/交付计数在机器摘要。
- zstd开发阶段新增Pi/Node控制运行时属于明确适配，Node现成Zstd API禁用；Bash实际执行边界限制注入解释器路径。最终原干净镜像只接收模型自身的合法完整构建输入/已构建业务binary，不含Pi/Node/key。原grader本来不build，因此含模型binary，不自动替模型修编。交接保留.inc/文本/其他普通输入并逐文件hash；越界链接等报adapter问题。不是完全恶意shell隔离证明。
- compiler官方参考控制原样893/894在2/8及4/16均失败，已确认unused巨大extern导致约16GiB BSS/被杀；隔离预检fixture定向修正后894/894。原失败、修复/hash保留；参考代码没有进入正式起点或模型环境。
- 第一190306 run仅canary：禁用Node Zstd API影响HTTP编码解码，修复控制请求Accept-Encoding:identity；保持未知.3001536预留。
- 192923 run旧zstd对发生整段bash正则误拦，native7/plugin5，19:43:37暂停、19:47:04归档停止。只重跑受影响zstd对，compiler零误拦继续。旧plugin最后未知.3196608保留；旧zstd不进主结果。
- 307b47a修复改为Bash DEBUG实际执行边界；查询、grep字面文本、C heredoc正例，注入Node执行负例均验收。实际CLI正负、丢guard上游0、独立PID截止、真实容器控制、每环境每臂128输出canary均通过才正式重启。
- compiler冻结7203cdd；干净zstd冻结307b47a。付费运行后主分支d42abef仅整理导入/lint，原报告保留。未修改产品src、Rule、State schema/预算/窗口；未推送或发布。临时caffeinate -i随runner释放，未改全局电源设置。

额外进度消息及实际压缩事件：

| 任务 | 组 | 提示触发 | Session真实交付 | 真实交付时间 UTC | 压缩事件 |
|---|---|---|---|---|---|
| rust-c-compiler | pi-memweave | 1 | 1 | 2026-11-01T19:49:12.910Z | 0 |
| rust-c-compiler | pi-native | 1 | 1 | 2026-11-01T19:48:51.052Z | 0 |
| zstd-decoder | pi-memweave | 0 | 0 | 无 | 0 |
| zstd-decoder | pi-native | 0 | 0 | 无 | 0 |

## 本次全部运营费用

新账本：已知峰值估算 **$5.137702680**，未知保守持有 **$0.619814400**，总敞口 **$5.757517080**。用户上限USD20，准入19加安全1；四个(task,variant)累计各4，不转移额度。compiler正式episode两臂各3.699766552，干净zstd各3.575725384，已包含此前费用/预留影响后等额固定。未重置账本。

| run/用途/臂 | 请求 | 已知 USD | 未知持有 USD |
|---|---|---|---|
| 20261101T190306Z-8db1b10487/canary/rust-c-compiler:pi-memweave | 1 | 0.000117360 | 0.000000000 |
| 20261101T190306Z-8db1b10487/canary/rust-c-compiler:pi-native | 1 | 0.000079848 | 0.000000000 |
| 20261101T190306Z-8db1b10487/canary/zstd-decoder:pi-native | 1 | 0.000000000 | 0.300153600 |
| 20261101T192923Z-bab528be27/canary/rust-c-compiler:pi-memweave | 1 | 0.000117360 | 0.000000000 |
| 20261101T192923Z-bab528be27/canary/rust-c-compiler:pi-native | 1 | 0.000079848 | 0.000000000 |
| 20261101T192923Z-bab528be27/canary/zstd-decoder:pi-memweave | 1 | 0.000117360 | 0.000000000 |
| 20261101T192923Z-bab528be27/canary/zstd-decoder:pi-native | 1 | 0.000079848 | 0.000000000 |
| 20261101T192923Z-bab528be27/solve/rust-c-compiler:pi-memweave | 887 | 1.396933488 | 0.000000000 |
| 20261101T192923Z-bab528be27/solve/rust-c-compiler:pi-native | 1290 | 3.383578608 | 0.000000000 |
| 20261101T192923Z-bab528be27/solve/zstd-decoder:pi-memweave | 59 | 0.104379096 | 0.319660800 |
| 20261101T192923Z-bab528be27/solve/zstd-decoder:pi-native | 86 | 0.073068492 | 0.000000000 |
| 20261101T202043Z-52b98f5cd8/canary/zstd-decoder:pi-memweave | 1 | 0.000117360 | 0.000000000 |
| 20261101T202043Z-52b98f5cd8/canary/zstd-decoder:pi-native | 1 | 0.000079848 | 0.000000000 |
| 20261101T202043Z-52b98f5cd8/solve/zstd-decoder:pi-memweave | 75 | 0.132228900 | 0.000000000 |
| 20261101T202043Z-52b98f5cd8/solve/zstd-decoder:pi-native | 18 | 0.046725264 | 0.000000000 |

有效正式费用只取本报告4行；上表另含canary、无效旧zstd及失败准备。旧wasm实验和旧USD30账本不混入；旧账本hash已核验未变。新缓存算法对旧wasm的独立免费补充保留在旧run/supplements/finance-20261101-v1，未覆写旧报告。

最终逐请求审计按唯一request_id核对：账本2,424次实际HTTP，无重复ID；2,422已结算、2次保守预留。有效正式2,270次全部结算；其余152次已结算=旧无效zstd的144次+canary的8次。两笔未知分别为首轮zstd原生canary的0.3001536和旧无效zstd插件的0.3196608 USD，未释放。compiler原生472,497,684输入token由原始Session单条消息、唯一HTTP最终usage和Harbor原agent_result三路一致，未重复计agent_end消息或累计快照。完整记录见交付目录usage-reconciliation.json。

2026-11-02 01:44:59 UTC只读停机检查：本次三个明确run标签均无保留容器，runner、独立watchdog及本次监控进程均未发现活跃项；原两有效run的cleanup均confirmed_stopped=true，停止标记存在。没有释放未知预留或发起新的请求。

## 验证、文件与复现

- 最终主分支：`PYTHONPATH=experiments/src experiments/.venv/bin/python -m pytest experiments/tests -q -o addopts=''`，Node24：321 passed in 7.02s。Ruff最终通过，首次23项样式问题及修复前日志保留；`npm run typecheck`、`git diff --check`通过。
- 产品完整Node24 `npm run check`：resources/typecheck及276测试通过112.77s，产品源文件此后未改。默认Node23早期失败/中断未冒充通过。Node guard3项通过。14案例本次实际CLI三次：全1/全0/全unknown。
- 发布完整付费入口、多seed/重复实验、额外消融、账户账单核对未运行；本次不宣称发布兼容认证或统计泛化。
- 完整交付目录：`/Users/godice/.local/share/memweave-experiments/analysis/marathon-next-20261101/v1`；metrics.json保留逐任务全部字段，trials.csv是简表，verifier-failures.csv保留失败来源，provenance.json及artifact-index.json保留hash/版本。原run/reports未覆写。

离线复算统计（不发模型请求；选择新输出文件）：

```sh
PYTHONPATH=/Users/godice/Coding/MemWeave/experiments/src /Users/godice/Coding/MemWeave/experiments/.venv/bin/python \
  /Users/godice/.local/share/memweave-experiments/analysis/marathon-next-20261101/v1/collect-next-terminal.py --output /tmp/memweave-next-recomputed.json
```

冻结版本重算原report应在独立源码和run副本执行：

```sh
frozen_src=$(mktemp -d /tmp/memweave-frozen.XXXXXX)
replay_parent=$(mktemp -d /tmp/memweave-replay.XXXXXX)
# compiler根用7203cdd；干净zstd根用307b47a。替换ROOT为相应完整run目录。
git archive 7203cddc413efed75598b7f5fc6bb12c99603efd | tar -x -C "$frozen_src"
cp -R "$ROOT" "$replay_parent/run"
PYTHONPATH="$frozen_src/experiments/src" /Users/godice/Coding/MemWeave/experiments/.venv/bin/python \
  -m memweave_eval.cli report "$replay_parent/run"
```

compiler根原report含失效旧zstd行，跨run总表必须按selection.json选择compiler两行与干净zstd两行。不要对原目录默认调用当前HEAD的report。新增finance-report需新目录，score-cases仍走既有CLI；方法与公式同时见experiments/有价值指标.md。
