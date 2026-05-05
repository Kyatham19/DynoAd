from __future__ import annotations
from collections import deque

import math
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import List, Sequence, Tuple

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

Size = Tuple[int, int]


# ---------------------------------------------------------
# helpers
# ---------------------------------------------------------
def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def ease(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 3 * t * t - 2 * t * t * t


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    hex_color = hex_color.strip().lstrip("#")
    if len(hex_color) != 6:
        return (255, 255, 255, alpha)
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def fit_cover(img: Image.Image, size: Size) -> Image.Image:
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - tw) // 2
    y = (nh - th) // 2
    return resized.crop((x, y, x + tw, y + th))


def fit_contain(img: Image.Image, size: Size) -> Image.Image:
    tw, th = size
    scale = min(tw / img.width, th / img.height)
    nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    x = (tw - nw) // 2
    y = (th - nh) // 2
    canvas.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)
    return canvas


def make_radial_gradient(size: Size, inner: Tuple[int, int, int], outer: Tuple[int, int, int], center: Tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    cx = w * center[0]
    cy = h * center[1]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    dist = dist / max(w, h)
    dist = np.clip(dist * 1.8, 0, 1)
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for i, (a, b) in enumerate(zip(inner, outer)):
        arr[:, :, i] = (a + (b - a) * dist).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def add_shadow(base: Image.Image, offset=(10, 14), blur=16, color=(0, 0, 0, 110)) -> Image.Image:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    alpha = base.getchannel("A") if "A" in base.getbands() else Image.new("L", base.size, 255)
    shadow_mask = Image.new("RGBA", base.size, color)
    shadow.paste(shadow_mask, offset, alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    out.alpha_composite(shadow)
    out.alpha_composite(base)
    return out


def try_extract_subject(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    if img.getchannel("A").getbbox() not in (None, (0, 0, img.width, img.height)):
        return img

    arr = np.array(img)
    rgb = arr[:, :, :3].astype(np.int16)

    border = np.concatenate([
        rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]
    ], axis=0)
    bg = np.median(border, axis=0)
    dist = np.sqrt(np.sum((rgb - bg) ** 2, axis=2))
    bright = rgb.mean(axis=2)

    mask = (dist > 35) | (bright < 235)
    mask = Image.fromarray((mask * 255).astype(np.uint8), "L")
    mask = mask.filter(ImageFilter.GaussianBlur(2))

    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)

    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    return out


def make_collage(images: Sequence[Image.Image], size: Size) -> Image.Image:
    w, h = size
    canvas = Image.new("RGB", size, (240, 250, 252))
    layouts = [
        (0.00, 0.00, 0.34, 0.52),
        (0.34, 0.00, 0.32, 0.52),
        (0.66, 0.00, 0.34, 0.52),
        (0.00, 0.52, 0.25, 0.48),
        (0.25, 0.52, 0.25, 0.48),
        (0.50, 0.52, 0.25, 0.48),
        (0.75, 0.52, 0.25, 0.48),
    ]
    for i, slot in enumerate(layouts):
        img = images[i % len(images)].convert("RGB")
        x, y, ww, hh = slot
        box = (int(x * w), int(y * h), int((x + ww) * w), int((y + hh) * h))
        tile = fit_cover(img, (box[2] - box[0], box[3] - box[1]))
        canvas.paste(tile, (box[0], box[1]))
    return canvas


def text_masked_collage(text: str, collage: Image.Image, size: Size) -> Image.Image:
    w, h = size
    bg = Image.new("RGB", size, (248, 248, 248))
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)

    words = text.upper().split()
    font_big = find_font(int(h * 0.28), bold=True)
    y = int(h * 0.18)
    for word in words:
        tw, th = text_size(draw, word, font_big)
        x = (w - tw) // 2
        draw.text((x, y), word, font=font_big, fill=255)
        y += int(th * 0.9)

    collage_fit = fit_cover(collage, size)
    bg.paste(collage_fit, (0, 0), mask)
    return bg


