# DESIGN PRINCIPLES — ViralCrawl (kim chỉ nam)

> Đây là **các nguyên tắc BẤT BIẾN** của hệ thống. Mỗi khi thêm/sửa tính năng, soi lại: *"Thay đổi này có
> vi phạm nguyên tắc nào không?"* Nếu có → dừng, thiết kế lại. Tài liệu này **không** mô tả code (xem
> `ARCHITECTURE.md`) — chỉ ghi **triết lý phải giữ**.
>
> Quy trình làm việc (component-hoá, surgical, test thật, điều phối đa session) nằm ở `rule.md` + `CLAUDE.md`.
> File này tập trung **invariant KIẾN TRÚC**.

---

## P1 — Hai tool chỉ giao tiếp qua FILESYSTEM CONTRACT
ViralCrawl và LohaPage nối nhau **duy nhất qua thư mục** `uploads/<Tên>_<page_id>/` (tên file = caption).
**KHÔNG** gọi API trực tiếp, KHÔNG RPC, KHÔNG websocket, KHÔNG chung DB.

- **Vì sao:** ghép lỏng (loose coupling) → mỗi tool chạy/deploy/bán/crash độc lập; thay ViralCrawl bằng tool
  khác (TikTok/Shopee/YT) mà LohaPage không đổi 1 dòng.
- **Vi phạm khi:** thêm lời gọi HTTP/DB thẳng từ tool này sang tool kia; đọc DB của LohaPage từ ViralCrawl.
- **Enforced:** `gom_dang_bai.giao_loha` / `folder_loha`; LohaPage `file-service.js` (watcher).

## P2 — Contract `uploads/` là BẤT BIẾN (không phá backward-compat)
Định dạng folder `<Tên>_<page_id≥5>` / `__group_<slug>` + caption-trong-tên-file là **API công khai** giữa 2 tool.

- **Vì sao:** LohaPage (bên nhận) đang parse đúng định dạng này (`lastIndexOf('_')`, page_id≥5, cắt tại `#`).
  Đổi định dạng = phá mọi bài đang chờ + phải sửa cả 2 repo cùng lúc.
- **Vi phạm khi:** đổi cách đặt tên folder/file; bỏ `#` khỏi tên file; dùng ký tự Windows cấm.
- **Enforced:** `gom_dang_bai._safe/_ten_tu_caption`, `kenh_nguon.folder_dich`. Đổi → phải version hoá contract.

## P3 — Worker nền KHÔNG được chặn HTTP/UI
Việc nặng (cào, render, dịch, TTS) chạy **thread nền hoặc subprocess**. HTTP handler phải **trả nhanh**
(enqueue rồi trả, không render trong request).

- **Vì sao:** server là `ThreadingHTTPServer` 1 tiến trình; handler chặn = UI đơ, "Lỗi kết nối" oan.
- **Vi phạm khi:** gọi `localize`/`ffmpeg`/`subprocess.run` blocking TRONG `_do_GET/_do_POST`.
- **Enforced:** `_queue_them` (enqueue) + `_queue_worker` (nền); `_kn_worker`, `_task_worker`...

## P4 — Mọi HÀNG ĐỢI phải BỀN + khôi phục sau khi tắt đột ngột
Hàng đợi cào (`_task_queue.json`) và render (`_render_queue.json`) persist ra đĩa (ghi atomic). Mở lại app →
job `dang` (dở) → `cho` để tiếp tục; cache giữ bước đã xong.

- **Vì sao:** máy khách tắt/crash/mất điện giữa render (nặng, lâu) — mất hàng đợi = làm lại từ đầu, tốn CPU.
- **Vi phạm khi:** thêm hàng đợi mới chỉ giữ trong RAM; không khôi phục lúc khởi động.
- **Enforced:** `_queue_luu/_queue_nap/_queue_saver`; `_task_luu/_task_nap`.

## P5 — License CHỈ GATE tính năng, KHÔNG đổi luồng nghiệp vụ
`TIER` (free/pro/unlimited/expired) và cờ `LOHAPAGE_OK` chỉ **cho phép / chặn**. Pipeline cào→render→giao
**không rẽ nhánh** theo license (chỉ chặn ở cổng).

- **Vì sao:** tách quan tâm (kinh doanh vs kỹ thuật); tắt gate (env override) = bản đầy đủ chạy y nguyên,
  dễ test; server bật/tắt quyền từ xa mà không cần build lại.
- **Vi phạm khi:** viết `if TIER==pro: render kiểu A else kiểu B`; nhét logic nghiệp vụ vào chỗ check quyền.
- **Enforced:** gate ở CỔNG (`_do_GET/_do_POST` + 4 worker) qua `_can_lohapage`/`_guard_expired`, không trong lõi render.

