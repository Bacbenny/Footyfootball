# Dùng máy tính cá nhân làm máy chủ playlist

Tài liệu runner GitHub cũ không còn khớp với cấu hình hiện tại. Workflow `.github/workflows/update.yml` chỉ chạy kiểm thử; nó không tạo hay commit playlist. `playlist.m3u` được loại khỏi Git và được tạo cục bộ trên máy chạy scraper để tránh công khai các URL phát có thể hết hạn hoặc phụ thuộc quyền truy cập.

## Vị trí playlist

Với cài đặt mặc định, file nằm trên máy chủ tại:

```text
/opt/footyfootball/playlist.m3u
```

`footyfootball-scraper.service` là tác vụ chạy một lần: nó ghi playlist rồi dừng bình thường. `footyfootball-web.service` là dịch vụ riêng phục vụ file trên cổng 8000.

## Kiểm tra máy chủ và playlist

```bash
sudo systemctl is-active footyfootball-web.service
sudo grep -c '^#EXTINF:' /opt/footyfootball/playlist.m3u
curl -I http://127.0.0.1:8000/playlist.m3u
```

Web service cần báo `active`, số mục playlist phải lớn hơn 0, và `curl` cần nhận HTTP `200`.

## Mở playlist

- Trên chính máy chủ: `http://127.0.0.1:8000/playlist.m3u`
- Trên TV/điện thoại cùng Wi-Fi: lấy IP nội bộ bằng `hostname -I | awk '{print $1}'`, rồi mở `http://<IP_LAN>:8000/playlist.m3u`.
- Trong VLC, chọn **Open Network Stream** rồi nhập URL phù hợp.

HTTP server mặc định không có đăng nhập. Không chuyển tiếp công khai cổng 8000 từ router ra Internet như cấu hình hiện tại; nếu cần truy cập bên ngoài mạng nhà, hãy dùng VPN riêng hoặc thêm lớp xác thực trước khi mở truy cập.

Xem hướng dẫn cài đặt và xử lý firewall tại [README.md](README.md).
