# 阶段 2：Task＋State 最小闭环验收

日期：2026-10-21。宿主 Pi v1.3.0，Node v24.22.0。用户已批准 `PHASE_2_PROPOSAL.md`，先同步 Task §8、State §14、Rule §3 及架构，再实现代码；固定 Rule 两份正文未改变。

## 已交付行为

正式入口注册 `task_create`、`task_find`、`task_resume`、`task_status`、`state_append`。创建生成 Task、初始 Goal v1、索引及分支绑定；批量 Fact/Decision 全部校验后一次提交，各记录计一个版本。下一次请求使用固定 Task/State/配置快照，在 Rule 与原生交互之后只添加一份当前 State。

`index.json` 仅保存发现信息及 Session 来源。`memweave.references.v1` custom 条目保存 U/A/T 定位，`memweave.scope.v1` 保存当前分支绑定与六字段覆盖；只有已完成且能匹配原生调用的工具结果可作 T 证据。State/Rule/引用头仅进入请求视图，不改原始消息正文，不创建第二套聊天文件。引用文件按已验证字节偏移增量读取，替换/截断重新严格读取；不调用可能迁移并改写文件的 SessionManager.open 读取外部来源。

创建/恢复、引用分配和 State 修改持 Task 文件锁，全局索引另持锁。`state.json` 原子替换旧字节加本批 JSONL，旧前缀保持；`state.md` 与索引版本可重建。op_id 绑定 Task、Session、assistant entry、原生 call ID 和条目序号；同调用重试不会追加，新 assistant 复用 call ID 可正常提交。

## 实际测试

```sh
npm run check
npm run test:live
```

- 资源一致性、严格类型检查及 **62 项常规测试通过**；常规组使用真实 Pi、替身供应商和本机 HTTP，未调用外部模型。
- 独立 **3 项 DeepSeek 测试通过，共 7 次真实推理**：原阶段 0/1 各 2 次；正式阶段 2 的创建 → State 写入 → 下一请求可见为 3 次。另在开发中单独运行阶段 2 测试一次，完成 3 次真实推理；不把替身结果计入 API 验收。
- API 验证只读取仓库外既有私有配置；认证文件前后逐字一致。密钥未写入测试、日志、仓库或发布包。

| 范围 | 实际观察 |
|---|---|
| 正式扩展执行 | Pi 原生加载器实际执行正式 Task/State 模块；npm 归档白名单、入口和 host SDK/typebox 加载回归通过 |
| 最小业务闭环 | 创建 → U1 证据 → F1 → 下一请求 State → 磁盘重开/reload，State v2 和 U/A/T 编号恢复 |
| 输入/证据 | 必填、互斥输入、空批次、非法类型/证据、同批猜测新 ID、Unicode 100/101 码点边界 |
| 原子与幂等 | 无效批次整批不写；旧日志字节前缀保留；同调用重试不重复；新轮复用 call ID 视为新调用 |
| 多实例/来源 | 两个 Pi 实例共享 Task，各自绑定；新普通 Session 无绑定；跨 Session 连号；fork 复制引用去重；缺失来源取消请求、不重置编号 |
| 分支 | 实际 navigateTree 恢复绑定及覆盖，追加 scope 锚定后磁盘重开一致；回退聊天仍能看到同 Task 已提交认知 |
| 归属 | 首次创建只接纳触发用户及创建轮，不吸收全部未绑定历史；切换不自动暂停旧 Task；latest_paused 可恢复现有 paused 记录 |
| 并发 | 独立 Node 进程并发提交四批，结果 v5、F1–F4，无丢失写入；两个真实 Pi 实例同时提交 Fact/Decision 成功 |
| 派生失败 | 实际不可写的 state.md 目标：报告已提交 State 版本与失败阶段；修复目标后，同调用重试保持版本并重建派生信息 |
| Session 故障 | 实际 append 文件故障可使 Pi 内存多一条、磁盘无该条；立即停止。普通扩展 reload 后仍核验并拒绝脏内存，须从磁盘重新打开 |
| 协议结构 | 原生 tool ID/arguments/result 配对、reasoning/signature、图片块保持；自有引用头只改变请求副本；State 和 Rule 不持久化 |

所有测试 Session、故障夹具、验证入口、包和 npm 临时缓存放在系统临时目录，并在成功/失败后清理。正式测试源码保存在仓库；没有修改用户业务项目、真实 Session 或私有认证。

## 限制与下一阶段

本阶段没有开启 Recent Window 裁剪或完整 token 预算；没有实现完整 State 窗口、update_goal/modify_fact/state_read/state_remain、memory_read 或 R 别名。这些仍按阶段 3–5 实现，固定 Rule 描述最终协议不代表所有工具已交付。

state.json、索引和 Pi Session 不是一个跨文件事务：提交后失败会明确报告部分完成，不自动撤销认知。Task 级 State 跨分支共享，聊天回退不回滚事实。索引发现元数据和 Session 来源仍需保留，不能宣称仅凭 Goal 日志即可重建整个索引。State 日志每批原子替换，长日志写入成本尚未量化。

文件锁在正常完成/异常返回时释放；强杀进程或机器崩溃可能留下锁。当前诊断 dead owner 或等待超时，不自动抢占，需确认没有写入者后清理。未验证断电持久性、长时间压力、任意第三方扩展、codemode 嵌套 Task/State 工具或其他 Pi 版本；缺少原生 assistant 来源的嵌套调用明确拒绝。安装渠道的既有范围、HTTPS 失败与 registry 未发布状态仍见 `PHASE_6_READINESS.md`。
