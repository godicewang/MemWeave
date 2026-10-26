# 实验系统验收记录

日期：2026-10-27。当前仍在实施验收，以下只记录已观察到的结果。

- Python 3.12.14、uv 0.13.5，锁定 Harbor 0.24.0；独立安装在 `experiments/.venv`。
- 31 项实验单元/替身及实际 Harbor 配置模型检查通过，Ruff 检查通过，Python 源码编译检查通过。这些不是模型通过证明。覆盖官方 Pro 解题禁用 verifier、重评分关联、资源不足降低并发、到期不启动新 Job、原件损坏、未知评分/费用、取消分类、派生诊断、独立 verifier 镜像及凭据泄漏阻断。
- 产品 Rule 资源一致性检查和 TypeScript 类型检查通过；未修改产品源码或定稿规范。
- 独立 Colima 0.10.3 / Lima 2.2.1，Docker daemon 29.5.2，8 CPU、16 GiB RAM、120 GiB disk。
- 已实际执行 Alpine 3.23.4 的 linux/amd64 与 linux/arm64 容器，分别返回 `x86_64` 与 `aarch64`。模型端点匿名请求返回 401，证明连接可达，不涉及推理。
- 虚拟机基础镜像中的 `/etc/resolv.conf` 曾指向不存在的 systemd-resolved 文件；只在该专用虚拟机内修复 DNS，未改任务网络协议。
- Compose 5.6.1、Buildx 0.38.1 已安装于仓库外专用工具目录。Buildx 二进制 SHA256 `6f20ba2437865311ef99015bf5d1039c3c8e4d2177c1c64aa41b134b5ecd3012` 已与官方 release asset digest 比对。
- 首次正式 Pro 预检 `20261026T164004Z-2930069ea1` 因 sidecar 平台设置错误停止：Harbor 按 daemon 架构构建 sidecar，而全局 `DOCKER_DEFAULT_PLATFORM` 错让它要求 amd64。已移除该全局变量，仅通过公开 Compose overlay 指定任务主容器 platform；不改任务。该失败运行原件保留，未发生推理。
- Pro 重测 `20261026T164818Z-53a5126492`：所选 NodeBB 任务的官方 oracle 在 linux/amd64 仿真中通过 117/117 必需测试，reward=1；nop 的 reward=0，均无异常。
- 该次原生 Pi 1.4.0 / Node 24.22.0 从 `/app` 正常启动，在 Agent 阶段实测模型端点可达且通用外网被阻断。原生 Session 记录 797425 输入 token（包含 771200 缓存 token）、7685 输出 token、估算 0.0217167 美元；只产补丁的解题 Job 没有 verifier 结果，随后官方全新沙箱重评分 reward=1。
- 同次 MemWeave 变体安装 NVM 时遇到 GitHub TLS 握手中断，未进入 Agent 执行、未产生补丁。整次报告为不完整，MemWeave 评分/费用保持未知，计划分母仍为 1；保留基础设施失败，不将它当作模型未解出。随后改用 NVM 官方支持的 `METHOD=script` 安装相同固定版本，避免 Git clone；新运行 `20261026T165811Z-9853d73783` 从头重验两变体，未覆盖旧记录，也不选取 best-of-N。
- 新运行 `20261026T165811Z-9853d73783` 已完整通过 Pro 单题/双变体链路。实验执行代码冻结于 `c4c8bfa`，产品包仍为上述 `f3931ce` 源码归档；后续离线报告补充计数与比较列，不改原件。

| Pro V2 变体 | 官方全新沙箱 reward | 输入（含缓存） | 缓存 | 输出 | Pi 估算 USD | Agent 秒 | 有 usage 的模型返回 |
|---|---:|---:|---:|---:|---:|---:|---:|
| pi-native | 1 | 1015700 | 985856 | 7247 | 0.023564736 | 163.744 | 41 |
| pi-memweave | 1 | 285134 | 250368 | 3506 | 0.016139208 | 35.736 | 16 |

这是一次完整配对，不是 best-of-N；前一个不完整运行另存。API 客户端内部重试次数无法仅由 Session 确定，表内是实际返回 usage 的记录数。双方均无 compaction；MemWeave 原生工具轨迹含 task_create 1 次、state_append 2 次，其中一次工具调用出错后模型自行纠正。记忆原件快照含 4 个文件，未复制认证或 embedding 权重。没有触发长程窗口压力，不能由该单题的时间/用量差值推断记忆收益。

正式原件位于仓库外默认根的 `runs/20261026T165811Z-9853d73783/`。`reports/report.md`、`reports/results.json`、`reports/trials.csv`、`reports/comparison.csv` 已实际生成；重评分、原始补丁哈希、Session 引用及两阶段网络探针均可核对。离线重建报告成功，原始文件哈希校验通过。归档前实际检查当前密钥字节序列，原件与记忆快照均未检出；没有把密钥写入报告。

Terminal-Bench 运行 `20261026T171138Z-a3c5a26691` 仅执行无模型控制预检，未进入冻结后的模型计划。所选 FreeCAD 的官方评分 Dockerfile 在安装 `gnucleus-freecad-validator[render]==0.1.3` 时，因 pip 不能卸载 conda/distutils 安装的 vtk 9.2.6 而失败，oracle/nop 均无评分；没有修改依赖绕过失败。

TB 另发现镜像冻结接线限制：该提交 66 题均仅提供 Dockerfile；实际 Harbor Compose 使用各 Trial 自动命名的本地镜像，收尾会删除，不能按 `hb__...` 假定它们仍存在。独立评分环境也不继承主环境的 Compose overlay。现在对没有可核对预构建镜像的任务明确阻断模型阶段；[冻结镜像与透明运行副本提案](DOCKERFILE_FREEZE_PROPOSAL.md) 待用户确认。不能宣称 TB 已完整跑通。

正式源码包来自提交 `f3931ce3b4d5d7b504e612e67cd46e4267f309a5` 的干净临时 checkout。归档 SHA256 为 `4d089821e9590380c8377afa8a44f3883b3a35b9f0696c0e99c2369ff2ab7c04`，77 个文件，未发布 npm。归档位于仓库外。

本轮所有模型 smoke 合计授权 20 美元、8 小时，首次正式运行始于 2026-10-27 00:40（北京时间），故整体截止时间为同日 08:40。两个任务集各配置最多 10 美元、4 小时；基础设施重验的时间与费用也计入整体范围。模型元数据 GET 不作为解题调用；上面的费用是 Pi usage 的估算，不是账单。

由于 Pro 基础设施重验已有 0.0217167 美元估算用量与已耗时间，随后 TB 实际 smoke 配置下调为最多 9.97 美元、13300 秒；即便当前 Pro 用满其 10 美元、4 小时，合计计划仍在原授权范围内。TB 此次也显式使用已实测的 linux/amd64，保持两变体同平台，未改变官方单题预算或资源。

截至上述验证，合计已知 Pi 估算费用为 **0.061420644 美元**（包括不完整运行的真实用量），TB 未产生模型费用。没有上传结果、提交榜单、发布 npm 或租用云资源。临时发现用的源码副本与失败可行性目录已清理；正式失败运行与原件保留。
