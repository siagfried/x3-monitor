# X3 Monitor

**仅支持 BandwagonHost（搬瓦工），必须预先安装并运行 3x-ui。**

**BandwagonHost only. A working 3x-ui installation is required before installation.**

X3 Monitor 是独立部署的客户端流量活跃监控：60 秒采样、Python venv、systemd、SQLite，仅通过 Tailnet HTTPS 访问。它不会安装、修改或重启 3x-ui / Xray，也不会修改订阅配置、公共订阅端口或防火墙。

An isolated client activity dashboard with 60-second sampling, Python venv, systemd and SQLite. The Web UI is available only over Tailnet HTTPS. The installer does not install, modify or restart 3x-ui / Xray and does not change subscriptions, public subscription ports or firewall rules.

## 安装前 / Prerequisites

- BandwagonHost VPS，已有可登录的 3x-ui 与可用 API。需要面板完整地址（含端口、路径）、用户名及密码，或已有 API Token。不要填订阅地址。启用两步验证时，建议使用可用的 API Token。
- Debian / Ubuntu 等 Linux，正在运行的 systemd，root / sudo，Python 3.10+ 和 `python3-venv`、可信 CA 证书。
- 本机已安装并登录 Tailscale，已启用 MagicDNS 与 Tailnet HTTPS。安装向导不代为登录 Tailscale、不修改 ACL、不启用 Funnel。
- 能访问 PyPI 和 KiwiVM API。推送依赖仅安装到独立 venv。

Requirements: a BandwagonHost VPS with a working 3x-ui API; Linux with systemd, root/sudo, Python 3.10+, `python3-venv` and trusted CA certificates; Tailscale already installed and signed in, with MagicDNS and Tailnet HTTPS available; outbound access to PyPI and the KiwiVM API. Provide the panel URL with its base path and credentials or API token, **not** the subscription URL. Prefer an API token when panel 2FA is enabled.

缺少 Python 组件时，可先运行（Debian / Ubuntu）：

```bash
sudo apt-get install python3 python3-venv ca-certificates
```

## 一键安装 / Install

本仓库为私人仓库。先在目标机器使用你自己的 GitHub 账号授权 GitHub CLI，或从 GitHub 下载源代码 ZIP 后解压。不要将 GitHub Token 或 KiwiVM 密钥嵌入下载链接。

This repository is private. Authenticate GitHub CLI on the target machine using your own account, or download and extract the source ZIP from GitHub. Do not embed credentials in download URLs.

已登录 GitHub CLI 后，一行获取源码并启动向导：

```bash
gh repo clone siagfried/x3-monitor && cd x3-monitor && sudo bash install.sh
```

已下载完整源码时 / From an extracted checkout:

```bash
sudo bash install.sh
```

安装器启动时显示中英文前提说明与 VEID/API Key 获取方式，随后交互输入：

1. VEID、API Key（隐藏输入）。
2. 3x-ui API 地址、Token 或用户名和密码（隐藏输入）。
3. 本机连接方式、可选自签 CA、监控端口（默认 8098）。
4. Tailnet HTTPS 端口（默认 8443，必须空闲）。
5. 可选的**已有** 3x-ui Tailnet 管理入口、显示时区（默认 `Asia/Shanghai`）。

The bilingual wizard asks for VEID/API key, 3x-ui API connection details, an optional CA file, loopback port, a free Tailnet HTTPS port, optional existing Tailnet panel link and display timezone. Secrets are entered without echo. Preflight checks verify both APIs before installing the service.

安装后自动启动并启用开机自启，最终显示本机的 `https://<device>.<tailnet>.ts.net:<port>/` 入口。监控无需额外用户名密码；仍受 Tailnet 访问策略约束。密码和密钥仅存于 `/opt/x3-monitor/config.json`（`root:x3-monitor`、`0640`），临时配置由受限临时目录清理。不要在带 `-x` 的调试会话中安装或分享配置文件。

The service starts immediately and is enabled at boot. The installer prints the Tailnet-only dashboard URL. The dashboard has no additional login; Tailnet policy controls access. Credentials remain in a restricted local configuration and are not committed to this repository.

仅查看计划 / Preview without changes:

```bash
bash install.sh --dry-run
```

高级配置 / Advanced: copy `config.example.json`, fill it in under a restricted directory, then run `sudo bash install.sh /absolute/path/config.json`. Public monitor origins and occupied unrelated Tailnet routes are rejected. Existing managed installations retain their current config and history even if a config argument is supplied.

## VEID / API Key 获取方式 / Where to obtain them

