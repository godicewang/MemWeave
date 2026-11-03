# 生命周期独立判定器补齐

本轮只扩展现有实验评估侧，不改变产品State、Task、Window、Session或Rule协议，不发起模型请求。历史v8报告及输入不覆盖。新判定按已定稿Recent Window第19、20节和实际Pi 1.4.0分支元数据实施；不导入产品窗口选择／reducer作为oracle。

先补显式restart：以原生分支ID／parent和已有`memweave.restart.v1`验证原锚点、命令前有效绑定及原始N个完整事件。末尾N事件无真实用户时按契约加入最近真实用户与末尾N-1事件；工具调用和结果保持整体。种子与锚点之后新增事件组成初始范围，旧pending不参与。之后的显式N/B变化、已提交reset或边界越过原锚点按既有普通全历史重选，不把种子永久固定。

每个请求检查冻结种子合法、完整事件／工具配对、范围与顺序、真实provider正文及持久Window元数据；这些断言AND才通过。缺receipt字段／分支／内容证据为unknown，已知错误种子／锚点／绑定／工具配对为失败。空会话未生成restart意图单列零机会，不能制造通过率。正、负、缺证据和真实Pi请求集成分别验证；这些测试是判定器控制，不是模型记忆成绩。

后续跨Session需独立来源分支与冻结锚点证据，不能只相信目标Session里声明的seed。压缩、context_edit、多模态及token裁剪没有独立规则时继续unknown；不因增加restart路径而声称全部生命周期已覆盖。新评分器版本与控制目录需单独冻结。

已完成显式restart切片：`restart_window_evidence.py`不导入产品选择器，现有request-ready元数据和原HTTP正文参与判定。实际Pi Session经本地OpenAI兼容HTTP发出5个请求：3个原始请求、restart后的新请求、N/B扩容后的请求，独立判定5/5通过；restart命令本身HTTP新增0，旧消息逐项不变。完整原生提示、Rule及原生／记忆工具均在实际请求中核对。此为真实Pi Session集成，未声称这次测试经过Pi命令行dispatcher或真实DeepSeek。

第一轮实际请求揭示旧判定器未排除产品既有“新Task初始化”临时程序块，导致Window消息数量误报；已补明确前缀，真实原消息与此前缀冲突时仍unknown而非静默忽略。内存中改错真实seed为失败、移除branch ledger为unknown，未改原轨迹。实验全量628项、整仓276项及类型／资源／Ruff检查通过，旧v8报告不覆写；新增评分版本为`fixed35-score-20261103-v9`。这些是oracle验收，不是35题模型分数。

跨Session补齐采用已归档的原始Pi Session，不新增一套聊天存储：在单个trial隔离根内按header ID查找原文件，拒绝冲突副本／重定向；按固定source anchor沿原parent链重建来源前缀。目标请求的branch ledger须与目标Session原件相符，来源锚点时间不晚于恢复回执，回执不晚于请求。时钟不一致只表示缺可用性证明，不据此断言模型／产品错误。来源之后的追加不改变该前缀。独立核对原始scope／references归属、seed事件、跨Session命名空间及工具配对，再比对实际HTTP；仅信恢复声明或最终State不足。缺原件／时钟／锚点为unknown，已知种子或来源不符为失败。此仍不证明系统选择了所有候选中最佳来源，或模型理解／采用了记忆。

两个真实Pi Session、完整业务工具／Rule与本地HTTP的集成已通过4/4请求，并实际经过现有`grade_identity_windows`入口；来源消息被移除时失败。原件后追加／待完成工具尾段在冻结锚点之外不进入旧范围，空的Task来源不能借空seed通过；同名entry ID在两Session中按来源前缀区分。原始消息逐项不变，缺文件／截断／损坏／时钟不一致保持缺证据。测试观测器显式使用临时memoryRoot，Rule取自同一隔离目录，不把开发者默认运行时目录当测试数据。默认生产根路径不变。

当前扩展评分版本v11，独立Window子判定版本native-identity-plain-text-v3。全量643项实验测试、276项整仓检查、类型／资源一致性／Ruff／diff检查通过；均无真实模型请求。压缩、context_edit、多模态及token分配／裁剪尚无完整独立判定，不作已实现声明。正式35题仍未运行，不能将这些控制值当实验成绩。
