# 验证记录 / Validation

日期 / Date: 2026-10-19

- Python 自动化测试 36 项通过 / 36 Python tests passed.
- Bash 安装／升级流程在独立临时目录中测试，systemd 与账号操作使用模拟实现 / Shell tests use isolated directories and mocked systemd/account operations.
- 已测试：全新安装、升级保留配置／历史、初始化失败回滚、默认卸载保留数据、拒绝无人值守 purge、精确确认后清理 / Fresh install, retained-config upgrade, failed-upgrade rollback, data-preserving uninstall, unattended purge rejection and exact purge confirmation.
- 已测试：拒绝公网 origin、端口冲突、已有 Funnel、改动过的非本项目转发；仅移除本项目拥有且完全匹配的路由 / Tailnet route ownership and conflict guards.
- 密钥使用隐藏输入，配置以独占新文件方式写入；仓库不含真实凭据、数据库、私钥或服务器专用配置 / Hidden secret prompts and exclusive restricted config creation; no production credentials or data in the repository.
- 未在生产监控上重新执行安装器；未重启 3x-ui / Xray / No production reinstall or panel/Xray restart.

真实部署前仍需目标系统满足 README 前提，浏览器通知需设备授权及实收测试。
Actual deployment still requires the documented prerequisites and device-level notification acceptance.

- Linux 侧仅对现有配置运行只读 preflight，并在独立目录运行模拟安装测试；真实固定版本依赖已在临时 venv 中安装并验证迁移目录后可导入 / Linux read-only preflight, isolated shell tests and actual pinned dependency installation/import after venv relocation passed.
