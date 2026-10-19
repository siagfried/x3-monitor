"""Interactive setup and narrowly scoped Tailnet deployment helpers."""
import argparse
import getpass
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import monitor
import provider

ROOT = Path('/opt/x3-monitor')


def ts_json(*args):
    result = subprocess.run(['tailscale', *args, '--json'], check=True,
                            capture_output=True, text=True, timeout=20)
    return json.loads(result.stdout or '{}')


def tailnet():
    status = ts_json('status')
    if status.get('BackendState') != 'Running':
        raise ValueError('请先安装并登录 Tailscale，再运行安装器。')
    dns = status.get('Self', {}).get('DNSName', '').rstrip('.')
    if not dns.endswith('.ts.net'):
        raise ValueError('未找到本机 Tailnet DNS 名称，请先启用 MagicDNS。')
    return dns, ts_json('serve', 'status')


def route(config, dns, port):
    key = f'{dns}:{port}'
    return config.get('Web', {}).get(key, {}), config.get('TCP', {}).get(str(port)), config.get('AllowFunnel', {}).get(key, False)


def require_route_available(current, dns, port, proxy, owned=False):
    web, tcp, funnel = route(current, dns, port)
    if funnel:
        raise ValueError('选定端口已启用公网 Funnel，请改用其他端口。安装器不会修改既有 Funnel。')
    if web or tcp:
        expected = {'Handlers': {'/': {'Proxy': proxy}}}
        if not owned or web != expected or tcp != {'HTTPS': True}:
            raise ValueError('Tailnet HTTPS 端口已被其他配置占用，请使用空闲端口。')


def ask(label, default='', secret=False):
    labels = {
        'KiwiVM API Key（隐藏输入）':'KiwiVM API Key (hidden)',
        '3x-ui 完整地址（含端口和面板路径；HTTPS 请用证书域名）':'3x-ui URL including port and panel path (HTTPS: use certificate hostname)',
        '3x-ui API Token（没有则直接回车，随后输入用户名和密码）':'3x-ui API token (blank to use username/password)',
        '3x-ui 用户名':'3x-ui username', '3x-ui 密码（隐藏输入）':'3x-ui password (hidden)',
        '本机连接地址（填 - 使用面板域名解析）':'Local connect address (- for normal DNS resolution)',
        '自签名证书的 CA 文件绝对路径（公共可信证书直接回车）':'CA file absolute path (blank for publicly trusted certificates)',
        '监控本机端口':'Monitor loopback port', 'Tailnet HTTPS 端口（请勿使用订阅端口）':'Tailnet HTTPS port (do not use subscription port)',
        '已有 3x-ui Tailnet HTTPS 入口（无则回车；不会新建或修改面板转发）':'Existing 3x-ui Tailnet HTTPS link (optional; no panel forwarding will be changed)',
        '显示时区':'Display timezone',
    }
    label = label + (' / '+labels[label] if label in labels else '')
    prompt = label + (f' [{default}]' if default and not secret else '') + ': '
    value = getpass.getpass(prompt) if secret else input(prompt)
    return (value if secret else value.strip()) or default


def port_number(value):
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError('端口需介于 1024 和 65535 之间。')
    return port


def make_config(dns, veid, key, panel_url, username, password, local_port=8098,
                https_port=8443, connect_host='', ca_file='',
                panel_link='', timezone='Asia/Shanghai', token=''):
    if not veid.isdigit() or not key or any(c.isspace() for c in key):
        raise ValueError('VEID 需为数字，API Key 不得为空或包含空白。')
    parsed = urlsplit(panel_url)
    if parsed.query or parsed.fragment or parsed.password:
        raise ValueError('面板地址不能含查询参数、账号密码或片段。')
    if connect_host not in ('', '127.0.0.1', '::1'):
        raise ValueError('本机连接地址只能使用 loopback。')
    origin = f'https://{dns}:{https_port}'
    if panel_link:
        link = urlsplit(panel_link)
        if link.scheme != 'https' or link.hostname != dns or link.username or link.query or link.fragment:
            raise ValueError('入口链接需为本机 Tailnet HTTPS 地址，可留空隐藏。')
    ZoneInfo(timezone)
    cfg = dict(panel=dict(url=panel_url, username=username, password=password, token=token,
                          ca_file=ca_file, timeout=15, list_path='panel/api/inbounds/list', connect_host=connect_host),
               web=dict(host='127.0.0.1', port=local_port, auth=False, public_origin=origin),
               timezone=timezone, interval_seconds=60, max_gap_seconds=150,
               database=str(ROOT/'data/monitor.sqlite3'), retention_days=365,
               panel_link=panel_link, provider=dict(veid=veid, api_key=key),
               installer=dict(manage_serve=True, https_port=https_port))
    monitor.validate(cfg)
    return cfg


