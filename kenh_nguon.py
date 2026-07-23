# -*- coding: utf-8 -*-
"""
KÊNH NGUỒN — kho "trang cá nhân" kiểu TikTok cho từng KÊNH đã cào.

Ý tưởng: sau khi cào METADATA theo kênh (tim_anh --type creator, KHÔNG tải media), lưu lại thành 1 "profile"
per kênh: avatar + tên (từ link kênh) + DANH SÁCH video (id/title/thumb — như lịch sử cào, CHƯA tải). Người
dùng đặt LỊCH: mỗi ngày tự tải N video CHƯA tải (gọi cao_anh_chon như nút "tải về"), rồi nối chuỗi
render→gom→LoHa sẵn có để auto đăng.

Module này CHỈ giữ DỮ LIỆU (đọc/ghi store + merge video + đánh dấu đã tải + chọn N chưa tải). Việc cào/tải
(subprocess) do web_app điều phối (tái dùng tim_anh + cao_anh_chon).

Store để ở userData (BỀN qua auto-update; NSIS xoá app-src) — cùng cách gom_dang_bai/data_dir.
"""
import json
import os
import time

GOC = os.path.dirname(os.path.abspath(__file__))

# Gốc userData (cha của 'data') qua data_dir — fail mềm về app-src cho dev.
try:
    import data_dir
    _DD, _ = data_dir.lay_data_dir()
    _BASE = os.path.dirname(_DD.rstrip("/\\")) or _DD
except Exception:
    _BASE = GOC
STORE_DIR = os.path.join(_BASE, "kenh_nguon")
STORE = os.path.join(STORE_DIR, "kenh_nguon.json")


def _now():
    return int(time.time())


def doc():
    """Đọc store → {"loha_uploads_dir": str, "kenh": [ ... ]}. Thiếu/hỏng → rỗng."""
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("kenh"), list):
            d.setdefault("loha_uploads_dir", "")
            d.setdefault("danh_sach", [])
            return d
    except (OSError, ValueError):
        pass
    return {"loha_uploads_dir": "", "kenh": [], "danh_sach": []}


def dat_loha_dir(path):
    """Đặt thư mục uploads LohaPage (dùng chung mọi kênh) — nơi giao video."""
    cfg = doc()
    cfg["loha_uploads_dir"] = (path or "").strip()
    luu(cfg)
    return cfg["loha_uploads_dir"]


def luu(cfg):
    os.makedirs(STORE_DIR, exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE)   # ghi atomic (né race đọc-dở khi worker + UI cùng lúc)


def _kid(platform, link):
    """Khoá ổn định của 1 kênh = platform + link (chuẩn hoá thô)."""
    return "%s::%s" % ((platform or "").strip().lower(), (link or "").strip())


def _tim(cfg, platform, link):
    kid = _kid(platform, link)
    for k in cfg.get("kenh", []):
        if k.get("kid") == kid:
            return k
    return None


def _chuan_video(it):
    """1 item preview (tim_anh) → bản ghi video gọn cho store (giữ đúng field cần cho lưới + tải)."""
    return {
        "id": str(it.get("id") or ""),
        "title": (it.get("title") or "").strip(),
        "thumb": it.get("thumb") or "",
        "url": it.get("url") or "",           # cao_anh_chon dùng id/url tuỳ nền tảng
        "like": str(it.get("like") or ""),
        "time": int(it.get("time") or 0),
        "video": bool(it.get("video", True)),
        "tai": False,                          # CHƯA tải (như lịch sử cào)
    }


