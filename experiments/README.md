# MemWeave 公开基线实验

在官方任务环境中实际重跑原生 Pi 和 Pi + MemWeave，保存原件，离线生成 JSON、CSV 和 Markdown 对照。只接入 Terminal-Bench 4.0 与 SWE-bench Pro V2，不包含自进化。行为边界见 [实现设计](../docs/experiments/IMPLEMENTATION_DESIGN.md)，实际通过范围见 [验收记录](../docs/experiments/VALIDATION.md)。

当前验收：Pro V2 的完整真实对照已跑通；TB 4.0 的 Dockerfile 镜像冻结适配尚待确认，不宣称已跑通。TB 首题官方评分镜像构建失败，没有发起模型请求；方案见 [待确认提案](../docs/experiments/DOCKERFILE_FREEZE_PROPOSAL.md)。没有可核对的镜像身份时执行器阻断模型阶段。

## 安装实验依赖

需要 Python 3.12–3.13、uv、可用的 Docker daemon、Compose 和 Buildx。依赖与产品 npm 环境独立：

```sh
cd experiments
uv sync --locked
uv run --locked pytest
uv run --locked ruff check src tests
```

Docker 可复用已有安装。macOS 新环境可使用 Colima；本轮本机安装在仓库外的专用工具目录，避免切换个人 Docker context：

```sh
export PATH="$HOME/.local/share/memweave-experiments/tools/native/bin:$HOME/.local/share/memweave-experiments/tools/bin:$PATH"
export DOCKER_CONFIG="$HOME/.local/share/memweave-experiments/tools/docker-config"
export DOCKER_HOST="unix://$HOME/.colima/memweave-eval/docker.sock"
colima --profile memweave-eval status
docker info
docker compose version
docker buildx version
```

本轮虚拟机为 8 CPU、16 GiB RAM、120 GiB disk，VZ/Rosetta，关闭 SSH agent 转发和自动切换 context；仅将实验根目录挂载到虚拟机。被测容器不挂载宿主 home 或 Docker socket。amd64 和 ARM 镜像可能同时存在；执行器实际运行对应架构探针，检查磁盘并按内存降低并发，不削减官方资源。

## 准备冻结输入

`configs/smoke.yaml` 和 `configs/baseline.yaml` 是有意不能直接运行的模板。填写完整源码提交、仓库外 npm 归档路径与 SHA256；不能使用 `latest`、短提交或占位哈希。沿用项目构建检查，使用干净提交的临时 checkout 执行 `npm pack`，不改变版本或发布 tag。执行时还逐文件比对归档与指定提交；不能把当前未提交源码冒充冻结包。

把填好的配置保存在仓库外时，将 `suite`、`subset` 改为可解析的绝对路径。运行根目录默认 `~/.local/share/memweave-experiments/`，必须在所有 Git 工作区外。它保存缓存及 `runs/<run_id>/` 原件；不要提交个人配置、归档、Session、State 或密钥。

`suites/` 锁定官方提交；`subsets/` 只声明筛选规则和规模。筛选保留原题指令、环境、评分和预算，按已声明的资源、分组和 SHA256 顺序确定任务；`selection.json` 保存全部入选、候补和排除理由。不能根据两个变体的解题成绩挑题。初始 smoke 默认 2 题，baseline 模板 12 题；数量可在实际运行前明确调整，baseline 模板不代表已授权扩大运行。

子集 seed 只控制选题，不对模型 API 的随机性作确定性承诺。

首次模型冒烟的用户授权是**两个任务集合计最多 20 美元、8 小时**。如果分开运行，须分配总额度，例如每个任务集最多 10 美元、14400 秒；不能把两个模板各自的上限相加当成新授权。模板默认也按这份分配填写。官方单题超时保持不变，整体止损可能提前取消任务，结果保留为中断。

唯一认证来源为仓库外 `~/.local/share/memweave-dev/pi-agent/auth.json` 的 DeepSeek API-key 条目；只把所需条目作为私有文件交给容器。不要把密钥粘贴到 YAML、命令参数或 Git。初始模型为 `deepseek-flash`、thinking off；两个变体使用同样设置。费用来自 Pi 原生 usage 的估算，缺失为未知；不是账单或精确硬消费上限。

## 三个入口

```sh
uv run --locked memweave-eval validate /absolute/path/to/experiment.yaml
uv run --locked memweave-eval run /absolute/path/to/experiment.yaml
uv run --locked memweave-eval report /absolute/path/to/runs/RUN_ID
```

`validate` 只读本地配置和已有归档，不下载、安装、启动容器或调用模型。它会列出尚待运行预检的项目，不证明任务已经可用。

`run` 要求实验源码已提交。它解析精确上游，做 Docker/架构/容量预检，执行官方 oracle 与 nop 控制测试，冻结清单与镜像身份，然后顺序运行两个变体的 Harbor Job。每个任务/变体/重复均是独立冷启动；Harbor 管理任务并发。新调用始终生成新 run_id；没有自动重试、续跑或 best-of-N。Ctrl-C、时间和估算费用止损都会收尾并保留已有原件。

Pro V2 解题 Job 显式关闭 verifier，按官方口径捕获包含未跟踪文件的补丁，并为捕获保留官方 60 秒收尾时间。只有对应原尝试及补丁存在时，才交给同一上游的 `PatchReplayAgent` 在全新沙箱评分。离线 Agent 阶段检查模型端点可达、通用外网被阻断；不能放宽网络绕过失败。主评分来自重评分，模型费用来自原始解题尝试。

`report` 不连接 Docker、网络或模型。它校验原件哈希并重建派生报告，保留全部计划行。缺失判分不计作失败得分，也不删除分母；未知费用不写成零。退出码：0 为流程完整（包括有效的未解出题），1 为配置/预检/程序错误，2 为取消、止损或不完整结果。

## 查看结果和诊断

- `selection.json`：冻结前筛选依据、任务哈希和排除原因。
- `experiment.lock.json`：配置、源码/包/上游/工具/镜像身份及全部计划行。
- `run.json`：Job 路径、原尝试与 Pro 补丁关联、停止原因和完整性。
- `harbor/`：原生 Job/Trial、评分输出、直接写入的 Pi Session、派生 ATIF、Pro 补丁和允许的记忆快照。
- `harbor-console/`：本地诊断输出；不自动上传，也不作为可公开分享的报告。
- `evidence-index.json`：原件路径与 SHA256；报告发现任意损坏会标记结果不完整。
- `reports/`：逐任务 JSON/CSV、变体比较 CSV、Markdown 报告，可离线重建。

Agent 正常使用 Pi 默认提示和原生工具；MemWeave 使用生产入口与完整默认 Rule。安装阶段准备原有 embedding 资源，不把它变成 Pro 离线阶段的网络例外。原始聊天只由 Pi Session 保存，不另建全量聊天数据库。

两个任务集分别报告。小样本、资源筛选、amd64 仿真和未触发记忆压力的限制均须保留；本地子集结果不能冒充官方榜单或证明长程记忆优势。遇到官方协议与实现冲突、平台不可靠或权限扩大，遵守设计第 3 节，先对齐重大决定，再继续受影响实现。
