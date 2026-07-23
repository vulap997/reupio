# reupo douyin+ (toolcaovideo) — v1.2.3

Công cụ desktop tự động **cào video đa nền tảng** (Douyin, Bilibili, Xiaohongshu, Weibo, YouTube, TikTok, Twitter/X, Instagram, Reddit, Threads) kèm **dịch + lồng tiếng tự động zh→vi** và **render reup**. Giao diện hoàn toàn bằng tiếng Việt, dành cho người **không biết lập trình**. Có **bản thương mại** với hệ thống license cloud, 3 gói (free/pro/unlimited), portal admin và installer Electron tự cài đặt.

> **Chỉ dùng cho học tập và nghiên cứu. Nghiêm cấm sử dụng thương mại.**
> Fork từ [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) (NON-COMMERCIAL LEARNING LICENSE 1.1).
> Video tải về thuộc bản quyền tác giả gốc — người dùng tự chịu trách nhiệm pháp lý.

> Lưu ý: tên hiển thị sản phẩm là **reupo douyin+**, tên kỹ thuật là **LLN-app**.

> ### DEV BẮT BUỘC ĐỌC: [`docs/BAI-HOC-NGHIEM-TRONG.md`](docs/BAI-HOC-NGHIEM-TRONG.md)
> Tổng hợp **bug nghiêm trọng đã gặp + rule bắt buộc** (venv/DB phải ở userData, `sys.executable`, bọc try/except handler, di cư HWID, NSIS preInit, test trên bản đóng gói...). **Đọc trước khi sửa code nền tảng** để không lặp lại lỗi cũ.

---

## Tính năng chính

### Nền tảng cào video

| Nền tảng | Engine | Chế độ |
|----------|--------|--------|
| Douyin | MediaCrawler (Playwright) | Từ khóa, link, kênh |
| Bilibili | MediaCrawler (Playwright) | Từ khóa, link, kênh |
| Xiaohongshu (nội địa) | MediaCrawler (Playwright) | Từ khóa, link |
| RedNote (quốc tế) | MediaCrawler (Playwright) | Từ khóa, link |
| Weibo | MediaCrawler (Playwright) | Từ khóa (ảnh) |
| YouTube | yt-dlp | Từ khóa, kênh, link |
| TikTok | yt-dlp | Link, kênh |
| Twitter (X) | yt-dlp | Link bài đăng |
| Instagram | yt-dlp | Link bài đăng |
| Reddit / Threads / XHS ảnh | Playwright screenshot | Chụp bài + đè phụ đề dịch |

Logo nền tảng riêng (`web/logos/`), kể cả `ig.png`, `reddit.png`, `threads.png`.

**Xem trước & chọn** (`tim_anh.py` metadata-only + modal): nút "Xem trước & chọn" liệt kê bài theo từ khóa/kênh để tick chọn trước khi cào. (Chức năng "Cào ảnh" riêng đã gỡ khỏi UI từ v1.0.1.)

**Tự phân loại video theo thể loại bằng AI (v1.0.11, cải tiến v1.2.3):** Module `phan_loai.py` gọi Gemini web headless để phân loại video render. **v1.2.3**: `_safe_folder()` tự tạo thư mục thể loại mới nếu Gemini đề xuất nhãn mới (không chỉ dùng thư mục hiện có); `_resolve_nhan()` chuẩn hoá nhãn. Cache/index metadata dùng module `index_metadata.py`.

**TikTok không cần đăng nhập (v1.0.12):** TikTok cào công khai qua yt-dlp (như YouTube) — trạng thái đăng nhập trả `"na"` (không áp dụng), không hiện nút đăng nhập. `kiem_tra_login.py` bỏ qua nhánh TT khi nền tảng trong `NEN_TANG_YTDLP`.

**Lịch sử cào (v1.0.12):** Tab "Lịch sử cào" gom jsonl từ mọi nền tảng, lọc theo nền tảng, tìm kiếm từ khóa, đánh dấu đã tải (làm mờ). Route `GET /api/lich_su_cao`.

**Kiểm tra cấu hình máy (v1.0.12):** `GET /api/may_goi_y` — trả kết quả kiểm tra chi tiết RAM/CPU/GPU+VRAM/ổ đĩa kèm verdict (chạy-được / cảnh báo) và khuyến nghị engine theo tier máy. Hàm `_may_goi_y()` trong `web_app.py`. **v1.2.3**: module `thong_tin_may.py` cung cấp đọc RAM/CPU realtime.