def them_kenh(platform, link, ten="", avatar="", sec_uid="", videos=None):
    """Thêm/cập nhật 1 kênh + MERGE danh sách video (dedup theo id, giữ 'tai' cũ). Trả bản ghi kênh."""
    cfg = doc()
    k = _tim(cfg, platform, link)
    if k is None:
        k = {
            "kid": _kid(platform, link),
            "platform": platform, "link": link,
            "ten": ten or "", "nick_goc": ten or "", "avatar": avatar or "", "sec_uid": sec_uid or "",
            "videos": [],
            "lich": {"on": False, "so_moi_ngay": 1, "gio": "09:00"},
            # đích đăng: page đơn (page_id) HOẶC group LohaPage (__group_<slug>, round-robin nhiều page)
            "dich": {"kieu": "page", "page_id": "", "page_ten": "", "group_slug": "", "hashtag": ""},
            "added_at": _now(), "cao_luc": 0,
        }
        cfg["kenh"].append(k)
    # cập nhật profile: nick_goc LUÔN theo lần cào mới; 'ten' (HIỂN THỊ) chỉ set khi user CHƯA tự đổi tên
    if ten:
        k["nick_goc"] = ten
        if not (k.get("ten") or "").strip():
            k["ten"] = ten
    if avatar:
        k["avatar"] = avatar
    if sec_uid:
        k["sec_uid"] = sec_uid
    k["cao_luc"] = _now()
    # MERGE video: giữ 'tai' của bản cũ, thêm video mới lên ĐẦU (mới nhất trước)
    cu = {v["id"]: v for v in k.get("videos", []) if v.get("id")}
    moi = []
    for it in (videos or []):
        vid = _chuan_video(it)
        if not vid["id"]:
            continue
        if vid["id"] in cu:
            vid["tai"] = cu[vid["id"]].get("tai", False)   # GIỮ trạng thái đã tải
        moi.append(vid)
    # video cũ KHÔNG xuất hiện lần cào này vẫn giữ lại (kênh xoá bài / cào ít hơn)
    ids_moi = {v["id"] for v in moi}
    for vid in k.get("videos", []):
        if vid.get("id") and vid["id"] not in ids_moi:
            moi.append(vid)
    k["videos"] = moi
    luu(cfg)
    return k


def xoa_kenh(platform, link):
    cfg = doc()
    kid = _kid(platform, link)
    n = len(cfg["kenh"])
    cfg["kenh"] = [k for k in cfg["kenh"] if k.get("kid") != kid]
    luu(cfg)
    return len(cfg["kenh"]) < n


def dat_lich(platform, link, lich):
    """Cập nhật lịch TẢI của 1 kênh (merge). lich = {on, so_moi_ngay, gio}."""
    cfg = doc()
    k = _tim(cfg, platform, link)
    if not k:
        return None
    k.setdefault("lich", {})
    for key in ("on", "so_moi_ngay", "gio"):
        if key in (lich or {}):
            k["lich"][key] = lich[key]
    luu(cfg)
    return k


def dat_dich(platform, link, dich):
    """Đặt ĐÍCH đăng của 1 kênh (page đơn hoặc group LohaPage). dich = {kieu, page_id, page_ten, group_slug, hashtag}."""
    cfg = doc()
    k = _tim(cfg, platform, link)
    if not k:
        return None
    k.setdefault("dich", {})
    for key in ("kieu", "page_id", "page_ten", "group_slug", "hashtag"):
        if key in (dich or {}):
            k["dich"][key] = dich[key]
    luu(cfg)
    return k


def doi_ten(platform, link, ten_moi):
    """Đổi TÊN HIỂN THỊ của kênh (chỉ cho thuận mắt — KHÔNG ảnh hưởng định tuyến/đích đăng)."""
    cfg = doc()
    k = _tim(cfg, platform, link)
    if not k:
        return None
    k["ten"] = (ten_moi or "").strip() or k.get("nick_goc") or k.get("ten") or ""
    luu(cfg)
    return k


def folder_dich(cfg, k):
    """Thư mục LohaPage để GIAO video của kênh k. page → <loha>/<page_ten>_<page_id>/ ; group → <loha>/__group_<slug>/.
    Trả (dest_dir, hashtag) hoặc (None, '') nếu chưa cấu hình đủ (thiếu loha_dir/page_id/group)."""
    import os as _os
    loha = (cfg.get("loha_uploads_dir") or "").strip()
    d = k.get("dich") or {}
    if not loha:
        return None, ""
    hashtag = d.get("hashtag") or ""
    if d.get("kieu") == "group":
        slug = (d.get("group_slug") or "").strip()
        if not slug:
            return None, ""
        return _os.path.join(loha, "__group_" + slug), hashtag
    pid = (d.get("page_id") or "").strip()
    if not pid or len(pid) < 5:                 # LohaPage yêu cầu page_id ≥5 ký tự
        return None, ""
    # tái dùng đúng cách đặt tên folder của gom (contract file-service.js)
    try:
        import gom_dang_bai
        return gom_dang_bai.folder_loha(loha, d.get("page_ten") or "page", pid), hashtag
    except Exception:
        _safe = (d.get("page_ten") or "page")
        return _os.path.join(loha, _safe + "_" + pid), hashtag


