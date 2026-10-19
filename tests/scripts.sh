#!/usr/bin/env bash
# Sandbox test of destructive branches. Never operates on /opt or real systemd.
set -euo pipefail
SRC=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
SANDBOX=$(mktemp -d)
trap 'rm -rf -- "$SANDBOX"' EXIT
ROOT="$SANDBOX/installation"
mkdir -p "$SANDBOX/bin" "$SANDBOX/system"
printf '#!/bin/sh\nexit 0\n' > "$SANDBOX/bin/systemctl"
chmod +x "$SANDBOX/bin/systemctl"
export PATH="$SANDBOX/bin:$PATH"
sed -e "s|/opt/x3-monitor|$ROOT|g" -e "s|/etc/systemd/system/x3-monitor.service|$SANDBOX/system/x3-monitor.service|g" -e 's/\[\[ $EUID -eq 0 \]\]/true/' "$SRC/uninstall.sh" > "$SANDBOX/uninstall.sh"
bash -n "$SRC/install.sh"
bash -n "$SRC/uninstall.sh"
bash "$SRC/install.sh" --dry-run
bash "$SRC/uninstall.sh" --dry-run
if bash "$SRC/install.sh" --bad argument; then echo 'FAIL invalid args'; exit 1; fi
if bash "$SANDBOX/uninstall.sh"; then echo 'FAIL unmanaged directory'; exit 1; fi
mkdir -p "$ROOT/data" "$ROOT/venv"
touch "$ROOT/.x3-monitor-owned" "$ROOT/monitor.py" "$ROOT/uninstall.sh" "$ROOT/dashboard.html" "$ROOT/config.json" "$ROOT/data/history" "$SANDBOX/system/x3-monitor.service"
if bash "$SANDBOX/uninstall.sh" --purge </dev/null; then echo 'FAIL unattended purge'; exit 1; fi
[[ -f $ROOT/data/history && -f $ROOT/config.json ]]
bash "$SANDBOX/uninstall.sh"
[[ -f $ROOT/data/history && -f $ROOT/config.json && -f $ROOT/.x3-monitor-owned ]]
[[ ! -e $ROOT/venv && ! -e $ROOT/monitor.py && ! -e $SANDBOX/system/x3-monitor.service ]]
echo 'PASS: syntax, dry runs, invalid arguments, ownership guard, purge guard, default data retention'

# Exercise install/upgrade control flow with mocked account, Python and systemd.
# Actual file copy/mkdir/chmod execute only under the sandbox.
cp "$SRC/billing.py" "$SRC/configure.py" "$SRC/monitor.py" "$SRC/dashboard.html" "$SRC/push_support.py" "$SRC/provider.py" "$SRC/sw.js" "$SRC/manifest.webmanifest" "$SRC/icon.svg" "$SRC/install_dependencies.py" "$SRC/initialize_push.py" "$SRC/requirements.txt" "$SRC/x3-monitor.service" "$SANDBOX/"
printf '{}\n' > "$SANDBOX/input.json"
sed -e "s|/opt/x3-monitor|$ROOT|g" -e "s|/etc/systemd/system/x3-monitor.service|$SANDBOX/system/x3-monitor.service|g" -e 's/\[\[ $EUID -eq 0 \]\]/true/' -e 's|\[\[ -d /run/systemd/system \]\]|true|' "$SRC/install.sh" > "$SANDBOX/install.sh"
cat > "$SANDBOX/bin/python3" <<'SH'
#!/usr/bin/env bash
set -e
if [[ ${1:-} == -m && ${2:-} == venv ]]; then
  target=${@: -1}
  mkdir -p "$target/bin"
  cat > "$target/bin/python" <<'PYSH'
#!/bin/sh
case "$1" in
  *initialize_push.py) if [ "${FAIL_INITIALIZE:-0}" = 1 ]; then exit 9; fi ;;
esac
exit 0
PYSH
  chmod +x "$target/bin/python"
fi
if [[ ${1:-} == - ]]; then cat >/dev/null; fi
exit 0
SH
printf '#!/bin/sh\nexit 0\n' > "$SANDBOX/bin/id"
printf '#!/bin/sh\nexit 0\n' > "$SANDBOX/bin/chown"
printf '#!/bin/sh\nprintf "x3-monitor:x:999:999::%s:/bin/false\\n"\n' "$ROOT" > "$SANDBOX/bin/getent"
cat > "$SANDBOX/bin/install" <<'SH'
#!/usr/bin/env bash
args=()
while (( $# )); do
  case $1 in
    -o|-g|-m) shift 2 ;;
    -d) directory=1; shift ;;
    *) args+=("$1"); shift ;;
  esac
done
if [[ ${directory:-0} == 1 ]]; then mkdir -p -- "${args[@]}"; else cp -- "${args[@]}"; fi
SH
chmod +x "$SANDBOX/bin/"*
# Existing retained config must survive upgrade.
echo 'retained secret config' > "$ROOT/config.json"
bash "$SANDBOX/install.sh" "$SANDBOX/input.json"
[[ $(cat "$ROOT/config.json") == 'retained secret config' && -f $ROOT/data/history ]]
[[ -f $ROOT/monitor.py && -f $ROOT/venv/bin/python && -f $SANDBOX/system/x3-monitor.service ]]
[[ $(stat -c %a "$ROOT/venv/bin") != 700 ]]
# A failed upgrade must restore code/config/venv and keep history.
echo 'old code fixture' > "$ROOT/monitor.py"
if FAIL_INITIALIZE=1 bash "$SANDBOX/install.sh" "$SANDBOX/input.json"; then echo 'FAIL injected upgrade failure'; exit 1; fi
[[ $(cat "$ROOT/monitor.py") == 'old code fixture' && $(cat "$ROOT/config.json") == 'retained secret config' ]]
[[ -f $ROOT/venv/bin/python && -f $ROOT/data/history ]]
echo 'PASS: failed upgrade restores previous monitor and retains history'
# Fresh install must use input config; retain earlier data fixture outside target.
mv "$ROOT" "$SANDBOX/retained"
rm -f "$SANDBOX/system/x3-monitor.service"
bash "$SANDBOX/install.sh" "$SANDBOX/input.json"
cmp "$ROOT/config.json" "$SANDBOX/input.json"
echo 'PASS: mocked fresh install and upgrade preserve existing configuration/history'
# Simulate an interactive terminal only in the sandbox copy to test exact phrase matching.
sed 's/\[\[ -t 0 \]\]/true/' "$SANDBOX/uninstall.sh" > "$SANDBOX/interactive-uninstall.sh"
if printf 'DELETE\n' | bash "$SANDBOX/interactive-uninstall.sh" --purge; then echo 'FAIL short confirmation accepted'; exit 1; fi
[[ -f $ROOT/config.json ]]
printf 'DELETE %s\n' "$ROOT" | bash "$SANDBOX/interactive-uninstall.sh" --purge
[[ ! -e $ROOT && -f $SANDBOX/retained/data/history ]]
echo 'PASS: wrong purge phrase rejected, exact purge deletes only sandbox target'
