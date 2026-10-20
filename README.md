# MemWeave — Pi Long Task Agent

本仓库用于构建运行在原生 Pi 内的长程任务记忆扩展，以 Pi Package 经 npm 或 Git 分发。用户继续使用 `pi`，复用原生循环、界面与 Session。首个兼容验收目标为 Pi v1.3.0，宿主版本由用户安装决定。

## 开始前

1. 阅读 `AGENTS.md`。
2. 阅读 `docs/INDEX.md` 和当前任务对应的 `docs/specs/`。
3. 复现 `docs/PHASE_0_VALIDATION.md` 中的接入检查，再按实施计划推进当前阶段。
4. 每个阶段按验收范围开发，不提前生成整套业务实现。

## 文档

- `docs/ARCHITECTURE.md`：代码与运行时文件的职责边界。
- `docs/PACKAGING.md`：分发方式、宿主依赖、已接受的副作用与兼容边界。
- `docs/IMPLEMENTATION_PLAN.md`：分阶段 Vibe Coding 计划。
- `docs/specs/`：五份已定稿行为规范，设计调整须先讨论确认。

源代码仓库、Pi Session 和 `~/.pi/memory/` 运行时数据必须分开存放。

已确认的默认设计：Agent 总预算为实际调用模型最大上下文的一半（按 token 向下取整，含输出预留）；Recent Window 容量为 200 个事件、每批移出 40 个；State 容量为 2000 个事件、每批管理 200 个，沿用最多保留 20 个的规则。精确定义见 Rule 技术稿 §3、State §7 与 Recent Window §5.1；这些参数尚待业务模块实现。

## 开发与发布分离

本仓库是唯一源码。npm 归档仅包含扩展运行代码、必要资源和用户说明；Git 安装会克隆仓库，但开发知识库和测试不得作为运行资源或模型上下文加载。两种渠道使用同一扩展入口，不维护第二份平行实现。

发布层只负责 Pi 扩展加载、Package 元数据、运行时资源定位和版本兼容检查；不得为发布便利改变已定稿的 Task、Rule、State、Recent Window 语义。

Rule 热读取、Window 预算和 State 注入统一使用 `context_with_system`；模板或预算错误主动取消请求。自动压缩由用户明确关闭，优先项目级设置，同配置范围内的普通 Pi 也会受影响；卸载扩展不自动恢复该设置。压缩恢复记录、宿主升级及第三方扩展组合的限制见 `docs/PACKAGING.md`。

## 当前进度

阶段 0 已完成：原生请求适配、主动取消、压缩边界、共享设置、reload/实例隔离和最小 Package 安装/加载有可复现测试。常规测试共 24 项；独立 DeepSeek 冒烟完成了 2 次真实请求和工具续跑，详情见 [阶段 0 验收记录](docs/PHASE_0_VALIDATION.md)。

当前生产入口检查目标 Pi 版本和有效 `compaction.enabled=false`，并取消手动 compaction；请求失败会先取消再报告。正式 Rule/config、Task、State 和 Recent Window 业务尚未实现，组装测试使用隔离夹具。启用开发入口前，用户须明确按 Pi 原生方式关闭有效自动压缩，优先受信任项目的 `.pi/settings.json`；扩展不会代写设置，卸载不自动恢复。具体范围见 `docs/PACKAGING.md`。

下一步为阶段 1 的正式配置与 Rule 模块，再继续 Task＋State、完整 State、原文回读、Recent Window 和恢复/发布验收。旧 SDK 应用实现保留在 Git 历史中。

## 骨架与开发命令

```text
src/
├── extension/index.ts       Pi Package 扩展入口与阶段 0 生命周期保护
├── config/                 配置与校验
├── rule/                   Rule 读取与渲染
├── task/                   Task 生命周期
├── state/                  Symbolic State
├── window/                 Recent Window
├── memory/                 引用与原文回读
├── pi/                     请求生命周期、兼容诊断与上下文半额上限
└── storage/                路径与存储基础能力
resources/rule.md           从独立模板生成，提交以支持 Git 安装
scripts/                    开发构建脚本
tests/
├── unit/                   纯逻辑与资源一致性
├── integration/            Pi 与 Package 集成
├── live/                   单独执行的真实 DeepSeek 冒烟
└── fixtures/               后续测试夹具
```

Node 最低版本与目标 Pi 一致，为 22.19.0；本机验证使用 `.node-version` 中的 24.22.0。开发依赖精确固定 Pi v1.3.0，生产使用宿主 peer。安装和验证命令：

```sh
npm ci --ignore-scripts
npm run build
npm run check
# 独立执行真实 DeepSeek API 验证
npm run test:live
```

`build` 生成默认 Rule 资源并做类型检查；Pi 直接加载 TypeScript，不生成第二套应用或捆绑宿主。`resources:check` 检查生成资源是否过期；`test:unit` 与 `test:integration` 可分别执行。常规测试使用替身与本机 HTTP，在系统临时目录中创建 Session、安装、打包和解包，成功/失败时均清理，不调用真实模型 API。`test:live` 使用仓库外既有 DeepSeek 私有配置，详情见验收记录。

当前版本为 `0.0.0`，`private: true` 用于防止开发骨架被误发布到 npm；正式包名、版本与发布验收在交付前确定。不要手改 `resources/rule.md`，应维护规范中的两份一致模板后执行 `npm run resources:sync`。密钥继续使用仓库外的私有配置。
