# -*- coding: utf-8 -*-
"""
XỬ LÝ VIDEO TỰ ĐỘNG (FFmpeg Pipeline) — phục vụ học tập.

Quét thư mục raw_videos/, với mỗi file .mp4 mới:
  1. Cắt 1 giây đầu + 1 giây cuối (bỏ intro/outro/metadata nguồn)
  2. Lật ngang (hflip) đổi "vân tay" hình ảnh
  3. Chèn logo watermark vào góc (có thể resize)
  4. Trộn âm thanh gốc với nhạc nền (nhạc nền nhỏ hơn)
  5. Tái mã hóa libx264 (crf/preset cấu hình được)
Xong → lưu sang processed_videos/ → xóa file gốc.

Xử lý TUẦN TỰ (1 file/lần) để không treo máy.
Cấu hình trong xu_ly_config.json (đổi đường dẫn/tọa độ/âm lượng không cần sửa code).
"""

import json
import logging
import os
import shutil
import subprocess
import socket
import sys
import time

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")
_LOCK_SOCK = None  # giữ socket khóa để chống chạy 2 bộ render cùng lúc
FILE_CONFIG = os.path.join(THU_MUC_GOC, "xu_ly_config.json")
FILE_LOG = os.path.join(THU_MUC_GOC, "process.log")
FLAG_TAM_DUNG = os.path.join(THU_MUC_GOC, "tam_dung_cao.flag")  # ổ đầy → tạm dừng cào

MAC_DINH = {
    "raw_dir": "raw_videos",
    "processed_dir": "processed_videos",
    "watermark_path": "",
    "watermark_pos": "20:20",
    "watermark_scale": "",
    "bg_audio_path": "trending_audio.mp3",
    "bg_volume": 0.25,
    "trim_start": 1.0,
    "trim_end": 1.0,
    "mirror": True,
    "crf": 23,
    "preset": "medium",
    "video_encoder": "auto",   # auto = dùng GPU NVIDIA (h264_nvenc) nếu có, không thì libx264 (CPU)
    "audio_bitrate": "192k",
    "delete_original": True,
    "quet_tat_ca_nen_tang": True,  # True: rerender MỌI nền tảng trong MediaCrawler/data/*/videos
    "poll_interval": 5,
    "min_free_gb": 5,
    "ffmpeg_path": "ffmpeg",
    "ffprobe_path": "ffprobe",
}


# ---------------- Helper an toàn (cross-drive / filter-injection / xóa gốc) ----------------
def _rel_an_toan(p, base):
    """os.path.relpath chống ValueError khi p & base KHÁC Ổ trên Windows (Rule 13).
    Cùng ổ → y hệt relpath. Khác ổ → trả abspath (dùng cho LOG là an toàn)."""
    try:
        return os.path.relpath(p, base)
    except ValueError:
        return os.path.abspath(p)


# Whitelist màu drawtext: tên màu thông dụng ffmpeg chấp nhận (chữ thường).
_MAU_OK = {"white", "black", "red", "green", "blue", "yellow", "orange",
           "pink", "gray", "grey", "cyan", "magenta", "purple", "brown"}


def _color_an_toan(c):
    """Whitelist/escape màu watermark chữ → chống injection vào filtergraph ffmpeg.
    Cho phép tên màu trong whitelist hoặc hex RRGGBB[AA]; ngược lại ép 'white'."""
    import re
    c = (c or "white").strip().lower()
    if c in _MAU_OK:
        return c
    m = re.fullmatch(r"#?([0-9a-f]{6}([0-9a-f]{2})?)", c)
    if m:
        return "#" + m.group(1)
    return "white"


def _font_an_toan(f):
    """Font watermark chữ: chỉ nhận file có thật, mặc định arial; escape ':' cho filtergraph."""
    f = (f or "C:/Windows/Fonts/arial.ttf")
    if not os.path.isfile(f):
        f = "C:/Windows/Fonts/arial.ttf"
    return f.replace("\\", "/").replace(":", "\\:")


def _xoa_goc_neu_hop_le(src, dst, watch_dir):
    """Chỉ xóa file gốc khi dst RENDER THẬT (tồn tại + đủ lớn) → chống mất gốc khi render hỏng.
    Dọn luôn thư mục con rỗng (không đụng watch_dir đang theo dõi)."""
    try:
        if os.path.isfile(dst) and os.path.getsize(dst) > 100_000:   # >100KB = render thật, không phải file rỗng/lỗi
            os.remove(src)
            logging.info("🗑 Đã xóa file gốc (cào): %s", os.path.basename(src))
            d = os.path.dirname(src)
            if watch_dir and os.path.abspath(d) != os.path.abspath(watch_dir) and not os.listdir(d):
                os.rmdir(d)
        else:
            logging.warning("Giữ file gốc — output thiếu/quá nhỏ: %s", dst)
    except OSError as e:
        logging.warning("Không xóa được file gốc %s: %s", os.path.basename(src), e)


