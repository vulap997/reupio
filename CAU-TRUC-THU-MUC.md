# CẤU TRÚC THƯ MỤC — ViralCrawl & LohaPage (có chú thích)

> Liệt kê thật, gom theo CHỨC NĂNG cho dễ hiểu. Bỏ qua: `node_modules/`, `.git/`, `__pycache__/`, venv, và các thư mục DỮ LIỆU (video/giọng thật của khách).

---

# 1) VIRALCRAWL — `C:\Users\vannh\viralcrawl\toolcaovideo`

App cào + render. Có **66 file .py ở thư mục gốc** — dưới đây gom theo nhóm.

## 1.1 — Lõi web / server / hệ thống
```
web_app.py          ⭐ UI CHÍNH: server port 8770, ~70 route /api/*, hàng đợi render
web/index.html      ⭐ toàn bộ giao diện (SPA 1 file)
khach_db.py         DB khách (SQLite): đăng nhập khách, quota gói, usage
data_dir.py         giải quyết thư mục lưu DATA (bền qua auto-update)
cache_artifact.py   cache srt/dub lossless (render lại nhanh)
ngon_ngu.py         ngôn ngữ đích (vi/en)  ·  log_i18n.py  dịch log sang EN
nen_tang_helper.py  helper nền tảng  ·  index_metadata.py  index video đã tải (chống trùng)
```

## 1.2 — CÀO video (crawl)
```
tim_anh.py          cào metadata/preview (search / creator)
tai_ytdlp.py        tải YouTube / TikTok qua yt-dlp
mo_dang_nhap.py     mở cửa sổ đăng nhập nền tảng  ·  kiem_tra_login.py  kiểm tra login
cookie_decrypt.py   giải mã cookie trình duyệt  ·  xhs_browser.py  tải XHS qua browser
theo_doi.py         theo dõi kênh (Windows schtasks)  ·  video_moi.py  phát hiện video mới
chay_tu_dong.py     cào hẹn giờ (schtasks)
```

## 1.3 — KÊNH NGUỒN / ĐĂNG BÀI (→ LohaPage)
```
kenh_nguon.py       ⭐ store profile kênh + đích LohaPage (page/nhóm + lịch)
gom_dang_bai.py     ⭐ giao_loha() / folder_loha() — GIAO file cho LohaPage
tao_caption.py      AI tạo tiêu đề + caption  ·  phan_loai.py  AI phân loại thể loại
doi_ten_kenh.py     đổi tên kênh  ·  lay_kenh_info.py  lấy info kênh
phan_tich_profile.py  phân tích profile kênh
bili_goi_y.py / yt_goi_y.py   gợi ý kênh (bilibili / youtube)
```

## 1.4 — DỊCH / LỒNG TIẾNG / RENDER (localize)
```
localize.py         ⭐ LÕI: dịch + lồng tiếng + render (ASR→dịch→TTS→ffmpeg)
xu_ly_chon.py       render video được tick (transforms + localize)
xu_ly_video.py      rerender tự động (poll data → processed_videos)
render_worker.py    worker render bền (giữ nóng model)
phu_de.py           phụ đề (whisper + google dịch)  ·  dan_sub.py  dán sub
dich_gemini_web.py  dịch qua Gemini web  ·  ai_dich.py  AI dịch đa provider (Groq/Gemini/Ollama)
ocr_text.py / ocr_anh.py / ocr_timing.py    OCR chữ Trung (đọc hardsub)
dai_sub.py / dai_sub_ocr.py / dai_sub_rapid.py    dò DẢI sub gốc để che
lam_sub_anh.py      làm sub cho ảnh
```

## 1.5 — GIỌNG (TTS)
```
giong_piper.py      Piper (giọng VN)  ·  tai_banmai.py  tải giọng Banmai
kokoro_synth.py     Kokoro (giọng EN)  ·  omnivoice_synth.py  OmniVoice (clone, cần GPU)
supertonic_synth.py Supertonic  ·  cat_giong_clone.py  cắt giọng mẫu clone
tts_chuan_hoa.py    chuẩn hóa text đọc (số/ngày → chữ)  ·  dub_preview.py  nghe thử giọng
_demucs_worker.py   tách nhạc nền khỏi giọng
```

## 1.6 — BĂM / ẢNH / khác
```
cat_nho.py          băm video thành clip nhỏ  ·  lam_video_anh.py  ghép ảnh thành video
preview_5s.py       preview 5 giây  ·  chup_bai.py  chụp bài
tao_watermark_mau.py / tao_icon.py    watermark / icon
_gen_lang_en.py / _lang_overrides.py  sinh + ghi đè bản dịch EN
```

