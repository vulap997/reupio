# TOÀN CẢNH: ViralCrawl × LohaPage

> Hai công cụ **RIÊNG**, nối nhau qua **THƯ MỤC** (không gọi API trực tiếp):
> **ViralCrawl** (cào + render video) → chép file vào `uploads/` → **LohaPage** (tự đăng Facebook) → Facebook.
> Mỗi tool có **license riêng**.

```
[ViralCrawl] ──▶ 📁 uploads/<Page>_<id>/ ──▶ [LohaPage] ──▶ Facebook
 cào+render        (video, caption ở tên file)   tự đăng       Reels/Video/Ảnh
```

---

## TOOL 1 — ViralCrawl (cào + render)

App Electron. `web_app.py` (server stdlib, port **8770**) phục vụ `web/index.html` + ~70 route `/api/*`.
Cào: **MediaCrawler** (Douyin/Bili/XHS/Weibo, venv riêng) + **yt-dlp** (YouTube/TikTok).
Render: faster-whisper (ASR tiếng Trung) → Gemini dịch → TTS lồng tiếng → ffmpeg che chữ + burn sub. Máy **CPU-only**.

### Cấu trúc (rút gọn)

```
toolcaovideo/
├── web_app.py          UI CHÍNH: server 8770, ~70 route /api/*, hàng đợi render
├── web/index.html      toàn bộ UI (SPA 1 file)
├── localize.py         dịch + lồng tiếng + render (ASR→dịch→TTS→ffmpeg)
├── xu_ly_chon.py       render video được tick (transforms + localize)
├── kenh_nguon.py       store "Kênh nguồn" (profile kênh + đích LohaPage)
├── gom_dang_bai.py     giao_loha()/folder_loha() — GIAO file cho LohaPage
├── tao_caption.py      AI tạo tiêu đề + caption
├── phan_loai.py        AI phân loại video theo thể loại
├── MediaCrawler/       fork cào Douyin/Bili/XHS/Weibo (venv riêng, uv)
├── desktop/main.js     Electron main (spawn web_app, license, cửa sổ)
└── license_server/     client license (lic_cli/lic_client) + server (Vercel)
```

### 4 luồng lấy video → đích

| Luồng | Cách | Đích đăng |
|---|---|---|
| **Cào từ khóa / link** | MediaCrawler / yt-dlp → tick chọn → render | Tay hoặc phân loại |
| **Kênh nguồn** | Theo kênh: lịch mỗi ngày tải N video mới → render → giao | **LohaPage** theo page gán sẵn |
| **Phân loại** | Sau render, AI đoán thể loại → xếp folder | Folder thường HOẶC **LohaPage** |
| **File đã tải** | Chọn video có sẵn → render | Tay |

### Luồng tự động "Kênh nguồn"

```
Cấu hình 1 lần: kênh → gán ĐÍCH (page_id / nhóm) + hashtag + lịch (N/ngày)
   │  worker mỗi 60s: tới giờ + chưa chạy hôm nay
   ▼
① re-cào metadata (lấy video mới)   ② tải N video CHƯA tải
③ enqueue render, kèm marker kn_giao = {thư mục LohaPage, caption}
④ render (dịch+lồng tiếng+burn sub) → <ten>_xuly.mp4
⑤ _kn_giao_sau_render → chép _xuly.mp4 vào uploads/<Page>_<id>/
        (tên file = caption; ghi thêm .txt — LohaPage BỎ QUA .txt)
```

### Quyền & license (tầng ViralCrawl)

Cờ `lohapage` ký trong token license (server **Vercel**) → gate 2 tab **Kênh nguồn** + **Đăng bài**.
Chuỗi: `lic_cli status` → `main.js env VC_LOHAPAGE` → `web_app.LOHAPAGE_OK`.
Chưa mua LohaPage → ẩn tab Kênh nguồn, khoá tab Đăng bài; gate cả **endpoint LẪN 4 worker nền** (không bypass qua lịch).

---

## TOOL 2 — LohaPage (tự đăng Facebook)

