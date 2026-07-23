# -*- coding: utf-8 -*-
"""
Gom video ĐÃ RENDER vào folder theo TRANG (mukbang, review phim...) cho tool đăng bài tự động.

- Trang định nghĩa trong trang_config.json: mỗi trang = danh sách từ khóa + kênh.
- Mỗi video lấy BẢN tốt nhất: _longtieng > _phude > _xuly > bản rerender (processed_videos).
- COPY vào dang_bai/<trang>/ ; ghi sổ dang_bai/_da_gom.txt để KHÔNG gom trùng
  (kể cả khi tool đăng đã xóa file sau N ngày).
- KHÔNG xóa/sửa bản gốc hay bản đã render.

Chạy: python gom_dang_bai.py        (gom thật)
      python gom_dang_bai.py --dry  (thử, không copy)
"""
import json
import os
import re
import shutil
import sys

import tao_caption

GOC = os.path.dirname(os.path.abspath(__file__))
CRAWLER = os.path.join(GOC, "MediaCrawler")

# Ledger/cấu hình gom đăng bài → userData (BỀN qua auto-update: NSIS xóa sạch app-src mỗi lần cập nhật;
# nếu để ở app-src thì _da_gom.txt + dang_bai/ MẤT → gom TRÙNG lại từ đầu). Rule 1/12: state ở userData.
import data_dir
try:
    _DD, _PROC = data_dir.lay_data_dir()       # set MC_DATA_DIR/VC_PROCESSED_DIR + tạo thư mục, trả (dd, pr)
    _GOM_BASE = os.path.dirname(_DD.rstrip("/\\")) or _DD   # gốc userData (cha của 'data')
except Exception:
    _GOM_BASE = GOC                            # fail mềm → giữ chỗ cũ (không phá luồng dev)
GOM_DIR = os.path.join(_GOM_BASE, "gom_dang_bai")
CONFIG = os.path.join(GOM_DIR, "trang_config.json")
DANG_BAI = os.path.join(GOM_DIR, "dang_bai")
LEDGER = os.path.join(DANG_BAI, "_da_gom.txt")


def _migrate_gom():
    """Di cư 1 LẦN dữ liệu gom cũ (app-src) → userData (best-effort, không raise)."""
    try:
        os.makedirs(GOM_DIR, exist_ok=True)
    except Exception:
        pass
    old_db = os.path.join(GOC, "dang_bai")
    if os.path.isdir(old_db) and not os.path.isdir(DANG_BAI):
        try:
            shutil.copytree(old_db, DANG_BAI, dirs_exist_ok=True)   # copytree chấp nhận khác ổ (copy nội dung)
        except Exception as e:
            print("migrate gom (dang_bai) fail:", e)
    old_cfg = os.path.join(GOC, "trang_config.json")
    if os.path.isfile(old_cfg) and not os.path.isfile(CONFIG):
        try:
            shutil.copy2(old_cfg, CONFIG)
        except Exception as e:
            print("migrate gom (config) fail:", e)


if _GOM_BASE != GOC:        # chỉ migrate khi thật sự đổi chỗ (bản đóng gói) — DEV giữ nguyên app-src
    _migrate_gom()

# Hậu tố biến thể đã render, kèm độ ưu tiên (cao = tốt hơn để đăng)
VARIANTS = [("_longtieng.mp4", 3), ("_phude.mp4", 2), ("_xuly.mp4", 1)]
NEN_TANG = ("douyin", "tiktok", "youtube", "bili", "xhs", "weibo")


def doc_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"trang": []}


def luu_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _safe(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s or "").strip().rstrip(". ")
    return s[:60].strip() or "trang"


def _safe_file(s):
    """Tên file an toàn (Windows/FB) — KHÔNG default, rỗng trả "" để bên gọi tự lùi."""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s or "")
    s = re.sub(r"\s{2,}", " ", s).strip().strip(". ")
    return s[:80].strip()


def _ledger():
    s = set()
    if os.path.exists(LEDGER):
        try:
            with open(LEDGER, encoding="utf-8") as f:
                s = {ln.strip() for ln in f if ln.strip()}
        except OSError:
            pass
    return s