## 1.7 — CÀI ĐẶT / MÁY / BẢO MẬT
```
cai_gpu.py / cai_kokoro.py / cai_omnivoice.py    cài phụ thuộc
chan_doan_gpu.py    chẩn đoán GPU  ·  thong_tin_may.py  thông tin máy
chon_thu_muc.py     hộp thoại chọn thư mục (tkinter)
bao_mat_key.py      mã hóa API key bằng DPAPI (→ key_store.dat)
test_login_cao.py   test
```

## 1.8 — Thư mục con
```
MediaCrawler/       ⭐ fork cào Douyin/Bili/XHS/Weibo (venv RIÊNG, uv, Python 3.11)
web/                UI: index.html + lang_en.js/json + logos/
desktop/            ELECTRON: main.js, preload.js, setup.html/js, package.json
   └── build/       script đóng gói NSIS: build_installer.ps1, stage_app.ps1, installer.nsh...
license_server/     LICENSE (server Vercel): lic_cli.py, lic_client.py, lic_db.py,
                    server.py, portal.html, hwid.py, api/, migrations/, schema.sql
docs/               tài liệu (codebase-summary, system-architecture, code-standards...)
plans/              kế hoạch từng feature
```

## 1.9 — File cấu hình / launcher ở gốc
```
CLAUDE.md rule.md SESSIONS.md      hướng dẫn Claude + điều phối session
HUONG-DAN.md BAO-CAO.md README.md  tài liệu người dùng
TOAN-CANH-2-TOOL.md                tổng quan 2 tool (vừa tạo)
app_config.json xu_ly_config.json trang_config.json   config
data_khach.db secret.key           DB khách + secret (gitignore)
*.bat (CAO-VIDEO, MO-WEB, XU-LY-VIDEO, CAI-DAT...)   launcher cho khách
```

## 1.10 — Thư mục DỮ LIỆU (KHÔNG đụng — video/giọng thật)
```
processed_videos/  video đã render   ·  _preview/  video xem trước
giong_mau/ long_tieng/ piper_vn/     giọng mẫu + model TTS
translation_memory/  từ điển tên riêng   ·  user_logos/  logo khách tải lên
video_nen/  nhạc nền   ·  zhconv/  vendor chuyển phồn↔giản thể
```

---

# 2) LOHAPAGE — `C:\Users\vannh\lohapage\loha-automation`

App tự đăng Facebook. **Mono-repo**: app desktop + web UI + server license + workflows.

```
loha-automation/
├── desktop/                    ⭐ ELECTRON APP (main process)
│   ├── src/
│   │   ├── main.js             khởi động: tray → DB → license → server → watcher → scheduler
│   │   ├── api-server.js       (86KB) HTTP localhost:3088 — serve React UI + REST API
│   │   ├── database.js         (75KB) SQLite: pages, posts, tokens, groups, pools, license
│   │   ├── facebook.js         (50KB) đăng Graph API (Reels/video/ảnh/story)
│   │   ├── scheduler.js        (48KB) cron: đăng pending, auto-schedule, refresh token
│   │   ├── file-service.js     (23KB) chokidar watch uploads/ → tạo post
│   │   ├── license.js          (19KB) license Supabase + HMAC + offline grace
│   │   ├── schedule-rule.js    tính giờ đăng kế tiếp (interval / fixed_times)
│   │   ├── telegram.js         bot Telegram (thông báo + pause)
│   │   ├── proxy.js metrics.js i18n.js updater.js zoom.js preload.js
│   │   └── (data.db chạy ở %APPDATA%/LohaAutomation/)
│   ├── assets/                 icon
│   └── scripts/                obfuscate.js, process-icons.js, copy-exe-to-root.js
│
├── web/                        ⭐ REACT UI (Vite) — api-server serve dist
│   └── src/  App.jsx, components/, pages/, hooks/, context/, i18n/, locales/, lib/
│
├── admin-web/                  web QUẢN TRỊ (app.js, index.html) — deploy Vercel
│
├── license-server/supabase/    ⭐ SERVER LICENSE RIÊNG (Supabase Edge Functions, Deno/TS)
│   ├── functions/
│   │   ├── activate/  validate/  trial/  deactivate/  upgrade/     (client gọi)
│   │   ├── admin-generate/ admin-list/ admin-renew/ admin-revoke/
│   │   │   admin-upgrade/ admin-reset-machine/                     (admin)
│   │   └── _shared/  hmac.ts  db.ts  tier.ts  cors.ts  audit.ts  admin-auth.ts
│   └── migrations/  20260425_initial_schema.sql   ← nơi bảng license_slots THẬT sống
│
├── workflows/                  workflow JSON (n8n-style)
│   ├── production/  facebook-full-post, facebook-multi-page-post, facebook-token-refresh,
│   │   content-scheduler, tiktok-upload-video, google-sheets-content-source,
│   │   notification-telegram, error-handler, analytics-collector, nocodb-facebook-scheduler
│   └── drafts/  facebook-basic-post, *-test-connection
│
├── templates/  content-templates.json
├── tools/  admin.ps1          ·  admin.cmd  ·  admin-web/ (đã nêu)
├── docs/  plans/  demo/  updates/
└── Lohaautomation.md  README.md
```

