# Footyfootball

Playlist IPTV bóng đá được cập nhật tự động bằng GitHub Actions.

## Cách hoạt động

- Lấy lịch bóng đá và thông tin đội từ API công khai được `OgBek/footyLive` sử dụng.
- Ưu tiên stream từ WatchFooty, sau đó thử CDNLiveTV và Streamed.pk khi nguồn trước không có link.
- Mỗi trận chỉ xuất **một stream duy nhất**. Bộ chọn ưu tiên FHD/1080p, sau đó HD/720p, rồi SD; HLS (`.m3u8`) được ưu tiên khi chất lượng ngang nhau.
- Playlist chính chỉ nhận URL media trực tiếp (`.m3u8`, `.mpd`, `.mp4`, `.ts`) hoặc URL embed có thể phân giải thành manifest media. Với trận LIVE, workflow dùng Chromium để bắt request media mà player thực sự tải; trang HTML embed không còn bị coi là nguồn IPTV hợp lệ.
- Tiêu đề dùng múi giờ Việt Nam (Asia/Ho_Chi_Minh), theo dạng `HH:MM:SS - DD/MM | Đội nhà VS Đội khách | Giải đấu`, giống mẫu trình phát.
- Tất cả chương trình dùng chung nhóm `FoottyLive`.
- Với trận đang diễn ra, workflow kiểm tra manifest/video trực tiếp. Các chương trình không có media trực tiếp được ghi rõ trong `output/footyfootball-unavailable.json` thay vì đưa link HTML lỗi vào playlist.
- Playlist được ghi tại `output/footyfootball.m3u`; metadata dễ kiểm tra nằm tại `output/footyfootball.json`.
- `output/footyfootball-unavailable.json` giải thích các trận có upstream metadata nhưng chưa có URL IPTV trực tiếp.

## Tự động cập nhật

Workflow chạy mỗi 15 phút, đồng thời có thể chạy thủ công từ tab **Actions**. Workflow sẽ commit playlist mới nếu dữ liệu thay đổi.

Raw playlist sau khi repo được tạo:

```text
https://raw.githubusercontent.com/Bacbenny/Footyfootball/main/output/footyfootball.m3u
```

## Chạy thủ công

Yêu cầu Node.js 20 trở lên:

```bash
npm install
npx playwright install chromium
npm run generate
```

## Lưu ý

Repo này chỉ tổng hợp metadata và các URL do nguồn bên ngoài cung cấp; không lưu trữ hay phát nội dung video. Chỉ sử dụng các nguồn stream mà bạn có quyền truy cập và tuân thủ pháp luật cũng như điều khoản của nhà cung cấp.