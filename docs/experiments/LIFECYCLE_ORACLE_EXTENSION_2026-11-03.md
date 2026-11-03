# 生命周期独立判定器补齐

本轮只扩展现有实验评估侧，不改变产品State、Task、Window、Session或Rule协议，不发起模型请求。历史v8报告及输入不覆盖。新判定按已定稿Recent Window第19、20节和实际Pi 1.4.0分支元数据实施；不导入产品窗口选择／reducer作为oracle。

先补显式restart：以原生分支ID／parent和已有`memweave.restart.v1`验证原锚点、命令前有效绑定及原始N个完整事件。末尾N事件无真实用户时按契约加入最近真实用户与末尾N-1事件；工具调用和结果保持整体。种子与锚点之后新增事件组成初始范围，旧pending不参与。之后的显式N/B变化、已提交reset或边界越过原锚点按既有普通全历史重选，不把种子永久固定。

每个请求检查冻结种子合法、完整事件／工具配对、范围与顺序、真实provider正文及持久Window元数据；这些断言AND才通过。缺receipt字段／分支／内容证据为unknown，已知错误种子／锚点／绑定／工具配对为失败。空会话未生成restart意图单列零机会，不能制造通过率。正、负、缺证据和真实Pi请求集成分别验证；这些测试是判定器控制，不是模型记忆成绩。

后续跨Session需独立来源分支与冻结锚点证据，不能只相信目标Session里声明的seed。压缩、context_edit、多模态及token裁剪没有独立规则时继续unknown；不因增加restart路径而声称全部生命周期已覆盖。新评分器版本与控制目录需单独冻结。

已完成显式restart切片：`restart_window_evidence.py`不导入产品选择器，现有request-ready元数据和原HTTP正文参与判定。实际Pi Session经本地OpenAI兼容HTTP发出5个请求：3个原始请求、restart后的新请求、N/B扩容后的请求，独立判定5/5通过；restart命令本身HTTP新增0，旧消息逐项不变。完整原生提示、Rule及原生／记忆工具均在实际请求中核对。此为真实Pi Session集成，未声称这次测试经过Pi命令行dispatcher或真实DeepSeek。

第一轮实际请求揭示旧判定器未排除产品既有“新Task初始化”临时程序块，导致Window消息数量误报；已补明确前缀，真实原消息与此前缀冲突时仍unknown而非静默忽略。内存中改错真实seed为失败、移除branch ledger为unknown，未改原轨迹。实验全量628项、整仓276项及类型／资源／Ruff检查通过，旧v8报告不覆写；新增评分版本为`fixed35-score-20261103-v9`。这些是oracle验收，不是35题模型分数。
