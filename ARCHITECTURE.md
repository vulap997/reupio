# ARCHITECTURE — ViralCrawl (kiến trúc kỹ thuật)

> Tài liệu này mô tả **hệ thống THẬT hiện tại** (bám mã nguồn), gồm: Layers · Core · Worker · State Machine ·
> Event Flow · Dependency Map · Data Flow · Retry/Error Policy · Performance. Chỗ nào **đang thiếu / nên chuẩn
> hoá** đều ghi rõ ở mục cuối. (LohaPage là app riêng — xem `TOAN-CANH-2-TOOL.md`.)
>
> *Lưu ý:* `docs/system-architecture.md` cũ đã lỗi thời (số dòng/tên file lệch) — file này là bản chính xác.

---

## 1. Kiến trúc phân tầng (Layers)

```
┌─ PRESENTATION ─────────────────────────────────────────────────┐
│ desktop/main.js   Electron: tray, gate license, spawn web_app,  │
│                   tắt HW video-decode + crash-recovery (GPU)     │
│ web/index.html    SPA 1 file — gọi REST /api/* (fetch)           │
├─ SERVICE / API ────────────────────────────────────────────────┤
│ web_app.py        ThreadingHTTPServer :8770, ~70 route /api/*   │
│                   _do_GET/_do_POST (mỗi handler try/except→500)  │
│                   _guard(): host allowlist + CSRF nonce (POST)   │
│                   gate quyền: expired / free / lohapage          │
├─ WORKER (nền — thread + subprocess) ───────────────────────────┤
│ Thread: _queue_worker (render), _task_worker (cào), _kn_worker, │
│   _auto_gom_worker, _wf_auto_worker, _auto_worker,              │
│   _login_recheck_worker, _queue_saver, _phan_loai_sau_render    │
│ Subprocess (venv riêng / python): MediaCrawler, localize.py,    │
│   xu_ly_chon.py, render_worker.py (BỀN), tim_anh.py,           │
│   mo_dang_nhap.py, kiem_tra_login.py, lic_cli.py, ffmpeg        │
├─ STORAGE ──────────────────────────────────────────────────────┤
│ SQLite  data_khach.db     khách + quota + usage (khach_db.py)   │
│ JSON    app_settings.json  kenh_nguon.json  _task_queue.json    │
│         _render_queue.json  trang_config.json                   │
│ FS      <DATA>/<nền>/videos  processed_videos  _cache_artifact  │
│         jsonl (metadata)  _da_tai_ids.txt (sổ chống trùng)      │
│ DPAPI   key_store.dat (API key mã hoá)  secret.key              │
└────────────────────────────────────────────────────────────────┘
```
**Nguyên tắc:** UI **không** đụng nghiệp vụ trực tiếp — mọi thứ qua REST `web_app.py`. Việc nặng (cào/render)
đẩy xuống **worker nền** (không chặn HTTP). Máy **CPU-only** → tách subprocess để cô lập crash + giải phóng RAM.

---

## 2. Core (những mảnh trung tâm)

```
Core
├── HTTP/Route    web_app._do_GET/_do_POST (~70 route) + _guard (CSRF/host)
├── Queue-Render  _queue (RAM) + _render_queue.json (bền) + _queue_worker + _queue_saver
├── Queue-Crawl   _tasks + _task_queue.json + _task_worker (scheduler chung)
├── Config        app_settings.json (_doc_settings/_luu_settings) + data_dir (đường dẫn bền)
├── License/Gate  TIER + LOHAPAGE_OK (env từ lic_cli) + _can_lohapage + _guard_expired
├── Cache         cache_artifact (srt/dub lossless, TTL 7d, LRU 3GB)
├── Khách/Quota   khach_db (SQLite): đăng nhập, gói, usage_cong/usage_lay
├── Data          data_dir (DATA_DIR/PROCESSED_DIR) + index_metadata (chống trùng)
└── i18n/Log      ngon_ngu (vi/en) + log_i18n + them_log (ring buffer)
```

---

## 3. Worker nền (đầy đủ)

