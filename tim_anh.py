# -*- coding: utf-8 -*-
"""
TÌM bài (XEM TRƯỚC) trên nền tảng có ảnh — phục vụ học tập.

Chạy MediaCrawler search ở chế độ CHỈ-METADATA (env MC_GET_MEDIAS=0, KHÔNG tải media)
rồi đọc jsonl → in 1 dòng JSON danh sách bài cho web hiển thị (thumbnail + tiêu đề),
để người dùng TICK chọn bài muốn cào (cả bài VIDEO lẫn bài ẢNH — dùng ảnh bìa làm preview).

Dùng:  python tim_anh.py --platform xhs --type search  --keyword "..." --count 20
       python tim_anh.py --platform dy  --type creator --creator "<id/link kênh>" --count 20
In:     {"ok": true, "items": [{"id","title","thumb","loai","video","so_anh","url","like","nick"}]}
"""
import argparse
import glob
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GOC = os.path.dirname(os.path.abspath(__file__))
MC = os.path.join(GOC, "MediaCrawler")
# python cho subprocess = python ĐANG CHẠY (sys.executable). Từ v0.1.20 venv ở userData -> hardcode cũ WinError 2.
PY = sys.executable or os.path.join(MC, ".venv", "Scripts", "python.exe")
if os.path.basename(PY).lower() == "pythonw.exe":
    _p = os.path.join(os.path.dirname(PY), "python.exe")
    PY = _p if os.path.exists(_p) else PY
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# mã nền tảng (web) -> thư mục dữ liệu MediaCrawler (data/<folder>)
DATA_FOLDER = {"xhs": "xhs", "rednote": "rednote", "dy": "douyin", "wb": "weibo", "bili": "bili"}

# Dấu hiệu trong log MediaCrawler cho biết đang CHỜ ĐĂNG NHẬP (cookie hết hạn / chưa login).
# So khớp KHÔNG phân biệt hoa-thường: log thật in chữ thường ("waiting for scan code login")
# còn tên hàm in dạng '[XiaoHongShuLogin.login_by_qrcode]'.
_DAU_HIEU_LOGIN = ("账号未登录", "未登录", "登录已过期", "登录失效", "login_by_qrcode",
                   "begin login", "waiting for scan code", "scan code login",
                   "need login", "请通过验证")
MSG_LOGIN = ("Phiên đăng nhập đã hết hạn (hoặc chưa đăng nhập) — "
             "hãy ĐĂNG NHẬP LẠI nền tảng rồi thử lại.")
MSG_QUA_LAU = ("Tìm quá lâu nên đã dừng — nền tảng có thể đang chặn hoặc bạn "
               "chưa đăng nhập. Hãy ĐĂNG NHẬP LẠI rồi thử lại.")


def _txt(x):
    """Chuẩn hoá stdout/stderr -> str ('' nếu None; bytes -> decode)."""
    if x is None:
        return ""
    return x if isinstance(x, str) else x.decode("utf-8", "replace")


def _can_dang_nhap(out):
    """out có dấu hiệu MediaCrawler đang chờ đăng nhập không (thường-hoá rồi so)."""
    low = _txt(out).lower()
    return any(m in low for m in _DAU_HIEU_LOGIN)


def _jsonl_files(folder):
    # jsonl ở env MC_DATA_DIR (userData/user-chọn → BỀN qua update) nếu có; else chỗ cũ MediaCrawler/data.
    _data = (os.environ.get("MC_DATA_DIR") or "").strip() or os.path.join(MC, "data")
    return glob.glob(os.path.join(_data, folder, "jsonl", "*contents*.jsonl"))


def _nid(d):
    return str(d.get("note_id") or d.get("aweme_id") or d.get("video_id") or d.get("id") or "")


def _snapshot_lines(folder):
    """{filepath: số dòng hiện tại} TRƯỚC search — để biết dòng nào search VỪA thêm."""
    snap = {}
    for f in _jsonl_files(folder):
        try:
            with open(f, encoding="utf-8", errors="ignore") as fp:
                snap[f] = sum(1 for _ in fp)
        except OSError:
            snap[f] = 0
    return snap


