# Triển khai Footyfootball trên VPS — phương án A

Theo phương án này, VPS tự lấy dữ liệu FPT Play, tạo `playlist.m3u` và phục vụ playlist qua HTTP. GitHub chỉ dùng để lưu mã nguồn và chạy unit test; GitHub Actions **không** tạo hoặc commit playlist.

## 1. Yêu cầu

- Ubuntu 20.04+ hoặc Debian 11+.
- Quyền `root` hoặc `sudo`.
- VPS có kết nối Internet.
- Nếu VPS không có IP Việt Nam: một proxy HTTP/HTTPS có IP Việt Nam.
- Mở cổng HTTP đã chọn trong firewall/security group của VPS. Mặc định là `8000`.

Kiểm tra hệ điều hành:

```bash
cat /etc/os-release
```

## 2. Cài đặt nhanh từ GitHub

Nếu VPS có IP Việt Nam, chạy:

```bash
curl -fsSL https://raw.githubusercontent.com/Bacbenny/Footyfootball/main/deploy/install.sh | sudo bash
```

Lệnh này cài Python, virtualenv, thư viện, systemd service, systemd timer và HTTP server. Script sẽ chạy scraper ngay lần đầu. Nếu API không truy cập được hoặc playlist không hợp lệ, script dừng và in log lỗi.

## 3. Cài đặt từ bản clone

Cách này phù hợp khi muốn xem hoặc chỉnh mã nguồn trước khi cài:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/Bacbenny/Footyfootball.git
cd Footyfootball
sudo bash deploy/install.sh
```

Không chạy `chmod +x install.sh` trong thư mục bất kỳ. File đúng là `deploy/install.sh`. Nếu đang ở thư mục gốc repository:

```bash
sudo chmod +x deploy/install.sh
sudo bash deploy/install.sh
```

## 4. Cấu hình proxy hoặc token sau khi cài

Installer tạo file:

```text
/opt/footyfootball/.env
```

Mở file:

```bash
sudo nano /opt/footyfootball/.env
```

Nếu VPS có IP Việt Nam, để proxy trống:

```env
VN_PROXY=
USER_TOKEN=
FPT_USE_USER_TOKEN=false
```

Nếu VPS ngoài Việt Nam, điền proxy có IP Việt Nam. Không đặt token hoặc mật khẩu trực tiếp vào GitHub workflow:

```env
VN_PROXY=http://user:password@proxy-host:port
```

Nếu cần dùng token FPT Play:

```env
USER_TOKEN=token_cua_ban
FPT_USE_USER_TOKEN=true
```

Giới hạn quyền file và chạy lại:

```bash
sudo chown footy:footy /opt/footyfootball/.env
sudo chmod 600 /opt/footyfootball/.env
sudo systemctl start footyfootball-scraper.service
```

## 5. Kiểm tra sau cài đặt

Kiểm tra file:

```bash
sudo ls -lh /opt/footyfootball/playlist.m3u
sudo head -20 /opt/footyfootball/playlist.m3u
```

Playlist hợp lệ phải có `#EXTM3U` và ít nhất một dòng `#EXTINF:`.

Kiểm tra service HTTP:

```bash
sudo systemctl status footyfootball-web.service --no-pager
curl -I http://127.0.0.1:8000/playlist.m3u
```

Kết quả cần có HTTP `200 OK`.

Kiểm tra timer:

```bash
systemctl list-timers footyfootball-scraper.timer
sudo systemctl status footyfootball-scraper.timer --no-pager
```

Chạy scraper ngay, không cần chờ timer:

```bash
sudo systemctl start footyfootball-scraper.service
```

Xem log:

```bash
sudo journalctl -u footyfootball-scraper.service -n 100 --no-pager
sudo journalctl -u footyfootball-web.service -n 50 --no-pager
```

## 6. Mở playlist từ điện thoại, TV hoặc VLC

Trên chính VPS, lấy IP công khai:

```bash
curl -4 https://ifconfig.me
```

URL playlist mặc định:

```text
http://IP_PUBLIC_VPS:8000/playlist.m3u
```

Mở port trên Ubuntu UFW nếu đang bật:

```bash
sudo ufw allow 8000/tcp
sudo ufw status
```

Nếu nhà cung cấp VPS có firewall/security group riêng, cũng phải mở TCP `8000` ở bảng điều khiển nhà cung cấp.

Kiểm tra từ một máy khác:

```bash
curl -I http://IP_PUBLIC_VPS:8000/playlist.m3u
```

Nếu `127.0.0.1` trên VPS trả `200` nhưng máy ngoài không truy cập được, lỗi nằm ở firewall hoặc security group, không phải scraper.

## 7. Cập nhật code

Installer đã đặt script cập nhật tại:

```bash
sudo bash /opt/footyfootball/update.sh
```

Script sẽ:

1. tải `scraper.py` và test mới nhất;
2. chạy unit test;
3. chạy scraper;
4. chỉ kết thúc thành công khi playlist vẫn hợp lệ;
5. giữ nguyên `.env` và playlist cũ nếu bước mới thất bại.

## 8. Tác vụ tự động

Timer chạy khoảng mỗi giờ:

```bash
systemctl list-timers footyfootball-scraper.timer
```

Sau khi scraper thành công, playlist cũ được thay thế nguyên tử. Nếu FPT API trả 403, timeout hoặc không có stream, playlist cũ không bị xoá.

## 9. Khắc phục sự cố

### `403 Forbidden`

Xem log:

```bash
sudo journalctl -u footyfootball-scraper.service -n 100 --no-pager
```

Nếu VPS ngoài Việt Nam, kiểm tra `VN_PROXY` trong `.env`. Proxy phải hoạt động từ chính VPS và có IP Việt Nam. Không dùng proxy đã hết hạn.

### Không có file playlist

Chạy:

```bash
sudo systemctl start footyfootball-scraper.service
sudo journalctl -u footyfootball-scraper.service -n 100 --no-pager
```

Không tạo file playlist rỗng để che lỗi. Cần sửa lỗi API/proxy rồi chạy lại.

### HTTP trả `404`

Kiểm tra file và thư mục làm việc:

```bash
sudo ls -lh /opt/footyfootball/playlist.m3u
sudo systemctl cat footyfootball-web.service
```

### Port đã được sử dụng

```bash
sudo ss -ltnp | grep ':8000'
```

Cài lại với port khác:

```bash
sudo HTTP_PORT=9000 bash deploy/install.sh
```

## 10. Gỡ cài đặt

```bash
sudo bash /opt/footyfootball/uninstall.sh
```

Lệnh này dừng service, xoá timer, xoá thư mục cài đặt và xoá user `footy`. File trong repository GitHub không bị xoá.