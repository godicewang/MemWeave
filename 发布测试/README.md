# 发布测试

本目录保存改动后的发布回归入口、候选产物功能验收及执行方法。先按根目录 [发布.md](../发布.md)完成适配与开发自测，再进行这里的测试。它不发布 npm/GitHub 包、不操作远端标签、不改用户全局 Pi 或真实运行数据。

## 命令

需先按 package-lock.json 安装开发依赖，使用项目 .node-version 对应 Node。普通执行：

```sh
npm ci --ignore-scripts
npm run test:release
```

| 命令 | 执行范围 |
|---|---|
| `npm run test:release` | 资源/类型/单元/原生集成回归、构建、本目录的入口与候选产物验收 |
| `npm run test:release -- --distribution` | 基础回归，再执行现有 npm/Git 分发测试 |
| `npm run test:release -- --live` | 基础回归，再执行已打包产物的真实 DeepSeek 冒烟 |
| `npm run test:release -- --full` | 上述全部；是正式发布前的必经自动入口 |
| `npm run test:release -- --help` | 查看命令与限制，不运行测试 |

每个阶段失败即停止并返回非零退出码；后续阶段不会继续。完整模式要求干净候选，Git 分发固定当前 HEAD，不能拿 origin/main 的旧候选替代。入口默认不调用真实模型；`--live` 和 `--full` 会调用真实 DeepSeek，复用仓库外 `~/.local/share/memweave-dev/pi-agent/` 私有配置。具体供应商专项仍按矩阵补测。

“基础”不是完全离线：包的运行依赖及历史 Pi fixture 可能从 npm 下载。分发阶段需要仓库 SSH 权限和网络，真实模型阶段需要私有认证；缺失不自动跳过。临时 Package、Session、State 与测试替身放在系统临时目录，结束后清理。

2026-10-26 用户要求：真实供应商和候选包功能验收必须使用完整 Pi 默认 System、原生工具和当前完整 MemWeave Rule/入口，不使用 NATIVE_SYSTEM/NATIVE_APPEND 哨兵替换，不缩减默认工具清单。测试数据、业务夹具、认证与运行目录仍隔离在系统临时目录；模型沿用本机 DeepSeek Flash/off 设置，不擅自更改采样。提供方/tokenizer 的独立校准明确标为控制实验，不能替代完整插件验收。哨兵提示仅供确定性 System 发现/优先级兼容测试使用，不计为真实默认环境。

组件业务夹具的 target_timeout_ms 是必须精确设置的目标，保留等值验收；恢复写入夹具保存一条真正新增的发布约束，保留版本、证据、原文及旧 State 前缀检查，避免要求重复保存已有 Fact 与 Rule 冲突。失败时记录最小工具/请求轨迹，不保存密钥或完整私有请求。

## 组织方式

- [测试矩阵](测试矩阵.md)：哪些用例必做、对应的现有测试、何时补人工或真实供应商验收。
- [适配方法](适配方法.md)：Pi 1.4.0、npm 和 GitHub 首发沉淀的方法及反例。
- [验收记录模板](验收记录模板.md)：记录候选、命令、失败修复、范围与发布后检查，不保存密钥或完整真实请求。
- [弹性预算验收](../docs/ELASTIC_BUDGET_VALIDATION.md)：40/40/20 分池、续读/到期截断、双宿主/真实 API、图片和性能；本地性能脚本在 `性能/elastic-budget.mjs`。
- [上下文显示审计](执行记录/2026-10-25_上下文显示.md)：修复前实际终端低中高负荷、Flash 66 万 token、API/TUI 对照。
- [上下文显示修复](执行记录/2026-10-25_上下文显示修复.md)：复用原生底栏显示上次成功请求、双宿主回归与真实 DeepSeek 三档/缩窗复测。
- [入口首次验收](执行记录/2026-10-24_入口验收.md)：本目录实际运行的结果、首轮失败与修正，不能替代后续候选验证。
- `run.mjs`：顺序调用既有测试和本目录用例，不再维护一套业务实现。
- `入口.test.mjs`：命令帮助、非法参数和使用方式的阻断边界。
- `产物.test.mjs`：两次打包的一致性、发布资源边界，同一归档加载后在独立 Pi 进程创建/恢复 Task、读取原文、提交 State 和 Window，并核验原有 Session 消息。

本目录只负责验收和方法，不重新定义 Task/State/Rule/Recent Window。核心期望以 docs/INDEX.md 指向的规范为准；发现不一致先讨论，不能通过修改测试期望掩盖回归。

## 发布前后区别

本地归档与本机临时 registry 是发布前验证，不能冒充 npm 公网安装；Git 测试要记录实际 ref 和 SSH/HTTPS；真实 Pi + 本机 HTTP 是实际宿主验收，但不是供应商 API 验收。发布后还须从目标 registry 下载该版本，核验 integrity、安装、恢复及标签。任何一个绿色命令均不自动授予发布权限。
