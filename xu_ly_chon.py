# -*- coding: utf-8 -*-
"""
XỬ LÝ VIDEO THEO LỰA CHỌN (né bản quyền) — khách tự tick checkbox.
Áp dụng các phép biến đổi đã chọn cho 1 video, GIỮ NGUYÊN bản gốc, xuất <tên>_xuly.mp4.

Phép biến đổi (tùy chọn): lật ngang, tăng tốc, watermark, chỉnh màu, cắt đầu/cuối,
trộn nhạc nền; phụ đề Việt (che chữ Trung), lồng tiếng, tách nhạc.

Dùng:  python xu_ly_chon.py "video.mp4" --mirror --speed 1.1 --watermark --color --phude ...
In ra "LOG:..." cho web_app đọc.
"""
import argparse
import os
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import xu_ly_video as xlv
import localize

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))


def log(m):
    print("LOG:" + m, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    # Biến đổi hình/tiếng
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--watermark", action="store_true")
    ap.add_argument("--watermark-path", dest="watermark_path", default="",
                    help="ảnh watermark cụ thể (override cfg) — chọn từ spinner đã tải")
    ap.add_argument("--color", action="store_true")
    ap.add_argument("--trim-start", type=float, default=0.0)
    ap.add_argument("--trim-end", type=float, default=0.0)
    ap.add_argument("--bg-nhac", action="store_true", help="Trộn nhạc nền (trending_audio.mp3)")
    ap.add_argument("--bg-vol", type=float, default=0.0, help="Âm lượng nhạc nền 0-1 (0 = mặc định cfg)")
    # Dịch & lồng tiếng
    ap.add_argument("--phude", action="store_true")
    ap.add_argument("--no-che", action="store_true")
    ap.add_argument("--long-tieng", action="store_true")
    ap.add_argument("--tach-nhac", action="store_true")
    ap.add_argument("--khong-tieng-goc", action="store_true", help="Bỏ HẲN tiếng gốc, chỉ giữ giọng lồng tiếng Việt")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--voice", default="vi-VN-HoaiMyNeural")
    ap.add_argument("--engine", default="gemini", choices=["google", "gemini"])
    ap.add_argument("--srt-co-san", default=None, help="Ghép từ phụ đề đã sửa (bỏ qua ASR)")
    ap.add_argument("--chi-asr", dest="chi_asr", action="store_true",
                    help="DỊCH THỦ CÔNG: chỉ ASR → ghi zh.srt rồi dừng (chờ nhập SRT đã dịch)")
    ap.add_argument("--chi-dich", dest="chi_dich", action="store_true",
                    help="TRANSLATE-PREFETCH: OCR(cache)→dịch→trans-cache rồi dừng (không dub/encode)")
    ap.add_argument("--chi-dub", dest="chi_dub", action="store_true",
                    help="DUB-PREFETCH: OCR(cache)→dịch(cache)→DUB→dub-cache rồi dừng (không encode). Cho ngôn ngữ edge (mạng)")
    ap.add_argument("--dich-lai", dest="dich_lai", action="store_true",
                    help="RENDER TỪ ĐẦU: bỏ qua cache dịch+lồng tiếng → làm mới (vẫn lưu đè cache)")
    ap.add_argument("--tach-truoc", action="store_true", help="Tách giọng trước khi nhận dạng")
    ap.add_argument("--ref-audio", default=None, help="Giọng mẫu (wav) để clone bằng OmniVoice")
    ap.add_argument("--tts", default="edge", choices=["edge", "piper", "omnivoice", "supertonic"],
                    help="Giọng lồng tiếng: edge=edge-tts (cần mạng, mặc định) | "
                         "piper=nhanh nhất (offline) | omnivoice=clone (cần GPU)")
    ap.add_argument("--out-dir", default=None,
                    help="Thư mục lưu video sau xử lý (mặc định: cạnh video gốc)")
    ap.add_argument("--chu-de", dest="chu_de", default="",
                    help="Loại video để nạp quy tắc dịch chuyên đề: phim|mukbang|thread (huong_dan/*.md)")
    ap.add_argument("--ratio", default="", choices=["", "9:16", "16:9"],
                    help="Đổi tỉ lệ khung (nền mờ giữ toàn khung). Trống = giữ nguyên")
    ap.add_argument("--blur-boxes", dest="blur_boxes", default="",
                    help="JSON list [{x,y,w,h}] vùng làm mờ (xoá logo gốc), px theo video gốc")
    ap.add_argument("--logo", default="",
                    help="JSON {path,x,y,w,h} chèn logo của mình, px theo video gốc")
    ap.add_argument("--text-wm", dest="text_wm", default="",
                    help="JSON {text,x,y,w,h} watermark CHỮ (drawtext), px theo video gốc")
    ap.add_argument("--goc-vol", type=float, default=None,
                    help="Âm lượng tiếng gốc 0-1 (0 = tắt hẳn, chỉ giọng Việt). Bỏ trống = giữ logic cũ")
    ap.add_argument("--che-band", dest="che_band", default="",
                    help="Dải che chữ THỦ CÔNG 'y0,y1' (phần trăm chiều cao 0-1 từ TRÊN), override dò tự động")
    ap.add_argument("--max-speed", dest="max_speed", type=float, default=0.0,
                    help="Tốc độ ĐỌC tối đa khi nén câu tràn (vd 1.3=thong thả, 2.5=bám timing). 0 = mặc định")
    ap.add_argument("--quy-tac", dest="quy_tac", default=None,
                    help="Quy tắc dịch ĐÃ CHỌN (chung/riêng) → env DICH_QUY_TAC cho dich_gemini_web. Rỗng = KHÔNG rule")
    ap.add_argument("--asr-engine", dest="asr_engine", default="",
                    help="Lấy lời thoại: ocr=Đọc từ sub (RapidOCR PP-OCRv5) | whisper=Giọng nói (Whisper) | rỗng=mặc định(OCR→Whisper)")
    ap.add_argument("--zoom", type=float, default=1.0,
                    help="Phóng to khung (>1.0 = cắt mép, giữ độ phân giải). 1.0 = giữ nguyên. Vd 1.15 = phóng 115%%.")
    ap.add_argument("--lang-tag", default="",
                    help="Render đa ngôn ngữ: gắn mã ngôn ngữ (vd 'en','ko') vào tên output → mỗi ngôn ngữ 1 file, không đè.")
    ap.add_argument("--target-lang", dest="target_lang", default="",
                    help="Render đa ngôn ngữ: NGÔN NGỮ ĐÍCH cho video này (vd 'en','ko','fr'). Ép TARGET_LANG cho lượt render "
                         "này (dịch + lồng tiếng theo ngôn ngữ đó), KHÔNG đổi cấu hình global. Rỗng = dùng global.")
    a = ap.parse_args()
    os.environ.pop("VC_SCAN_VHASH", None)   # xoá seed scan-cache job TRƯỚC (worker bền dùng chung env) → job này tự đặt lại nếu pre-encode; không pre-encode → localize theo video_hash gốc như cũ
    if a.target_lang:
        os.environ["TARGET_LANG"] = a.target_lang   # render đa ngôn ngữ: ép đích cho lượt NÀY (localize/phu_de/dich đọc env)
        if not a.lang_tag:
            a.lang_tag = a.target_lang               # tự gắn hậu tố tên = mã ngôn ngữ (không đè file các ngôn ngữ khác)
    if a.quy_tac is not None:
        os.environ["DICH_QUY_TAC"] = a.quy_tac   # 'Cải thiện dịch' chọn chung/riêng → ép đúng rule đã tick
    if a.chu_de:
        os.environ["DICH_CHU_DE"] = a.chu_de   # ai_dich._doc_huong_dan nạp rule chuyên đề tương ứng
    if a.max_speed and a.max_speed >= 1.0:
        os.environ["DUB_MAX_SPEED"] = str(a.max_speed)   # localize._ghep_track_khop đọc env này (mức nén tối đa)
    if a.asr_engine:
        os.environ["ASR_ENGINE"] = a.asr_engine   # ocr="Đọc từ sub" | whisper="Giọng nói thành văn bản"
    che_band_manual = None
    if a.che_band:
        try:
            _p = [float(x) for x in a.che_band.split(",")]
            if len(_p) == 2 and 0.0 <= _p[0] < _p[1] <= 1.0:
                che_band_manual = (_p[0], _p[1])
        except Exception:
            che_band_manual = None

    src = os.path.abspath(a.video)
    if not os.path.isfile(src):
        # Chẩn đoán: thư mục cha còn không → biết file bị xoá hay cả thư mục mất (giúp người dùng đúng cách xử lý).
        if not os.path.isdir(os.path.dirname(src)):
            log("⚠ Video KHÔNG còn — cả thư mục đã mất (có thể bị xoá khi cập nhật/dọn ổ). Hãy CÀO LẠI rồi render. " + src)
        else:
            log("⚠ Không thấy video — file đã bị xoá/đổi tên/di chuyển (thư mục vẫn còn). Bấm 'Làm mới' danh sách rồi cào/chọn lại. " + src)
        print("XULY_DONE 0")
        sys.exit(1)
    cfg = xlv.tu_tim_ffmpeg(xlv.nap_config())
    if a.watermark_path and os.path.isfile(a.watermark_path):
        cfg["watermark_path"] = a.watermark_path   # spinner chọn watermark đã tải (override watermark cố định)
    if xlv.lay_thoi_luong(cfg, src) <= 0:   # mp4 hỏng/tải dở (thiếu moov atom)
        log("⚠ Video hỏng hoặc tải chưa xong (thiếu moov atom). Hãy tải lại video rồi thử lại.")
        print("XULY_DONE 0")
        sys.exit(1)
    thu_muc = os.path.dirname(src)
    ten = os.path.splitext(os.path.basename(src))[0]
    if getattr(a, "lang_tag", ""):
        ten = ten + "_" + a.lang_tag   # render đa ngôn ngữ: mỗi mã ngôn ngữ 1 file '<tên>_<lang>_xuly.mp4', không đè
    ra_dir = thu_muc
    if a.out_dir:
        ra_dir = os.path.abspath(a.out_dir)
        try:
            os.makedirs(ra_dir, exist_ok=True)
        except Exception as e:
            log("⚠ Không tạo được thư mục lưu: " + str(e) + " → dùng cạnh video gốc.")
            ra_dir = thu_muc
    final = os.path.join(ra_dir, ten + "_xuly.mp4")
    _n = 2                                   # KHÔNG ghi đè bản render cũ → tích luỹ ' (2)','(3)'... cùng kết quả; user tự xoá
    while os.path.exists(final):
        final = os.path.join(ra_dir, "%s (%d)_xuly.mp4" % (ten, _n))
        _n += 1

    # Tách "tăng tốc" ra khỏi biến đổi hình: tăng tốc để CUỐI cùng, sau khi
    # whisper đã nghe audio ở TỐC ĐỘ GỐC (audio nhanh -> whisper nghe sai).
    # Lật/watermark/màu/cắt vẫn làm TRƯỚC localize (để sub burn không bị lật ngược).
    co_zoom = bool(a.zoom and a.zoom > 1.0)
    co_bien_hinh = (a.mirror or a.watermark or a.color
                    or a.trim_start > 0 or a.trim_end > 0 or a.bg_nhac or co_zoom)
    co_speed = (a.speed and a.speed != 1.0)
    co_localize = a.phude or a.long_tieng or bool(a.srt_co_san) or a.chi_asr or a.chi_dich or a.chi_dub
    # CHE CHỮ ĐỘC LẬP: bật "Che chữ Trung" mà KHÔNG dịch/phụ đề/lồng tiếng → vẫn XOÁ sub Trung gốc
    # (dò dải + blur, GIỮ tiếng gốc, 1 encode nhanh, KHÔNG ASR). che_chu mặc định ON (web bỏ --no-che khi tắt).
    co_che_doc_lap = (not a.no_che) and not co_localize

    # ----- Đổi khung / logo (1 pass riêng ở cuối) -----
    import json as _json
    try:
        blur_boxes = _json.loads(a.blur_boxes) if a.blur_boxes else []
    except Exception:
        blur_boxes = []
    try:
        logo = _json.loads(a.logo) if a.logo else None
    except Exception:
        logo = None
    try:
        text_wm = _json.loads(a.text_wm) if a.text_wm else None
    except Exception:
        text_wm = None
    # text_wm có thể là DICT (1 watermark) hoặc LIST (nhiều — vd FREE: Loha Tech + watermark khách)
    if isinstance(text_wm, dict):
        _co_twm = bool((text_wm.get("text") or "").strip())
    elif isinstance(text_wm, list):
        _co_twm = any(isinstance(w, dict) and (w.get("text") or "").strip() for w in text_wm)
    else:
        _co_twm = False
    co_khung = bool(a.ratio) or bool(blur_boxes) or bool(logo and logo.get("path")) or _co_twm

    if not co_bien_hinh and not co_speed and not co_localize and not co_khung and not co_che_doc_lap:
        log("⚠ Chưa chọn phép xử lý nào.")
        print("XULY_DONE 0")
        sys.exit(1)

    work = src
    temps = []   # các file tạm cần dọn

    # Chỉ "CẮT đầu/cuối" mới cần encode TRƯỚC (whisper phải nghe đúng khung đã cắt + cắt chính xác).
    # Lật/màu/watermark/nhạc nền/TĂNG TỐC đều GỘP vào lần encode CUỐI → bỏ bớt 1–2 lần encode.
    co_cat = (a.trim_start > 0 or a.trim_end > 0)

    def _cfg_hinh(co_speed_o_day):
        """Set cfg cho 1 lần xlv encode theo lựa chọn (dùng cho B1-khi-cắt và path không-localize)."""
        cfg["mirror"] = a.mirror
        cfg["zoom"] = a.zoom          # phóng to (>1.0) — áp trong dung_lenh_ffmpeg (pass reframe trước localize)
        cfg["speed"] = a.speed if co_speed_o_day else 1.0
        if not a.color:
            cfg["color_filter"] = ""
        if not a.watermark:
            cfg["watermark_path"] = ""
        cfg["bg_audio_path"] = cfg.get("bg_audio_path", "") if a.bg_nhac else ""
        if a.bg_vol > 0:
            cfg["bg_volume"] = a.bg_vol
        cfg["trim_start"] = a.trim_start
        cfg["trim_end"] = a.trim_end

    if co_localize:
        # ---- Biến đổi hình: GỘP vào burn (không cắt) HOẶC encode trước (có cắt) ----
        burn_kw = {}
        if co_cat or co_zoom:
            # CÓ cắt HOẶC zoom: encode trước (cắt/zoom + lật/màu/watermark/nhạc nền), KHÔNG tăng tốc (để burn lo).
            # Zoom PHẢI ở đây (không gộp vào extra_vf của burn) → localize dò/che chữ Trung + burn sub trên khung ĐÃ zoom.
            _cfg_hinh(False)
            # 🐛 FIX: LẬT NGANG (hflip) — KHÔNG áp ở pre-encode! Nếu lật TRƯỚC OCR thì OCR đọc chữ Trung NGƯỢC →
            # RÁC (vd 'MAAS"a"') → Gemini dịch rác → BỊA nội dung sai. → Để mirror cho lần BURN CUỐI (burn_phude tự
            # lật toạ-độ blur/sub theo mirror như nhánh 'else'). Pre-encode chỉ zoom/cắt/màu/watermark → OCR đọc THUẬN.
            _burn_mirror = bool(a.mirror)
            cfg["mirror"] = False
            dur = xlv.lay_thoi_luong(cfg, work)
            temp = os.path.join(thu_muc, ten + "_bd_tmp.mp4")
            cmd = xlv.dung_lenh_ffmpeg(cfg, work, temp, dur)
            log("🎞 Đang cắt + biến đổi hình (zoom/watermark/màu)...")
            kq = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if kq.returncode != 0 or not os.path.isfile(temp):
                log("⚠ FFmpeg lỗi: " + (kq.stderr or "")[-400:])
                print("XULY_DONE 0")
                sys.exit(1)
            work = temp
            temps.append(temp)
            if _burn_mirror:
                burn_kw["extra_vf"] = ["hflip"]   # LẬT ở BURN CUỐI (OCR đã đọc frame chưa lật → chữ Trung THUẬN)
            # ĐA-NGÔN-NGỮ: OCR chạy trên `temp` (pre-encode) — video_hash(temp) đổi theo MTIME mỗi lần re-encode →
            # scan-cache MISS mỗi ngôn ngữ. Đặt SEED ỔN ĐỊNH = hash(GỐC) + chữ-ký transform, BỎ đường-dẫn OUTPUT temp
            # (chứa mã ngôn ngữ '_vi/_en_bd_tmp' → khác nhau!) → seed GIỐNG nhau qua các ngôn ngữ → _scan_key reuse →
            # OCR 1 LẦN, ngôn ngữ sau HIT cache. (band/dub/srt vẫn theo temp — srt/dub per-lang đúng.)
            import cache_artifact as _ca_seed
            import hashlib as _hl_seed
            _cmd_sig = [c for c in cmd if c != temp]   # bỏ đường-dẫn output temp (có mã ngôn ngữ) → seed ổn định
            os.environ["VC_SCAN_VHASH"] = "%s#%s" % (
                _ca_seed.video_hash(src) or "x",
                _hl_seed.sha1((" ".join(map(str, _cmd_sig))).encode("utf-8", "replace")).hexdigest()[:12])
        else:
            # KHÔNG cắt: dồn lật/màu/watermark/nhạc nền vào lần burn cuối (khỏi encode B1)
            vf_extra = []
            if a.mirror:
                vf_extra.append("hflip")
            if a.color and cfg.get("color_filter"):
                vf_extra.append(cfg["color_filter"])
            burn_kw = dict(extra_vf=vf_extra,
                           wm_path=(cfg.get("watermark_path") if a.watermark else None),
                           wm_pos=cfg.get("watermark_pos", "20:20"),
                           wm_scale=cfg.get("watermark_scale", ""),
                           bg_path=(cfg.get("bg_audio_path") if a.bg_nhac else None),
                           bg_vol=(a.bg_vol if a.bg_vol > 0 else cfg.get("bg_volume", 0.25)))

        # GỘP đổi-khung (logo / blur-box xoá logo gốc / watermark-chữ) vào lần burn CHÍNH khi KHÔNG reframe
        # → bỏ pass 2 "đổi khung/logo" (tiết kiệm 1 lần encode ~120s video dài). Reframe (a.ratio) đổi kích
        # thước khung nên KHÔNG gộp được → vẫn để pass 2 lo.
        _merge_khung = co_khung and not a.ratio
        if _merge_khung:
            burn_kw.update(logo=logo, text_wm=text_wm, blur_boxes=blur_boxes)

        # ---- Phụ đề / lồng tiếng (whisper nghe ở TỐC ĐỘ GỐC; tốc độ gộp vào burn) ----
        burn_sub = a.phude or (bool(a.srt_co_san) and not a.long_tieng)
        try:
            ket = localize.chay(work, model_size=a.model, che_chu=not a.no_che, burn=burn_sub,
                                lam_long_tieng=a.long_tieng, lam_tach_nhac=a.tach_nhac,
                                voice=a.voice, engine=a.engine, srt_co_san=a.srt_co_san,
                                tach_truoc=a.tach_truoc, ref_audio=a.ref_audio,
                                tts_engine=a.tts, log_fn=log, tat_tieng_goc=a.khong_tieng_goc,
                                goc_vol=a.goc_vol, chi_asr=a.chi_asr, chi_dich=a.chi_dich, che_band_manual=che_band_manual,
                                dich_lai=a.dich_lai, chi_dub=a.chi_dub,
                                speed=(a.speed if co_speed else 1.0), **burn_kw)
        except BaseException:
            # Lồng tiếng/localize lỗi giữa chừng → DỌN temp (vd _slow_tmp.mp4) rồi mới ném tiếp,
            # tránh để rác đĩa + bị liệt kê thành "video nhân đôi chưa render".
            for _t in temps:
                try: os.remove(_t)
                except OSError: pass
            raise
        if a.chi_asr:
            # DỊCH THỦ CÔNG pha 1: chỉ ASR → zh.srt (KHÔNG có video). Đổi tên srt về tên gốc + báo OK.
            cu = os.path.join(thu_muc, os.path.splitext(os.path.basename(work))[0] + ".zh.srt")
            dst = os.path.join(thu_muc, ten + ".zh.srt")
            if os.path.isfile(cu) and os.path.abspath(cu) != os.path.abspath(dst):
                try: shutil.move(cu, dst)
                except OSError: pass
            for t in temps:
                try: os.remove(t)
                except OSError: pass
            if os.path.isfile(dst):
                log("✔ Xuất phụ đề gốc xong (chờ dịch thủ công): " + os.path.basename(dst))
                print("XULY_DONE 1"); sys.exit(0)
            log("⚠ Không tạo được phụ đề gốc."); print("XULY_DONE 0"); sys.exit(1)
        if a.chi_dich:
            # TRANSLATE-PREFETCH: dịch xong → trans-cache ĐÃ lưu TRONG localize (theo scan-seed). vi.srt cạnh
            # temp là byproduct. Dọn temp + báo OK; render CHÍNH ngôn ngữ này sẽ HIT trans-cache → bỏ dịch.
            for t in temps:
                try: os.remove(t)
                except OSError: pass
            log("✔ Prefetch dịch xong (%d câu) — trans-cache sẵn cho render." % ((ket or {}).get("so_cau", 0)))
            print("XULY_DONE 1"); sys.exit(0)
        ra = (ket or {}).get("video_longtieng") or (ket or {}).get("video_phude") or ""
        if not (ra and os.path.isfile(ra)):
            # H6: localize/ASR KHÔNG ra video (video không lời thoại, whisper rỗng/CPU lỗi...).
            # Nếu người dùng CÒN chọn biến hình/tăng tốc/đổi khung → KHÔNG chết, mà lùi nhánh CHỈ-encode-hình
            # (bỏ phụ đề/lồng tiếng). Chỉ-localize (không biến hình) → vẫn dừng có thông báo như cũ.
            if co_bien_hinh or co_speed or co_khung:
                log("⚠ Không có lời thoại/ASR → chỉ áp biến hình (bỏ lồng tiếng/phụ đề).")
                # dọn temp đã tạo (vd bản cắt) rồi encode-hình lại từ GỐC cho sạch (transforms áp 1 lần đủ).
                for t in temps:
                    try: os.remove(t)
                    except OSError: pass
                temps = []
                work = src
                if co_bien_hinh or co_speed:
                    _cfg_hinh(co_speed)
                    dur = xlv.lay_thoi_luong(cfg, work)
                    temp = os.path.join(thu_muc, ten + "_bd_tmp.mp4")
                    cmd = xlv.dung_lenh_ffmpeg(cfg, work, temp, dur)
                    log("🎞 Đang xử lý hình (lật/watermark/màu/cắt/tăng tốc — 1 lần encode)...")
                    kq = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
                    if kq.returncode != 0 or not os.path.isfile(temp):
                        log("⚠ FFmpeg lỗi: " + (kq.stderr or "")[-400:])
                        print("XULY_DONE 0")
                        sys.exit(1)
                    work = temp
                    temps.append(temp)
                # nếu chỉ co_khung (không biến hình/speed) → để nguyên work=src, pass đổi khung lo bên dưới
            else:
                log("⚠ Không tạo được video phụ đề/lồng tiếng.")
                for t in temps:
                    try: os.remove(t)
                    except OSError: pass
                print("XULY_DONE 0")
                sys.exit(1)
        else:
            # đổi tên srt tạm (theo tên work) về tên gốc cho gọn; nếu out_dir khác ổ/thư mục → đưa srt đi cùng video.
            for hau in (".zh.srt", ".vi.srt"):
                cu = os.path.join(thu_muc, os.path.splitext(os.path.basename(work))[0] + hau)
                if os.path.isfile(cu):
                    moi = os.path.join(thu_muc, ten + hau)
                    try: shutil.move(cu, moi)
                    except OSError: moi = cu if os.path.isfile(cu) else None
                    # SRT-LECH: out_dir ở thư mục/ổ khác → move .srt sang đó để đi CÙNG mp4 output.
                    if moi and os.path.isfile(moi) and ra_dir and \
                            os.path.abspath(ra_dir) != os.path.abspath(thu_muc):
                        try: shutil.move(moi, os.path.join(ra_dir, ten + hau))
                        except OSError: pass
            work = ra
            temps.append(ra)
            if _merge_khung:
                co_khung = False   # đã gộp logo/watermark vào burn chính → BỎ pass 2 đổi-khung

    elif co_che_doc_lap:
        # ---- CHE CHỮ ĐỘC LẬP: xoá sub Trung gốc (blur dải) + biến đổi hình, GIỮ TIẾNG GỐC, KHÔNG ASR ----
        # CÓ cắt → encode cắt+biến-hình trước, rồi blur (burn_phude) chỉ thêm tốc độ.
        band = None
        try:
            import dai_sub
            _bd = dai_sub.detect_blur_band(work, log_fn=log)   # trả DICT {source,y0,y1,H}; "none"=không dò được
            if _bd and _bd.get("source") != "none" and _bd.get("y0") is not None:
                band = (_bd["y0"], _bd["y1"], _bd["H"],
                        _bd.get("x0", 0.0), _bd.get("x1", 1.0))   # (y0,y1,H,x0,x1) → blur HỘP cho burn_phude
        except Exception as e:
            log("⚠ Dò dải chữ Trung lỗi: " + str(e))
        if co_cat:
            _cfg_hinh(False)
            dur = xlv.lay_thoi_luong(cfg, work)
            temp0 = os.path.join(thu_muc, ten + "_bd_tmp.mp4")
            cmd = xlv.dung_lenh_ffmpeg(cfg, work, temp0, dur)
            log("🎞 Đang cắt + biến đổi hình...")
            kq = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if kq.returncode != 0 or not os.path.isfile(temp0):
                log("⚠ FFmpeg lỗi: " + (kq.stderr or "")[-400:]); print("XULY_DONE 0"); sys.exit(1)
            work = temp0; temps.append(temp0)
            vf_extra = []   # biến hình đã áp ở bước cắt
            wm_path = bg_path = None; spd = (a.speed if co_speed else 1.0)
        else:
            vf_extra = []
            if a.mirror: vf_extra.append("hflip")
            if a.color and cfg.get("color_filter"): vf_extra.append(cfg["color_filter"])
            wm_path = (cfg.get("watermark_path") if a.watermark else None)
            bg_path = (cfg.get("bg_audio_path") if a.bg_nhac else None)
            spd = (a.speed if co_speed else 1.0)
        if band:
            log("🎯 Che dải chữ Trung gốc (GIỮ tiếng, KHÔNG phụ đề/lồng tiếng) — 1 lần encode...")
        else:
            log("ℹ Không thấy dải chữ Trung → chỉ biến đổi hình (GIỮ tiếng).")
        temp = os.path.join(thu_muc, ten + "_che_tmp.mp4")
        # vi_srt=None → KHÔNG burn phụ đề; audio_path=None → GIỮ tiếng gốc; blur_band → blur đúng dải (None=bỏ che)
        ok_che = localize.burn_phude(
            work, None, temp, che_chu=bool(band), audio_path=None, log_fn=log,
            extra_vf=vf_extra, speed=spd, wm_path=wm_path,
            wm_pos=cfg.get("watermark_pos", "20:20"), wm_scale=cfg.get("watermark_scale", ""),
            bg_path=bg_path, bg_vol=(a.bg_vol if a.bg_vol > 0 else cfg.get("bg_volume", 0.25)),
            blur_band=band)
        if not ok_che or not os.path.isfile(temp):
            log("⚠ Che/encode lỗi."); print("XULY_DONE 0"); sys.exit(1)
        work = temp; temps.append(temp)

    elif co_bien_hinh or co_speed:
        # ---- KHÔNG dịch/sub: 1 LẦN encode duy nhất (cắt + lật/màu/watermark/nhạc nền + tăng tốc) ----
        _cfg_hinh(co_speed)
        dur = xlv.lay_thoi_luong(cfg, work)
        temp = os.path.join(thu_muc, ten + "_bd_tmp.mp4")
        cmd = xlv.dung_lenh_ffmpeg(cfg, work, temp, dur)
        log("🎞 Đang xử lý hình (lật/watermark/màu/cắt/tăng tốc — 1 lần encode)...")
        kq = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if kq.returncode != 0 or not os.path.isfile(temp):
            log("⚠ FFmpeg lỗi: " + (kq.stderr or "")[-400:])
            print("XULY_DONE 0")
            sys.exit(1)
        work = temp
        temps.append(temp)

    # ---- Đổi khung / blur logo / chèn logo (1 pass cuối) ----
    if co_khung:
        temp2 = os.path.join(thu_muc, ten + "_khung_tmp.mp4")
        log("🖼 Đang đổi khung/logo (tỉ lệ %s%s%s%s)..." % (
            a.ratio or "giữ nguyên",
            ", làm mờ %d vùng" % len(blur_boxes) if blur_boxes else "",
            ", chèn logo" if (logo and logo.get("path")) else "",
            ", watermark chữ" if _co_twm else ""))
        ok, err = xlv.bien_doi_khung(cfg, work, temp2, ratio=a.ratio,
                                     blur_boxes=blur_boxes, logo=logo, mirror=a.mirror,
                                     text_wm=text_wm)
        if not ok:
            # GIỮ work (bản đã render xong: localize/biến hình — phần tốn công nhất) → CHỈ bỏ pass đổi khung,
            # vẫn lưu kết quả. (Trước đây xoá CẢ temps gồm _longtieng.mp4 → mất sạch công localize 10-30 phút.)
            log("⚠ Đổi khung/logo lỗi (%s) → giữ bản đã render, bỏ qua đổi khung." % (err or "")[:140])
            try:
                if os.path.isfile(temp2):
                    os.remove(temp2)
            except OSError:
                pass
            # KHÔNG exit — rơi xuống "Xuất bản cuối" để move(work → _xuly.mp4)
        else:
            if work != src and work in temps:
                temps.remove(work)
            if work != src and os.path.isfile(work):
                try: os.remove(work)
                except OSError: pass
            work = temp2
            temps.append(temp2)

    # ---- Xuất bản cuối ----
    if work == src:
        log("⚠ Không có gì thay đổi.")
        print("XULY_DONE 0")
        sys.exit(1)
    if work in temps:
        temps.remove(work)
    shutil.move(work, final)
    for t in temps:   # dọn các tạm còn lại
        if os.path.isfile(t):
            try: os.remove(t)
            except OSError: pass

    log("✔ Xong: " + os.path.basename(final))
    print("XULY_DONE 1")


if __name__ == "__main__":
    main()
