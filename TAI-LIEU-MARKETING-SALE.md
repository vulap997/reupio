# ViralCrawl — Tài liệu Marketing & Sales

> Tài liệu nội bộ cho phòng **Marketing** (làm content, review, quảng cáo) và **Sale** (demo, tư vấn khách).
> Phiên bản sản phẩm: **v0.1.6**. Cập nhật: 2026-06-15.
> Mọi tính năng dưới đây đều đã có thật trong sản phẩm (không phóng đại).

---

## 1. Sản phẩm là gì? (Pitch 1 câu)

**ViralCrawl là phần mềm "tất-cả-trong-một" giúp người không biết lập trình tự động TẢI VIDEO từ 8 nền tảng mạng xã hội, BIÊN TẬP LẠI để đăng lại (reup), và DỊCH + LỒNG TIẾNG VIỆT chỉ với vài cú click — toàn bộ giao diện tiếng Việt, chạy ngay trên máy tính Windows.**

### Pitch 1 đoạn (cho landing page / mở đầu tư vấn)
Bạn muốn làm kênh TikTok/YouTube/Facebook bằng video triệu view từ Trung Quốc, Douyin, hay các nền tảng quốc tế — nhưng ngại tải thủ công, không biết edit, không biết tiếng Trung? **ViralCrawl** làm hết: gõ từ khóa hoặc dán link → phần mềm tự tải video chất lượng cao → tự biên tập lại để tránh trùng lặp bản quyền → tự dịch và lồng tiếng Việt giọng AI tự nhiên → tự tạo caption. Cài 1 lần bằng 1 file, không cần biết code, không cần cài đặt rườm rà.

---

## 2. Khách hàng mục tiêu (ai nên mua?)

| Nhóm khách | Vì sao cần ViralCrawl |
|------------|------------------------|
| **Nhà sáng tạo nội dung / KOC / TikToker** | Cần nguồn video viral liên tục, muốn reup nhanh mà không bị "trùng content" |
| **Chủ kênh reup / MMO (kiếm tiền online)** | Xây nhiều kênh, cần tự động hoá tải + xử lý + lồng tiếng hàng loạt |
| **Agency / team sản xuất nội dung** | Cần công cụ chuẩn hoá quy trình cho nhiều nhân viên không rành kỹ thuật |
| **Người bán hàng / shop online** | Lấy video review sản phẩm từ Douyin/Xiaohongshu, Việt hoá để chạy quảng cáo |
| **Người học tiếng Trung / dịch thuật** | Dịch + phụ đề + lồng tiếng video tiếng Trung sang tiếng Việt tự động |
| **Nhà nghiên cứu / sinh viên truyền thông** | Thu thập dữ liệu nội dung mạng xã hội theo chủ đề để phân tích |

**Chân dung điển hình:** người Việt 20–40 tuổi, làm nội dung số, **KHÔNG biết lập trình**, ngại công cụ tiếng Anh phức tạp, muốn tiết kiệm thời gian và tăng sản lượng video.

---

## 3. Nỗi đau khách đang gặp → ViralCrawl giải quyết

| Khách đang khổ vì… | ViralCrawl xử lý |
|--------------------|------------------|
| Tải video thủ công từng cái, mất hàng giờ | Gõ từ khóa/dán link → tải hàng loạt tự động |
| Reup bị quét bản quyền / trùng lặp | Tự biên tập lại (lật, đổi tốc độ, watermark, nhạc nền, re-encode) |
| Không biết tiếng Trung, không edit được video TQ | Tự nhận dạng tiếng Trung → dịch Việt → lồng tiếng giọng AI |
| Phải thuê người lồng tiếng, dịch phụ đề | Lồng tiếng + phụ đề tự động, giọng clone tự nhiên |
| Công cụ nước ngoài khó dùng, tiếng Anh, cài đặt rối | Giao diện 100% tiếng Việt, cài 1 file, tự setup |
| Quên check kênh đối thủ / nguồn video mới | Theo dõi kênh tự động + hẹn giờ tải mỗi ngày |
| Viết caption mỏi tay | Tự tạo caption từ nội dung phụ đề |

---

## 4. Bộ tính năng đầy đủ (kèm lợi ích để làm content)

### 4.1. Tải video từ 8 nền tảng
- **Nền tảng hỗ trợ:** Douyin (TikTok Trung Quốc), Bilibili, Xiaohongshu (Tiểu Hồng Thư), Weibo, **YouTube, TikTok, Twitter/X, Instagram**.
- **Cào theo nhiều cách:** từ khóa, link trực tiếp, hoặc cả kênh/tài khoản.
- **Bộ lọc thông minh:** sắp xếp theo *Hot nhất / Mới nhất / Liên quan*, lọc theo *thời gian đăng* (1 ngày / 1 tuần / 6 tháng).
- **Gợi ý kênh theo chủ đề:** xếp hạng kênh theo lượng follow/subscriber để tìm nguồn video chất.
> 💡 *Lợi ích bán hàng:* "Một phần mềm — 8 nền tảng. Không cần 8 công cụ khác nhau."

