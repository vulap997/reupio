# -*- coding: utf-8 -*-
"""
Đè chữ đã dịch LÊN chữ gốc trong ảnh chụp (nền trắng khớp ảnh), giữ nguyên icon.
Dùng bbox vùng chữ (do chup_bai.py lưu trong noi_dung.json).

API: overlay_text(img_path, bbox, new_text, out_path)
"""
import os

from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
MAU_CHU = (26, 26, 27)      # #1a1a1b ~ màu chữ Reddit/Threads
MAU_NEN = (255, 255, 255)   # nền trắng


def _font(size):
    for name in ("verdana.ttf", "arial.ttf", "segoeui.ttf"):
        p = os.path.join(_FONT_DIR, name)
        if os.path.isfile(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    """Ngắt dòng theo từ cho vừa bề rộng max_w (giữ xuống dòng có sẵn)."""
    lines = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            t = (cur + " " + w).strip()
            if not cur or draw.textlength(t, font=font) <= max_w:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def overlay_text(img_path, bbox, new_text, out_path,
                 mau_chu=MAU_CHU, max_size=30, min_size=12):
    """Xoá trắng vùng bbox rồi vẽ new_text (tự co cho vừa). bbox=[x,y,w,h] (px ảnh)."""
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    x, y, w, h = bbox

    # Lấy màu nền khớp ảnh (mẫu ngay phía trên vùng chữ); mặc định trắng
    nen = MAU_NEN
    try:
        px = img.getpixel((min(img.width - 1, x + 1), max(0, y - 3)))
        if isinstance(px, tuple) and sum(px[:3]) > 720:   # đủ sáng -> coi là nền
            nen = px[:3]
    except Exception:
        pass
    draw.rectangle([x - 4, y - 4, x + w + 4, y + h + 4], fill=nen)

    # Tự co cỡ chữ cho khít chiều cao vùng (để không đè lên icon dưới)
    size = max_size
    while size >= min_size:
        font = _font(size)
        lines = _wrap(draw, new_text, font, w)
        lh = int(size * 1.4)
        if lh * len(lines) <= h or size == min_size:
            break
        size -= 1

    cy = y
    for ln in lines:
        draw.text((x, cy), ln, fill=mau_chu, font=font)
        cy += lh
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--bbox", required=True, help="x,y,w,h")
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    bb = [int(v) for v in a.bbox.split(",")]
    overlay_text(a.img, bb, a.text, a.out)
    print("saved", a.out)
