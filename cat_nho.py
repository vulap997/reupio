# -*- coding: utf-8 -*-
"""
BĂM VIDEO DÀI -> NHIỀU CLIP NGẮN theo CẢNH (PySceneDetect) — phục vụ reup shorts.

Ý tưởng: dò ranh giới CẢNH bằng PySceneDetect (ContentDetector, OpenCV, CPU-only) rồi GOM
các cảnh liền nhau thành chunk ~độ-dài-mục-tiêu, CẮT TẠI ranh giới cảnh (không cắt giữa cảnh).
Tùy chọn đổi khung 9:16 (nền mờ) ngay trong cùng lần encode qua xu_ly_video.bien_doi_khung.

Không thêm dep nặng: chỉ `scenedetect` (kéo theo opencv/numpy đã có). Chạy được cả CPU lẫn GPU.

CLI:
  python cat_nho.py <video> [thu_muc_ra] [--so-ban N | --muc-tieu 40 | --ranges file.json]
                    [--ratio 9:16] [--nguong 27] [--chinh-xac] [--phan-tich]
"""
import os
import subprocess
import sys

import xu_ly_video

# Windows: ẩn cửa sổ console của ffmpeg/ffprobe (chuẩn dự án)
_CNW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _cfg():
    """cfg đầy đủ (ffmpeg/ffprobe/encoder...) tương thích bien_doi_khung — tái dùng nạp_config."""
    cfg = xu_ly_video.tu_tim_ffmpeg(xu_ly_video.nap_config())
    cfg["crf"] = int(cfg.get("crf", 23))
    return cfg


def thoi_luong(video, ffprobe):
    """Thời lượng (giây) của video; 0.0 nếu lỗi."""
    try:
        kq = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video],
            capture_output=True, text=True, timeout=60, creationflags=_CNW)
        return float(kq.stdout.strip())
    except Exception:
        return 0.0


def phat_hien_canh(video, nguong=27.0, log_fn=print, dur=0.0):
    """Trả list (start_sec, end_sec) của TỪNG cảnh bằng PySceneDetect. [] → caller chia ĐỀU.
    Video DÀI: dò cảnh = decode TOÀN BỘ video trên CPU (i3 không GPU) → ngốn disk/CPU → từng treo máy với video
    72 phút. Nên: >40 phút BỎ dò (chia đều, tức thì); ≤40 phút dò nhưng downscale + frame_skip (nhanh, nhẹ I/O)."""
    if dur and dur > 2400:   # >40 phút: bỏ dò cảnh hẳn (tránh treo máy/disk 100%) — băm reup chia đều là đủ
        log_fn("ℹ Video dài ~%.0f phút → CHIA ĐỀU (bỏ dò cảnh để khỏi treo máy/disk 100%%)." % (dur / 60.0))
        return []
    try:
        from scenedetect import open_video, SceneManager, ContentDetector
    except Exception as e:
        log_fn("⚠ Thiếu scenedetect (%s) → cắt theo thời lượng đều." % str(e)[:60])
        return []
    try:
        v = open_video(video)
        if not dur:
            try:
                dur = v.duration.get_seconds()
            except Exception:
                dur = 0
        if dur > 2400:
            log_fn("ℹ Video dài ~%.0f phút → CHIA ĐỀU (bỏ dò cảnh)." % (dur / 60.0))
            return []
        frame_skip = 2 if dur > 900 else (1 if dur > 300 else 0)   # video dài → bỏ qua frame: nhanh + nhẹ CPU/disk
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=float(nguong)))
        try:
            sm.downscale = max(int(getattr(sm, "downscale", 1) or 1), 3 if dur > 600 else 1)   # dò ở độ phân giải thấp → nhanh
        except Exception:
            pass
        sm.detect_scenes(video=v, frame_skip=frame_skip, show_progress=False)
        return [(s.get_seconds(), e.get_seconds()) for s, e in sm.get_scene_list()]
    except Exception as e:
        log_fn("⚠ Dò cảnh lỗi (%s) → cắt theo thời lượng đều." % str(e)[:60])
        return []


def _chia_deu(s, e, muc_tieu):
    """Chia khoảng [s, e] thành các đoạn ~muc_tieu giây (đều nhau)."""
    n = max(1, int(round((e - s) / max(1.0, muc_tieu))))
    buoc = (e - s) / n
    return [(s + i * buoc, s + (i + 1) * buoc) for i in range(n)]


