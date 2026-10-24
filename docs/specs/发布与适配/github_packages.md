# GitHub Packages 首发

## 已确认的范围

2026-10-24 用户要求发布首个 GitHub Package，并确认因 GitHub 命名空间要求使用 `@godicewang/memweave@0.1.0`；npm 继续使用 `@godice/memweave@0.1.0`，用户安装推荐 npm。两处均为同一运行实现的测试版，不创建第二份源码，不改变核心设计或数据格式。

此次是已发布 npm 版本的跨 registry 镜像，不递增 npm 版本、不重发 npm，也不调整 npm 的 `latest`/`next`。后续发布仍须用户明确要求；普通提交与 push 不构成发布授权。

## 产物与执行

- 源产物为 npmjs.org 已发布的 `@godice/memweave@0.1.0`，固定校验值：`sha512-9Yys8Z4yCTc/sKL/dD0xTXNfQFZF5Ee5rGlApU1IH4jd6I0c9edAQNcqAaLuZvIxPlP9u02eafbe1TPOkEELBA==`。
- 验证原归档完整性后，仅修改归档 `package.json` 中的包名与 `publishConfig.registry`，其余字段和文件逐字节保留；源仓库的主包名、registry 和版本保持 npm 配置。
- 不运行归档的生命周期脚本，不增加宿主 peer 副本、开发文档、凭据或运行时数据。归档内 README 保留 npm 首发时的内容；GitHub 仓库主页独立使用当前简版 README。
- 使用仓库内 GitHub Actions 的短期 `GITHUB_TOKEN`，仅赋予 `contents: read` 与 `packages: write`，不创建个人访问令牌或改写本机 npm 凭据。
- 首发工作流只响应精确 Git tag `github-packages/v0.1.0` 或手动运行；常规分支提交不触发发布。工作流仅能发布固定的 0.1.0 镜像，不能据此自动发布未来版本。
- 明确使用 GitHub registry `https://npm.pkg.github.com` 和测试标签 `next`；不将 registry 自动附带的 `latest` 视为稳定版声明，不扩大 npm 首发例外的适用范围。
- 已存在同版本时先核验实际结果，不覆盖、删除或递增版本重试。

## 验收与可见性

发布前检查变更范围、文件白名单、许可、归档 integrity 与原始文件一致性。发布后从 GitHub registry 回读并校验版本、标签、下载归档和与候选归档一致的 integrity，确认关联到 `godicewang/MemWeave`。

检查实际可见性；GitHub Packages 的默认可见性与 npm 不同，不以 `--access public` 或公开仓库推断包已公开。公开时只公开已有 npm 公共产物，并核验 Package 页面。GitHub npm registry 的安装认证要求按官方机制处理，不能承诺匿名安装；普通用户继续推荐 npmjs.org 安装。

依据：[GitHub npm registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-npm-registry)、[Package 权限与可见性](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)。
