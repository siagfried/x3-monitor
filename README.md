# X3 Monitor

独立的 3x-ui 流量活跃监控：Python venv + systemd + SQLite，60 秒采样。
Independent 3x-ui activity monitoring with an isolated Python venv, systemd, SQLite and 60-second sampling.

**需预先安装并运行 3x-ui。不限制 VPS 服务商；Tailscale 与 BandwagonHost API 均为可选。**
**An existing working 3x-ui installation is required. Any VPS provider is supported; Tailscale and BandwagonHost API are optional.**

![X3 Monitor dashboard](docs/images/dashboard.png)

*示例客户端和流量，不含真实服务器或个人资料。Example clients and traffic, not production or personal data.*

## 安装 / Install

需要 Linux、运行中的 systemd、root/sudo、Python 3.10+、python3-venv、可信 CA 证书，以及可登录的已有 3x-ui API。准备完整面板地址（端口和路径）、API Token 或用户名密码，**不要填订阅地址**。依赖从 PyPI 安装到独立 venv。

Requires Linux, systemd, root/sudo, Python 3.10+, python3-venv, trusted CA certificates and a working existing 3x-ui API. Provide the panel URL with port/base path and a token or credentials—not the subscription URL. Dependencies are installed from PyPI into the venv.

缺少 Python 组件时 / Missing Python components (Debian/Ubuntu):

```bash
sudo apt-get install python3 python3-venv ca-certificates
```

下载完整源码后启动中英文向导 / Start the bilingual wizard from the complete source tree:

```bash
sudo bash install.sh
```

或一行获取源码并安装 / Download and install a tagged version:

```bash
curl -fL https://github.com/siagfried/x3-monitor/archive/refs/tags/v1.1.0.tar.gz -o x3-monitor-v1.1.0.tar.gz && tar -xzf x3-monitor-v1.1.0.tar.gz && cd x3-monitor-1.1.0 && sudo bash install.sh
```

密码、密钥隐藏输入；安装后自动启动并开机自启。不安装、修改或重启 3x-ui/Xray，不改动订阅和防火墙。
Secrets are entered without echo. The monitor starts and is enabled at boot. The installer never installs, modifies or restarts 3x-ui/Xray or changes subscriptions/firewall rules.

只看计划 / Preview: `bash install.sh --dry-run`。
高级 / Advanced: fill in `config.example.json` in a restricted directory, then run `sudo bash install.sh /absolute/path/config.json`. Existing managed installations keep their current configuration/history, even if a new config argument is supplied.

## 访问方式 / Access modes

| 方式 / Mode | 行为 / Behavior |
| --- | --- |
| Tailnet（可选） | Tailscale 已安装、登录并启用 MagicDNS/HTTPS。仅增加选定 Serve 端口，不启用 Funnel、不改动其他路由。Requires Tailscale already signed in; adds only the selected Serve route. |
| HTTPS 反向代理 / Reverse proxy | 默认。绑定 loopback，启用监控登录；需自行配置已有 HTTPS 代理。Default; loopback listener with authentication; configure the HTTPS proxy separately. |
| 直接 HTTPS / Direct HTTPS | 需要有效证书、私钥和登录密码，绑定 `0.0.0.0`；防火墙自行配置。Requires certificate/key and authentication; firewall unchanged. |
| 本机 HTTP / Local HTTP | 仅 `127.0.0.1`，适合本机或 SSH 隧道，不启用推送。Loopback only; push disabled. |

公网方式要求 HTTPS 和至少 16 字符的登录密码。GET、POST 均校验登录，写入还检查 Origin。配置和复制的私钥保存在服务器受限目录（`root:x3-monitor`、`0640`）。
Public access requires HTTPS and a password of at least 16 characters. Reads and writes require authentication; writes also validate Origin. Config and copied keys stay in restricted local files.

代理模式不安装代理、不签发证书、不开防火墙。将 HTTPS 代理指向 `http://127.0.0.1:8098`（或配置端口），保留 Authorization/Origin。直接 HTTPS 复制安装时的证书，续期后需更新 `/opt/x3-monitor/web-cert.pem` 和 `web-key.pem`，保持权限并重启监控。
Proxy mode needs a separately configured HTTPS proxy forwarding to the loopback port with Authorization/Origin preserved. Direct HTTPS uses copied certificates; update the copies after renewal and restart the monitor.

3x-ui 管理页和订阅的访问范围保持原样。可填写已有面板 HTTPS 链接；主题同步需要另行配置兼容桥接。
Panel/subscription exposure stays unchanged. An existing panel HTTPS link is optional; theme synchronization needs a separate compatible bridge.

## 无 API：手动设置 / No provider API

VEID 回车即可跳过供应商 API，适用于其他 VPS 服务商。右上角系统状态中可设置：下次重置日期和时分、已用流量、总流量。默认已用 0、总量 1000 GB、每月 8 日 00:00。
Leave VEID blank to skip provider APIs. System status lets you edit the next reset date/time, used baseline and total allowance. Defaults: zero used, 1000 GB, monthly reset on day 8 at 00:00.

