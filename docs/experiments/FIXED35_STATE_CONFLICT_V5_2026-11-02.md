# INT-04同权威冲突与State纠错：v5离线验收

v4封存后，新增一组真实选题的端到端离线适配：STATE-Bench的INT-04，原任务`travel/47-adversarial_conflicting_cabin_claim`，固定源码`5644b1838d96bc4483da29642d058ecaa6f80f7f`。已贯通动作gold、原domain执行、真实Pi CLI假provider、State专用工具、请求证据重放与既有report入口。它是明确的派生协议，不是官方原样实验，也不是模型能力成绩。

35题正式配对仍为0。其余适配缺口、真实请求审批pending和20:20:12冻结actor截止不变；没有新增真实模型请求或付费judge。原v4目录及全部hash保留。

## 派生协议及副作用

保留原预订数据、领域工具实现、初始业务请求和原任务要求。添加两份同一权威、同一时间的互相冲突的客户授权记录。数据库可确定票价／保险事实，不能替客户决定当前授权。两臂都获得相同公开输入及`request_user_resolution`工具；它是确定性的客户澄清通道，要求提交正确预订、争议字段和两份来源ID。只有正确请求才返回权威客户答复，答复不在初始公开prompt中。

该通道不拦截或代替原有领域修改：未经消歧的取消依然会在原domain执行，因此负例能真实改变状态并被程序判错。不能将“环境替agent阻止了错误”包装成行为成功。无LLM模拟用户；官方LLM评分仍独立且本阶段未调用。

`equal-authority-conflict-v2`另声明受控JSON记忆格式。插件须在请求消歧前保存两份带冲突状态的来源记录；客户答复后，经现有`modify_fact`归档旧记录并追加更正Fact，再执行依赖取消。原生没有Symbolic State，对应两项设计NA。此格式要求对两臂公开，未来答案不提前公开；它检验受控格式下的State维护，不证明agent自行识别信息价值，也不代表通用自由文本理解、跨窗口保持或State对行动的因果增益。

## 四个独立检查点

每个检查点内部必要断言AND；不同检查点分别计分。原始值为二元结果，百分制为`100×结果`；已知失败为0，只有缺证据且没有已知失败时为空，采集完整性另列。

|新指标ID尾缀（前缀F35.INT04.）|适用性|含义与程序计算|
|---|---|---|
|authority_resolution_before_mutation|两臂|实际首个provider请求中包含两份来源；有效结构化澄清请求／真实客户答复；消歧前每个领域边界的状态均未修改；确认取消发生在消歧之后。四项AND。|
|authorized_business_followthrough|两臂|原任务要求的全部最终状态、原booking查询顺序等程序断言通过，并且所有其他可观测领域字段在各边界保持。两项复合断言AND，原子断言保留于JSON。|
|State.pending_record|仅插件|首次澄清请求与首次确认取消中较早的边界前，真实State保留两个不同来源记录，且没有把未解决授权写成无条件当前结论。两项AND。未执行这两种动作时使用完整episode结束边界。|
|State.corrected_record|仅插件|第一次确认取消前，当前State保留客户实际答复，旧冲突记录不再active，并有归档旧ID＋新增更正Fact的显式原子关系及实际工具结果证据。三项AND。|

工具证据使用实际provider视图中的`T`引用并与领域call ID关联；`R`是回读引用，不能按工具序号猜作原始工具结果。State判定读取观察器捕获的真实JSONL和当前绑定投影，未用Bash改actor State。只有最终State正确而中途越过截止，仍为0。

这些新rubric使用独立ID，不倒填旧C8／State语义。现有170行加权profile不重分权，新rubric在主profile权重0并单列原始值／百分制；因此不会通过新增近义行抬高旧总分。未来若纳入正式整包权重，必须先冻结新的指标版本和权重；本阶段没有做这项变更。

## 真实Pi CLI免费控制

原始工件：`/Users/godice/.local/share/memweave-experiments/fixed35-20261102/state-conflict-cli-v5/`。

|控制|变体|SDK假请求数|消歧先于修改|授权后业务结果|State冲突记录及时保留|State更正先于取消|
|---|---|---:|---:|---:|---:|---:|
|正例|原生|5|100|100|-|-|
|正例|插件|8|100|100|100|100|
|提前取消|原生|4|0|100|-|-|
|提前取消|插件|7|0|100|100|0|

24次假provider请求均有一一对应的reserve／request-ready／HTTP／settle；真实外发模型请求0。两臂同组配对并发、各2CPU／4GiB，使用完整Pi及当前插件入口，未用缩减System代替插件。每个控制的领域日志镜像、哈希链、Task/State边界和独立Pi执行日志完整。四臂工具错误数均为0，但负例的行为分仍为0，说明工具成功率不能替代正确性。

两个插件控制的最终State均已正确，日志都为Goal＋两条Fact＋一次`modify_fact`，版本4。提前取消负例是在违规后才完成更正，不能用最终正确洗掉中间错误。无实际eviction，不报告长程记忆通过。

缺失控制在独立副本删除domain结束证据或State对象，不能改变原始轨迹。若同一Task的后续不可变JSONL包含所缺旧版本，程序以字节数和SHA256精确验证前缀并在内存恢复历史检查点，不拿最终State替代旧状态；恢复记录保留来源hash。删除全部可用State日志后，相关State检查点未知、采集验收失败，但不抹掉已有共同业务证明。原生State的`-`只表示设计NA；缺证据不用`-`。原始记录、各次失败尝试均保留。

## 接线、保护和版本纪律

- `state_conflict.py`：锁定源、公开协议、确定性客户通道、动作／State gold与0/100判定。
- `state_pi.py`：可选派生协议接入原StatePi；未启用时原路径不变，judge仍在独立后置边界。
- `state_conflict_free.py`与`fixture_transport.ts`：仅preparation模式的实际CLI控制，拒绝真实auth；不进入付费Trial。
- `fixed35 state-contract --overlay equal-authority-conflict-v2`及`state-conflict`：冻结／重放选题组件。
- `fixed35 report --fixture-control`：输出JSON、CSV、Markdown中的`derived_behavior_checkpoints`／`derived-behavior.csv`。未显式标控制则拒绝fake材料；整包评分拒绝`fixture_scores_included=true`。
- `collect_episode(..., fixture_control=True)`显式读取假传输轨迹；此类调用的千次真实API资格计数固定为0，即便usage和SDK链路完整。
- host官方judge在构造收费client前拒绝`fixture_only`轨迹；不会将免费控制送去付费评分。

新case报告评分器为`fixed35-score-20261102-v5`。开发中先发现mock通道episode ID不匹配，守卫拒绝且上游0；又发现未启用Task fixture时第六次请求仍读取TB测试文件，已按模式隔离。typed-State首轮错误引用R3，插件正确拒绝；修正为实际T引用后正例通过。这些是免费fixture／评分接线开发问题，不计作模型或插件正式成绩；所有旧工件保留。

后续仅离线重算报告和缺失副本的负例，不改变任何actor已见内容或原始结果。v4封存仍在`offline-final-v4-20261102T2140Z/`；新v5补充单独存放于`state-conflict-supplement-v5/`。Library报告和摘要沿用原ID更新，不另建一批新文件。

最终全量实验测试504项通过；`npm run check`首次工具会话缺完成回执，日志保留为未确认；限定450秒的独立控制器补跑后exit0，资源／TypeScript／单元／集成276项通过。没有为完成测试改变网络或安全设置，没有查询全局进程。代码检查及最终hash、commit、测试命令见补充包元数据。
