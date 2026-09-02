#!/usr/bin/env bash
#
# Footyfootball — VPS auto-installer (Ubuntu/Debian)
#
# Cài đặt:  curl -fsSL https://raw.githubusercontent.com/Bacbenny/Footyfootball/main/deploy/install.sh | sudo bash
# Hoặc chạy local:  sudo bash deploy/install.sh
#
# Tuỳ chọn (đặt trước lệnh chạy):
#   INSTALL_DIR=/opt/footyfootball   thư mục cài đặt
#   HTTP_PORT=8000                   cổng phục vụ playlist
#   VN_PROXY=http://user:pass@host:port   proxy VN (nếu IP ngoài VN)
#   USER_TOKEN=xxx  FPT_USE_USER_TOKEN=true   token FPT Play (tuỳ chọn)
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/footyfootball}"
HTTP_PORT="${HTTP_PORT:-8000}"
SERVICE_USER="${SERVICE_USER:-footy}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

# ── kiểm tra root ──────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  err "Cần chạy với sudo:  sudo bash deploy/install.sh"
  exit 1
fi

# ── 1. cài gói hệ thống ────────────────────────────────────────
log "Cập nhật apt và cài Python + curl…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv curl git >/dev/null

# ── 2. tạo user dịch vụ (không có shell login) ─────────────────
if ! id "$SERVICE_USER" &>/dev/null; then
  log "Tạo user dịch vụ '$SERVICE_USER'…"
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  ok "Đã tạo user $SERVICE_USER"
fi

# ── 3. tạo thư mục cài đặt ─────────────────────────────────────
log "Cài đặt vào $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$REPO_DIR"/scraper.py "$REPO_DIR"/test_scraper.py "$INSTALL_DIR"/
[[ -f "$REPO_DIR/.env" ]] && cp "$REPO_DIR/.env" "$INSTALL_DIR/"

# ── 4. tạo virtualenv + cài thư viện ───────────────────────────
log "Tạo virtualenv và cài thư viện…"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet 'requests[socks]' curl_cffi
ok "Đã cài thư viện"

# ── 5. chạy test offline ───────────────────────────────────────
log "Chạy unit test…"
if (cd "$INSTALL_DIR" && "$INSTALL_DIR/venv/bin/python" -m pytest -q test_scraper.py 2>/dev/null || \
    cd "$INSTALL_DIR" && "$INSTALL_DIR/venv/bin/python" -m unittest -q test_scraper.py); then
  ok "Test đạt"
else
  err "Test thất bại — kiểm tra lại code"
fi

# ── 6. tạo file .env từ biến môi trường ────────────────────────
ENV_FILE="$INSTALL_DIR/.env"
log "Tạo $ENV_FILE"
cat > "$ENV_FILE" <<EOF
# Footyfootball — tự động sinh bởi install.sh
# Proxy VN (nếu VPS ngoài VN):  http://user:pass@host:port  hoặc  host:port:user:pass
VN_PROXY=${VN_PROXY:-}
# Token FPT Play (tuỳ chọn, mở thêm kênh)
USER_TOKEN=${USER_TOKEN:-}
FPT_USE_USER_TOKEN=${FPT_USE_USER_TOKEN:-false}
EOF
chmod 600 "$ENV_FILE"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
ok "Đã ghi $ENV_FILE"

# ── 7. tạo systemd service (HTTP server) ───────────────────────
log "Tạo systemd service footyfootball-web (port $HTTP_PORT)…"
cat > /etc/systemd/system/footyfootball-web.service <<EOF
[Unit]
Description=Footyfootball HTTP playlist server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python -m http.server $HTTP_PORT --bind 0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# ── 8. tạo systemd service (scraper) ───────────────────────────
log "Tạo systemd service footyfootball-scraper…"
cat > /etc/systemd/system/footyfootball-scraper.service <<EOF
[Unit]
Description=Footyfootball playlist generator
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/scraper.py
EOF

# ── 9. tạo systemd timer (mỗi giờ) ─────────────────────────────
log "Tạo systemd timer footyfootball-scraper (mỗi 1 giờ)…"
cat > /etc/systemd/system/footyfootball-scraper.timer <<EOF
[Unit]
Description=Run Footyfootball scraper every hour

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ── 10. kích hoạt dịch vụ ──────────────────────────────────────
systemctl daemon-reload
systemctl enable --now footyfootball-web.service
systemctl enable --now footyfootball-scraper.timer

# chạy scraper ngay lần đầu
log "Chạy scraper lần đầu…"
systemctl start footyfootball-scraper.service || true
sleep 3
if systemctl is-active --quiet footyfootball-scraper.service; then
  err "Scraper vẫn đang chạy hoặc lỗi — xem: journalctl -u footyfootball-scraper -e"
else
  ok "Scraper chạy xong lần đầu"
fi

ok "══════════════════════════════════════════════════"
ok " Cài đặt hoàn tất!"
ok "══════════════════════════════════════════════════"
echo
echo "  Playlist URL:   http://<IP-VPS>:$HTTP_PORT/playlist.m3u"
echo "  Thư mục:        $INSTALL_DIR"
echo "  Cập nhật mỗi:   1 giờ (systemd timer)"
echo
echo "  Lệnh hữu ích:"
echo "    systemctl status footyfootball-web"
echo "    systemctl status footyfootball-scraper"
echo "    journalctl -u footyfootball-scraper -f   # xem log realtime"
echo "    systemctl restart footyfootball-scraper   # chạy ngay"
echo "    sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python $INSTALL_DIR/scraper.py  # chạy thủ công"
echo
echo "  Gỡ cài đặt:  sudo bash $INSTALL_DIR/deploy/uninstall.sh"
