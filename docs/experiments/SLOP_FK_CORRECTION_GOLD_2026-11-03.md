# SCB-02源题外键反证与中途记录

选择已选Slop database_migration的真实规范演进：checkpoint_1要求迁移时`PRAGMA foreign_keys = OFF`，checkpoint_3改为每次迁移开始启用`PRAGMA foreign_keys = ON`。原第1/2阶段规则及第3阶段反证均由固定源文本／hash支撑，不能将旧OFF无范围地继续当当前指导。旧检查点的适用测试／原严格0仍按既有v18口径单列，不改源测试。

派生公开协议仅追加通用紧凑记录语法：如有State工具，外键规则卡使用`{"r":"fk","v":"ON或OFF","lo":起始检查点,"hi":结束检查点或null}`，值必须来自当时已提供的规范。JSON本身小于100字符；不提供未来值、参考实现或测试答案给正式Actor。原生收到相同条件说明但没有State工具，插件专属记录分原生NA。

独立检查点分别计分，不将整题所有不同指标AND成一个分：

1. 初始记录：第2阶段首次持久源码变化前（若无变化则该阶段完整结束边界），存在适用于checkpoint_2的正确OFF卡，且无相反当前typed卡。
2. 反证更新：第3阶段同类依赖边界前存在正确ON卡，所有适用于checkpoint_3的未归档typed卡均为ON。旧OFF可以归档，或被替换成明确仅适用1–2阶段的历史卡；仅移出显示窗口不能替代失效。
3. 当前业务：原第3阶段五个独立测试全部实际执行并通过，覆盖添加外键、空表未来写入约束、已有数据冲突、SET NULL例外及事务失败回滚。此为指定程序行为断言，不冒称整个原题通过。
4. 任务连续性：同一迁移工具的细化继续同一已绑定Task；仅检查实际绑定／新增对象，不能凭绑定ID宣称认知恢复。

记录评分只覆盖显式FK typed卡协议；不是通用自由文本语义评审。无记录、错误值或仍适用的旧typed卡为可证失败；丢journal、丢工具边界或错误阶段归因为缺证据，不能默认空记录。每个检查点保留各断言及原始分子分母，补充行不重复计权。

免费预检从原始空工作区执行全部5个源阶段；已知正确／错误轨迹可在隔离fixture中使用官方reference实现，不能让参考代码进入正式镜像、缓存或任务输入。正例、中途只追加未失效旧项、过晚修正及保留已限定历史范围等控制要经过真实Pi CLI与原State工具；不作为LLM表现。本切片不改产品State schema、Rule或预算。

## 实际验收与边界

2026-11-03 21:45 UTC前，真实Pi CLI的5个免费控制全部完成，共63个假provider请求、工具错误0：原生正例，插件正例、仅追加、过晚修正、保留限定历史。插件的初始记录均100；反证检查分别100、0、0、100；Task连续性均100。原生State／Task为设计NA。所有控制的五份源码交接树逐文件hash完全相同。

两臂正例各自重新执行5次原Slop verifier，共10次，每个实际Docker资源回执均为2CPU／8GiB，独立watchdog与终态清理保留。五项业务断言均100；原始严格AND仍为0（原第1阶段回归测试在后续阶段跳过），派生适用测试AND为100。其余State控制仅在完整交接树相同后显式复用正例程序测试，不声称重新执行另外15次verifier，更不声称LLM过题。

时序取首次**观察到**源码投影变化所关联工具的开始边界；后续恢复源码或补写State不能抹去早期失败。缺初始／结束快照、缺独立Pi调用边界、未关联源码变化、重叠工具无法归因均为缺证据。它不证明单个工具内部没有瞬态修改，也不推断模型阅读或采用了State。

`fixed35 slop-fk-tasks`生成相同公开schema及独立私有合同，`fixed35 slop-fk`读取真实CAS journal和原verifier证据。报告v20在原JSON／CSV／Markdown接入四个独立补充行；每行含含义、AND公式、原值、百分制、断言及适用性，额外权重0，防止重复计权。不以这些组件冒充整组旧C5／Task语义指标已经全部完成。未解决的完整35题契约仍阻止整包采集验收；340行软件控制报告明确标fixture且`collection_accepted=false`。

最终完整回归742项、Ruff及diff检查通过；仓库`npm run check`包含资源一致性、类型检查和276项单元／集成测试通过。程序fixture的Actor为2CPU／4GiB，原程序verifier为2CPU／8GiB，均为对称离线预检资源，不作为正式运行资源验收。首次无本地监听权限的全量回归为717通过、2失败、4错误，按既有权限流程执行后723通过；最终新增组件按同一有权限的测试路径验收。

本轮真实账本hash保持`fabfce853c8b8beb43fb840f6eba8992b1fc4c48dd2a550ac4183d7f8b20c029`；新增真实模型费用0，正式仍0/35。最终组件输出在`~/.local/share/memweave-experiments/fixed35-20261103/slop-fk-delivery-v20-final/`；较早v20显示与汇总生成异常的中间产物也保留，最终报告在新目录生成，旧v17/v18/v19工件不覆写。

```sh
memweave-eval fixed35 slop-fk-tasks --design DESIGN.json --source PINNED_SLOP \
  --runtime-task ORIGINAL_SCB02_TASK --output NEW_DERIVED_DIR
memweave-eval fixed35 slop-fk TRIAL --contract PRIVATE_CONTRACT.json \
  --official-outcome ORIGINAL_VERIFIER_OUTCOME.json --arm pi-memweave --output NEW_COMPONENT.json
memweave-eval fixed35 report PAIRED_ROOT --official-outcomes PAIRED_ORIGINAL_OUTCOMES.json --output NEW_REPORT_DIR
```

软件控制重算需显式加`--fixture-control`，不能因此获得正式准入。私有gold／参考实现仅用于隔离控制；最终产物没有向真实模型提供它们。