App Electron sống trong **system tray**. Cửa sổ load `localhost:3088` = **api-server.js (Express)** vừa serve React UI vừa là REST API. DB = **SQLite** (`%APPDATA%/LohaAutomation/data.db`), token mã hoá **DPAPI**.

### Cấu trúc (mono-repo)

```
loha-automation/
├── desktop/src/                ELECTRON (main process)
│   ├── main.js         khởi động: tray → DB → license → server → watcher → scheduler
│   ├── api-server.js   (86KB) HTTP 3088: serve React UI + toàn bộ REST API
│   ├── database.js     (75KB) SQLite: pages, posts, tokens, groups, pools, license
│   ├── facebook.js     (50KB) đăng Graph API (Reels 3-pha / video / ảnh / story)
│   ├── scheduler.js    (48KB) cron: đăng pending, auto-schedule, refresh token...
│   ├── file-service.js (23KB) chokidar watch uploads/ → tạo post
│   ├── license.js      (19KB) license Supabase + HMAC + offline grace 72h
│   └── schedule-rule.js, telegram.js, proxy.js, i18n.js, updater.js...
├── web/                        React UI (Vite) — api-server serve dist
├── admin-web/                  web quản trị
├── license-server/supabase/    SERVER LICENSE riêng (Supabase Edge Functions)
├── workflows/                  workflow JSON (facebook-post, token-refresh, tiktok...)
└── data.db → %APPDATA%/LohaAutomation/
```

### Pipeline: file → đăng

```
watcher (chokidar + quét lại 30s) thấy .mp4 mới trong uploads/
   ▼
file-service.importFile:
   ├─ CHỈ nhận .mp4/ảnh (.txt BỎ QUA)
   ├─ folder <Tên>_<pageID> → page_id (lastIndexOf '_', ≥5)
   │  hoặc __group_<slug> → pickNextPageForGroup (round-robin)
   ├─ getContentForFile: 'filename' (caption = TÊN FILE, cắt tại #) | 'random' (pool)
   ├─ check LICENSE + slot (chưa kích hoạt / hết slot → BỎ QUA)
   ├─ createPost(status='draft')
   ├─ page có schedule rule + chưa đạt cap/ngày → 'pending' + giờ
   └─ chép file sang done/
   ▼
scheduler.js (cron */2 phút) processPendingPosts:
   ├─ chặn: telegram-pause / license-off / fb_throttle_until
   ├─ bài >10' → đẩy FB "native scheduling"; ≤10'/quá hạn → đăng NGAY (1/page/tick)
   ├─ daily cap vượt → dời +24h;  pickToken (xoay vòng) → worker ≤10 song song
   └─ atomic claim (pending→processing) → facebook.postToFacebook
   ▼
facebook.js (Graph API v18.0, PAGE token):
   reel  → 3-pha (start→transfer→finish); lỗi tỷ lệ/thời lượng → fallback /videos
   video → <50MB single-shot | ≥50MB resumable chunk (8→4MB, đổi host)
   image/text → /photos, /feed
   message = caption + "\n\n" + hashtags   (KHÔNG giới hạn độ dài)
```

### Scheduler (cron)

| Chu kỳ | Job |
|---|---|
| **\*/2 phút** | **đăng bài pending** (tick chính) |
| \*/5 phút | draft → pending |
| \*/3 phút | sync bài scheduled đã đăng chưa |
| 4h / 4:30h | refresh token pool |
| 6h | revalidate license |

**Timing rule:** `interval` (giãn cách giờ, **tối thiểu 20 phút** — luật FB) HOẶC `fixed_times` (khung giờ) + `active_hours` + jitter ngẫu nhiên. Cap FB **75 ngày**. Nối đuôi bài pending cuối.

### Đăng & xử lý lỗi

- **Graph API chính thức** (page token), **không** automation trình duyệt. Ưu tiên Reels; loại đăng do `content_type` quyết định (LohaPage không tự đo video).
- 429 → throttle toàn app 10 phút. Token hết hạn → thử token khác 1 lần. Lỗi khác → `failed` ngay (không retry vòng).
- Xoay nhiều **user token** (least-recent/random/round-robin) chống rate-limit; nhiều page/nhóm.

