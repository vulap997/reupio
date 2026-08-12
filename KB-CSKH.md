# KB CHĂM SÓC KHÁCH HÀNG — reupo douyin+ (LLN-app)

> **Tài liệu tri thức (knowledge base) cho AI trả lời khách hàng.**
> Trả lời khách bằng **tiếng Việt**, thân thiện, ngắn gọn. Chỉ dùng thông tin trong file này; nếu không chắc thì hướng dẫn khách liên hệ Zalo hỗ trợ **0394.426.246**.
> Tên kỹ thuật của sản phẩm là `LLN-app`.
> Phiên bản hiện tại: **v1.3.7**. Chỉ chạy trên **Windows 10/11 (64-bit)**.

---

## 0. AI HỖ TRỢ CẦN NHỚ (quy tắc trả lời)

- Tên sản phẩm hiển thị: **reupo douyin+**. Tên kỹ thuật là **LLN-app** (LLN APP.exe, lln-app) — nếu khách thấy chữ "LLN-app" thì đó là **đúng sản phẩm**, không phải nhầm.
- Đây là **tool desktop cho Windows**, KHÔNG có app điện thoại, KHÔNG có bản web online. Khách hỏi "dùng trên điện thoại/Mac được không?" → **không**, chỉ Windows 10/11 64-bit.
- Nhiều lỗi "cào 0 video" là do **nền tảng chặn (anti-bot / hết phiên đăng nhập)**, KHÔNG phải lỗi tool. Luôn hướng khách kiểm tra đăng nhập trước.
- Khi khách muốn **mua/gia hạn/nâng cấp** → hướng tới Zalo **0394.426.246** hoặc tab **"Gói của tôi" → "Nâng Cấp Gói"** trong app.
- Không hứa tính năng chưa có. Không tư vấn cách lách giới hạn gói, crack, hay né bản quyền.

---

## 1. SẢN PHẨM LÀ GÌ

**reupo douyin+** là công cụ desktop giúp người **không biết lập trình** tự động:
1. **Cào (tải) video** từ nhiều nền tảng mạng xã hội.
2. **Dịch + làm phụ đề + lồng tiếng** tự động (chủ yếu tiếng Trung → tiếng Việt).
3. **Render "reup"**: xử lý lại video (cắt, lật, chèn logo, che phụ đề gốc, đổi khung 9:16, băm nhỏ...) để đăng lại.
4. **Tự động hóa**: theo dõi kênh, hẹn giờ cào, chạy cả quy trình tự động.

Giao diện hoàn toàn **tiếng Việt** (có thể chuyển tiếng Anh), mở bằng trình duyệt dạng dashboard.

---

## 2. NỀN TẢNG HỖ TRỢ

### Nền tảng ĐANG BẬT (khách dùng được ở v1.3.7)

| Nền tảng | Tải video | Cách cào | Ghi chú |
|----------|-----------|----------|---------|
| **Douyin** (TikTok TQ) | ✅ | Từ khóa, link, kênh | Cần đăng nhập (quét QR) |
| **Bilibili** | ✅ | Từ khóa, link, kênh | Cần đăng nhập (quét QR) |
| **Xiaohongshu (XHS nội địa)** | ✅ | Từ khóa, link | Cần đăng nhập; cả ảnh |
| **RedNote (XHS quốc tế)** | ✅ | Từ khóa, link | Nền tảng riêng, tách khỏi XHS |
| **YouTube** | ✅ | Từ khóa, kênh, link | Công khai, KHÔNG cần đăng nhập |
| **TikTok** | ✅ | Link, kênh | Công khai, KHÔNG cần đăng nhập |
| **Facebook** | ✅ | Link, kênh/Page | Nền tảng MỚI (v1.3.x) |

- Douyin/Bilibili/XHS/RedNote dùng engine MediaCrawler (trình duyệt tự động, **cần đăng nhập bằng QR 1 lần**).
- YouTube/TikTok/Facebook dùng yt-dlp (tải công khai, **không cần đăng nhập**).

### Nền tảng TẠM KHOÁ (đang ẩn trên UI, sẽ mở ở bản sau)

