# 35案例续接：WDM实际资源补采

本附记接续[INT-07采集修复与源题适配记录](FIXED35_CONTINUATION_2026-11-03.md)，仅记录无模型资源控制，不是35题模型实验成绩。代码检查点为`5de3cde266436ab547d625ed7cef7b81ae3f37f8`；此前Switch v8封存、旧账本、失败控制均不覆盖。

## 结果与来源

独立目录为`~/.local/share/memweave-experiments/fixed35-20261103/resource-controls-v4/completion-v2`。源题为已锁定TB4 `wdm-design`，保留原始指令、原始参考解、原始验证器和28800秒actor／1200秒verifier时限；派生资源对actor和独立验证环境均明确设置5 CPU、16384 MiB，原始为8 CPU、16384 MiB。此配置不是官方资源原样复现。

|无模型控制|原始验证器reward|actor实际限额|独立verifier实际限额|清理|
|---|---:|---|---|---|
|参考1|1|5 CPU／16 GiB|5 CPU／16 GiB|精确容器及空项目网络已删除|
|参考2|1|5 CPU／16 GiB|5 CPU／16 GiB|精确容器及空项目网络已删除|
|空解|0|5 CPU／16 GiB|5 CPU／16 GiB|精确容器及空项目网络已删除|

六份回执来自真实Docker `HostConfig`，不是请求配置推断。逐一核对完整容器ID、可信compose项目和main服务标签、冻结image ID、停止状态及`NanoCpus=5000000000`、`Memory=17179869184`。actor另有原控制执行前同步回执。控制使用Harbor公开`keep_containers`选项，仅为在控制结束后读取不可变实际限额；读取后删除各自精确匹配的停止容器和无容器连接的本项目网络，不改变全局电源、网络或安全配置。

Harbor 0.24.0 `SingleStepTrial._run()`先完成工件采集并停止actor环境，再运行独立verifier。因此本单阶段任务两阶段按资源峰值取5 CPU／16 GiB，而不是相加；两个参考控制并发完成。该结论不自动推广到多阶段或sidecar。此处只验证限额配置及参考／空解链路，未测完整模型求解时的峰值RSS，也不代表Agent已能在该资源下解题。

首版后处理错误地以`trial_name`查询actor项目，而实际Harbor创建的是`trial_name + '__env'`。两个原始参考控制本身已成功并保留停止容器；错误审计的`controller-end.json`与脚本留在v4根目录。`completion-v2`按实际控制前回执与已核实的Harbor源代码修正可信项目名，复用这两次原始结果完成只读审计，再执行此前尚未启动的空解。没有篡改原始reward或因后处理失败重跑模型。

旧`resource-controls-v3`controller的宿主进程状态仍未知，禁止查询的操作没有重试。其未创建的WDM目标已有独占取消目录，旧脚本不能在该路径继续启动WDM；这不等于声称旧controller已退出。

## 准入边界与费用

WDM这一派生配置的参考／空解实际资源证据缺口已补齐；它仍不是完整正式准入。35题仍缺部分独立业务gold／适用契约、跨Session／restart／token裁剪等独立oracle、Interrupt官方资产；付费canary的单独审批也仍待确认。已冻结的时钟不因资源控制通过而自动延长或缩短。未进行新的正式模型调用。

真实账本仍为2次尝试：已结算USD0.001342872、无usage未知预留USD0.3001536，敞口USD0.301496472。本阶段新增真实费用0；模拟请求／控制数量不计为长程千次API资格。正式仍0/35，不能提供35题真实数字评分表。

最终代码的实验回归615项、整仓`npm run check`276项、TypeScript、Rule资源一致性、Ruff及diff检查通过；本附记之后只有文档／封存元数据变化，不改产品、actor输入或评分逻辑。所有控制脚本、原始结果hash、实际资源回执与精确清理记录见上述`completion-v2/result.json`及`artifact-index.json`。
