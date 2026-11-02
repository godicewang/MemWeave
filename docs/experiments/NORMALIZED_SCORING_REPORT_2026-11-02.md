# 三个SWE-Marathon案例的百分制离线重算

用户于2026-11-02要求每项同时展示原始口径和满分100分的归一化分，并给两类及加权总分。此次只离线读取wasm-simd、rust-c-compiler、zstd-decoder的六个有效臂，不发模型请求，不重跑benchmark，不改原分、提示、模型代码、原始报告或账本。

## 如何读表

版本为normalized-20261102-v1。工程与行为各50%；公共产品profile用于同题两臂比较，插件运行策略与记忆行为profile仅用于完整插件，不能跨profile比总分。每项解释、原始公式、百分制公式、单位、固定权重、阈值依据、状态及来源均来自同一registry。170个目录行×6臂共1020行；计数和近义展示行不重复计权。

完整逐项表在新交付目录的normalized-scores.md、normalized-scores.csv及JSON，Registry与六臂精简JSON已另存Library供表格制作。原CSV只保留汇总列，避免把全部明细塞入单一超大字段。

## 固定profile的分层结果

|任务|组|profile|工程已知均分/覆盖|行为已知均分/覆盖|完整点总分|全部已知均分|固定权重覆盖|完整区间|
|---|---|---|---|---|---:|---:|---:|---|
|rust-c-compiler|pi-memweave|common_product|97.233146/60.0000%|15.979546/70.0000%|—|53.481208|65.0000%|[34.762785,69.762785]|
|rust-c-compiler|pi-memweave|plugin_memory|93.877248/47.0000%|—/0.0000%|—|93.877248|23.5000%|[22.061153,98.561153]|
|rust-c-compiler|pi-native|common_product|99.662776/45.0000%|17.992969/70.0000%|—|49.950719|57.5000%|[28.721664,71.221664]|
|rust-c-compiler|pi-native|plugin_memory|N/A|N/A|N/A|N/A|N/A|原生结构性不适用|
|wasm-simd|pi-memweave|common_product|89.316239/37.5000%|39.994963/100.0000%|—|53.446220|68.7500%|[36.744277,67.994277]|
|wasm-simd|pi-memweave|plugin_memory|95.267367/23.0000%|—/0.0000%|—|95.267367|11.5000%|[10.955747,99.455747]|
|wasm-simd|pi-native|common_product|96.585670/37.5000%|80.000000/100.0000%|—|84.523364|68.7500%|[58.109813,89.359813]|
|wasm-simd|pi-native|plugin_memory|N/A|N/A|N/A|N/A|N/A|原生结构性不适用|
|zstd-decoder|pi-memweave|common_product|99.047619/45.0000%|25.839793/90.0000%|—|50.242402|67.5000%|[33.913621,66.413621]|
|zstd-decoder|pi-memweave|plugin_memory|96.585366/41.0000%|—/0.0000%|—|96.585366|20.5000%|[19.800000,99.300000]|
|zstd-decoder|pi-native|common_product|99.152542/52.0588%|28.423773/90.0000%|—|54.343011|71.0294%|[38.599521,67.570109]|
|zstd-decoder|pi-native|plugin_memory|N/A|N/A|N/A|N/A|N/A|原生结构性不适用|

六臂完整点总分均为空，因为固定profile证据不完整；高已知均分不能解读为高完整质量。插件记忆profile行为类覆盖均为0：14个事后离线案例仅验证oracle，未倒填为模型成绩。区间下限是已证实贡献，不是unknown=0断言。

## 同题共同证据比较

|任务|共同权重覆盖|原生共同已知分|插件共同已知分|插件−原生|结论边界|
|---|---:|---:|---:|---:|---|
|rust-c-compiler|57.5000%|49.950719|47.413539|-2.537180|暂定，仅比较相同指标且双方可观察的权重|
|wasm-simd|65.0000%|83.630482|50.760425|-32.870056|暂定，仅比较相同指标且双方可观察的权重|
|zstd-decoder|67.2794%|51.798195|50.097998|-1.700198|暂定，仅比较相同指标且双方可观察的权重|

