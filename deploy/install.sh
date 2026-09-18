#!/usr/bin/env bash
#
# Footyfootball — VPS auto-installer (Ubuntu/Debian)
#
# Clone trước:
#   git clone https://github.com/Bacbenny/Footyfootball.git
#   cd Footyfootball && sudo bash deploy/install.sh
#
# Hoặc cài trực tiếp:
#   curl -fsSL https://raw.githubusercontent.com/Bacbenny/Footyfootball/main/deploy/install.sh | sudo bash
#
# Tuỳ chọn không nhạy cảm:
#   INSTALL_DIR=/opt/footyfootball
#   HTTP_PORT=8000
#   SOURCE_BASE_URL=https://raw.githubusercontent.com/Bacbenny/Footyfootball/main
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/footyfootball}"
HTTP_PORT="${HTTP_PORT:-8000}"
SERVICE_USER="${SERVICE_USER:-footy}"
SOURCE_BASE_URL="${SOURCE_BASE_URL:-https://raw.githubusercontent.com/Bacbenny/Footyfootball/main}"
SCRIPT_PATH="${BASH_SOURCE[0]:-}"

log() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
ok() { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

if [[ -n "${PREFIX:-}" || -n "${TERMUX_VERSION:-}" ]]; then
  err "Bạn đang dùng Termux. Hãy chạy: bash deploy/install-termux.sh"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  err "Cần chạy với sudo: sudo bash deploy/install.sh"
  exit 1
fi

if ! [[ "$HTTP_PORT" =~ ^[0-9]+$ ]] || ((HTTP_PORT < 1 || HTTP_PORT > 65535)); then
  err "HTTP_PORT phải là số từ 1 đến 65535."
  exit 1
fi

SCRIPT_DIR=""
if [[ -n "$SCRIPT_PATH" && -f "$SCRIPT_PATH" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
fi

LOCAL_REPO_DIR=""
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/../scraper.py" ]]; then
  LOCAL_REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

TEMP_SOURCE_DIR=""
cleanup() {
  if [[ -n "$TEMP_SOURCE_DIR" && -d "$TEMP_SOURCE_DIR" ]]; then
    rm -rf "$TEMP_SOURCE_DIR"
  fi
}
trap cleanup EXIT

download_source_file() {
  local name="$1"
  local destination="$2"
  if [[ -n "$LOCAL_REPO_DIR" && -f "$LOCAL_REPO_DIR/$name" ]]; then
    cp "$LOCAL_REPO_DIR/$name" "$destination"
  else
    curl --fail --silent --show-error --location \
      "$SOURCE_BASE_URL/$name" -o "$destination"
  fi
}

export DEBIAN_FRONTEND=noninteractive
log "Cài gói hệ thống cần thiết…"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv curl ca-certificates >/dev/null

if ! id "$SERVICE_USER" &>/dev/null; then
  log "Tạo user dịch vụ '$SERVICE_USER'…"
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

TEMP_SOURCE_DIR="$(mktemp -d)"
download_source_file "scraper.py" "$TEMP_SOURCE_DIR/scraper.py"
download_source_file "test_scraper.py" "$TEMP_SOURCE_DIR/test_scraper.py"
download_source_file "deploy/uninstall.sh" "$TEMP_SOURCE_DIR/uninstall.sh"
download_source_file "deploy/update.sh" "$TEMP_SOURCE_DIR/update.sh"

log "Cài đặt vào $INSTALL_DIR…"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$INSTALL_DIR"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 \
  "$TEMP_SOURCE_DIR/scraper.py" "$INSTALL_DIR/scraper.py"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 \
  "$TEMP_SOURCE_DIR/test_scraper.py" "$INSTALL_DIR/test_scraper.py"
install -o root -g root -m 0755 \
  "$TEMP_SOURCE_DIR/uninstall.sh" "$INSTALL_DIR/uninstall.sh"
install -o root -g root -m 0755 \
  "$TEMP_SOURCE_DIR/update.sh" "$INSTALL_DIR/update.sh"

log "Tạo virtualenv và cài thư viện…"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet "requests[socks]" curl_cffi

log "Chạy unit test…"
if ! (
  cd "$INSTALL_DIR"
  "$INSTALL_DIR/venv/bin/python" -m unittest -q test_scraper.py
); then
  err "Unit test thất bại. Dừng cài đặt để không bật scraper lỗi."
  exit 1
fi
ok "Unit test đạt"

ENV_FILE="$INSTALL_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  log "Tạo cấu hình $ENV_FILE…"
  cat > "$ENV_FILE" <<'EOF'
# Footyfootball — cấu hình scraper
# Để trống nếu VPS có IP Việt Nam.
# Nếu VPS ngoài Việt Nam, điền proxy HTTP/HTTPS có IP Việt Nam:
VN_PROXY=

# Tuỳ chọn: token FPT Play nếu tài khoản của bạn cần dùng.
USER_TOKEN=
FPT_USE_USER_TOKEN=false
EOF
  chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
else
  log "Giữ nguyên cấu hình hiện có $ENV_FILE"
  chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

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
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/footyfootball-scraper.service <<EOF
[Unit]
Description=Footyfootball playlist generator
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/scraper.py
TimeoutStartSec=300
NoNewPrivileges=true
EOF

cat > /etc/systemd/system/footyfootball-scraper.timer <<'EOF'
[Unit]
Description=Run Footyfootball scraper every hour

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
EOF

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chown root:root "$INSTALL_DIR/uninstall.sh" "$INSTALL_DIR/update.sh"
chmod 0755 "$INSTALL_DIR/uninstall.sh" "$INSTALL_DIR/update.sh"
chmod 0600 "$ENV_FILE"

systemctl daemon-reload
systemctl enable --now footyfootball-web.service
systemctl enable --now footyfootball-scraper.timer

log "Chạy scraper lần đầu để kiểm tra API và tạo playlist…"
if ! systemctl start footyfootball-scraper.service; then
  err "Scraper thất bại. Xem log bằng: journalctl -u footyfootball-scraper.service -n 100 --no-pager"
  exit 1
fi

if [[ ! -s "$INSTALL_DIR/playlist.m3u" ]] || ! grep -q '^#EXTINF:' "$INSTALL_DIR/playlist.m3u"; then
  err "Scraper không tạo playlist hợp lệ tại $INSTALL_DIR/playlist.m3u"
  journalctl -u footyfootball-scraper.service -n 80 --no-pager >&2 || true
  exit 1
fi

if ! curl --fail --silent "http://127.0.0.1:$HTTP_PORT/playlist.m3u" >/dev/null; then
  err "HTTP server không phục vụ được playlist trên cổng $HTTP_PORT"
  systemctl status footyfootball-web.service --no-pager >&2 || true
  exit 1
fi

ok "Cài đặt hoàn tất"
echo
echo "  Playlist URL: http://<IP-VPS>:$HTTP_PORT/playlist.m3u"
echo "  Thư mục:      $INSTALL_DIR"
echo "  Cập nhật:      mỗi giờ bằng systemd timer"
echo
echo "  Xem log:       journalctl -u footyfootball-scraper.service -f"
echo "  Chạy ngay:     sudo systemctl start footyfootball-scraper.service"
echo "  Cập nhật code: sudo bash $INSTALL_DIR/update.sh"
echo "  Gỡ cài đặt:   sudo bash $INSTALL_DIR/uninstall.sh"