**Cache artifact lossless (v1.0.12):** Module `cache_artifact.py` — cache srt/band/dub tái dùng khi render lại cùng video + tham số. API: `duong_cache_dir()`, `video_hash()`, `tinh_key()`, `lay()`, `luu()`, `bat()`. Lưu tại `dirname(DATA_DIR)/_cache_artifact` — bền qua update. Env `VC_CACHE_ON` (mặc định bật) + `VC_CACHE_CAP` (mặc định 3000 MB). **v1.0.15**: TTL tăng từ 1 ngày lên **7 ngày** (tuỳ chỉnh qua `VC_CACHE_TTL_DAYS`), ngăn hết cache sau 1 đêm khi render lại cùng video.

**Viết lại theo phong cách (v1.0.15):** Nút chọn phong cách cho video ĐÃ review — allowlist `_PC` server-side trong `web_app.py` gồm 9 kiểu (`hai_huoc`, `viral`, `kich_tinh`, `cam_xuc`, `doi_thuong`, `hoc_thuat`, `mc`, `van_hoc`, `ngan_gon`); inject vào `--quy-tac` có sẵn (không free-text, không route AI mới). File quy tắc phụ đề mới: `translation_memory/10_subtitle_format.md`.

**Xem trước 5 giây (v1.0.11):** Module `preview_5s.py` tạo đoạn preview ~5s (cắt + áp hiệu ứng hình: blur, logo, watermark — không ASR/dịch/TTS) để user xem bố cục trước khi render full. Route `POST /api/preview5s`.

**Dịch tên file khi cào (v1.0.11):** Module `MediaCrawler/tools/dich_ten.py` dịch tiêu đề tiếng Trung của video sang tiếng Việt khi đặt tên file. Gọi qua `dich_tieu_de(text, platform)`.

**Chia thư mục Bilibili + XHS theo từ khóa/kênh/link (v1.0.11):** `MediaCrawler/store/bilibili/bilibilli_store_media.py` và `MediaCrawler/store/xhs/xhs_store_media.py` thêm tham số `sub_dir` vào `save_video()` — cùng cấu trúc `tu-khoa/<kw>/`, `kenh/<tên>/`, `link/` như Douyin.

**Bilibili tải qua API + cookie (v1.0.11):** Module `cookie_decrypt.py` giải mã cookie Chromium qua Windows DPAPI (AESGCM) — cung cấp class `CookieManager` và hàm `cookie_header(user_data_dir, host_substr)` cho Bilibili tải video có xác thực.

**Fix đăng nhập (v1.0.11):** `kiem_tra_login.py` — XHS dùng `web_session`/`id_token` + DOM arbiter `_xhs_dom`; TikTok kiểm DOM thay vì chỉ kiểm cookie (cookie TikTok còn trên đĩa cả khi phiên đã chết); Douyin dùng `LOGIN_STATUS=='1'` + `localStorage HasUserLogin`.

**Giọng clone lưu bền (v1.0.11):** Giọng clone do khách tải lên lưu tại `userData/clone_voices` (bền qua auto-update, không bị NSIS xóa). Quota clone tính khi dùng lần đầu (`_dem_clone_lan_dau`), không trừ lúc upload.

### Dịch + phụ đề

- **ASR tiếng Trung** — mặc định **"Đọc từ sub" (OCR)**: `ocr_text.py` dùng **RapidOCR PP-OCRv5 ONNX** đọc nguyên văn chữ phụ đề cứng (hardsub) trực tiếp từ frame video. **v1.0.15**: `ocr_dong()` dùng FSM event-detection (so mask sub hiện tại + hysteresis `OCR_HYST`) giảm OCR-call ~484→~120 lần/video (≈ số câu thật, không OCR mọi frame). Vùng che dải sub dò bằng `dai_sub_rapid.py` — `phat_hien_hop_dong()` nâng `n_max` 600→4000 và khe gộp động `max(0.8, stride/fps*2.2)` để xử lý đúng video dài (fix trả 0 câu). Fallback **faster-whisper** (`medium`) khi không có hardsub. Ép engine qua env `ASR_ENGINE=whisper`. FunASR đã gỡ ở v1.0.13.
- **Dịch**: `google` (mặc định, song song), `gemini` (Playwright headless + translation_memory), `ai` (VideoLingo summary-first).
- **Translation memory** (`translation_memory/*.md`) — từ điển tên riêng + quy tắc dịch người dùng tự sửa.
- **AI đa nhà cung cấp** (`ai_dich.py`) — Groq/Gemini/Ollama Cloud/OpenRouter; xoay vòng key khi 429; key mã hoá DPAPI.

