# State统计从既有提交原件恢复

免费CLI控制的`FreeEpisodePi`直接调用原Pi入口，未执行正式runner结束时的memory归档。其完整State journal已经由现有全局Task registry保存到evaluator-only CAS，但旧统计器只认`memory.tar.gz`，因此F/D计数和节奏成为unknown。不能据工具输入或成功回执猜事件数。

本切片先补免费控制的同一结束归档；对已完成控制不重跑，只在独立原Pi执行／阶段采集完整、初始及最终全局Task inventory完整且所有journal版本／hash／追加前缀一致时，使用既有CAS原件。缺最终清单、前缀改写、Task消失、哈希或版本矛盾均保持缺证据；不能把空清单默认为零。若有效归档与CAS不符，不挑其中更好的一份。

同一只读reducer处理归档和CAS；不创建伪造memory归档，不改运行时State。Goal不算F/D，modify_fact新Fact计一次，归档／滑窗不增加累计数，重放不重复计数。初始已有操作在完整初始inventory已知时从本轮新增中扣除，当前有效存量仍取最终版本。历史缺初始基线须明确口径，不悄悄推断为空。仅在完整Session计数与实际assistant-return捕获一致时解释本轮节奏，不能把恢复来源历史返回混入。

只有一次写入时，事件密度可知而均匀度CV仍为样本不足；这是数学边界，不是采集失败。所有重算写新评分器目录，保留v15及其unknown原值。该变更只修观测，不改变模型已见上下文或动作，不追加付费请求。

多阶段归档按验证过的追加前缀选择，不用文件mtime判断最终版本；有效旧归档若为终态CAS的前缀可恢复至后者，内容冲突则保持unknown。fixed35没有完整初始inventory时不拿最终journal总数冒充本轮新增，原始总数另列。历史报告API保留原算法并显式标`final_journal_total_without_initial_baseline`，不覆写过去口径。

已完成一个实际Pi CLI免费控制，5个模拟请求，生成真实`memory.tar.gz`；归档与同次CAS在累计／存量／归因位置／节奏／回执-提交矩阵逐项相等。已有MAB-06的旧原件也在不重跑情况下恢复到新增1、有效1、位置14、R=37、密度1/37，单次写入CV仍样本不足。670项完整实验回归通过；正式35题仍0，没有新增DeepSeek请求。