### 4.2. Tự động biên tập lại (Reup) — tránh trùng bản quyền
- Pipeline FFmpeg: **lật ngang, thêm watermark/logo, chèn nhạc nền, tăng tốc nhẹ (1.1x), re-encode H.264**.
- **Tăng tốc bằng GPU NVIDIA (NVENC)** — render nhanh hơn nhiều so với chỉ dùng CPU.
> 💡 *Lợi ích:* "Reup an toàn hơn — video được 'làm mới' để giảm rủi ro bị quét trùng lặp."

### 4.3. Lồng tiếng Trung → Việt TỰ ĐỘNG (tính năng "đinh")
- **2 hệ giọng để chọn:**
  - **edge-tts / viXTTS** — giọng AI tự nhiên, có thể **clone giọng**, **tách nhạc nền (Demucs)** giữ lại nhạc gốc, dịch **offline (NLLB)**.
  - **F5-TTS** — clone giọng tiếng Việt **chất lượng cao**, có sẵn mẫu giọng nam/nữ.
- **Music ducking:** tự giảm nhạc nền khi có lời nói → nghe rõ giọng đọc.
- Không cần thuê người lồng tiếng, không cần biết tiếng Trung.
> 💡 *Lợi ích:* "Biến video tiếng Trung thành video tiếng Việt hoàn chỉnh — giọng đọc tự nhiên, giữ nguyên nhạc nền — chỉ trong vài phút."

### 4.4. Dịch & phụ đề thông minh
- Tự **nhận dạng giọng nói** (faster-whisper) → **dịch sang tiếng Việt** → tạo **phụ đề** → (tùy chọn) **AI tinh chỉnh** câu chữ cho mượt → ghép/đốt phụ đề vào video.
- **AI đa nhà cung cấp** (Groq / Gemini / Ollama) tinh chỉnh phụ đề; quản lý nhiều key, tự xoay vòng khi quá tải.
> 💡 *Lợi ích:* "Phụ đề Việt chuẩn, tự nhiên — không còn dịch máy ngô nghê."

### 4.5. Nội dung dạng ảnh (Reddit & Threads)
- Tự **chụp bài đăng**, **OCR** đọc chữ trong ảnh, **đè phụ đề tiếng Việt**, tạo **audio đọc** từng ảnh → làm video kể chuyện từ bài viết.
> 💡 *Lợi ích:* "Khai thác cả nội dung dạng bài viết/ảnh, không chỉ video."

### 4.6. Tự động hoá & theo dõi
- **Theo dõi kênh:** chỉ tải video MỚI khi kênh đăng bài, kiểm tra định kỳ.
- **Hẹn giờ:** đặt lịch tự cào mỗi ngày (qua Windows Task Scheduler).
> 💡 *Lợi ích:* "Đặt một lần — phần mềm tự làm việc mỗi ngày kể cả khi bạn ngủ."

### 4.7. Tạo caption & gom đăng bài
- Tự **viết caption** từ nội dung phụ đề; gom nội dung để đăng bài nhanh.

### 4.8. Trải nghiệm dễ dùng
- **Giao diện web 100% tiếng Việt** (song ngữ Việt/Anh), dashboard trực quan.
- **Không cửa sổ đen dòng lệnh** — thiết kế cho người không biết code.

---

## 5. Điểm bán hàng độc đáo (USP) — vì sao chọn ViralCrawl

1. **All-in-one:** tải + biên tập + dịch + lồng tiếng + caption trong MỘT phần mềm (đối thủ thường chỉ làm 1 việc).
2. **8 nền tảng** trong cùng một công cụ.
3. **Lồng tiếng Việt bằng AI** với 2 hệ giọng + tách nhạc nền — hiếm công cụ Việt nào có.
4. **100% tiếng Việt, cho người không biết code** — rào cản kỹ thuật gần như bằng 0.
5. **Cài 1 file, tự cập nhật** — không cần cài Python/Node/FFmpeg thủ công.
6. **Tự động hoá** theo dõi kênh + hẹn giờ — làm việc 24/7.
7. **Bảo mật chuẩn:** dữ liệu/khoá API mã hoá theo máy (Windows DPAPI), license gắn máy.

---

## 6. Tự làm thủ công vs Dùng ViralCrawl

