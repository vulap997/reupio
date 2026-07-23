# -*- coding: utf-8 -*-
"""
NHÁNH A — Ghép ảnh đã đè sub (_vi.png) + audio TTS (.wav) theo sub.json thành 1 video .mp4 reup
kiểu TikTok dọc 1080x1920: NỀN clip b-roll (làm mờ + tối) chạy phía sau, CARD post đè lên giữa.

- Nền: 1 clip ngẫu nhiên trong --nen-dir (mặc định video_nen/), loop cho đủ tổng thời lượng, blur+tối,
  chạy LIÊN TỤC xuyên các cảnh. Thư mục rỗng -> fallback: dùng chính ảnh card phóng to làm mờ làm nền.
- Card: mỗi item = 1 cảnh, card hiện suốt thời lượng .wav. Card vừa khung -> căn giữa; CAO quá khung
  -> tự CUỘN dọc theo đúng thời lượng đọc (xử lý text dài). Không .wav -> hiện --giay-min giây im lặng.
- Chữ đã nằm trong ảnh card (tiếng Việt nếu đã dịch, "giữ nguyên" nếu nội dung vốn tiếng Việt) -> KHÔNG cần font.

Dùng:
  python lam_video_anh.py --folder anh_chup/threads/DZVvvaTEtpD
  python lam_video_anh.py --folder ... --nen-dir video_nen --logo logo.png
"""
import argparse
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
_VIDEO_EXT = ("*.mp4", "*.mov", "*.webm", "*.mkv", "*.avi", "*.m4v")


def log(msg):
    print("LOG:" + msg, flush=True)


def _ffprobe(args):
    fp = shutil.which("ffprobe")
    if not fp:
        return ""
    r = subprocess.run([fp, "-v", "error"] + args, capture_output=True, text=True)
    return (r.stdout or "").strip()


def _thoi_luong(path):
    if not os.path.isfile(path):
        return 0.0
    try:
        return float(_ffprobe(["-show_entries", "format=duration", "-of", "csv=p=0", path]))
    except Exception:
        return 0.0


def _kich_thuoc(path):
    out = _ffprobe(["-select_streams", "v", "-show_entries", "stream=width,height",
                    "-of", "csv=s=,:p=0", path])
    try:
        w, h = out.split(",")[:2]
        return int(w), int(h)
    except Exception:
        return 0, 0


def _chon_nen(nen_dir):
    if not nen_dir or not os.path.isdir(nen_dir):
        return None
    files = []
    for e in _VIDEO_EXT:
        files += glob.glob(os.path.join(nen_dir, e))
    return random.choice(files) if files else None