def create_circle(size: Size, circle_center: Tuple[int, int], radius: int, fill: Tuple[int, int, int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    x, y = circle_center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    return canvas


def draw_center_text(img: Image.Image, lines: List[str], font_sizes: List[int], fills: List[Tuple[int, int, int]], center_y: int, shadow=False, angles=None) -> Image.Image:
    out = img.convert("RGBA")
    w, h = out.size
    temp = Image.new("RGBA", out.size, (0, 0, 0, 0))
    y = center_y
    if angles is None:
        angles = [0] * len(lines)

    for line, fs, fill, ang in zip(lines, font_sizes, fills, angles):
        font = find_font(fs, bold=True)
        d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        tw, th = text_size(d, line, font)
        txt = Image.new("RGBA", (tw + 80, th + 80), (0, 0, 0, 0))
        td = ImageDraw.Draw(txt)
        pos = (40, 40)
        if shadow:
            td.text((pos[0] + 8, pos[1] + 8), line, font=font, fill=(0, 0, 0, 90))
        td.text(pos, line, font=font, fill=fill + (255,))
        txt = txt.rotate(ang, expand=True, resample=Image.BICUBIC)
        x = (w - txt.width) // 2
        temp.alpha_composite(txt, (x, y))
        y += max(10, int(th * 0.9))
    out.alpha_composite(temp)
    return out.convert("RGB")


def draw_corner_slice(canvas: Image.Image, color=(155, 214, 38)) -> None:
    w, h = canvas.size
    slice_img = Image.new("RGBA", (280, 280), (0, 0, 0, 0))
    d = ImageDraw.Draw(slice_img)
    d.ellipse((10, 10, 270, 270), fill=(210, 250, 140, 255), outline=(255, 255, 255, 210), width=14)
    d.ellipse((50, 50, 230, 230), outline=(255, 255, 255, 180), width=6)
    for ang in range(0, 360, 45):
        rad = math.radians(ang)
        x2 = 140 + int(math.cos(rad) * 95)
        y2 = 140 + int(math.sin(rad) * 95)
        d.line((140, 140, x2, y2), fill=(255, 255, 255, 170), width=5)
    slice_img = slice_img.filter(ImageFilter.GaussianBlur(0.4))
    slice_img = slice_img.resize((250, 250), Image.LANCZOS)
    canvas.alpha_composite(slice_img, (-35, h - 215))
    canvas.alpha_composite(slice_img.rotate(30, expand=True), (w - 180, -55))


def write_frame(writer, img: Image.Image):
    writer.append_data(np.asarray(img.convert("RGB"), dtype=np.uint8))


def ffmpeg_concat_audio(video_path: str, audio_path: str) -> str:
    out = str(Path(video_path).with_name(Path(video_path).stem + "_with_music.mp4"))
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", audio_path,
        "-shortest",
        "-filter:a", "volume=0.18",
        "-c:v", "copy",
        "-c:a", "aac",
        out,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return out
    except Exception:
        return video_path


# ---------------------------------------------------------
# avatar helpers
# ---------------------------------------------------------
def _detect_nonwhite_bbox(img: Image.Image, white_threshold: int = 240) -> Tuple[int, int, int, int]:
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    nonwhite = np.any(arr < white_threshold, axis=2)
    ys, xs = np.where(nonwhite)

    if len(xs) == 0 or len(ys) == 0:
        return (0, 0, img.width, img.height)

    x1, x2 = xs.min(), xs.max()
    y1, y2 = ys.min(), ys.max()
    pad = 10
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(img.width, x2 + pad)
    y2 = min(img.height, y2 + pad)
    return (x1, y1, x2, y2)


def _remove_white_background(img: Image.Image, threshold: int = 242, feather: int = 10) -> Image.Image:
    """
    Better white background removal:
    - finds near-white pixels
    - removes only the near-white region connected to image borders
    - preserves bright parts inside the subject better than naive white removal
    """
    rgba_img = img.convert("RGBA")
    arr = np.asarray(rgba_img).copy()
    rgb = arr[:, :, :3].astype(np.uint8)

    h, w = rgb.shape[:2]

    # near-white test
    bright = rgb.mean(axis=2)
    maxc = rgb.max(axis=2)
    minc = rgb.min(axis=2)

    # background candidates: bright and low saturation
    bg_candidate = (bright >= threshold) & ((maxc - minc) <= 28)

    # flood fill only from borders so internal whites stay
    visited = np.zeros((h, w), dtype=bool)
    q = deque()

    for x in range(w):
        if bg_candidate[0, x]:
            q.append((x, 0))
            visited[0, x] = True
        if bg_candidate[h - 1, x] and not visited[h - 1, x]:
            q.append((x, h - 1))
            visited[h - 1, x] = True

    for y in range(h):
        if bg_candidate[y, 0] and not visited[y, 0]:
            q.append((0, y))
            visited[y, 0] = True
        if bg_candidate[y, w - 1] and not visited[y, w - 1]:
            q.append((w - 1, y))
            visited[y, w - 1] = True

    directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    while q:
        x, y = q.popleft()
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and bg_candidate[ny, nx]:
                visited[ny, nx] = True
                q.append((nx, ny))

    # visited == removable white background connected to edges
    alpha = np.where(visited, 0, 255).astype(np.uint8)

    alpha_img = Image.fromarray(alpha, "L")

    # soften edges
    if feather > 0:
        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(feather))

    arr[:, :, 3] = np.asarray(alpha_img)

    out = Image.fromarray(arr, "RGBA")

    # trim again after transparency
    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)

    return out

