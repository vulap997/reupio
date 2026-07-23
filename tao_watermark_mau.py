# -*- coding: utf-8 -*-
"""Tạo watermark.png mẫu (logo chữ REUP nền mờ bo góc) để test pipeline."""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 140, 60
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, W - 1, H - 1], radius=12, fill=(255, 45, 85, 180))
try:
    font = ImageFont.truetype("arialbd.ttf", 28)
except Exception:
    font = ImageFont.load_default()
text = "REUP"
try:
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
except Exception:
    tw, th = 60, 20
d.text(((W - tw) / 2, (H - th) / 2 - 4), text, fill=(255, 255, 255, 255), font=font)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watermark.png")
img.save(out)
print("Saved:", out)