**Điểm đáng chú ý về LohaPage:**
- `desktop/` = app chạy trên máy khách. `web/` = giao diện (build ra, api-server serve).
- `license-server/supabase/` = **server cấp license riêng** (khác server Vercel của ViralCrawl). Bảng `license_slots` + logic slot sống ở đây (migrations + functions).
- `workflows/` cho thấy LohaPage còn có hướng **TikTok** (`tiktok-upload-video`) + nguồn nội dung Google Sheets/NocoDB — không chỉ Facebook.

---

# 3) THƯ MỤC CHỨA VIDEO (data cào + processed render)

> Đây là nơi VIDEO THẬT nằm khi chạy. **Gốc thư mục (`DATA_DIR` / `PROCESSED_DIR`) tùy chế độ:**
> - **Dev** (chạy từ mã nguồn): `MediaCrawler/data/` và `processed_videos/` (ngay trong repo).
> - **Bản đóng gói:** `%APPDATA%/viralcrawl-desktop/data/` và `.../processed_videos/` (bền qua update).
> - **Khách tự chọn ổ** (tab Cài đặt): `<ổ chọn>/data/` và `<ổ chọn>/processed_videos/`.

## 3.1 — `<DATA_DIR>/` — VIDEO ĐÃ CÀO (chưa render)
```
<DATA_DIR>/
├── douyin/                          (mỗi nền 1 folder: douyin, bili, xhs, rednote, weibo, youtube, tiktok)
│   ├── videos/                      ⭐ VIDEO ĐÃ TẢI VỀ — chia theo KIỂU CÀO (sub_dir):
│   │   ├── kenh/                    ← cào THEO KÊNH
│   │   │   └── <Tên kênh (dịch Việt)>/
│   │   │       └── <Tiêu đề (dịch Việt)>_<id6>.mp4    vd: Món cay Tứ Xuyên_412345.mp4
│   │   ├── tu-khoa/                 ← cào TỪ KHÓA
│   │   │   └── <từ khóa>/
│   │   │       └── <Tiêu đề>_<id6>.mp4
│   │   └── link/                    ← tải LINK lẻ
│   │       └── <Tiêu đề>_<id6>.mp4
│   │   (<id6> = 6 số cuối video id · tên kênh+tiêu đề ĐÃ dịch sang tiếng Việt)
│   ├── jsonl/                       metadata (lịch sử cào + chống trùng)
│   │   ├── search_contents_<ngày>.jsonl     ← cào từ khóa
│   │   ├── creator_contents_<ngày>.jsonl    ← cào theo kênh
│   │   └── detail_contents_<ngày>.jsonl     ← tải link lẻ
│   ├── images/                      ảnh (bài ảnh XHS/Weibo)
│   └── _da_tai_ids.txt              SỔ id đã tải → KHÔNG tải trùng
├── bili/  xhs/  rednote/  weibo/  youtube/  tiktok/   (cùng cấu trúc trên)
├── _task_queue.json                 hàng đợi CÀO (bền, resume sau tắt app)
├── _render_queue.json               hàng đợi RENDER (bền — mới thêm)
└── _login_check.json                cache trạng thái đăng nhập nền tảng
```