| Worker | Khởi động | Chu kỳ | Việc |
|---|---|---|---|
| `_queue_worker` | `_khoi_dong_queue` | liên tục | Lấy video `cho` → render (1 lúc 1) → post-hooks |
| `_queue_saver` | `_khoi_dong_queue` | 4s | Ghi `_render_queue.json` (bền, chỉ khi đổi) |
| `_task_worker` | `_khoi_dong_task` | liên tục | Hàng đợi CÀO (kind='crawl'), login-aware |
| `_kn_worker` | `_khoi_dong_kn` | 60s | Kênh nguồn: kênh tới giờ → tải N → render → giao LohaPage |
| `_auto_gom_worker` | `_khoi_dong_auto_gom` | `_AUTOGOM_INTERVAL` | Gom output → LohaPage (nếu bật auto_gom) |
| `_wf_auto_worker` | `_khoi_dong_wfauto` | ~10' | Quy trình tự động (băm→render) |
| `_auto_worker` | `_khoi_dong_auto` | — | Auto-render video gốc chưa render |
| `_login_recheck_worker` | `_khoi_dong_login_recheck` | 180s | Kiểm login LIVE → badge tươi (hết "xanh giả") |
| `_phan_loai_sau_render` | (sau mỗi render) | 1 thread/video | AI phân loại → move + sidecar LohaPage |
| `render_worker.py` | `_rw_ensure` (subprocess) | thường trực | Render BỀN (giữ nóng Whisper/OCR → video 2+ nhanh) |

Render mặc định qua **worker bền** (`VC_RENDER_WORKER=1`); dịch-thủ-công hoặc worker treo `>VC_RENDER_STALL`
(1800s) → **fallback subprocess** `xu_ly_chon.py`.

---

## 4. State Machine (THẬT — 3 hàng đợi RIÊNG, không phải 1 chuỗi)

### 4.1 — Hàng đợi CÀO (`_tasks`, `_task_queue.json`)
```
cho ──▶ dang ──▶ xong
                └▶ loi        (login hết / timeout / cào 0)
```
Khôi phục sau tắt app: `dang → cho`. Login-aware: nền chưa login → task "🔒 Cần đăng nhập", bỏ qua task cùng nền.

### 4.2 — Hàng đợi RENDER (`_queue`, `_render_queue.json`)
```
cho ──▶ dang ──┬─▶ xong
               ├─▶ loi ──(VC_RENDER_RETRY, còn lượt)──▶ cho   (tự thử lại)
               └─▶ cho_srt   (dịch-thủ-công: ASR xong, chờ người nhập SRT)
                       └─(srt_import)─▶ cho (pha 2: render với SRT)
```
Cờ kèm item: `cancel` (huỷ), `retry` (đếm lần), `pha_xong_asr`, `_dub_phut` (quota). Khôi phục: `dang → cho`;
file gốc mất → `loi`. **Không** retry với: huỷ / dịch-thủ-công / file hỏng (thiếu moov atom).

### 4.3 — Vòng đời VIDEO (cross-cutting — suy từ file/ledger, KHÔNG phải 1 biến state)
```
CÀO (id trong jsonl)
  └▶ TẢI (id trong _da_tai_ids.txt + file trong <nền>/videos)
       └▶ [BĂM] clip_nho/<tên>_cảnhNN.mp4        (tuỳ chọn)
       └▶ RENDER (<tên>_xuly.mp4 cạnh gốc)
            ├▶ PHÂN LOẠI (move → processed/phân loại/<thể loại>/)
            └▶ GIAO LohaPage (copy → uploads/<Page>_<id>/<caption>.mp4)
```
→ "đã cào / đã tải / đã render" nhận diện qua **tên file + ledger**, không có 1 cột trạng thái tập trung
(đây là điểm nên chuẩn hoá — xem §9).

### 4.4 — Login nền tảng (`_login_check.json`) · 4.5 — License
```
Login:    in | out | unknown | na(yt/tt không cần)     — recheck LIVE 180s
License:  free | pro | unlimited | expired  (+ cờ lohapage)  — từ lic_cli status
```

---

## 5. Event Flow (chuỗi sự kiện THẬT)

