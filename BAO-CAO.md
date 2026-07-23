# BÁO CÁO DỰ ÁN: HỆ THỐNG CÀO & XỬ LÝ VIDEO DOUYIN

> Hệ thống tự động **cào video → xử lý (rerender) → quản lý**, có 3 lớp giao diện (web, Flet, dòng lệnh) và trợ lý AI. Dựa trên mã nguồn mở [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler). **Phục vụ học tập, phi thương mại.**

---

## 1. Mục tiêu

Xây dựng một công cụ hoàn chỉnh cho người dùng không biết lập trình:
- **Cào video** Douyin (và Bilibili/Xiaohongshu/Weibo) theo nhiều cách.
- **Tự động hoá**: theo dõi kênh, hẹn giờ, render hàng loạt — chạy nền không cần can thiệp.
- **Xử lý video** (reup): đổi "vân tay" để tránh trùng nguồn.
- **Giao diện đẹp** (dashboard web) + **trợ lý AI** điều khiển bằng tiếng Việt.

## 2. Công nghệ sử dụng

| Thành phần | Vai trò |
|------------|---------|
| **Python 3.11** (quản lý bởi `uv`) | Ngôn ngữ chính |
| **MediaCrawler** | Lõi cào dữ liệu nền tảng |
| **Playwright (Chromium)** | Trình duyệt tự động: đăng nhập + ký request |
| **Node.js** | Chạy JS ký chữ ký `a_bogus` của Douyin |
| **FFmpeg** (Gyan 8.1.1) | Cắt/lật/chèn logo/trộn nhạc/tái mã hóa video |
| **Flet** | Giao diện desktop hiện đại (Material Design) |
| **HTTP server / FastAPI + HTML/CSS** | Giao diện web dashboard |
| **tkinter** | Giao diện cũ (lưu trữ trong `_cu/`) |
| **Groq AI (Llama 3.3)** | Trợ lý AI điều khiển tool bằng hội thoại |
| **faster-whisper + Google Translate** | Tạo phụ đề tiếng Việt |
| **Windows Task Scheduler** | Hẹn giờ / theo dõi định kỳ / tự khởi động |

## 3. Kiến trúc & các thành phần

```
reupo douyin+/
├─ MediaCrawler/              # Lõi cào (đã tùy chỉnh)
├─ GIAO DIỆN
│   ├─ cao_video_flet.py      # GUI Flet hiện đại (chạy desktop hoặc web :8560)
│   ├─ web_app.py / web_server.py + web/   # Dashboard web (HTML/CSS)
│   └─ _cu/                    # GUI tkinter cũ (lưu trữ)
├─ CÀO & TỰ ĐỘNG
│   ├─ mo_trinh_duyet.py      # Mở trình duyệt để đăng nhập sẵn
│   ├─ theo_doi.py            # Theo dõi kênh, tải video mới định kỳ
│   ├─ chay_tu_dong.py        # Cào theo lịch (hẹn giờ)
│   ├─ doi_ten_kenh.py        # Thêm tên tiếng Anh cho thư mục kênh
│   └─ sap_xep_lai.py         # Sắp xếp lại video cũ vào cấu trúc mới
├─ XỬ LÝ
│   ├─ xu_ly_video.py + xu_ly_config.json  # Pipeline FFmpeg (reup)
│   ├─ phu_de.py              # Tạo phụ đề .srt (nhận giọng + dịch)
│   ├─ groq_ai.py + ai_system.md           # Trợ lý AI (function calling)
│   ├─ tao_icon.py, tao_watermark_mau.py   # Tạo tài nguyên mẫu
├─ LAUNCHER (.bat)            # CAI-DAT, CAO-VIDEO, WEB-UI, XU-LY-VIDEO,
│                             # CAI-TU-DONG, TAT-TU-DONG, render_nen...
└─ TÀI LIỆU                   # HUONG-DAN.md, BAO-CAO.md
```

## 4. Các chức năng chính

### 4.1. Cào video
- **Theo từ khóa**: lọc Sắp xếp (Liên quan / Nhiều like nhất / Mới nhất) + Thời gian (1 ngày/tuần/6 tháng) → lấy "video hot theo chủ đề".
- **Theo link**: dán nhiều link cùng lúc.
- **Theo kênh**: nhiều kênh, chọn **Mới nhất** hoặc **Nhiều like nhất** + số lượng.
- **Chạy ẩn (headless)** khi đã đăng nhập sẵn.