def gom_chunk(canh, dur_total, muc_tieu=40.0, toi_thieu=None, toi_da=None):
    """Gom các cảnh liền nhau thành chunk ~muc_tieu giây, CẮT tại ranh giới cảnh.
    - cảnh đơn dài hơn toi_da -> chia đều thành nhiều đoạn.
    - chunk cuối ngắn hơn toi_thieu -> gộp vào chunk trước.
    toi_thieu/toi_da mặc định theo TỈ LỆ muc_tieu (0.5x / 2x) để khớp mọi độ dài mục tiêu.
    Trả list (start, end). Không có cảnh -> chia đều cả video."""
    if toi_thieu is None:
        toi_thieu = muc_tieu * 0.5
    if toi_da is None:
        toi_da = muc_tieu * 2.0
    if not canh:
        return _chia_deu(0.0, dur_total, muc_tieu)
    chunks = []
    cs = canh[0][0]
    for (_s, e) in canh:
        if e - cs >= muc_tieu:      # tới ngưỡng -> chốt chunk tại CUỐI cảnh này
            chunks.append((cs, e))
            cs = e
    if cs < dur_total - 0.1:        # phần đuôi còn lại
        chunks.append((cs, dur_total))
    if len(chunks) >= 2 and (chunks[-1][1] - chunks[-1][0]) < toi_thieu:
        cuoi = chunks.pop()
        chunks[-1] = (chunks[-1][0], cuoi[1])
    out = []
    for (s, e) in chunks:
        if e - s > toi_da:
            out.extend(_chia_deu(s, e, muc_tieu))
        else:
            out.append((s, e))
    return out


def chia_N(canh, dur, n):
    """Chia [0, dur] thành ĐÚNG n đoạn ~đều nhau, mỗi mốc cắt được DỜI về ranh giới cảnh
    gần nhất (trong dung sai nửa đoạn) để không cắt giữa hành động. `canh` = list (s, e) cảnh.
    Không có cảnh gần → giữ mốc chia đều. Trả list (start, end) (bỏ đoạn < 0.5s)."""
    n = max(1, int(round(n)))
    if n <= 1 or dur <= 0:
        return [(0.0, max(dur, 0.0))]
    part = dur / n
    bounds = sorted({b for (s, e) in canh for b in (s, e) if 0.5 < b < dur - 0.5})
    used, cuts = set(), []
    for i in range(1, n):
        ideal = part * i
        best = None
        for b in bounds:
            if b not in used and (best is None or abs(b - ideal) < abs(best - ideal)):
                best = b
        if best is not None and abs(best - ideal) <= part * 0.5:
            cuts.append(best); used.add(best)
        else:
            cuts.append(ideal)
    cuts.sort()
    pts = [0.0] + cuts + [dur]
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if pts[i + 1] - pts[i] >= 0.5]


def _cat_copy(ff, video, s, d, dst):
    """Cắt nhanh KHÔNG re-encode (-c copy) — keyframe-accurate, tức thì. Trả True nếu ra dst."""
    cmd = [ff, "-y", "-ss", "%.3f" % s, "-i", video, "-t", "%.3f" % d,
           "-c", "copy", "-movflags", "+faststart", dst]
    kq = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", creationflags=_CNW)
    return kq.returncode == 0 and os.path.isfile(dst)


