# State 写入容错与实验指标验收

日期：2026-10-29。位置：本机 `/Users/godice/Coding/MemWeave`。开始时工作区干净，已有检查点 `939c142`；本次修改保留为本地 diff，未推送、发布或部署。

## 变更范围

用户授权把运行时正文拒绝线从默认 100 放宽到 200，模型仍按 100 编写。先在 State 规范 §21 注明容错，再修改唯一共享校验器 `src/state/content.ts`：按配置目标的两倍拒绝，继续按 Unicode 码点计数，不截断。共享范围包括 task_create.goal、update_goal.goal、state_append.items[].content 和 modify_fact.append_fact.content；配置值、固定 Rule、工具说明、预算和 Window 均保持。原子批次、幂等和 token 准入代码不变。

实验增加纯离线 `state_metrics.py`，接入原有 schema1 `report.py` 与 schema2 `campaign_report.py`。每个任务／变体／重复运行行保存完整 `state_metrics` 与 CSV 标量字段，Markdown 显示密度告警、间隔和各写工具结果。指标不影响模型提示、实验执行、原件或官方评分。定义及边界见 [有价值指标](../../experiments/有价值指标.md)，入口见 [实验 README](../../experiments/README.md)。

## 实际执行

Node 使用项目指定的 `24.22.0`，Pi 开发宿主为 `1.4.0`，Python 使用现有 `experiments/.venv`（3.12）。所有测试使用替身、本机 HTTP 或离线原件，未调用真实模型。

| 命令 | 观察结果 |
|---|---|
| `node --test tests/unit/state-store.test.ts`（实现前） | 新测试在 101 字处失败，复现旧拒绝线 |
| `node --test tests/unit/state-store.test.ts tests/integration/state-constraints.test.ts` | 5/5；100、101、200 接受，201 原子拒绝，Unicode、Goal、modify_fact、幂等检查通过 |
| `PATH=/Users/godice/.local/share/memweave-dev/node-v24.22.0-darwin-arm64/bin:$PATH MEMWEAVE_TEST_NPM_CACHE=/Users/godice/.npm npm_config_offline=true npm run test:release` | 退出 0；资源检查、类型检查、276/276 单元及原生 Pi 集成、构建、5/5 入口及候选产物检查通过 |
| `cd experiments` 后 `.venv/bin/python -m pytest` | 211/211 通过，含新增 21 项统计测试 |
| `cd experiments` 后 `.venv/bin/python -m ruff check src tests` | 通过 |
| `git diff --check` | 通过 |

新增统计测试覆盖：比例闭区间边界、零事件／零分母／短样本、多条批次、失败重试、原件重复及幂等、已提交但失败的回执、Goal／其他写工具分列、归档／滑窗后的存量、内部间隔与首尾段、零／一／两次写入、相同模型位置的零间隔、均匀／不均匀间隔、旧轨迹缺 usage／缺 isError、来源无法定位、损坏原件、两种报告的 JSON／CSV／Markdown 集成、原件哈希失效和历史重试隔离。

首次沙箱回归中，本机端口监听被系统拒绝，实验出现 4 项 setup error；在授权的本机测试权限下重新执行全部通过。产品第一次 Node 24 `npm run check` 为 275 通过、1 项旧 Pi 1.3 测试宿主冷安装超时；使用已有缓存离线执行上表默认入口后，包含该恢复测试的 276 项全部通过。没有通过修改测试超时或跳过检查来消除这些环境问题。默认入口的旧宿主数据恢复测试通过，不等于另外完成了 Pi 1.3 全量类型与专项矩阵。

本次完整日志暂存 `/tmp/memweave-state-release.log`；产品首次失败日志为 `/tmp/memweave-state-check-node24.log`。未执行 `--full`、分发专项、真实 DeepSeek 或新的付费 A/B 实验，默认入口通过不构成完整发布验收。

## 历史原件只读核对

读取原 49 题最终主运行清单，对每个插件 Trial 的 result、Session、memory.tar.gz 与其原运行 evidence-index 的 SHA256 逐一比对，再运行新指标函数。未调用报告重建入口改写历史报告，也未改变历史官方成绩、原件或历史重试。

| 核对项 | 结果 |
|---|---:|
| 插件主任务原件校验 | 49/49 |
| state_append 尝试／成功批次／失败／未知 | 272 / 84 / 188 / 0 |
| 累计落地 F/D（含 modify_fact 新 Fact，排除 Goal） | 226 |
| 带 usage 的 assistant 返回 | 2755 |
| 所有新增 F/D 可按原生调用稳定 ID 定位的任务 | 49/49 |
| 每任务密度：正常／过密／过稀 | 19 / 20 / 10 |

这些数字验证了指标读取及归因，不能把 84 个成功批次当成 226 条事件，也不能把 188 次失败全部归因于长度。新拒绝线能减少哪部分真实失败及其实际比例，仍需以后另行授权真实模型实验；本次不据此宣称实测成功率已提升。聚合比例也不能代替逐任务告警。

只含指标和公开任务 ID 的核对结果暂存 `/tmp/memweave-state-metrics-long49.json`，未复制原文聊天、认证或完整 State 到仓库。
