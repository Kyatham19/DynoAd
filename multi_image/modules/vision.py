from __future__ import annotations

from typing import Tuple

import numpy as np
from PIL import Image, ImageFilter, ImageOps

Box = Tuple[int, int, int, int]


def _clamp_box(box: Box, w: int, h: int) -> Box:
    x1, y1, x2, y2 = box
    x1 = max(0, min(x1, w - 1))
    y1 = max(0, min(y1, h - 1))
    x2 = max(x1 + 1, min(x2, w))
    y2 = max(y1 + 1, min(y2, h))
    return x1, y1, x2, y2


def _expand_box(box: Box, w: int, h: int, pad_ratio: float = 0.08) -> Box:
    x1, y1, x2, y2 = box
    bw = x2 - x1
    bh = y2 - y1
    px = int(bw * pad_ratio)
    py = int(bh * pad_ratio)
    return _clamp_box((x1 - px, y1 - py, x2 + px, y2 + py), w, h)


def detect_primary_object_box(img: Image.Image) -> Box:
    rgb = img.convert("RGB")
    gray = ImageOps.grayscale(rgb).filter(ImageFilter.GaussianBlur(1.2))
    arr = np.asarray(gray).astype(np.float32)

    border = np.concatenate([
        arr[:10, :].ravel(),
        arr[-10:, :].ravel(),
        arr[:, :10].ravel(),
        arr[:, -10:].ravel(),
    ])

    bg = float(np.median(border))
    diff = np.abs(arr - bg)
    threshold = max(18.0, float(np.percentile(diff, 82)))

    ys, xs = np.where(diff > threshold)
    h, w = arr.shape

    if len(xs) < 50 or len(ys) < 50:
        return int(w * 0.15), int(h * 0.12), int(w * 0.85), int(h * 0.88)

    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())
    return _expand_box((x1, y1, x2, y2), w, h, pad_ratio=0.10)