def _do_sang(path, ff):
    """Độ sáng trung bình (YAVG 0..255) của 1 khung GIỮA clip — để chỉnh nền cho VỪA SÁNG.
    Trả -1 nếu không đo được."""
    dur = _thoi_luong(path)
    ss = max(0.0, dur / 2.0)
    try:
        r = subprocess.run([ff, "-ss", f"{ss:.2f}", "-i", path, "-frames:v", "1",
                            "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                            "-f", "null", "-"], capture_output=True, text=True)
        m = re.search(r"YAVG=([0-9.]+)", (r.stderr or "") + (r.stdout or ""))
        return float(m.group(1)) if m else -1.0
    except Exception:
        return -1.0


def _gradient_png(path, w, h, top=(26, 26, 58), bot=(58, 26, 74)):
    """Ảnh nền gradient dọc (xanh→tím đậm) bằng PIL — nền dự phòng KHÔNG-ĐEN (kể cả post dark-mode).
    Dựng cột 1px rồi resize cho nhanh (không loop từng pixel)."""
    from PIL import Image
    base = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        base.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    base.resize((w, h)).save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1920)
    ap.add_argument("--nen-dir", default=os.path.join(THU_MUC_GOC, "video_nen"))
    ap.add_argument("--card-w", type=int, default=880)        # bề ngang card (chừa lề + né nút TikTok bên phải)
    ap.add_argument("--logo", default="")                     # ảnh logo PNG (tuỳ chọn) -> góc trên phải
    ap.add_argument("--giay-min", type=float, default=3.0)    # thời lượng cảnh không có audio
    ap.add_argument("--nghi", type=float, default=0.6)        # khoảng lặng cuối mỗi cảnh
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    ff = shutil.which("ffmpeg")
    if not ff:
        log("⚠ Không thấy ffmpeg.")
        print("VIDEO_DONE 0", flush=True)
        return

    folder = a.folder
    sj = os.path.join(folder, "sub.json")
    if not os.path.isfile(sj):
        log(f"⚠ Không thấy {sj} (chạy lam_sub_anh.py trước).")
        print("VIDEO_DONE 0", flush=True)
        return
    try:
        items = json.load(open(sj, encoding="utf-8")).get("items") or []
    except Exception as e:
        log(f"⚠ Lỗi đọc sub.json: {str(e)[:120]}")
        print("VIDEO_DONE 0", flush=True)
        return

    # lọc item có ảnh thật + tính thời lượng từng cảnh
    canh = []
    for it in items:
        img = os.path.join(folder, it.get("anh") or "")
        if not os.path.isfile(img):
            log(f"⚠ Bỏ qua, thiếu ảnh: {it.get('anh')}")
            continue
        wavname = it.get("wav")
        wav = os.path.join(folder, wavname) if wavname else ""
        wav = wav if (wav and os.path.isfile(wav)) else ""
        dur = (_thoi_luong(wav) + a.nghi) if wav else max(0.5, a.giay_min)
        canh.append({"img": img, "wav": wav, "dur": dur})
    if not canh:
        log("⚠ Không có cảnh hợp lệ.")
        print("VIDEO_DONE 0", flush=True)
        return

    W, H, CW = a.w, a.h, min(a.card_w, a.w - 40)
    X = (W - CW) // 2
    # Vùng an toàn TikTok mobile: chừa trên ~200px, chừa đáy ~520px (caption/username + thanh điều hướng)
    RT = round(H * 0.105)          # mép trên vùng đặt card (~200 ở 1920)
    RH = H - RT - round(H * 0.27)  # chiều cao vùng đặt card (đáy né UI TikTok)
    total = sum(c["dur"] for c in canh)

    code = os.path.basename(os.path.normpath(folder))
    out = a.out or os.path.join(folder, f"{code}.mp4")
    logo = a.logo if (a.logo and os.path.isfile(a.logo)) else ""

    tmpdir = tempfile.mkdtemp(prefix="vid_", dir=folder)
    try:
        # ---- Nền: dựng 1 lần cho đủ tổng thời lượng, blur+tối, chạy liên tục ----
        nen_src = _chon_nen(a.nen_dir)
        bg_file = None
        if nen_src:
            bg_file = os.path.join(tmpdir, "_bg.mp4")
            # Độ sáng nền THÍCH ỨNG: kéo về YAVG~88 → clip TỐI (kể cả đen thui) được nâng cho HIỆN RÕ,
            # clip CHÓI thì hạ bớt để card nổi. Tránh việc trừ cứng -0.30 làm clip tối → đen tuyền.
            y = _do_sang(nen_src, ff)
            b = -0.10 if y < 0 else max(-0.22, min(0.42, (88.0 - y) / 255.0))
            if 0 <= y < 35:
                log(f"ℹ Clip nền RẤT TỐI (YAVG={y:.0f}/255) → đã nâng sáng; nên chọn clip sáng hơn cho đẹp.")
            vf_bg = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                     f"boxblur=20:1,eq=brightness={b:.3f}:saturation=1.06,fps=30,setsar=1,format=yuv420p")
            r = subprocess.run([ff, "-y", "-stream_loop", "-1", "-i", nen_src, "-t", f"{total:.3f}",
                                "-an", "-vf", vf_bg, "-c:v", "libx264", "-preset", "veryfast",
                                "-crf", "23", bg_file], capture_output=True, text=True)
            if r.returncode != 0 or not os.path.isfile(bg_file):
                log(f"⚠ Dựng nền clip lỗi → nền gradient. {(r.stderr or '')[-120:]}")
                bg_file = None
            else:
                log(f"🎞 Nền: {os.path.basename(nen_src)} (blur, {total:.1f}s)")
        if not bg_file:
            # Không có clip video_nen (rỗng/lỗi) → NỀN GRADIENT (không bao giờ đen, kể cả post dark-mode).
            # Tránh dùng ảnh card tối làm nền → ra đen thui.
            grad = os.path.join(tmpdir, "_grad.png")
            try:
                _gradient_png(grad, W, H)
                bf = os.path.join(tmpdir, "_bg.mp4")
                r = subprocess.run([ff, "-y", "-loop", "1", "-i", grad, "-t", f"{total:.3f}",
                                    "-vf", "fps=30,setsar=1,format=yuv420p", "-c:v", "libx264",
                                    "-preset", "veryfast", "-crf", "23", bf], capture_output=True, text=True)
                if r.returncode == 0 and os.path.isfile(bf):
                    bg_file = bf
                    log("🎨 Nền gradient (không có clip video_nen).")
                else:
                    log(f"⚠ Nền gradient lỗi → nền từ ảnh. {(r.stderr or '')[-120:]}")
            except Exception as e:
                log(f"⚠ Nền gradient lỗi ({str(e)[:60]}) → nền từ ảnh (có thể tối với post dark-mode).")

        segs = []
        cum = 0.0
        for i, c in enumerate(canh):
            ow, oh = _kich_thuoc(c["img"])
            CH = round(CW * oh / ow) if ow else CW
            CH -= CH % 2
            if CH <= RH:
                yexpr = str(RT + (RH - CH) // 2)            # vừa khung -> căn giữa
            else:
                yexpr = f"{RT}-({CH}-{RH})*t/{c['dur']:.3f}"  # cao quá -> cuộn dọc hết thời lượng

            inp = []
            if bg_file:
                inp += ["-ss", f"{cum:.3f}", "-t", f"{c['dur']:.3f}", "-i", bg_file]
                inp += ["-loop", "1", "-i", c["img"]]
                fc = (f"[1:v]scale={CW}:{CH}[cd];[0:v]setsar=1[bg];"
                      f"[bg][cd]overlay={X}:{yexpr}")
                vidx = 1
            else:
                inp += ["-loop", "1", "-i", c["img"]]
                fc = (f"[0:v]split=2[c0][c1];"
                      f"[c0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                      f"boxblur=18:1,eq=brightness=-0.30,setsar=1[bg];"
                      f"[c1]scale={CW}:{CH}[cd];[bg][cd]overlay={X}:{yexpr}")
                vidx = 0

            if logo:
                inp += ["-i", logo]
                lidx = vidx + 1
                fc += f"[v0];[{lidx}:v]scale=150:-1[lg];[v0][lg]overlay={W}-180:60"

            # nguồn audio
            if c["wav"]:
                inp += ["-i", c["wav"]]
                aidx = (lidx + 1) if logo else (vidx + 1)
                amap = f"{aidx}:a"
                af = ["-af", f"apad=pad_dur={a.nghi},aresample=44100", "-ac", "2", "-ar", "44100"]
            else:
                inp += ["-f", "lavfi", "-t", f"{c['dur']:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
                aidx = (lidx + 1) if logo else (vidx + 1)
                amap = f"{aidx}:a"
                af = ["-ac", "2", "-ar", "44100"]

            fc += ",fps=30,format=yuv420p[v]"
            seg = os.path.join(tmpdir, f"seg{i:03d}.mp4")
            cmd = [ff, "-y"] + inp + ["-filter_complex", fc, "-map", "[v]", "-map", amap,
                   "-t", f"{c['dur']:.3f}"] + af + [
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                   "-r", "30", "-c:a", "aac", "-b:a", "160k", seg]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not os.path.isfile(seg):
                log(f"⚠ Lỗi cảnh {i + 1}: {(r.stderr or '')[-220:]}")
                continue
            segs.append(seg)
            cum += c["dur"]
            log(f"✔ Cảnh {i + 1}/{len(canh)} ({'cuộn' if CH > RH else 'giữa'}, {c['dur']:.1f}s)")

        if not segs:
            log("⚠ Không dựng được cảnh nào.")
            print("VIDEO_DONE 0", flush=True)
            return

        listf = os.path.join(tmpdir, "list.txt")
        with open(listf, "w", encoding="utf-8") as f:
            for s in segs:
                p = os.path.abspath(s).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{p}'\n")
        r = subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", out],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(out):
            r = subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", listf,
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", out],
                               capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(out):
            log(f"⚠ Lỗi ghép video: {(r.stderr or '')[-220:]}")
            print("VIDEO_DONE 0", flush=True)
            return
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    log(f"✔ Video: {os.path.relpath(out, THU_MUC_GOC)} ({_thoi_luong(out):.1f}s, {len(segs)} cảnh)")
    print("VIDEO_DONE 1", flush=True)


if __name__ == "__main__":
    main()