| Công việc | Thủ công | Với ViralCrawl |
|-----------|----------|----------------|
| Tải 20 video | ~1–2 giờ, copy link từng cái | Vài phút, tự động hàng loạt |
| Biên tập tránh trùng | Mở phần mềm edit, làm tay | Tự động pipeline FFmpeg |
| Dịch + phụ đề 1 video | Nghe-dịch-gõ tay, 30–60 phút | Tự động vài phút |
| Lồng tiếng | Thuê người (vài trăm K/video) | Giọng AI, miễn phí, vài phút |
| Theo dõi kênh đối thủ | Vào xem thủ công mỗi ngày | Tự động báo + tải video mới |

> 💡 *Chốt sale:* "ViralCrawl thay thế cả một quy trình + nhiều công cụ + chi phí thuê ngoài."

---

## 7. Gói & License (mô hình thương mại)

- **Đăng ký tài khoản 1 lần** ngay trong app → tài khoản **gắn với máy** (mỗi license dùng đúng máy đã đăng ký).
- **2 gói:**
  - **FREE** — dùng các tính năng cơ bản.
  - **PRO** — mở khoá tính năng nâng cao (theo chính sách kinh doanh).
- **Hết hạn PRO → tự xuống FREE**, app **vẫn mở bình thường**, chỉ tạm khoá tính năng trả phí (không khoá cứng, không mất dữ liệu).
- **Hoạt động kể cả khi mất mạng ngắn hạn** (offline grace 7 ngày).
- **Portal quản trị** (cho admin/đại lý): xem danh sách user, cấp/thu hồi gói, thống kê số thiết bị đang hoạt động.

> 📌 *Lưu ý cho Sale:* mô hình "gắn máy" = chống chia sẻ license tràn lan → bảo vệ doanh thu. Mỗi khách = 1 license = 1 máy.

---

## 8. Cài đặt & trải nghiệm (điểm cộng khi tư vấn)

- **1 file cài đặt** `ViralCrawl-Setup.exe` — double-click là xong.
- **Tự setup lần đầu** (tự tải các thành phần cần thiết), **không cần quyền admin** (cài vào thư mục người dùng).
- **Tự cập nhật** — có bản mới, app tự tải bản vá, khách luôn dùng phiên bản mới nhất.
- Chạy trên **Windows 10/11 (64-bit)**, khuyến nghị RAM 8GB (cho tính năng phụ đề/lồng tiếng).

---

## 9. Kịch bản DEMO cho Sale (tư vấn khách)

**Demo "Wow" trong 5 phút:**
1. Mở app → chỉ giao diện **tiếng Việt, gọn gàng** (ghi điểm "dễ dùng").
2. Gõ 1 **từ khóa hot** (vd "mukbang", "review đồ ăn") → bấm **Bắt đầu cào** → cho khách thấy video tải về hàng loạt.
3. Chọn 1 video tiếng Trung → bật **Lồng tiếng** → chọn giọng → cho khách nghe **giọng Việt AI tự nhiên + giữ nhạc nền**. (Đây là khoảnh khắc "chốt".)
4. Bật **Xử lý video** → cho thấy video được tự biên tập lại (chống trùng).
5. Mở tab **Theo dõi kênh** → giải thích "đặt 1 lần, tự chạy mỗi ngày".
6. Chốt: "Tất cả những gì anh/chị vừa thấy — không cần biết code, không cần tiếng Trung, không cần thuê ai."

**Mẹo tư vấn:** hỏi khách "Anh/chị đang làm kênh nền tảng nào, nội dung gì?" → demo đúng nền tảng + chủ đề của khách để tăng tính thuyết phục.

---

## 10. Câu hỏi thường gặp (FAQ — xử lý từ chối)

**Q: Tôi không biết gì về máy tính, dùng được không?**
A: Được. Giao diện hoàn toàn tiếng Việt, cài 1 file, các thao tác chỉ là chọn và bấm nút.

**Q: Lồng tiếng có tự nhiên không hay giọng máy móc?**
A: Dùng giọng AI thế hệ mới (viXTTS/F5-TTS) có thể clone giọng, nghe tự nhiên; còn giữ được nhạc nền gốc.

**Q: Reup có bị quét bản quyền không?**
A: Phần mềm tự biên tập lại (lật, đổi tốc độ, watermark, re-encode) để giảm rủi ro trùng lặp — nhưng không có công cụ nào đảm bảo 100%, vẫn cần dùng nội dung hợp lệ (xem mục 13).

**Q: Một license dùng được mấy máy?**
A: License gắn theo máy đã đăng ký. Cần thêm máy thì liên hệ để cấp thêm.

**Q: Mất mạng có dùng được không?**
A: Có thời gian ân hạn offline (7 ngày) cho các lần mở app.

