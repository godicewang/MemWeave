# MemWeave

MemWeave 是运行在原生 [Pi](https://github.com/earendil-works/pi) 中的长程任务记忆扩展：保存任务目标、事实和决策，管理近期上下文，并按引用读取历史原文，帮助长任务持续推进。安装后继续使用 `pi`。

## 安装

当前稳定版：`@godice/memweave@0.1.1`，渠道为 `latest`。**推荐通过 npm 安装。**

需要 **Node.js ≥ 22.19.0**；已支持 **Pi 1.3.0 和 1.4.0**，推荐安装 1.4.0，其他 Pi 版本尚未验证。

### 1. 安装 Node.js

已有符合要求的 Node.js 可跳过。macOS 推荐通过 [Homebrew](https://brew.sh/) 安装；已有 Homebrew 时运行：

```sh
brew install node
node --version
```

尚未安装 Homebrew，可按其官网指引安装。其他系统可参考 [Node.js 官方安装说明](https://nodejs.org/en/download)。

### 2. 安装 Pi

已有 Pi 1.3.0 或 1.4.0 可跳过；没有 Pi 或使用其他版本时，安装已支持的版本：

```sh
npm install -g --ignore-scripts @earendil-works/pi-coding-agent@1.4.0
pi --version
```

### 3. 安装 MemWeave 并启动

在你的业务项目目录运行，无需克隆或构建本仓库：

```sh
pi install npm:@godice/memweave@latest
pi
```

固定本版可用 `pi install npm:@godice/memweave@0.1.1`。`next` 是独立测试渠道，本次稳定版发布不移动它的标签。

每次交互启动先选择启用或未启用 MemWeave。首次启用时回车确认，扩展会创建或替换 `~/.pi/memory/rule.md`，全局关闭 Pi 自动压缩并重新加载。后续升级扩展会再次覆盖 Rule，自定义内容请先备份。

选择“MemWeave 未启用”会恢复全局自动压缩，底部显示当前模式。两种模式共用 Pi 配置与 Session。本地开发使用 `pi install /absolute/path/to/MemWeave`，确认 `pi list` 只有一个 MemWeave 来源。

在 Pi 中配置模型与 API 密钥，然后用文字请求创建任务，例如：“为当前工作创建一个 Task，目标是完成……”。当前真实模型验收使用官方 DeepSeek Flash；完整配置、升级与卸载说明见[使用指南](USER_GUIDE.md)。

本版还支持显式 `/memweave-restart`：从近期现场准备新 Task、保留旧记忆，等待下一条输入后生成新 Goal；并增加阶段交付时的业务/认知检查。上下文按弹性预算分池，底栏显示上次实际 API 用量，State 读写使用有界缓存。详见[使用指南](USER_GUIDE.md)。