```
[A] CÀO THỦ CÔNG / LỊCH
  user bấm Cào / schtasks  →  _task_them(crawl)  →  _task_worker  →  chay_crawl (subprocess MediaCrawler)
  →  video vào <nền>/videos + ghi jsonl + _da_tai_ids.txt

[B] RENDER
  enqueue (_queue_them)  →  _queue_worker chọn 'cho'  →  _video_san_sang? (đợi tải xong)
  →  _render_via_worker (render_worker.py bền) | fallback subprocess xu_ly_chon.py → localize.py
  →  _xuly.mp4  →  POST-HOOKS:
       ├ opts.phan_loai_sau  → _phan_loai_sau_render (thread)
       ├ opts.kn_giao        → _kn_giao_sau_render → giao_loha
       ├ else                → _don_srt_canh_video (dọn .srt)
       └ opts._dub_phut      → kdb.usage_cong (đếm quota lồng tiếng)

[C] KÊNH NGUỒN (tự động)
  _kn_worker (60s): kênh tới giờ + chưa chạy hôm nay
  →  _kn_tai_va_render: re-cào metadata → tải N chưa-tải (cao_anh_chon) → enqueue render + marker kn_giao
  →  [B render]  →  _kn_giao_sau_render  →  gom_dang_bai.giao_loha → uploads/<Page>_<id>/

[D] PHÂN LOẠI → LOHAPAGE
  sau [B]  →  _phan_loai_sau_render: Gemini đoán thể loại → move _xuly.mp4 vào folder thể loại
  →  nếu folder là folder LohaPage (<Tên>_<id≥5> / __group_) + có quyền → ghi sidecar .txt caption

[E] GATE QUYỀN (xuyên suốt)
  desktop/main.js: lic_cli status → env VC_TIER + VC_LOHAPAGE  →  web_app: TIER + LOHAPAGE_OK
  →  _guard_expired / _can_lohapage chặn endpoint + worker
```

---

## 6. Dependency Map (module + ranh giới subprocess)

```
desktop/main.js ──spawn──▶ web_app.py
      └──▶ lic_cli.py ──▶ lic_client ──▶ lic_db  (license, server Vercel)

web_app.py
  ├─import→ khach_db · data_dir · kenh_nguon · gom_dang_bai · tao_caption
  │         phan_loai · cache_artifact · ngon_ngu · index_metadata · nen_tang_helper
  ├─subprocess→ MediaCrawler (venv riêng)          [CÀO]
  ├─subprocess→ tim_anh.py / tai_ytdlp.py          [preview / tải]
  ├─subprocess→ xu_ly_chon.py ──▶ localize.py      [RENDER fallback]
  ├─subprocess→ render_worker.py ──▶ localize.py   [RENDER bền]
  ├─subprocess→ mo_dang_nhap.py / kiem_tra_login.py [login]
  └─subprocess→ lic_cli.py                          [làm mới gói]

localize.py  (lõi render)
  ├─▶ phu_de.py           (WhisperModel + Google dịch)
  ├─▶ ocr_text/ocr_anh    (OCR chữ Trung — đọc hardsub)
  ├─▶ dai_sub/_ocr/_rapid (dò DẢI sub để che)
  ├─▶ ai_dich / dich_gemini_web (dịch AI, nhiều key xoay)
  ├─▶ giong_piper / kokoro_synth / omnivoice_synth (TTS)
  ├─▶ _demucs_worker      (tách nhạc nền)
  ├─▶ cache_artifact      (HIT srt/dub → bỏ bước đã xong)
  └─▶ ffmpeg / xu_ly_video.co_nvenc (encode)

kenh_nguon ──▶ gom_dang_bai.folder_loha        (đồng bộ contract với phân loại)
gom_dang_bai ──▶ tao_caption                    (caption LohaPage)
```
**Ranh giới quan trọng:** cào + render chạy **subprocess** (venv/python riêng) → crash 1 video **không** làm
sập `web_app`. `localize.py` load lại mỗi lần → sửa nó **không cần restart** web_app (nhưng cache cũ phải "render từ đầu").

---

## 7. Data Flow

```
Từ khoá/Link/Kênh
   │ cào (MediaCrawler/yt-dlp)
   ▼
metadata (jsonl)  +  VIDEO (<nền>/videos/<tên>_<id>.mp4)  +  _da_tai_ids.txt
   │ render (localize: ASR→dịch→TTS→ffmpeg) — cache srt/dub
   ▼
<tên>_xuly.mp4  (+ .zh.srt/.vi.srt tạm)
   │ phân loại (AI) HOẶC kn_giao (kênh nguồn)
   ▼
processed_videos/phân loại/<thể loại>/     HOẶC     <loha uploads>/<Page>_<id>/<caption>.mp4 + .txt
   │
   ▼
(LohaPage watch → đăng Facebook)
```

---

## 8. Retry / Error Policy (THẬT — KHÔNG đồng nhất)