### Lồng tiếng zh→vi — nhóm engine ViralVoice

UI phơi engine TTS qua 1 dropdown gộp (render/lồng tiếng), **mặc định = edge**:

- **edge-tts** (mặc định) — cloud, song song nhiều luồng; retry 3 lần → fallback gTTS
- **Piper TTS** (tiếng Việt) — offline ONNX, ~8x realtime CPU; giọng **Banmai FREE** tải qua HTTP Range (`tai_banmai.py`); giọng khác tải on-demand qua **gdown** từ Google Drive (`giong_piper.py`); lưu tại `piper_vn/`
- **OmniVoice** (clone tiếng Việt, GPU NVIDIA) — cài nền tự động (`cai_omnivoice.py`) vào venv riêng `.venv_omnivoice`; synth qua `omnivoice_synth.py`; cắt giọng mẫu qua `cat_giong_clone.py`
- **Kokoro-82M** (tiếng Anh) — `cai_kokoro.py` / `kokoro_synth.py`, venv riêng `.venv_kokoro` tại `LIC_CACHE_DIR/runtime`; đọc qua `localize.long_tieng_kokoro()`; GPU nếu có, else CPU
- ~~**F5-TTS**~~ — **đã gỡ hoàn toàn ở v1.2.0** (`cai_f5.py`, `f5_tts_dub.py`, `slim_f5_model.py` đã xóa)
- **Chuẩn hoá text TTS**: `_chuan_hoa_tts()` ưu tiên `vietnormalizer`; fallback `tts_chuan_hoa.py`
- **Hạn mức lồng tiếng dùng chung mọi đường (v1.2.3):** `_dub_quota_loc()` + `_dub_phut` trong `web_app.py` kiểm tra quota trước mọi path lồng tiếng — kể cả khi trợ lý AI gọi `render_video`; chống bypass.
- **Cân bằng audio**: `tron_audio()` chuẩn hoá giọng dub về peak −1dBFS
- `_ghep_track_khop()` ghép track theo timestamp bằng pydub raw bytes (env `DUB_FILL`, `DUB_MAX_SPEED`, `DUB_CATCHUP`). **v1.0.15**: cơ chế catch-up đồng bộ drift — khi giọng trễ > `DUB_CATCHUP_THRESHOLD` (mặc định 0.3s) thì nén mạnh hơn tới `DUB_CATCHUP_MAX` (mặc định 2.2×) để đuổi kịp dần, giảm lệch tích luỹ trên video dài. Bỏ bước giảm-tốc-trước-render (`xu_ly_chon.py`); drift xử lý tại đây.
- **Piper TTS song song (v1.0.15)**: `long_tieng_piper()` dùng `ThreadPoolExecutor` với pool nhiều `PiperVoice` (`intra_op_num_threads=1` tránh ONNX over-subscribe); số luồng qua env `PIPER_WORKERS` (mặc định `min(cpu_count, 6)`). Tốc độ đọc qua `DUB_PIPER_SPEED` (mặc định 0.9 — nhanh hơn ~10%, ít tràn khe hơn)
- **Che chữ & đè phụ đề** — `dai_sub.py` blur dải phụ đề Trung gốc; dò dải ưu tiên `dai_sub_rapid.py` (RapidOCR clustering TIGHT) → fallback Tesseract → OpenCV. Env `CHE_OCR`, `CHE_CAP` (giới hạn chiều cao blur mặc định 15%)
- **Tách nhạc Demucs** (`_demucs_worker.py`) — subprocess tối ưu RAM
- **Xem trước lồng tiếng** — `dub_preview.py` sinh audio preview trước khi render full
- Output cạnh video: `.zh.srt` / `.vi.srt`, `_phude.mp4`, `_longtieng.mp4`

