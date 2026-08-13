# Footyfootball

Playlist IPTV bóng đá được cập nhật tự động bằng GitHub Actions.

## Cách hoạt động

- Lấy lịch bóng đá và thông tin đội từ API công khai được `OgBek/footyLive` sử dụng.
- Ưu tiên stream từ WatchFooty, sau đó thử CDNLiveTV và Streamed.pk khi nguồn trước không có link.
- Mỗi trận chỉ xuất **một stream duy nhất**. Bộ chọn ưu tiên FHD/1080p, sau đó HD/720p, rồi SD; HLS (`.m3u8`) được ưu tiên khi chất lượng ngang nhau.
- Tiêu đề dùng múi giờ Việt Nam (Asia/Ho_Chi_Minh), theo dạng `HH:MM:SS - DD/MM | Đội nhà VS Đội khách | Giải đấu`, giống mẫu trình phát.
- Tất cả chương trình dùng chung nhóm `FoottyLive`.
- Với trận đang diễn ra, workflow kiểm tra khả năng truy cập của các ứng viên stream và bỏ trận nếu không còn link hoạt động.
- Playlist được ghi tại `output/footyfootball.m3u`; metadata dễ kiểm tra nằm tại `output/footyfootball.json`.

## Tự động cập nhật

Workflow chạy mỗi 15 phút, đồng thời có thể chạy thủ công từ tab **Actions**. Workflow sẽ commit playlist mới nếu dữ liệu thay đổi.

Raw playlist sau khi repo được tạo:

```text
https://raw.githubusercontent.com/Bacbenny/Footyfootball/main/output/footyfootball.m3u
```

## Chạy thủ công

Yêu cầu Node.js 20 trở lên:

```bash
npm run generate
```

## Lưu ý

Repo này chỉ tổng hợp metadata và các URL do nguồn bên ngoài cung cấp; không lưu trữ hay phát nội dung video. Chỉ sử dụng các nguồn stream mà bạn có quyền truy cập và tuân thủ pháp luật cũng như điều khoản của nhà cung cấp.