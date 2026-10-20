# MemWeave — Pi Long Task Agent

本仓库用于构建运行在原生 Pi 内的长程任务记忆扩展，以 Pi Package 经 npm 或 Git 分发。用户继续使用 `pi`，复用原生循环、界面与 Session。首个兼容验收目标为 Pi v1.3.0，宿主版本由用户安装决定。

## 开始前

1. 阅读 `AGENTS.md`。
2. 阅读 `docs/INDEX.md` 和当前任务对应的 `docs/specs/`。
3. 先执行 `docs/IMPLEMENTATION_PLAN.md` 的阶段 0，确认 Pi 的真实扩展/API 接入方式。
4. 不要在阶段 0 前生成整套业务实现。

## 文档

- `docs/ARCHITECTURE.md`：代码与运行时文件的职责边界。
- `docs/PACKAGING.md`：分发方式、宿主依赖、已接受的副作用与兼容边界。
- `docs/IMPLEMENTATION_PLAN.md`：分阶段 Vibe Coding 计划。
- `docs/specs/`：五份已定稿行为规范，设计调整须先讨论确认。

源代码仓库、Pi Session 和 `~/.pi/memory/` 运行时数据必须分开存放。

已确认的默认设计：Agent 总预算为实际调用模型最大上下文的一半（按 token 向下取整，含输出预留）；Recent Window 容量为 200 个事件、每批移出 40 个；State 容量为 2000 个事件、每批管理 200 个，沿用最多保留 20 个的规则。精确定义见 Rule 技术稿 §3、State §7 与 Recent Window §5.1；当前仅完成文档设计。

## 开发与发布分离

本仓库是唯一源码。npm 归档仅包含扩展运行代码、必要资源和用户说明；Git 安装会克隆仓库，但开发知识库和测试不得作为运行资源或模型上下文加载。两种渠道使用同一扩展入口，不维护第二份平行实现。

发布层只负责 Pi 扩展加载、Package 元数据、运行时资源定位和版本兼容检查；不得为发布便利改变已定稿的 Task、Rule、State、Recent Window 语义。

Rule 热读取、Window 预算和 State 注入统一使用 `context_with_system`；模板或预算错误主动取消请求。自动压缩由用户明确关闭，优先项目级设置，同配置范围内的普通 Pi 也会受影响；卸载扩展不自动恢复该设置。压缩恢复记录、宿主升级及第三方扩展组合的限制见 `docs/PACKAGING.md`。

## 当前进度

当前仓库处于文档阶段，旧 SDK 应用实现已回退。既有临时验证支持接入方案的部分可行性，不代表可安装的完整产品或全部兼容验收已完成。开发顺序为：接入验证 → 配置/Rule → Task＋State 最小闭环 → 完整 State → 原文回读 → Recent Window → 恢复与发布验收。不再开发独立安装器或自建 TUI；下一步按实施计划阶段 0 建立最小原生扩展和可复现测试。
