# 实验系统验收记录

日期：2026-10-27。当前仍在实施验收，以下只记录已观察到的结果。

- Python 3.12.14、uv 0.13.5，锁定 Harbor 0.24.0；独立安装在 `experiments/.venv`。
- 21 项实验单元/替身及实际 Harbor 配置模型检查通过，Ruff 检查通过。这些不是真实 benchmark 或模型通过证明。
- 产品 Rule 资源一致性检查和 TypeScript 类型检查通过；未修改产品源码或定稿规范。
- 独立 Colima 0.10.3 / Lima 2.2.1，Docker daemon 29.5.2，8 CPU、16 GiB RAM、120 GiB disk。
- 已实际执行 Alpine 3.23.4 的 linux/amd64 与 linux/arm64 容器，分别返回 `x86_64` 与 `aarch64`。模型端点匿名请求返回 401，证明连接可达，不涉及推理。
- 虚拟机基础镜像中的 `/etc/resolv.conf` 曾指向不存在的 systemd-resolved 文件；只在该专用虚拟机内修复 DNS，未改任务网络协议。
- 官方任务 oracle/nop、Pro 离线阶段、完整 Pi/冻结包与真实模型 smoke 尚未通过；待实际验证后更新。

正式源码包来自提交 `f3931ce3b4d5d7b504e612e67cd46e4267f309a5` 的干净临时 checkout。归档 SHA256 为 `4d089821e9590380c8377afa8a44f3883b3a35b9f0696c0e99c2369ff2ab7c04`，77 个文件，未发布 npm。归档位于仓库外。

本轮所有模型 smoke 合计授权 20 美元、8 小时。当前未发起推理；模型元数据 GET 不作为解题调用。
