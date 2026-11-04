# 截止终止证据：v51实施设计

无付费真实Pi长Bash控制复现：本地截止正常返回143、杀掉工具并保全stdout，但Pi1.4 print-mode先unsubscribe再dispose／exit，不保证agent_end或tool_result。仅把这些回调缺失记为采集丢失，会令合法截止运行无法验收。依据为实际宿主`dist/modes/print-mode.js`的SIGTERM处理及隔离控制；不是修改Pi核心或延长Actor时间。

评估扩展拟在SIGTERM事件的microtask记录独立`execution_terminated`，明确包含信号、原定截止、owner PID、实际workspace及Task库存CAS。它不是agent_end、不是工具返回、不进入模型请求，不保存凭据。microtask让Pi自己的同步信号处理先杀掉被跟踪子工具；原退出行为不变。

离线判定必须同时核对原stdout哈希、执行清单状态、同一次调用／阶段／producer身份、原截止守卫PID和时间，以及原生异常／退出；只有证明是冻结截止取消，才能解释未完成工具和原生结束回调缺失。已完成工具的结果或快照丢失依旧不放行。取消操作单列，不能把未知工具回执伪造成成功；后续如何显示其错误／取消口径须保留原始字段、明确计算范围和版本，原冻结报告不覆写。

当前已冻结旧运行不热改Actor扩展。若原Harbor工件或独立评估边界足以恢复终态，应保存独立补充证据和来源；不足时仍待修复或按明确例外规则处理，不生成虚构结束事件。此文是本轮实现的限定设计，真实CLI与报告接线验证完成前不宣称已解决采集问题。

v51将工具的原始`errors`、`unknown_results`保留不动，另列`deadline_cancellations`。Q1的本版本运行失败口径为（真实错误回执数＋已证明截止取消数）/尝试数；取消是执行未完成，不是合成错误回执。未解释的结果未知数为原始未知数减去已证明取消数，仍进入未知覆盖与区间。CSV/JSON逐行说明该范围；不把取消计成成功，不补零毫秒执行耗时，不外推到没有终止证据的工具。此项仅属于工程可靠性，不改变原题得分。旧冻结评分版本不覆盖。

已执行的真实Pi＋假provider控制保存在`~/.local/share/memweave-experiments/fixed35-20261104/tool-hang-deadline-v2/`：2026-11-04 11:25:56.620 UTC独立PID守卫触发，实际信号快照于11:25:56.629落盘；原生结束回调为false、完成工具0、已证明取消1，原退出错误保持`NonZeroAgentExitCodeError`。Bash探针停止、原stdout哈希保留、容器清理已确认。真实模型调用0；这是采集实现验证，不是Agent行为成绩。

容量元数据GET仅新增请求开始／HTTP状态或错误类型／低基数cause code的评估日志，不改认证、实际响应、重试或产品拒绝行为。TB-09第二次插件尝试的`MODEL_CAPACITY_UNVERIFIED`原始诊断按精确格式保留为带哈希诊断，不能被普通JSON解析误报为截断；其它非JSON仍拒绝。零个实际模型请求的token总和为数学上的0，缓存比率0/0为N/A，不表示provider报告缓存0。两次原生尝试未知费用继续预留，不能以此修复释放或重复请求。
