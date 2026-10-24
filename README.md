# MemWeave

MemWeave 是运行在原生 [Pi](https://github.com/earendil-works/pi) 中的长程任务记忆扩展：保存任务目标、事实和决策，管理近期上下文，并按引用读取历史原文，帮助长任务持续推进。安装后继续使用 `pi`。

## 安装

当前测试版：`@godice/memweave@0.1.0`。**推荐通过 npm 安装。**

需要 **Node.js ≥ 22.19.0**，推荐 Node.js 24 LTS；已支持 **Pi 1.3.0 和 1.4.0**，推荐安装 1.4.0，其他 Pi 版本尚未验证。

### 1. 安装 Node.js

已有符合要求的 Node.js 可跳过。macOS、Linux 或 Windows WSL 可通过 [nvm](https://github.com/nvm-sh/nvm) 安装：

```sh
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.8/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm install 24
nvm use 24
node --version
npm --version
```

Windows 原生环境可使用 [Node.js 官方安装程序](https://nodejs.org/en/download)安装 24 LTS。

### 2. 安装 Pi

已有 Pi 1.3.0 或 1.4.0 可跳过；没有 Pi 或使用其他版本时，安装已支持的版本：

```sh
npm install -g --ignore-scripts @earendil-works/pi-coding-agent@1.4.0
pi --version
```

### 3. 安装 MemWeave 并启动

在你的业务项目目录运行，无需克隆或构建本仓库：

```sh
pi install npm:@godice/memweave@0.1.0
pi
```

也可用 `pi install npm:@godice/memweave@next` 跟随测试渠道。

首次启动时回车确认，扩展会创建或替换 `~/.pi/memory/rule.md`，全局关闭 Pi 自动压缩并重新加载。后续升级扩展会再次覆盖 Rule，自定义内容请先备份。

在 Pi 中配置模型与 API 密钥，然后用文字请求创建任务，例如：“为当前工作创建一个 Task，目标是完成……”。当前真实模型验收使用官方 DeepSeek Flash；完整配置、升级与卸载说明见[使用指南](USER_GUIDE.md)。
