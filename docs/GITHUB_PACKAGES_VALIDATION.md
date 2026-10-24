# GitHub Packages 首发验收

日期：2026-10-24。用户要求发布首个 GitHub Package，并确认采用 `@godicewang/memweave@0.1.0`；npm 包名保持 `@godice/memweave`，不发布 npm 新版本。两者均按测试版维护。

## 主页

README 已由开发过程说明精简为 49 行：项目用途、支持的 Node/Pi 版本、Node 与 Pi 安装命令、推荐 npm 安装、首次初始化及 Rule 升级覆盖提示，详细说明链接到 USER_GUIDE。

- Node.js 最低 22.19.0，推荐 24 LTS；Pi 支持 1.3.0 和 1.4.0，命令固定安装 1.4.0。
- Node 安装示例来自 nvm 官方 v0.40.8；Windows 原生环境提供 Node 官方下载页。
- 三组命令均通过 bash/zsh 语法检查；公开 registry 实际回读 Pi 1.4.0 的 engines 与 MemWeave 0.1.0 及 next 标签。
- GitHub REST API 匿名读取的 README 正文与本地已提交文件逐字节一致。

本次未在用户机器上重新安装 Node/Pi，也未修改用户模型、压缩或记忆配置。

## 候选包

发布准备代码为 `scripts/prepare-github-package.mjs`。从 npmjs.org 下载已发布版本，核验固定源 integrity，仅修改产物 package.json 的包名与 publishConfig.registry。仓库的 package.json、package-lock.json、运行源码与资源均未修改。

本地实际准备成功：59 文件，除 package.json 外的 58 文件逐字节不变；重打包后解包复核通过，MIT 许可、关联仓库、资源白名单和元数据检查通过。

- npm 原归档：`sha512-9Yys8Z4yCTc/sKL/dD0xTXNfQFZF5Ee5rGlApU1IH4jd6I0c9edAQNcqAaLuZvIxPlP9u02eafbe1TPOkEELBA==`
- 本地 GitHub 候选：`sha512-tMm/pNXNiQhc54JY1DDzRhrftjl7mkZyzaDpxGWhDXV0kmFgjrBzgO8l1oMMuouaA938DiGtw4juIDTY3bDF9w==`

## 实际发布

发布源码检查点 `349cb42fb4a15344de8e116c7a14e3b364f1e9b3`；推送用户授权的专用 tag `github-packages/v0.1.0`，触发 [GitHub Actions run 40087449190](https://github.com/godicewang/MemWeave/actions/runs/40087449190)。REST API 和公开网页均显示 Success，工作流总时长 19 秒，发布 job 15 秒。

准备与发布步骤全部成功，工作流实际执行并断言：

1. 从固定 npm 原归档重建并核验同一候选文件集合与内容。
2. 目标为 `https://npm.pkg.github.com`、`@godicewang/memweave@0.1.0`、`next`；已存在时核验，不覆盖或递增版本。
3. 发布后回读版本、next 指向及候选 integrity；实际下载 GitHub registry 归档并计算 sha512，与该次候选一致。
4. GitHub Package API 可回读元数据，关联仓库为 `godicewang/MemWeave`。

最后使用无登录的网页读取确认 [Package 页面](https://github.com/godicewang/MemWeave/pkgs/npm/memweave)公开可见，显示 0.1.0、`@godicewang/memweave`、MIT 与对应仓库；并非只凭发布命令或 access 参数推断公开状态。页面的 Latest 展示不作为本项目稳定版声明。

工作流只授权 contents:read/packages:write；使用短期 GITHUB_TOKEN，不创建 PAT、不改本机 npm 认证。正常分支 push 不触发；固定首发 tag 或手动运行只能尝试这一个版本，未来发布仍须用户明确要求。本次未调用真实模型 API，未重跑无运行代码变更的业务测试，也未将归档一致性检查表述为新的模型验收。

本机直接 GitHub HTTPS/Git 网络访问失败，官方 Action ref 改由 GitHub REST API 核验；SSH push 与 REST API 可用，未修改全局网络设置。匿名下载 Actions 日志返回 403，最终执行结果依据公开 job 各步骤状态与工作流中的明确断言，并以公开 Package 页面交叉确认。GitHub npm registry 安装仍有 GitHub 认证要求，用户入口继续推荐 npmjs.org，无需 GitHub token。
