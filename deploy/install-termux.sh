#!/usr/bin/env bash
#
# Footyfootball — cài đặt trên Termux (Android)
#
# Chạy:  bash deploy/install-termux.sh
#
# Tuỳ chọn (đặt trước lệnh):
#   VN_PROXY=http://user:pass@host:port   proxy VN (nếu IP ngoài VN)
#   USER_TOKEN=xxx  FPT_USE_USER_TOKEN=true   token FPT Play (tuỳ chọn)
#
set -euo pipefail

INSTALL_DIR="$HOME/footyfootball"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log()  { printf '\033[1;34m[termux]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

# ── 1. cài gói Termux ──────────────────────────────────────────
log "Cài Python, git, curl, cron…"
pkg update -y
pkg install -y python git curl cronie termux-services termux-api
ok "Đã cài gói hệ thống"

# ── 2. tạo thư mục cài đặt ─────────────────────────────────────
log "Cài đặt vào $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp "$REPO_DIR"/scraper.py "$REPO_DIR"/test_scraper.py "$INSTALL_DIR"/

# ── 3. cài thư viện Python ─────────────────────────────────────
log "Cài thư viện Python…"
pip install --quiet 'requests[socks]' curl_cffi
ok "Đã cài thư viện"

# ── 4. chạy test ───────────────────────────────────────────────
log "Chạy unit test…"
cd "$INSTALL_DIR"
if python -m unittest -q test_scraper.py; then
  ok "Test đạt"
else
  err "Test thất bại — tiếp tục cài đặt anyway"
fi

# ── 5. tạo file .env ───────────────────────────────────────────
ENV_FILE="$INSTALL_DIR/.env"
log "Tạo $ENV_FILE"
cat > "$ENV_FILE" <<EOF
# Footyfootball — tự động sinh bởi install-termux.sh
VN_PROXY=${VN_PROXY:-}
USER_TOKEN=${USER_TOKEN:-}
FPT_USE_USER_TOKEN=${FPT_USE_USER_TOKEN:-false}
EOF
ok "Đã ghi $ENV_FILE"

# ── 6. chạy scraper lần đầu ────────────────────────────────────
log "Chạy scraper lần đầu…"
cd "$INSTALL_DIR"
python scraper.py || err "Scraper lỗi lần đầu — xem log trên"
ok "Scraper chạy xong"

# ── 7. tạo crontab (mỗi 1 giờ) ─────────────────────────────────
log "Thiết lập crontab chạy mỗi giờ…"
CRON_LINE="0 * * * * cd $INSTALL_DIR && python scraper.py >> $INSTALL_DIR/scraper.log 2>&1"
# xoá dòng cũ nếu có rồi thêm lại
( crontab -l 2>/dev/null | grep -v "footyfootball" ; echo "$CRON_LINE" ) | crontab -
ok "Đã tạo crontab"

# ── 8. tạo script chạy HTTP server ─────────────────────────────
cat > "$INSTALL_DIR/start-server.sh" <<EOF
#!/usr/bin/env bash
# Khởi động HTTP server phục vụ playlist.m3u
cd "$INSTALL_DIR"
echo "HTTP server chạy tại: http://$(hostname):8000/playlist.m3u"
echo "Nhấn Ctrl+C để dừng."
python -m http.server 8000 --bind 0.0.0.0
EOF
chmod +x "$INSTALL_DIR/start-server.sh"
ok "Đã tạo start-server.sh"

# ── 9. tạo script dừng tất cả ──────────────────────────────────
cat > "$INSTALL_DIR/stop-server.sh" <<EOF
#!/usr/bin/env bash
pkill -f "http.server 8000" 2>/dev/null && echo "Đã dừng HTTP server" || echo "HTTP server không chạy"
EOF
chmod +x "$INSTALL_DIR/stop-server.sh"

ok "══════════════════════════════════════════════════"
ok " Cài đặt hoàn tất!"
ok "══════════════════════════════════════════════════"
echo
echo "  Playlist URL:   http://<IP-điện-thoại>:8000/playlist.m3u"
echo "  Thư mục:        $INSTALL_DIR"
echo "  Cập nhật mỗi:   1 giờ (crontab)"
echo
echo "  Lệnh hữu ích:"
echo "    bash $INSTALL_DIR/start-server.sh    # mở HTTP server"
echo "    bash $INSTALL_DIR/stop-server.sh     # dừng HTTP server"
echo "    cd $INSTALL_DIR && python scraper.py # chạy scraper ngay"
echo "    cat $INSTALL_DIR/playlist.m3u        # xem danh sách kênh"
echo "    crontab -l                           # xem lịch crontab"
echo "    crontab -r                           # xoá toàn bộ crontab"
echo
echo "  Lấy IP điện thoại:  ip addr show wlan0 | grep inet"
