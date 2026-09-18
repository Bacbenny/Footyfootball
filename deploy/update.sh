#!/usr/bin/env bash
#
# Cập nhật scraper đã cài trên VPS mà không đụng vào .env hoặc playlist cũ.
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/footyfootball}"
SERVICE_USER="${SERVICE_USER:-footy}"
SOURCE_BASE_URL="${SOURCE_BASE_URL:-https://raw.githubusercontent.com/Bacbenny/Footyfootball/main}"

if [[ $EUID -ne 0 ]]; then
  echo "Cần chạy với sudo: sudo bash /opt/footyfootball/update.sh" >&2
  exit 1
fi

if [[ ! -d "$INSTALL_DIR" || ! -x "$INSTALL_DIR/venv/bin/python" ]]; then
  echo "Không tìm thấy bản cài đặt tại $INSTALL_DIR." >&2
  exit 1
fi

TEMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TEMP_DIR"; }
trap cleanup EXIT

curl --fail --silent --show-error --location \
  "$SOURCE_BASE_URL/scraper.py" -o "$TEMP_DIR/scraper.py"
curl --fail --silent --show-error --location \
  "$SOURCE_BASE_URL/test_scraper.py" -o "$TEMP_DIR/test_scraper.py"

install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 \
  "$TEMP_DIR/scraper.py" "$INSTALL_DIR/scraper.py"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 \
  "$TEMP_DIR/test_scraper.py" "$INSTALL_DIR/test_scraper.py"

(
  cd "$INSTALL_DIR"
  "$INSTALL_DIR/venv/bin/python" -m unittest -q test_scraper.py
)

systemctl start footyfootball-scraper.service
if [[ ! -s "$INSTALL_DIR/playlist.m3u" ]] || ! grep -q '^#EXTINF:' "$INSTALL_DIR/playlist.m3u"; then
  echo "Bản cập nhật không tạo playlist hợp lệ; xem journalctl để biết lỗi." >&2
  exit 1
fi

echo "Đã cập nhật scraper và tạo playlist thành công."