例如compiler插件自身条件均分高于原生，部分原因是它观察到了更多工具槽位；换用共同证据范围后插件较低。不能拿不同覆盖的条件均分直接判胜。三题的区间/贡献/覆盖按任务各1/3，非按31767、894、43个测试或请求数赋权；另列task_macro_observed_score等权平均各任务条件均分。

## 关键逐项示例（完整170项见长表）

|指标含义与原始公式|满分100转换/权重依据|wasm原生/插件|compiler原生/插件|zstd原生/插件|
|---|---|---|---|---|
|原题正式得分：unmodified original verifier reward|100*x；总权重{"common_product": 0.19999999999999998, "plugin_memory": 0}；比例合法域[0,1]；不裁剪异常值|raw=1.000000 → 100.000000 (scored,覆盖100.0000%)<br>raw=0.000000 → 0.000000 (scored,覆盖100.0000%)|raw=0.000000 → 0.000000 (scored,覆盖100.0000%)<br>raw=0.000000 → 0.000000 (scored,覆盖100.0000%)|raw=0.000000 → 0.000000 (scored,覆盖100.0000%)<br>raw=0.000000 → 0.000000 (scored,覆盖100.0000%)|
|原题细分通过比例：original passed/original total|100*x；总权重{"common_product": 0.09999999999999999, "plugin_memory": 0}；比例合法域[0,1]；不裁剪异常值|raw=1.000000 → 100.000000 (scored,覆盖100.0000%)<br>raw=0.999748 → 99.974817 (scored,覆盖100.0000%)|raw=0.629754 → 62.975391 (scored,覆盖100.0000%)<br>raw=0.559284 → 55.928412 (scored,覆盖100.0000%)|raw=0.279070 → 27.906977 (scored,覆盖100.0000%)<br>raw=0.162791 → 16.279070 (scored,覆盖100.0000%)|
|原题受保护文件约束：已冻结保护约束必要断言全部通过为1，否则0；未登记则缺评估机会|100*x；总权重{"common_product": 0.1, "plugin_memory": 0}；比例合法域[0,1]；需固定gold及证据|raw=0.000000 → 0.000000 (scored,覆盖100.0000%)<br>raw=0.000000 → 0.000000 (scored,覆盖100.0000%)|raw=— → — (unknown,覆盖0.0000%)<br>raw=— → — (unknown,覆盖0.0000%)|raw=1.000000 → 100.000000 (scored,覆盖100.0000%)<br>raw=1.000000 → 100.000000 (scored,覆盖100.0000%)|
|原题公开测试过程谓词：已冻结完整公开命令/测试回执谓词通过为1，否则0；不等同通用从未测试|100*x；总权重{"common_product": 0.05, "plugin_memory": 0}；比例合法域[0,1]；需固定gold及证据|raw=1.000000 → 100.000000 (scored,覆盖100.0000%)<br>raw=1.000000 → 100.000000 (scored,覆盖100.0000%)|raw=0.000000 → 0.000000 (scored,覆盖100.0000%)<br>raw=0.000000 → 0.000000 (scored,覆盖100.0000%)|raw=0.000000 → 0.000000 (scored,覆盖100.0000%)<br>raw=0.000000 → 0.000000 (scored,覆盖100.0000%)|
|bash 工具错误率：真实工具错误回执数 / 工具尝试数；有未知结果时原标量空，另给已知子集分及全尝试区间|100*(1-x)；总权重{"common_product": 0.0375, "plugin_memory": 0}；比例合法域[0,1]；不裁剪异常值|raw=0.037383 → 96.261682 (scored,覆盖100.0000%)<br>raw=0.034188 → 96.581197 (scored,覆盖100.0000%)|raw=0.020233 → 97.976654 (scored,覆盖100.0000%)<br>raw=0.021348 → 97.865169 (scored,覆盖100.0000%)|raw=— → 93.750000 (partial,覆盖94.1176%)<br>raw=0.057143 → 94.285714 (scored,覆盖100.0000%)|
|准备边界State最新版本一致：passed eligible mechanical checks/known eligible checks; coverage separately|100*x；总权重{"common_product": 0, "plugin_memory": 0.1}；比例合法域[0,1]；不裁剪异常值|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=— → — (unknown,覆盖0.0000%)|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=1.000000 → 100.000000 (scored,覆盖100.0000%)|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=1.000000 → 100.000000 (scored,覆盖100.0000%)|
|完整事件Window保真：passed eligible mechanical checks/known eligible checks; coverage separately|100*x；总权重{"common_product": 0.075, "plugin_memory": 0.025}；比例合法域[0,1]；不裁剪异常值|raw=— → — (unknown,覆盖0.0000%)<br>raw=— → — (unknown,覆盖0.0000%)|raw=— → — (unknown,覆盖0.0000%)<br>raw=— → — (unknown,覆盖0.0000%)|raw=— → — (unknown,覆盖0.0000%)<br>raw=— → — (unknown,覆盖0.0000%)|
|引用scope/版本/内容保真：passed eligible mechanical checks/known eligible checks; coverage separately|100*x；总权重{"common_product": 0.05, "plugin_memory": 0.025}；比例合法域[0,1]；不裁剪异常值|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=— → — (not_applicable,覆盖0.0000%)|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=— → — (not_applicable,覆盖0.0000%)|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=— → — (not_applicable,覆盖0.0000%)|
|显式逻辑操作recovery：external-state confirmed recovered eligible operations/eligible operations|100*x；总权重{"common_product": 0.05, "plugin_memory": 0.05}；比例合法域[0,1]；不裁剪异常值|raw=— → — (unknown,覆盖0.0000%)<br>raw=— → — (unknown,覆盖0.0000%)|raw=— → — (unknown,覆盖0.0000%)<br>raw=— → — (unknown,覆盖0.0000%)|raw=— → — (unknown,覆盖0.0000%)<br>raw=— → — (unknown,覆盖0.0000%)|
|F/D新增密度：实际JSONL累计新增Fact/Decision条目数 / 原始Session带usage对象assistant返回R；含modify_fact的新Fact，不含Goal/归档/重放|100 if .05<=x<=.10; 100*x/.05 if x<.05; 100*.10/x if x>.10；总权重{"common_product": 0, "plugin_memory": 0.015}；既有诊断策略区间[0.05,0.10]，非普适最优值|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=0.068571 → 100.000000 (scored,覆盖100.0000%)|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=0.024803 → 49.605411 (scored,覆盖100.0000%)|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=0.026667 → 53.333333 (scored,覆盖100.0000%)|
|成功写批次间隔均匀度：成功新增F/D写批次返回位置p的内部间隔d_i=p_(i+1)-p_i；总体std(d)/mean(d)，至少2间隔且均值>0|100/(1+x)；总权重{"common_product": 0, "plugin_memory": 0.01}；CV>=0，至少两个内部间隔；连续有界变换，无经验告警阈值|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=0.568467 → 63.756534 (scored,覆盖100.0000%)|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=0.763444 → 56.707221 (scored,覆盖100.0000%)|raw=— → — (not_applicable,覆盖0.0000%)<br>raw=— → — (insufficient_sample,覆盖0.0000%)|
|输入缓存利用率：cache/input|100*x；总权重{"common_product": 0, "plugin_memory": 0}；比例合法域[0,1]；不裁剪异常值|raw=0.997635 → 99.763530 (scored,覆盖100.0000%)<br>raw=0.973193 → 97.319346 (scored,覆盖100.0000%)|raw=0.999165 → 99.916504 (scored,覆盖100.0000%)<br>raw=0.967766 → 96.776617 (scored,覆盖100.0000%)|raw=0.938588 → 93.858784 (scored,覆盖100.0000%)<br>raw=0.975005 → 97.500490 (scored,覆盖100.0000%)|
|插件相对原生费用指数（原费用比单列）：plugin estimated USD/native estimated USD; match task/model/price/USD|100*C_native/(C_native+C_plugin) = 100/(1+r)；总权重{"common_product": 0, "plugin_memory": 0}；相对费用指数，同费50；非节省率或质量收益|raw=1.114725 → 47.287474 (scored,覆盖100.0000%)<br>raw=1.114725 → 47.287474 (scored,覆盖100.0000%)|raw=0.412857 → 70.778581 (scored,覆盖100.0000%)<br>raw=0.412857 → 70.778581 (scored,覆盖100.0000%)|raw=2.829923 → 26.110185 (scored,覆盖100.0000%)<br>raw=2.829923 → 26.110185 (scored,覆盖100.0000%)|

