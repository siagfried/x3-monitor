#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT=/opt/x3-monitor
UNIT=/etc/systemd/system/x3-monitor.service
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
FILES=(monitor.py dashboard.html push_support.py provider.py configure.py sw.js manifest.webmanifest icon.svg install_dependencies.py initialize_push.py requirements.txt uninstall.sh)
echo 'X3 Monitor · 仅支持 BandwagonHost（搬瓦工）/ BandwagonHost only'
echo '必须预先安装并运行 3x-ui / A working 3x-ui installation is required.'
echo '仅安装独立监控服务；不安装、修改或重启 3x-ui / Xray。'
echo 'Installs the monitor only; never installs, modifies or restarts 3x-ui / Xray.'
if [[ ${1:-} == --dry-run && $# -eq 1 ]]; then
  echo 'PLAN: interactive VEID/API + panel setup -> read-only checks -> isolated venv -> systemd -> Tailnet HTTPS only.'
  echo 'Existing configuration/history and unrelated Tailscale routes are preserved; no Funnel or firewall changes.'
  exit 0
fi
[[ $# -le 1 && ${1:-} != -* ]] || { echo 'Usage: sudo bash install.sh [config.json | --dry-run]'; exit 2; }
[[ $EUID -eq 0 ]] || { echo '请使用 sudo / Run as root'; exit 1; }
[[ -d /run/systemd/system ]] || { echo '需要正在运行的 systemd / Running systemd required'; exit 1; }
command -v python3 >/dev/null || { echo '请先安装 python3 和 python3-venv / Install Python 3.10+ and python3-venv first'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
[[ ! -L $ROOT && ! -L $UNIT && ! -L $ROOT/config.json && ! -L $ROOT/data && ! -L $ROOT/venv ]] || { echo '拒绝符号链接目标 / Refusing symlink target'; exit 1; }
[[ ! -e $ROOT || -f $ROOT/.x3-monitor-owned ]] || { echo '拒绝覆盖未知目录 / Refusing unmanaged directory'; exit 1; }
[[ ! -e $UNIT || -f $ROOT/.x3-monitor-owned ]] || { echo '拒绝覆盖未知服务 / Refusing unmanaged unit'; exit 1; }
for f in "${FILES[@]}" x3-monitor.service; do
  [[ -f $SOURCE/$f ]] || { echo '安装包不完整 / Incomplete source package'; exit 1; }
done
TEMP=$(mktemp -d)
SWITCHED=0
SUCCESS=0
HAD_VENV=0
WAS_ACTIVE=0
WAS_ENABLED=0
HAD_SERVE=0
[[ ! -f $ROOT/.serve-owned.json ]] || HAD_SERVE=1
cleanup() {
  result=$?
  if (( SWITCHED && ! SUCCESS )); then
    set +e
    echo '安装失败，恢复先前程序 / Installation failed; restoring previous program.' >&2
    if (( ! HAD_SERVE )) && [[ -f $ROOT/.serve-owned.json && -f $ROOT/configure.py ]]; then python3 "$ROOT/configure.py" --remove-serve; fi
    systemctl stop x3-monitor.service
    for f in "${FILES[@]}" config.json vapid-private.pem panel-ca.crt; do rm -f -- "$ROOT/$f"; done
    if [[ -f $TEMP/prior.tar ]]; then tar -xf "$TEMP/prior.tar" -C "$ROOT"; fi
    rm -rf -- "$ROOT/venv"
    if (( HAD_VENV )); then mv -- "$TEMP/old-venv" "$ROOT/venv"; fi
    if [[ -f $TEMP/unit.before ]]; then cp -- "$TEMP/unit.before" "$UNIT"; else rm -f -- "$UNIT"; fi
    systemctl daemon-reload
    if (( WAS_ENABLED )); then systemctl enable x3-monitor.service; else systemctl disable x3-monitor.service; fi
    if (( WAS_ACTIVE )); then systemctl start x3-monitor.service; fi
    echo '历史数据保留。请检查错误后重试 / History retained. Review the error and retry.' >&2
  fi
  rm -rf -- "$TEMP"
  exit "$result"
}
trap cleanup EXIT
if [[ -f $ROOT/config.json ]]; then
  CONFIG=$ROOT/config.json
  echo '升级模式：保留原配置、凭据和历史 / Upgrade: preserving existing configuration, credentials and history.'
elif [[ $# -eq 1 ]]; then
  CONFIG=$(realpath -- "$1")
else
  CONFIG=$TEMP/config.json
  python3 "$SOURCE/configure.py" --output "$CONFIG"
fi
python3 "$SOURCE/monitor.py" --config "$CONFIG" --check
python3 "$SOURCE/configure.py" --preflight "$CONFIG"
python3 - "$CONFIG" <<'PY'
import json,sys
c=json.load(open(sys.argv[1]))
assert c['database']=='/opt/x3-monitor/data/monitor.sqlite3', 'Default database path required'
PY
# Prepare all dependencies before interrupting an older monitor installation.
python3 -m venv --without-pip "$TEMP/venv"
"$TEMP/venv/bin/python" "$SOURCE/install_dependencies.py"
if ! id x3-monitor >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$ROOT" --no-create-home --shell /usr/sbin/nologin x3-monitor
else
  [[ $(getent passwd x3-monitor | cut -d: -f6) == "$ROOT" ]] || { echo 'Existing account has unexpected home'; exit 1; }
fi
if [[ -f $ROOT/.x3-monitor-owned ]]; then
  if systemctl is-active --quiet x3-monitor.service; then WAS_ACTIVE=1; fi
  if systemctl is-enabled --quiet x3-monitor.service; then WAS_ENABLED=1; fi
  prior=()
  for f in "${FILES[@]}" config.json vapid-private.pem panel-ca.crt; do [[ ! -f $ROOT/$f ]] || prior+=("$f"); done
  if (( ${#prior[@]} )); then tar -cf "$TEMP/prior.tar" -C "$ROOT" "${prior[@]}"; fi
fi
[[ ! -f $UNIT ]] || cp -- "$UNIT" "$TEMP/unit.before"
if (( WAS_ACTIVE )); then systemctl stop x3-monitor.service; fi
install -d -m 0750 -o root -g x3-monitor "$ROOT"
touch "$ROOT/.x3-monitor-owned"
install -d -m 0700 -o x3-monitor -g x3-monitor "$ROOT/data"
if [[ -d $ROOT/venv ]]; then mv -- "$ROOT/venv" "$TEMP/old-venv"; HAD_VENV=1; fi
SWITCHED=1
mv -- "$TEMP/venv" "$ROOT/venv"
for f in "${FILES[@]}"; do install -m 0640 -o root -g x3-monitor "$SOURCE/$f" "$ROOT/$f"; done
if [[ ! -f $ROOT/config.json ]]; then install -m 0640 -o root -g x3-monitor "$CONFIG" "$ROOT/config.json"; fi
python3 "$ROOT/configure.py" --prepare-ca "$ROOT/config.json"
if [[ -f $ROOT/panel-ca.crt ]]; then chown root:x3-monitor "$ROOT/panel-ca.crt"; fi
"$ROOT/venv/bin/python" "$ROOT/initialize_push.py" "$ROOT/config.json"
chown -R root:x3-monitor "$ROOT/venv"
chmod -R g+rX,o-rwx "$ROOT/venv"
chown root:x3-monitor "$ROOT/vapid-private.pem" "$ROOT/config.json"
chmod 0640 "$ROOT/config.json"
"$ROOT/venv/bin/python" "$ROOT/monitor.py" --config "$ROOT/config.json" --check
install -m 0644 "$SOURCE/x3-monitor.service" "$UNIT"
systemctl daemon-reload
systemctl enable --now x3-monitor.service
systemctl is-active --quiet x3-monitor.service
# Serve only the chosen port. Never reset other routes or enable Funnel.
python3 "$ROOT/configure.py" --serve "$ROOT/config.json"
SUCCESS=1
echo '安装完成，已开机自启 / Installed and enabled at boot.'
echo '卸载（保留历史）/ Uninstall (keep history): sudo bash /opt/x3-monitor/uninstall.sh'
