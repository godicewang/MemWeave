# wasm-simd 正式运行前验收

此文保留首次预检切面，包含当时的镜像和尚未运行项；最终冻结镜像、CLI守卫修复、真实canary、实际结果及缺项以[最终实验报告](MARATHON_REPORT_2026-11-01.md)为准，不能把此处早期门禁当作已覆盖真实CLI顺序。

2026-11-01，原 Mac 本地，付费模型请求 0。用户总上限 USD30，硬截止 2026-11-02T00:40:38Z。未推送、发布或购买环境。

## 冻结条件

- 原题 abundant-ai/swe-marathon `dd4d2bbc8d2ec8bb22fc4a4261d3b0c827faa2a4`，task hash `ce36e2b62e2d72ecade093b23fd9e02fd8e53392c1f66e705fba60188e65e458`。
- 原始未完成解释器，原 instruction/verifier/Dockerfile；每组 4 CPU、16384 MB、20480 MB、Agent 18000 秒、verifier 1200 秒。正式组独立新容器，不含参考解或已完成 checkpoint。
- 官方原镜像 `sha256:39fb3ee86e53c6ad9f610f9ba5f95d15ab25ef22e0e8d470c85accdaa1c27e49`；运行镜像 alias 可能不同，须保持同一 ID。
- 生产源码检查点 `207d746babd80b2381f04688d8d576c73429af30`；候选归档 SHA256 `5ed61de2eb9d8096cf063fb519c4b54c8f63b09cd518c00e4d228d1bed92f022`，逐文件与检查点核验。
- Harbor 0.24.0、Pi 1.4.0、Node 24.22.0。`deepseek-flash`，当前官方 DeepSeek-V4.1-Flash-1017 路由，thinking off、输出 16384。按官方峰值价格预留，实际返回 model/usage 记录于传输轨迹。
- 全局准入 29 USD，各组累计 12 USD，全部重试与重跑共用 `budgets/marathon-20261101/quota.json`，其余不自动转移。模型停止 00:15:38 UTC，容器兜底停止从 00:38:38 UTC 开始，硬截止 00:40:38 UTC。
- 二元案例固定在 `experiments/cases/wasm-simd-v1.json`：保护文件、依赖、公开测试、早期失败引用保留代理、原指令驱逐后的 State 保护约束交付及后续动作。第80个 usage assistant 返回后共同一次进度询问。原题 reward 单列；无驱逐/无依赖动作 N/A，缺证据 unknown，代理不称因果采用。

## 已执行检查

- `PYTHONPATH=experiments/src experiments/.venv/bin/python -m pytest experiments/tests`：251 passed，日志 `/tmp/memweave-marathon-20261101/pytest-final.log`。
- Node24 `node --test experiments/tests/pi-guard.test.ts`：3 passed，日志 `/tmp/memweave-marathon-20261101/pi-guard-final.log`。包含真实SDK DONE取消/重试、完整原生Pi压缩、真实请求摘要及公共steer。
- `ruff check experiments/src/memweave_eval experiments/tests`、`git diff --check`：通过。
- Node24、`MEMWEAVE_TEST_NPM_CACHE=/Users/godice/.npm npm_config_offline=true npm run check`：资源一致性/TypeScript/276 项产品测试通过，日志 `/tmp/memweave-marathon-20261101/npm-check-offline.log`。首次未使用缓存的兼容安装超时，保留原日志，不算通过。
- `npm pack` 本地归档及 `verify_package(..., commit)`：通过，不发布。
- 共享目录官方控制：oracle reward 1、31767/31767；nop reward 0、1931/31767，均无异常。原始 Cargo.toml 经 tomllib 逐字读取确认合法；早期关于多出括号的判断已纠正，未改动原题。
- 双容器共享额度：`quota-smoke-v2` 返回 [0,2]，只一个获准；0.7608 是假请求预留，不是真实费用。
- `deadline-smoke`：容器内仅停止指定 PID；宿主仅停止2个本次标签实例；无关测试实例未受影响。Docker查询/kill短暂失败回归会重试并确认，硬截止未确认会告警。
- `marathon-20261101-concurrent-v2`：两个完整容器与真实 Pi/候选包、内存假 HTTP，并发执行重叠 8.772509 秒；均无 Trial 异常。原生4工具、Rule0/State0；插件完整16工具、Rule1/State v1；全部 mock request_end settled=true，输出均16384，真实外部模型请求0。

共享证据根：`/Users/godice/.local/share/memweave-experiments/preflights/`。`/tmp` 中更早的 reward 回收失败及第一次 URL 假传输失败保留为失败预检，不能混作最终验收。

## 正式命令与门禁

```sh
PATH=/Users/godice/.local/share/memweave-experiments/tools/native/bin:$PATH \
DOCKER_HOST=unix:///Users/godice/.colima/memweave-eval/docker.sock \
DOCKER_CONFIG=/Users/godice/.local/share/memweave-experiments/tools/docker-config \
PYTHONPATH=experiments/src experiments/.venv/bin/python -m memweave_eval.cli run \
experiments/configs/marathon-wasm.yaml
```

入口先核验已提交的实验实现、官方题目、资源/架构、原评分控制、全部变体软件/真实假请求及无凭据网络策略，再写不可变 experiment.lock.json；之后才读取私有认证，启动两个并发 Job。正式 run ID、最终源码 hash、镜像与软件对象、价格、金标 hash、两组 Trial 和守卫原件以该 lock 及原始证据为准。

尚未验证真实模型解题结果、真实费用与实际驱逐；这些必须由正式运行回答。完整指标覆盖边界见 `experiments/有价值指标.md`，不将规范化谓词夹具冒充全部语义场景实测。