细分通过率由原验证器passed/total精确计算，不采用已经舍入的pass_rate/partial_score标量；官方原reward保持。费用指数是同题配对指标，两个臂重复显示同一值，非两个独立臂质量分。

## 映射与缺失处理

- 成功率100p、错误率100(1−p)。部分工具s/f/u：观测分100s/(s+f)、覆盖(s+f)/(s+f+u)、区间[100s/N,100(s+u)/N]。例如zstd原生Bash保留17次尝试/1错误/1未知，不把未返回补成功。
- 密度在[0.05,0.10]得100，区间外按与边界比例衰减；含modify_fact新Fact，不含Goal/归档/幂等重放。CV为100/(1+CV)，至少2个内部间隔且均值正；首段/尾段单列。两项合计总权重2.5%，可被无价值写入游戏，属于策略分而非语义价值。
- 缓存分为100hit/input；费用指数100Cn/(Cn+Cp)，同费50。它们权重0，不奖励低质量低费。三题费用先加和再转换，不能平均指数；总费用指数64.308298。
- 纯诊断计数没有固有优劣，没有预登记目标则保留原值、分数空、权重0。未知、无机会和invalid不伪造成0/100，不在已知子集上自动重分全部权重。
- 同一正确性族binary/partial分配2/3及1/3，不重复宣称独立正确性；回执下界不与严格新鲜度重复计权；案例AND与子断言、fixture结果不重复加权。

