import os
import random

import cv2
import numpy as np
from PIL import Image, ImageDraw

import core

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "test_out")
os.makedirs(OUT, exist_ok=True)

random.seed(7)
np.random.seed(7)

W, H = 1200, 800

# 背景：渐变 + 随机形状 + 细线 + 噪声，模拟复杂一点的画面
y = np.linspace(0, 1, H)[:, None]
x = np.linspace(0, 1, W)[None, :]
bg = np.zeros((H, W, 3), np.float32)
bg[..., 0] = 60 + 80 * x + 30 * y
bg[..., 1] = 90 + 60 * y
bg[..., 2] = 120 + 70 * (1 - x)
img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8), "RGB")
d = ImageDraw.Draw(img)
for _ in range(30):
    x0, y0 = random.randint(0, W), random.randint(0, H)
    x1, y1 = x0 + random.randint(30, 260), y0 + random.randint(20, 180)
    color = tuple(random.randint(30, 220) for _ in range(3))
    d.rectangle([x0, y0, x1, y1], outline=color, width=random.randint(2, 6))
for _ in range(40):
    x0, y0 = random.randint(0, W), random.randint(0, H)
    x1, y1 = x0 + random.randint(-120, 120), y0 + random.randint(-120, 120)
    d.line([x0, y0, x1, y1], fill=tuple(random.randint(80, 255) for _ in range(3)), width=random.randint(1, 3))
arr = np.array(img).astype(np.int16) + np.random.normal(0, 4, (H, W, 3)).astype(np.int16)
bg_img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
bg_img.save(os.path.join(OUT, "background.png"))

TEXT = "仅供测试 12345"
wm = core.add_text_watermark(bg_img, TEXT, color="#FFFFFF", opacity=0.85, margin=28, stroke=2)
wm.save(os.path.join(OUT, "watermarked.png"))

# 用文字实际 bbox 生成精确 mask（模拟画笔涂抹）
overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
dr = ImageDraw.Draw(overlay)
font = core._font(max(18, int(W * 0.035)))
bbox = dr.textbbox((0, 0), TEXT, font=font, stroke_width=2)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
x = W - 28 - tw - bbox[0]
y = H - 28 - th - bbox[1]
# 精确 mask：只覆盖文字笔画
dr.text((x, y), TEXT, font=font, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(255, 255, 255, 255))
alpha = np.array(overlay.getchannel("A"))
precise_mask = (alpha > 40).astype(np.uint8) * 255
core.cv_imwrite(os.path.join(OUT, "mask_precise.png"), precise_mask)

# 矩形 mask（包围文字）
rx0, ry0 = max(0, x + bbox[0] - 10), max(0, y + bbox[1] - 10)
rx1, ry1 = min(W, x + bbox[2] + 10), min(H, y + bbox[3] + 10)
rect_mask = np.zeros((H, W), np.uint8)
cv2.rectangle(rect_mask, (rx0, ry0), (rx1, ry1), 255, -1)
core.cv_imwrite(os.path.join(OUT, "mask_rect.png"), rect_mask)

src = core.cv_imread(os.path.join(OUT, "watermarked.png"))
for name, mask in (("precise", precise_mask), ("rect", rect_mask)):
    for method in ("telea", "shiftmap"):
        out = core.inpaint(src, mask, method=method, radius=6)
        core.cv_imwrite(os.path.join(OUT, f"removed_{name}_{method}.jpg"), out, [cv2.IMWRITE_JPEG_QUALITY, 95])

# 第二张：不同背景、水印位置偏移，用模板匹配定位
bg2 = bg_img.rotate(0).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
bg2 = Image.fromarray(np.clip(np.array(bg2).astype(np.int16) + np.random.normal(0, 5, (H, W, 3)), 0, 255).astype(np.uint8))
wm2 = core.add_text_watermark(bg2, TEXT, color="#FFFFFF", opacity=0.85, margin=70, stroke=2)
wm2.save(os.path.join(OUT, "watermarked_shifted.png"))

tpl_bbox = core.mask_bbox(precise_mask)
x0, y0, x1, y1 = tpl_bbox
template = src[y0:y1, x0:x1].copy()
tmask = precise_mask[y0:y1, x0:x1].copy()
target = core.cv_imread(os.path.join(OUT, "watermarked_shifted.png"))
match = core.match_mask_template(target, template, tmask, scales=(1.0,), min_score=0.3)
print("match:", match)
if match:
    score, loc, scale = match
    m2 = core.place_mask(precise_mask, target.shape[:2], tpl_bbox, loc, scale)
    core.cv_imwrite(os.path.join(OUT, "match_mask.png"), m2)
    out2 = core.inpaint(target, m2, method="shiftmap", radius=6)
    core.cv_imwrite(os.path.join(OUT, "removed_shifted_shiftmap.jpg"), out2, [cv2.IMWRITE_JPEG_QUALITY, 95])
    out2b = core.inpaint(target, m2, method="telea", radius=6)
    core.cv_imwrite(os.path.join(OUT, "removed_shifted_telea.jpg"), out2b, [cv2.IMWRITE_JPEG_QUALITY, 95])

# 测试加水印
text_added = core.add_text_watermark(bg_img, "我的水印 2026", color="#FFE066", opacity=0.8, margin=24)
text_added.save(os.path.join(OUT, "added_text.png"))

logo = Image.new("RGBA", (300, 100), (0, 0, 0, 0))
ld = ImageDraw.Draw(logo)
ld.rounded_rectangle([2, 2, 297, 97], radius=18, fill=(255, 255, 255, 210))
ld.text((30, 18), "LOGO", font=core._font(46), fill=(20, 20, 20, 255))
logo.save(os.path.join(OUT, "logo.png"))
logo_added = core.add_logo_watermark(bg_img, os.path.join(OUT, "logo.png"), width_ratio=0.18, opacity=0.9)
logo_added.save(os.path.join(OUT, "added_logo.png"))

print("done", OUT)