class AvatarOverlay:
    def __init__(
        self,
        avatar_path: str,
        canvas_size: Size,
        total_duration: float,
        enabled: bool = True,
        mode: str = "full",          # intro | outro | full
        side: str = "right",         # left | right
        width_ratio: float = 0.50,   # exactly half video
        bottom_margin: int = 0,
        remove_bg: bool = True,
        white_threshold: int = 238,
        feather: int = 8,
        intro_duration: float = 2.5,
        outro_duration: float = 2.5,
    ) -> None:
        self.enabled = enabled and bool(avatar_path) and Path(avatar_path).exists()
        self.avatar_path = avatar_path
        self.canvas_size = canvas_size
        self.total_duration = total_duration
        self.mode = mode.lower().strip()
        self.side = side.lower().strip()
        self.width_ratio = clamp(width_ratio, 0.10, 0.90)
        self.bottom_margin = max(0, int(bottom_margin))
        self.remove_bg = remove_bg
        self.white_threshold = white_threshold
        self.feather = feather
        self.intro_duration = max(0.1, intro_duration)
        self.outro_duration = max(0.1, outro_duration)

        self.reader = None
        self.avatar_fps = 25.0
        self.avatar_duration = 1.0
        self.crop_box = None

        if self.enabled:
            try:
                self.reader = imageio.get_reader(self.avatar_path)
                meta = self.reader.get_meta_data()
                self.avatar_fps = float(meta.get("fps", 25.0) or 25.0)

                duration = meta.get("duration", None)
                if duration is not None:
                    self.avatar_duration = max(0.1, float(duration))
                else:
                    try:
                        nframes = self.reader.count_frames()
                        self.avatar_duration = max(0.1, nframes / self.avatar_fps)
                    except Exception:
                        self.avatar_duration = 3.0

                first = Image.fromarray(self.reader.get_data(0)).convert("RGBA")
                self.crop_box = _detect_nonwhite_bbox(first, white_threshold=self.white_threshold)
            except Exception as e:
                print("[avatar] failed to load avatar:", e)
                self.enabled = False

    def active_at(self, t: float) -> bool:
        if not self.enabled:
            return False
        if self.mode == "full":
            return True
        if self.mode == "intro":
            return t <= self.intro_duration
        if self.mode == "outro":
            return t >= max(0.0, self.total_duration - self.outro_duration)
        return True

    def source_time(self, t: float) -> float:
        if self.mode == "outro":
            local_t = max(0.0, t - (self.total_duration - self.outro_duration))
        else:
            local_t = t
        if self.avatar_duration <= 0:
            return 0.0
        return local_t % self.avatar_duration