def wizard():
    if not sys.stdin.isatty():
        raise ValueError('请在交互终端运行 sudo bash install.sh；不要将脚本通过管道直接执行。')
    dns, current = tailnet()
    print('''X3 Monitor 安装向导 / Setup wizard
仅支持 BandwagonHost（搬瓦工）/ BandwagonHost only.
必须预先安装并运行 3x-ui / Install and run 3x-ui before using this installer.

VEID / API Key 获取方式：
1. 登录 https://bandwagonhost.com/clientarea.php
2. Services → My Services → 目标 VPS → KiwiVM Control Panel。
3. KiwiVM 左侧选择 API，复制页面显示的 VEID；点击 Show API Key 查看密钥。
   使用已有密钥即可；不要点击 Reset API Key，以免影响其他应用。
   API 页面和文档：https://kiwivm.64clouds.com/api-doc.php
Get VEID / API Key:
Sign in at https://bandwagonhost.com/clientarea.php → Services → My Services →
your VPS → KiwiVM Control Panel → API. Copy VEID and click Show API Key.
Use your existing key; do not reset it, as other applications may depend on it.
密钥输入不会回显，仅写入本机受限配置，不进入安装日志。
Secret input is hidden and stored in a restricted local config, never printed.

还需要 3x-ui 的 API 连接信息；网页本身仅通过 Tailnet 访问，无额外监控登录。
安装不会改动或重启 3x-ui / Xray，不会改动订阅端口或公网防火墙。
''')
    veid = ask('VEID')
    key = ask('KiwiVM API Key（隐藏输入）', secret=True)
    panel_url = ask('3x-ui 完整地址（含端口和面板路径；HTTPS 请用证书域名）')
    token = ask('3x-ui API Token（没有则直接回车，随后输入用户名和密码）', secret=True)
    username = '' if token else ask('3x-ui 用户名')
    password = '' if token else ask('3x-ui 密码（隐藏输入）', secret=True)
    parsed = urlsplit(panel_url)
    default_host = '' if parsed.hostname in ('127.0.0.1', '::1', 'localhost') else '127.0.0.1'
    print('证书域名可经 127.0.0.1 连接并保留证书验证 / A certificate hostname can connect over loopback with TLS hostname verification.')
    connect_host = ask('本机连接地址（填 - 使用面板域名解析）', default_host)
    if connect_host == '-':
        connect_host = ''
    ca_file = ask('自签名证书的 CA 文件绝对路径（公共可信证书直接回车）')
    local_port = port_number(ask('监控本机端口', '8098'))
    https_port = port_number(ask('Tailnet HTTPS 端口（请勿使用订阅端口）', '8443'))
    require_route_available(current, dns, https_port, f'http://127.0.0.1:{local_port}')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', local_port))
    panel_link = ask('已有 3x-ui Tailnet HTTPS 入口（无则回车；不会新建或修改面板转发）')
    timezone = ask('显示时区', 'Asia/Shanghai')
    cfg = make_config(dns, veid, key, panel_url, username, password, local_port,
                      https_port, connect_host, ca_file, panel_link, timezone, token)
    print('只读检查 3x-ui 与 KiwiVM API / Checking existing 3x-ui and KiwiVM read-only APIs…')
    monitor.Panel(cfg['panel']).fetch()
    provider.fetch(cfg['provider'])
    print('检查通过 / Checks passed. Installing the isolated monitor service.')
    return cfg