# ---------------- Cấu hình & log ----------------
def nap_config() -> dict:
    cfg = dict(MAC_DINH)
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"[CẢNH BÁO] Lỗi đọc config, dùng mặc định: {e}")
    # ViralCrawl: thư mục video ĐÃ RENDER = env VC_PROCESSED_DIR (userData/user-chọn → BỀN qua update) nếu có.
    _proc_env = (os.environ.get("VC_PROCESSED_DIR") or "").strip()
    if _proc_env:
        cfg["processed_dir"] = _proc_env
    # Chuẩn hóa đường dẫn tương đối -> tuyệt đối (theo thư mục script)
    for k in ("raw_dir", "processed_dir", "watermark_path", "bg_audio_path"):
        if cfg.get(k) and not os.path.isabs(cfg[k]):
            cfg[k] = os.path.join(THU_MUC_GOC, cfg[k])
    return cfg


def setup_log():
    # Ép console dùng UTF-8 để in được tiếng Việt (Windows mặc định cp1252)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(FILE_LOG, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------- Kiểm tra FFmpeg ----------------
def tim_exe(base):
    """Tìm 1 exe (base = 'ffmpeg' | 'ffprobe'): PATH -> BUNDLE (vendor/ffmpeg/bin) -> winget.
    Trả về đường dẫn tuyệt đối nếu thấy; không thấy gì thì trả tên trần `base`
    (để subprocess báo lỗi rõ ràng). Dùng CHUNG cho web_app/xu_ly_video/localize."""
    p = shutil.which(base)
    if p:
        return p
    here = os.path.dirname(os.path.abspath(__file__))
    exe = base + ".exe"
    # bundle: app đóng gói (file ở app-src) -> ../vendor ; dev (repo) -> desktop/vendor
    for b in (os.path.join(here, "..", "vendor", "ffmpeg", "bin"),
              os.path.join(here, "desktop", "vendor", "ffmpeg", "bin")):
        c = os.path.join(b, exe)
        if os.path.isfile(c):
            return os.path.abspath(c)
    import glob as _glob
    winget = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    hits = _glob.glob(os.path.join(winget, "**", exe), recursive=True) if winget else []
    return hits[0] if hits else base


def tu_tim_ffmpeg(cfg):
    """Điền ffmpeg_path/ffprobe_path khi chưa hợp lệ. Ưu tiên BUNDLE kèm app
    (vendor/ffmpeg/bin — khách KHÔNG cần cài gì), rồi winget. Lưới đỡ phòng khi
    childEnv (desktop) chưa kịp thêm vendor vào PATH."""
    for key, base in (("ffmpeg_path", "ffmpeg"), ("ffprobe_path", "ffprobe")):
        val = cfg.get(key, "")
        if shutil.which(val) or (val and os.path.isfile(val)):
            continue
        found = tim_exe(base)
        if os.path.isfile(found) or shutil.which(found):   # chỉ ghi đè khi tìm THẬT ra
            cfg[key] = found
            logging.info(f"Tự tìm thấy {base}: {found}")
    return cfg


def kiem_tra_ffmpeg(cfg) -> bool:
    """Kiểm tra ffmpeg & ffprobe có chạy được không."""
    for ten, duong_dan in (("ffmpeg", cfg["ffmpeg_path"]), ("ffprobe", cfg["ffprobe_path"])):
        path = shutil.which(duong_dan) or (duong_dan if os.path.isfile(duong_dan) else None)
        if not path:
            logging.error(
                f"KHÔNG tìm thấy {ten}! Hãy cài FFmpeg và thêm vào PATH.\n"
                f"  • Cách 1 (Windows 10/11): mở PowerShell gõ:  winget install Gyan.FFmpeg\n"
                f"  • Cách 2: tải tại https://www.gyan.dev/ffmpeg/builds/ , giải nén, "
                f"thêm thư mục bin vào biến môi trường PATH.\n"
                f"  • Hoặc đặt đường dẫn đầy đủ tới {ten}.exe trong xu_ly_config.json "
                f"(khóa '{ten}_path')."
            )
            return False
    return True