### Workflow Engine — tab "Quy trình" (v1.2.0)

- **Pipeline gộp** Nguồn → Băm → Render → Xuất trong 1 tab block-card; nút **"🚀 Bật tự động"** kích hoạt chạy tự động cả chuỗi. Route `/api/workflow_run`, `/api/workflow_auto_on`, `/api/workflow_auto_off`, `/api/workflow_auto_get`; trạng thái lưu trong `workflow_auto.json` (`FILE_WFAUTO`).
- **Module `render_worker.py`** — warm-process render; giữ subprocess render sẵn để giảm cold-start mỗi job.
- **Tab "Theo dõi kênh" và "Hẹn giờ" đã gộp vào tab Quy trình** (không còn tab riêng). Lịch hẹn giờ qua Windows Task Scheduler (`chay_tu_dong.bat` / `theo_doi.bat` dùng `%APPDATA%\viralcrawl-desktop\runtime\venv`).
- **Băm nhỏ cải tiến (v1.2.0):** RESUME từ điểm bị dừng; video > 40 phút chia đều; tiến trình ở mức ưu tiên `BELOW_NORMAL` (tránh đụng độ tài nguyên).
- **Render tích lũy `(N)_xuly.mp4`** — lần render thứ N ghi vào tên có chỉ số, tránh đè bản cũ. Tab "Video đã render" (`fMode="render"`) liệt kê bản đã render.
- **Pipeline FFmpeg reup** (`xu_ly_video.py`) — cắt, lật, watermark ảnh, watermark chữ chạy, che phụ đề, nhạc nền, tăng tốc, chỉnh màu, đổi khung 9:16 nền mờ; NVENC auto, fallback CPU.
- **WinError 206 fix (v1.2.2):** hàm `_fc_args()` trong `localize.py` ghi filter_complex ra file tạm rồi truyền `-filter_complex_script <path>` thay vì inline, tránh giới hạn 32767 ký tự lệnh Windows.
- **Băm scene-cut (v1.2.2):** phát hiện cảnh bằng PySceneDetect, cắt đúng ranh giới cảnh (không giật).
- **Đăng bài** (`gom_dang_bai.py`) — gom bản render theo trang; tích hợp đăng FB tự động qua LLN Page.

### Lưu trữ bền vững (v1.0.7+)

Video cào và video đã render nằm **ngoài thư mục cài** — sống sót qua auto-update:

- Module `data_dir.py` giải quyết 1 gốc dữ liệu duy nhất, đặt env `MC_DATA_DIR` / `VC_PROCESSED_DIR` cho mọi subprocess.
- Ưu tiên: env `MC_DATA_DIR` > user chọn (`app_settings.json` key `data_root`) > `userData` > thư mục app (dev).
- `base_config.SAVE_DATA_PATH` (MediaCrawler) đọc env `MC_DATA_DIR`.
- Module `chon_thu_muc.py` (tkinter native) cho user chọn thư mục lưu video — **có thể chọn ổ bất kỳ (C:, D:, E:...)**.
- Endpoint `GET /api/data_dir` trả thông tin + dung lượng trống; `POST /api/data_dir` action `pick` hoặc thay đổi gốc.
- Tab Cài đặt có card "Thu muc luu video" — hiển thị đường dẫn + dung lượng + nút Doi/Mo.
- **v1.0.8 — fix cross-drive path crash:** helper `_rel_goc()` trong `web_app.py` fallback sang đường dẫn tuyệt đối khi `os.path.relpath` ném `ValueError` do khác ổ đĩa (ví dụ video ở `D:\Reel`, app ở `C:`). Fix 7 điểm dùng `relpath` trong file listing, render queue, render-progress và queue-detail.

### Hệ thống gói 3 mức

| Tính năng | FREE | PRO | UNLIMITED |
|-----------|------|-----|-----------|
| Cào video | 20/ngày | Không giới hạn | Không giới hạn |
| Lồng tiếng | 5 video hoặc ≤10 phút/ngày | 20 video hoặc ≤60 phút/ngày | Không giới hạn |
| Giọng nâng cao | Mặc định | Tất cả | Tất cả |
| Clone giọng | 0 | 3 lượt (tích luỹ) | Không giới hạn |
| Theo dõi kênh | 0 | 3 kênh | Không giới hạn |
| Trợ lý AI | Không | Không | Có |

