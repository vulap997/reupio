# -*- coding: utf-8 -*-
"""Cắt giọng MẪU clone về độ dài hợp lý cho F5-TTS.

Giọng mẫu clone lý tưởng ~5–15 giây. Mẫu QUÁ DÀI làm F5 chậm (điều kiện hoá dài) + chất lượng
thường KÉM hơn (lẫn nhiều ngữ điệu/khoảng lặng). Script này:
  - Nếu mẫu đã đủ ngắn (≤ max): chỉ chuẩn hoá mono 24kHz (giữ nguyên nội dung).
  - Nếu DÀI hơn max: bỏ khoảng LẶNG đầu rồi lấy 1 đoạn nói liền ~target giây.

Dùng:
  python cat_giong_clone.py input.mp3 output.wav [--target 12] [--max 15]
In "OK|<độ dài giây>" nếu xong, "ERR" nếu lỗi.
Cũng dùng được như module: cat_giong_clone.cat(inp, out, target=12, maxs=15) -> bool.
"""
import os
import sys
import shutil
import argparse
import subprocess

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))


def _exe(ten):
    """Tìm ffmpeg/ffprobe: ưu tiên bundle của app (xu_ly_video.tim_exe), rồi PATH."""
    try:
        sys.path.insert(0, THU_MUC_GOC)
        import xu_ly_video
        e = xu_ly_video.tim_exe(ten)
        if e:
            return e
    except Exception:
        pass
    return shutil.which(ten) or ten


def thoi_luong(path):
    """Độ dài audio (giây), 0 nếu lỗi."""
    try:
        r = subprocess.run([_exe("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def cat(inp, out, target=12.0, maxs=15.0):
    """Cắt giọng mẫu về ~target giây (bỏ lặng đầu) NẾU dài hơn maxs; ngắn rồi thì giữ nguyên.
    Luôn xuất mono 24kHz wav. Trả True nếu out hợp lệ."""
    ff = _exe("ffmpeg")
    if not os.path.isfile(inp):
        return False
    dur = thoi_luong(inp)
    # Đã đủ ngắn → chỉ chuẩn hoá định dạng (KHÔNG cắt nội dung)
    if dur <= maxs + 0.5:
        r = subprocess.run([ff, "-y", "-i", inp, "-ac", "1", "-ar", "24000", out],
                           capture_output=True)
        return r.returncode == 0 and os.path.isfile(out)
    # DÀI → bỏ khoảng lặng ĐẦU (để mẫu bắt đầu ngay tại giọng nói) rồi lấy `target` giây liền mạch
    af = "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-38dB"
    r = subprocess.run([ff, "-y", "-i", inp, "-af", af, "-t", str(target),
                        "-ac", "1", "-ar", "24000", out], capture_output=True)
    if r.returncode == 0 and os.path.isfile(out) and thoi_luong(out) >= 1.0:
        return True
    # Fallback (silenceremove lỗi / ra quá ngắn): lấy thẳng `target` giây đầu
    r = subprocess.run([ff, "-y", "-i", inp, "-t", str(target), "-ac", "1", "-ar", "24000", out],
                       capture_output=True)
    return r.returncode == 0 and os.path.isfile(out)


def main():
    ap = argparse.ArgumentParser(description="Cắt giọng mẫu clone về độ dài hợp lý cho F5-TTS")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--target", type=float, default=12.0, help="Độ dài đích khi cắt (giây)")
    ap.add_argument("--max", type=float, default=15.0, help="Vượt ngưỡng này mới cắt (giây)")
    a = ap.parse_args()
    ok = cat(a.input, a.output, target=a.target, maxs=a.max)
    print(("OK|%.1f" % thoi_luong(a.output)) if ok else "ERR")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