### License (tầng LohaPage — TÁCH ViralCrawl)

Server RIÊNG **Supabase** (ViralCrawl là Vercel). HMAC-SHA256 + machine-id. Gói theo `max_pages`: trial 5 · starter 20 · pro 60 · unlimit ∞. Offline grace 72h + chống chỉnh đồng hồ. Hết hạn → dừng auto-import + scheduler.

---

## ĐIỂM NỐI — contract giao file

Cầu nối duy nhất giữa 2 tool. ViralCrawl ghi, LohaPage đọc — phải khớp từng chi tiết.

| Thành phần | ViralCrawl ghi | LohaPage đọc | |
|---|---|---|---|
| Tên folder | `<Tên>_<page_id>` / `__group_<slug>` | `lastIndexOf('_')`, prefix `__group_` | **khớp** |
| page_id | bắt buộc ≥5 ký tự | `if len<5 → bỏ` | **khớp** |
| Caption | nhét vào **TÊN FILE**: `Tiêu đề #tag.mp4` | mode 'filename' → cắt tại `#` | **khớp** |
| Sidecar `.txt` | có ghi (caption đầy đủ) | **bỏ qua** (chỉ đọc .mp4/ảnh) | dư thừa |

### Hai license độc lập

| | ViralCrawl | LohaPage |
|---|---|---|
| Server | `…vercel.app` | `…supabase.co` |
| Gate cái gì | cờ `lohapage` → mở/khoá tab Kênh nguồn + Đăng bài | `max_pages` slot → cho/không cho auto-import + đăng |
| Khách cần | **CẢ HAI** license mới chạy trọn (mua tool này chưa đủ) | |

---

## Toàn trình end-to-end (1 video)

```
[ViralCrawl]                                        [LohaPage]
theo dõi kênh ─▶ tải video ─▶ dịch+lồng tiếng+render ─▶ giao file
                                                            │
                              uploads/<Page>_<id>/Tiêu đề #tag.mp4
                                                            ▼
                              watcher ─▶ tạo post(draft) ─▶ theo lịch → pending
                                                            ▼
                              scheduler ─▶ Graph API ─▶ ĐĂNG Facebook (Reels/Video)
                                                            ▼
                              ✓ posted  (hoặc failed → thử token khác / báo Telegram)
```

Không cần thao tác sau khi cấu hình 1 lần: ViralCrawl tự cào→render→giao theo lịch; LohaPage tự đăng theo lịch page. Mỗi bên có license + quota riêng.

---

## Điểm cần lưu ý (rủi ro / dễ vấp)

| # | Vấn đề | Hệ quả |
|---|---|---|
| 1 | Page bên LohaPage **chưa đặt schedule rule** | Bài chỉ nằm **draft** — không tự đăng |
| 2 | Page để content mode **'random'** | Caption ViralCrawl **bị bỏ**, dùng pool riêng của LohaPage |
| 3 | **2 license** lệch trạng thái (mua 1, chưa mua 1) | Cấu hình được nhưng không đăng — hoặc ngược lại |
| 4 | Vượt cap bài/ngày hoặc hết slot LohaPage | Âm thầm giữ draft / bỏ bài — ViralCrawl **không biết** |
| 5 | Bài đẩy FB "native scheduling" (>10 phút) | Phụ thuộc FB đăng đúng giờ; sai thì sync mới phát hiện |
| 6 | `content_type` sai loại (video dọc mà không phải 'reel') | Không lên Reels — LohaPage không tự đo video |
| 7 | Chưa test THẬT: login+cào+render+đăng FB liền mạch | Mỗi mảnh test ảo OK; mạch liền cần 2 app live + 2 license |

---

*Nguồn: đọc trực tiếp mã 2 repo — ViralCrawl (`web_app.py`, `kenh_nguon.py`, `gom_dang_bai.py`) · LohaPage (`file-service.js`, `database.js`, `facebook.js`, `scheduler.js`, `license.js`). Số liệu test = test ảo headless, chưa chạy live end-to-end.*
