# Pi 1.4.0 适配与首次 npm 发布验收

## 已确认范围

用户要求适配 Pi 1.4.0 并发布首版。2026-10-24 核验官方 npm `latest=1.4.0`、对应包的精确版本与 Node `>=22.19.0` 要求，以及官方 [v1.4.0 发布记录](https://github.com/earendil-works/pi/releases/tag/v1.4.0)。

原 npm 名称 `memweave` 已被其他维护者使用，包含已发布的 `0.1.0`；用户明确确认改为 `@godice/memweave`。首次版本 `0.1.0`，未要求稳定版，按发布规范使用 `next`。许可证由用户确认采用 MIT，版权署名 `godice`。

## 接口核查与实施边界

从官方 npm 下载 Pi 1.4.0，和现有 1.3.0 安装产物逐文件对比：扩展事件类型、runner、SettingsManager、SessionManager、消息转换、PackageManager、资源加载器、Bash/read 工具实现一致。loader 增加 pi-ai/models 子路径映射，本项目继续使用已可用的根导出，不因此切换实现。

AgentSession 的工具恢复与失败输出恢复有修复；SDK/ModelRuntime 调整了归属请求头与客户端 identity。MemWeave 不使用归属请求头 hook，继续以普通主会话和官方 DeepSeek 为验收范围。自动压缩仍由有效设置关闭；运行中重新开启时的原生 context_edit 仍按已确认边界处理，不删除记录。

保留 1.3.0，通过精确白名单加入 1.4.0；生产 peer 不捆绑宿主，开发依赖固定 1.4.0。只调整适配层版本检查、发布元数据、许可、必要测试及说明，不改变五份运行时契约、请求 hook、预算、数据格式或初始化副作用。

## 实际验收结果

环境为 macOS arm64、Node v24.22.0。以下均实际执行并观察结果：

| 检查 | 结果 |
|---|---|
| 测试先行 | 原版本拒绝 1.4.0、归档缺少 LICENSE 两项断言实际失败；补齐后通过 |
| Pi 1.3.0 `npm run check` 与 `npm run build` | 类型/模板检查、190 项单元与原生集成测试通过，0 失败/跳过；构建通过 |
| Pi 1.3.0 scoped 临时 registry 升级 | 1 项通过；旧版与 0.1.0 安装、Rule 更新、数据恢复与卸载，7 次本机 HTTP 请求 |
| Pi 1.4.0 `npm run check` 与 `npm run build` | 类型/模板检查、190 项单元与原生集成测试通过，0 失败/跳过；构建通过 |
| Pi 1.4.0 scoped 临时 registry 跨宿主升级 | 1 项通过；旧产物在真实 1.3.0 创建记录，0.1.0 在 1.4.0 恢复；7 次本机 HTTP 请求，原始消息前缀、State、配置、认证与卸载保留通过 |
| Pi 1.4.0 本地 npm 归档与 Git SSH | 本地归档安装/禁用/卸载 1 项通过；远程 Git 固定 `25d818c0772ce3a904a3c6bd6102a2c2ca6c055d` 安装、恢复与移除 1 项通过，后者使用 7 次本机 HTTP 请求；均未捆绑宿主 peer |
| Pi 1.4.0 真实终端 | 离线、无模型，真实 PTY 回车接受原生确认，自动 reload；默认 Rule 逐字一致，全局 enabled=false、reserveTokens=512 保留、v2 标记记录 0.1.0；正常退出。仅显式包装入口传入临时 memory/profile 路径，不改 HOME 或真实用户文件 |
| Pi 1.4.0 真实 DeepSeek | `tests/live/release.test.ts` 1 项通过；npm 归档解包后，独立进程恢复 Task、memory_read 读取 U1、state_append 提交，3 次真实推理；引导使用 3 次本机 HTTP，私有认证文件字节保持不变 |

第一次 1.4.0 常规检查中，历史恢复测试误把只支持 1.3.0 的旧产物加载到 1.4.0，出现明确版本错误；没有放宽旧产物的检查，而是让测试按旧产物的精确开发宿主启动独立 1.3.0 环境，再由当前 1.4.0 恢复。历史宿主依赖安装、测试源码与 Session 均在临时目录；首次安装耗时较长，因此扩大该恢复测试的时限。修正后整组通过，不将第一次失败隐去。

实际源码调整仅为宿主精确白名单和适用版本注释。新版本的原生并发对话框、工具恢复等修复可直接受益，不额外实现一套 UI 或恢复机制；本次未采用会改变核心布局或副作用的可选机制。

真实 CLI 独立重启也已验证：在隔离 Rule 写入编辑标记后退出，再用另一个 Pi 1.4.0 进程启动；未再次弹出初始化，编辑标记保留。两个终端正常退出，未配置或调用模型。

## 公网发布与安装

发布源提交为 `25d818c0772ce3a904a3c6bd6102a2c2ca6c055d`，最终归档共 59 文件，压缩 1,944,259 字节，展开 6,627,624 字节；只包含运行源码、默认配置/Rule/tokenizer、许可、README、USER_GUIDE 与 package.json，不含 AGENTS、开发规范、测试、脚本、凭据或用户数据。

归档 integrity：`sha512-9Yys8Z4yCTc/sKL/dD0xTXNfQFZF5Ee5rGlApU1IH4jd6I0c9edAQNcqAaLuZvIxPlP9u02eafbe1TPOkEELBA==`。

使用当前 npm 账号 `godice` 发布该已核验归档，显式 `--tag next --access public --registry=https://registry.npmjs.org/ --ignore-scripts`，用户完成 npm 要求的通行密钥二次验证后，命令退出码 0，返回 `+ @godice/memweave@0.1.0`。npm 同时提示包正在处理，最初 registry 查询为 404；约几分钟后已可公开读取。没有重复上传或递增版本重发。

公网核验结果：

- registry 返回版本 `0.1.0`、MIT 许可及与上述归档完全一致的 sha512 integrity。
- `next=0.1.0`；首发还额外生成 `latest=0.1.0`。通过 npm 标准 `dist-tag rm` 尝试移除 latest 时，服务器返回 HTTP 400，未删除成功。用户明确接受本次标签例外，保持两个既存指向，但本项目仍将 0.1.0 定义为测试版；后续测试发布不移动 latest，规范已同步。
- 使用实际 Pi 1.4.0 CLI，在全新的临时业务目录与 Pi 配置目录运行 `pi install npm:@godice/memweave@0.1.0`，从 npmjs.org 下载成功；原生 `pi list` 列出对应来源。
- 从实际公网安装目录由原生加载器加载一个扩展，未加载 Package 内开发上下文；原生 Session 独立进程创建并恢复 Task、读取 U1、提交 State 与 Window，最终 State version=3、窗口参数=4。共 7 次本机 HTTP 模型替身请求，未新增真实模型推理。
- 公网安装包不含 AGENTS/docs/tests/scripts 或宿主 peer 副本，实际 LICENSE、包名、版本与元数据检查通过。

公开包为 [@godice/memweave@0.1.0](https://www.npmjs.com/package/@godice/memweave/v/0.1.0)。适配、构建、归档与已推送源码检查点均已完成；该包为测试版，不将 `latest` 的首发附带标签当作稳定性承诺。
