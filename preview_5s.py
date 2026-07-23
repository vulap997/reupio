# -*- coding: utf-8 -*-
"""Preview NHANH ~5s: cắt 5s đoạn giữa + áp hiệu ứng HÌNH (blur che chữ Trung + phụ đề PLACEHOLDER
"phụ đề sẽ ở đây" + logo + watermark chữ + đổi khung + lật/màu). KHÔNG ASR/dịch/TTS → nhanh,
cho user xem BỐ CỤC trước khi render full (render full mới có sub/giọng thật).
Dùng:  python preview_5s.py <video> <opts.json> <out.mp4>
"""
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import xu_ly_video as xlv
import localize
import dai_sub


def main():
    video, opts_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
    o = json.load(open(opts_path, encoding="utf-8"))
    cfg = xlv.tu_tim_ffmpeg(xlv.nap_config())
    ff = cfg["ffmpeg_path"]
    tdir = os.path.dirname(os.path.abspath(out))

    # 1) Cắt 5s ĐOẠN GIỮA (thường có thoại/sub), re-encode ultrafast cho burnable
    dur = xlv.lay_thoi_luong(cfg, video) or 0
    ss = max(0.0, dur / 2.0 - 2.5) if dur > 6 else 0.0
    clip = os.path.join(tdir, "_pv_clip.mp4")
    subprocess.run([ff, "-y", "-ss", "%.2f" % ss, "-t", "5", "-i", video,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", clip],
                   capture_output=True)
    if not os.path.isfile(clip):
        print("PREVIEW_LOI cat clip"); sys.exit(1)

    # 2) Dải che chữ Trung (tự dò — KHÔNG cần ASR)
    bb = None
    if o.get("che_chu"):
        r = dai_sub.detect_blur_band(clip, srt=None, log_fn=lambda *a, **k: None)
        if isinstance(r, dict) and r.get("source") != "none":
            bb = (r["y0"], r["y1"], r["H"])

    # 3) Phụ đề PLACEHOLDER (chỗ phụ đề thật sẽ nằm)
    srt = os.path.join(tdir, "_pv.vi.srt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,300 --> 00:00:05,000\nphụ đề sẽ ở đây\n")

    # 4) burn_phude: blur dải che + burn placeholder + lật (hình)
    vf = ["hflip"] if o.get("mirror") else []
    burned = os.path.join(tdir, "_pv_burn.mp4")
    ok = localize.burn_phude(clip, srt, burned, che_chu=bool(o.get("che_chu")),
                             log_fn=lambda *a, **k: None, blur_band=bb, extra_vf=vf)
    src2 = burned if (ok and os.path.isfile(burned)) else clip

    # 5) bien_doi_khung: logo + watermark CHỮ + đổi khung (1 pass cuối)
    logo, text_wm, ratio = o.get("logo"), o.get("text_wm"), (o.get("ratio") or "")
    if logo or (text_wm and text_wm.get("text")) or ratio:
        r2 = xlv.bien_doi_khung(cfg, src2, out, ratio=ratio, logo=logo, text_wm=text_wm)
        ok2 = (r2[0] if isinstance(r2, tuple) else r2)
        if not (ok2 and os.path.isfile(out)):
            if os.path.abspath(src2) != os.path.abspath(out):
                os.replace(src2, out)
    else:
        if os.path.abspath(src2) != os.path.abspath(out):
            os.replace(src2, out)

    for tmp in (clip, srt, burned):
        try:
            if os.path.isfile(tmp) and os.path.abspath(tmp) != os.path.abspath(out):
                os.remove(tmp)
        except OSError:
            pass
    print("PREVIEW_DONE", os.path.basename(out))


if __name__ == "__main__":
    main()