def danh_dau_tai(platform, link, ids):
    """Đánh dấu các video (theo id) là ĐÃ tải."""
    cfg = doc()
    k = _tim(cfg, platform, link)
    if not k:
        return 0
    ids = set(str(i) for i in (ids or []))
    n = 0
    for v in k.get("videos", []):
        if v.get("id") in ids and not v.get("tai"):
            v["tai"] = True
            n += 1
    if n:
        luu(cfg)
    return n


def dat_title_vi_batch(kid, mapping):
    """Lưu tiêu đề Việt ĐÃ CHUẨN HOÁ (nút 'Dịch tiêu đề') cho NHIỀU video cùng lúc — 1 lần ghi đĩa.
    mapping = {video_id: title_vi}. Dùng LUÔN làm caption thật khi gom→LohaPage (xem gom_dang_bai._gom_kenh_nguon)."""
    if not mapping:
        return 0
    cfg = doc()
    n = 0
    for k in cfg.get("kenh", []):
        if k.get("kid") == kid:
            for v in (k.get("videos") or []):
                t = mapping.get(v.get("id"))
                if t:
                    v["title_vi"] = t
                    n += 1
            break
    if n:
        luu(cfg)
    return n


# ------------------------------------------------------------------ DANH SÁCH (playlist RENDER, khác LohaPage
# — LohaPage tự chọn video để ĐĂNG; danh sách ở đây là để chọn NHANH lại video CẦN RENDER) ------------------

def ds_list():
    """Mọi 'danh sách' đã lưu (mọi kênh)."""
    return doc().get("danh_sach", [])


def ds_luu(ten, kid, ids, dong_bo=False, ten_tap=None):
    """Tạo/cập nhật 1 DANH SÁCH = tên + kênh + list id video (ĐÚNG thứ tự đã chọn). Bấm vào danh sách sau này
    sẽ tự tick lại đúng các video này để tải/render. `ten` CHỈ để đặt tên/tìm lại danh sách — KHÔNG tự dùng làm
    tên tập. dong_bo=True → đặt LUÔN title_vi='<ten_tap> Tập N' cho từng video theo thứ tự (đồng bộ tên tập —
    dùng làm caption thật khi đăng); ten_tap rỗng thì lùi về dùng `ten`. dong_bo=False → GIỮ tiêu đề bình
    thường (không đụng title_vi đã có, nếu có)."""
    ten = (ten or "").strip()
    if not ten:
        return None
    cfg = doc()
    arr = cfg.setdefault("danh_sach", [])
    rec = next((d for d in arr if d.get("ten") == ten), None)
    if rec is None:
        rec = {"ten": ten, "kid": kid, "ids": [], "dong_bo": False, "added_at": _now()}
        arr.append(rec)
    rec["kid"] = kid
    rec["ids"] = [str(i) for i in (ids or [])]
    rec["dong_bo"] = bool(dong_bo)
    luu(cfg)
    if dong_bo and rec["ids"]:
        goc = (ten_tap or "").strip() or ten
        mapping = {vid: "%s Tập %d" % (goc, i + 1) for i, vid in enumerate(rec["ids"])}
        dat_title_vi_batch(kid, mapping)
    return rec


def ds_xoa(ten):
    cfg = doc()
    arr = cfg.get("danh_sach", [])
    n = len(arr)
    cfg["danh_sach"] = [d for d in arr if d.get("ten") != ten]
    luu(cfg)
    return len(cfg["danh_sach"]) < n


def chua_tai(k, n=0):
    """Danh sách video CHƯA tải của 1 kênh (bản ghi kênh), mới nhất trước. n>0 = giới hạn N."""
    ds = [v for v in (k.get("videos") or []) if not v.get("tai")]
    ds.sort(key=lambda v: v.get("time", 0), reverse=True)
    return ds[:n] if n and n > 0 else ds


def thong_ke(k):
    """Tóm tắt 1 kênh cho UI (không kèm full videos)."""
    vids = k.get("videos") or []
    return {
        "kid": k.get("kid"), "platform": k.get("platform"), "link": k.get("link"),
        "ten": k.get("ten") or "", "nick_goc": k.get("nick_goc") or "", "avatar": k.get("avatar") or "",
        "sec_uid": k.get("sec_uid") or "",
        "so_video": len(vids), "so_chua_tai": sum(1 for v in vids if not v.get("tai")),
        "lich": k.get("lich") or {}, "dich": k.get("dich") or {}, "cao_luc": k.get("cao_luc") or 0,
    }