def preflight(cfg):
    monitor.validate(cfg)
    dns, current = tailnet()
    origin = urlsplit(cfg['web'].get('public_origin', ''))
    if origin.scheme != 'https' or origin.hostname != dns or origin.username or origin.query or origin.fragment or origin.path not in ('', '/'):
        raise ValueError('监控 public_origin 必须为本机 Tailnet HTTPS 地址。')
    port = origin.port or 443
    proxy = f"http://127.0.0.1:{int(cfg['web']['port'])}"
    require_route_available(current, dns, port, proxy, owned=(ROOT/'.x3-monitor-owned').is_file())
    return dns, port, proxy, current


def prepare_ca(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    source = cfg['panel'].get('ca_file')
    if source:
        destination = ROOT/'panel-ca.crt'
        if Path(source).resolve() != destination.resolve():
            shutil.copyfile(source,destination)
        destination.chmod(0o640)
        cfg['panel']['ca_file'] = str(destination)
        Path(path).write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')


def activate_serve(cfg):
    dns, port, proxy, current = preflight(cfg)
    web, _, _ = route(current, dns, port)
    if not web:
        (ROOT/'.serve-owned.json').write_text(json.dumps(dict(dns=dns,port=port,proxy=proxy)),encoding='utf-8')
        (ROOT/'.serve-owned.json').chmod(0o600)
        subprocess.run(['tailscale','serve','--bg',f'--https={port}',proxy],check=True,timeout=90)
    # Re-read the daemon state: a successful CLI exit alone is not evidence of isolation.
    web, tcp, funnel = route(ts_json('serve','status'),dns,port)
    if funnel or web != {'Handlers':{'/':{'Proxy':proxy}}} or tcp != {'HTTPS':True}:
        raise ValueError('Tailnet Serve 状态校验失败，请检查 Tailscale。')
    print('监控入口 / Dashboard (Tailnet only): '+cfg['web']['public_origin']+'/')


def remove_owned_serve():
    marker = ROOT/'.serve-owned.json'
    if not marker.is_file() or marker.is_symlink():
        return
    owned = json.loads(marker.read_text())
    current = ts_json('serve','status')
    web, tcp, funnel = route(current,owned['dns'],owned['port'])
    if not web and not tcp and not funnel:
        marker.unlink()
    elif not funnel and web == {'Handlers':{'/':{'Proxy':owned['proxy']}}} and tcp == {'HTTPS':True}:
        subprocess.run(['tailscale','serve',f"--https={int(owned['port'])}",'off'],check=True,timeout=30)
        marker.unlink()
    else:
        raise ValueError('监控转发已被其他配置更改，保留该转发；请手动检查后再卸载。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    parser.add_argument('--preflight')
    parser.add_argument('--serve')
    parser.add_argument('--prepare-ca')
    parser.add_argument('--remove-serve',action='store_true')
    args = parser.parse_args()
    try:
        if args.output:
            cfg = wizard()
            fd = os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump(cfg,f,ensure_ascii=False,indent=2)
        elif args.preflight:
            cfg = json.loads(Path(args.preflight).read_text(encoding='utf-8'))
            preflight(cfg)
            if not cfg.get('provider',{}).get('veid') or not cfg.get('provider',{}).get('api_key'):
                raise ValueError('仅支持 BandwagonHost：请配置 VEID 和 API Key / BandwagonHost VEID and API Key required')
            monitor.Panel(cfg['panel']).fetch()
            provider.fetch(cfg['provider'])
            print('3x-ui / KiwiVM 只读检查通过 / Read-only API checks passed.')
        elif args.serve:
            activate_serve(json.loads(Path(args.serve).read_text(encoding='utf-8')))
        elif args.prepare_ca:
            prepare_ca(args.prepare_ca)
        elif args.remove_serve:
            remove_owned_serve()
        else:
            parser.error('choose --output, --preflight, --serve or --remove-serve')
    except (Exception,KeyboardInterrupt) as exc:
        # Do not print raw network exceptions: they may embed sensitive URLs.
        message = str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        print('安装检查未通过 / Setup check failed: '+message,file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