@lru_cache(maxsize=256)
def prepared_frame(self, frame_index: int) -> Image.Image:
    arr = self.reader.get_data(frame_index)
    img = Image.fromarray(arr).convert("RGBA")

    if self.crop_box is not None:
        img = img.crop(self.crop_box)

    if self.remove_bg:
        img = _remove_white_background(
            img,
            threshold=self.white_threshold,
            feather=self.feather
        )

    # extra trim after background removal
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    W, H = self.canvas_size
    target_w = int(W * self.width_ratio)

    scale = target_w / max(1, img.width)
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # keep full height inside frame
    max_h = H
    if img.height > max_h:
        scale2 = max_h / max(1, img.height)
        img = img.resize(
            (max(1, int(img.width * scale2)), max_h),
            Image.LANCZOS
        )

    return img

    def overlay(self, frame: Image.Image, t: float) -> Image.Image:
        if not self.active_at(t):
            return frame

        src_t = self.source_time(t)
        frame_index = int(src_t * self.avatar_fps)

        try:
            avatar = self.prepared_frame(frame_index)
        except Exception:
            try:
                avatar = self.prepared_frame(0)
            except Exception:
                return frame

        out = frame.convert("RGBA")
        W, H = out.size

        x = 0 if self.side == "left" else (W - avatar.width)
        y = H - avatar.height - self.bottom_margin
        y = max(0, y)

        out.alpha_composite(avatar, (x, y))
        return out.convert("RGB")


# ---------------------------------------------------------
# scene builders
# ---------------------------------------------------------
def scene_intro_masked(images: Sequence[Image.Image], size: Size, title: str, progress: float) -> Image.Image:
    collage = make_collage(images, size)
    frame = text_masked_collage(title, collage, size).convert("RGBA")
    scale = lerp(1.08, 1.0, ease(progress))
    zoomed = fit_cover(frame, (int(size[0] * scale), int(size[1] * scale)))
    zoomed = zoomed.resize(size, Image.LANCZOS)
    return zoomed.convert("RGB")


def scene_circle_title(size: Size, title: str, subtitle: str, progress: float) -> Image.Image:
    base = Image.new("RGBA", size, (247, 247, 247, 255))
    w, h = size
    cx = int(w * 0.50)
    cy = int(h * 0.48)
    radius = int(lerp(h * 0.18, h * 0.42, ease(progress)))
    circle = create_circle(size, (cx, cy), radius, (149, 236, 29, 255))
    circle = circle.filter(ImageFilter.GaussianBlur(2))
    base.alpha_composite(circle)
    lines = [title.upper()]
    fsz = [int(h * 0.16)]
    fills = [(255, 255, 255)]
    frame = draw_center_text(base.convert("RGB"), lines, fsz, fills, center_y=int(h * 0.32), shadow=False, angles=[-8])
    if subtitle.strip():
        frame = draw_center_text(frame, [subtitle.upper()], [int(h * 0.09)], [(255, 255, 255)], center_y=int(h * 0.46), shadow=False, angles=[-8])
    return frame