**Q: Có cần cài Python/Node/FFmpeg gì không?**
A: Không. Bản installer tự lo phần kỹ thuật, khách chỉ cần double-click.

**Q: Tải video TikTok/YouTube/X/Instagram được không?**
A: Được — hỗ trợ cả 8 nền tảng (Douyin, Bilibili, Xiaohongshu, Weibo, YouTube, TikTok, Twitter/X, Instagram).

---

## 11. Góc nội dung cho Marketing (hook & caption mẫu)

**Hook quảng cáo (chạy ads / tiêu đề video):**
- "Biến video Trung Quốc triệu view thành video Việt — chỉ 1 phần mềm, không cần biết tiếng Trung."
- "Làm kênh reup mà không biết edit? Phần mềm này làm hết cho bạn."
- "8 nền tảng — 1 click — tải, biên tập, lồng tiếng Việt tự động."
- "Tải video Douyin + lồng tiếng Việt AI trong 3 phút (xem demo)."

**Góc content (cho team sáng tạo):**
- Video demo "trước/sau": video gốc tiếng Trung → video Việt hoàn chỉnh.
- So sánh "làm tay 2 tiếng vs ViralCrawl 5 phút".
- Series "1 ngày làm 50 video reup với ViralCrawl".
- Review tính năng lồng tiếng AI (điểm khác biệt mạnh nhất).
- Testimonial khách hàng (chủ kênh reup, shop online).

**Từ khoá SEO/ads gợi ý:** tool cào video, phần mềm reup video, lồng tiếng AI tiếng Việt, tải video Douyin, dịch video Trung Việt, công cụ làm content tự động.

---

## 12. Thông số tóm tắt (cho FAQ kỹ thuật)

| Mục | Thông tin |
|-----|-----------|
| Hệ điều hành | Windows 10/11 (64-bit) |
| RAM khuyến nghị | 8 GB (cho phụ đề/lồng tiếng) |
| GPU | Tùy chọn — NVIDIA giúp render nhanh hơn (NVENC) |
| Cài đặt | 1 file .exe, tự setup, không cần admin |
| Cập nhật | Tự động (auto-update) |
| Ngôn ngữ giao diện | Tiếng Việt (có cả tiếng Anh) |
| Nền tảng hỗ trợ | 8 (Douyin, Bilibili, Xiaohongshu, Weibo, YouTube, TikTok, Twitter/X, Instagram) |

---

## 13. ⚠️ Sử dụng có trách nhiệm (Sale BẮT BUỘC nắm để tư vấn đúng)

- Sản phẩm có nguồn gốc **học tập/nghiên cứu**; video tải về **thuộc bản quyền tác giả gốc**.
- **Tư vấn khách dùng đúng mục đích hợp pháp:** quản lý nội dung của chính mình, nội dung được cấp phép, nội dung có thoả thuận, hoặc mục đích tham khảo/nghiên cứu/bản địa hoá.
- **Không cam kết** "100% không bị quét bản quyền" — đây là rủi ro của việc reup, khách tự chịu trách nhiệm pháp lý.
- Khuyến nghị khách: dùng nick phụ khi đăng nhập nền tảng, không cào quá dày để tránh bị khoá tài khoản.
- **Tránh nói quá** trong quảng cáo (vd "kiếm tiền chắc chắn", "không bao giờ bị bản quyền") — dễ gây khiếu nại + rủi ro pháp lý cho công ty.

> Mục tiêu: bán đúng giá trị thật (tiết kiệm thời gian, tự động hoá, Việt hoá nội dung) — không bán "lời hứa ảo".

---

## 14. Bảo mật & độ tin cậy (điểm cộng khi chốt khách doanh nghiệp)

- **Khoá API & dữ liệu nhạy cảm được mã hoá theo máy** (Windows DPAPI) — không lưu dạng văn bản thường.
- **License gắn máy + token ký số** — chống dùng lậu, chống sửa file để nâng gói.
- **Hệ thống license chạy trên hạ tầng cloud chuyên nghiệp** (máy chủ khu vực Singapore — gần Việt Nam, phản hồi nhanh).
- **Đã qua kiểm thử bảo mật** (chống giả mạo phiên, chống dò mật khẩu, xác thực thanh toán bằng chữ ký) — yên tâm cho khách trả phí.

---

## 15. Một câu chốt (tagline đề xuất)

> **"ViralCrawl — Tải, biên tập, lồng tiếng Việt mọi video viral. Một phần mềm, không cần biết code."**

---

*Tài liệu này mô tả tính năng có thật của sản phẩm v0.1.6. Khi làm content/quảng cáo, vui lòng bám sát mục 13 (sử dụng có trách nhiệm) để tránh rủi ro pháp lý và khiếu nại.*
