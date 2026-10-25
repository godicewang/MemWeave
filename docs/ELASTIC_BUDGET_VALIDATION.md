# 弹性预算实现与验收（2026-10-25）

候选代码：`c8855d3b390331ce629cd00b2590512519f9c4af`，功能提交 `fbaa66d`，请求准备优化 `c8855d3`。Package 仍为 `@godice/memweave@0.1.0`，本轮未修改版本、未发布 npm/GitHub Packages。遵循 [已确认设计](ELASTIC_BUDGET_DESIGN.md)，先更新直接规范和固定 Rule，再编写边界测试、实现与验收。

## 实现与边界

- `src/config/defaults.json` 新增 elastic_budget；旧部分配置和六字段 scope 继续兼容，严格校验比例、上限及嵌套字段。
- `src/window/budget.ts` 先计算实际必需成本，余量按回读/普通 Window/池内安全 40/40/20 分池；回读不借 Window，各层安全与输出不借出。State 准入、N/B、O/A 仍按基础预算计算。
- 普通正文按当前工具轮/近 3 事件/其余事件的 50/35/15 按需回收。到期已核验回读合计最多占普通池 10%，不会因处于最近工具事件而绕过。
- `src/window/read-budget.ts` 保留合法 JSON、引用键和真实范围/完整性；正文与证据按额度缩短，图片只整体保留/省略；token 截断另附 tag。元数据本身不可容纳时返回原生工具错误。
- Pi 适配层核对原生 assistant/call/input；新旧回读共享读池，旧内容允许缩短以支持 offset 续读。并行调用预留份额，同一调用重试不重复扣费，Session/模型切换不沿用另一帧。
- 回读期限仍按后续真实消息计数。已有消息的截断仅发生在请求展示；首次工具返回按限额生成新的原生结果，不改写旧消息。原始正文仍由 Pi Session 或既定原件保存。没有新工具参数、State 类型、持久化字段/文件或全量聊天副本。
- 回读截断与 offset 说明固定写入 Rule 的回读段落，不在截断发生时临时加入。技术稿 §4、独立 Rule 和发布资源逐字一致（允许末尾换行）。历史 state_read 没有 offset，提示使用较少 event_ids/字符预算。
- 官方 tokenizer 可从 token ID 解码前缀候选，关闭空格清理，并复核原文前缀和带头/tag 的最终 token 数；无法使用时回退 Unicode 搜索。最终 Window 只渲染一次，请求内复用，预算观察数据不持有消息副本。

## 实际执行

环境：macOS arm64，Apple M4 Pro，48 GiB，Node v24.22.0。Pi 1.4.0 使用项目依赖；Pi 1.3.0 使用系统临时目录中的同候选隔离 checkout 与本机固定宿主依赖，没有改写 SDK 或用户配置。

| 命令/范围 | 观察结果 |
|---|---|
| `memweave-dev npm run test:release -- --full`，Pi 1.4.0，干净候选 | 资源/类型/216 项单元与原生集成、构建、5 项入口/归档、3 项 npm/Git 分发、1 项真实产物用例全部通过，无 skip |
| `memweave-dev npm run test:release`，隔离 Pi 1.3.0，同候选 | 资源/类型/216 项常规测试、构建及 5 项入口/归档全部通过，无 skip；未把它描述为完整发布门槛 |
| `memweave-dev node --test tests/live/elastic-budget.test.ts`，Pi 1.4.0 | 2 次真实 DeepSeek 请求，4 次 Faux 准备另计；人为缩小可配置读池至 0.5% 验证截断、合法 JSON/offset、固定 Rule 和实际输出上限到达提供方 |
| `memweave-dev node --test --test-name-pattern='blind cross-Task' tests/live/vision.test.ts`，Pi 1.4.0 | 3 次真实请求，5 次 Faux 准备另计；出站图片数 [0,0,1]，原生图片 hash/字节保留，随机 OCR 与形状颜色正确 |
| 完整入口中的产物真实 DeepSeek 恢复 | 3 次真实请求，本机 HTTP 准备另计；解包产物、独立进程恢复、已知来源回读和 State 追加通过 |

以上定版供应商证据共 8 次真实推理；开发过程中另有针对中间候选的探测，不混充定版证据。所有真实测试使用仓库外私有认证，测试前后核验 auth.json 字节不变；报告不保存密钥、完整真实请求或 Session。

双宿主对同候选各重复打包并核验白名单，均为 61 个文件，integrity 完全一致：

```text
sha512-wpMO7i8BHvuW9RfPVKIU7DFRw0FgiQn6GjOpDoUYGJrtvvjDlNankCuS2vRUKZ/T9pfjwK4yZWEVYuHeForg8Q==
```

Git 分发固定当前候选 SHA；临时 registry 的安装/升级/恢复/禁用/卸载不等于 npm 公网发布。未上传新版或移动任何发布标签。

## 回归修正与性能

旧回归中的 60% 请求总限额、统一 Q、旧快照文字期望按新契约改验基础/额外/总上限。最小引用/tag 及必要成本仍不允许透支；80% 之外的取消用例实际观察 provider/HTTP 新增数为零。工具描述现在固定包含 tag 拼写，因此原始 Session 的不改写检查针对真实非 system 消息，而不误报原生 system 持久化的工具说明。

并行回读与后续 offset 先暴露了“旧内容占满读池会阻止续读”的问题，已修为新旧回读在同池内公平预留；对应原生测试验证两个并行部分返回、旧结果仍存活时继续 offset 读取、调用重试和范围字段。没有通过借用 Window 或安全预留绕过问题。

性能使用 [固定样本脚本](../发布测试/性能/elastic-budget.mjs)，无真实 API：401 个文本消息、手工事件分组、1,525,068 UTF-8 bytes、预热后各 5 次交替测量。这里只测预算分配与渲染，不包括完整 Session 索引、I/O、Pi Loop 或 API 延迟；新旧策略展示量不同，不能当作等输出性能或长期执行质量比较。

| 计量方式 | 旧统一配额中位数 | 新分池初版中位数 | 优化后中位数（最大值） |
|---|---:|---:|---:|
| UTF-8 保守计数 | 56.7 ms | 53.8 ms | 27.6 ms（29.4 ms） |
| 官方 DeepSeek tokenizer | 729.3 ms | 6236.1 ms | 922.4 ms（930.1 ms） |

初版性能退化来自重复渲染和截断时反复编码；修正后真实计数边界与源前缀复核保留。新分池相对旧方案在该官方 tokenizer 样本中仍约慢 26%，其中包括更严格普通池造成的额外截断；不宣称全部场景更快或固定缓存命中。正文/token ID 不持久缓存。

## 本机同步、清理与未验证项

本机 `~/.pi/memory/rule.md` 与旧默认模板逐字相同，已备份后同步新默认 Rule；备份保留于 `~/.local/share/memweave-dev/rule-backups/rule-before-elastic-20261025-160659.md`。未改变同版本自定义 Rule 的自动保留规则。日常本地源码 Package 重启 Pi 后选择启用即可使用；npm 已发布的旧归档不会自动获得本轮源码变化。

临时宿主 checkout、性能旧代码、Package、Session、State 和失败夹具在验收完成后清理；有意保留本机 Rule 备份。源码/规范/回归提交保留于 Git。

尚未执行数小时长任务成功率对照或不同模型的质量 benchmark；预算安全余量不等于模型能力保证。未扩展 Pi 1.3.0/1.4.0 以外宿主、任意第三方组合或其他模型图片费用的兼容承诺。此次未改启动选择/设置副作用或重做真实 TUI 专项，其原生自动回归仍通过。