### Giao diện

- **Dashboard web** (`web_app.py` :8770) — Python stdlib `ThreadingHTTPServer`; bảo mật DNS-rebinding + CSRF nonce gate (POST/PUT/DELETE yêu cầu header `X-CSRF-Token`); CSRF nonce hết hạn (server restart) — client tự xin lại qua `_renewCsrf()` + retry 1 lần (không cần F5 tay); ~90 route `/api/*`; **rednote và xhs là 2 nền tảng riêng** (profile/data/domain độc lập) kể từ v1.0.14; port override qua env `VC_PORT`. **v1.0.15**: ETA cào hiển thị MB/s × size (`_eta_dir`/`_crawl_worker`); render XONG → tự về sub-tab Edit (`web/index.html`); tab **Lồng tiếng** độc lập đã gộp vào tab **Render** (sub-tab Edit / Lồng tiếng) — không còn tab riêng. Route `/api/dub/*` backend vẫn còn nhưng UI không gọi trực tiếp nữa. **v1.1.1**: checkbox **"Cào không trùng"** (`caoKhongTrung`) hiện khi Douyin + tìm-từ-khóa/theo-kênh → truyền `khong_trung` vào `web_app.py:chay_crawl` → set `MC_DEEP_NEW=1`; sort lưới Xem trước: video mới tinh (`da_thay=0`) lên trên, đã-thấy-chưa-tải giữa, đã tải (`da_tai`) xuống dưới (`_gan_badge` + `web_app.py`); đăng xuất Douyin xóa `Local Storage`/`Session Storage` (`_logout_nentang` trong `web_app.py`) — mở login lại không bị tự đóng cửa sổ; 3 hàm JS (`splitTts`, `PIPER_VOICES`, `integratePiperVoices`) được khôi phục vào `web/index.html` — fix ReferenceError khi render với giọng Piper (regression v1.0.15)
- **Kiểm tra đăng nhập LIVE** (`kiem_tra_login.py`) — Douyin dùng tín hiệu pong thật (`LOGIN_STATUS=='1'` / localStorage `HasUserLogin=='1'`); XHS và rednote dùng `web_session`/`id_token` + DOM `_xhs_dom`. **v1.2.3 — fix login xanh-giả rednote/xhs:** DOM `__INITIAL_STATE__.user.loggedIn` làm trọng tài tại `kiem_tra_login.py`; `_xac_minh_sau_dong()` re-check trạng thái sau khi đóng cửa sổ login (threading, `web_app.py`); debounce chống SPA-race.
- **Song ngữ** (vi/en) — sidebar SVG outline icon, logo nền tảng PNG, 1 dropdown `#appLang`

### Bảo mật (v1.0.9–v1.0.11 — đã implement)

- **Web backend**: CSRF nonce `_guard()` fail-CLOSED (POST/PUT/DELETE yêu cầu header `X-CSRF-Token` khớp `CSRF_NONCE`); `_bam_serve_files` allowlist file-level cho `/video`; whitelist `out_dir` chỉ kiểm `os.path.isabs` + chặn prefix `-` (hỗ trợ user chọn thư mục bất kỳ, CSRF bảo vệ); chặn arg-injection `--flag=value`; error handler trả generic (traceback chỉ log stderr)
- **Credential at-rest**: `secret.key` MARKER `DPAPI1:`, ghi atomic `os.replace`, fail-CLOSED Windows nếu DPAPI lỗi (`khach_db.py`); cookie phiên ghi temp dir + dọn `atexit`/`finally`; SSRF guard `_url_an_toan` trong `tai_ytdlp.py` + `enable_file_urls=False` (chặn `file://`, loopback, RFC1918)
- **Pipeline render**: filter-injection whitelist `_color_an_toan`/`_font_an_toan` (drawtext), cross-drive `_rel_an_toan`, delete-orig chỉ khi dst>100KB, temp-leak mkstemp+finally
- **License server**: webhook HMAC-SHA256(raw_body+timestamp) + chống replay; rate-limit DB-backed (`login_attempts`); partial-unique `uq_devices_hwid_active ON devices(hwid) WHERE active` (1 máy=1 license active); `them_admin.py` chọn backend qua env `LIC_DB`; churn cap `LIC_CHURN_MAX` (1 tài khoản=1 máy)
- **Tier enforcement**: `_can()` gate `/api/ai` → `tro_ly_ai` (UNLIMITED only); `_block()` DRY quanh `_lim()`
- **XSS**: `esc()` escape 5 ký tự; CSP `script-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'`

