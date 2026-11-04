# LONG-05源题程序与参数身份审计

本组件只在现有实验CLI／report中离线消费固定ruby-rust-port原验证器工件，不修改题目、环境、原分、产品或Actor。完整正式配对仍未准入。它不包含State／Task／跨窗口记忆gold，不证明千次模型调用资格。

原pytest-json-ctrf 0.3.5把同函数参数样本合并到一行，`retries`包含参数重合次数。已有参考控制的fixture回放控制台为2001项，CTRF仅2行；Markdown为42项，CTRF8行。原metrics按CTRF行求和得到265，不能叫做2298个原参数样本的通过率；原reward和原partial保持原样，独立导出展开样本的passed／failed／skipped及身份覆盖，不用派生口径覆盖原数。

冻结原test.sh的22个gate和全部测试／数据hash；纯AST解析顶层测试、18组Markdown参数和2000条固定trace，不import测试或执行候选。逐gate控制台每个完整ID和终态计数必须恰等源预期，再核对CTRF函数身份、参数折叠次数、状态优先级及原metrics。重复、缺行、错ID、数量／状态／reward矛盾均要求修复。

六个业务检查点按源测试分区：认证／CSRF／安全／限流，ORM，CRUD／分类／审核，路由／Liquid／feed／分页，搜索／媒体／cache／跨运行时job，2000回放及并发。每点要求其全部实际源样本通过；子断言和六点都不新增权重。Markdown原测试允许已注明的renderer divergence skip，七次skip不伪装为通过，单列原题接受但未证明的行为；它不进入六个严格业务点。完整原协议验收只表示原门禁接受其声明的skip政策。

原空解若完整工件证明Rust服务在原health前置条件失败，业务点由该必要交付条件记0，保留所有未执行gate／样本，不捏造2298个失败断言。缺stdout、缺原reward或未知提前退出仍是缺证据；其他反作弊／环境错误不套用该分支。

仅重放既有隔离参考／空解控制，并增加每点pass／fail／missing、参数折叠、skip、重复／截断、原分矛盾及health分支测试。原分与组件、控制与模型能力分别展示，不将参考控制当正式成绩。

已通过实际CLI重放两个参考／一个空解：两个参考均原reward1、原partial264/265，展开2291passed／0failed／7skipped／2298total；六个严格业务点100。空解原reward0、Rust health失败，六个必要交付点0、2298样本明确未执行、执行断言失败数0。验证器／固定数据逐字节匹配源题；16GiB对称资源仍是此前已披露的派生控制，不称官方24GiB完整配置模型成绩。

三个控制均贯通现有report，新增`ruby-source-counts.csv`及Markdown逐口径说明，JSON保留原metrics和全部展开身份。初步本地重放曾漏认ResourceOracle自定义import，已在任何正式准入前修复；最终重放独立`ruby-source-v32-final`全部强制fixture标记，原初步文件留存但不作为结果。最终评估代码884项全量离线回归通过，34项组件／报告边界测试包含各点pass／fail／missing、折叠数量、skip、坏JSON、源码变化、控制准入及CSV输出。Ruff／diff检查通过，无新增模型请求。