**Weibo, Twitter (X), Instagram, Reddit, Threads** — ở v1.3.7 các nút này **bị ẩn khỏi giao diện** ("chưa hoàn thiện, cập nhật ở bản sau"). Nếu khách hỏi cào được các nền tảng này không → trả lời **hiện chưa hỗ trợ trong bản này**, sẽ bổ sung ở bản cập nhật tới. Đừng hứa mốc thời gian.

---

## 3. GÓI CƯỚC & GIÁ (QUAN TRỌNG)

### 3.1. Các gói cước + bản dùng thử

Khi khách đăng ký tài khoản, tự động nhận **gói FREE = bản dùng thử 7 ngày**. Hết 7 ngày mà không nâng cấp → tài khoản chuyển sang trạng thái **"hết hạn dùng thử" (view-only)**: vẫn mở app xem được nhưng **mọi thao tác bị chặn**.

Sau khi hết hạn dùng thử, khách hàng có thể đăng ký các gói cước sau:

| Tính năng | FREE (dùng thử 7 ngày) | Gói Tháng (Cơ bản) | Gói Năm & Gói Vĩnh Viễn (Mở rộng) |
|-----------|------------------------|--------------------|-----------------------------------|
| **Giá bán** | Miễn phí | **299.000đ / tháng** | **999.000đ / năm** hoặc **1.799.000đ / Vĩnh viễn** |
| **Cào video / ngày** | **3** | Không giới hạn | Không giới hạn |
| **Lồng tiếng — số video/ngày** | **1** | **30 video** | **Không giới hạn** |
| **Lồng tiếng — tổng phút/ngày** | **1 phút** | **120 phút** | **Không giới hạn** |
| **Lồng tiếng — độ dài mỗi video** | ≤ 1 phút | ≤ 60 phút | Không giới hạn |
| **Giọng đọc nâng cao** | ❌ | ✅ | ✅ |
| **Clone giọng (tổng lượt)** | 0 | **5 lượt** | **Không giới hạn** |
| **Theo dõi kênh (số kênh)** | 0 | **5 kênh** | **Không giới hạn** |
| **Băm nhỏ video** | ❌ | ✅ | ✅ |
| **Quy trình tự động (Workflow)** | ❌ | ✅ | ✅ |
| **Trợ lý AI** | ❌ | ❌ | ✅ (Đầy đủ) |
| **Tài liệu & Quà tặng** | Không có | Video HDSD cơ bản | Video HDSD cơ bản + **Bộ 3 Quà Tặng Độc Quyền** (xem mục 3.3) |

**Lưu ý cho AI:** Giới hạn cào/lồng tiếng **reset lúc 00:00 mỗi ngày** (giờ máy). Lượt **clone giọng tính tích lũy** — clone xong rồi xóa vẫn bị trừ lượt.

### 3.2. Bảng giá & Kỳ hạn thanh toán

* **GÓI THÁNG (Tính năng Cơ bản):** **299.000đ / tháng**. Tặng kèm video hướng dẫn sử dụng cơ bản.
* **GÓI NĂM (Tính năng Mở rộng):** **999.000đ / năm**. Tặng kèm video hướng dẫn + **Bộ 3 Quà Tặng Độc Quyền**.
* **GÓI VĨNH VIỄN (Tính năng Mở rộng):** **1.799.000đ / trọn đời**. Tặng kèm video hướng dẫn + **Bộ 3 Quà Tặng Độc Quyền**.

### 3.3. Bộ quà tặng kèm độc quyền (Chỉ áp dụng khi mua Gói Năm và Gói Vĩnh Viễn)
Khi khách hàng mua Gói Năm hoặc Gói Vĩnh Viễn, họ sẽ được tặng kèm bộ tài liệu và quà tặng thực chiến giá trị bao gồm:
1. **Danh sách 20 kênh nội dung reup nổi tiếng bên Trung Quốc** để tham khảo ý tưởng, lấy nguồn video chất lượng cao làm tài liệu reup.
2. **Tài liệu & Video hướng dẫn cách upload tự động lên đa nền tảng** (Facebook Reels, TikTok, YouTube Shorts) giúp tối ưu hóa thời gian và quy trình làm MMO.
3. **Báo cáo Top 10 ngách reup ngon và dễ kiếm tiền nhất bên Trung Quốc** để định hướng nội dung nhanh chóng, tránh lãng phí thời gian thử sai.

