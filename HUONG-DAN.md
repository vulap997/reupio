# TOOL CÀO VIDEO (học tập)

Tool dựa trên mã nguồn mở [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) — giấy phép **chỉ cho phép học tập, KHÔNG dùng thương mại**.

## Nền tảng hỗ trợ

| Nền tảng | Tải video | Tải ảnh | Ghi chú |
|----------|-----------|---------|---------|
| **Douyin** | ✅ | ✅ | Quét QR bằng app Douyin |
| **Bilibili** | ✅ | — | Quét QR bằng app Bilibili |
| **Xiaohongshu** | ✅ | ✅ | Quét QR bằng app XHS |
| **Weibo** | ❌ | ✅ | Chỉ tải được ảnh |

(MediaCrawler còn hỗ trợ Kuaishou/Tieba/Zhihu nhưng các nền tảng đó không có chức năng tải video nên không đưa vào tool.)

## Cài đặt (chỉ làm 1 lần — máy này ĐÃ cài xong)

1. Đảm bảo máy đã có **Python** và **Chrome hoặc Edge**.
2. Chạy file **`CAI-DAT.bat`** → đợi cài xong (vài phút, cần mạng).

## Cách dùng (giao diện đồ họa)

1. Chạy file **`CAO-VIDEO.bat`** → cửa sổ giao diện mở lên (không còn cửa sổ đen).
2. **Bước 1 – Chọn nền tảng**: bấm Douyin / Bilibili / Xiaohongshu / Weibo.
3. **Bước 2 – Chọn cách cào**:
   - **🔍 Theo từ khóa**: gõ từ khóa tìm kiếm (nhiều từ cách nhau dấu phẩy) + chọn số lượng.
   - **🔗 Theo link**: dán link video/bài viết, **mỗi dòng 1 link** (hỗ trợ link đầy đủ, link rút gọn, hoặc ID).
   - **👤 Theo kênh**: dán link trang cá nhân (kênh) + chọn số lượng + ô **"Lấy video"** (Mới nhất / Nhiều like nhất). Có thể dán nhiều kênh, mỗi dòng 1 kênh. (Nhiều like nhất = chọn trong ~120 bài gần đây của kênh.)
4. **Bước 3 – Nhập thông tin** vào ô lớn, rồi bấm **▶ BẮT ĐẦU CÀO**.
5. **Lần đầu chạy mỗi nền tảng**: trình duyệt sẽ mở trang đăng nhập → dùng **app tương ứng trên điện thoại quét mã QR**. Các lần sau tự đăng nhập (đã lưu phiên riêng từng nền tảng).
6. Tiến trình hiện trực tiếp trong khung **Nhật ký chạy**. Xong bấm **📂 Mở thư mục video**.

> Phiên bản dòng lệnh cũ vẫn còn ở file `cao_video.py` (chạy bằng `MediaCrawler\.venv\Scripts\python.exe cao_video.py`) nếu bạn thích dùng menu chữ.

## Tải video HOT theo chủ đề

Ở chế độ **🔍 Theo từ khóa** (Douyin) có thêm 2 ô:
- **Sắp xếp**: chọn **"Nhiều like nhất (HOT)"** để lấy video hot nhất, hoặc "Mới nhất".
- **Thời gian**: chọn **"Trong 1 tuần"** / "Trong 1 ngày" để lấy video hot *gần đây*.

Ví dụ muốn lấy video đang hot về mèo: từ khóa `mèo` + Sắp xếp "Nhiều like nhất" + Thời gian "Trong 1 tuần".

> Lưu ý: Douyin không có "bảng xếp hạng hot" tổng. Đây là cách thực tế nhất — lấy video nhiều like nhất theo *chủ đề* bạn nhập.

### Dịch từ khóa sang tiếng Trung (tìm hiệu quả hơn)

Douyin/Bilibili là nền tảng Trung Quốc, tìm bằng tiếng Trung ra nhiều kết quả hơn. Ở chế độ **🔍 Theo từ khóa**:
1. Gõ từ khóa **tiếng Việt/Anh** (vd `mèo dễ thương`)
2. Bấm **🇨🇳 Dịch từ khóa sang tiếng Trung**
3. Hộp thoại hiện 2 bản: **简体 giản thể** (cho Douyin/đại lục) và **繁體 phồn thể** (Đài Loan/HK)
4. Bấm "Dùng từ khóa này" (hoặc "Dùng cả hai") → tự điền vào ô tìm kiếm, rồi BẮT ĐẦU CÀO

(Cần có kết nối mạng để dịch.)

## Gợi ý kênh — tìm kênh theo từ khóa (tab "🔎 Gợi ý kênh")

1. Nhập từ khóa (vd `mukbang`, `美食`) → bấm **🔎 Tìm kênh** (đợi ~1–2 phút)
2. Tool hiện danh sách kênh **xếp theo lượt follow**, mỗi kênh 1 thẻ: avatar + tên + số follow/like/video + ô tick
3. **Tick** các kênh muốn → bấm **✔ Lưu kênh đã tick**
4. Bấm **➜ Đưa vào CÀO KÊNH** (tải video các kênh đó ngay) hoặc **➜ Đưa vào THEO DÕI** (theo dõi định kỳ)

> Tìm kênh cần đăng nhập sẵn + chạy ~1–2 phút (tool tra số follow thật của từng kênh).