1. 登录 [BandwagonHost 客户中心](https://bandwagonhost.com/clientarea.php)。
2. 打开 **Services → My Services → 目标 VPS → KiwiVM Control Panel**。
3. 在 KiwiVM 左侧点击 **API**，复制页面显示的 **VEID**。
4. 点击 **Show API Key** 查看现有密钥。不要随意使用 Reset API Key，重置会使其他应用中的旧密钥失效。

Sign in to the [BandwagonHost client area](https://bandwagonhost.com/clientarea.php), open your VPS in **Services → My Services**, launch **KiwiVM Control Panel**, then open **API**. Copy VEID and reveal the existing key using **Show API Key**. Avoid resetting a key used by other applications. The authenticated API page also provides the [KiwiVM API reference](https://kiwivm.64clouds.com/api-doc.php).

本程序固定只读查询白名单：`getServiceInfo`、`getAuditLog`、`backup/list`、`snapshot/list`、`getSuspensionDetails`、`getPolicyViolations`。不提供开关机、重装、删除或恢复备份等操作。API Key 本身可能具有更广的供应商权限，应仅存放在可信服务器。

The application enforces the read-only allowlist above. It does not implement power controls, reinstall, backup deletion or restore. The key itself may have broader provider permissions; keep it on a trusted server.

## 网络边界 / Tailnet-only access

Web 服务仅绑定 `127.0.0.1`，Tailscale Serve 将选定的 HTTPS 端口转发至它；不启用公网 Funnel，不监听 `0.0.0.0`，不重置其他 Serve 端口。目标端口存在其他转发或 Funnel 时，安装会停止。参见 [Tailscale Serve 官方文档](https://tailscale.com/docs/reference/tailscale-cli/serve) 与 [Serve/Funnel 访问范围](https://tailscale.com/docs/features/tailscale-funnel)。

The monitor binds loopback only. The installer adds only the chosen Tailscale Serve HTTPS route and never enables Funnel or resets unrelated routes. A conflicting route or Funnel on that port stops installation.

**3x-ui 原有管理页是否公开，由其已有配置决定。安装器不会自动收紧面板公网访问，也不会创建新的面板转发；先将面板管理入口设置为仅 Tailnet 可访问，再填入可选入口链接。订阅可以继续保留公网访问。**

The installer does not change the existing panel's exposure. Configure the 3x-ui management page for Tailnet-only access separately, then supply its existing Tailnet link if desired. Public subscriptions can remain available independently. The optional link merely opens the panel; panel theme synchronization needs a separately configured compatible theme bridge.

## 功能 / Features

- 中英文切换、深浅主题，电脑三列、平板两列、手机单列。
- 总览固定第一，客户端独立日历，统一六行日期高度。无使用无底色，少于 2 小时浅青绿、达到 2 小时深青绿。
- 每日时间轴及活跃时段提示：时间范围、上下行流量。采样流量在区间内按时间比例分摊，因此单段流量为估计值。
- 选择卡片可排序、关注；设备图标可更换。排序、关注和设备图标由服务器保存；语言、主题由浏览器保存。
- 未选中时隐藏“今日”和零值时间／流量，保留占位；选中时显示。
- 关注客户端从无流量转为活跃时 Web Push 通知；首次观测和采集恢复不提醒。
- 官方已用／总流量、精确重置时间，应用供应商流量倍率；以 `data_next_reset` 为准，不按固定“每月 8 日零点”推算。
- 系统状态：本机资源、KiwiVM 操作日志、自动备份与快照、暂停／违规记录（接口提供时）。备份只展示元数据，不提供下载、恢复或删除操作。
- 历史记录保留 365 天；独立安装与安全卸载。

Features: Chinese/English UI, light/dark themes, responsive 3/2/1-column layout, pinned overview, per-client calendars and daily timelines, shared ordering/favorites/icons, Web Push activity alerts, authoritative KiwiVM bandwidth and reset time, system resources, provider audit/backup/issue metadata and 365-day retention.

“活跃”指采样区间有流量，不代表真实连接在线。每日总览使用时长按客户端累加，可超过 24 小时。KiwiVM 总流量和客户端采样统计的范围不同，不保证数值相等。界面 GB 使用 `1024³` 字节，与现有 KiwiVM 统计换算保持一致。

Active means traffic observed during a sampling interval, not an exact connection state. Overview duration sums all clients and may exceed 24 hours. Provider bandwidth and per-client sampled traffic have different scopes. GB is displayed using `1024³` bytes.

通知需要在每个设备的浏览器允许并订阅。网页关闭后可通过浏览器厂商推送服务接收加密消息；完全退出浏览器、禁用后台运行或系统通知权限时不保证送达。iOS/iPadOS 可能需要添加到主屏幕。该安装器不会替用户授权或发送通知。

Notifications require browser permission and subscription on each device. Background delivery depends on browser/OS support; installation does not grant permission or send notifications automatically.

## 升级和卸载 / Upgrade and uninstall

更新源码后再次运行 `sudo bash install.sh`。保留配置、VAPID 密钥及历史；依赖准备好后才短暂重启监控服务。切换程序失败时回滚先前程序。3x-ui / Xray 不重启。

Update the checkout and rerun the installer. Existing config, push identity and history are retained. Dependencies are prepared before interrupting the monitor; failed upgrades restore the previous program. The panel and Xray are not restarted.

```bash
# 停止并移除监控程序，保留配置和历史 / Keep config and history
sudo bash /opt/x3-monitor/uninstall.sh

# 完全清理：交互输入确认短语 / Purge requires an exact interactive confirmation
sudo bash /opt/x3-monitor/uninstall.sh --purge
```

卸载仅删除安装器记录且仍与原配置完全匹配的监控 Serve 路由。外部创建的路由、面板访问防护、订阅和服务账号保留。若路由已被其他配置改变，卸载会停止并提示检查。默认保留的配置含密钥，请继续保护。

Uninstall removes only an unchanged Serve route owned by this installer. External routes, panel protection, subscriptions and the service account remain. Modified routes are preserved for manual review. Retained configuration still contains secrets.

## 验证 / Validation

```bash
python3 -m unittest discover -s tests
bash tests/scripts.sh
```

36 项自动化测试及隔离安装／升级／回滚／卸载分支测试已通过。`tests/scripts.sh` 使用临时目录与模拟 systemd/account，不操作真实 `/opt`。这验证安装逻辑，不等于在任意新 VPS 上完成了真实安装、证书签发或浏览器通知实收。当前没有在现有生产监控上重新执行安装器。

36 automated tests and sandbox installation/upgrade/rollback/uninstall checks passed. These validate logic, not a completed installation or certificate issuance on every new VPS. Web Push receipt requires device-level acceptance. The installer has not been rerun against the existing production monitor.

本项目为独立监控工具，与 BandwagonHost、Tailscale、3x-ui 官方无隶属关系。

An independent monitoring tool, not affiliated with BandwagonHost, Tailscale or 3x-ui.