### 3.4. Nên chọn gói nào?
* **Gói Tháng**: Dành cho khách dùng thử nghiệm dự án ngắn hạn, làm quen với tool.
* **Gói Năm**: Gói tiết kiệm, phù hợp cho người làm MMO lâu dài, ổn định, cần khai thác hết sức mạnh của tool bao gồm cả Trợ lý AI và các quà tặng thực chiến.
* **Gói Vĩnh Viễn**: Gói tối ưu chi phí nhất (bằng giá chưa đầy 2 năm sử dụng gói năm), mua một lần dùng trọn đời, được hỗ trợ cập nhật lâu dài và nhận đầy đủ bộ quà tặng kèm.

---

## 4. CÁCH MUA / NÂNG CẤP GÓI

1. Trong app: mở tab **"Gói của tôi"** → bấm **"Nâng Cấp Gói"** (hoặc tab **"Bảng Giá"** để so sánh).
2. Liên hệ **Zalo: 0394.426.246** để được cấp/kích hoạt gói.
3. Sau khi được cấp gói trên hệ thống, trong app bấm **"Làm mới gói"** (tab "Gói của tôi") để đồng bộ ngay — không cần cài lại, không cần khởi động lại máy.
4. Nếu bấm "Làm mới gói" báo **offline** → kiểm tra mạng rồi thử lại (app cần kết nối để đồng bộ gói với máy chủ).

**Gói hết hạn** → tự về mức thấp hơn (FREE/hết hạn), **app vẫn mở bình thường**, chỉ mất tính năng của gói cao. Gia hạn lại thì bấm "Làm mới gói".

---

## 5. MÔ HÌNH MÃ BẢN QUYỀN (LICENSE KEY)

- **1 mã kích hoạt = 1 máy**, và **1 máy = 1 mã kích hoạt** (ràng buộc 2 chiều). Nhập mã lần đầu tool sẽ **gắn mã kích hoạt với máy tính hiện tại**.
- Kích hoạt **1 lần**, sau đó tool nhớ phiên — các lần mở sau không cần nhập lại.
- **Dùng offline được tối đa 7 ngày** (grace) khi mất mạng; sau đó cần online để xác thực lại.

### Thông báo khách có thể gặp về license:
| Thông báo | Nghĩa & cách xử lý |
|-----------|--------------------|
| "**Mã kích hoạt này đã được gắn với một máy khác. Mỗi mã kích hoạt chỉ dùng được trên 1 máy.**" | Mã kích hoạt đã bị khóa vào máy khác. Muốn chuyển sang máy mới → liên hệ Zalo **0394.426.246** để admin **gỡ thiết bị** rồi kích hoạt lại trên máy mới. |
| "**Máy này đã được kích hoạt với một mã khác. Mỗi máy chỉ dùng được 1 mã kích hoạt.**" | Máy đã gắn mã kích hoạt khác. Dùng lại đúng mã cũ, hoặc nhờ admin gỡ thiết bị cũ. |
| "**Bản dùng thử FREE đã hết 7 ngày. Nâng cấp để tiếp tục thao tác.**" | Hết 7 ngày dùng thử → mua mã kích hoạt Gói Tháng/Năm/Vĩnh viễn để tiếp tục. |

> **Đổi máy / cài lại Windows / thay ổ cứng** có thể làm mã máy (HWID) đổi → mã kích hoạt không nhận diện được. Cách xử lý: liên hệ Zalo hỗ trợ để admin **gỡ thiết bị cũ trên Google Sheet (đổi active từ 1 thành 0 ở sheet Devices)**, sau đó khách nhập lại mã trên máy mới.

---

## 6. YÊU CẦU HỆ THỐNG

