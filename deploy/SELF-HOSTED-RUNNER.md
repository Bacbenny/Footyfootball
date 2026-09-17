# Chạy Footyfootball trên máy tính cá nhân (Self-hosted Runner)

Hướng dẫn này giúp bạn dùng máy tính ở nhà (Windows, macOS, hoặc Linux) làm runner cho GitHub Actions. Vì máy tính có IP Việt Nam, FPT Play sẽ không chặn 403, và playlist tự động đẩy lên GitHub repo `Footyfootball`.

## Tổng quan

```
  Máy tính của bạn (IP VN)
    │
    ├── GitHub Actions self-hosted runner
    │     (chạy scraper mỗi giờ)
    │
    └── Tự động commit playlist.m3u → GitHub repo Footyfootball
```

## Bước 1: Cài Python

### Windows
1. Tải Python tại https://www.python.org/downloads/
2. Khi cài, **tích chọn "Add Python to PATH"**
3. Mở Command Prompt, kiểm tra:
   ```
   python --version
   ```

### macOS
```bash
brew install python@3
```

### Linux (Ubuntu/Debian)
```bash
sudo apt update && sudo apt install python3 python3-pip -y
```

## Bước 2: Đăng ký self-hosted runner trên GitHub

1. Mở trình duyệt, vào repo **Footyfootball** trên GitHub
2. Vào **Settings → Actions → Runners → New self-hosted runner**
3. Chọn hệ điều hành khớp với máy tính của bạn (Windows / macOS / Linux)
4. GitHub sẽ hiển thị các lệnh cài đặt — **copy và chạy lần lượt trên máy tính**

### Ví dụ (Windows):
```cmd
mkdir actions-runner
cd actions-runner
:: Tải file runner (link GitHub cung cấp)
curl -o actions-runner-win-x64-2.xxx.tar.gz -L https://github.com/actions/runner/releases/download/v2.xxx/actions-runner-win-x64-2.xxx.tar.gz
tar xzf actions-runner-win-x64-2.xxx.tar.gz
:: Cấu hình runner (token GitHub cung cấp)
./config.cmd --url https://github.com/Bacbenny/Footyfootball --token XXXXXXXXXXX
:: Cài đặt dịch vụ nền
./run.cmd
```

### Ví dụ (Linux/macOS):
```bash
mkdir actions-runner && cd actions-runner
curl -o actions-runner-osx-x64-2.xxx.tar.gz -L https://github.com/actions/runner/releases/download/v2.xxx/actions-runner-osx-x64-2.xxx.tar.gz
tar xzf actions-runner-osx-x64-2.xxx.tar.gz
./config.sh --url https://github.com/Bacbenny/Footyfootball --token XXXXXXXXXXX
./run.sh
```

Khi GitHub hỏi nhãn (label), đặt tên là: **`self-hosted`** (mặc định).

## Bước 3: Cài runner chạy nền tự động (không cần mở terminal)

### Windows — cài dịch vụ Windows:
```cmd
./svc.cmd install
./svc.cmd start
```

### Linux — cài systemd service:
```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

### macOS — cài launchd service:
```bash
./svc.sh install
./svc.sh start
```

Sau bước này, runner sẽ chạy nền 24/7, không cần mở terminal.

## Bước 4: Cấu hình biến GitHub Secrets

Vào repo **Footyfootball → Settings → Secrets and variables → Actions → New repository secret**:

| Tên secret | Giá trị | Bắt buộc? |
|---|---|---|
| `USE_TOKEN` | Token FPT Play của bạn | Có (nếu dùng token) |
| `VN_PROXY` | Để trống (máy VN không cần) | Không |

**Không cần `VN_PROXY`** vì máy tính của bạn đã ở VN.

## Bước 5: (Tuỳ chọn) Đổi nhãn runner trong workflow

Workflow đã được cập nhật để tự động dùng self-hosted runner. Nếu bạn muốn chỉ chạy trên máy tính của mình (không bao giờ dùng GitHub-hosted), vào **Settings → Variables → Actions → New variable**:

- Tên: `RUNNER_LABEL`
- Giá trị: `self-hosted`

Khi đó workflow sẽ **chỉ** chạy trên máy tính của bạn.

## Bước 6: Kiểm tra

1. Vào repo **Footyfootball → Actions**
2. Chọn workflow **"Update FPT event playlist"**
3. Bấm **"Run workflow"** → **"Run workflow"**
4. Xem log — nếu runner của bạn nhận job, bạn sẽ thấy:
   ```
   Runner name: <tên máy tính của bạn>
   ```
5. Sau khi chạy xong, kiểm tra repo có file `playlist.m3u` mới

## Mở playlist trên TV / điện thoại

Sau khi workflow chạy thành công, playlist URL là:

```
https://raw.githubusercontent.com/Bacbenny/Footyfootball/main/playlist.m3u
```

Nhập URL này vào VLC, Kodi, hoặc IPTV player.

## Lệnh quản lý runner

### Windows
```cmd
:: Xem trạng thái
./svc.cmd status
:: Dừng
./svc.cmd stop
:: Khởi động lại
./svc.cmd start
:: Gỡ cài đặt
./svc.cmd uninstall
```

### Linux
```bash
sudo ./svc.sh status
sudo ./svc.sh stop
sudo ./svc.sh start
sudo ./svc.sh uninstall
```

### macOS
```bash
./svc.sh status
./svc.sh stop
./svc.sh start
./svc.sh uninstall
```

## Khắc phục sự cố

| Lỗi | Nguyên nhân | Cách sửa |
|---|---|---|
| Workflow chạy trên `ubuntu-latest` thay vì máy bạn | Chưa đặt variable `RUNNER_LABEL` | Vào Settings → Variables → Actions, thêm `RUNNER_LABEL=self-hosted` |
| Runner offline | Máy tính tắt hoặc mất mạng | Bật máy, kiểm tra Internet, chạy lại `./svc.cmd start` |
| Runner không nhận job | Nhãn không khớp | Đảm bảo runner có nhãn `self-hosted` |
| Python không tìm thấy | Chưa thêm vào PATH | Cài lại Python, tích "Add to PATH" |
| `pip install` lỗi | Quyền hạn | Windows: chạy CMD as Administrator; Linux: thêm `--user` |
| Playlist rỗng | API FPT Play thay đổi | Xem log trong Actions tab |
| 403 Forbidden | IP ngoài VN | Máy tính phải ở VN, hoặc cấu hình `VN_PROXY` |

## So sánh: Self-hosted runner vs VPS cloud

| | Máy tính cá nhân | VPS cloud |
|---|---|---|
| Chi phí | Miễn phí | ~100k-300k/tháng |
| IP Việt Nam | Có (nếu ở VN) | Cần chọn VPS VN |
| Chạy 24/7 | Chỉ khi máy bật | Luôn |
| Bảo trì | Tự bạn quản lý | Nhà cung cấp quản lý |
| Phù hợp | Có máy tính luôn bật | Cần ổn định 24/7 |
