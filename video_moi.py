# -*- coding: utf-8 -*-
"""
"Video MỚI theo kênh" — lớp phụ trên hệ theo dõi kênh, KHÔNG đụng crawl/render/ledger/data gốc.

Crawler ghi mỗi video mới của 1 kênh theo dõi vào sổ MediaCrawler/data/<nền tảng>/_video_moi.jsonl
(douyin/core.py:_ghi_video_moi). Module này:
  - tao_links(): mirror video mới sang cây video_moi_theo_kenh/<kênh>/<ngày ĐĂNG>/<file> bằng HARDLINK
                 (cùng ổ NTFS → không tốn dung lượng; khác ổ → copy). GIỮ NGUYÊN bản gốc trong data/.
  - doc_nhom(): gom theo kênh → ngày cho tab web hiển thị.
  - danh_dau_da_xem(): đánh dấu da_xem=true (KHÔNG xóa file/link — user chọn giữ hết).

Sec_uid lưu trong sổ là khóa định danh kênh bền vững (tên thư mục dùng tên kênh cho dễ đọc).
"""
import json
import os
import shutil
from datetime import datetime

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
# Gốc data = env MC_DATA_DIR (userData/user-chọn → BỀN qua update; crawler ghi _video_moi.jsonl qua
# SAVE_DATA_PATH=MC_DATA_DIR) nếu có; else chỗ cũ. Standalone (Task Scheduler) suy qua data_dir.
try:
    import data_dir as _dd
    THU_MUC_DATA = _dd.giai_quyet()[0]
except Exception:
    THU_MUC_DATA = (os.environ.get("MC_DATA_DIR") or "").strip() or os.path.join(THU_MUC_GOC, "MediaCrawler", "data")
# Sổ link "Video mới" đặt cạnh DATA_DIR (cùng userData) để BỀN qua update; tao_links() vẫn dựng lại được.
THU_MUC_MOI = os.path.join(os.path.dirname(THU_MUC_DATA) or THU_MUC_GOC, "video_moi_theo_kenh")
NEN_TANG = ["douyin"]   # nền tảng có ghi _video_moi.jsonl (thêm sau khi hook nền tảng khác)


def _so_path(nt):
    return os.path.join(THU_MUC_DATA, nt, "_video_moi.jsonl")


def _videos_dir(nt):
    return os.path.join(THU_MUC_DATA, nt, "videos")


def _safe(s):
    s = (s or "").strip() or "khong-ro"
    for c in '\\/:*?"<>|':
        s = s.replace(c, " ")
    return s.strip().rstrip(".") or "khong-ro"


def _ngay(rec, src):
    """Ngày kênh ĐĂNG (create_time); thiếu thì lấy ngày tải về (mtime của file gốc)."""
    ct = rec.get("create_time") or 0
    try:
        if ct:
            return datetime.fromtimestamp(int(ct)).strftime("%Y-%m-%d")
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
    except Exception:
        return "khong-ro"


def _doc_so(nt):
    """Đọc mọi dòng jsonl của 1 nền tảng → list dict (bỏ dòng hỏng)."""
    p, out = _so_path(nt), []
    if not os.path.isfile(p):
        return out
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def tao_links():
    """Tạo hardlink cho mọi video mới chưa có link trong cây video_moi_theo_kenh/. Trả số link mới tạo."""
    tao = 0
    for nt in NEN_TANG:
        vdir = _videos_dir(nt)
        for rec in _doc_so(nt):
            rel = rec.get("file")
            if not rel:
                continue
            src = os.path.join(vdir, *rel.split("/"))
            if not os.path.isfile(src):
                continue   # bản gốc đã bị xóa sau rerender → bỏ qua, không tạo link
            dst_dir = os.path.join(THU_MUC_MOI, _safe(rec.get("kenh")), _ngay(rec, src))
            dst = os.path.join(dst_dir, os.path.basename(src))
            if os.path.exists(dst):
                continue
            try:
                os.makedirs(dst_dir, exist_ok=True)
                try:
                    os.link(src, dst)        # hardlink: KHÔNG copy bytes, không tốn dung lượng
                except OSError:
                    shutil.copy2(src, dst)   # khác ổ đĩa (EXDEV) → đành copy
                tao += 1
            except Exception:
                pass
    return tao


def doc_nhom():
    """Gom video mới theo kênh → ngày cho web. Trả list kênh, sắp xếp kênh có video mới nhất lên đầu."""
    kenh_map = {}
    for nt in NEN_TANG:
        for rec in _doc_so(nt):
            key = rec.get("sec_uid") or rec.get("kenh") or "?"
            k = kenh_map.setdefault(key, {"kenh": rec.get("kenh") or "?",
                                          "sec_uid": rec.get("sec_uid") or "", "videos": []})
            k["videos"].append({
                "aweme_id": rec.get("aweme_id") or "",
                "tieu_de": os.path.splitext(os.path.basename(rec.get("file") or ""))[0],
                "create_time": rec.get("create_time") or 0,
                "platform": nt,
                "file": rec.get("file") or "",     # rel trong videos/<nt> → web build path /video + render (thumbnail + thao tác)
                "da_xem": bool(rec.get("da_xem")),
            })
    ds = []
    for k in kenh_map.values():
        k["videos"].sort(key=lambda v: v["create_time"], reverse=True)
        k["so_moi"] = sum(1 for v in k["videos"] if not v["da_xem"])
        k["tong"] = len(k["videos"])
        k["moi_nhat"] = k["videos"][0]["create_time"] if k["videos"] else 0
        ds.append(k)
    ds.sort(key=lambda x: (x["so_moi"] > 0, x["moi_nhat"]), reverse=True)
    return ds


def danh_dau_da_xem(aweme_ids=None, sec_uid=None):
    """Đánh dấu da_xem=true theo danh sách aweme_id hoặc cả kênh (sec_uid). KHÔNG xóa file/link. Trả số đã đánh dấu."""
    ids = set(aweme_ids or [])
    n = 0
    for nt in NEN_TANG:
        recs = _doc_so(nt)
        if not recs:
            continue
        thay = False
        for r in recs:
            if r.get("da_xem"):
                continue
            if (ids and r.get("aweme_id") in ids) or (sec_uid and r.get("sec_uid") == sec_uid):
                r["da_xem"] = True
                thay = True
                n += 1
        if thay:
            try:
                with open(_so_path(nt), "w", encoding="utf-8") as f:
                    for r in recs:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            except Exception:
                pass
    return n
