# MemWeave 公开基线实验

在官方任务环境中实际重跑原生 Pi 和 Pi + MemWeave，保存原件，离线生成 JSON、CSV 和 Markdown 对照。只接入 Terminal-Bench 4.0 与 SWE-bench Pro V2，不包含自进化。行为边界见 [实现设计](../docs/experiments/IMPLEMENTATION_DESIGN.md)，实际通过范围见 [验收记录](../docs/experiments/VALIDATION.md)。

当前历史结果：Pro V2 四题原生 4/4、插件 3/4；TB 四题原生均有效未通过，插件一题有效未通过、三题在安装阶段失败。软件缓存改造用于减少重复安装和提前发现此类问题，不改变这些历史成绩。边界见 [镜像接线方案](../docs/experiments/DOCKERFILE_FREEZE_PROPOSAL.md) 和 [软件缓存设计](../docs/experiments/RUNTIME_CACHE_DESIGN.md)，实际验证见验收记录。

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

2026-10-27 用户为本次 TB 接线后的新运行再次授权最多 20 美元、8 小时，从该次正式 run 开始，包含构建、控制、解题与评分。先前首次窗口与新窗口独立记录；不据此自动放大后续运行。

唯一认证来源为仓库外 `~/.local/share/memweave-dev/pi-agent/auth.json` 的 DeepSeek API-key 条目；只把所需条目作为私有文件交给容器。不要把密钥粘贴到 YAML、命令参数或 Git。初始模型为 `deepseek-flash`、thinking off；两个变体使用同样设置。费用来自 Pi 原生 usage 的估算，缺失为未知；不是账单或精确硬消费上限。

## 三个入口

```sh
uv run --locked memweave-eval validate /absolute/path/to/experiment.yaml
uv run --locked memweave-eval run /absolute/path/to/experiment.yaml
uv run --locked memweave-eval report /absolute/path/to/runs/RUN_ID
```

`validate` 只读本地配置和已有归档，不下载、安装、启动容器或调用模型。它会列出尚待运行预检的项目，不证明任务已经可用。

`run` 要求实验源码已提交。它解析精确上游，做 Docker/架构/容量预检，执行官方 oracle 与 nop 控制测试，再对全部任务的两个变体完成无凭据、无模型的软件准备与完整入口加载检查。全部通过后冻结镜像、软件对象与计划，再顺序运行正式 Harbor Job。每个任务/变体/重复使用新的可写实例；固定软件由缓存复制，Harbor 管理任务并发。新调用始终生成新 run_id；没有自动重试、续跑或 best-of-N。Ctrl-C、时间和估算费用止损覆盖准备阶段，都会收尾并保留已有原件。

软件缓存在 `<实验根>/cache/agent-assets/v1/`：Node 官方下载按精确版本/架构复用，Node+Pi 安装和插件依赖按官方镜像 ID/平台/版本/准备代码哈希复用，插件再绑定候选包；embedding 按产品资源与路径清单哈希复用。首次遇到新镜像或软件身份仍需准备，后续 Trial 不运行 npm、NVM 或资源下载。原生 Pi 只接收 Node+Pi；插件包与模型归档分开保存。缓存不包含认证、设置、Session、Task、State 或搜索索引，也不接收正式 Trial 的回写。

准备失败会在首次模型调用之前阻断，不能把公共软件错误当成解题失败或据此替换任务。正式 Trial 的缓存缺失、摘要不符会报错，不能静默重装。需要重建时，在没有活动运行的情况下显式移除相应对象目录，再发起新 run；不要删除历史 `runs/`。此优化没有重启旧实验，也没有延续已经结束的费用窗口。

TB 使用原始 Dockerfile 和 context 构建两阶段镜像，运行副本只调整镜像引用及必要的等价继承展开；TOML 排版 diff 单独保存，其他文件逐字不变。按公开 Harbor resolver 保持共享/独立 verifier、资源、网络与测试上传语义。构建或官方控制失败时，按 selection.json 的既定候补顺序在模型阶段前替换并记录；整体止损不触发替补，模型开始后不因答错换题。独立 verifier 资源也参与并发容量检查。

Pro V2 解题 Job 显式关闭 verifier，按官方口径捕获包含未跟踪文件的补丁，并为捕获保留官方 60 秒收尾时间。只有对应原尝试及补丁存在时，才交给同一上游的 `PatchReplayAgent` 在全新沙箱评分。离线 Agent 阶段检查模型端点可达、通用外网被阻断；不能放宽网络绕过失败。主评分来自重评分，模型费用来自原始解题尝试。

`report` 不连接 Docker、网络或模型。它校验原件哈希并重建派生报告，保留全部计划行。缺失判分不计作失败得分，也不删除分母；未知费用不写成零。退出码：0 为流程完整（包括有效的未解出题），1 为配置/预检/程序错误，2 为取消、止损或不完整结果。

## 查看结果和诊断

- `selection.json`：冻结前筛选依据、任务哈希和排除原因。
- `admission.json`：TB 按固定候选顺序的构建/控制准入与失败原因，不含模型成绩。
- `preparation/`、`runtime-tasks/`：TB 原始构建日志、镜像身份、配置 diff、等价校验和仓库外运行副本；均纳入证据索引。
- `experiment.lock.json`：配置、源码/包/上游/工具/镜像身份及全部计划行。
- `runtime-assets.json`、`runtime-assets.lock.json`：本次软件计划、冻结对象摘要与来源；原件离线可读，不要求历史报告读取全局缓存。
- `run.json`：Job 路径、原尝试与 Pro 补丁关联、停止原因和完整性。
- `harbor/`：原生 Job/Trial、评分输出、直接写入的 Pi Session、派生 ATIF、Pro 补丁和允许的记忆快照。
- `harbor-console/`：本地诊断输出；不自动上传，也不作为可公开分享的报告。
- `evidence-index.json`：原件路径与 SHA256；报告发现任意损坏会标记结果不完整。
- `reports/`：逐任务 JSON/CSV、变体比较 CSV、Markdown 报告，可离线重建。

Agent 正常使用 Pi 默认提示和原生工具；MemWeave 使用生产入口与完整默认 Rule。安装阶段准备原有 embedding 资源，不把它变成 Pro 离线阶段的网络例外。原始聊天只由 Pi Session 保存，不另建全量聊天数据库。

`experiment-setup.json` 分别记录缓存命中、对象摘要、独立配置和部署秒数；预检原件为 `runtime-preflight.json`。预检使用完整 Pi SDK/生产扩展加载，并实际运行本机 embedding，不发起模型推理，不能当作任务能力成绩。报告单列软件准备 Job、正式解题 Job 和整体墙钟；首次准备与缓存命中的运行需要分别解释。

两个任务集分别报告。小样本、资源筛选、amd64 仿真和未触发记忆压力的限制均须保留；本地子集结果不能冒充官方榜单或证明长程记忆优势。遇到官方协议与实现冲突、平台不可靠或权限扩大，遵守设计第 3 节，先对齐重大决定，再继续受影响实现。
