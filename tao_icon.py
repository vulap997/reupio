# -*- coding: utf-8 -*-
"""Tạo icon.ico cho shortcut: nền hồng bo góc + nút play trắng."""
import os
from PIL import Image, ImageDraw

img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([8, 8, 248, 248], radius=52, fill=(255, 45, 85, 255))
d.polygon([(102, 78), (102, 178), (188, 128)], fill=(255, 255, 255, 255))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
img.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("Saved:", out)
