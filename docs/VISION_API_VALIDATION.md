# DeepSeek 真实视觉 API 验收

日期：2026-10-21。使用项目既有私有 DeepSeek API 配置、Pi v1.3.0、Node v24.22.0。两项真实 PNG 视觉测试通过；没有修改生产代码、模型配置、Pi 源码或定稿规范。

## 模型核实

[DeepSeek 官方入口说明](https://api-docs.deepseek.com/zh-cn/)写明：调用标识仍为 `deepseek-flash`，当前由 DeepSeek-V4.1-Flash-1017 提供服务。[图像理解文档](https://api-docs.deepseek.com/zh-cn/guides/vision/)说明该模型支持图片输入，Chat Completions 使用 image_url 内容块。

用现有凭据实际查询 `/models`，HTTP 200，deepseek-flash 返回 `input_modalities=["text","image"]`、`context_window=1048576`。本机 Pi v1.3.0 同一模型也声明 `input=["text","image"]`，无需覆盖其模型能力或更换模型名。静态 contextWindow 仍为 1000000，生产容量适配继续使用经核验的 1048576 派生 524288；本次不改预算设计。[模型元数据定义](https://api-docs.deepseek.com/zh-cn/api/list-models/)

## 实际测试与证据

```sh
memweave-dev node --test tests/live/vision.test.ts
memweave-dev npm run check
```

| 路径 | 实际结果 |
|---|---|
| 直接用户图片输入 | 1 次真实推理；正确识别随机八位数字、左侧红圆、中间蓝色正方形和右侧绿色三角形 |
| 跨 Task R 附件回读 | 3 次真实推理；先读已知来源 U1 获取附件 R，再显式回读附件，最后正确识别另一个随机编号及形状/颜色 |
| 实际发送图片数量 | R 回读三次请求依次为 `[0,0,1]`；消费 Session 之前从未见过来源图片 |
| 防止文字泄漏 | 随机编号只存在于图片像素中，不在提示、文件名、PNG 文本元数据或实际请求正文里；逐请求检查正文没有答案 |
| 图片与协议 | 回读 image data 与来源 Session 保存的图片一致；出站 data URL 的 SHA-256 与工具返回图片一致，原生工具调用/结果仍配对 |
| 供应商图片角色 | Pi 的 OpenAI 兼容适配器将工具图片投影为 user 内容块；出站检查只在 user 角色出现 image_url，未给供应商的 tool 消息塞图片 |
| 常规回归 | 98 项常规测试与类型/Rule 资源一致性通过；该组不调用真实模型 |

最终正式视觉用例共 **2 项通过、4 次真实 DeepSeek 推理**。跨 Task 用例另有 4 次 Faux 调用用于建立来源与消费 Task，不计为真实视觉推理。临时验证阶段也调用了真实 API，其结果与正式用例分别记录，不把 Faux 冒充真实模型。

测试入口为 `tests/live/vision.test.ts`，程序生成图片的夹具为 `tests/fixtures/vision-image.ts`。正式测试代码留在开发仓库，不进入 npm 运行包；图片、Session、配置与认证缓存仍只在隔离的系统临时目录，结束时清理。

## 观察到的失败与限制

首次临时测试使用七段数码管字形：直接看图通过，跨 Task 回读的回答将八位数字 `74071683` 识别为 `7407683`，少了一位。该次严格比对失败，临时文件已删除，不能计为通过。随后换用包含清晰字距和基线的 5×7 字模，临时复测及正式两项测试均通过。没有更换模型、传输接口或降低“八位完全一致”的验收条件。

这说明真实视觉链路可用，但不能保证 OCR 永远正确；本次不是 OCR 准确率评测。正式 R 用例同时验证无文字答案、图片只在显式读取后发送、原件/工具/出站哈希一致，再独立检查模型识别结果。

本次只实测程序生成的 900×480 RGB PNG、数字 OCR 和简单形状/颜色识别。JPEG/GIF/WebP、照片、复杂截图、中文 OCR、超限图片、Files API、外链图片和其他供应商未由本次真实调用覆盖。不能用两项通过承诺这些场景的准确性或兼容性。

Recent Window 的正式裁剪与完整 Q/X 预算仍留在阶段 5；本次证明供应商视觉输入和 MemWeave 附件回读链路，不扩大阶段 4 的预算完成声明。

## 密钥与清理

复用仓库外 `~/.local/share/memweave-dev/pi-agent/auth.json`，每项正式测试结束后核对文件字节未改动。请求观察只保留模型名、图片数量/角色/哈希及正文泄漏检查结果，不记录认证头、密钥或完整图片载荷。临时试验代码及失败/成功 Session 均已清理；密钥不进入测试源码、报告或 Git。
