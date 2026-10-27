# Terminal-Bench 官方 Dockerfile 构建与镜像冻结方案

状态：2026-10-27 用户已确认，开始实现。官方 Dockerfile 原样使用；只补齐实验接线，失败任务在模型运行前按既定候补顺序处理。

日期：2026-10-27

## 第一部分：目的、范围与取舍

Pro V2 的官方镜像、解题只产补丁和全新沙箱评分已通过真实模型冒烟。TB 4.0 还需要解决镜像冻结问题，才能宣称两个变体在冻结的环境中比较。

当前固定的 TB 4.0 提交中，66 题均没有 `environment.docker_image`，依靠 Dockerfile 构建。实际 Harbor 0.24.0 wheel 的 `docker-compose-build.yaml` 不设置固定 image 名；Compose 按 Trial project 生成镜像，并在 `down --rmi local` 时删除。镜像还带有各 Trial 的 Compose 标签。现有按 `hb__<environment hash>` 在 Job 收尾后查镜像的做法不能成立，不能把 Mock 检查当成实际支持。

此外，独立 verifier 明确不继承 `extra_docker_compose`。本次 FreeCAD 解题环境按 amd64 构建，官方评分环境按 daemon 的 arm64 构建；后者在安装 validator 时遇到 pip 无法卸载 conda/distutils 的 vtk 9.2.6，oracle 与 nop 均没有评分。系统没有修改 Dockerfile、依赖或测试去绕过失败，也没有对此题发起模型请求。

已确认：保留上游 checkout 原样，提前按各任务的原始 Dockerfile 分别构建解题与独立评分镜像，固定实际镜像内容身份。在仓库外生成透明的运行副本，仅把构建结果作为 Harbor 原生 `docker_image` 输入。两变体引用同一镜像，不修改题目、测试、资源、网络或超时。仍无法构建或无法通过官方控制测试的任务明确排除，在被测候选运行前按原候补顺序替换；不能修补评分依赖后继续冒充原任务。

这是当前实验执行器对 Dockerfile 任务的适配，不是 TB 或 Pi 强制要求预构建。FreeCAD 的依赖构建失败独立处理；尚不能断言它由 ARM 导致，也不承诺冻结镜像会修复依赖问题。

优点是保留现有 Harbor/Pi，保持官方解题与评分语义，并能锁定本次实际构建出的环境。代价是本地运行副本的 task.toml 不再逐字等于上游，必须同时记录原始与派生哈希、差异及构建证据，明确它是本地冻结执行；不能声称采用上游发布的预构建镜像。

另一个选择是维持逐字原任务边界，暂时只验收 Pro V2 的实际运行；TB 的配置和诊断保留，停止在模型阶段之前，等待允许的上游接入方式。本轮不会自行换任务集、改评分依赖、换 Harbor 版本、部署云环境或放宽冻结要求。

## 第二部分：实现细节

1. 只处理本设计已允许的 CPU、单主服务、单步骤任务。用固定平台构建官方 `environment/Dockerfile`；独立 verifier 使用 Harbor 公共解析器选出的官方目录及 Dockerfile，保留原环境资源和阶段网络。
2. 构建 context 不包含额外文件，不修改 Dockerfile 的正文、依赖或测试。记录 Dockerfile/context 哈希、平台、镜像 config/content digest、实际工具版本和构建日志。构建失败不能进入模型阶段。
3. 在仓库外的运行根内复制入选任务；配置值差异仅允许 task.toml 中的镜像引用，以及为保持原继承语义而显式展开的等价 verifier 环境。TOML 用库序列化，排版变化另存文本 diff；其他文件逐字一致。保留原 Dockerfile 便于核对，Harbor 使用其公开的预构建镜像优先规则；不 patch 框架。

```toml
[environment]
# 原有 cpus、memory_mb、storage_mb、network_mode 等逐项不变
docker_image = "<由官方 environment/Dockerfile 构建并冻结的本地镜像引用>"

# 仅当原任务本来就使用独立 verifier 时生成，不把 shared 改成 separate
[verifier.environment]
# 原有或官方继承后的资源、网络、OS 逐项不变
docker_image = "<由官方 verifier Dockerfile 构建并冻结的本地镜像引用>"
```

4. 比较原始与运行配置的展开结果，除了镜像引用之外必须等价；指令、solution、tests、资源、网络、超时、artifacts 和 verifier 模式不得改变。分别记录原任务哈希、运行副本哈希和允许的差异。
5. 同一冻结镜像重新跑官方 oracle/nop；只有 1/0 且无基础设施错误才准入。FreeCAD 这次失败明确保留，后续若相同原 Dockerfile 仍失败则使用事先排序的候补，不观察两个变体成绩后换题。
6. 镜像不足或被清理时阻断，不静默重新构建后沿用旧 run_id；重新准备使用新运行。原有无自动 Trial 重试、冷启动、预算止损、凭据边界与离线报告保持不变。

7. 使用 Harbor 0.24.0 的公开 TaskConfig / verifier resolver 展开前后配置，验证资源、网络、评分模式及测试上传语义等价。独立 verifier 有官方 tests/Dockerfile 时构建该目录，保留 bundled_tests=true；无独立镜像/Dockerfile、原本回退主镜像时，只冻结主镜像，不给 verifier 强加镜像字段，保留 bundled_tests=false 与原测试上传行为。共享 verifier 仍共享。
8. 构建使用原始 context、Dockerfile、既定 linux/amd64 和官方 build_timeout_sec，另受本次整体时限约束。不给构建进程推理密钥，不添加业务源码、Pi 或 MemWeave 到 Dockerfile/context。原生与插件仍由正常 Agent setup 安装。
9. `images.py` 负责镜像构建、身份检查、运行副本及等价校验；runner 只在模型前执行候选准入。`selection.json` 保留原固定顺序；新增 `admission.json`（schema_version=1）记录逐候选来源哈希、准备证据、控制 Job 引用、准入/失败状态与原因。只有官方 oracle=1、nop=0 且无异常才准入；构建/控制失败继续下一候补，取消、整体止损或执行器错误停止。模型开始后不替换或重试。
10. `preparation/<task_id>/` 保存角色构建日志、镜像身份、Dockerfile/context 哈希、task.toml 文本 diff 和版本化 manifest；`runtime-tasks/<task_id>/` 保存运行副本。锁文件加入对应 manifest 引用与哈希。两目录和 admission.json 纳入原件索引，原件损坏使报告不完整。每个变体前后检查镜像身份、原任务及运行副本哈希；缺失时阻断，不静默重建。

本次用户已再次明确授权：新的正式 TB 运行最多 20 美元、8 小时，从该次 run 开始计算，包含准备、控制测试、模型和评分；开发时间不占该运行窗口。此前首次冒烟窗口与本轮分开记录，不删除旧结果。

直接变更范围为实验文档、`experiments/src/memweave_eval/images.py`、runner/storage 接线、相关测试及必要 TOML 写入依赖；不改产品或 Pi 核心。先测试配置等价、测试上传、平台/镜像缺失、候补和整体止损，再实现；实际容器控制与真实 Pi 结果分开报告。

确认依据：根 [AGENTS.md](../../AGENTS.md) 第 2 节和实验 [实现设计](IMPLEMENTATION_DESIGN.md) 第 3 节；用户已明确要求按“优先沿用官方 Dockerfile，补齐实验接线；构建仍失败的具体题目，记录失败并按既定候补规则处理”开始开发及真实对照。