def scene_product_hero(size: Size, subject: Image.Image, title: str, progress: float) -> Image.Image:
    w, h = size
    bg = make_radial_gradient(size, (175, 250, 65), (85, 148, 10), center=(0.5, 0.43)).convert("RGBA")
    halo = create_circle(size, (w // 2, int(h * 0.5)), int(h * 0.26), (198, 255, 120, 120)).filter(ImageFilter.GaussianBlur(18))
    bg.alpha_composite(halo)

    word = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(word)
    font = find_font(int(h * 0.15), bold=True)
    tw, th = text_size(d, title.upper(), font)
    d.text(((w - tw) // 2, int(h * 0.15)), title.upper(), font=font, fill=(255, 255, 255, 245))
    bg.alpha_composite(word)

    subject = try_extract_subject(subject)
    scale_base = min((w * 0.40) / max(1, subject.width), (h * 0.48) / max(1, subject.height))
    scale = scale_base * lerp(0.9, 1.0, ease(progress))
    product = subject.resize((max(1, int(subject.width * scale)), max(1, int(subject.height * scale))), Image.LANCZOS)
    product = add_shadow(product, offset=(14, 18), blur=24, color=(0, 0, 0, 105))
    bg.alpha_composite(product, ((w - product.width) // 2, int(h * 0.32)))
    return bg.convert("RGB")


def scene_burst_text(size: Size, title: str, subtitle: str, progress: float) -> Image.Image:
    base = Image.new("RGBA", size, (246, 246, 246, 255))
    draw_corner_slice(base)
    y_shift = int(lerp(45, 0, ease(progress)))
    frame = draw_center_text(base.convert("RGB"), [title.upper()], [int(size[1] * 0.14)], [(112, 205, 12)], center_y=int(size[1] * 0.34) + y_shift, shadow=False)
    frame = draw_center_text(frame, [subtitle.upper()], [int(size[1] * 0.10)], [(112, 205, 12)], center_y=int(size[1] * 0.46) + y_shift, shadow=False)
    return frame


def scene_final_packshot(size: Size, subject: Image.Image, title: str, subtitle: str, cta: str, logo: Image.Image | None, progress: float) -> Image.Image:
    w, h = size
    base = Image.new("RGBA", size, (248, 248, 248, 255))
    draw_corner_slice(base)

    back = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(back)
    big_font = find_font(int(h * 0.18), bold=True)
    d.text((int(w * 0.07), int(h * 0.12)), title.upper(), font=big_font, fill=(120, 208, 18, 255))
    d.text((int(w * 0.39), int(h * 0.30)), subtitle.upper(), font=find_font(int(h * 0.10), bold=True), fill=(120, 208, 18, 255))
    base.alpha_composite(back)

    subject = try_extract_subject(subject)
    scale_base = min((w * 0.35) / max(1, subject.width), (h * 0.44) / max(1, subject.height))
    scale = scale_base * lerp(0.86, 1.0, ease(progress))
    product = subject.resize((max(1, int(subject.width * scale)), max(1, int(subject.height * scale))), Image.LANCZOS)
    product = add_shadow(product, offset=(12, 16), blur=22, color=(0, 0, 0, 110))
    base.alpha_composite(product, (int(w * 0.32), int(h * 0.35)))

    if cta:
        btn = Image.new("RGBA", (int(w * 0.22), int(h * 0.07)), (120, 208, 18, 255))
        bd = ImageDraw.Draw(btn)
        bd.rounded_rectangle((0, 0, btn.width - 1, btn.height - 1), radius=btn.height // 2, fill=(120, 208, 18, 255))
        font = find_font(int(h * 0.038), bold=True)
        tw, th = text_size(bd, cta.upper(), font)
        bd.text(((btn.width - tw) // 2, (btn.height - th) // 2 - 2), cta.upper(), font=font, fill=(255, 255, 255, 255))
        base.alpha_composite(btn, (int(w * 0.68), int(h * 0.82)))

    if logo is not None:
        logo_rgba = logo.convert("RGBA")
        max_w = int(w * 0.17)
        scale_logo = min(max_w / max(1, logo_rgba.width), (h * 0.08) / max(1, logo_rgba.height))
        logo_rgba = logo_rgba.resize((max(1, int(logo_rgba.width * scale_logo)), max(1, int(logo_rgba.height * scale_logo))), Image.LANCZOS)
        base.alpha_composite(logo_rgba, (int(w * 0.06), int(h * 0.06)))
    return base.convert("RGB")


# ---------------------------------------------------------
# public API
# ---------------------------------------------------------
def generate_canva_style_ad(
    image_paths: Sequence[str],
    output_path: str = "output/canva_style_ad.mp4",
    size: Size = (1206, 682),
    fps: int = 30,
    title: str = "FRESH",
    subtitle: str = "SQUEEZE",
    burst_title: str = "CITRUS",
    burst_subtitle: str = "BURST",
    cta: str = "BUY NOW",
    logo_path: str | None = None,
    music_path: str | None = None,

    # avatar options
    avatar_enabled: bool = False,
    avatar_path: str = "assets/avatars/real_male.mp4",
    avatar_mode: str = "full",         # intro | outro | full
    avatar_side: str = "right",        # left | right
    avatar_width_ratio: float = 0.50,  # half screen
    avatar_remove_bg: bool = True,
    avatar_white_threshold: int = 238,
    avatar_feather: int = 8,
    avatar_intro_duration: float = 2.5,
    avatar_outro_duration: float = 2.5,
    avatar_bottom_margin: int = 0,
) -> str:
    paths = [str(p) for p in image_paths if str(p).strip()]
    if not paths:
        raise ValueError("Please provide at least one image.")

    images: List[Image.Image] = []
    for p in paths:
        if not Path(p).exists():
            raise FileNotFoundError(p)
        images.append(Image.open(p).convert("RGBA"))

    logo = Image.open(logo_path).convert("RGBA") if logo_path and Path(logo_path).exists() else None
    hero = images[0]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(output_path, fps=fps, codec="libx264", quality=8, macro_block_size=None)

    scene_plan = [
        (1.5, lambda p: scene_intro_masked(images, size, f"{title} {subtitle}", p)),
        (1.2, lambda p: scene_circle_title(size, title, "", p)),
        (1.2, lambda p: scene_circle_title(size, title, subtitle, p)),
        (2.0, lambda p: scene_product_hero(size, hero, f"{title} {subtitle}", p)),
        (1.4, lambda p: scene_burst_text(size, burst_title, burst_subtitle, p)),
        (2.7, lambda p: scene_final_packshot(size, hero, burst_title, burst_subtitle, cta, logo, p)),
    ]

    total_duration = sum(d for d, _ in scene_plan)

    avatar = AvatarOverlay(
        avatar_path=avatar_path,
        canvas_size=size,
        total_duration=total_duration,
        enabled=avatar_enabled,
        mode=avatar_mode,
        side=avatar_side,
        width_ratio=avatar_width_ratio,
        bottom_margin=avatar_bottom_margin,
        remove_bg=avatar_remove_bg,
        white_threshold=avatar_white_threshold,
        feather=avatar_feather,
        intro_duration=avatar_intro_duration,
        outro_duration=avatar_outro_duration,
    )

    elapsed = 0.0
    for duration, renderer in scene_plan:
        frames = max(1, int(duration * fps))
        for i in range(frames):
            prog = i / max(1, frames - 1)
            t = elapsed + (i / fps)

            frame = renderer(prog)
            if avatar.enabled:
                frame = avatar.overlay(frame, t)

            write_frame(writer, frame)
        elapsed += duration

    writer.close()

    if music_path and Path(music_path).exists():
        return ffmpeg_concat_audio(output_path, music_path)
    return output_path


if __name__ == "__main__":
    sample_dir = Path(__file__).parent / "sample_images"
    demo_paths = sorted(str(p) for p in sample_dir.glob("*.png"))
    out = generate_canva_style_ad(
        image_paths=demo_paths,
        output_path=str(Path(__file__).parent / "output" / "demo_ad.mp4"),
        title="FRESH",
        subtitle="SQUEEZE",
        burst_title="CITRUS",
        burst_subtitle="BURST",
        cta="ORDER NOW",
        avatar_enabled=True,
        avatar_path="assets/avatars/real_male.mp4",
        avatar_mode="full",
        avatar_side="right",
        avatar_width_ratio=0.50,
        avatar_remove_bg=True,
    )
    print(out)