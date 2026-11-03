# Interrupt源契约的可执行组件

本切片只补当前已选INT-08/09/10的固定源身份、最终DOM／URL判定和共同60%回放前缀契约，接入现有fixed35 CLI／报告。网站镜像尚不可用，不能宣称浏览器环境或完整中断／记忆行为准入通过；不请求真实模型，不重试旧拒绝动作。

源revision固定为`17da111e4858b93c0cab1d88f85e1735fbd1d423`。INT-08的目标是订单302的状态Canceled；INT-09分别检查默认配送和账单地址中的111 Magnolia Path与Atlanta, Georgia, 30303；INT-10使用源URL规则保留鞋类及0–30价格条件。最终URL符合源规则仍可能保留评分限制，不能据此判定撤回成功。此限制必须在输出中显式保留。

合同由已批准设计及实际pinned源文件生成，逐一核raw场景、变换后配置、原配置、原JS locator与评估器hash。契约及gold仅放evaluator侧，不挂载给Actor。固定JS只允许三个已核实selector的outerText读取，不执行任意Python／模板eval。

最终DOM采集使用调用方提供的真实Playwright上下文，在同一登录上下文的新Page读取源指定目标，保持Actor Page不被导航；仅保存目标文本、URL及错误类别，不复制cookies或认证。捕获失败为缺证据，不能按空列表或空字符串默认为成功。测试替身必须显式标fixture，不能进入正式成绩。

每个最终检查点的必要程序断言AND：目标URL／locator身份与所有必需值；已知文本错误为0，记录丢失或采集失败为unknown并阻止验收。该组件不证明过程中无错误修改，也不证明模型采用了State。INT-10另保留“评分撤回尚未由真实filter轨迹验证”的未完成项，不把源URL成功改称C5成功。

60%沿上游`floor(pct*N)`，使用共同冻结baseline的`K=3*N//5`。baseline必须有完整actions、准确num_actions及匹配task_id，不能是已中断轨迹，前K不能含STOP；哈希绑定原件和前缀。不得按每臂实际进度重新算K，也不把后40%答案／动作交给Actor。合法前缀仍不证明中断处存在业务机会，网站状态和未完成依赖动作须在真实环境另行核验；不将未校验机会当设计NA。

新增35项独立测试覆盖订单、地址、原URL规则、每个地址新值／旧值的单独反例、缺字段、关闭失败、来源hash、回放计数／STOP／取整／未来动作隔离，以及现有CLI与报告接线；完整实验回归722项通过。真实source CLI已在三个pinned选题上生成私有合同并执行9个显式浏览器替身控制：INT-08/09为100／0／unknown，INT-10原URL为100／0／unknown而完整撤回仍unknown。替身未启动浏览器、网站、Actor或模型，不能宣称实际网站验收。

实际Playwright目标由源`Eval/requirements.txt`固定为1.37.0，代码使用其同步API；这里只核对源API调用方式，尚未完成真实浏览器兼容验收。真实上下文以外必须显式fixture，fixture baseline也不能默认进入真实回放。网站资产、真实baseline、动作／请求时序及State更正仍列pending，合同状态始终`SOURCE_COMPONENT_NOT_ADMITTED`。

现有入口如下，输出采用不可覆盖的新文件；`interrupt-final`在缺记录时输出缺证据，不能填假分：

```sh
memweave-eval fixed35 interrupt-contract --design DESIGN.json --source PINNED_INTERRUPT \
  --case-id INT-09 --output EVALUATOR_ONLY/INT-09.json
memweave-eval fixed35 interrupt-baseline --contract CONTRACT.json \
  --replay SHARED_BASELINE.json --output EVALUATOR_ONLY/prefix.json
memweave-eval fixed35 interrupt-final --contract CONTRACT.json \
  --capture EVALUATOR_ONLY/final.json --output NEW_REPORT.json
```

测试替身另加`--fixture-control`，该标志不会使合同变成正式准入。自动报告使用`interrupt-final-source-v1`适配器；共同约束只计一次，补充检查点额外权重0。原始WebArena reward仅来自原verifier，不由本组件或fixture补造。逐项报告版本为v19，原v18及其36个Slop控制封存不改。
