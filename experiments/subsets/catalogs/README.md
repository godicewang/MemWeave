# 定向选题审查清单

`long-horizon-49-v1.yaml` 是用户确认的49题长程专项清单：SWE Pro V2 35题、TB 4.0 14题，简单/中等/难/超难各为7/7/14/21。

它保存完整ID、来源提交、预评级依据、公开证据与任务哈希、单题资源、历史暴露和模型前候补顺序。`review_profile` 的1–4为人工结构注记，不是任务成绩。`environment_admission` 尚为待官方控制和完整Agent预检；静态筛选通过不能改写为已跑通。

此目录文件**不是schema1的Subset输入**。schema2 Campaign通过`catalog`和`catalog_sha256`逐ID、逐哈希读取，入口配置为`experiments/configs/long-horizon-49.yaml`；不能调整count或搜索seed冒充这49题。选题时未运行；用户后续已授权整批20美元/48小时止损和最高10并发的真实双变体测试，详见[执行方案](../../../docs/experiments/LONG_HORIZON_49_RUN_PROPOSAL.md)。目录本身仍保留冻结时元数据，不改写选题历史。

候补仅限同集合、同预评级档，在模型前准入失败时按顺序使用；公共软件接线失败先修接线。TB有三档没有已审查的同档候补，需暂停该槽位并重新对齐，不能跨档凑数或因解题失败换题。

逐题说明、旧题处理、选择限制和后续运行边界见 [选题文档](../../../docs/experiments/LONG_HORIZON_49_SELECTION.md)。清单和审查意见不能注入被测Agent。