| Điểm lỗi | Chính sách hiện tại | Ghi chú |
|---|---|---|
| **Render lỗi** | tự thử lại `VC_RENDER_RETRY` (mặc định **1**) | bỏ qua: huỷ / dịch-thủ-công / file hỏng moov |
| **Render worker treo** | `>VC_RENDER_STALL` (1800s) không event → kill + **fallback subprocess** | |
| **AI dịch (Gemini/Groq)** | **nhiều key, xoay khi 429**; provider fail → provider khác | ai_dich.py |
| **Cào** | login-aware (hết phiên → báo, bỏ task cùng nền); timeout | không retry vòng |
| **Tải (cao_anh_chon)** | 1 lần; fail → log, đánh dấu bỏ | |
| **Quota lồng tiếng** | greedy `_dub_quota_loc`: nhận tới hết budget, chặn phần vượt | đếm sau success |
| **Tắt app giữa chừng** | khôi phục queue: `dang → cho`; cache giữ bước đã xong | §4 |
| **Handler HTTP lỗi** | try/except → **500 JSON** (không sập server) + ghi `_loi_500.log` | |

→ **Chưa có:** retry cào/tải/OCR/giao có giới hạn lần thống nhất; backoff mũ; dead-letter. (nên chuẩn hoá §9)

---

## 9. Error Boundary (cô lập lỗi — THẬT)

```
web_app (HTTP)      mỗi _do_GET/_do_POST bọc try/except → 500, KHÔNG rớt connection
_queue_worker       try/except MỖI video → 1 video lỗi không giết worker; finally reset _render_proc
_task_worker        try/except mỗi task
_phan_loai_sau      chạy THREAD riêng + try/except → lỗi phân loại không chặn render kế
subprocess cào/render  tiến trình RIÊNG → crash không sập web_app (worker bền: kill+restart)
nhiều chỗ except: pass  (cache, login-check, giao_loha, dọn srt) — lỗi phụ không làm hỏng luồng chính
```
**Cô lập tiến trình mạnh** (subprocess) nhưng **boundary trong-tiến-trình rải rác** (`except: pass` nhiều) →
lỗi có thể bị nuốt âm thầm (đã gặp: bug `re`→`_re` ở phân loại bị `except` nuốt, sidecar không ghi mà không báo).

---

## 10. Performance Map (máy CPU-only i3, 16GB, không GPU dùng được)

| Tài nguyên | Nặng ở đâu | Giảm tải hiện có |
|---|---|---|
| **CPU** | Whisper ASR · OCR · ffmpeg encode | worker BỀN giữ nóng model (video 2+ nhanh); OCR-first (bỏ Whisper-fill) |
| **RAM** | Whisper + demucs + TTS cùng lúc | giải phóng Whisper sau ASR (`gc`); tách subprocess |
| **Disk** | processed_videos + cache + video gốc | cache LRU 3GB + TTL 7d; cảnh báo khi sắp đầy; dọn .srt sau render |
| **Mạng** | Gemini dịch · tải video | nhiều key xoay; cache srt (dịch lại KHÔNG gọi mạng) |
| **Thời gian** | render ~realtime×N/video | cache srt/dub → render lại chỉ ghép; ETA theo mốc pct≥24 |

---

## 11. Điểm NÊN chuẩn hoá (gaps thật — để lớn lên dễ bảo trì)

1. **State video tập trung** — hiện suy từ tên file/ledger (dễ lệch giữa các tab). Nên có 1 bảng
   `video(id, trạng thái, đường dẫn, hash, thời gian)` làm nguồn sự thật duy nhất.
2. **Retry/backoff thống nhất** — mỗi tầng (render/cào/dịch/FB) mỗi kiểu. Nên có helper retry chung
   (số lần + backoff + dead-letter) áp cho cào/tải/OCR/giao.
3. **Bớt `except: pass`** — thay bằng log có phân loại (đã dính bug bị nuốt). Cân nhắc 1 error-reporter chung.
4. **Event bus nhẹ** — hiện các bước nối bằng gọi hàm trực tiếp + marker trong opts. Nếu thêm nền tảng
   (TikTok/Shopee...) → 1 event bus (`download_done`, `render_done`...) giúp gắn thêm consumer dễ hơn.
5. **Gom 66 file .py theo package domain** (khi vượt ~100–150 file): `core/ crawl/ render/ tts/ ocr/
   facebook/ license/ ui/ workers/ utils/` — đúng gợi ý review; chưa cần gấp.
6. **Thống kê lỗi + timeline per-video** (dashboard) — hiện chỉ log dòng; nên có bảng OCR/dịch/render/giao lỗi.

---

*Nguồn: đọc trực tiếp web_app.py (route, worker, queue, gate), localize.py, kenh_nguon.py, gom_dang_bai.py,
data_dir.py, cache_artifact.py, desktop/main.js. Bám hành vi THẬT tại thời điểm viết — nhánh feat/dang-bai-longtieng-en.*
