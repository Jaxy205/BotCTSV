# Bot Theo Dõi Fanpage CTSV HUIT (Săn Slot CTXH)

Hệ thống bot tự động theo dõi fanpage [CTSV HUIT](https://www.facebook.com/ctsv.huit) và gửi thông báo tức thì về Telegram khi có bài viết mới hoặc form đăng ký CTXH.

## 🚀 Tính năng nổi bật
1. **Quét tự động**: Mặc định 2 phút/lần (có thể tùy chỉnh).
2. **Tự động bóc tách Link Form**: Phát hiện link Google Form, Microsoft Form... và đặt nút bấm mở form trực tiếp trên Telegram để bấm điền ngay lập tức.
3. **Chống trùng lặp**: Ghi nhớ bài viết đã gửi qua `seen_posts.json`.
4. **Chuông cảnh báo ưu tiên**: Tự động nhận diện từ khóa `CTXH`, `công tác xã hội`, `đăng ký` để gắn cờ báo động khẩn cấp 🚨.

---

## 🛠 Cách sử dụng hàng ngày
- Chỉ cần **nhấp đúp chuột vào file `run_bot.bat`**.
- Cửa sổ chạy ngầm sẽ tự động quét, khi có bài viết mới sẽ phát chuông báo trên Telegram của bạn.
- Khi không dùng nữa: Nhấn tổ hợp phím `Ctrl + C` hoặc đóng cửa sổ `run_bot.bat`.

---

## ⚙ Cấu hình (.env)
- `TELEGRAM_BOT_TOKEN`: Token bot tạo từ `@BotFather`.
- `TELEGRAM_CHAT_ID`: ID tài khoản Telegram nhận thông báo.
- `CHECK_INTERVAL_SECONDS`: Khoảng thời gian quét (mặc định: `120` giây = 2 phút).
