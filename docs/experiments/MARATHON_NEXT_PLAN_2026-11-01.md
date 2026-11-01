# 第二批Marathon配对：冻结前实施方案

用户2026-11-01T17:50:13Z授权：本次总额20USD，硬截止2026-11-02T05:50:13Z；两题zstd-decoder/rust-c-compiler各原生Pi与完整插件，不改旧run或旧账本，不推送发布。当前开发检查点1b388340ffcfd9b0680c009cdfff590b47fa7a1a，工作区初始干净。

## 排程、资源和费用

拟四臂同时运行，各2CPU/8192MiB/20480MiB；同题公平一致，合计8CPU/32GiB，预检必须证明本机12CPU/约41GiBVM可承载。相对原题4CPU/16GiB是明确的资源适配，不称官方原样复现。zstd原5h、compiler原10h，compiler verifier为40分钟；模型绝对截止须按最长verifier加报告/清理余量动态预留（至少65分钟），不沿用旧25分钟。若启动太晚，缩短的有效上限必须冻结、两臂一致并披露。

新budget_id与旧任务完全分离。准入19USD、安全1USD，四个(task,variant)累计子额各4USD，剩余3USD不自动转给任何臂。每题短canary每臂最多1次、小输出，所有重试/压缩/失效尝试计入同一新账本。模型deepseek-flash、thinking off、输出16384；当日官方峰值input miss0.30/cache hit0.006/output1.20 USD/M再次核验。费用是保守估计，不是账单。

固定上游仍dd4d2bbc8d2ec8bb22fc4a4261d3b0c827faa2a4。compiler task.toml旧文字称连续reward，但该提交tests/run_tests.py实际SCORING_MODE=binary，并另出partial_score；按实际冻结verifier代码报告，不换main、不改评分器。

## zstd封闭边界

原题禁止解释器和任何现成zstd实现；Pi所需Node24本身含zstd接口，Python守卫也不应加入任务。拟采用Node评估配套和原子flock；不装Python或codec库。正式评分在原官方干净镜像中交接保存的C源码、构建产物和原Makefile（原verifier要求已存在的二进制，不替模型自动构建），Pi/Node/认证/评估资产不进入验证环境；业务源码逐字移交，不修答案。保全所有其他原件并审计禁止的运行时依赖，不把它们作为合法C99解题能力。

需以负例证明直接Node codec、去掉preload、复制/改名运行时等不能通过干净验证边界；原verifier及Makefile/libxxhash限制保持。封闭环境恢复及额外控制平面本身属于适配，必须在报告列清，不声称原环境完全未变。此门禁未过不得付费启动zstd。

## 指标与验收

主cache比=明确供应商cache-hit input / total input（已含cache），辅助cache/(input+completion)。缺失unknown、显式0有效、零分母N/A，负值或cache>input invalid。任务/臂与总体均用token加权和。

费用比=同任务/模型/价格/货币插件估算USD / 原生估算USD，附百分比及ratio-1；零原生N/A，缺项unknown。总比用匹配任务两侧费用和，不平均比值。正式配对与含重跑/预检的运营费用分开。

接入既有report与campaign、JSON/CSV/Markdown和价值指标文档。旧wasm仅生成新独立补充目录，不覆写旧reports。复用P0/State/Task程序案例、真实CLI正/丢守卫零上游负例、PID/精确容器停止、原题reference/nop、四臂同时资源烟测、正式环境短canary，完成后才冻结并发launch。持续监控直至四臂和verifier终态。

## 预检发现与冻结修订

compiler原始参考解在2CPU8GiB与4CPU16GiB均893/894，因extern大数组被错误定义，生成程序退出137。隔离参考fixture首次通用extern修正892/894（保留），缩小到超UINT_MAX的extern存储修正后894/894、原verifier binary1。正式source/verifier不改，原oracle原始结果仍0，准入冻结这个已知结果并要求独立known-good控制1的hash凭证。修正源码不进入正式镜像/挂载/缓存。

zstd独立verifier首次source-only交接导致reference/nop都decoder not found，未通过。原测试脚本不执行构建，因此冻结修订为交接原模型已构建二进制及源文件（排除.o），不自动替agent编译；对原件完整归档后移除可识别的复制/改名Node ELF，原Makefile与业务C字节不改。正式评分仍用原验证脚本。该适配不提供额外codec，不宣称抵抗任意恶意混淆或与原环境完全等价。

## 冻结门禁与观测覆盖

离线实验单测290通过；两题专属谓词分别覆盖正/负/缺证据。产品完整Node24 `npm run check` 276项通过（默认shell Node23那次出现4个失败并中断，已改用与实验一致的Node24复验）；原有14个C/Task独立夹具保持，不能把未自然发生的Task find/resume当本题实测。真实Pi1.4+完整包、Node24.22、四臂2CPU8GiB免费CLI预检均零外部模型请求，含原生4工具/插件完整工具、Rule/State实际交付、guard丢失上游0、独立Linux PID deadline；Node双进程flock全球1美元mock准入只准1个0.7608预留，不计为真实花费。两种镜像实际Docker ID完成pause/unpause/stop确认，未触及其他容器。

State严格准备边界可测（当前绑定的已提交journal版本+hash，实际payload messages必须匹配），最新版本在之后并发变化标unknown；已有回执下界仍分列。最终provider→HTTP投影与tool call/result配对可测；这不是独立Window选择策略金标。引用输出保存scope/版本/投影hash/范围元数据，独立原件投影无法由所有混合/截断/附件情况统一安全重建时仍unknown；没有读取机会N/A。逻辑操作恢复仅接受明确op_id，通用自然工具重试没有op_id时unknown，不以相似参数猜测。开放文本的“是否有价值”不是通用字符串评分器。

正式前每臂最多1次128输出token真实canary，沿相同CLI/模型/dispatcher/镜像/ledger挂载路径；4个(request_ready/reserve/http/settle)必须与新账本对应，否则不开始正式运行。正式与canary按episode区分，四臂取最小剩余额作为相同准入余量，累计各臂仍不超过4USD，全球19USD，额外1USD安全不自动使用。每次请求在最坏input miss+max output额度准入后才读取私有key注入，SDK只有占位key。

原生保留原生自动compaction和默认上下文；插件启用当前Rule/State/Window、禁用原生compaction和实际弹性预算机制，因此是产品整体对照，不是相同有效窗口的State消融。相同模型thinking off、16384最大输出、同题资源和时间政策；所有provider重试/原生compaction计费。双方第80个usage对象assistant返回时各仅一次相同进度询问（概要：简短汇报后继续任务），有额外模型可见输入，属于原题适配对照，不称官方原样榜单。业务保护/公开验证按冻结case评分，State约束保留为明确代理，不冒称采用率或因果记忆收益。

正式模型绝对停止2026-11-02T04:45:13Z，容器最后停止05:48:13Z；最长原verifier40分钟，另留报告清理。若实际launch晚于18:45:13，compiler实际可用时限短于10h，最终记录实际启动和有效时限，不以题面10h冒充实际。临时caffeinate仅随本次runner生命周期，结束释放，不改电源设置，不能保证合盖不休眠。

父任务末轮复核要求增加最终验收余量：模型截止再提前15分钟到04:45:13Z（总65分钟），同题两臂一致；最长40分钟verifier可并行执行，至少25分钟用于交接、报告和清理，不超用户05:50:13。zstd原verifier不build的事实已通过首次失败控制确认，因此必须接收原agent构建二进制；这与“仅源码”措辞不同，原始完整源码/产物先归档、Node控制运行时清理后交接，禁止混入预检oracle二进制。原评分器不改。