---

## Bản thương mại (license + installer) — ĐÃ LIVE

- **License server** (`license_server/`) — FastAPI, SQLite hoặc Postgres/Supabase mirror; device binding HWID; tier free/pro/unlimited; offline grace 7 ngày
  - **Live**: `https://license-server-cyan-kappa.vercel.app` (Vercel sin1 + Supabase ap-southeast-1)
  - Bản đóng gói (`app.isPackaged`) LUÔN dùng `LIC_SERVER_PROD`, không cho env override
  - **Ràng buộc 2 chiều**: 1 tài khoản = 1 máy + 1 máy = 1 tài khoản
  - `them_admin.py` thêm admin, chọn backend qua env `LIC_DB` (SQLite hoặc Postgres)
  - `desktop/build_lic.ps1` + `desktop/lic_cli.spec` — script đóng gói `lic_cli.exe` (chống crack). **Lưu ý:** v1.0.11 chưa build lic_cli.exe; app dùng `lic_cli.py` thô.
- **Portal admin** — dashboard (`/portal`): 6 KPI cards, 3 chart inline SVG, smart filter, phân trang
- **Mô hình license**: đăng ký 1 lần → FREE + gắn HWID → cache offline → không login lại. Pro/Unlimited hết hạn → FREE, app vẫn mở
- **Installer Electron** (`desktop/`) — `LLN-app-Setup-x.y.z.exe`, bundle uv+node+ffmpeg
  - Lần đầu mở tự `uv sync` + `playwright install chromium`; venv + Chromium + marker ở `userData/runtime/` (bền qua update)
  - License cache ở `userData` qua `LIC_CACHE_DIR`; DB khách ở `userData` qua `KHACH_DB_DIR`
- **GPU tự động**: `hasNvidia()` → Bước 3/3 tự `uv sync --extra gpu` CHỈ máy NVIDIA
- **Tự cập nhật** — `electron-updater` tải từ máy chủ cập nhật; delta download blockmap

---

## Nâng cấp gói

Liên hệ Zalo **0865.060.530** hoặc vào tab "Gói của tôi" trong app → "Nâng Cấp Gói".

* **Gói Tháng (Cơ bản):** **299.000đ / tháng**. Tặng kèm video hướng dẫn sử dụng cơ bản.
* **Gói Năm (Mở rộng):** **999.000đ / năm**. Tặng kèm video hướng dẫn + **Bộ 3 Quà Tặng Độc Quyền**.
* **Gói Vĩnh Viễn (Mở rộng):** **1.799.000đ / trọn đời**. Tặng kèm video hướng dẫn + **Bộ 3 Quà Tặng Độc Quyền**.

*Bộ 3 Quà Tặng Độc Quyền khi mua Gói Năm/Vĩnh Viễn bao gồm:*
1. Danh sách 20 kênh nội dung reup nổi tiếng bên Trung Quốc.
2. Hướng dẫn chi tiết cách upload tự động lên đa nền tảng (Facebook Reels, TikTok, YouTube Shorts).
3. Báo cáo phân tích Top 10 ngách reup tiềm năng nhất tại thị trường Trung Quốc.

---

## Yêu cầu hệ thống

- Windows 10/11 (x64)
- Python 3.11 (tool) — tự cài qua `uv sync`
- Node.js portable — bundle sẵn trong installer
- FFmpeg — bundle sẵn trong installer (hoặc `winget install Gyan.FFmpeg` khi cài thủ công)
- RAM khuyến nghị 8 GB (dùng phụ đề/lồng tiếng)

---

## Cài đặt

### Bản installer (khuyến nghị)

Tải `LLN-app-Setup-1.3.12.exe` từ nguồn cung cấp.