- **Windows 10 hoặc 11, 64-bit** (bắt buộc). Không hỗ trợ Mac, Linux, điện thoại.
- **RAM khuyến nghị ≥ 8 GB** (dùng phụ đề/lồng tiếng nặng hơn).
- Ổ cứng trống: video review phim rất nặng (150–450MB/video), nên cần ổ trống rộng.
- **GPU**: không bắt buộc. Có card **NVIDIA** thì render/nhận giọng nhanh hơn (tool tự dùng). Máy chỉ có CPU vẫn chạy được nhưng **lồng tiếng/render chậm hơn** — đây là điều bình thường, không phải lỗi.
- Node.js, FFmpeg, Python: **đã bundle sẵn trong bản cài** — khách không cần cài thủ công.

---

## 7. CÀI ĐẶT

### Bản cài (khuyến nghị cho khách)
1. Tải file **`ViralCrawl-Setup-1.3.7.exe`** (link từ nơi bán / Zalo hỗ trợ).
2. Chạy file cài → cài vào máy tự động.
3. **Lần đầu mở**: có màn hình **thiết lập tự động** (tải môi trường chạy + trình duyệt Chromium). Cần **mạng** và **đợi vài phút** — đây là bình thường, chỉ chạy 1 lần.
4. Tạo tài khoản (tự nhận gói FREE dùng thử) → vào tool.

### Cảnh báo SmartScreen (Windows Defender)
- Khi mở file cài, Windows có thể hiện **"Windows protected your PC"** vì installer **chưa ký số**.
- Cách qua: bấm **"More info"** (Thông tin thêm) → **"Run anyway"** (Vẫn chạy). Đây **không phải virus**, chỉ do chưa mua chứng chỉ ký số.

### Tự cập nhật
- Tool **tự kiểm tra & cập nhật** bản mới (electron-updater). Video đã cào và đã render **KHÔNG bị mất khi cập nhật** (lưu ngoài thư mục cài).

---

## 8. HƯỚNG DẪN DÙNG TỪNG CHỨC NĂNG

**Cấu trúc menu (thanh trái) v1.3.7:** ⚡ Tìm và tải video · ▶ Theo dõi kênh · 👤 Kênh nguồn (chỉ hiện khi có LLN Page) · 🔀 Quy trình · ✨ Trợ lý AI · 📁 File đã tải · 🎬 Đã render · 🕐 Lịch sử tải · 🎬 Render · ✂️ Băm nhỏ · 📤 Đăng bài · ⚙️ Cài đặt · 💎 Bảng Giá · 🎫 Gói của tôi. Đầu trang có **wizard 5 bước**: Đăng nhập → Chọn nền tảng → Cào video → Xem trước → Render & Đăng.
> Lưu ý: **"Lồng tiếng" không còn là menu riêng** (nằm trong tab Render); **"Theo dõi kênh" và "Hẹn giờ cào" đã gộp vào tab 🔀 Quy trình**.

### 8.1. Cào video
Chọn nền tảng → chọn cách cào → nhập nội dung → bấm **BẮT ĐẦU CÀO**. 3 cách:
- **🔍 Theo từ khóa**: gõ từ khóa (nhiều từ cách nhau dấu phẩy) + số lượng. Với Douyin có thêm **Sắp xếp** ("Nhiều like nhất (HOT)" / "Mới nhất") và **Thời gian** ("Trong 1 ngày/tuần/6 tháng") để lấy video hot theo chủ đề.
- **🔗 Theo link**: dán link video/bài viết, **mỗi dòng 1 link** (hỗ trợ link đầy đủ, link rút gọn, hoặc ID).
- **👤 Theo kênh**: dán link trang cá nhân + số lượng + chọn "Mới nhất" hoặc "Nhiều like nhất". Dán nhiều kênh, mỗi dòng 1 kênh.

**Mẹo tìm hiệu quả hơn (Douyin/Bilibili):** vì là nền tảng Trung Quốc, tìm bằng **tiếng Trung** ra nhiều kết quả hơn. Có nút **"🇨🇳 Dịch từ khóa sang tiếng Trung"** (giản thể + phồn thể) rồi điền vào ô tìm.

