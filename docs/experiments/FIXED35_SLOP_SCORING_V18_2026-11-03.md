# Slop原始与派生评分分列

已有Slop适配保留原报告计数与严格全测试AND，同时额外计算固定条件跳过后的适用测试AND。数据库迁移第3–5阶段可出现原始86/87、原严格0、派生100。后者不能填入原始结果列。

本切片只修评估数据来源：现有`fixed35 report`的`S3.original_reward`读取`original_all_reported_tests_AND`，派生`score`单列为`slop_score_channels.derived_applicable`；缺原字段保持未知，不回退至派生分。原始严格口径是本系统对全部原报告测试组的冻结AND，不冒称Slop官方榜单唯一分数。原题、测试、固定条件跳过规则和模型可见内容均不改。

提交缺少原题必需文件且交接明确完整时，原始和派生口径均为已知0；不制造测试通过数或假装执行过原测试。未完成／基础设施故障仍区分已知失败与缺证据。非法分值（布尔、负数、非有限、非二元）拒绝导入，不能裁剪成0或100。

逐项映射版本进入v18，旧v17、旧Slop控制／报告不覆写。先用原始0／派生100、缺字段、非法值及必需文件缺失的测试验证，再通过现有报告入口输出两臂同口径JSON／CSV／Markdown。控制验收仍不等于模型成绩，正式运行与整题业务gold仍未完成。

687项完整实验回归通过；另以实际`single_report`验证JSON原始0／派生100、主指标CSV、独立通道CSV和Markdown，缺原分时维持unknown。原文件保持哈希不变的36个既有verifier控制也已逐项重算，独立输出为仓库外`fixed35-20261103/slop-score-provenance-v18`：

|源题|控制|检查点数|原始严格分|派生适用分|
|---|---|---:|---:|---:|
|circuit_eval|reference|8|100|100|
|circuit_eval|nop|8|0|0|
|database_migration|reference|5|0|100|
|database_migration|nop|5|0|0|
|trajectory_api|reference|5|100|100|
|trajectory_api|nop|5|0|0|

每点沿用固定的原测试组AND，表中控制不是原生／插件模型臂，不能拿reference当插件结果。未运行容器或付费模型；真实账本仍保持`fabfce853c8b8beb43fb840f6eba8992b1fc4c48dd2a550ac4183d7f8b20c029`，正式0/35。旧清单有缓存评分时比对JSON规范化结果；没有缓存评分的条目只读其实际原报告重算，不默认旧分为0或100。

后续预检还复现正式`score_pair`错误使用上一轮固定截止`1793661132`的问题。修复只读取当前admission已哈希冻结的campaign `container_cutoff`，供纯程序verifier使用；缺失／变化的campaign证明在创建评分目录或启动verifier前拒绝。两臂同一截止，并在输出中记录campaign hash及截止来源。不修改现有campaign时钟、API额度或源测试；程序verifier仍预留既有15秒边界及每点900秒上限。
