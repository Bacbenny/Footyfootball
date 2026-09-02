# Triển khai VPS tự động — Footyfootball

Bộ script tự động cài đặt Footyfootball trên VPS Linux (Ubuntu/Debian),
tạo dịch vụ nền phục vụ file `playlist.m3u` qua HTTP, và hẹn giờ chạy
scraper mỗi giờ giống GitHub Actions.

## Yêu cầu

- VPS chạy **Ubuntu 20.04+** hoặc **Debian 11+**
- Quyền `root` (hoặc `sudo`)
- Nếu VPS ở ngoài Việt Nam: cần proxy VN (xem bên dưới)

## Cài đặt nhanh (1 lệnh)

```bash
curl -fsSL https://raw.githubusercontent.com/Bacbenny/Footyfootball/main/deploy/install.sh | sudo bash
```

## Cài đặt với tuỳ chọn

```bash
# VPS ngoài VN — cần proxy
sudo VN_PROXY="http://user:pass@proxy-vn.example.com:8080" \
     bash deploy/install.sh

# Đổi cổng HTTP
sudo HTTP_PORT=9000 bash deploy/install.sh

# Dùng token FPT Play (mở thêm kênh)
sudo USER_TOKEN="token_cua_ban" FPT_USE_USER_TOKEN=true \
     bash deploy/install.sh

# Kết hợp tất cả
sudo VN_PROXY="http://user:pass@host:8080" \
     USER_TOKEN="xxx" FPT_USE_USER_TOKEN=true \
     HTTP_PORT=9000 \
     bash deploy/install.sh
```

## Cài đặt từ mã nguồn đã clone

```bash
git clone https://github.com/Bacbenny/Footyfootball.git
cd Footyfootball
sudo bash deploy/install.sh
```

## Kết quả sau cài đặt

| Thành phần | Vị trí |
|---|---|
| Thư mục cài đặt | `/opt/footyfootball` |
| Virtualenv | `/opt/footyfootball/venv` |
| File .env | `/opt/footyfootball/.env` (chmod 600) |
| HTTP server | systemd service `footyfootball-web` |
| Scraper timer | systemd timer `footyfootball-scraper` (mỗi giờ) |
| User dịch vụ | `footy` (system user, không login) |

## URL danh sách phát

```
http://<IP-VPS>:8000/playlist.m3u
```

Nhập URL này vào VLC / Kodi / IPTV player trên TV hoặc điện thoại.

## Lệnh quản lý

```bash
# Xem trạng thái
systemctl status footyfootball-web
systemctl status footyfootball-scraper

# Xem log realtime
journalctl -u footyfootball-scraper -f
journalctl -u footyfootball-web -f

# Chạy scraper ngay (không đợi timer)
sudo systemctl start footyfootball-scraper

# Khởi động lại HTTP server
sudo systemctl restart footyfootball-web

# Xem danh sách timer
systemctl list-timers footyfootball-scraper
```

## Đổi cấu hình sau khi cài

Sửa file `/opt/footyfootball/.env`, rồi chạy lại scraper:

```bash
sudo nano /opt/footyfootball/.env
sudo systemctl start footyfootball-scraper
```

## Mở từ ngoài Internet

Mặc định chỉ truy cập được trong mạng nội bộ. Để mở từ ngoài:

**Cách 1 — Port forwarding (đơn giản, ít an toàn):**
- Mở port `8000` trên router về IP VPS
- Truy cập: `http://<IP-công-khai>:8000/playlist.m3u`

**Cách 2 — Cloudflare Tunnel (an toàn, miễn phí):**
```bash
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list
sudo apt update && sudo apt install cloudflared
cloudflared tunnel --url http://localhost:8000
```
Cloudflare sẽ cấp một URL HTTPS tạm — dùng URL đó cho VLC/Kodi.

**Cách 3 — Tailscale (VPN riêng, an toàn nhất):**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
Truy cập qua IP Tailscale: `http://<tailscale-ip>:8000/playlist.m3u`

## Gỡ cài đặt

```bash
sudo bash /opt/footyfootball/deploy/uninstall.sh
# hoặc
sudo bash deploy/uninstall.sh
```

## Khắc phục sự cố

| Lỗi | Nguyên nhân | Cách sửa |
|---|---|---|
| 403 Forbidden | IP ngoài VN | Đặt `VN_PROXY` trong `.env` |
| playlist.m3u rỗng | API thay đổi | Xem `journalctl -u footyfootball-scraper -e` |
| Port 8000 bị chiếm | Dịch vụ khác dùng port | Đặt `HTTP_PORT=9000` rồi cài lại |
| curl_cffi cài lỗi | Thiên nhiên Python cũ | Cài Python 3.10+ |
| Scraper không chạy | Timer chưa enable | `systemctl enable --now footyfootball-scraper.timer` |
