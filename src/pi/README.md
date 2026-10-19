# Pi SDK 宿主基础层

当前是阶段 0 的无界面基础切片，使用固定 Pi 1.3.0；不实现 Task、Rule、State 或 Window 业务。

- `host.ts`：创建原生 `AgentSessionRuntime`，所有 Session 替换复用同一工厂；接入公开内置扩展，保留资源发现，报告加载失败；退出先取消并等待活动请求。
- `settings.ts`：仅遮蔽本实例的 compaction 有效值，普通设置继续委托原生对象；不写用户共享压缩开关。
- `trust.ts`：利用公开信任存储、加载回调与扩展 handler 类型接通无界面信任流程。Pi 1.3.0 未从包根导出 CLI 信任解析函数；这一小段兼容接线限定在适配层，不导入 SDK 私有路径。信任扩展先于已保存决定，未知项目遵循全局默认；`ask` 在无界面时不授权。
- `requests.ts`：原生请求准备后创建每请求 frame，通过扩展 `context` 组装；在原生变换后核对后置改写，在发送边界检查成功状态，不重算预算或重写供应商协议。
- `../extension/index.ts`：仅注册 context、生命周期与手动 compaction 取消事件。

`createMemWeaveHost()` 返回原生 Runtime。请求业务通过 `pipeline(target)` 按实例提供 `prepare` / `transform`，它们是内部接线接口，不是新模型工具或持久化协议。不提供 pipeline 时，宿主可以初始化，但发送会明确失败；不能把裸 Pi 请求冒充完整 MemWeave。

当前测试中的透传 pipeline、临时规则和 State 文本仅为接入夹具，未实现正式模板渲染、状态恢复或窗口算法。业务模块接入后仍须各自完整验收。原生工具实现、请求模型/thinking 信息、工具声明和供应商转换由 Pi 保留；此层不另写循环或全量历史库。

TUI 绑定/信任确认界面、完整命令及恢复/更新提示、锁定应用安装尚待后续阶段 0 切片；接入 TUI 时需统一 mode 绑定，避免重复发出 `session_start`。目前不宣称完整官方 CLI 功能或任意第三方扩展组合兼容。