def cat_khoang(video, thu_muc_ra, khoang, ratio="", chinh_xac=True, log_fn=print):
    """Cắt `video` theo list `khoang` [(s, e)...] -> clip <ten>_cảnhNN[_9x16].mp4 trong `thu_muc_ra`.
    chinh_xac=True (mặc định) -> re-encode cắt chính xác frame; False + ratio="" -> -c copy nhanh.
    Trả list đường dẫn clip đã tạo."""
    video = os.path.abspath(video)
    if not os.path.isfile(video):
        log_fn("⚠ Không thấy video: %s" % video)
        return []
    cfg = _cfg()
    ff = cfg["ffmpeg_path"]
    if not thu_muc_ra:
        thu_muc_ra = os.path.join(os.path.dirname(video), "clip_nho")
    os.makedirs(thu_muc_ra, exist_ok=True)
    ten = os.path.splitext(os.path.basename(video))[0]
    doi_khung = ratio in xu_ly_video.KHUNG_RATIO
    # RESUME: thoát giữa chừng rồi băm LẠI (cùng video + cùng cấu hình) → BỎ QUA clip đã xong, làm tiếp —
    # KHÔNG xoá làm lại từ đầu (trước đây xoá hết → mất công). Chữ ký = ranges + ratio: đổi số-bản/ngưỡng/ratio
    # → ranges đổi → chữ ký khác → xoá clip cũ + làm mới (tránh sót clip sai biên/thừa). glob.escape giữ ký tự
    # đặc biệt; "_cảnh" ngăn xoá nhầm video khác cùng tiền tố.
    import glob as _g, hashlib as _h, json as _j
    _sig = _h.md5(_j.dumps([[round(s, 2), round(e, 2)] for s, e in khoang] + [ratio],
                           ensure_ascii=False).encode("utf-8")).hexdigest()
    _sigf = os.path.join(thu_muc_ra, "_bam_sig_%s.txt" % _h.md5(ten.encode("utf-8")).hexdigest()[:8])
    try:
        _resume = os.path.isfile(_sigf) and open(_sigf, encoding="utf-8").read().strip() == _sig
    except OSError:
        _resume = False
    if not _resume:
        for old in _g.glob(os.path.join(thu_muc_ra, _g.escape(ten) + "_cảnh*.mp4")):
            try:
                os.remove(old)
            except OSError:
                pass
        try:
            open(_sigf, "w", encoding="utf-8").write(_sig)
        except OSError:
            pass
    else:
        log_fn("↻ Băm tiếp (resume) — bỏ qua clip đã có của lượt trước.")
    ra = []
    for i, (s, e) in enumerate(khoang, 1):
        d = e - s
        if d < 1.0:
            continue
        hau_to = ("_" + ratio.replace(":", "x")) if doi_khung else ""
        dst = os.path.join(thu_muc_ra, "%s_cảnh%02d%s.mp4" % (ten, i, hau_to))
        # clip đã băm xong lượt trước + HỢP LỆ (ffprobe ra thời lượng) → bỏ qua; clip dở/hỏng (bị kill giữa
        # ghi → mp4 thiếu moov → dur=0) → KHÔNG skip, băm lại cho đúng.
        if _resume and os.path.isfile(dst) and thoi_luong(dst, cfg.get("ffprobe_path") or "ffprobe") > 0.5:
            ra.append(dst); log_fn("  ↳ bỏ qua (đã có): %s" % os.path.basename(dst)); continue
        if doi_khung or chinh_xac:
            # 1 lần encode: cắt [s, s+d] + (đổi khung 9:16 nếu có) — chính xác theo frame
            ok, err = xu_ly_video.bien_doi_khung(cfg, video, dst, ratio=ratio, ss=s, dur=d)
            if not ok:
                log_fn("  ⚠ cảnh%02d lỗi: %s" % (i, (err or "")[:200]))
                continue
        else:
            # nhanh: copy stream (không encode)
            if not _cat_copy(ff, video, s, d, dst):
                log_fn("  ⚠ cảnh%02d cắt -c copy lỗi → thử re-encode." % i)
                ok, err = xu_ly_video.bien_doi_khung(cfg, video, dst, ss=s, dur=d)
                if not ok:
                    log_fn("  ⚠ cảnh%02d lỗi: %s" % (i, (err or "")[:200]))
                    continue
        ra.append(dst)
        log_fn("  ✓ %s (%.1fs)" % (os.path.basename(dst), d))
    log_fn("✅ Xong: %d/%d clip → %s" % (len(ra), len(khoang), thu_muc_ra))
    return ra


def cat(video, thu_muc_ra="", muc_tieu=40.0, ratio="", nguong=27.0, chinh_xac=False, so_ban=0, log_fn=print):
    """Băm `video` thành nhiều clip trong `thu_muc_ra`.
    - so_ban > 0: chia ĐÚNG `so_ban` bản (đều nhau, dời mốc về cảnh gần nhất) — cách MỚI/khuyên dùng.
    - so_ban = 0: gom theo `muc_tieu` giây (cách cũ).
    - ratio: "" giữ khung | "9:16" | "16:9". chinh_xac: re-encode cắt chính xác frame.
    Trả list đường dẫn clip đã tạo."""
    video = os.path.abspath(video)
    if not os.path.isfile(video):
        log_fn("⚠ Không thấy video: %s" % video)
        return []
    cfg = _cfg()
    dur = thoi_luong(video, cfg["ffprobe_path"])
    if dur <= 0:
        log_fn("⚠ Không đọc được thời lượng (ffprobe). Bỏ qua.")
        return []
    canh = phat_hien_canh(video, nguong, log_fn, dur=dur)   # truyền dur → video dài tự chia đều (khỏi treo)
    if so_ban and int(so_ban) > 0:
        khoang = chia_N(canh, dur, int(so_ban))
        log_fn("🎬 %d cảnh → ✂ chia %d bản (đều + dời về cảnh%s)."
               % (len(canh), len(khoang), (" + " + ratio) if ratio else ""))
    else:
        khoang = gom_chunk(canh, dur, muc_tieu)
        log_fn("🎬 %d cảnh → ✂ băm %d clip (mục tiêu ~%.0fs%s)."
               % (len(canh), len(khoang), muc_tieu, (" + " + ratio) if ratio else ""))
    return cat_khoang(video, thu_muc_ra, khoang, ratio=ratio, chinh_xac=chinh_xac, log_fn=log_fn)


