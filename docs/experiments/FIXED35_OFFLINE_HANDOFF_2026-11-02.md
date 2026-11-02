# 固定35案例：离线实施交付与未完成范围

本轮没有完成35题原生／插件正式配对，不能给出实测百分制或有效加权总分。正式配对数为0、正式臂数为0、整包采集验收为false。下列交付是现有实验系统的工程实现、无付费预检和诚实的未运行矩阵；不是模型能力成绩，也不是官方榜单结果。

实现检查点为`1d4a64f84b46caf0d57d97a7853b86102bcacd7e`，此前阶段检查点`865e5cf`、`68cbf95`等保留。最终文档提交与实现检查点的差异只在交付说明。没有push、发布、重跑旧benchmark或覆盖原始轨迹、旧报告、账本。

## 可读取的交付

独立目录：

`/Users/godice/.local/share/memweave-experiments/fixed35-20261102/offline-final-v4-20261102T2140Z/`

- `summary.json`：35题逐题就绪状态、家族未实现项、计费、测试、截止及验收状态；SHA256为`aec6d1beb22e90e146be0c5369b29b7d99774c04aeb7a81ab4b1be38c91a128f`。
- `sources/`：35个固定选择器与源hash、新版5950格适用矩阵、35个`DRAFT_NOT_ADMITTED`契约和`pack-draft.json`。
- `unrun-package/`：由既有`fixed35 pack-report`生成的11900格双臂JSON、逐项raw/公式/分数/状态CSV、插件与原生35题宽表、同口径比较表。实际结果单元格为0；没有把未运行填成0分或满分。
- `switch-source-components/`：INT-06/07源绑定契约、已有reference/nop原验证器结果重放和缺证据负例。最终交付检查点没有实际assistant答案，故仍缺证据；原业务测试控制分别为100／0，不能算模型或Task成绩。
- `slop-control-audit.json`：36项控制的原始与派生口径、原报告hash、停止状态。
- `artifact-index.json`及`external-proof-index.json`：本次补充包及引用的原预检证据索引；原证据不变。
- 测试XML/日志、仓库检查日志及仅组装离线材料的`assemble-offline-v4.py`。

便于父任务读取的小型摘要已保存到Library：`MemWeave_35案例离线交付摘要_20261102.json`，`library_file_id=libfile_07508bc106bc8191af3a11488e2ac27b`，对应同一summary SHA256。没有上传原始Session、凭据或隐藏测试／答案。

## 工程实现与边界

现有`memweave-eval fixed35`入口已接入source、run、schedule、replay、report、pack-report、STATE/MAB/Task组件，以及新增Switch源组件。包括真实Pi CLI的假provider验证、reserve→request准备→响应→settle关联、VM单一额度权威、actor／模拟用户／官方judge共账、独立截止、资源队列、CAS内容重放、State演化、Task持久记录、已知U/A文本引用、raw与百分制两种输出。

关键修正是研究建议不再被误当作完整不适用清单：新版5950个case×metric单元格中3673个计划测量、2032个设计待完成、245个明确旧题专属NA。按角色区分2695个有评分含义的单元格、3010个原始诊断单元格和245个旧题专属项。这些数量不代表实现完成率，更不代表2032个独立功能；每题都还有未解决设计。原生插件专属指标另作结构性NA。

结果不能自行将计划／未解决项目降成NA。整包读取报告必须匹配case、文件hash、契约hash／版本、报告schema／evaluator版本、逐项mapping版本和完整双臂集合。缺证据、未运行和未解决设计会阻止采集验收和点总分；条件均分必须和覆盖率一起解释。不可恢复采集例外需原因及已尝试修复，不能借用`-`语义。

评分仍采用预冻结分层权重；每指标先在benchmark内对有效case取均值，再对有效benchmark均值取宏平均。每个检查点的必要程序断言AND，再在预定义机会内汇总；不会把全题不同指标合成一个AND。纯诊断计数没有内在优劣方向，不作为能力满分。本轮没有真实数据，所有模型总分为空。

## 逐家族实际范围

|家族|选题数|无付费已完成|尚未完成，不能宣称正式准入|
|---|---:|---|---|
|TB4|12|固定源、全部原题reference/nop控制与双臂Pi软件预检；TB-04 read-only检查点|其余11题独立业务／记忆gold；故障、生命周期、引用、真实驱逐机会和完整契约|
|Slop-Code-Bench|3|8／5／5公开阶段、持久Session与源码交接、官方eval-snapshot入口、36项2CPU／8GiB控制|逐阶段重要State、保全／纠错gold与完整配对准入|
|STATE-Bench|5|原domain程序控制5／5、逐题业务AND、实际domain IPC、host后置官方judge入口|INT-04同权威冲突overlay；State层更新／及时性gold；新额度服务下真实actor／辅助canary|
|Switch-SWE|2|原题控制；16／19阶段路由台账、返回点、源响应ID与原F2P/P2P绑定；通用真实Pi Task／引用工具预检|选题实际Task语料种子／Goal语义与排名gold、首个关键动作恢复、简单插话overlay和完整actor接线|
|InterruptBench|3|固定源选择器|官方资产下载／访问门禁、浏览器环境、60%回放协议与业务断言|
|MemoryAgentBench|8|split+row+context hash+QA选择器；原QA／typed-action；4个有限字面纠错组件；双臂CLI|书籍高价值信息gold；三次真实eviction与对应快照；隔离压力参数冻结|
|SWE-Marathon|2|原题起点、原验证器reference/nop及双臂Pi软件预检|长程业务／记忆gold与完整执行；Ruby原资源配对只能公平顺序调度|

