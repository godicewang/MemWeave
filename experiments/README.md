# RSI-Orin：保留的实验环境

本分支已按用户要求撤下旧指标、百分制评分器、派生题目及其专用运行入口。新的 RSI 技术方案见 [RSI_TECHNICAL_DESIGN.md](../docs/RSI_TECHNICAL_DESIGN.md)；本次仅整理方案，未实现 RSI 执行系统。

保留内容：

- `suites/` 的上游来源与固定提交、`subsets/` 的原题选择清单；这些文件不包含附加题面或判定 hook。
- `configs/smoke.yaml`、`configs/baseline.yaml` 的原题环境模板，以及历史 `long-horizon-49.yaml` 配置。模板仍需完整归档身份；历史配置不构成新的运行授权。
- Harbor/Pi 软件环境准备、镜像构建与校验、原始官方产物重放、运行缓存、私有配置隔离、外置凭据传输、费用准入和停止组件。
- 仓库外已有工具、Docker/Colima 环境、镜像、原题源缓存、历史运行日志与账本。本次没有重建环境、删除历史证据或释放未知费用预留。

已删除：旧 State/工程/行为/财务派生指标与评分注册表、旧报告生成及 Campaign/配对调度接线、`cases/` 中的定制题目合同与额外协议、对应夹具/脚本/专用配置和测试。传输守卫仍记录费用与请求身份，但不再解释 State 真值、注入派生任务或追加进度消息。共享 sealed-runtime 环境组件保留，不代表任何旧派生题目可以继续使用。

`memweave-eval` 当前仅保留离线 `validate CONFIG`；原 `run`、`report`、`score-report`、`score-cases` 等入口均已移除。不得把历史配置、日志中的派生题面或历史成绩重新用作 RSI 题库。

## 环境开发检查

已有虚拟环境与依赖锁文件继续保留：

```sh
cd experiments
uv sync --locked
uv run --locked pytest
uv run --locked ruff check src tests
uv run --locked memweave-eval --help
```

本机现有环境位于仓库外 `~/.local/share/memweave-experiments/`，Docker endpoint 为 `unix://$HOME/.colima/memweave-eval/docker.sock`，专用工具位于该根目录的 `tools/`。本次未切换个人 Docker context、修改服务或电源设置。

旧实验设计和结果保留在 [历史资料目录](../docs/experiments/README.md)及 Git 历史。它们是归档证据，不是本分支的有效指标或新 RSI 设计要求。恢复旧评分器需显式切换历史提交；当前分支不提供复用这些定制题目的执行路径。
