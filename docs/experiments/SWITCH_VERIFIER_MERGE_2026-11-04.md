# Switch可信基础树交接修复

1CPU4GiB原参考控制的INT-06在执行F2P/P2P业务测试前失败，`result.status=error`，原reward缺失；INT-07参考结果为1，但旧资源收集器误读单阶段路径，未捕获多阶段`steps/turn-01/agent/actual-resource-limits.json`。这些都不是模型成绩，旧工件不覆盖。

INT-06失败原因是源grader先`git clone --shared`，再以`copytree(..., symlinks=True, dirs_exist_ok=True)`覆盖同一可信基础树。后者遇到克隆中已有同目标符号链接仍抛FileExistsError（Django文档的四个图标）。修复只在覆盖可信树时跳过源和目标均为符号链接且`readlink`完全相同的条目；不同目标的碰撞继续报错，普通文件、额外预编译运行资源及缺失链接按原行为复制。不接触Actor提交树，不忽略测试失败。

该补丁仅用于新的版本化任务／评估器，需记录旧／新grader与task hash、原失败、实际参考／空解和资源证据。原始上游pin与源码不改；所有业务测试及F2P/P2P列表不改。未来结果明确标为含可信树合并修复的派生协议，不把旧的源基础设施异常冒充正常失败或参考通过。尚未有本轮Switch正式模型配对，不存在用新grader选择胜出旧成绩。