通用剩余项还包括受控无效输入／原子性／幂等机会的全包调度、独立完整Rule期望、完整Window选取策略oracle、所有引用类型与若干S1/S2语义机会。已有helper、合成正反例或测试通过不等于逐题适配完成。

五个长程候选为TB-07 mp-checkpoint、WDM、模拟UEFI防御清理、Kubernetes Rust、Ruby Rust；本项目成功且≥1000 unique主模型API调用资格均为`NOT_RUN`，当前计数0。不会用mock、工具、judge、输入token或多次重跑累计凑千次，也不把高效少于千次当能力失败。

## 控制结果必须保留的差异

Slop的36项“控制接受”包括预期失败的nop，并非36个正确解全部通过。database_migration的3–5阶段有一个源码明确只适用于1–2阶段的skip，上游runner仍把它计入total：

|阶段|原reference通过／总数|原严格分|派生全部适用测试分|
|---|---:|---:|---:|
|checkpoint_3|86／87|0|100|
|checkpoint_4|116／117|0|100|
|checkpoint_5|136／137|0|100|

原测试、原总数、原严格0和原JSON均保留；派生分只排除这一个有固定源码证据的条件不适用项，未知skip不排除。不能把派生36项预检称为官方全部通过。

Switch INT-06最终原题测试是4个F2P加35个P2P；INT-07是6加44。源响应ID、原评分器逻辑ID与运行时MemWeave Task ID是三种身份。已有通用Task CLI的正确绑定、State交付和动作fixture不证明两道选题已正确恢复工作；源业务测试通过也不能作记忆采用率。

## 实际验证、费用与停止

以下命令针对最终实现候选实测：

```sh
PYTHONPATH=experiments/src experiments/.venv/bin/python -m pytest experiments/tests --junitxml=/tmp/memweave-35-20261102/tests-v4-seal.xml
npm run check
experiments/.venv/bin/ruff check experiments/src/memweave_eval/fixed35*.py experiments/tests/test_fixed35*.py
git diff --check
```

结果为483项Python测试通过；资源／TypeScript／单元／集成276项通过；受影响Ruff和差异检查通过。最初默认沙箱中的4个localhost fixture因端口bind权限报错，走工具审批后同一离线套件全部通过；没有改变网络／安全设置。未运行真实模型、官方收费judge、完整35题正式配对或发布验收。

独立USD20预算账本仍只有之前6笔已结算canary，已知费／敞口均为USD0.00227448，预留0；本离线收尾阶段新增模型请求0。mock账本数字不计入真实费。原USD19硬闸加USD1安全余量保留，没有重置账本。actor截止20:20:12、judge23:12:12、容器23:22:12、用户硬截止23:42:12 UTC均未延长。最后只读Docker核验本任务标签下无残留容器；本阶段没有启动actor、watchdog或额度服务。

新付费请求此前被自动审批拒绝：目标是向已配置DeepSeek发送新的Pi actor／模拟用户／judge／canary请求，所需外发内容、目的地和花费确认由父任务询问后仍待答复。该拒绝动作没有重试或换路径。与此同时，逐题gold与部分适配确实未完成；即使确认及时返回，也不能把目前工程描述成完整35题就绪。现在冻结actor窗口已过，不能未经新授权延长。

当前执行环境未暴露State专用工具，无法通过其更新任务State；没有用Bash直接改运行时State。产品`src/`、Rule资源、prompt和预算实现没有本轮改动。

## 无模型复现

在实现检查点或仅多出交付文档的最终提交中，使用明确新目录：

```sh
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli fixed35 sources /tmp/memweave-35-20261102/library/MemWeave_35案例选题与指标映射.json --sources /tmp/memweave-35-20261102/sources --output /tmp/fixed35-new-source-draft
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli fixed35 pack-report /tmp/fixed35-new-source-draft/pack-draft.json --output /tmp/fixed35-new-unrun-report
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli fixed35 switch-contract INT-06 --source /tmp/memweave-35-20261102/sources/switch --output /tmp/fixed35-new-switch-contract.json
```

`sources`验证批准设计hash和全部源pin；`pack-report`生成完整未运行表，不启动模型。源材料来自已验证的Library文件，不把不存在的云端路径当作本机数据。完整补充包的`assemble-offline-v4.py`可向另一个新目录重放本机保存的控制证据。`run`／`schedule --execute`不是本轮可执行复现入口：正式准入、授权与冻结时间条件均未满足。
