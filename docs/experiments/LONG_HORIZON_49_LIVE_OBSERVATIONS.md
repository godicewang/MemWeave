# 49题双变体实验：持续观察

2026-10-28。本文件由当前活动会话追加，不是定时任务输出。计划：SWE Pro V2 35题、TB 4.0 14题，各原生/完整MemWeave Pi一次；统一20美元/48小时止损。官方评分仍是二值reward，不把环境错误当0。

- 18:47 CST：已完成schema2定向清单、按题配对的混合Harbor Job、统一观察账本和分组评分接线；81项实验自动测试通过，Ruff与Python编译通过。软件准备和官方任务控制尚在验证，未发起付费解题。
- 专用Colima已由8核/16GiB/120GiB扩到12核/42GiB/240GiB；Docker实测12 CPU、44082647040 bytes内存。保留原VZ/Rosetta和隔离设置。
- 审计发现：官方PatchReplayAgent按task_name找补丁，混合变体Job不能直接作为重放来源。现按变体复制原始result.json与原补丁、记录SHA后分别交给官方评分器；没有修改官方评分器。
- 观察边界：Harbor公开生命周期hook记录解题开始/结束；原生Session挂载后增量读取完整usage行。只派生计数和引用，不增加模型提示、工具或聊天副本。费用以官方峰时费率保守估算；在途响应可能晚报usage，不能承诺账单硬上限。

后续每组的准入、并行、真实推理、评分与异常将在此继续记录；最终98行表和badcase报告另行生成。

- 18:48:39 CST：正式Campaign开始，run_id=`20261028T104839Z-2121023e21`，统一截止2026-10-30 18:48:39 CST；初始源码b63b24e，候选包仍为f3931ce3产物。首组S01–S05准备官方linux/amd64镜像，未开始模型推理，当前费用0。原件位于`~/.local/share/memweave-experiments/runs/20261028T104839Z-2121023e21/`。
- 18:49 CST：独立公共Job API空解验证正在原官方Flipt容器内运行Go编译，docker top显示编译进程持续推进；尚未出分，不提前声明通过。主机memory_pressure显示85% free指标（不是虚拟机内存配额），暂未见资源压力。

- 18:53 CST：核对历史同题Flipt控制，官方verifier耗时约9分31秒（oracle）、7分12秒（nop），当前独立空解验证仍在Go编译；尚无评分异常证据。14题TB的官方评分器CPU/内存均不高于对应Agent配置，仍以官方资源配额安排题对。当前实际解题并发0、费用0，准备/控制不计解题。

- 18:57 CST：公开Harbor Job API的真实Flipt空解控制已结束，官方reward=0、exception_info=null，耗时约11分07秒；完整start/environment-start/agent-start/agent-end/verification-start/end记录齐全。该结果验证空补丁不会误得分及生命周期接线，不是原生Pi能力成绩。没有模型调用。虚拟机Docker盘实测236GiB总量、37GiB已用、189GiB可用。

- 18:59 CST：S02 Vuls官方镜像已成功拉取并冻结为sha256:3347b76b458ed77cf1a4d77aaa3abc48c86a417f70c0e7717427473c1ad4fb36，linux/amd64；约十分钟的下载等待没有触发替换。当前进入S03 Open Library镜像准备。独立nop底层日志显示真实Go TestLoad及子测试执行并失败，官方reward=0；后续准入仍须oracle=1/nop=0成对通过。实际解题并发及费用仍为0。

- 19:08 CST：首组3/5官方镜像已冻结（Flipt、Vuls、Open Library），开始Navidrome；尚无准入失败、替换或付费推理。新增只读Session分析程序在仓库外analysis/long49，按原件路径汇总调用/工具错误、最大实际上下文输入、原生压缩、Window非空边界及积压；不修改Task、Session、补丁或评分，也不把仅有State写入当作记忆收益证明。

- 19:11 CST：当前组Navidrome准备期间，用独立受限进程并行预拉取同组Qutebrowser原官方linux/amd64镜像；只温热Docker缓存，不改任务定义/镜像内容，正式prepare_task仍核对镜像并执行全部控制。命令、task.toml哈希与完整拉取日志保存在Campaign preparation-overlap/，无凭据、无模型。未提前缓存其他未活动组，避免不受控磁盘增长。

- 19:17:14 CST：S04 Navidrome官方GHCR镜像拉取失败：short read（expected 58,698,298 bytes, received 36,303,808），unexpected EOF。原始日志在groups/g01/preparation/该完整任务ID/main.log；目前原生/插件均无模型尝试，不能计能力0分或插件badcase。同档RS01存在；因旧选题§5允许同档候补、新执行§5却写首批不自动使用，两处边界尚未完全对齐，已向用户集中提问；候补未启用，其他原题准备继续。

- 19:33:50 CST：用户已明确同意按冻结顺序使用同集合/同档候补；S04将使用RS01，原题阻断证据保留。旧准备run在19:21:33安全停止，模型请求0、费用0、Docker无残留活动容器。新接线按49槽位保存actual_task_id，并另列原题/失败候补双变体阻断行。86项自动检查、Ruff及Python编译通过；另以两份内容不同的历史NodeBB原补丁调用冻结上游PatchReplayAgent查找逻辑，两次均匹配自身SHA，未调用模型、未重评或新增能力成绩。
- 窗口延续只接受已结束、无任何模型Job/Session的同清单/候选/runtime准备run，已核验父索引；继承S04镜像阻断以直接启用RS01，不重复尝试原题。整批仍20美元、截止不晚于2026-10-30 18:48:39 CST。此前时间全部保留在整体墙钟，既无模型重复尝试也无预算重置。
- 评分可信度补强：最终run/live纳入证据索引，未入索引新增成绩拒绝；SWE评分还核对原尝试、同变体交接清单、原/副本补丁与结果SHA及评分Job source_job。该接线防错测试不是真实Pi能力成绩。完整Pi/插件加载和任务控制仍在每组模型前真实执行。