1. Chạy installer — cài vào `%LOCALAPPDATA%\Programs\LLN-app\`
2. Lần đầu mở: màn setup tự động (`uv sync` + `playwright install chromium`)
3. Tạo tài khoản và gắn máy (gói FREE tự cấp)
4. Vào thẳng tool

> SmartScreen: bấm "More info" → "Run anyway" (installer chưa ký số).

### Cài thủ công (developer)

```
Double-click: CAI-DAT.bat   → cài môi trường (1 lần)
Double-click: MO-WEB.bat     → mở http://127.0.0.1:8770
```

---

## Cấu trúc thư mục (tóm tắt)

```
repo/
├── MediaCrawler/           Lõi cào (fork NanmiCoder, đã patch); venv riêng .venv (uv, Py3.11)
├── license_server/         Hệ thống license thương mại (cloud, độc lập)
│   ├── server.py           FastAPI endpoints; lic_db.py (SQLite) / lic_db_pg.py (Postgres mirror)
│   ├── portal.html         Dashboard admin
│   └── api/index.py        Handler Vercel serverless
├── desktop/                Đóng gói Electron installer (productName "ViralCrawl")
│   ├── main.js             Luồng Setup→License→Tool; auto-update; killByPort(8770)
│   ├── setup.js            Setup bền vững (venv+Chromium ở userData, sống qua update)
│   └── build/              fetch_tools / stage_app / after_build (PS1)
├── web/                    Giao diện web (index.html ~290KB, logos/, lang_en.json)
├── translation_memory/     Quy tắc + từ điển dịch user (nạp *.md top-level)
├── giong_mau/              Giọng mẫu clone (nam.wav, nu.wav + upload/) — F5-TTS đã gỡ v1.2.0
├── docs/                   Tài liệu dự án
│
├── phan_loai.py            Tự phân loại video render theo thể loại (AI Gemini web headless)
├── preview_5s.py           Preview nhanh ~5s (cắt + hiệu ứng hình, không ASR/dịch/TTS)
├── index_metadata.py       Cache/index metadata video (dùng bởi phan_loai.py)
├── cookie_decrypt.py       Giải mã cookie Chromium DPAPI (CookieManager, cho Bilibili API)
├── cache_artifact.py       Cache LOSSLESS srt/band/dub tái dùng khi render lại (v1.0.12)
├── giong_piper.py          Dict giọng Piper + tải on-demand qua gdown; PIPER_DIR qua _piper_dir_rw() (v1.0.13)
├── tai_banmai.py           Tải giọng Banmai FREE qua HTTP Range; _piper_dir_rw() bền update (v1.0.13)
├── cai_omnivoice.py        Tự cài OmniVoice nền vào .venv_omnivoice (GPU NVIDIA, v1.0.12)
├── omnivoice_synth.py      Synth TTS OmniVoice trong .venv_omnivoice (v1.0.12)
├── cai_kokoro.py           Tự cài Kokoro-82M vào .venv_kokoro (EN, v1.2.0)
├── kokoro_synth.py         Synth TTS Kokoro trong .venv_kokoro (v1.2.0)
├── render_worker.py        Warm-process render (v1.2.0)
├── thong_tin_may.py        Đọc RAM/CPU realtime (v1.2.3)
├── lay_kenh_info.py        Lấy thông tin kênh (v1.2.0)
├── phan_tich_profile.py    Phân tích profile kênh (v1.2.0)
├── xhs_browser.py          Trình duyệt XHS helper (v1.2.0)
├── cat_giong_clone.py      Cắt giọng mẫu clone về 3–12s (v1.0.12)
├── dub_preview.py          Xem trước audio lồng tiếng trước khi render full (v1.0.12)
├── ocr_text.py             OCR đọc chữ phụ đề cứng bằng RapidOCR PP-OCRv5 ONNX; tự dò CUDA→CPU (v1.0.13)
├── dai_sub_rapid.py        Dò dải sub bằng RapidOCR det + clustering TIGHT (v1.0.13)
├── tts_chuan_hoa.py        Chuẩn hoá text TTS: số/ngày/tiền (port NghiTTS, fallback)
├── web_app.py              Web server CHÍNH (:8770) — ~90+ route /api/*; TIER gating
├── data_dir.py             Giải quyết gốc lưu data BỀN qua update (v1.0.7)
├── chon_thu_muc.py         Native folder picker (tkinter) cho user chọn thư mục lưu (v1.0.7)
├── khach_db.py             DB tài khoản tool (SQLite + Fernet + DPAPI; usage_gioihan)
├── localize.py             Pipeline Dịch & phụ đề + lồng tiếng (ASR/dịch/TTS/che chữ/burn sub)
├── ai_dich.py              AI dịch đa provider (Groq/Gemini/Ollama/OpenRouter)
├── xu_ly_video.py          Render reup tự động (poll data → ffmpeg → processed_videos)
├── xu_ly_chon.py           Render video được tick + localize → (N)_xuly.mp4 (render tích lũy)
├── cat_nho.py              Băm video dài → clip ngắn theo cảnh (PySceneDetect) + 9:16
├── tai_ytdlp.py            Tải YouTube/TikTok/Twitter(X)/Instagram/Reddit qua yt-dlp
├── kiem_tra_login.py       Kiểm tra đăng nhập LIVE (API/DOM, không false green khi hết phiên)
├── theo_doi.py/chay_tu_dong.py   Theo dõi kênh + cào hẹn giờ (Windows schtasks)
├── bao_mat_key.py          Mã hoá API key (Windows DPAPI → key_store.dat)
├── CAI-DAT.bat             Cài môi trường chính (1 lần)
└── MO-WEB.bat              Mở giao diện web (:8770)
```

---

## Tài liệu chi tiết

| Tài liệu | Nội dung |
|----------|---------|
| [docs/project-overview-pdr.md](docs/project-overview-pdr.md) | Tổng quan dự án, PDR, model license, gói cước, rủi ro |
| [docs/system-architecture.md](docs/system-architecture.md) | Kiến trúc, luồng register-device + tier, Vercel+Supabase |
| [docs/code-standards.md](docs/code-standards.md) | Quy ước code, pattern mirror lic_db, env-based config |
| [docs/deployment-guide.md](docs/deployment-guide.md) | Deploy: installer, auto-update, VPS/Docker, Vercel+Supabase |
| [docs/project-roadmap.md](docs/project-roadmap.md) | Trạng thái tính năng: đã xong / còn lại |
| [HUONG-DAN.md](HUONG-DAN.md) | Hướng dẫn người dùng cuối |

---

## Lưu ý quan trọng

- Không cào quá nhiều cùng lúc; dùng nick phụ. Cần đăng nhập QR lại khi phiên hết hạn. Bị treo → `DON-DEP.bat`
- Thương mại hoá cần xin phép tác giả MediaCrawler
- Task Scheduler giữ tên `ToolCaoVideoTheoDoi/TuDong/Render` — KHÔNG đổi tên
- **GPU Whisper**: tự dùng NVIDIA nếu có, fallback CPU; `nvidia-cu12` là optional (`uv sync --extra gpu`)
- **ASR mặc định = "Đọc từ sub" (RapidOCR PP-OCRv5)** khi có hardsub → fallback faster-whisper; FunASR đã gỡ ở v1.0.13; **dịch mặc định = Google**. OCR dò hardsub sát đáy đến `y_hi=0.995` (99.5% khung). **v1.0.15**: OCR FSM event-detection giảm số lần gọi OCR từ ~484→~120/video; `phat_hien_hop_dong()` `n_max=4000`, khe gộp động → xử lý đúng video dài. Tuỳ chỉnh: `OCR_CHK` (nhịp kiểm tra, giây), `OCR_XOR` (ngưỡng phát hiện đổi chữ), `OCR_HYST` (hysteresis frame). **v1.1.1**: fix regression render Piper (xem giao diện bên trên)
- Windows Scheduled Task: máy phải bật và đăng nhập khi tác vụ chạy
- **zhconv/ (v1.2.2):** thư viện chuyển phồn↔giản thể đã được **vendor** vào repo (`repo/zhconv/`), dùng bởi `localize.py` và `ocr_text.py`; không cần cài ngoài. Đã tích hợp vào `stage_app.ps1` (robocopy).
- **Dọn .srt sau render (v1.2.3):** `_don_srt_canh_video()` xóa file `.srt` tạm cạnh video sau khi render xong. Giữ lại: đặt env `VC_GIU_SRT=1`.
- **Douyin retry 风控 (v1.2.2):** `core.py` tự retry khi gặp lỗi 风控 (anti-bot Douyin) — giảm cào 0 video do fingerprint.