**Cào không trùng (Douyin):** tick **"Cào không trùng"** để bỏ qua video đã tải trước đó.

### 8.2. Xem trước & chọn
Nút **"Xem trước & chọn"**: liệt kê bài theo từ khóa/kênh (chỉ lấy thông tin, chưa tải) để **tick chọn** đúng bài muốn lấy rồi mới cào. Hỗ trợ XHS/Douyin/Bilibili.

### 8.3. Gợi ý kênh / gợi ý từ khóa
Trong tab **Tìm và tải video** có nút **"✨ Gợi ý"**: nhập từ khóa → tool tìm & **xếp kênh theo lượt follow** → tick chọn → đưa vào cào kênh hoặc theo dõi. (Chạy ~1–2 phút; cần đăng nhập sẵn.) Với Douyin/Bilibili còn có gợi ý **dịch từ khóa sang tiếng Trung** cho ra nhiều kết quả hơn.

### 8.4. Theo dõi kênh (PRO/UNLIMITED)
Nằm trong tab **🔀 Quy trình** (chọn Nguồn = Kênh → 👁 Theo dõi), hoặc menu **▶ Theo dõi kênh**. Tool kiểm tra kênh **định kỳ**, kênh nào có video mới thì tải ngay (bỏ qua video đã có). Đặt "Kiểm tra mỗi … phút" (khuyên 15–30). **Không tức thời** (nền tảng không báo mới, phải kiểm tra định kỳ). Cần **máy bật + đã đăng nhập**. FREE: 0 kênh; PRO: 3 kênh; UNLIMITED: không giới hạn.

### 8.5. Hẹn giờ cào tự động
Nằm trong tab **🔀 Quy trình** (chọn Nguồn = Cào/Kênh → ⏰ Hẹn giờ tự cào). Đặt **giờ chạy mỗi ngày** → Windows tự chạy tool cào vào giờ đó, kể cả khi không mở tool. Yêu cầu: máy **đang bật + đã đăng nhập Windows** vào giờ hẹn, và đã **đăng nhập nền tảng sẵn** (vì chạy ẩn/headless).

### 8.6. Render / Reup (tab "🎬 Render")
Pipeline xử lý lại video để đăng lại: **cắt đầu/cuối · lật ngang · chèn logo (ảnh hoặc chữ chạy) · che phụ đề gốc · tự dò & che watermark/logo nguồn (che bằng logo hoặc làm mờ) · trộn nhạc nền · tăng tốc 1.1x · chỉnh màu · đổi khung 9:16 nền mờ · băm nhỏ**. Tab Render chia 2 phần: **✂️ Edit** (chỉnh sửa) và **🎙 Lồng tiếng**. Giữ bản gốc, xuất bản đã xử lý.
- **Băm nhỏ (PRO/UNLIMITED)**: cắt video dài thành nhiều clip ngắn tại **ranh giới cảnh** (không giật), có thể đổi 9:16 luôn — cũng có menu riêng **✂️ Băm nhỏ**.
- **Ghép video**: gộp nhiều video thành 1 tập, đặt tên mới trực tiếp.
- **Video đã render** liệt kê ở menu **🎬 Đã render**; render nhiều lần ghi thành `(N)_xuly.mp4` (không đè bản cũ), có tag ngôn ngữ trên thẻ.

### 8.7. Dịch & Phụ đề
- **Nhận lời thoại gốc**: mặc định **"Đọc từ sub" (OCR)** — đọc thẳng phụ đề cứng trên video (chính xác nhất). Tùy chọn **"Giọng nói (ASR)"** = nhận dạng bằng Whisper (tự dùng GPU nếu có).
- **Dịch**: dùng **AI (Gemini)** cho render/lồng tiếng (đã bỏ Google dịch khỏi luồng này để chất lượng đồng đều, dùng từ điển tên riêng).
- **Từ điển/quy tắc dịch**: khách tự sửa ở ô "Cải thiện dịch" trong Cài đặt (tên riêng, thuật ngữ...).
- Dịch được **hơn 70 ngôn ngữ đích** (chọn ở "Ngôn ngữ đích"), không chỉ tiếng Việt.
- Xuất SRT tiếng gốc + SRT ngôn ngữ đích và bản video có phụ đề.

