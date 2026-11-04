# v34：交接证据、内部时钟与仍未完成的准入

本轮完整实验仍未完成：正式0/35、模型结果单元格0、两张真实百分制表和加权能力总分未交付。沿用v32／v33全部未完成说明；35个有限源题组件不是35题完整实现，不以测试数量或参考解分数替代模型成绩。

## 交接修复

Slop原host evaluator遇完整提交快照缺`requirements.txt`／原入口时，已知原严格0，但原件只有内存判定、无可重放路径。v34独立落盘source problem／checkpoint、必需文件和交接manifest哈希，沿现有source_evidence report／sha字段供source业务组件消费。任一身份错误、回执缺失／损坏／哈希不符仍unknown并阻止采集验收；完整缺原必需文件则必要交付失败0，原测试全部未执行，不伪造测试断言失败。旧格式不无证升级。

两个源题26个原程序阶段控制按新版本重放，原分／派生分不变。另六个纯合成交接工件通过实际host reader及CLI：完整缺入口0，缺receipt和坏receipt均unknown；没有Actor、容器verifier或模型请求。这只证明工件管道，不能填模型分。最终924项完整离线pytest、40项组件／来源／报告边界、Ruff和diff检查通过。产品／TS输入未改，旧276项npm检查未冒称再次执行。

## 22:30的具体依据和含义

实际冻结文件`fixed35-20261103/campaign.json`为：

|字段|UTC|含义|
|---|---|---|
|started_at|11-03 02:44:57|用户24小时起点|
|model_cutoff|11-03 22:30:00|内部Actor新模型请求停止|
|judge_cutoff|11-04 01:30:00|内部辅助judge／额度服务截止|
|container_cutoff|11-04 01:45:00|内部容器停止|
|hard_deadline|11-04 02:44:57|用户总截止|

22:30是初期人为冻结的保守内部切片，不是用户要求，也不是所有题唯一推导出的开始时间。差值是3小时judge余量、15分钟容器余量、59分57秒清理／报告余量；这是配置差值，不能宣称所有短题都必须如此预留。

真实`fixed35_schedule.pair_policy`按题另算：`latest_pair_start=min(model_cutoff-actor_span, container_cutoff-total_span)`。setup每臂120秒；完整源逐阶段Actor还扣中间verifier；总span含全部verifier，同机无法双臂并行则乘双臂并留顺序开销；Slop verifier按900秒×阶段数。因此22:30甚至不是统一的“Actor最晚启动”。正式入口先校验完整合同、当前双臂真实canary、代码／包／资源／预算，再看该题latest_pair_start。

未使用的内部时钟可在用户截止内以新版本、等政策、完整准入前提重新冻结，不能把内部钟当用户撤销授权，也不能为凑题数静默截短长程题。此次campaign和旧ledger没有改；特定辅助JSON canary重试的审批拒绝也未绕过。

## 当前为何没有可正式执行的配对

最新完整期望11900单元格：NOT_RUN5782、DESIGN_NA3782、DESIGN_UNRESOLVED2336；采集验收false。一次case×metric轴的未解决项含1646个能力口径、333个原始诊断；两臂投影因原生插件专用NA不同，不能直接把这两个数乘2当2336。

按冻结固定权重核查，35题的common_product与plugin_memory均仍存在正权重未解决项。不是只剩零权重诊断，也不是只缺被拒的STATE调用。各题完整记忆／机会／生命周期gold、真实环境及当前完整CLI／canary准入仍未闭合。只有完成这些条件且完整公平时长仍可容纳，才可按既有授权运行；不把假provider、原题参考控制或裸模型回答算正式配对。

账本结算USD0.001342872、未知预留USD0.3001536、敞口USD0.301496472不变；本段新增付费0、未知未释放。用户总预算20美元、总截止11-04 02:44:57 UTC保持。Coordinator State工具仍不可用，未用Bash直改；Library上传、宿主进程查询、辅助JSON重试的既有拒绝未重试。旧宿主controller仍unknown，精确本任务Docker标签为空只证明对应容器不活动。

原始值、0–100公式和加权状态表已由既有report／pack-report产生，仍是未运行状态，不是用户要求的两张成绩表。新版本输出和完整索引独立封存，旧v30／32／33不覆盖。没有push、发布、付费测试或题目／原verifier改动。