def _ghi_ledger(key):
    os.makedirs(DANG_BAI, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(key + "\n")


def _trang_cua(loai, ten, cfg):
    """Trang (DICT) chứa từ khóa/kênh này (None nếu không thuộc trang nào)."""
    for tr in cfg.get("trang", []):
        if loai == "tu-khoa" and ten in (tr.get("tu_khoa") or []):
            return tr
        if loai == "kenh" and ten in (tr.get("kenh") or []):
            return tr
    return None


def _viet_caption(tieu_de, tr):
    """Caption = tiêu đề (ĐÃ dịch/dọn) + hashtag của trang."""
    return tao_caption.tao_caption(tieu_de, tr.get("hashtag"))


def folder_loha(loha_dir, page_ten, page_id):
    """Folder đích trong uploads LohaPage: '<Tên>_<page_id>' (contract file-service.js lastIndexOf('_'))."""
    return os.path.join(loha_dir, _safe(page_ten) + "_" + str(page_id).strip())


def _ten_tu_caption(caption, cap=120):
    """Biến caption (đa dòng: 'Tiêu đề\\n\\n#tag') → TÊN FILE 1-dòng hợp LohaPage: '<Tiêu đề> #tag1 #tag2'.
    LohaPage parseFromText(filename) cắt tại '#' đầu → caption=trước, hashtag=sau → filename LÀ caption luôn
    (khỏi cần .txt). GIỮ '#' + khoảng trắng; bỏ ký tự cấm filename Windows/FB."""
    s = " ".join((caption or "").split())                # gộp xuống-dòng → 1 dòng
    s = re.sub(r'[\\/:*?"<>|]+', " ", s)                 # bỏ ký tự cấm (GIỮ '#')
    s = re.sub(r"\s{2,}", " ", s).strip().strip(". ")
    return s[:cap].strip()


def giao_loha(dest_dir, video_path, caption, ten_goi_y="", log=print):
    """GIAO 1 video ĐÃ RENDER vào folder LohaPage (dest_dir = <loha>/<Tên>_<page_id> hoặc __group_<slug>).
    Contract đã verify (file-service.js): TÊN FILE là caption (LohaPage parse filename khi không có .txt) +
    VẪN ghi sidecar '.txt' (đa dòng/dài, LohaPage ưu tiên) TRƯỚC '.mp4' (né race watcher). ten_goi_y rỗng →
    tên file = caption 1-dòng (FLOW MỚI: kenh_nguon/phân loại); có ten_goi_y → dùng nó (gom cũ, giữ nguyên).
    DÙNG CHUNG. Trả đường dẫn .mp4 đích, hoặc None nếu lỗi."""
    ext = os.path.splitext(video_path)[1] or ".mp4"
    base = _safe_file(ten_goi_y) if ten_goi_y else (_ten_tu_caption(caption) or "video")
    ten, i = base, 2
    while os.path.exists(os.path.join(dest_dir, ten + ext)) or os.path.exists(os.path.join(dest_dir, ten + ".txt")):
        ten, i = "%s_%d" % (base, i), i + 1
    dest = os.path.join(dest_dir, ten + ext)
    txt_dest = os.path.join(dest_dir, ten + ".txt")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with open(txt_dest, "w", encoding="utf-8") as f:   # .txt TRƯỚC (sidecar sẵn khi watcher bắt .mp4)
            f.write(caption or "")
        shutil.copy2(video_path, dest)                     # .mp4 SAU
        return dest
    except OSError as e:
        log(f"  ✖ giao_loha lỗi {os.path.basename(video_path)}: {e}")
        return None


def _ung_vien():
    """Quét mọi bản ĐÃ RENDER. Trả list (stem, rank, full, loai, nhom_ten)."""
    # Gốc data/processed = env (userData/user-chọn → BỀN qua update) nếu có; else chỗ cũ.
    _proc = (os.environ.get("VC_PROCESSED_DIR") or "").strip() or os.path.join(GOC, "processed_videos")
    _data = (os.environ.get("MC_DATA_DIR") or "").strip() or os.path.join(CRAWLER, "data")
    bases = [_proc]
    for plat in NEN_TANG:
        bases.append(os.path.join(_data, plat, "videos"))
    out = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        la_processed = os.path.basename(base) == "processed_videos"
        for root, _d, files in os.walk(base):
            for f in files:
                low = f.lower()
                if not low.endswith(".mp4"):
                    continue
                rank, stem = None, None
                for suf, rk in VARIANTS:
                    if low.endswith(suf):
                        rank, stem = rk, f[: -len(suf)]
                        break
                if rank is None:
                    if la_processed:           # bản rerender (không có hậu tố biến thể)
                        rank, stem = 0, f[:-4]
                    else:
                        continue               # bản gốc chưa render -> bỏ
                parts = os.path.join(root, f).replace("\\", "/").split("/")
                loai = nhom_ten = None
                if "tu-khoa" in parts:
                    i = parts.index("tu-khoa")
                    loai, nhom_ten = "tu-khoa", parts[i + 1] if i + 1 < len(parts) else None
                elif "kenh" in parts:
                    i = parts.index("kenh")
                    loai, nhom_ten = "kenh", parts[i + 1] if i + 1 < len(parts) else None
                if not nhom_ten:
                    continue
                out.append((stem, rank, os.path.join(root, f), loai, nhom_ten))
    return out


def _dest_trang(tr, loha_dir):
    """Thư mục đích của 1 trang: LoHa (<loha>/<Tên>_<page_id>) nếu đủ page_id, else dang_bai/<Tên>/."""
    page_id = (tr.get("page_id") or "").strip()
    if loha_dir and page_id:
        return folder_loha(loha_dir, tr["ten"], page_id), "LoHa"
    return os.path.join(DANG_BAI, _safe(tr["ten"])), "dang_bai"


def _gom_the_loai(cfg, loha_dir, the_loai_paths, seen, kq, dry_run, log):
    """NHÁNH THỂ LOẠI (Kiểu 2): mỗi trang chọn N 'thể loại' (folder phân loại đã chứa video render). Copy MỌI
    .mp4 trong folder thể loại → folder Page của trang. Ledger key 'TL::<trang>::<stem>' (tách khỏi gom kênh/từ-khoá)."""
    for tr in cfg.get("trang", []):
        cats = tr.get("the_loai") or []
        if not cats:
            continue
        dest_dir, dich = _dest_trang(tr, loha_dir)
        for cat in cats:
            folder = (the_loai_paths or {}).get(cat)
            if not folder or not os.path.isdir(folder):
                continue
            for f in sorted(os.listdir(folder)):
                low = f.lower()
                if not low.endswith(".mp4"):
                    continue
                stem = None                       # bỏ hậu tố render (_longtieng/_phude/_xuly) → tiêu đề sạch
                for suf, _rk in VARIANTS:
                    if low.endswith(suf):
                        stem = f[: -len(suf)]
                        break
                if stem is None:
                    stem = f[:-4]                 # bản rerender (không hậu tố biến thể)
                key = "TL::%s::%s" % (tr["ten"], stem)
                if key in seen:
                    continue
                tieu_de = tao_caption.tieu_de_thuong(re.sub(r"_\d{4,}$", "", stem))
                ten_goi_y = _safe_file(tieu_de) or _safe_file(stem) or "video"
                if dry_run:
                    log(f"  [DRY→{dich}] {tr['ten']} (thể loại {cat}) <- {f}  ⇒  {ten_goi_y}")
                    kq[tr["ten"]] = kq.get(tr["ten"], 0) + 1
                    continue
                dest = giao_loha(dest_dir, os.path.join(folder, f), _viet_caption(tieu_de, tr),
                                 ten_goi_y=ten_goi_y, log=log)
                if dest:
                    _ghi_ledger(key)
                    seen.add(key)
                    kq[tr["ten"]] = kq.get(tr["ten"], 0) + 1
                    log(f"  ✔ [{dich}] {tr['ten']} (thể loại {cat}) <- {os.path.basename(dest)}")


def _rendered_best():
    """Mọi bản ĐÃ RENDER (processed_videos + data/*/videos) → {stem: (rank, full)} giữ rank cao nhất.
    KHÔNG lọc theo folder (dùng cho khớp theo ID kênh nguồn)."""
    _proc = (os.environ.get("VC_PROCESSED_DIR") or "").strip() or os.path.join(GOC, "processed_videos")
    _data = (os.environ.get("MC_DATA_DIR") or "").strip() or os.path.join(CRAWLER, "data")
    bases = [_proc] + [os.path.join(_data, p, "videos") for p in NEN_TANG]
    best = {}
    for base in bases:
        if not os.path.isdir(base):
            continue
        la_processed = os.path.basename(base) == "processed_videos"
        for root, _d, files in os.walk(base):
            for f in files:
                low = f.lower()
                if not low.endswith(".mp4"):
                    continue
                rank = stem = None
                for suf, rk in VARIANTS:
                    if low.endswith(suf):
                        rank, stem = rk, f[: -len(suf)]
                        break
                if rank is None:
                    if la_processed:
                        rank, stem = 0, f[:-4]
                    else:
                        continue
                if stem not in best or rank > best[stem][0]:
                    best[stem] = (rank, os.path.join(root, f))
    return best


def _id6_cands(stem):
    """id6 khả dĩ của 1 stem render (khớp video id kênh nguồn): 6 ký tự cuối stem + 6 ký tự cuối phần sau '_'."""
    return {stem[-6:], (stem.split("_")[-1] or "")[-6:]}


def da_giao_map():
    """{id6: set(tên trang)} — quét ledger 'KN::<trang>::<stem>' (Kênh nguồn) để biết 1 video (theo id6) ĐÃ
    được gom/giao vào Page/folder nào rồi. Dùng làm TAG 'đã có ở <trang>' trên lưới Kênh nguồn — tránh
    tải/render/gán trùng mà không hay."""
    m = {}
    for key in _ledger():
        if not key.startswith("KN::"):
            continue
        parts = key.split("::", 2)
        if len(parts) != 3:
            continue
        _pre, trang, stem = parts
        for id6 in _id6_cands(stem):
            if id6:
                m.setdefault(id6, set()).add(trang)
    return m


def _gom_kenh_nguon(cfg, loha_dir, seen, kq, dry_run, log):
    """(Kiểu 1) KÊNH NGUỒN: mỗi trang chọn N kênh (kid) từ Kênh nguồn → giao MỌI bản render của video THUỘC kênh đó
    (khớp theo id6 video lưu trong kenh_nguon) → folder Page. Ledger 'KN::<trang>::<stem>' (không phụ thuộc tên folder)."""
    pages = [tr for tr in cfg.get("trang", []) if tr.get("kn")]
    if not pages:
        return
    try:
        import kenh_nguon as _kn
        by_kid = {k.get("kid"): k for k in _kn.doc().get("kenh", [])}
    except Exception:
        return
    best = _rendered_best()
    stem_ids = {stem: _id6_cands(stem) for stem in best}
    for tr in pages:
        dest_dir, dich = _dest_trang(tr, loha_dir)
        id6_to_video = {}          # id6 -> bản ghi video (để lấy title_vi đã dịch qua nút "Dịch tiêu đề")
        for kid in tr.get("kn", []):
            ch = by_kid.get(kid)
            if not ch:
                continue
            for v in ch.get("videos", []):
                if v.get("id"):
                    id6_to_video[str(v["id"])[-6:]] = v
        if not id6_to_video:
            continue
        want = set(id6_to_video.keys())
        for stem, (rank, full) in sorted(best.items()):
            matched6 = stem_ids[stem] & want
            if not matched6:
                continue
            key = "KN::%s::%s" % (tr["ten"], stem)
            if key in seen:
                continue
            vmatch = id6_to_video.get(next(iter(matched6)))
            title_vi = (vmatch or {}).get("title_vi") or ""   # ƯU TIÊN tiêu đề đã chuẩn hoá (nút Dịch tiêu đề)
            tieu_de = title_vi if title_vi else tao_caption.tieu_de_thuong(re.sub(r"_\d{4,}$", "", stem))
            ten_goi_y = _safe_file(tieu_de) or _safe_file(stem) or "video"
            if dry_run:
                log(f"  [DRY→{dich}] {tr['ten']} (kênh nguồn) <- {os.path.basename(full)}  ⇒  {ten_goi_y}")
                kq[tr["ten"]] = kq.get(tr["ten"], 0) + 1
                continue
            dest = giao_loha(dest_dir, full, _viet_caption(tieu_de, tr), ten_goi_y=ten_goi_y, log=log)
            if dest:
                _ghi_ledger(key)
                seen.add(key)
                kq[tr["ten"]] = kq.get(tr["ten"], 0) + 1
                log(f"  ✔ [{dich}] {tr['ten']} (kênh nguồn) <- {os.path.basename(dest)}")


def gom(dry_run=False, log=print, the_loai_paths=None):
    """Gom bản render tốt nhất + GHI caption .txt, route theo trang.
    Có loha_uploads_dir + page_id → copy vào <loha>/<Tên>_<page_id>/ ; không thì dang_bai/<Tên>/.
    2 nguồn: (Kiểu 1) KÊNH NGUỒN (trang.kn = kid, khớp id6) + kênh/từ-khoá theo folder; (Kiểu 2) THỂ LOẠI (the_loai_paths)."""
    cfg = doc_config()
    if not cfg.get("trang"):
        log("⚠ Chưa cấu hình trang nào (trang_config.json trống).")
        return {}
    loha_dir = (cfg.get("loha_uploads_dir") or "").strip()
    if loha_dir:                                   # cảnh báo page_id không hợp lệ (LoHa cần ≥5 ký tự)
        for tr in cfg.get("trang", []):
            pid = (tr.get("page_id") or "").strip()
            if pid and len(pid) < 5:
                log(f"⚠ Trang '{tr.get('ten')}': Page ID '{pid}' < 5 ký tự — LoHa sẽ BỎ QUA. Sửa lại Page ID Facebook.")
            elif not pid:
                log(f"ℹ Trang '{tr.get('ten')}' chưa có Page ID → gom vào dang_bai/ (không đẩy thẳng LoHa).")
    seen = _ledger()
    # nhóm theo (trang, stem) -> giữ bản rank cao nhất
    best = {}
    for stem, rank, full, loai, nhom_ten in _ung_vien():
        tr = _trang_cua(loai, nhom_ten, cfg)
        if not tr:
            continue
        k = (tr["ten"], stem)
        if k not in best or rank > best[k][0]:
            best[k] = (rank, full, tr)
    kq = {}
    for (trang, stem), (rank, full, tr) in sorted(best.items()):
        if stem in seen:                       # video đã gom trước đó -> bỏ
            continue
        kq.setdefault(trang, 0)
        page_id = (tr.get("page_id") or "").strip()
        if loha_dir and page_id:
            dest_dir = folder_loha(loha_dir, trang, page_id)   # <loha>/<Tên>_<page_id>
            dich = "LoHa"
        else:
            dest_dir = os.path.join(DANG_BAI, _safe(trang))
            dich = "dang_bai"
        # TÊN FILE CHUẨN: dùng TIÊU ĐỀ ĐÃ DỊCH (bỏ chữ Hán) y như tên video tải về (LoHa ghép cặp .mp4/.txt theo stem).
        title_goc = re.sub(r"_\d{4,}$", "", stem)
        tieu_de = tao_caption.tieu_de_thuong(title_goc)
        ten_goi_y = _safe_file(tieu_de) or _safe_file(title_goc) or "video"
        if dry_run:
            log(f"  [DRY→{dich}] {trang} <- {os.path.basename(full)}  ⇒  {ten_goi_y} (+caption)")
            kq[trang] += 1
            continue
        dest = giao_loha(dest_dir, full, _viet_caption(tieu_de, tr), ten_goi_y=ten_goi_y, log=log)
        if dest:
            _ghi_ledger(stem)
            seen.add(stem)
            kq[trang] += 1
            log(f"  ✔ [{dich}] {trang} <- {os.path.basename(dest)}")
    # (Kiểu 1) KÊNH NGUỒN — giao bản render của video thuộc kênh đã chọn (khớp id6)
    _gom_kenh_nguon(cfg, loha_dir, seen, kq, dry_run, log)
    # (Kiểu 2) THỂ LOẠI — copy video từ folder phân loại đã chọn của mỗi trang
    _gom_the_loai(cfg, loha_dir, the_loai_paths, seen, kq, dry_run, log)
    tong = sum(kq.values())
    log(f"📤 Đã gom {tong} video vào {len(kq)} trang." if tong else "Không có video mới để gom.")
    return kq


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    gom(dry_run=("--dry" in sys.argv))
