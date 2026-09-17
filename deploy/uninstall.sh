#!/usr/bin/env bash
#
# Footyfootball — gỡ cài đặt VPS
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/footyfootball}"
SERVICE_USER="${SERVICE_USER:-footy}"

log()  { printf '\033[1;34m[uninstall]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Cần chạy với sudo:  sudo bash deploy/uninstall.sh"
  exit 1
fi

log "Dừng và xoá dịch vụ…"
systemctl stop footyfootball-web.service footyfootball-scraper.timer 2>/dev/null || true
systemctl disable footyfootball-web.service footyfootball-scraper.timer footyfootball-scraper.service 2>/dev/null || true
rm -f /etc/systemd/system/footyfootball-web.service \
      /etc/systemd/system/footyfootball-scraper.service \
      /etc/systemd/system/footyfootball-scraper.timer
systemctl daemon-reload
ok "Đã xoá service + timer"

log "Xoá thư mục $INSTALL_DIR…"
rm -rf "$INSTALL_DIR"
ok "Đã xoá thư mục"

log "Xoá user $SERVICE_USER…"
if id "$SERVICE_USER" &>/dev/null; then
  userdel "$SERVICE_USER" 2>/dev/null || true
  ok "Đã xoá user $SERVICE_USER"
fi

ok "Gỡ cài đặt hoàn tất."