## P6 — Mỗi SUBPROCESS phải crash được mà KHÔNG sập web_app
Cào (MediaCrawler venv), render (localize/render_worker), login — chạy **tiến trình RIÊNG**. Web_app bọc lỗi,
worker bền treo/chết → kill + fallback; 1 video lỗi không giết worker.

- **Vì sao:** cô lập lỗi — 1 video hỏng / 1 driver crash không được kéo sập cả app.
- **Vi phạm khi:** import + gọi thẳng thư viện nặng (whisper/ffmpeg native) trong tiến trình web_app; không
  bọc try/except quanh vòng lặp worker.
- **Enforced:** subprocess `xu_ly_chon.py`/`render_worker.py`; `_render_via_worker` (kill khi treo >stall);
  `_queue_worker` try/except mỗi video.

## P7 — STATE + CACHE bền phải ở userData (KHÔNG ở app-src)
Data video, `app_settings.json`, queue, cache, cookie, khách-DB, giọng clone → ở **userData** (hoặc ổ khách
chọn). App-src (`Program Files`) **read-only** + bị NSIS xoá khi auto-update.

- **Vì sao:** update = mất sạch nếu để trong app-src (đã dính bug này); ghi app-src fail WinError 5.
- **Vi phạm khi:** ghi file trạng thái/dữ liệu vào thư mục cài; hardcode đường dẫn tương đối cho state.
- **Enforced:** `data_dir.lay_data_dir` (DATA_DIR/PROCESSED_DIR), `KHACH_DB_DIR`/`LIC_CACHE_DIR`, `_cache_artifact`.

## P8 — Idempotent + CHỐNG TRÙNG ở mọi bước lặp
Cào không tải trùng (ledger `_da_tai_ids.txt` + jsonl id). Gom idempotent (sổ `_da_gom.txt`). Render không đè
(đánh số `<tên> (2)_xuly.mp4`). Kênh nguồn re-crawl không nhân đôi (merge theo id).

- **Vì sao:** worker chạy lặp (mỗi 60s/định kỳ) + user bấm lại + khôi phục sau restart → phải an toàn khi chạy lại.
- **Vi phạm khi:** thêm bước tạo file/đăng mà không có khoá chống trùng (id/hash/sổ).
- **Enforced:** `index_metadata`, `_da_tai_ids.txt`, `gom_dang_bai` ledger, `kenh_nguon.them_kenh` (merge).

## P9 — CPU-ONLY là ràng buộc CỨNG
Máy khách i3, 16GB, **không GPU dùng được**. Không giả định GPU; luôn cân nhắc thời gian render THẬT; cache để
render lại nhanh; giải phóng RAM sau ASR.

- **Vì sao:** whisper/OCR/ffmpeg trên CPU rất chậm — feature "auto retry/re-render" vô tội vạ = đốt hàng giờ CPU.
- **Vi phạm khi:** mặc định bật tính năng đòi GPU; retry render không giới hạn; giữ nhiều model trong RAM cùng lúc.
- **Enforced:** `cache_artifact`, `render_worker` giữ nóng model, `VC_RENDER_RETRY=1`, `gc` sau ASR, cảnh báo disk.

## P10 — Không nuốt lỗi ÂM THẦM ở đường chính
`except: pass` chỉ cho việc PHỤ (dọn cache, sidecar, badge). Đường nghiệp vụ chính phải **log có phân loại** —
lỗi phải THẤY được.

- **Vì sao:** đã dính bug thật: `re`→`_re` ở phân loại bị `except` nuốt → sidecar không ghi mà **không ai biết**.
- **Vi phạm khi:** bọc `try/except: pass` quanh bước quan trọng (dịch/giao/đếm quota) mà không log.
- **Enforced (một phần):** `_loi_500.log`, `them_log`. **Nên cải thiện:** error-reporter chung (xem ARCHITECTURE §11).

---

## ✅ Checklist khi thêm 1 tính năng mới
1. Có gọi thẳng sang tool kia không? → **P1/P2** (phải qua `uploads/` contract).
2. Việc nặng có chạy trong HTTP handler không? → **P3** (đẩy xuống worker).
3. Có tạo hàng đợi/tiến-trình dài không? → **P4** (bền + khôi phục) · **P6** (crash không sập app).
4. Có rẽ nhánh nghiệp vụ theo license không? → **P5** (chỉ gate, không rẽ).
5. Ghi file trạng thái ở đâu? → **P7** (userData, không app-src).
6. Chạy lại có nhân đôi/đè không? → **P8** (idempotent + chống trùng).
7. Có đòi GPU / retry render vô hạn không? → **P9** (CPU-only).
8. Có `except: pass` ở bước chính không? → **P10** (log, đừng nuốt).

---

*Nguồn: chắt lọc từ hành vi THẬT của codebase (data_dir, queue bền, subprocess cô lập, gate license, cache
artifact, ledger chống trùng) + các bài học đã ghi trong `SESSIONS.md`/`rule.md`. Cập nhật khi có invariant mới.*