## 3.2 — `<PROCESSED_DIR>/` — VIDEO ĐÃ RENDER
```
<PROCESSED_DIR>/  (= processed_videos)
├── douyin/  bili/  ...              rerender TỰ ĐỘNG → xếp theo nền tảng
│   └── <tên>_xuly.mp4
└── phân loại/                       khi BẬT phân loại (AI đoán thể loại)
    ├── mukbang/                     ← folder thể loại thường
    │   └── <tên>_xuly.mp4
    ├── xe cộ/   phim/   thú cưng/ ...
    └── <Tên Trang FB>_<page_id>/    ← folder LohaPage (nếu gán thể loại → đăng)
        ├── <caption>.mp4
        └── <caption>.txt            (LohaPage bỏ qua .txt, đọc tên file)
```

## 3.3 — QUY TẮC ĐẶT TÊN FILE render (quan trọng)
Các bản render nằm **cạnh video gốc** (hoặc trong folder đích), tích lũy KHÔNG ghi đè:
```
<tên>.mp4              video GỐC (đã cào)
<tên>_xuly.mp4         ⭐ render ĐẦY ĐỦ (transforms + dịch/lồng tiếng) — bản chính để đăng
<tên>_phude.mp4        CHỈ burn phụ đề (không lồng tiếng)
<tên>_longtieng.mp4    CHỈ lồng tiếng (không đổi hình)
<tên>.zh.srt           phụ đề tiếng Trung (OCR/ASR)   ┐ sidecar — tự dọn sau render
<tên>.vi.srt           phụ đề tiếng Việt (đã dịch)    ┘ (giữ trong cache _cache_artifact)
<tên> (2)_xuly.mp4     render LẦN 2 (đánh số, không đè bản cũ)
clip_nho/<tên>_cảnh07.mp4    clip BĂM NHỎ (mỗi cảnh 1 file, trong folder con clip_nho)
```

## 3.4 — Đường video đi tới LohaPage
```
ViralCrawl chép _xuly.mp4  →  <thư mục uploads LohaPage>/<Trang>_<page_id>/<caption>.mp4
                              hoặc  .../__group_<slug>/<caption>.mp4   (nhóm nhiều trang)
        │  (LohaPage watch thư mục này)
        ▼
LohaPage:  uploads/<Trang>_<id>/  →  (đăng xong)  →  done/<Trang>_<id>/
           %APPDATA%/LohaAutomation/  (hoặc thư mục uploads khách tự đặt)
```

## 3.5 — CÁC ĐƯỜNG DẪN KHÁC (đăng bài + config + state)
`<ROOT>` = cha của `<DATA>` (= userData khi đóng gói).

### Đăng bài (giao LohaPage)
```
loha_uploads_dir   đường TUYỆT ĐỐI khách đặt (trỏ tới uploads của LohaPage)
                   vd:  %APPDATA%\LohaAutomation\uploads
                   lưu ở:  <ROOT>\kenh_nguon\kenh_nguon.json  (field "loha_uploads_dir")

Kênh nguồn & Phân loại giao vào:
   <loha_uploads_dir>\<Tên trang>_<page_id>\<caption>.mp4  (+ <caption>.txt)
   <loha_uploads_dir>\__group_<slug>\<caption>.mp4         (nhóm nhiều trang)
Nếu CHƯA đặt loha_uploads_dir (gom cũ):
   <ROOT>\gom_dang_bai\dang_bai\<Tên trang>\...
```

### Config / State / Khách
```
<ROOT>\kenh_nguon\kenh_nguon.json       Kênh nguồn (kênh + đích + lịch + loha_uploads_dir)
<ROOT>\gom_dang_bai\trang_config.json   cấu hình trang LohaPage (tab Đăng bài)
<DATA>\_render_queue.json               hàng đợi RENDER (bền, resume sau tắt app)
<DATA>\_task_queue.json                 hàng đợi CÀO (bền)
<DATA>\_login_check.json                cache trạng thái login nền tảng
_cache_artifact\                        cache srt/dub (render lại nhanh, TTL 7d, LRU 3GB)
<KHACH_DB_DIR>\app_settings.json        cài đặt app (thư mục data, phân loại, watermark...)
<KHACH_DB_DIR>\data_khach.db            DB khách (đăng nhập, gói, usage)
<KHACH_DB_DIR>\secret.key               khóa mã hóa (mất = mất data cũ)
key_store.dat                           API key mã hóa DPAPI (ai_dich)
```
`KHACH_DB_DIR` = `<ROOT>` (userData) khi đóng gói; dev = thư mục app.

---

*Nguồn: liệt kê trực tiếp thư mục 2 repo + đọc code (data_dir.py, MediaCrawler store, hậu tố render trong web_app.py). ⭐ = quan trọng nhất. Mục 3 dựng từ CODE vì máy dev đang trống — video thật nằm trên laptop khách.*