### 8.8. Lồng tiếng
Nằm ở tab **🎬 Render → sub-tab 🎙 Lồng tiếng** (KHÔNG còn là tab riêng). Trên UI khách chọn giọng dưới tên thương hiệu **"ViralVoice"** (khách KHÔNG thấy tên kỹ thuật Piper/edge…):
- **ViralVoice — Tiêu chuẩn (nhanh)** (mặc định) — giọng offline, chạy không cần mạng, không giới hạn. Giọng Việt mặc định **Ngọc Huyền (nữ)**; còn Mai Phương, Phương Trang, Thanh Phương (nữ), Mạnh Dũng, Minh Khang (nam).
- **ViralVoice — Clone giọng (cần GPU)** — nhân bản giọng từ mẫu (cần GPU NVIDIA).
- **ViralVoice — Online** — giọng cloud tự nhiên (cần mạng); mỗi ngôn ngữ có sẵn giọng Nam/Nữ.
- Hỗ trợ lồng tiếng **hơn 70 ngôn ngữ đích** (không chỉ Việt), chọn ở "Ngôn ngữ đích"; có thể bật nhiều ngôn ngữ đầu ra cùng lúc (mỗi ngôn ngữ 1 giọng).
- Có nút **"Xem trước lồng tiếng"** để nghe thử trước khi render toàn bộ.
- Tool tự **che phụ đề gốc** + **đè phụ đề đích** + tách nhạc nền (Demucs) để giữ nhạc mà thay lời.

> **Giới hạn theo gói:** FREE = 1 video ≤1 phút/ngày; PRO = 20 video hoặc 60 phút/ngày (mỗi video ≤60 phút); UNLIMITED = không giới hạn. Nếu vượt, phần vượt bị bỏ qua kèm thông báo — có thể **render KHÔNG lồng tiếng** hoặc **nâng cấp gói**.

### 8.9. Trợ lý AI (chỉ UNLIMITED)
Ra lệnh bằng tiếng Việt (vd "tải video review phim"), AI tự gọi đúng chức năng cào/tìm kênh. **Chỉ có ở gói UNLIMITED.**

### 8.10. Đăng bài / LLN Page (sản phẩm khác)
Tab **"Kênh nguồn"** và **"Đăng bài"** (tự động đăng lên Facebook Page qua LLN Page) thuộc **sản phẩm LLN Page riêng**. Khách phải **mua/mở khóa LLN Page** mới dùng được 2 tab này. Thông báo khi chưa có quyền: *"Tính năng này thuộc LLN Page — cần mua/mở khoá LLN Page để dùng Kênh nguồn & Đăng bài."*

---

## 9. ĐĂNG NHẬP NỀN TẢNG (QUÉT QR)

- **Lần đầu cào mỗi nền tảng TQ** (Douyin/Bili/XHS/RedNote), tool mở trình duyệt → khách **dùng app tương ứng trên điện thoại quét mã QR**. Các lần sau tự đăng nhập (đã lưu phiên riêng từng nền tảng).
- Có nút **"🌐 Đăng nhập trình duyệt"**: mở sẵn để đăng nhập trước mà không cần cào (dùng khi đăng nhập lần đầu hoặc khi phiên hết hạn).
- **QUAN TRỌNG:** khi cửa sổ trình duyệt mở ra để đăng nhập, **ĐỪNG tự đóng** cho tới khi quét QR xong và vào được trang. Đóng sớm = đăng nhập thất bại.
- YouTube/TikTok/Facebook: **không cần đăng nhập**.

---

## 10. VIDEO TẢI VỀ NẰM Ở ĐÂU

