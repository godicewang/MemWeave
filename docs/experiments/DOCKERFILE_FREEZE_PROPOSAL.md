# Terminal-Bench Dockerfile 镜像冻结待确认方案

状态：待用户确认；未按本提案生成运行副本或改动上游任务。

日期：2026-10-27

## 第一部分：目的、范围与取舍

Pro V2 的官方镜像、解题只产补丁和全新沙箱评分已通过真实模型冒烟。TB 4.0 还需要解决镜像冻结问题，才能宣称两个变体在冻结的环境中比较。

当前固定的 TB 4.0 提交中，66 题均没有 `environment.docker_image`，依靠 Dockerfile 构建。实际 Harbor 0.24.0 wheel 的 `docker-compose-build.yaml` 不设置固定 image 名；Compose 按 Trial project 生成镜像，并在 `down --rmi local` 时删除。镜像还带有各 Trial 的 Compose 标签。现有按 `hb__<environment hash>` 在 Job 收尾后查镜像的做法不能成立，不能把 Mock 检查当成实际支持。

此外，独立 verifier 明确不继承 `extra_docker_compose`。本次 FreeCAD 解题环境按 amd64 构建，官方评分环境按 daemon 的 arm64 构建；后者在安装 validator 时遇到 pip 无法卸载 conda/distutils 的 vtk 9.2.6，oracle 与 nop 均没有评分。系统没有修改 Dockerfile、依赖或测试去绕过失败，也没有对此题发起模型请求。

推荐：保留上游 checkout 原样，提前按各任务的原始 Dockerfile 分别构建解题与独立评分镜像，固定实际镜像内容身份。在仓库外生成透明的运行副本，仅把构建结果作为 Harbor 原生 `docker_image` 输入。两变体引用同一镜像，不修改题目、测试、资源、网络或超时。仍无法构建或无法通过官方控制测试的任务明确排除，在被测候选运行前按原候补顺序替换；不能修补评分依赖后继续冒充原任务。

优点是保留现有 Harbor/Pi，保持官方解题与评分语义，并能锁定本次实际构建出的环境。代价是本地运行副本的 task.toml 不再逐字等于上游，必须同时记录原始与派生哈希、差异及构建证据，明确它是本地冻结执行；不能声称采用上游发布的预构建镜像。

另一个选择是维持逐字原任务边界，暂时只验收 Pro V2 的实际运行；TB 的配置和诊断保留，停止在模型阶段之前，等待允许的上游接入方式。本轮不会自行换任务集、改评分依赖、换 Harbor 版本、部署云环境或放宽冻结要求。

## 第二部分：拟实现细节

1. 只处理本设计已允许的 CPU、单主服务、单步骤任务。用固定平台构建官方 `environment/Dockerfile`；独立 verifier 使用 Harbor 公共解析器选出的官方目录及 Dockerfile，保留原环境资源和阶段网络。
2. 构建 context 不包含额外文件，不修改 Dockerfile 的正文、依赖或测试。记录 Dockerfile/context 哈希、平台、镜像 config/content digest、实际工具版本和构建日志。构建失败不能进入模型阶段。
3. 在仓库外的运行根内复制入选任务；与上游不同的内容仅允许 task.toml 中的镜像引用，示意差异如下。保留原 Dockerfile 便于核对，Harbor 使用其公开的预构建镜像优先规则；不 patch 框架。

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

需要确认的原因：根 [AGENTS.md](../../AGENTS.md) 第 2 节要求“存在多个会改变外部行为、恢复语义或数据格式的合理方案”时先询问；实验 [实现设计](IMPLEMENTATION_DESIGN.md) 第 3 节要求对任务转换、环境协议和核心冻结边界先对齐。这是对新发现接入限制的提案，尚不是已授权的实现。