def _rows_vua_them(folder, snap):
    """Các dòng search VỪA THÊM sau snapshot (dòng vượt số cũ + file mới). Dedup theo id, giữ bản mới nhất.
    -> Trả ĐÚNG kết quả của LẦN search NÀY, KỂ CẢ bài đã từng cào trước đó (không lọc theo lịch sử —
    đó là bug cũ làm 'Tìm thấy 0 bài' khi search từ khóa quen)."""
    seen = {}
    for f in sorted(_jsonl_files(folder), key=os.path.getmtime):
        old = snap.get(f, 0)
        try:
            fp = open(f, encoding="utf-8")
        except OSError:
            continue
        with fp:
            for i, line in enumerate(fp):
                if i < old:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                nid = _nid(d)
                if nid:
                    seen[nid] = d
    return list(seen.values())


def _seen_ids_before(folder, snap):
    """Tập ID đã CÓ TRƯỚC lần search này (dòng < snapshot) = 'đã từng tìm thấy lần trước'.
    Dùng để ĐẨY bài cũ xuống dưới, bài MỚI TINH lên trên (KHÔNG ẩn — chỉ sắp xếp)."""
    ids = set()
    for f in _jsonl_files(folder):
        old = snap.get(f, 0)
        if old <= 0:
            continue
        try:
            fp = open(f, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fp:
            for i, line in enumerate(fp):
                if i >= old:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    nid = _nid(json.loads(line))
                except Exception:
                    continue
                if nid:
                    ids.add(nid)
    return ids


def _item_xhs(d):
    imgs = [u for u in (d.get("image_list") or "").split(",") if u.strip()]
    loai = d.get("type") or ""
    co_video = bool((d.get("video_url") or "").strip()) or loai == "video"
    return {
        "id": str(d.get("note_id") or ""),
        "title": (d.get("title") or d.get("desc") or "").strip()[:160],
        "thumb": imgs[0] if imgs else "",
        "loai": "video" if co_video else "anh",
        "video": co_video,
        "so_anh": len(imgs),
        "url": d.get("note_url") or "",
        "like": str(d.get("liked_count") or ""),
        "time": int(d.get("time") or d.get("create_time") or 0),
        "nick": d.get("nickname") or "",
        "user_id": str(d.get("user_id") or ""),   # gom TÁC GIẢ → gợi ý kênh THẬT (link profile)
        "avatar": d.get("avatar") or "",
    }


def _item_dy(d):
    imgs = [u for u in (d.get("note_download_url") or "").split(",") if u.strip()]
    co_video = bool((d.get("video_download_url") or "").strip())
    return {
        "id": str(d.get("aweme_id") or ""),
        "title": (d.get("title") or d.get("desc") or "").strip()[:160],
        "thumb": d.get("cover_url") or (imgs[0] if imgs else ""),
        "loai": "video" if co_video else "anh",
        "video": co_video,
        "so_anh": len(imgs),
        "url": d.get("aweme_url") or "",          # Douyin detail nhận URL
        "like": str(d.get("liked_count") or ""),
        "cmt": str(d.get("comment_count") or ""),
        "time": int(d.get("create_time") or 0),   # epoch giây (lọc ngày đăng). Douyin KHÔNG có view.
        "nick": d.get("nickname") or "",
    }


def _item_wb(d):
    imgs = [u for u in (d.get("image_list") or "").split(",") if u.strip()]
    return {
        "id": str(d.get("note_id") or ""),
        "title": (d.get("content") or "").strip()[:160],
        "thumb": imgs[0] if imgs else "",
        "loai": "anh",
        "video": False,
        "so_anh": len(imgs),
        "url": str(d.get("note_id") or ""),       # Weibo detail nhận note_id
        "like": str(d.get("liked_count") or ""),
        "time": int(d.get("create_time") or d.get("time") or 0),
        "nick": d.get("nickname") or "",
    }


def _item_bili(d):
    return {
        "id": str(d.get("video_id") or ""),
        "title": (d.get("title") or d.get("desc") or "").strip()[:160],
        "thumb": d.get("video_cover_url") or "",
        "loai": "video",
        "video": True,
        "so_anh": 0,
        "url": d.get("video_url") or "",          # Bilibili detail nhận URL
        "like": str(d.get("liked_count") or ""),
        "view": str(d.get("video_play_count") or ""),   # Bili CÓ view (lượt xem)
        "cmt": str(d.get("video_comment") or ""),
        "time": int(d.get("create_time") or 0),         # epoch giây (lọc ngày đăng)
        "nick": d.get("nickname") or "",
    }


_PARSER = {"xhs": _item_xhs, "rednote": _item_xhs, "dy": _item_dy, "wb": _item_wb, "bili": _item_bili}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True)   # xhs/dy/wb/bili (mã web)
    ap.add_argument("--type", default="search")    # search (từ khóa) | creator (kênh)
    ap.add_argument("--keyword", default="")       # khi --type search
    ap.add_argument("--creator", default="")       # khi --type creator (id/link kênh, phẩy cho nhiều)
    ap.add_argument("--count", default="20")
    ap.add_argument("--headless", default="yes")
    a = ap.parse_args()

    folder = DATA_FOLDER.get(a.platform)
    parser = _PARSER.get(a.platform)
    if not folder or not parser:
        print(json.dumps({"ok": False, "msg": "Nền tảng chưa hỗ trợ xem trước: " + a.platform}))
        return

    # XHS/RedNote CREATOR: API user_posted bị CAPTCHA 461 (automation-detect + thiếu xsec_token động) DÙ trình
    # duyệt render được trang kênh (account/IP KHÔNG bị chặn) → đi BROWSER-FIRST: xhs_browser.py mở profile bằng
    # Playwright (persistent context đã login) + cuộn + parse DOM card. Search/ảnh + nền khác giữ đường httpx cũ.
    if a.platform in ("xhs", "rednote") and a.type == "creator":
        if not a.creator.strip():
            print(json.dumps({"ok": False, "msg": "Chưa nhập kênh."}, ensure_ascii=False)); return
        prof = os.path.join(os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(MC, "browser_data"),
                            f"{a.platform}_user_data_dir")
        lenh = [PY, os.path.join(GOC, "xhs_browser.py"), "--action", "list",
                "--url", a.creator, "--count", str(a.count),
                "--intl", "1" if a.platform == "rednote" else "0",
                "--profile", prof, "--headless", a.headless]
        try:
            kq = subprocess.run(lenh, cwd=MC, creationflags=_NO_WINDOW, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=1800)
        except subprocess.TimeoutExpired:
            print(json.dumps({"ok": False, "msg": "Tải danh sách kênh quá lâu (trình duyệt) — thử lại."}, ensure_ascii=False)); return
        for line in reversed((kq.stdout or "").strip().splitlines()):   # in lại dòng JSON cuối xhs_browser xuất
            if line.strip().startswith("{"):
                print(line.strip()); return
        print(json.dumps({"ok": False, "msg": "Không đọc được kết quả trình duyệt. " + (kq.stderr or "")[:160]}, ensure_ascii=False))
        return

    snap = _snapshot_lines(folder)

    env = os.environ.copy()
    env["MC_GET_MEDIAS"] = "0"   # CHỈ metadata — KHÔNG tải ảnh/video
    mc_plat = a.platform
    if a.platform in ("xhs", "rednote"):   # rednote = XHS QUỐC TẾ: cùng crawler 'xhs', khác domain/profile/data
        mc_plat = "xhs"
        env["MC_XHS_INTL"] = "1" if a.platform == "rednote" else "0"
        env["MC_XHS_PROFILE"] = f"{a.platform}_user_data_dir"
        env["MC_XHS_LEAF"] = a.platform
    # Cùng đường cào như chay_crawl nhưng MC_GET_MEDIAS=0 -> chỉ lấy danh sách (jsonl) để xem trước.
    if a.type == "creator":
        if not a.creator.strip():
            print(json.dumps({"ok": False, "msg": "Chưa nhập kênh."}))
            return
        lenh = [PY, "main.py", "--platform", mc_plat, "--lt", "qrcode",
                "--type", "creator", "--creator_id", a.creator,
                "--crawler_max_notes_count", str(a.count),
                "--get_comment", "no", "--save_data_option", "jsonl",
                "--headless", a.headless]
        env.setdefault("DY_CREATOR_SORT", "newest")
    else:
        if not a.keyword.strip():
            print(json.dumps({"ok": False, "msg": "Chưa nhập từ khóa."}))
            return
        lenh = [PY, "main.py", "--platform", mc_plat, "--lt", "qrcode",
                "--type", "search", "--keywords", a.keyword,
                "--crawler_max_notes_count", str(a.count),
                "--get_comment", "no", "--save_data_option", "jsonl",
                "--headless", a.headless]
    try:
        kq = subprocess.run(lenh, cwd=MC, env=env, creationflags=_NO_WINDOW,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    except subprocess.TimeoutExpired as e:
        # Cào treo tới hết giờ — gần như luôn vì đang CHỜ QUÉT QR (login headless không quét được,
        # MediaCrawler retry tới 600s). KHÔNG in chuỗi 'Command [...] timed out' khó hiểu cho khách:
        # đọc output dở (TimeoutExpired vẫn giữ stdout đã bắt) để nhận diện đang chờ đăng nhập.
        out = _txt(e.stdout) + _txt(e.stderr)
        msg = MSG_LOGIN if _can_dang_nhap(out) else MSG_QUA_LAU
        print(json.dumps({"ok": False, "msg": msg}, ensure_ascii=False))
        return
    except Exception as e:
        print(json.dumps({"ok": False, "msg": "Lỗi tìm: " + str(e)[:200]}, ensure_ascii=False))
        return

    seen0 = _seen_ids_before(folder, snap)   # ID đã thấy ở lần search TRƯỚC → sẽ đẩy xuống dưới
    items = []
    for d in _rows_vua_them(folder, snap):
        it = parser(d)
        if isinstance(it, dict):
            it["da_thay"] = _nid(d) in seen0   # đã từng tìm thấy lần trước (chưa chắc đã tải)
        items.append(it)
    # 0 bài + MediaCrawler báo lỗi -> nói RÕ nguyên nhân thay vì "0 bài" mập mờ.
    if not items:
        out = (kq.stdout or "") + (kq.stderr or "")
        low = out.lower()
        # Phân biệt RÕ nguyên nhân (đừng để khách tưởng "kênh không có video"):
        # 1) CAPTCHA / 461 = XHS đòi xác minh người thật (risk-control IP/account)
        _ten = "RedNote" if a.platform == "rednote" else "Xiaohongshu"
        if any(m in low for m in ("captcha", "verifytype", "461")):
            if a.type == "search":   # search bị CAPTCHA cả API lẫn browser → hướng dẫn cào theo KÊNH
                _msg = (_ten + " CHẶN tìm theo TỪ KHÓA (xác minh CAPTCHA — cả API lẫn trình duyệt đều bị chặn ở khâu tìm kiếm). "
                        "Cách dùng: (1) Cào theo LINK KÊNH (dán link trang kênh — đường này KHÔNG bị chặn như tìm từ khóa), "
                        "hoặc (2) Tìm theo từ khóa trên nền tảng khác (Douyin/YouTube/Bilibili ổn định hơn).")
            else:
                _msg = (_ten + " yêu cầu xác minh (CAPTCHA) — tài khoản/IP đang bị nghi ngờ. Thử TÀI KHOẢN uy tín hơn "
                        "(cũ, đã xác minh SĐT) hoặc ĐỔI IP/mạng rồi thử lại.")
            print(json.dumps({"ok": False, "msg": _msg}, ensure_ascii=False))
            return
        # 2) -104 = tài khoản không có quyền truy cập API (account mới/bị hạn chế)
        if "-104" in out or "没有权限" in out or "权限访问" in out:
            print(json.dumps({"ok": False, "msg": "Tài khoản hiện tại KHÔNG được phép truy cập API " + _ten + " (−104). Hãy đăng nhập bằng TÀI KHOẢN uy tín hơn (cũ, đã xác minh SĐT) hoặc đổi IP."}, ensure_ascii=False))
            return
        # 3) Chưa đăng nhập / phiên hết hạn (gồm cả nhánh abort 'Chưa đăng nhập ... KHÔNG cào được')
        if _can_dang_nhap(out) or "chưa đăng nhập" in low or "không cào được" in low:
            print(json.dumps({"ok": False, "msg": MSG_LOGIN}, ensure_ascii=False))
            return
        # 4) Bị chặn IP / lỗi mạng
        if "ipblockerror" in low or "300012" in out or "network connection error" in low:
            print(json.dumps({"ok": False, "msg": "Nền tảng tạm chặn truy cập (anti-bot). Nghỉ vài phút, tắt VPN hoặc đổi mạng, giảm số lượng rồi thử lại."}, ensure_ascii=False))
            return
        # 5) Lỗi lấy dữ liệu khác
        if any(m in out for m in ("DataFetchError", "RetryError")):
            print(json.dumps({"ok": False, "msg": "Nền tảng từ chối yêu cầu — phiên có thể hết hạn hoặc bị chặn. Hãy ĐĂNG NHẬP LẠI (đợi vào trang chủ rồi mới đóng) hoặc đổi IP rồi thử lại."}, ensure_ascii=False))
            return
        # 6) Không lỗi rõ ràng = thật sự 0 nội dung
    print(json.dumps({"ok": True, "items": items, "tong": len(items)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
