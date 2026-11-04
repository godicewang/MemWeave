# fixed35：完成任务的空网络回收

2026-11-04 07:32，MAB-07两臂canary在容器创建前遇到Docker默认地址池耗尽；实际供应商请求为0、账本无对应条目，两臂清理确认。长期免费控制及已完成实验的空Compose网络未全部移除，不能通过修改地址池、全局prune或重试付费调用来掩盖。

新增现有CLI `fixed35 cleanup-empty-networks <campaign-root> --output <新目录>`，默认只读审计；显式`--execute`才删除。输入必须是有匹配budget_id的campaign，逐个核验其Harbor原始result.json的终态、目录／trial身份与hash，只查询该trial的`__env`和`__verifier__trial`项目标签。网络当前为空且项目标签／ID匹配时，删除前再次检查；有容器连接、标签不符或观测缺失时跳过，daemon错误不冒充成功。每次删除前后单列审计事件，异常保留INCOMPLETE，未知结果先核对准确ID。

不改Docker daemon、地址池、安全／网络设置、Actor输入、源题／verifier或历史raw。禁止全局network prune；不查询旧拒绝的宿主进程，不触碰不属于本campaign的网络。该修复属于观察／清理设施；失败canary没有Actor表现，后续另开版本重试前先核实零派发。已完成的MAB与TB-07成绩不重跑；活动UEFI连接的网络不会被删除。

另有TB-01资源验收修正：顶层Harbor override同时作用于独立verifier，实际2CPU/4GiB，而任务文件verifier原声明1CPU。参考解原奖励1及实际两阶段回执均已保留，离线恢复而非重跑；后续两臂按相同实际限额披露。没有把这一资源差异写成测试失败或原题资源完全复现。

验证覆盖空网络dry-run／执行、活动连接、检查与删除间新连接、标签错误、未完成trial、非法身份、重定向结果与daemon失败。它只证明清理边界，不是模型能力或案例成绩。

本次实际dry-run核验202个已完成项目，2026-11-04 07:41:35 UTC按ID回收20个空网络，动作原件保存在本轮`network-cleanup-v1-execute`；十项专项、1092项完整实验回归与Ruff／diff检查通过。网络耗尽也打断TB-06免费参考控制的verifier创建，保留该基础设施失败，后续从该未完成控制续接；不重跑已完成TB-01／03／04原控制。MAB-07失败canary没有供应商调用，另版本恢复07／08后才将原四题续跑范围声明完成，不能仅用控制器退出冒充四题完成。
