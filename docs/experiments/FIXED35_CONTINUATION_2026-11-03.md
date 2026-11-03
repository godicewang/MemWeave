# 35案例续接：独立额度与时钟

2026-11-03用户明确允许继续此前35题任务，允许公开benchmark任务、代码、工具输出及本轮State发送至现有DeepSeek API，并允许模拟用户、评分器接收必需评估输入。总额度USD20，后续将时间调整为24小时：起点02:44:57 UTC，硬截止2026-11-04 02:44:57 UTC。旧运行、旧账本和v5封存不修改。Library写回不在此次明确授权范围，继续暂停。

本轮仅使用现有实验系统。先核对真实选题机会、gold和采集，再分家族准入。未完成的能力不能用通用fixture或设计NA替代；所有正式成绩来自独立原生／插件actor。保持长题原有时间／资源口径，超过可用资源的题对按固定顺序串行；不以缩短题目换取“完成35题”。剩余时间和费用不足时如实记录未完成。

执行配置现改为每次admission携带不可变campaign路径及SHA256，显式绑定独立budget_id、ledger、原生／插件等额子限额、actor／judge／container／总截止。新入口拒绝缺配置、hash变化、旧账本身份、总额超20及不等额两臂。历史常量仅供历史离线调度兼容，不作为新付费运行默认值。真实quota服务标签及停止核验也绑定账本身份，不能误接旧服务。

冻结计划采用DeepSeek `deepseek-flash`，thinking off，正式输出上限8192，两臂同设置。2026-11-03核对[官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)仍为V4.1-Flash-1017；按峰时cache miss USD0.30/M、cache hit USD0.006/M、输出USD1.20/M保守估算与预留，Search/Fetch不启用。账单与估算分开。

本轮计划硬闸USD19，原生9、插件9、共用预检1，另留USD1不开放自动使用；所有actor／模拟用户／judge请求共账，未知请求预留不释放。正式前仍需真实CLI免费正负例与受控真实canary。此前未执行的被拒绝DeepSeek canary仅依新明确授权允许一次重试；再次拒绝立即停止该动作，不变换工具或路径绕过。

初始就绪边界：v5已完成INT-04受控同权冲突／State纠错的真实Pi假provider正负例；其余State领域有独立动作gold，MAB已绑定8个源选择器，Slop18阶段及TB／Marathon原控制已完成。Switch真实Task语料与恢复动作、Interrupt官方资产及部分逐题记忆gold仍需实现。正式运行尚未启动，本文不构成实验成绩。
