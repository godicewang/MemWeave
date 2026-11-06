# RSI-Orin 代码清理记录

用户要求先保存当前版本，再创建 RSI-Orin，删除旧指标和经过修改或加入 hook 的题目；保留实验环境与未修改原题。本次只整理用户给出的 RSI 方案，未实现自进化执行器、未启动模型实验、未推送。

## 保存与分支

- 开始时为 `main`，HEAD `d12042fbb837e6240cd220dfb823cc242acbc732`；只有一份已有审计文档存在 26 行改动。
- `7909899` 保存该改动，形成清理前检查点。
- 从该检查点新建 `RSI-Orin`，未覆盖任何既有分支。
- `1f9c434e0b050fad62d0725869f181d40b85196d` 提交用户原述的结构化方案 `docs/RSI_TECHNICAL_DESIGN.md`；方案中的百分比歧义仍保留原话。收到后续指示后未再修改该方案。
- 精确删除／修改清单与原题来源提交见 [机器清单](RSI_ORIN_CLEANUP.json)。历史文件可从上述 Git 检查点恢复，但不得把旧派生题目重新投入本分支实验。

## 清理边界

删除 103 个已提交、可恢复的文件：

| 范围 | 文件数 | 删除依据 |
|---|---:|---|
| `experiments/cases/` | 27 | TB-01 附加协议、隐藏派生判定和 Marathon/wasm 行为评分合同，均非未改动的上游原题 |
| `experiments/fixtures/` | 3 | 旧定制行为 oracle 的正／负／缺证据夹具 |
| `experiments/scripts/` | 1 | TB-01 派生效果突变脚本 |
| `experiments/configs/` | 9 | 绑定旧派生 case、gold、额外输入或重跑协议的执行配置 |
| `experiments/src/` | 29 | 旧 State/工程/行为/财务派生指标、百分制注册表、评分器、报表、Campaign/配对执行与 TB-01 专用代码 |
| `experiments/tests/` | 33 | 被删除模块和专用题目的测试 |
| `experiments/有价值指标.md` | 1 | 旧指标口径文件 |

对混合模块拆除旧 gold／评分门禁、State 真值抽取、派生请求边界、额外进度输入、题面时间改写与专用工具 hook。`checkpoint_observer.ts` 现在只附加传输守卫；不注册业务工具、不追加用户消息。旧 CLI 的 `run/report/score-*` 等入口撤下，仅保留离线 `validate`。

## 保留范围与验证

- 产品 `src/`、根 `tests/`、运行资源和 `docs/specs/` 相对于方案提交没有变化。
- 三份 `experiments/suites/` 固定来源、全部 YAML 原题选择清单保持原字节。`smoke.yaml`、`baseline.yaml` 原题模板和 `long-horizon-49.yaml` 历史配置保留；后者的旧执行器已撤下。
- 保留 Harbor、Pi、Node 的软件准备、镜像构建校验、缓存、官方产物重放、私有目录隔离、外置凭据服务、费用预留／结算、截止和进程归属控制。共享 sealed-runtime 环境组件保留，已与旧定制题目接线分离。
- 不改动 `experiments/.venv/`、锁文件、仓库外工具／镜像／Colima 环境。费用准入和完整性记录用于安全运行，不参与旧指标打分。
- `/tmp/memweave-35-20261102/sources/` 下 8 个上游源码仓库（TB4、Marathon、Slop、Slop runner、STATE、Switch、Interrupt、MAB）均经 `git status --porcelain` 核实为干净；精确提交见机器清单。
- 仓库外历史运行、账本、冻结包、日志及其内的定制任务副本原样留作证据，没有批量永久删除。它们不属于当前可执行题库，不重新使用。无法逐项证明来源的外部历史文件同样未误删。
- `docs/experiments/` 中的旧结果和审计保留为历史资料；入口 README 与索引明确其不再是当前有效指标或执行说明。

## 实际执行检查

| 命令／检查 | 结果 |
|---|---|
| `experiments/.venv/bin/python -m pytest experiments/tests --junitxml=/tmp/memweave-rsi-tests.xml -q` | 138 项通过，0 失败／错误／跳过；本地假 provider 与回环服务，无真实供应商请求 |
| `experiments/.venv/bin/ruff check experiments/src experiments/tests` | 通过 |
| `experiments/.venv/bin/python -m compileall -q experiments/src` | 通过 |
| `PATH=<本机 Node24>/bin:$PATH MEMWEAVE_TEST_NPM_CACHE=/Users/godice/.npm npm_config_offline=true npm run check` | Rule 资源核对、TypeScript 类型检查及 276 项产品测试通过 |
| `<本机 Node24>/bin/node --test experiments/tests/pi-guard.test.ts` | 2 项通过：真实 Pi SDK + 假 provider 的重试／原生压缩额度接线，以及旧进度环境变量不能追加消息 |
| `experiments/.venv/bin/python -m memweave_eval.cli --help` | 仅显示 `{validate}` |
| Python 相对 import 闭包 | 22 个保留模块无缺失目标 |
| `git diff --check` | 通过 |

首次沙箱内回归的本地监听因 EPERM 失败；经正常权限流程运行本地回环测试后，上表均通过。曾有一次批量删除被自动审批拒绝，原因是混入原题选择配置及共享环境组件；未执行该清单，收窄并重新核对后批准执行上述 103 项删除，相关环境文件保留。

未运行真实模型、benchmark、发布验收、npm 发布或 push；未修改用户运行时 State（本会话无 State 专用工具），未使用 Bash 改写 State。新 RSI 系统尚未实现。清理完成后，用户又提供并对齐第二版方案；当前 `docs/RSI_TECHNICAL_DESIGN.md` 已整合为 v2，明确百分点、首次通过停止、单进化 Agent，以及保存／记忆／Graph 机制；本记录前述 `1f9c434` 仍是第一版方案的历史检查点。