def _ha_uu_tien():
    """Hạ ưu tiên tiến trình băm xuống BELOW_NORMAL → ffmpeg con KẾ THỪA → băm chạy nền KHÔNG làm lag máy
    (nhường CPU/scheduler cho app đang dùng). NVENC/encode vẫn chạy, chỉ bớt giành CPU. Tắt: BAM_PRIORITY=normal."""
    if os.environ.get("BAM_PRIORITY", "below").lower() == "normal":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p           # handle 64-bit: PHẢI set restype/argtypes
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]   # else ctypes truncate → fail âm thầm
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)   # BELOW_NORMAL_PRIORITY_CLASS
    except Exception:
        pass


def main(argv):
    # Ép console UTF-8 để in được emoji/tiếng Việt (Windows mặc định cp1252 -> crash)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _ha_uu_tien()   # băm nền: nhường CPU cho app đang dùng → đỡ lag
    if not argv:
        print("Dùng: python cat_nho.py <video> [thu_muc_ra] "
              "[--so-ban N | --muc-tieu 40 | --ranges file.json] [--ratio 9:16] [--nguong 27] "
              "[--chinh-xac] [--phan-tich]")
        return 1
    video = argv[0]
    thu_muc_ra = ""
    muc_tieu, ratio, nguong, chinh_xac, so_ban = 40.0, "", 27.0, False, 0
    ranges_file, phan_tich = "", False
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--muc-tieu" and i + 1 < len(argv):
            muc_tieu = float(argv[i + 1]); i += 2
        elif a == "--so-ban" and i + 1 < len(argv):
            so_ban = int(float(argv[i + 1])); i += 2
        elif a == "--ranges" and i + 1 < len(argv):
            ranges_file = argv[i + 1]; i += 2
        elif a == "--ratio" and i + 1 < len(argv):
            ratio = argv[i + 1]; i += 2
        elif a == "--nguong" and i + 1 < len(argv):
            nguong = float(argv[i + 1]); i += 2
        elif a == "--chinh-xac":
            chinh_xac = True; i += 1
        elif a == "--phan-tich":
            phan_tich = True; i += 1
        elif not a.startswith("--") and not thu_muc_ra:
            thu_muc_ra = a; i += 1
        else:
            i += 1

    if phan_tich:
        # Chỉ DÒ CẢNH + thời lượng, in JSON ra stdout (cho UI xem trước, KHÔNG cắt file).
        import json
        cfg = _cfg()
        dur = thoi_luong(video, cfg["ffprobe_path"])
        canh = phat_hien_canh(video, nguong, log_fn=lambda *a, **k: None)
        print(json.dumps({"dur": dur, "scenes": [[float(s), float(e)] for s, e in canh]}))
        return 0
    if ranges_file:
        # Cắt theo ĐÚNG các khoảng đã chọn (từ bản xem trước). chinh_xac theo CỜ (mặc định False = -c copy TỨC THÌ,
        # snap keyframe gần nhất, KHÔNG re-encode → hết lag). --chinh-xac (user tick) → re-encode đúng frame.
        import json
        with open(ranges_file, encoding="utf-8-sig") as f:   # utf-8-sig: bỏ BOM nếu có
            kh = [(float(a), float(b)) for a, b in json.load(f)]
        ra = cat_khoang(video, thu_muc_ra, kh, ratio=ratio, chinh_xac=chinh_xac)
        return 0 if ra else 2
    ra = cat(video, thu_muc_ra, muc_tieu=muc_tieu, ratio=ratio, nguong=nguong,
             chinh_xac=chinh_xac, so_ban=so_ban)
    return 0 if ra else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
