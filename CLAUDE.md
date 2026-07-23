# CLAUDE.md — reupo douyin+

Tool cào video đa nền tảng (Douyin/Bilibili/XHS/Weibo qua MediaCrawler; YouTube/TikTok qua yt-dlp) + dịch/lồng tiếng + render reup. Tên kỹ thuật: LLN-app.

## Quy tắc bắt buộc (rule.md)
1. **TRƯỚC khi implement/update**: đọc kỹ `rule.md` + memory + skill đã build trong dự án.
2. **SAU khi làm**: test thật kỹ, fix đến hết bug rồi mới báo cáo. **CẤM bịa kết quả test** — báo đúng output thật, kể cả khi fail.
3. **KHÔNG thay đổi/phá hỏng** logic khác đang hoạt động bình thường.
4. Tìm kiếm codebase: dùng `codegraph` MCP nếu có; chưa cấu hình thì dùng Grep/Glob.
5. Phát hiện lỗi mới → lưu vào memory để không tái phạm.
6. **Điều phối đa session**: MỖI lần nhận prompt, ĐỌC `SESSIONS.md` TRƯỚC để biết session khác đang sửa file nào (tránh đè nhau). Khi bắt đầu sửa code → ghi/cập nhật mục của mình (việc + danh sách file đụng + trạng thái) vào `SESSIONS.md`; nếu file mình định sửa đang nằm trong mục "đang làm" của session khác → HỎI user trước. KHÔNG xóa mục của session khác.

## Ràng buộc cứng
- **TUYỆT ĐỐI không xóa/sửa `MediaCrawler/data/` và `processed_videos/`** — video thật của user.
- **Không tự commit/push** — user tự quản lý git; chỉ commit khi được yêu cầu rõ ràng.
- **Máy CPU-only**: i3-9100F, 16GB RAM, RX560 (không có GPU dùng được). whisper/demucs/ffmpeg rerender chậm — không giả định GPU, luôn cân nhắc thời gian chạy thực.
- **Trả lời user bằng tiếng Việt**; giữ tên thư viện/lệnh/CLI nguyên gốc.
- IDE có thể ghi đè file bằng buffer cũ — sau khi sửa JS chạy `node --check` để xác minh.

## Nguyên tắc code (Karpathy)
1. **Think Before Coding** — nêu rõ giả định; mơ hồ thì HỎI; có cách đơn giản hơn thì nói thẳng.
2. **Simplicity First** — code tối thiểu giải đúng bài; không abstraction/feature/config thừa.
3. **Surgical Changes** — chỉ đụng dòng liên quan trực tiếp yêu cầu; match style sẵn có; thấy dead code thì báo, không xóa.
4. **Goal-Driven Execution** — biến task thành tiêu chí verify được ("sửa bug" → "tái hiện bug → làm cho pass"); mỗi bước có check.

## Kiến trúc nhanh
- `web_app.py` (~1375 dòng) — **UI CHÍNH**: stdlib `ThreadingHTTPServer` **port 8770**, phục vụ `web/index.html`, ~60 route `/api/*`, hàng đợi render (worker nền), đăng nhập khách (`khach_db.py`, sqlite). Mở bằng `MO-WEB.bat`. (`web_server.py` FastAPI:8866 = bản cũ, KHÔNG dùng.)
- `localize.py` — dịch/lồng tiếng: faster-whisper ASR tiếng Trung (CPU int8) → Google dịch thô → AI sửa cả SRT (`ai_dich.py`) → lồng tiếng VieNeu-TTS (local CPU; edge-tts là fallback) → demucs tách nhạc → ffmpeg che chữ Trung + burn phụ đề. Output cạnh video: `.zh.srt/.vi.srt`, `_phude.mp4`, `_longtieng.mp4`.
- `ai_dich.py` — AI dịch đa provider (Groq/Gemini/Ollama Cloud/OpenRouter), nhiều key tự xoay khi 429, mặc định `ollama/gemma3:12b`. Key mã hóa DPAPI (`bao_mat_key.py` → `key_store.dat`, gitignore).
- `xu_ly_video.py` — rerender tự động: poll TẤT CẢ `data/<nền tảng>/videos` → ffmpeg (cắt/lật/watermark/tốc độ/màu/nhạc nền) → `processed_videos/<nền tảng>/`. `xu_ly_chon.py` — render video được tick (transforms + localize) → `_xuly.mp4`, giữ gốc.
- `MediaCrawler/` — fork NanmiCoder đã patch (`media_platform/douyin/core.py`: nhánh userlist, env `DY_SORT_TYPE/DY_PUBLISH_TIME/DY_CREATOR_SORT`, ledger `_da_tai_ids.txt`; `store/douyin/douyin_store_media.py`: thêm `sub_dir`). Gọi qua subprocess với venv riêng: `MediaCrawler\.venv\Scripts\python.exe` (uv, Python 3.11).
- Tự động hóa: `theo_doi.py` (poll kênh mới) + `chay_tu_dong.py` (cào hẹn giờ) qua Windows schtasks.
- Môi trường: Windows 10, PowerShell 5.1, ffmpeg cài qua winget.

## Tài liệu
- `docs/` (codebase-summary, system-architecture, code-standards, project-overview-pdr) — LƯU Ý: số dòng/danh sách file trong docs đã lỗi thời so với code hiện tại.
- `HUONG-DAN.md` — hướng dẫn người dùng cuối. `BAO-CAO.md` — báo cáo dự án.
