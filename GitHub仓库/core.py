from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Sequence

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def cv_imread(path: str, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def cv_imwrite(path: str, img: np.ndarray, params: list[int] | None = None) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jpg":
        ext = ".jpg"
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        return False
    buf.tofile(path)
    return True


# ---------------------------------------------------------------- image io

def pil_open(path: str) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img


def pil_to_bgr(img: Image.Image) -> np.ndarray:
    if img.mode == "RGBA":
        rgb = np.array(img.convert("RGB"))
    else:
        rgb = np.array(img.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def bgr_to_pil(img: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def save_image(img: Image.Image, path: str, quality: int = 95, exif: bytes | None = None,
               icc: bytes | None = None) -> None:
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    kwargs = {}
    if exif:
        kwargs["exif"] = exif
    if icc:
        kwargs["icc_profile"] = icc
    if ext in (".jpg", ".jpeg"):
        img.convert("RGB").save(path, "JPEG", quality=quality, subsampling=0, **kwargs)
    elif ext == ".png":
        img.save(path, "PNG", optimize=True, **kwargs)
    elif ext == ".webp":
        img.save(path, "WEBP", quality=quality, **kwargs)
    else:
        img.save(path, **kwargs)


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    for i in range(1, 10000):
        p = f"{stem}_{i}{ext}"
        if not os.path.exists(p):
            return p
    return f"{stem}_{os.getpid()}{ext}"


# ---------------------------------------------------------------- masks

@dataclass
class Stroke:
    points: list[tuple[int, int]]
    radius: int
    erase: bool = False


def build_mask(shape: tuple[int, int], rects: Iterable[Sequence[int]], strokes: Iterable[Stroke]) -> np.ndarray:
    h, w = shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for rect in rects:
        x1, y1, x2, y2 = [int(v) for v in rect]
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
    for stroke in strokes:
        color = 0 if stroke.erase else 255
        pts = [(int(x), int(y)) for x, y in stroke.points]
        if len(pts) == 1:
            cv2.circle(mask, pts[0], max(1, stroke.radius), color, -1)
        else:
            for a, b in zip(pts, pts[1:]):
                cv2.line(mask, a, b, color, max(1, stroke.radius * 2), cv2.LINE_AA)
    return mask


def mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def resize_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    if mask.shape[1] == w and mask.shape[0] == h:
        return mask
    return cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)


# ---------------------------------------------------------------- inpaint

def inpaint(img_bgr: np.ndarray, mask: np.ndarray, method: str = "telea", radius: int = 5,
            grow: int = 2) -> np.ndarray:
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    if mask.max() == 0:
        return img_bgr.copy()
    if grow > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow * 2 + 1, grow * 2 + 1))
        mask = cv2.dilate(mask, k, iterations=1)

    bbox = mask_bbox(mask)
    if bbox is None:
        return img_bgr.copy()
    x0, y0, x1, y1 = bbox
    margin = max(24, radius * 4, grow * 4)
    x0, y0 = max(0, x0 - margin), max(0, y0 - margin)
    x1, y1 = min(img_bgr.shape[1], x1 + margin), min(img_bgr.shape[0], y1 + margin)
    work = img_bgr[y0:y1, x0:x1].copy()
    wm = mask[y0:y1, x0:x1]

    if method == "shiftmap":
        out = np.zeros_like(work)
        try:
            # xphoto 的 mask 语义与 cv2.inpaint 相反：非零=有效区域，零=待修复
            inv = cv2.bitwise_not(wm)
            cv2.xphoto.inpaint(work, inv, out, cv2.xphoto.INPAINT_SHIFTMAP)
        except Exception:
            out = cv2.inpaint(work, wm, radius, cv2.INPAINT_TELEA)
    elif method == "ns":
        out = cv2.inpaint(work, wm, radius, cv2.INPAINT_NS)
    else:
        out = cv2.inpaint(work, wm, radius, cv2.INPAINT_TELEA)

    # 轻微羽化边界，减少接缝；mask 内部保持 1
    if radius > 0:
        k = max(3, radius * 2 + 1)
        soft = cv2.GaussianBlur(wm, (k, k), 0).astype(np.float32) / 255.0
        hard = (wm > 0).astype(np.float32)
        alpha = np.maximum(soft, hard * 0.92)[..., None]
        out = (out.astype(np.float32) * alpha + work.astype(np.float32) * (1 - alpha)).astype(np.uint8)

    result = img_bgr.copy()
    result[y0:y1, x0:x1] = out
    return result


# ---------------------------------------------------------------- add watermark

