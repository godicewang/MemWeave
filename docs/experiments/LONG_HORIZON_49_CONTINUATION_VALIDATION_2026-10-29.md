# 49题实验单侧恢复接线验收

2026-10-29；这是实验控制器的开发与无模型验收，不是49题最终能力报告。生产候选f3931ce及归档SHA4d089821保持不变，未发布npm。

183257阶段在20:30:23 UTC关闭，已有21个正常完整题对、累计费用估算3.727987032美元。S16插件模型前端点探针超时触发旧公共取消，T07原生及S18双方中断；保留全部轨迹和首次成绩。用户已授权实验环境自主修复并取消整体费用／时间限制，恢复契约见执行方案§22。

修复范围：

- 固定Node探针正文、两个端点和每次连接／总超时逐字比对496320b完全相同。仅外网阻断且model传输失败时最多三次，每次原判定与耗时留存；外网可达、错误HTTP／schema不以重试绕过。
- 单侧严格证明Pi前故障时，保留正常侧并先为其原补丁完成首次官方评分，组记incomplete，其余任务继续。未知调用／费用或凭据故障仍拒绝。
- completed_parent在all_tasks模式按侧保存首次有效评分，正常0不重跑；正常Pro推理已结束但无评分时只补首次评分。取消侧用全新实例与初始材料补齐，不接旧Session／State、评分反馈或旁观诊断。
- 原件不动、不复制Session。继承result／patch／原group lock／Session核对旧证据索引与SHA、任务变体和镜像；评分使用原PatchReplayAgent在全新沙箱。报表区分score_only与新解题，继承费用只累计一次。
- 资源等待允许先启动按等待顺序第一个能满足全部CPU／内存／磁盘额度的题对，整题对资源包络和10实例上限不变。

实际检查：

| 检查 | 观察结果 |
|---|---|
| 新增测试先运行 | 传输／队列5项红灯，续跑接口与绑定边界随后补齐；未把红灯宣称通过 |
| 完整实验Python开发测试 | 137项通过；JUnit在仓库外continuation-preflight-20261029/developer-tests.xml |
| Ruff、git diff --check | 通过 |
| 真实S22完整插件SDK与新Node探针、无认证／模型 | 加载通过；模型端点401、外网ECONNRESET阻断，新attempts记录1次；该检查不产生能力成绩 |
| 真实闭合183257原件的只读恢复计划 | 保留43条已评分行（21完整题对＋T07插件首次0）；S16原生只补首次评分；还需54次新解题；保留9条历史中断及全部3.727987032美元 |
| 原件可重用性 | S16原生aa7713ee…、T07插件e28100d7… result SHA、原补丁／group lock／Session和任务身份核对通过 |
| 补丁绑定与报表边界 | 合成无模型夹具通过：旧正常0不覆盖、评分阶段新增模型次数0、不复制Session、替换评分补丁／篡改原件均拒绝；不是Pi能力样本 |
| 生产候选一致性 | git diff f3931ce -- src resources package.json package-lock.json为空 |

准备成果仍保留：S16–22完整SDK无模型预检／缓存，S21–23公开镜像按完整原registry index及全部descriptor导入、原ID／rootfs／配置一致；S24及后续暂只做有限主机blob预取。专用VM在继续前空闲107328MiB；S17已完成镜像两个可重拉标签有界回收，原件不动，不做全局prune。

实际新阶段的付费解题及官方成绩须继续观察后另记；这里不声称修复能提高插件能力、保证评分稳定或已经完成49题。S06第一次0／0及既有评分不稳定疑点保留。

## Docker观察修复验收（2026-10-29 CST）

204027阶段因Docker全JSON列表触发snapshotter可写层Size走访竞争而关闭。仅给观察命令显式加`--size=false`，元数据JSON、15秒观察频率和其他失败停止条件保持原样。新增两项边界测试：禁止隐式Size、真实列表失败不得伪装为空列表；修改前前者红，修改后全部139项实验开发检查及Ruff通过。

在S22原始官方镜像中启动一个无网络、0.25 CPU／64MiB、无模型的临时文件增删容器，交替各执行30次旧查询与修复查询。旧查询2次失败，修复查询30次全部成功且均包含该容器ID；只清理本次诊断容器，未重启虚拟机。仓库外回执：`analysis/long49/continuation-preflight-20261029/observer-size-acceptance.json`。此验收验证观察接线，不是模型能力或官方评分。

续跑继续继承26个正常题对、T07插件首次0，以及累计模型费用；S14插件／S23双方原补丁只补首次官方评分，S14被基础设施取消的原生侧保留历史后重新完成。所有首次0分、评分疑点和中断费用保留。

## 原构建镜像身份的部分题对续跑验收

46b54b48d8无新增模型调用即被原镜像身份保护阻断，累计费用仍$4.318621224。T07官方Dockerfile所有层命中，manifest／config与旧日志一致，重导出attestation导致外层index不同。新增内部冻结准备输入：从已校验原group lock取记录，先核对全任务、各角色context／Dockerfile／来源／平台／原Id，再设本实验别名；不build，不使用解过题实例。8项新增边界检查及全套147项、Ruff均通过，生产候选不变。

T07原index、manifest／config及完整amd64文件层从专用VM内容目录只读导出并逐blob SHA／大小验证。原attestation的in-toto payload有缺失，第一次全图恢复明确失败；平台定向归档保留旧index及manifest元数据，Docker官方load --platform linux/amd64成功恢复main 55b450e…／verifier 558cb38…原Id。必须使用完整docker.io/library引用，未规范化短引用导入后不能按正常名称查找；这两次有限失败及回执保留。没有改内容存储或补造证明payload，不声称attestation完整。

随后使用真实prepare_task冻结路径重建运行副本、verify_prepared_task及image_snapshot核验：两角色原Id／平台完全相同，官方协议不变，0模型。归档、SHA、源group lock／build日志SHA和验收位于仓库外`analysis/long49/t07-original-index-recovery-20261029/`。续跑仍53条已评分、3条只补首评、42侧新模型，保留10条中断历史。
