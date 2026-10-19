# MemWeave 开发版安装

当前版本只提供 SDK 宿主基础、帮助/版本与安装管理；交互界面和记忆业务仍在开发。尚未对外发布。此指南用于本地发布验收。

安装无需全局 Pi。此切片仅验收 macOS arm64；Node/npm 必须与产物 `release.json` 中的确切版本一致（当前构建环境 Node 24.22.0、npm 11.19.1）。Node/npm 需预先可用，安装器不下载或替换它们。依赖通过 npm 注册表按安装锁下载，需网络或 npm 缓存。

从可信来源获取产物并核对归档 SHA-256，解压后执行：

```sh
tar -xzf memweave-0.1.0-dev.0.tgz
node package/dist/install/cli.js install
~/.local/bin/memweave --version
```

默认应用文件放在 `~/.local/share/memweave/`，入口为 `~/.local/bin/memweave`；可将 `~/.local/bin` 加入自己的 PATH。安装器不自动修改 shell 配置。Node 路径记录在入口中；移动或更换 Node 后需重新安装。

更新时解压新的应用产物，用同一安装命令安装。也可使用已安装的入口：

```sh
memweave manage install --from /absolute/path/to/package
memweave manage status
memweave manage rollback
memweave manage uninstall
```

`rollback` 在两个最近成功激活的版本间切换；不同数据兼容声明会被拒绝，不自动降级用户数据。失败的安装保留当前激活版本。卸载撤去入口和激活记录，保留下载的版本文件；确认不再需要后可自行删除应用根目录。用户配置、凭据、Session、`~/.pi/memory/` 和 `rule.md` 不随安装、更新或卸载改写。

所有管理命令均可指定 `--root <应用根目录> --bin-dir <命令目录>`，适合临时验证。两项应在后续管理中保持一致。已有未由安装器管理的同名命令会导致安装失败。若进程被强制结束，检查没有管理操作运行后，方可手动删除应用根目录内的 `.operation-lock`；不要在并发安装期间删除锁。

开发者从仓库生成产物：`npm ci --ignore-scripts`，再执行 `npm run release:build -- --out <不存在的新目录>`。同一源码、锁文件与工具链应生成相同归档；内部规范、测试和凭据不会进入产物。普通 `npm install -g` 不能替代这里的锁定安装流程。