### 4.2. Gợi ý kênh
- Tìm kênh theo từ khóa → **xếp hạng theo lượt follow** (card avatar + tên + follow/like/video) → chọn → đưa sang Cào / Theo dõi / Cả hai.

### 4.3. Theo dõi & Hẹn giờ (tự động)
- **Theo dõi kênh**: kiểm tra định kỳ (vd 30 phút), **chỉ tải video MỚI** (sổ ledger chống tải lại).
- **Hẹn giờ**: cào tự động mỗi ngày qua Task Scheduler.
- **Render tự khởi động cùng Windows** → pipeline reup chạy nền liên tục.

### 4.4. Xử lý video (reup)
Pipeline FFmpeg: cắt đầu/cuối · lật ngang · chèn logo · trộn nhạc nền · **tăng tốc 1.1x** · chỉnh màu · tái mã hóa H.264 → giữ bản đẹp, xóa bản gốc. Tự dừng khi ổ đầy.

### 4.5. Dịch & Trợ lý AI
- **Dịch Việt ⇄ Trung** (giản thể/phồn thể) + gợi ý từ thay thế, có "nghĩa ngược" để kiểm chứng.
- **Trợ lý AI (Groq/Llama)**: ra lệnh bằng tiếng Việt ("tải video review phim"), AI tự gọi đúng chức năng.
- **Phụ đề**: nhận giọng tiếng Trung → dịch tiếng Việt → xuất `.srt`.

### 4.6. Giao diện web (dashboard)
Sidebar · 4 thẻ thống kê (số liệu thật) · thẻ nền tảng (logo thật) · chip từ khóa · **File đã tải** (preview video + lọc theo ngày/kênh/từ khóa) · theme sáng/tối.

## 5. Sản phẩm đầu ra

- **Video MP4 (H.264, có tiếng, tối đa 1080p)** — chia thư mục `videos/tu-khoa|kenh|link/...`, tên theo tiêu đề.
- **Bản đã reup** trong `processed_videos/` (giữ cấu trúc).
- **Dữ liệu JSONL**: tiêu đề, tác giả, like/share/comment, link...
- **Phụ đề .srt** (tùy chọn).

## 6. Các vấn đề kỹ thuật đã xử lý

| Vấn đề | Giải pháp |
|--------|-----------|
| `uv` lỗi 403 (mirror TQ) | Đổi sang pypi.org |
| Trình duyệt đóng ngay (CDP xung đột) | Chuyển Playwright tiêu chuẩn |
| `UnicodeEncodeError cp1252` khi ký a_bogus | Ép PyExecJS ghi file tạm UTF-8 |
| Xung đột hồ sơ trình duyệt | Tự dọn Chromium sót trước khi cào |
| Tải video 403 (chống hotlink) | Gửi header + thử nhiều link CDN |
| Tải lại vô tận sau khi xóa bản gốc | Sổ ledger ghi nhớ ID đã tải |
| Douyin không có API tìm kênh | Lấy tác giả từ video → tra follow → xếp hạng |
| Logo nền tảng | Dùng ảnh logo thật do người dùng cung cấp |

## 7. Giới hạn & lưu ý

- **Bắt buộc đăng nhập** (quét QR 1 lần) — các nền tảng chặn bot, không cào ẩn danh được.
- **Theo dõi không tức thời** (Douyin không push → kiểm tra định kỳ); cào quá dày dễ bị **hạn chế tài khoản (风控)** → nên dùng nick phụ.
- Video có thể còn **watermark** của nền tảng.
- Video review phim **rất nặng** (150–450MB) → cào + render tốn thời gian/ổ cứng.

---

## ⚠️ Đây là dự án HỌC TẬP

Dự án được thực hiện **hoàn toàn cho mục đích học tập và nghiên cứu** (tìm hiểu web scraping, tự động hoá, xử lý video bằng FFmpeg, xây dựng giao diện, tích hợp AI). **Không sử dụng cho mục đích thương mại.** Mã nguồn nền (MediaCrawler) có giấy phép chỉ cho phép học tập. Video tải về thuộc bản quyền của tác giả gốc — người dùng tự chịu trách nhiệm tuân thủ điều khoản của các nền tảng và quy định pháp luật.