# ---------------- Tiện ích ----------------
def lay_thoi_luong(cfg, path) -> float:
    """Lấy thời lượng video (giây) bằng ffprobe. Trả 0 nếu lỗi."""
    try:
        kq = subprocess.run(
            [cfg["ffprobe_path"], "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return float(kq.stdout.strip())
    except Exception:
        return 0.0


def _bitrate_nguon(ffmpeg_path, path) -> int:
    """Bitrate VIDEO stream của nguồn (bps) qua ffprobe → để cap maxrate NVENC không encode cao hơn nguồn.
    Ưu tiên stream bit_rate; thiếu → format bit_rate (trừ ~audio). 0 nếu không đọc được (→ bỏ cap, an toàn)."""
    ffp = tim_exe("ffprobe") or "ffprobe"
    try:
        r = subprocess.run(
            [ffp, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=bit_rate", "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        v = (r.stdout or "").strip()
        if v and v.isdigit() and int(v) > 0:
            return int(v)
    except Exception:
        pass
    try:   # stream bit_rate N/A (1 số mp4) → dùng format bit_rate (gồm audio, trừ ~192k cho khỏi cap oan)
        r = subprocess.run(
            [ffp, "-v", "error", "-show_entries", "format=bit_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        v = (r.stdout or "").strip()
        if v and v.isdigit() and int(v) > 200000:
            return int(v) - 192000
    except Exception:
        pass
    return 0


def file_on_dinh(path, cho=2.0) -> bool:
    """Kiểm tra file đã ghi xong chưa (kích thước không đổi)."""
    try:
        s1 = os.path.getsize(path)
        if s1 == 0:
            return False
        time.sleep(cho)
        return os.path.getsize(path) == s1
    except OSError:
        return False


def kiem_tra_o_cung(cfg) -> bool:
    """Còn đủ dung lượng không? Nếu thiếu -> tạo flag tạm dừng cào."""
    try:
        free_gb = shutil.disk_usage(cfg["processed_dir"]).free / (1024 ** 3)
    except Exception:
        free_gb = 999
    if free_gb < cfg["min_free_gb"]:
        if not os.path.exists(FLAG_TAM_DUNG):
            with open(FLAG_TAM_DUNG, "w", encoding="utf-8") as f:
                f.write(f"O cung con {free_gb:.1f}GB < nguong {cfg['min_free_gb']}GB")
            logging.warning(f"Ổ cứng còn {free_gb:.1f}GB (< {cfg['min_free_gb']}GB) "
                            f"→ TẠM DỪNG cào (tạo {os.path.basename(FLAG_TAM_DUNG)}).")
        return False
    # đủ chỗ lại → gỡ flag
    if os.path.exists(FLAG_TAM_DUNG):
        try:
            os.remove(FLAG_TAM_DUNG)
            logging.info("Ổ cứng đã đủ chỗ → bỏ tạm dừng cào.")
        except OSError:
            pass
    return True


# ---------------- Chọn encoder (GPU NVIDIA nếu có) ----------------
_NVENC = None


def co_nvenc(ffmpeg_path="ffmpeg", che_do="auto") -> bool:
    """True nếu nên encode bằng h264_nvenc (GPU NVIDIA). che_do: auto/nvenc/cpu.
    'auto' = thử encode thử 1 frame; lỗi (không GPU/driver, vd máy AMD/CPU) → False.
    Kết quả cache lại để khỏi thử nhiều lần."""
    global _NVENC
    che_do = (che_do or "auto").lower()
    if che_do == "cpu":
        return False
    if che_do == "nvenc":
        return True
    if _NVENC is None:
        try:
            r = subprocess.run([ffmpeg_path, "-hide_banner", "-loglevel", "error",
                                "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
                                "-c:v", "h264_nvenc", "-f", "null", "-"],
                               capture_output=True, timeout=30)
            _NVENC = (r.returncode == 0)
            logging.info("Encoder video: %s", "h264_nvenc (GPU)" if _NVENC else "libx264 (CPU)")
        except Exception:
            _NVENC = False
    return _NVENC


# ---------------- Dựng lệnh FFmpeg ----------------
def dung_lenh_ffmpeg(cfg, src, dst, duration) -> list:
    """Tạo danh sách tham số ffmpeg cho 1 video."""
    trim_start = float(cfg["trim_start"])
    trim_end = float(cfg["trim_end"])
    eff_dur = duration - trim_start - trim_end if duration > 0 else 0

    co_watermark = bool(cfg.get("watermark_path")) and os.path.isfile(cfg["watermark_path"])
    co_bg = bool(cfg.get("bg_audio_path")) and os.path.isfile(cfg["bg_audio_path"])

    cmd = [cfg["ffmpeg_path"], "-y"]
    # Cắt đầu/cuối ngay khi đọc input 0 (nếu video đủ dài)
    if eff_dur > 0.5:
        cmd += ["-ss", str(trim_start), "-t", str(eff_dur)]
    cmd += ["-i", src]                                  # input 0: video gốc
    idx = 1
    wm_idx = bg_idx = None
    if co_watermark:
        cmd += ["-i", cfg["watermark_path"]]            # input: logo
        wm_idx = idx
        idx += 1
    if co_bg:
        cmd += ["-i", cfg["bg_audio_path"]]             # input: nhạc nền
        bg_idx = idx
        idx += 1

    speed = float(cfg.get("speed", 1.0) or 1.0)

    filtres = []
    # ----- Video: zoom (phóng to, cắt mép) + hflip + tăng tốc (setpts) -----
    vf = []
    _zoom = float(cfg.get("zoom", 1.0) or 1.0)
    if _zoom > 1.0:   # phóng to Z×: scale up rồi crop TÂM về kích thước gốc (giữ độ phân giải, cắt mép). trunc(.../2)*2 = dim CHẴN cho h264.
        vf.append(f"scale=iw*{_zoom}:ih*{_zoom},crop=trunc(iw/{_zoom}/2)*2:trunc(ih/{_zoom}/2)*2")
    if cfg.get("mirror"):
        vf.append("hflip")
    if cfg.get("color_filter"):
        vf.append(cfg["color_filter"])  # chỉnh màu nhẹ (đổi vân tay nhưng vẫn dễ nhìn)
    if speed != 1.0:
        vf.append(f"setpts=PTS/{speed}")
    if vf:
        filtres.append(f"[0:v]{','.join(vf)}[vbase]")
        cur = "vbase"
    else:
        cur = "0:v"
    if co_watermark:
        if cfg.get("watermark_scale"):
            filtres.append(f"[{wm_idx}:v]scale={cfg['watermark_scale']}[wm]")
            wm_lab = "wm"
        else:
            wm_lab = f"{wm_idx}:v"
        filtres.append(f"[{cur}][{wm_lab}]overlay={cfg['watermark_pos']}[vout]")
        video_map = "[vout]"
    else:
        video_map = f"[{cur}]" if cur != "0:v" else "0:v"

    # ----- Âm thanh: tăng tốc (atempo) + trộn nhạc nền -----
    af = []
    if speed != 1.0:
        af.append(f"atempo={speed}")  # atempo hỗ trợ 0.5–2.0
    if co_bg:
        if af:
            filtres.append(f"[0:a]{','.join(af)}[a0]")
            orig_a = "a0"
        else:
            orig_a = "0:a"
        filtres.append(f"[{bg_idx}:a]volume={cfg['bg_volume']}[bg]")
        filtres.append(f"[{orig_a}][bg]amix=inputs=2:duration=first:normalize=0[aout]")
        audio_map = "[aout]"
    elif af:
        filtres.append(f"[0:a]{','.join(af)}[aout]")
        audio_map = "[aout]"
    else:
        audio_map = "0:a?"

    if filtres:
        cmd += ["-filter_complex", ";".join(filtres)]
    cmd += ["-map", video_map, "-map", audio_map]
    if co_nvenc(cfg["ffmpeg_path"], cfg.get("video_encoder", "auto")):
        # GPU NVIDIA: nhanh hơn nhiều, nhả CPU cho việc khác (vd crawl chạy song song).
        # NVENC kém hiệu quả hơn x264 → KHÔNG dùng chung số crf (cq=crf=23 → ~6.7Mbps phình 3.4×). Dùng cq
        # RIÊNG cao hơn (mặc định 28 ~4.3Mbps, đồng bộ localize._enc_video). Chỉnh: env NVENC_CQ.
        cq = (os.environ.get("NVENC_CQ", "") or "28").strip()
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                "-cq", cq, "-b:v", "0"]
        # CAP BITRATE theo NGUỒN: cq28 hay encode ra bitrate CAO HƠN nguồn (đo thật: nguồn 2.64Mbps → ra
        # 3.96Mbps, phình 1.5×) = phí đĩa + upload chậm, KHÔNG thêm chất lượng (nội dung gốc đã nén ở nguồn).
        # → maxrate ~= bitrate nguồn × hệ số (mặc định 1.2, dư biên cho vùng chuyển động). Đo thật: file giảm
        # ~45% (29→16MB), thời gian encode gần như không đổi, chất lượng giữ. Tắt: NVENC_CAP_SRC=0.
        if os.environ.get("NVENC_CAP_SRC", "1") != "0":
            _brs = _bitrate_nguon(cfg.get("ffmpeg_path", "ffmpeg"), src)
            if _brs > 0:
                try:
                    _he_so = float(os.environ.get("NVENC_CAP_HESO", "1.2") or 1.2)
                except ValueError:
                    _he_so = 1.2
                _maxr = int(_brs * _he_so)
                cmd += ["-maxrate", str(_maxr), "-bufsize", str(_maxr * 2)]
    else:
        cmd += ["-c:v", "libx264", "-crf", str(cfg["crf"]), "-preset", cfg["preset"]]
    cmd += ["-c:a", "aac", "-b:a", cfg["audio_bitrate"], "-movflags", "+faststart", dst]
    return cmd


def lay_kich_thuoc(cfg, path):
    """(rộng, cao) của video bằng ffprobe. Trả (0,0) nếu lỗi.
    cfg có thể chỉ có 'ffmpeg_path' (vd burn_phude) → tự tìm ffprobe, tránh KeyError → (0,0) → dims fallback SAI."""
    ffprobe = cfg.get("ffprobe_path") or tim_exe("ffprobe") or "ffprobe"
    try:
        kq = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=s=x:p=0", path],
            capture_output=True, text=True, timeout=60)
        w, h = kq.stdout.strip().split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 0, 0


def _enc_args(cfg):
    """Tham số encoder video (NVENC nếu có, không thì libx264) — dùng chung."""
    if co_nvenc(cfg["ffmpeg_path"], cfg.get("video_encoder", "auto")):
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                "-cq", str(cfg["crf"]), "-b:v", "0"]
    return ["-c:v", "libx264", "-crf", str(cfg["crf"]), "-preset", cfg["preset"]]


# Tỉ lệ đích -> kích thước chuẩn
KHUNG_RATIO = {"9:16": (1080, 1920), "16:9": (1920, 1080)}


def khung_filter_parts(cfg, src, in_lab, n0=0, blur_boxes=None, logo=None,
                       logo_in_lab="1:v", text_wm=None, mirror=False):
    """Dựng các node filter LOGO / BLUR-BOX (xoá logo gốc) / WATERMARK-CHỮ (KHÔNG reframe) cho 1 filter_complex.
    DÙNG CHUNG: bien_doi_khung (pass riêng) + localize.burn_phude (GỘP vào 1 encode khi không reframe).
    - in_lab: nhãn video VÀO (vd 'v0' hoặc 'vmsk'). logo_in_lab: nhãn input ảnh logo (caller TỰ thêm '-i').
    - n0: số bắt đầu cho nhãn 'vN' (tránh trùng nhãn của caller).
    - mirror=True: video đã hflip → tự lật x của blur_boxes (px) cho trúng. logo/text-wm dùng biểu thức W/H
      runtime nên KHÔNG cần lật.
    Trả (parts, out_lab, n, tw_files). tw_files = file tạm drawtext (caller PHẢI dọn SAU khi chạy ffmpeg)."""
    import tempfile
    blur_boxes = blur_boxes or []
    parts = []
    cur = in_lab
    n = n0
    tw_files = []
    src_w = (lay_kich_thuoc(cfg, src)[0] if (mirror and blur_boxes) else 0)
    # ----- Làm mờ từng vùng (xoá logo gốc) -----
    for b in blur_boxes:
        try:
            x, y, w, h = int(b["x"]), int(b["y"]), int(b["w"]), int(b["h"])
        except Exception:
            continue
        if w <= 0 or h <= 0:
            continue
        if mirror and src_w > 0:
            x = max(0, src_w - x - w)
        n += 1
        a, c, bl, out = f"v{n}a", f"v{n}c", f"v{n}b", f"v{n}"
        parts.append(f"[{cur}]split[{a}][{c}]")
        parts.append(f"[{c}]crop={w}:{h}:{x}:{y},gblur=sigma=14:steps=2[{bl}]")   # gblur (ko cap chroma) thay boxblur=12 (vỡ box NHỎ: chroma radius max 10)
        parts.append(f"[{a}][{bl}]overlay={x}:{y}[{out}]")
        cur = out
    # ----- Chèn logo của mình (CAP CỨNG chống "logo siêu to") -----
    if logo and logo.get("path") and os.path.isfile(logo["path"]):
        sw, sh = lay_kich_thuoc(cfg, src)
        sw, sh = (sw or 854), (sh or 480)
        if logo.get("phu_kin") and all(_k in logo for _k in ("x", "y", "w", "h")):
            # CHE KÍN logo nguồn (auto): logo của mình PHỦ ĐỦ BỀ NGANG đoạn blur (user chốt) → scale theo
            # WIDTH vùng blur, cao AUTO giữ tỉ lệ (KHÔNG hở 2 mép như 'decrease' cũ). Cao cap 40%H (logo dọc
            # lạ khỏi tràn). Cap ngang 35%W chống phình khi dò lệch. blur (đã xoá logo nguồn) nằm dưới.
            lw = max(8, min(int(logo["w"]), int(sw * 0.35)))
            lx = max(0, min(int(logo["x"]), sw - lw))
            hcap = max(8, int(sh * 0.40))
            ly = max(0, min(int(logo["y"]), sh - 8))
            n += 1
            out = f"v{n}"
            parts.append(f"[{logo_in_lab}]scale={lw}:-2,crop={lw}:min(ih\\,{hcap}):0:0[lg]")
            parts.append(f"[{cur}][lg]overlay={lx}:{ly}[{out}]")
            cur = out
        else:
            slot = max(24, int(sw * 0.08))
            goc = (logo.get("goc") or "").strip().lower()
            if goc not in ("tr", "tl", "br", "bl"):
                try:
                    lx, ly, lw, lh = int(logo["x"]), int(logo["y"]), int(logo["w"]), int(logo["h"])
                    cx, cy = lx + lw / 2.0, ly + lh / 2.0
                    goc = ("b" if cy > sh / 2.0 else "t") + ("r" if cx > sw / 2.0 else "l")
                except Exception:
                    goc = "tr"
            pos = {"tr": "W-w-12:12", "tl": "12:12", "br": "W-w-12:H-h-12",
                   "bl": "12:H-h-12"}.get(goc, "W-w-12:12")
            n += 1
            out = f"v{n}"
            parts.append(f"[{logo_in_lab}]scale={slot}:{slot}:force_original_aspect_ratio=decrease[lg]")
            parts.append(f"[{cur}][lg]overlay={pos}[{out}]")
            cur = out
    # ----- Watermark CHỮ (drawtext) — ghi chữ ra file UTF-8 tránh escaping + dấu tiếng Việt -----
    _tw_list = text_wm if isinstance(text_wm, list) else ([text_wm] if isinstance(text_wm, dict) else [])
    # NHIỀU watermark CHẠY → mỗi cái 1 BĂNG DỌC riêng (không đè dọc) + lệch pha ngang.
    n_run = sum(1 for _t in _tw_list
                if isinstance(_t, dict) and (_t.get("text") or "").strip() and _t.get("chay"))
    run_idx = 0
    for _tw in _tw_list:
        if not isinstance(_tw, dict):
            continue
        _tw_text = (_tw.get("text") or "").strip()
        if not _tw_text:
            continue
        try:
            tx, ty = int(_tw.get("x", 0)), int(_tw.get("y", 0))
            th = int(_tw.get("h", 0)) or 40
            fs = max(12, int(th * 0.8))
            _fd, _twf = tempfile.mkstemp(prefix="_vc_wm_", suffix=".txt")
            with os.fdopen(_fd, "w", encoding="utf-8") as _f:
                _f.write(_tw_text)
            tw_files.append(_twf)
            font = _font_an_toan(_tw.get("font"))
            tfp = _twf.replace("\\", "/").replace(":", "\\:")
            color = _color_an_toan(_tw.get("color"))
            n += 1
            out = f"v{n}"
            if _tw.get("chay"):
                bn = max(1, n_run)
                bi = run_idx
                _B = "(h-text_h)/%d" % bn
                px = r"x=abs(mod(120*t+%d*(w-text_w)\,2*(w-text_w))-(w-text_w))" % bi
                py = r"y=%d*(h-text_h)/%d+abs(mod(80*t\,2*(%s))-(%s))" % (bi, bn, _B, _B)
                run_idx += 1
            elif _tw.get("goc"):
                _wp = {"br": ("w-text_w-14", "h-text_h-14"), "tr": ("w-text_w-14", "14"),
                       "tl": ("14", "14"), "bl": ("14", "h-text_h-14")}.get(_tw["goc"], ("w-text_w-14", "h-text_h-14"))
                px, py = "x=" + _wp[0], "y=" + _wp[1]
            else:
                px, py = f"x={tx}", f"y={ty}"
            parts.append(f"[{cur}]drawtext=fontfile='{font}':textfile='{tfp}':"
                         f"{px}:{py}:fontsize={fs}:fontcolor={color}:borderw=2:bordercolor=black@0.7[{out}]")
            cur = out
        except Exception:
            pass
    return parts, cur, n, tw_files


def co_text_wm(text_wm):
    """text_wm (dict/list) có watermark chữ hợp lệ không — để caller quyết có cần khung-pass / input không."""
    if isinstance(text_wm, dict):
        return bool((text_wm.get("text") or "").strip())
    if isinstance(text_wm, list):
        return any(isinstance(w, dict) and (w.get("text") or "").strip() for w in text_wm)
    return False


def bien_doi_khung(cfg, src, dst, ratio="", blur_boxes=None, logo=None, mirror=False,
                   ss=None, dur=None, text_wm=None):
    """1 PASS ffmpeg: làm mờ vùng (xoá logo gốc) -> chèn logo của mình -> đổi tỉ lệ khung
    (nền mờ giữ toàn khung). Toạ độ tính theo PIXEL của video GỐC (như bộ vẽ hiển thị).

    - blur_boxes: [{x,y,w,h}, ...] vùng làm mờ. mirror=True -> tự lật x (logo gốc đã bị
      hflip nên dịch sang phía đối diện) để blur trúng.
    - logo: {path, x, y, w, h} chèn logo (KHÔNG lật x — giữ đúng vị trí màn hình người vẽ).
    - ratio: "" giữ nguyên | "9:16" | "16:9".
    - ss/dur: (giây) CẮT đoạn [ss, ss+dur] trong CÙNG lần encode (cho chức năng băm clip —
      cat_nho.py). None = cả video. -ss đặt TRƯỚC -i: seek nhanh keyframe rồi decode tới ss,
      khi re-encode cho cắt CHÍNH XÁC theo frame.
    Trả True nếu tạo được dst.
    """
    blur_boxes = blur_boxes or []

    cmd = [cfg["ffmpeg_path"], "-y"]
    if ss is not None:
        cmd += ["-ss", "%.3f" % float(ss)]
    cmd += ["-i", src]
    if dur is not None:
        cmd += ["-t", "%.3f" % float(dur)]
    logo_ok = bool(logo and logo.get("path") and os.path.isfile(logo["path"]))
    if logo_ok:
        cmd += ["-i", logo["path"]]

    parts = ["[0:v]null[v0]"]
    _kp, cur, n, tw_files = khung_filter_parts(cfg, src, "v0", 0, blur_boxes, logo, "1:v", text_wm, mirror)
    parts += _kp
    # ----- Đổi tỉ lệ khung (nền mờ giữ toàn khung) -----
    if ratio in KHUNG_RATIO:
        ow, oh = KHUNG_RATIO[ratio]
        n += 1
        out = f"v{n}"
        parts.append(f"[{cur}]split[rbg][rfg]")
        parts.append(f"[rbg]scale={ow}:{oh}:force_original_aspect_ratio=increase,"
                     f"crop={ow}:{oh},boxblur=20:3,setsar=1[rbgb]")
        parts.append(f"[rfg]scale={ow}:{oh}:force_original_aspect_ratio=decrease,setsar=1[rfgs]")
        parts.append(f"[rbgb][rfgs]overlay=(W-w)/2:(H-h)/2[{out}]")
        cur = out

    cmd += ["-filter_complex", ";".join(parts), "-map", f"[{cur}]", "-map", "0:a?"]
    cmd += _enc_args(cfg)
    # RE-ENCODE audio (KHÔNG copy): 1 số video crawl về có AAC channel-config "khác chuẩn" → `-c:a copy`
    # truyền payload hỏng ("channel element not allocated", mất tiếng). Encode lại AAC stereo chuẩn cho an toàn.
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100", "-movflags", "+faststart", dst]

    try:
        kq = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if kq.returncode != 0 or not os.path.isfile(dst):
            # audio copy có thể fail (codec lạ) -> thử lại với aac
            cmd2 = cmd[:-3] + ["-c:a", "aac", "-b:a", cfg.get("audio_bitrate", "192k"),
                               "-movflags", "+faststart", dst]
            kq = subprocess.run(cmd2, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if kq.returncode != 0 or not os.path.isfile(dst):
                return False, (kq.stderr or "")[-500:]
        return True, ""
    finally:
        for _twf in tw_files:                     # TEMP-LEAK: dọn các file chữ watermark
            if os.path.isfile(_twf):
                try:
                    os.remove(_twf)
                except OSError:
                    pass


# ---------------- Danh sách thư mục cần quét ----------------
def cac_thu_muc_quet(cfg):
    """Trả [(thu_muc_quet, thu_muc_goc_de_tinh_rel)].
    Bật quet_tat_ca_nen_tang -> quét data/<nen_tang>/videos, giữ tên nền tảng trong đường ra."""
    if cfg.get("quet_tat_ca_nen_tang", True):
        # Gốc data = env MC_DATA_DIR (userData/user-chọn → BỀN qua update) nếu có; else chỗ cũ.
        base = (os.environ.get("MC_DATA_DIR") or "").strip() or os.path.join(THU_MUC_CRAWLER, "data")
        ds = []
        for plat in ("douyin", "tiktok", "youtube", "bili", "xhs", "weibo", "kuaishou",
                     "twitter", "instagram"):
            d = os.path.join(base, plat, "videos")
            if os.path.isdir(d):
                ds.append((d, base))   # rel tính từ data/ -> đường ra có "douyin/videos/..."
        if ds:
            return ds
    # Mặc định: 1 thư mục raw_dir (rel tính từ chính nó -> đường ra không có tên nền tảng)
    return [(cfg["raw_dir"], cfg["raw_dir"])]


# ---------------- Xử lý 1 file ----------------
def xu_ly_file(cfg, src, base_dir=None, watch_dir=None) -> bool:
    base_dir = base_dir or cfg["raw_dir"]
    watch_dir = watch_dir or base_dir
    try:
        rel = os.path.relpath(src, base_dir)
    except ValueError:
        # src & base_dir KHÁC Ổ (Windows) → relpath ném ValueError. Đặt PHẲNG file vào
        # processed_dir bằng basename thay vì văng (Rule 13). Hiếm gặp; log để biết.
        rel = os.path.basename(src)
        logging.warning("Nguồn khác ổ với base_dir → đặt phẳng vào processed_dir: %s", rel)
    dst = os.path.join(cfg["processed_dir"], rel)
    if os.path.exists(dst):
        logging.info(f"Đã có bản rerender, bỏ qua: {rel}")
        if cfg.get("delete_original"):
            try:
                os.remove(src)
                logging.info(f"🗑 Xóa bản gốc trùng: {rel}")
            except OSError:
                pass
        return True
    os.makedirs(os.path.dirname(dst) or cfg["processed_dir"], exist_ok=True)

    if not file_on_dinh(src):
        logging.info(f"File đang được ghi, chờ lượt sau: {rel}")
        return False

    duration = lay_thoi_luong(cfg, src)
    logging.info(f"▶ Bắt đầu xử lý: {rel} (thời lượng {duration:.1f}s)")
    t0 = time.time()
    cmd = dung_lenh_ffmpeg(cfg, src, dst, duration)
    try:
        kq = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except Exception as e:
        logging.error(f"Lỗi gọi ffmpeg: {e}")
        return False

    if kq.returncode != 0:
        logging.error(f"FFmpeg lỗi với {rel}:\n{(kq.stderr or '')[-1500:]}")
        # dọn file lỗi (nếu có)
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        return False

    logging.info(f"✔ Xong: {rel} ({time.time()-t0:.1f}s) → {_rel_an_toan(dst, THU_MUC_GOC)}")

    # Dọn file gốc — CHỈ khi dst render THẬT (tồn tại + đủ lớn) để không mất gốc khi render hỏng (DELETE-ORIG).
    if cfg.get("delete_original"):
        _xoa_goc_neu_hop_le(src, dst, watch_dir)
    return True


# ---------------- Vòng lặp chính ----------------
def quet_va_xu_ly(cfg):
    """Quét tất cả thư mục cần theo dõi, xử lý tuần tự từng file .mp4."""
    files = []   # (src, base_dir, watch_dir)
    for watch_dir, base_dir in cac_thu_muc_quet(cfg):
        for root, _dirs, names in os.walk(watch_dir):
            for n in names:
                if n.lower().endswith(".mp4"):
                    files.append((os.path.join(root, n), base_dir, watch_dir))
    files.sort()
    for src, base_dir, watch_dir in files:
        if not kiem_tra_o_cung(cfg):
            logging.warning("Tạm dừng xử lý do ổ cứng đầy.")
            break
        try:
            xu_ly_file(cfg, src, base_dir, watch_dir)  # TUẦN TỰ — 1 file/lần
        except Exception as e:
            logging.error(f"Lỗi không mong đợi với {src}: {e}")


def _da_chay_roi() -> bool:
    """Chống chạy 2 bộ render cùng lúc (bind 1 cổng cục bộ; bind lỗi = đã có bản đang chạy)."""
    global _LOCK_SOCK
    _LOCK_SOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _LOCK_SOCK.bind(("127.0.0.1", 47654))
        return False
    except OSError:
        return True


def main():
    setup_log()
    if _da_chay_roi():
        logging.info("Đã có 1 bộ render đang chạy → thoát (tránh trùng).")
        return
    cfg = nap_config()
    logging.info("=" * 50)
    logging.info("Khởi động bộ xử lý video (FFmpeg pipeline).")

    cfg = tu_tim_ffmpeg(cfg)
    if not kiem_tra_ffmpeg(cfg):
        sys.exit(1)

    os.makedirs(cfg["raw_dir"], exist_ok=True)
    os.makedirs(cfg["processed_dir"], exist_ok=True)
    if not (cfg.get("watermark_path") and os.path.isfile(cfg["watermark_path"])):
        logging.warning(f"Không thấy logo watermark ({cfg.get('watermark_path')}) → bỏ qua chèn logo.")
    if not (cfg.get("bg_audio_path") and os.path.isfile(cfg["bg_audio_path"])):
        logging.warning(f"Không thấy nhạc nền ({cfg.get('bg_audio_path')}) → giữ nguyên âm thanh gốc.")

    ds_quet = [d for d, _ in cac_thu_muc_quet(cfg)]
    logging.info("Theo dõi %d thư mục (quét mỗi %ss):" % (len(ds_quet), cfg["poll_interval"]))
    for d in ds_quet:
        logging.info("  • " + os.path.relpath(d, THU_MUC_GOC))
    try:
        while True:
            quet_va_xu_ly(cfg)
            time.sleep(float(cfg["poll_interval"]))
    except KeyboardInterrupt:
        logging.info("Đã dừng bộ xử lý (người dùng).")


if __name__ == "__main__":
    main()