def _font(size: int) -> ImageFont.FreeTypeFont:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        os.path.join(windir, "Fonts", "msyh.ttc"),
        os.path.join(windir, "Fonts", "msyhbd.ttc"),
        os.path.join(windir, "Fonts", "simhei.ttf"),
        os.path.join(windir, "Fonts", "arial.ttf"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _rgba(color: str, opacity: float) -> tuple[int, int, int, int]:
    r, g, b = ImageColor.getrgb(color)
    return r, g, b, max(0, min(255, int(255 * opacity)))


def add_text_watermark(img: Image.Image, text: str, font_size: int = 0, color: str = "#FFFFFF",
                       opacity: float = 0.78, margin: int = 24, stroke: int = 2,
                       position: str = "右下角") -> Image.Image:
    if not text.strip():
        return img.copy()
    base = img.convert("RGBA")
    w, h = base.size
    size = font_size if font_size and font_size > 0 else max(18, int(w * 0.035))
    font = _font(size)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    if position == "左下角":
        x = margin - bbox[0]
        y = h - margin - th - bbox[1]
    elif position == "右上角":
        x = w - margin - tw - bbox[0]
        y = margin - bbox[1]
    elif position == "左上角":
        x = margin - bbox[0]
        y = margin - bbox[1]
    else:
        x = w - margin - tw - bbox[0]
        y = h - margin - th - bbox[1]
    fill = _rgba(color, opacity)
    stroke_fill = (0, 0, 0, max(0, min(255, int(255 * opacity * 0.75))))
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    return Image.alpha_composite(base, overlay)


def add_logo_watermark(img: Image.Image, logo_path: str, width_ratio: float = 0.15,
                       opacity: float = 0.85, margin: int = 24,
                       position: str = "右下角") -> Image.Image:
    base = img.convert("RGBA")
    logo = Image.open(logo_path).convert("RGBA")
    target_w = max(16, int(base.width * width_ratio))
    target_h = max(1, int(logo.height * target_w / max(1, logo.width)))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)
    if opacity < 1:
        alpha = logo.getchannel("A").point(lambda a: int(a * opacity))
        logo.putalpha(alpha)
    if position == "左下角":
        x, y = margin, base.height - margin - target_h
    elif position == "右上角":
        x, y = base.width - margin - target_w, margin
    elif position == "左上角":
        x, y = margin, margin
    else:
        x, y = base.width - margin - target_w, base.height - margin - target_h
    base.alpha_composite(logo, (x, y))
    return base


# ---------------------------------------------------------------- template match

def match_mask_template(image_bgr: np.ndarray, template_bgr: np.ndarray, template_mask: np.ndarray,
                        scales: Sequence[float] = (1.0,), min_score: float = 0.55):
    """用带 mask 的模板匹配找水印位置，返回 (score, (x, y), scale) 或 None。"""
    if template_mask.max() == 0:
        return None
    best_score = -1.0
    best_loc = None
    best_scale = 1.0
    ih, iw = image_bgr.shape[:2]
    for scale in scales:
        if scale == 1.0:
            t, m = template_bgr, template_mask
        else:
            t = cv2.resize(template_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            m = cv2.resize(template_mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        if t.shape[0] > ih or t.shape[1] > iw or t.shape[0] < 4 or t.shape[1] < 4:
            continue
        try:
            res = cv2.matchTemplate(image_bgr, t, cv2.TM_CCORR_NORMED, mask=m)
        except cv2.error:
            continue
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = float(max_val)
            best_loc = max_loc
            best_scale = scale
    if best_loc is None or best_score < min_score:
        return None
    return best_score, best_loc, best_scale


def place_mask(sample_mask: np.ndarray, target_shape: tuple[int, int], bbox: tuple[int, int, int, int],
               loc: tuple[int, int], scale: float = 1.0) -> np.ndarray:
    """把样图 mask 按模板匹配位置贴到目标图。"""
    h, w = target_shape[:2]
    out = np.zeros((h, w), dtype=np.uint8)
    x0, y0, x1, y1 = bbox
    if scale != 1.0:
        m = cv2.resize(sample_mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    else:
        m = sample_mask
    ox = int(round(loc[0] - x0 * scale))
    oy = int(round(loc[1] - y0 * scale))
    mh, mw = m.shape[:2]
    dx0, dy0 = max(0, ox), max(0, oy)
    dx1, dy1 = min(w, ox + mw), min(h, oy + mh)
    if dx1 <= dx0 or dy1 <= dy0:
        return out
    sx0, sy0 = dx0 - ox, dy0 - oy
    out[dy0:dy1, dx0:dx1] = m[sy0:sy0 + (dy1 - dy0), sx0:sx0 + (dx1 - dx0)]
    return out