## 实测覆盖与不能推出的结论

wasm严格State准备边界仍unknown；后两题可核验版本。三题独立Window gold缺失，引用无实际读取机会保留覆盖缺口，逻辑operation映射缺失，不能推测重试率。Task检索/恢复等无预登记自然机会，不把夹具通过变成模型100分。

wasm两臂已违反保护文件要求，其保护约束分为0。插件在驱逐前已经修改，旧跨窗代理0不能归因为遗忘或记忆采用率0。原题结果与任务完成质量始终单列，不能由综合分掩盖这些已知失败。

## 代码、测试与复现

实现检查点6f468712ef09b3625df95bad1055b7dd423b8e04。新增score_catalog.json、normalized_scores.py、score_report.py，经现有report/campaign自动写原始+分数JSON、长CSV/Markdown及固定family→leaf权重CSV；新增CLI score-report生成独立历史补充。

最终完整免费回归348 passed（完整免费回归）；Ruff、npm run typecheck和git diff --check通过。先修复了超大CSV字段，保留此前失败日志；没有再跑付费模型、benchmark或完整付费发布验收。产品src/resources/docs/specs/预算/窗口未改。

完整新目录：`/Users/godice/.local/share/memweave-experiments/analysis/normalized-three-cases-20261102/v2`。provenance.json记录17个输入文件hash并复核原raw-index；artifact-index.json记录新工件。原有效/无效run、raw、旧报告和两个预算账本保持。

```sh
PYTHONPATH=experiments/src experiments/.venv/bin/python -m pytest experiments/tests -q -o addopts=''
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli score-report \
  /Users/godice/.local/share/memweave-experiments/analysis/normalized-three-cases-20261102/v2/six-valid-arms-input.json \
  --output /tmp/memweave-normalized-recomputed-new
```

输出目录必须不存在。新实验原report/campaign流程自动生成；历史必须用新目录，禁止对旧run默认重写report。

当前会话没有MemWeave State/Task专用工具，执行前State核对/新任务记录未执行，未通过Bash改写State；这是工具可用性限制，不影响已完成的离线实现。

最终审计补充：细分通过计数0/0为N/A，缺passed或total为unknown，负值或passed>total为invalid；CSV保留observed_raw及s/f/u/n，Markdown逐行也展示已知原比率与分子分母/未知数。相同campaign槽位但实际任务或模型不同不做配对比较。v1生成记录保留，最终增强表在v2新目录，未覆盖旧原始报告。