- Mặc định trong thư mục dữ liệu của tool (`MediaCrawler\data\<nền tảng>\videos\...`), chia theo cách cào: `tu-khoa\<từ khóa>\`, `kenh\<tên kênh>\`, `link\`.
- Video đã render nằm ở `processed_videos\` (hoặc tên `_xuly.mp4` cạnh gốc).
- Khách có thể **chọn ổ lưu bất kỳ** (C:, D:, E:...) ở tab **Cài đặt → "Thư mục lưu video"** (hiện đường dẫn + dung lượng trống + nút Đổi/Mở).
- **Video KHÔNG bị mất khi cập nhật tool** (lưu ngoài thư mục cài).
- Nút **"📂 Mở thư mục video"** để mở nhanh.

---

## 11. XỬ LÝ LỖI THƯỜNG GẶP (FAQ)

### A. Cào xong nhưng 0 video / 0 tệp
Nguyên nhân phổ biến (theo thứ tự kiểm tra):
1. **Phiên đăng nhập hết hạn** → thẻ đăng nhập chuyển đỏ → **đăng nhập lại (quét QR)** rồi cào lại.
2. **Nền tảng tạm chặn (anti-bot / giới hạn tần suất / 风控)** do cào nhiều/nhanh → **đợi vài phút** rồi thử lại, giảm số lượng, dùng nick phụ.
3. Từ khóa không ra kết quả → đổi/giảm từ khóa (thử từ khóa tiếng Trung).
> Thông báo tool hay hiện: *"⚠ Nền tảng trả 0 kết quả — ĐÂY KHÔNG PHẢI LỖI TOOL..."*. Trấn an khách: đây là nền tảng chặn tạm thời, không phải hỏng tool.

### B. Cửa sổ đăng nhập mở ra rồi tự đóng / "Đăng nhập chưa xong"
- Đừng tự đóng cửa sổ; quét QR, chờ vào được trang chủ mới đóng.
- Sau khi quét QR, nền tảng có thể bắt **xác minh thêm** (trượt captcha / số điện thoại) — làm theo trên trình duyệt rồi chạy lại.

### C. Thẻ đăng nhập báo xanh nhưng cào vẫn 0 video (hoặc ngược lại)
- Tool kiểm tra đăng nhập **trực tiếp (live)**. Nếu nghi ngờ, bấm **"🌐 Đăng nhập trình duyệt"** đăng nhập lại cho chắc, rồi cào.

### D. Máy tính chậm khi lồng tiếng / render (không có GPU)
- Bình thường trên máy **chỉ có CPU**. Lồng tiếng, tách nhạc, render tốn thời gian. Muốn nhanh: dùng máy có **GPU NVIDIA**, hoặc chọn giọng **ViralVoice — Tiêu chuẩn** (nhanh, offline), hoặc render **không lồng tiếng**.

### E. Cài đặt bị Windows chặn (SmartScreen)
- Bấm **"More info" → "Run anyway"**. Installer chưa ký số, không phải virus.

### F. Không nâng cấp / không kích hoạt được gói
- Kiểm tra **mạng**; bấm **"Làm mới gói"** trong tab "Gói của tôi".
- Nếu báo "gắn máy khác" / "máy đã có tài khoản khác" → cần admin **gỡ thiết bị** (liên hệ Zalo).

### G. App treo / lỗi lạ khi đang chạy
- Đóng hẳn app rồi mở lại. Nếu vẫn treo do tiến trình cào cũ còn sót → có công cụ **dọn dẹp** (`DON-DEP.bat` với bản thủ công) hoặc khởi động lại máy.
- Lỗi có mã "WinError" thường đã được xử lý tự động ở bản mới nhất → khuyên khách **cập nhật lên bản mới**.

### H. Chạm giới hạn gói (banner hiện lên)
Các thông báo mẫu và ý nghĩa:
- *"Đã đạt giới hạn cào N video/ngày của gói ... Nâng cấp để cào không giới hạn."* → hết lượt cào hôm nay (reset 00:00) hoặc nâng cấp.
- *"Đã đạt giới hạn lồng tiếng N video/ngày ..."* / *"... N phút lồng tiếng/ngày ..."* → hết quota lồng tiếng hôm nay.
- *"Gói ...: mỗi video lồng tiếng tối đa N phút. Video này X phút — nâng cấp để lồng video dài hơn."* → video dài quá mức cho phép của gói.
- *"Băm nhỏ chỉ có ở gói PRO/UNLIMITED."*, *"Quy trình tự động chỉ có ở gói PRO/UNLIMITED."*, *"Trợ lý AI chỉ có ở gói UNLIMITED."*, *"Gói FREE không có tính năng clone/theo dõi kênh..."* → tính năng cần gói cao hơn.
Cách xử lý chung: **đợi sang ngày mới** (với giới hạn theo ngày) hoặc **nâng cấp gói**.

---

## 12. AN TOÀN TÀI KHOẢN & LƯU Ý

- **Không cào quá nhiều / quá nhanh** → dễ bị nền tảng **hạn chế/khóa tài khoản (风控)**. Nên dùng **nick phụ**, mỗi lần chỉ cào vài chục video, để tool nghỉ giữa các lượt.
- Theo dõi kênh: kiểm tra càng dày càng nhanh nhưng **dễ bị hạn chế** — khuyên 15–30 phút.
- Video tải về **thuộc bản quyền tác giả gốc**. Sản phẩm phục vụ **học tập/nghiên cứu**; người dùng tự chịu trách nhiệm tuân thủ điều khoản nền tảng và pháp luật khi đăng lại.
- Video có thể còn **watermark** của nền tảng gốc.

---

## 13. LIÊN HỆ HỖ TRỢ

- **Zalo hỗ trợ / mua gói / gỡ thiết bị: 0394.426.246**
- Trong app: tab **"Gói của tôi"** (xem gói, nâng cấp, làm mới) và tab **"Cài đặt"**.

---

## 14. CÂU HỎI NHANH (mẫu Q&A cho AI)

- **Hỏi: Tool chạy trên điện thoại/Mac được không?** → Không. Chỉ Windows 10/11 64-bit.
- **Hỏi: Tải YouTube/TikTok/Facebook có cần đăng nhập không?** → Không. Chỉ Douyin/Bili/XHS/RedNote cần quét QR.
- **Hỏi: Cào 0 video là lỗi tool à?** → Thường không. Do hết phiên đăng nhập hoặc nền tảng chặn tạm. Đăng nhập lại + thử lại sau vài phút.
- **Hỏi: Mua gói bao nhiêu tiền?** → Gói Tháng giá 299.000đ/tháng. Gói Năm giá 999.000đ/năm. Gói Vĩnh Viễn giá 1.799.000đ/trọn đời. Khi mua Gói Năm và Vĩnh Viễn sẽ được tặng kèm bộ 3 quà tặng reup độc quyền. Xem chi tiết tại mục 3.2.
- **Hỏi: Đổi sang máy mới thì mã kích hoạt còn dùng được không?** → Cần admin gỡ thiết bị cũ trên Google Sheet (Zalo 0394.426.246) rồi nhập mã kích hoạt lại trên máy mới.
- **Hỏi: Trợ lý AI có ở Gói Tháng không?** → Không, các tính năng mở rộng (Trợ lý AI, không giới hạn lồng tiếng) chỉ hỗ trợ từ Gói Năm và Gói Vĩnh Viễn trở lên.
- **Hỏi: Video có bị mất khi cập nhật tool không?** → Không, lưu ngoài thư mục cài.
- **Hỏi: Vì sao lồng tiếng/render chậm?** → Máy không có GPU NVIDIA. Bình thường. Dùng giọng "ViralVoice — Tiêu chuẩn" hoặc máy có GPU để nhanh hơn.
- **Hỏi: Tool cào được Weibo/Twitter/Instagram/Reddit/Threads không?** → Bản 1.3.7 hiện **chưa hỗ trợ** (đang tạm ẩn), sẽ mở ở bản cập nhật sau. Hiện cào được: Douyin, Bilibili, Xiaohongshu, RedNote, YouTube, TikTok, Facebook.
- **Hỏi: Lồng tiếng/dịch được ngôn ngữ nào?** → Hơn 70 ngôn ngữ đích (không chỉ tiếng Việt), chọn ở "Ngôn ngữ đích" khi render.
- **Hỏi: Installer báo virus/Windows chặn?** → SmartScreen do chưa ký số. Bấm More info → Run anyway.