## Theo dõi kênh — tự tải video MỚI (tab "👀 Theo dõi kênh")

Tool kiểm tra các kênh theo chu kỳ, kênh nào có video mới thì tải ngay (bỏ qua video đã có).

1. Tab **👀 Theo dõi kênh** → dán link các kênh (mỗi dòng 1 kênh, dạng `/user/MS4w...`)
2. Đặt **"Kiểm tra mỗi … phút"** (khuyên 15–30) và **số video lấy tối đa mỗi lần**
3. Bấm **✅ BẬT theo dõi** → Windows tự kiểm tra định kỳ
4. **🧪 Kiểm tra ngay** để chạy thử liền; **⛔ TẮT** để dừng

> Không phải tức thời — Douyin không gửi thông báo, nên tool phải kiểm tra định kỳ. Kiểm tra càng dày càng nhanh nhưng **dễ bị hạn chế tài khoản**. Cần đăng nhập sẵn + máy bật. Nhật ký: `MediaCrawler\data\theo_doi.log`.

## Chạy tự động mỗi ngày (tab "Hẹn giờ tự động")

1. Sang tab **⚡ Cào ngay**, chọn nền tảng + cách cào + nhập từ khóa/link/kênh (như bình thường).
2. Sang tab **⏰ Hẹn giờ tự động** → bấm **⬇ Lấy cấu hình từ tab Cào ngay** (lưu lại tác vụ sẽ chạy).
3. Đặt **giờ chạy mỗi ngày** (giờ 24h, ví dụ 08:00).
4. Bấm **✅ BẬT chạy hằng ngày**. Windows Task Scheduler sẽ tự chạy tool vào giờ đó mỗi ngày, kể cả khi không mở tool.
5. Muốn thử ngay: bấm **🧪 Chạy thử ngay**. Muốn dừng: bấm **⛔ TẮT**.

**Quan trọng:**
- Tác vụ tự động chạy ở chế độ **ẩn (headless)** nên cần đã đăng nhập sẵn. **Lần đầu và khi phiên hết hạn**, phải mở tab "Cào ngay" chạy 1 lần + **quét QR** để lưu đăng nhập.
- Máy phải **đang bật và đã đăng nhập Windows** vào giờ hẹn.
- Nhật ký các lần chạy tự động: `MediaCrawler\data\tu_dong.log`
- Cấu hình tác vụ lưu ở: `lich_config.json`

## Nút 🌐 Đăng nhập trình duyệt

Bấm nút này để mở sẵn trình duyệt và **đăng nhập trước** (không cần chạy cào). Dùng khi:
- Đăng nhập lần đầu một nền tảng.
- Phiên đăng nhập hết hạn, cần đăng nhập lại (nhất là trước khi để tool chạy tự động hằng ngày).

Cách dùng: chọn nền tảng → bấm **🌐 Đăng nhập trình duyệt** → đăng nhập trong cửa sổ hiện ra → vào được trang chủ thì **đóng cửa sổ**. Phiên được lưu, lần cào sau khỏi quét QR.

## Media tải về nằm ở đâu?

**Douyin** — chia thư mục theo cách cào, tên file theo tiêu đề video:
```
MediaCrawler\data\douyin\videos\
  ├─ tu-khoa\<từ khóa>\<tiêu đề>_<id>.mp4      ← cào theo từ khóa
  ├─ kenh\<tên kênh>\<tiêu đề>_<id>.mp4         ← cào theo kênh
  └─ link\<tiêu đề>_<id>.mp4                     ← cào theo link
```

Các nền tảng khác:
```
Bilibili:     MediaCrawler\data\bili\videos\<id>\
Xiaohongshu:  MediaCrawler\data\xhs\videos\  (ảnh: data\xhs\images\)
Weibo:        MediaCrawler\data\weibo\images\
```

Thông tin bài viết (tiêu đề, tác giả, lượt thích...) lưu dạng JSONL trong thư mục `jsonl` cùng cấp.

## Mẹo & xử lý lỗi

- **Cửa sổ trình duyệt mở ra để đăng nhập**: ĐỪNG tự tay đóng nó cho tới khi quét QR xong và vào được trang. Đóng sớm = đăng nhập thất bại, không tải được gì.
- **"Đăng nhập chưa xong"**: quét QR lại, chờ vào trang rồi tool tự cào tiếp. Lần sau đã lưu phiên nên không cần quét lại.
- **Đăng nhập cứ báo thất bại**: sau khi quét QR, nền tảng có thể bắt xác minh thêm (trượt captcha / số điện thoại) trên trình duyệt — làm theo rồi chạy lại.
- **Xong nhưng 0 tệp**: thường do từ khóa không ra kết quả, hoặc phiên đăng nhập hết hạn (quét QR lại).
- **Không nên cào quá nhiều / quá nhanh** (dễ bị khóa tài khoản). Tool mặc định nghỉ ~2 giây giữa các lượt, mỗi lần chỉ nên cào vài chục video.
- Muốn chỉnh sâu hơn (proxy, số giây nghỉ, headless...): sửa file `MediaCrawler\config\base_config.py`.
- Media cào về thuộc bản quyền của tác giả gốc — chỉ dùng để học tập, không đăng tải lại vì mục đích thương mại.
