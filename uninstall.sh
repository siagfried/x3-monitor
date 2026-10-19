#!/usr/bin/env bash
set -euo pipefail
echo '卸载独立监控；保留 3x-ui / Xray / Remove monitor only; preserve 3x-ui / Xray.'
ROOT=/opt/x3-monitor
PURGE=0
case ${1:-} in
  '') ;;
  --purge) PURGE=1 ;;
  --dry-run) echo 'PLAN: stop/disable service; remove owned code and venv; KEEP data, configuration and account. --purge requires typed confirmation.'; exit 0 ;;
  *) echo 'Usage: sudo bash uninstall.sh [--purge|--dry-run]'; exit 2 ;;
esac
[[ $EUID -eq 0 ]] || { echo 'Run as root'; exit 1; }
[[ ! -L $ROOT && -f $ROOT/.x3-monitor-owned ]] || { echo 'Refusing unrecognized installation'; exit 1; }
[[ $(realpath -- "$ROOT") == /opt/x3-monitor ]] || exit 1
if (( PURGE )); then
  [[ -t 0 ]] || { echo 'Purge requires an interactive terminal'; exit 1; }
  read -r -p 'Delete ALL history and configuration? Type DELETE /opt/x3-monitor: ' ANSWER
  [[ $ANSWER == 'DELETE /opt/x3-monitor' ]] || { echo 'Cancelled'; exit 1; }
fi
# Remove only this installer's exact owned Serve route; preserve all other routes.
if [[ -f $ROOT/.serve-owned.json && -f $ROOT/configure.py ]]; then
  python3 "$ROOT/configure.py" --remove-serve
fi
if systemctl cat x3-monitor.service >/dev/null 2>&1; then
  systemctl disable --now x3-monitor.service
fi
[[ ! -L /etc/systemd/system/x3-monitor.service ]] || { echo 'Refusing symlink unit'; exit 1; }
rm -f -- /etc/systemd/system/x3-monitor.service
systemctl daemon-reload
if (( PURGE )); then
  rm -rf -- /opt/x3-monitor
  echo 'Deleted installation and history. Service account retained; remove manually if no longer needed.'
else
  [[ ! -L $ROOT/venv ]] || { echo 'Refusing symlink venv'; exit 1; }
  rm -rf -- /opt/x3-monitor/venv
  rm -f -- "$ROOT/monitor.py" "$ROOT/dashboard.html" "$ROOT/push_support.py" "$ROOT/provider.py" "$ROOT/configure.py" "$ROOT/sw.js" "$ROOT/manifest.webmanifest" "$ROOT/icon.svg" "$ROOT/install_dependencies.py" "$ROOT/initialize_push.py" "$ROOT/requirements.txt" "$ROOT/uninstall.sh"
  echo 'Removed service and program. KEEP /opt/x3-monitor/data and config.json (contains credentials). Reinstall to resume.'
fi
