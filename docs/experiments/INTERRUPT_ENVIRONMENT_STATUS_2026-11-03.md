# Interrupt网站资产的实际阻塞

2026-11-03续接中，官方WebArena文档仍指向公开Google Drive、Internet Archive和CMU镜像。先前部分HTML为公开下载的病毒扫描提示，不是登录页；不应将它误报为账号阻塞。采用页面声明的匿名表单，没有cookie、账号、付费资源或安全设置变化。

实际小Range探针确认admin原件总长9,640,032,256字节；已有5,487,760,917字节部分文件的尾64KiB与公开206响应完全一致。shopping原件总长67,575,898,112字节（约62.94GiB），超过既有32GiB下载容量上限；这是体积／资源问题，不能当作下载鉴权失败。不得用admin镜像代替shopping。

admin恢复控制的下一64MiB请求未得到匹配Range，程序在创建新分片之前退出：新增分片0，旧文件未改动，控制进程已终态，临时caffeinate释放。后续精确复现该请求，仅读取2,040字节诊断页，确认Google Drive明确返回“Quota exceeded／Too many users”。至此停止下载，不通过换token、账号、User-Agent或路由规避配额；后续小探针返回缓存206也不能推翻这次配额拒绝。Internet Archive元数据为`is_dark=true`，没有尝试绕过；既有CMU请求为空响应。

原件保留在`~/.local/share/memweave-experiments/fixed35-20261102/webarena-archives/shopping_admin_final_0719.partial`，hash为`8b1fac5fad1580f9a19ef5165b4727b9d247b37cf6d1d069fc7ec50e6b1c90a3`。本次终态回执在`fixed35-20261103/webarena-admin-recovery-v2/`，准确Range诊断在`/tmp/memweave-35-20261103/admin-exact-range-classification.json`。诊断不包含真实模型凭据或浏览器认证。

因此INT-08/09/10仍不能启动完整网站配对；已实现的源DOM／URL及60%前缀组件仅为部分实现。真实浏览器兼容、baseline回放及业务中断机会尚未验证，INT-10的活动评分过滤器仍缺校准。不能把公开资产阻塞隐去，也不能把剩余gold／时序实现缺口都归咎于资产。正式成绩仍不存在，不以程序fixture代替。

本次恢复和诊断真实模型费用0，真实账本hash未变。禁止重试的辅助JSON请求、旧宿主进程查询和Library上传均未重试。