设置按显示时区保存，新的客户端采样流量继续累加到自定义已用量。每月在所设日期、时刻归零；短月份用月底，之后恢复原始日号。GB 为 `1024³` 字节。当期额度独立保存，不受 365 天历史清理影响。
Settings use the displayed timezone. New sampled traffic adds to the baseline. Monthly resets use the chosen local day/time; short months use their last day, then restore the original day. GB is `1024³` bytes. The allowance ledger is independent of history pruning.

**手动用量是 3x-ui 客户端上下行之和，不是供应商对整台 VPS 的官方计费。** 不含未采样系统流量；中断或计数器重置可能漏计，跨重置时刻按区间时间比例估算；不自动回填安装前用量。
**Manual usage is sampled client upload/download, not authoritative whole-VPS billing.** Unmonitored traffic is excluded; gaps/resets may lose data, reset-spanning samples are proportional estimates, and pre-install traffic is not backfilled.

无 API 时显示本机运行时间、负载、可用内存、磁盘和手动额度，不伪造供应商套餐、机房、操作、备份或违规记录。
Without an API, local resources and manual allowance remain available; provider records are not fabricated.

## 可选 BandwagonHost API / Optional provider API

自动供应商对接目前仅支持 KiwiVM；其他服务商使用手动模式。登录 [BandwagonHost 客户中心](https://bandwagonhost.com/clientarea.php)，依次进入 **Services → My Services → 目标 VPS → KiwiVM Control Panel → API**，复制 VEID，点击 **Show API Key**。不要重置其他应用正在使用的密钥。
The optional automatic integration is for KiwiVM; other providers use manual mode. Open the client area, launch KiwiVM for the VPS and open API. Copy VEID and reveal the existing key with Show API Key. Avoid resetting keys used elsewhere. See the [KiwiVM API page](https://kiwivm.64clouds.com/api-doc.php).

有 API 时使用官方流量、倍率和 `data_next_reset`，禁止手动改额度。只读白名单：`getServiceInfo`、`getAuditLog`、`backup/list`、`snapshot/list`、`getSuspensionDetails`、`getPolicyViolations`。不实现开关机、重装、删除或恢复备份。密钥本身可能有更广权限，仅存可信服务器。
With an API, official counters/reset time are authoritative; manual writes are disabled. Only the read-only allowlist above is implemented. Keep the key on a trusted server because the key itself may have broader privileges.

## 界面和通知 / UI and notifications

中英文、深浅主题、电脑三列/平板两列/手机单列；固定总览、六行月历、每日时间轴、排序/关注/设备图标。少于 2 小时浅青绿，达到 2 小时深青绿。未选中时隐藏“今日”和零值统计，保留占位。排序/关注/图标由服务器共享；主题/语言由浏览器保存。
Chinese/English UI, themes, responsive 3/2/1-column layout, overview, calendars/timelines and shared ordering/favorites/icons. Theme/language are browser-local.

活跃仅指 60 秒采样区间观测到流量，不等于连接在线；总览时长按客户端累加，可超过 24 小时。历史保留 365 天。
Active means observed traffic, not exact connection state. Combined duration may exceed 24 hours. History is retained for 365 days.

后台通知需 HTTPS、浏览器/设备授权和关注客户端；仅无流量转活跃时提醒，首次观测和采集恢复不提醒。浏览器厂商推送服务转发加密内容，送达取决于设备/浏览器后台权限；iOS/iPadOS 可能需添加至主屏幕。本机 HTTP 模式禁用推送。
Background alerts require HTTPS and device/browser permission. Delivery depends on OS/browser support. Local HTTP mode disables push.

## 升级、卸载和验证 / Upgrade, uninstall and checks

更新源码后再次运行安装器，保留现有配置、密钥和历史；失败时回滚先前监控程序。
Rerun the updated installer to retain config/keys/history. Failed program switches restore the prior monitor.

```bash
# 保留配置和历史 / Keep configuration and history
sudo bash /opt/x3-monitor/uninstall.sh
# 完全清理，需精确确认短语 / Exact interactive confirmation required
sudo bash /opt/x3-monitor/uninstall.sh --purge
# Tests
python3 -m unittest discover -s tests
bash tests/scripts.sh
```

仅移除本安装器拥有且未更改的 Serve 路由；外部转发、面板、订阅和服务账号保留。默认保留的配置含凭据，请继续保护。
Only unchanged owned Serve routes are removed. External routes, panel, subscriptions and account remain. Retained config contains credentials.

42 项测试、隔离安装/升级/回滚/卸载和示例浏览器手动修改/重载持久化检查通过。公网代理、证书续期需目标环境验收；现有生产监控没有改为公网。
42 tests, sandbox install/upgrade/rollback/uninstall and example-browser persistence checks passed. Proxy/TLS renewal need target acceptance; existing production monitoring was not exposed publicly.

本项目与 3x-ui、BandwagonHost、Tailscale 无官方隶属关系。
Not affiliated with 3x-ui, BandwagonHost or Tailscale.
