from __future__ import annotations

import math
import os
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

try:
    from modules.vision import detect_primary_object_box
except Exception:
    def detect_primary_object_box(img: Image.Image):
        w, h = img.size
        return (int(w * 0.12), int(h * 0.10), int(w * 0.88), int(h * 0.90))

try:
    from modules.copy_generation import generate_scene_copies as _external_generate_scene_copies
except Exception:
    _external_generate_scene_copies = None


Color = Tuple[int, int, int]

ALL_STYLES = [
    "Cinematic Hero Reveal",
    "Color Splash Burst",
    "Floating Studio Shot",
    "Product-in-Environment",
    "Luxury Dark Editorial",
    "Tech Spec Reveal",
    "Reflective Premium Floor",
    "Urban Street Hype",
    "Hyperreal Macro Reveal",
    "Brand Launch Trailer",
]


@dataclass
class RenderSpec:
    size: Tuple[int, int] = (720, 1280)
    fps: int = 12
    total_duration: int = 12
    brand: str = "Dyno"
    headline: str = "NEW ARRIVAL"
    tagline: str = "Premium design. Smart styling."
    cta: str = "SHOP NOW"

    style: str = "Auto"

    music_path: Optional[str] = None
    music_volume: float = 0.20
    music_fade_in: float = 0.5
    music_fade_out: float = 0.8

    voice_path: Optional[str] = None
    voice_volume: float = 1.0

    auto_style: bool = True
    style_seed: int = 7


# -------------------------------------------------
# helpers
# -------------------------------------------------
def _safe_font(size: int, bold: bool = False):
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _fonts(w: int):
    return {
        "brand": _safe_font(max(14, w // 38), True),
        "title": _safe_font(max(18, w // 24), True),
        "body": _safe_font(max(12, w // 46), False),
        "cta": _safe_font(max(13, w // 42), True),
        "huge": _safe_font(max(24, w // 20), True),
        "mid": _safe_font(max(16, w // 30), True),
        "small": _safe_font(max(11, w // 50), False),
    }


def _palette_from_image(img: Image.Image) -> tuple[Color, Color]:
    arr = np.asarray(img.convert("RGB").resize((48, 48), Image.LANCZOS))
    mean = arr.reshape(-1, 3).mean(axis=0)
    base = tuple(int(x) for x in mean)
    dark = tuple(max(8, int(c * 0.22)) for c in base)
    light = tuple(min(245, int(c * 1.18 + 10)) for c in base)
    return dark, light


def _image_stats(img: Image.Image) -> dict:
    arr = np.asarray(img.convert("RGB").resize((128, 128), Image.LANCZOS)).astype(np.float32)
    brightness = float(arr.mean())
    contrast = float(arr.std())
    saturation = float((arr.max(axis=2) - arr.min(axis=2)).mean())
    edges_x = np.abs(np.diff(arr.mean(axis=2), axis=1)).mean()
    edges_y = np.abs(np.diff(arr.mean(axis=2), axis=0)).mean()
    edge_energy = float(edges_x + edges_y)
    w, h = img.size
    aspect = w / max(1, h)
    return {
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "edge_energy": edge_energy,
        "aspect": aspect,
    }


def _choose_style_for_image(img: Image.Image, idx: int, seed: int = 7) -> str:
    stats = _image_stats(img)
    candidates: list[str] = []

    if stats["contrast"] < 34 and stats["brightness"] < 120:
        candidates.extend(["Luxury Dark Editorial", "Reflective Premium Floor"])
    if stats["saturation"] > 68:
        candidates.extend(["Color Splash Burst", "Urban Street Hype"])
    if stats["edge_energy"] > 24:
        candidates.extend(["Hyperreal Macro Reveal", "Cinematic Hero Reveal"])
    if stats["brightness"] > 165:
        candidates.extend(["Floating Studio Shot", "Product-in-Environment"])
    if 0.85 <= stats["aspect"] <= 1.15:
        candidates.append("Brand Launch Trailer")

    if not candidates:
        candidates = [
            "Cinematic Hero Reveal",
            "Floating Studio Shot",
            "Product-in-Environment",
            "Tech Spec Reveal",
        ]

    ordered_unique: list[str] = []
    for item in candidates + ALL_STYLES:
        if item not in ordered_unique:
            ordered_unique.append(item)

    rng = random.Random(seed + idx * 17 + int(stats["brightness"]))
    top_pool = ordered_unique[: min(4, len(ordered_unique))]
    return top_pool[rng.randrange(len(top_pool))]


def choose_styles_for_ad(images: list[Image.Image], preferred_style: str = "Auto", seed: int = 7) -> list[str]:
    if not images:
        return ["Cinematic Hero Reveal"]

    if preferred_style and preferred_style != "Auto":
        return [preferred_style for _ in images]

    chosen = []
    used = set()

    for idx, img in enumerate(images):
        style = _choose_style_for_image(img, idx, seed=seed)

        # if same style repeats, pick a different unused style
        if style in used:
            remaining = [s for s in ALL_STYLES if s not in used]
            if remaining:
                style = remaining[idx % len(remaining)]

        chosen.append(style)
        used.add(style)

    return chosen


def _make_gradient(size: Tuple[int, int], c1: Color, c2: Color) -> Image.Image:
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / max(1, h - 1)
        row = [int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)]
        arr[y, :, :] = row
    return Image.fromarray(arr, mode="RGB").convert("RGBA")


def _cover_resize(img: Image.Image, size: Tuple[int, int], extra_scale: float = 1.0) -> Image.Image:
    tw, th = size
    w, h = img.size
    scale = max(tw / w, th / h) * extra_scale
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    out = img.resize((nw, nh), Image.LANCZOS)
    x = max(0, (nw - tw) // 2)
    y = max(0, (nh - th) // 2)
    return out.crop((x, y, x + tw, y + th))


def _contain_resize(img: Image.Image, box_size: Tuple[int, int]) -> Image.Image:
    bw, bh = box_size
    w, h = img.size
    scale = min(bw / max(1, w), bh / max(1, h))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return img.resize((nw, nh), Image.LANCZOS)


def _line_height(draw, font):
    box = draw.textbbox((0, 0), "Ag", font=font)
    return box[3] - box[1]


def _wrap_text(draw, text, font, max_width):
    words = (text or "").split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = current + " " + word
        box = draw.textbbox((0, 0), trial, font=font)
        width = box[2] - box[0]
        if width <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_multiline(base, xy, text, font, fill, max_width, line_gap=6):
    draw = ImageDraw.Draw(base)
    lines = _wrap_text(draw, text, font, max_width)
    x, y = xy
    lh = _line_height(draw, font)
    cy = y
    for line in lines:
        draw.text((x, cy), line, font=font, fill=fill)
        cy += lh + line_gap
    return cy


def _frame_to_np(img: Image.Image):
    return np.asarray(img.convert("RGB"), dtype=np.uint8)


def _ease(t: float) -> float:
    return 3 * t * t - 2 * t * t * t


def _draw_cta(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font, fill=(255, 255, 255, 235), text_fill=(18, 18, 18, 255)):
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pad_x = max(10, int(tw * 0.14))
    pad_y = max(6, int(th * 0.16))
    bw = tw + pad_x * 2
    bh = th + pad_y * 2
    draw.rounded_rectangle((x, y, x + bw, y + bh), radius=max(14, bh // 3), fill=fill)
    draw.text((x + (bw - tw) // 2, y + (bh - th) // 2 - 1), text, font=font, fill=text_fill)


def _make_shadow(size: Tuple[int, int], blur: int = 26, opacity: int = 120, radius: int = 36) -> Image.Image:
    w, h = size
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(shadow)
    d.rounded_rectangle((20, 20, w - 20, h - 20), radius=radius, fill=(0, 0, 0, opacity))
    return shadow.filter(ImageFilter.GaussianBlur(blur))


def _extract_product(img: Image.Image) -> Image.Image:
    x1, y1, x2, y2 = detect_primary_object_box(img)
    w, h = img.size
    bw = x2 - x1
    bh = y2 - y1
    pad_x = int(bw * 0.06)
    pad_y = int(bh * 0.06)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)
    cropped = img.crop((x1, y1, x2, y2)).convert("RGBA")
    return cropped


# -------------------------------------------------
# catchy tagline generation
# -------------------------------------------------
def _guess_product_label(img: Image.Image) -> str:
    """
    Simple image-based guess.
    No extra model needed.
    """
    w, h = img.size
    aspect = w / max(1, h)

    arr = np.asarray(img.convert("RGB").resize((96, 96), Image.LANCZOS)).astype(np.float32)
    brightness = float(arr.mean())
    saturation = float((arr.max(axis=2) - arr.min(axis=2)).mean())

    if aspect > 1.55:
        return "collection"
    if aspect < 0.65:
        return "bottle"
    if brightness > 185 and saturation < 28:
        return "device"
    if saturation > 70:
        return "style"
    if 0.85 <= aspect <= 1.15:
        return "product"
    return "design"


def _build_headline_candidates(label: str, brand: str) -> list[str]:
    label = (label or "product").strip().lower()
    brand = (brand or "Brand").strip()

    generic_map = {
        "shoe": [
            "Run Bold. Move Faster.",
            "Built To Outrun Ordinary.",
            "Step Into The Spotlight.",
            "Every Step. Pure Power.",
            "Speed Meets Street Style.",
        ],
        "watch": [
            "Time, Reimagined Beautifully.",
            "Built To Be Noticed.",
            "Luxury That Keeps Moving.",
            "Wear Precision With Pride.",
            "A Statement Every Second.",
        ],
        "phone": [
            "Power In Your Palm.",
            "Built For The Next Move.",
            "Smarter. Sleeker. Faster.",
            "The Future Feels Better.",
            "Hold What’s Next.",
        ],
        "perfume": [
            "Leave A Lasting Impression.",
            "Elegance You Can Feel.",
            "A Scent That Speaks.",
            "Own The Moment Instantly.",
            "Luxury In Every Note.",
        ],
        "bag": [
            "Carry Confidence Daily.",
            "Style That Moves With You.",
            "Made To Turn Heads.",
            "Designed For Every Entrance.",
            "Where Fashion Meets Function.",
        ],
        "bottle": [
            "Refresh Your Routine.",
            "Pure Style. Pure Impact.",
            "Made To Stand Out.",
            "Every Sip, Elevated.",
            "Simple. Bold. Premium.",
        ],
        "device": [
            "Sharper. Faster. Smarter.",
            "Designed For Modern Power.",
            "Precision In Every Touch.",
            "Performance Meets Style.",
            "Built To Lead.",
        ],
        "collection": [
            "More Style. More Impact.",
            "A Lineup Worth Watching.",
            "Built To Be Remembered.",
            "Every Angle Feels Premium.",
            "Crafted To Catch Eyes.",
        ],
        "style": [
            "Style That Stops Scrolls.",
            "Make Every Look Count.",
            "Bold By Design.",
            "Own The Visual Moment.",
            "Fresh. Sharp. Unmissable.",
        ],
        "product": [
            "Made To Steal Attention.",
            "Designed To Be Desired.",
            "Bold Looks. Real Impact.",
            "Built For Instant Appeal.",
            "Premium Starts Here.",
        ],
        "design": [
            "Where Design Meets Desire.",
            "Crafted To Stand Out.",
            "Visual Impact, Instantly.",
            "A Better Look Begins Here.",
            "Elevate Every Frame.",
        ],
    }

    options = generic_map.get(label, generic_map["product"]).copy()

    branded = [
        f"{brand} Looks Better Here.",
        f"Turn Heads With {brand}.",
        f"{brand} In Its Best Light.",
        f"See {brand} Steal The Scene.",
    ]

    return options + branded


def _build_tagline_candidates(label: str, brand: str) -> list[str]:
    label = (label or "product").strip().lower()
    brand = (brand or "Brand").strip()

    generic = [
        f"Premium presentation crafted to make every {label} feel irresistible.",
        f"Sharper visuals, stronger presence, and instant brand recall for every frame.",
        f"A polished ad look that keeps the product first and the message memorable.",
        f"Scroll-stopping motion designed to highlight detail, style, and value.",
        f"Built to make {brand} feel modern, bold, and ready to convert attention.",
    ]

    label_specific = {
        "shoe": [
            "Dynamic visuals that bring speed, comfort, and style into one bold statement.",
            "Made to showcase motion, performance, and confidence in every frame.",
        ],
        "phone": [
            "Sleek storytelling that highlights innovation, clarity, and modern performance.",
            "A premium tech feel designed to make every detail look smarter.",
        ],
        "perfume": [
            "Elegant motion and rich tones designed to make luxury feel unforgettable.",
            "Crafted to create a premium mood around every note and detail.",
        ],
        "watch": [
            "Refined visuals built to express precision, luxury, and timeless appeal.",
            "Editorial styling that gives every second a premium presence.",
        ],
        "bag": [
            "Fashion-forward presentation designed to highlight elegance, utility, and trend.",
            "A stylish visual treatment that keeps the product aspirational and sharp.",
        ],
        "bottle": [
            "Clean, refreshing visuals designed to make the product feel premium and desirable.",
            "Bright presentation that adds energy, clarity, and instant shelf appeal.",
        ],
    }

    return label_specific.get(label, []) + generic


def _generate_catchy_scene_copies(
    brand: str,
    image_count: int,
    user_headline: str,
    user_tagline: str,
    user_cta: str,
    product_labels: list[str],
    seed: int = 7,
):
    results = []
    rng = random.Random(seed + image_count * 11)

    for i in range(image_count):
        label = product_labels[i] if i < len(product_labels) else "product"

        if user_headline and user_headline.strip():
            headline = user_headline.strip()
        else:
            headline = rng.choice(_build_headline_candidates(label, brand))

        if user_tagline and user_tagline.strip():
            tagline = user_tagline.strip()
        else:
            tagline = rng.choice(_build_tagline_candidates(label, brand))

        cta = user_cta.strip() if user_cta and user_cta.strip() else "Shop now"

        results.append(
            {
                "headline": headline,
                "tagline": tagline,
                "cta": cta,
            }
        )

    return results


def generate_scene_copies(
    brand: str,
    image_count: int,
    user_headline: str,
    user_tagline: str,
    user_cta: str,
    product_labels: list[str],
    seed: int = 7,
):
    """
    Uses external copy generator if available.
    If its output is weak or generic, fallback to catchy per-image lines.
    """
    if _external_generate_scene_copies is not None:
        try:
            external = _external_generate_scene_copies(
                brand=brand,
                image_count=image_count,
                user_headline=user_headline,
                user_tagline=user_tagline,
                user_cta=user_cta,
            )
            if isinstance(external, list) and len(external) >= image_count:
                cleaned = []
                fallback = _generate_catchy_scene_copies(
                    brand=brand,
                    image_count=image_count,
                    user_headline=user_headline,
                    user_tagline=user_tagline,
                    user_cta=user_cta,
                    product_labels=product_labels,
                    seed=seed,
                )
                for i in range(image_count):
                    item = external[i] if i < len(external) else {}
                    headline = str(item.get("headline", "") or "").strip()
                    tagline = str(item.get("tagline", "") or "").strip()
                    cta = str(item.get("cta", "") or "").strip()

                    if len(headline.split()) < 2:
                        headline = fallback[i]["headline"]
                    if len(tagline.split()) < 4:
                        tagline = fallback[i]["tagline"]
                    if not cta:
                        cta = fallback[i]["cta"]

                    cleaned.append({"headline": headline, "tagline": tagline, "cta": cta})
                return cleaned
        except Exception:
            pass

    return _generate_catchy_scene_copies(
        brand=brand,
        image_count=image_count,
        user_headline=user_headline,
        user_tagline=user_tagline,
        user_cta=user_cta,
        product_labels=product_labels,
        seed=seed,
    )

def _remove_logo_background(logo: Image.Image) -> Image.Image:
    """
    Remove plain light background from logos and keep only the mark.
    """
    img = logo.convert("RGBA")
    arr = np.array(img).copy()

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    # strong white / near-white background removal
    white_mask = (r >= 230) & (g >= 230) & (b >= 230)
    arr[white_mask, 3] = 0

    # soften light edges a little
    soft_mask = (r >= 205) & (g >= 205) & (b >= 205) & (~white_mask)
    arr[soft_mask, 3] = np.minimum(arr[soft_mask, 3], 90)

    out = Image.fromarray(arr, mode="RGBA")

    # crop transparent empty area
    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)

    return out



def _draw_logo(base: Image.Image, logo: Optional[Image.Image], spec: RenderSpec):
    if logo is None:
        return

    w, h = spec.size

    cleaned_logo = _remove_logo_background(logo)
    lg = _contain_resize(cleaned_logo, (int(w * 0.12), int(h * 0.06)))

    x = w - lg.size[0] - int(w * 0.05)
    y = int(h * 0.04)

    base.alpha_composite(lg, (x, y))

def _gallery(images: list[Image.Image], size: Tuple[int, int], cols: int = 2) -> Image.Image:
    sw, sh = size
    count = min(4, len(images))
    tw = int(sw * 0.24)
    th = int(sh * 0.16)
    gap = int(sw * 0.02)
    rows = math.ceil(count / cols)
    canvas = Image.new("RGBA", (cols * tw + (cols - 1) * gap, rows * th + (rows - 1) * gap), (0, 0, 0, 0))
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= count:
                break
            card = Image.new("RGBA", (tw, th), (255, 255, 255, 18))
            d = ImageDraw.Draw(card)
            d.rounded_rectangle((0, 0, tw - 1, th - 1), radius=28, fill=(255, 255, 255, 18), outline=(255, 255, 255, 50), width=2)
            inner = _contain_resize(images[idx].convert("RGBA"), (int(tw * 0.78), int(th * 0.72)))
            ix = (tw - inner.size[0]) // 2
            iy = (th - inner.size[1]) // 2
            card.alpha_composite(inner, (ix, iy))
            x = c * (tw + gap)
            y = r * (th + gap)
            canvas.alpha_composite(card, (x, y))
            idx += 1
    return canvas


def _color_splash_overlay(size: Tuple[int, int], t: float) -> Image.Image:
    w, h = size
    splash = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(splash)
    r1 = int(w * (0.16 + 0.28 * t))
    r2 = int(w * (0.10 + 0.20 * t))
    d.ellipse((int(w * 0.20) - r1, int(h * 0.26) - r1, int(w * 0.20) + r1, int(h * 0.26) + r1), fill=(255, 90, 140, 88))
    d.ellipse((int(w * 0.82) - r2, int(h * 0.74) - r2, int(w * 0.82) + r2, int(h * 0.74) + r2), fill=(80, 180, 255, 74))
    return splash.filter(ImageFilter.GaussianBlur(28))


def _neon_grid_overlay(size: Tuple[int, int], t: float) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    step = max(28, w // 16)
    shift = int(step * t)
    for x in range(-step, w + step, step):
        d.line((x + shift, 0, x - int(h * 0.12) + shift, h), fill=(120, 220, 255, 26), width=2)
    for y in range(0, h + step, step):
        d.line((0, y, w, y), fill=(255, 255, 255, 10), width=1)
    return img.filter(ImageFilter.GaussianBlur(1))


def _editorial_vignette(size: Tuple[int, int], strength: int = 125) -> Image.Image:
    w, h = size
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((-int(w * 0.12), -int(h * 0.06), int(w * 1.12), int(h * 1.06)), fill=255)
    mask = ImageChops.invert(mask).filter(ImageFilter.GaussianBlur(max(40, w // 14)))
    overlay = Image.new("RGBA", size, (0, 0, 0, strength))
    overlay.putalpha(mask)
    return overlay



def _spec_lines_overlay(size: Tuple[int, int], t: float) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _style_motion(style: str, scene_index: int) -> tuple[float, tuple[float, float], tuple[float, float], float, int, int]:
    table = {
        "Cinematic Hero Reveal": (1.20, (0.56, 0.66), (0.44, 0.32), 0.05, 16, 66),
        "Color Splash Burst": (1.24, (0.24, 0.70), (0.78, 0.24), 0.07, 12, 58),
        "Floating Studio Shot": (1.16, (0.50, 0.58), (0.50, 0.42), 0.03, 22, 76),
        "Product-in-Environment": (1.20, (0.30, 0.50), (0.70, 0.52), 0.04, 10, 52),
        "Luxury Dark Editorial": (1.16, (0.48, 0.34), (0.52, 0.70), 0.03, 20, 108),
        "Tech Spec Reveal": (1.24, (0.72, 0.48), (0.28, 0.52), 0.06, 14, 86),
        "Reflective Premium Floor": (1.12, (0.52, 0.50), (0.48, 0.54), 0.02, 12, 84),
        "Urban Street Hype": (1.28, (0.72, 0.76), (0.24, 0.24), 0.08, 10, 60),
        "Hyperreal Macro Reveal": (1.34, (0.58, 0.58), (0.44, 0.44), 0.12, 24, 92),
        "Brand Launch Trailer": (1.26, (0.54, 0.68), (0.46, 0.28), 0.07, 16, 74),
    }
    if style == "Brand Launch Trailer":
        variants = [
            (1.24, (0.54, 0.68), (0.46, 0.28), 0.06, 16, 74),
            (1.22, (0.24, 0.52), (0.76, 0.48), 0.05, 12, 70),
            (1.30, (0.64, 0.66), (0.30, 0.34), 0.09, 18, 78),
        ]
        return variants[min(scene_index, len(variants) - 1)]
    return table.get(style, table["Cinematic Hero Reveal"])


def _moving_background(spec: RenderSpec, bg_img: Image.Image, t: float, style: str, scene_index: int) -> Image.Image:
    w, h = spec.size
    c1, c2 = _palette_from_image(bg_img)
    base = _make_gradient(spec.size, c1, c2)
    extra_scale, start_ratio, end_ratio, drift_zoom, blur, overlay_alpha = _style_motion(style, scene_index)

    dynamic_scale = extra_scale + drift_zoom * 0.55 * t
    bg = _cover_resize(bg_img, spec.size, extra_scale=dynamic_scale)
    bw, bh = bg.size
    overflow_x = max(0, bw - w)
    overflow_y = max(0, bh - h)
    eased = _ease(t)
    x_ratio = start_ratio[0] * (1 - eased) + end_ratio[0] * eased
    y_ratio = start_ratio[1] * (1 - eased) + end_ratio[1] * eased
    x_ratio += 0.012 * math.sin(t * math.pi * 1.25 + scene_index * 0.5)
    y_ratio += 0.010 * math.cos(t * math.pi * 1.1 + scene_index * 0.8)
    x_ratio = max(0.0, min(1.0, x_ratio))
    y_ratio = max(0.0, min(1.0, y_ratio))
    crop_x = int(overflow_x * x_ratio) if overflow_x > 0 else 0
    crop_y = int(overflow_y * y_ratio) if overflow_y > 0 else 0
    moving = bg.crop((crop_x, crop_y, crop_x + w, crop_y + h)).filter(ImageFilter.GaussianBlur(blur))
    moving.putalpha(76)
    base.alpha_composite(moving, (0, 0))
    base.alpha_composite(Image.new("RGBA", spec.size, (0, 0, 0, overlay_alpha)), (0, 0))

    if style in {"Color Splash Burst", "Urban Street Hype"}:
        base.alpha_composite(_color_splash_overlay(spec.size, t), (0, 0))
    if style in {"Tech Spec Reveal", "Brand Launch Trailer"}:
        base.alpha_composite(_neon_grid_overlay(spec.size, t), (0, 0))
    if style == "Luxury Dark Editorial":
        base.alpha_composite(_editorial_vignette(spec.size, 120), (0, 0))

    sweep = Image.new("RGBA", spec.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sweep)
    sweep_x = int((-0.25 + 1.15 * t) * w)
    sd.rectangle((sweep_x, 0, sweep_x + int(w * 0.13), h), fill=(255, 255, 255, 16))
    sweep = sweep.rotate(11, expand=False).filter(ImageFilter.GaussianBlur(30))
    base.alpha_composite(sweep, (0, 0))
    return base


def _animate_product(product: Image.Image, t: float, base_scale: float = 1.0, zoom_strength: float = 0.05, pulse: float = 0.0) -> Image.Image:
    scale = base_scale + zoom_strength * t + pulse * math.sin(t * math.pi)
    nw = max(1, int(product.size[0] * scale))
    nh = max(1, int(product.size[1] * scale))
    return product.resize((nw, nh), Image.LANCZOS)


def _product_motion_offset(t: float, amp_x: float = 0.0, amp_y: float = 0.0) -> tuple[int, int]:
    return int(math.sin(t * math.pi * 1.2) * amp_x), int(math.cos(t * math.pi * 1.1) * amp_y)


def _transition_fade(a: Image.Image, b: Image.Image, frames: int) -> list[np.ndarray]:
    return [_frame_to_np(Image.blend(a, b, i / max(1, frames - 1))) for i in range(frames)]


def _transition_slide(a: Image.Image, b: Image.Image, frames: int) -> list[np.ndarray]:
    w, h = a.size
    out = []
    for i in range(frames):
        t = _ease(i / max(1, frames - 1))
        frame = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        frame.alpha_composite(a, (int(-w * t), 0))
        frame.alpha_composite(b, (int(w - w * t), 0))
        out.append(_frame_to_np(frame))
    return out


def _transition_zoom(a: Image.Image, b: Image.Image, frames: int) -> list[np.ndarray]:
    w, h = a.size
    out = []
    for i in range(frames):
        t = _ease(i / max(1, frames - 1))
        base = Image.blend(a, b, t * 0.55)
        aw, ah = max(1, int(w * (1.0 + 0.10 * t))), max(1, int(h * (1.0 + 0.10 * t)))
        bw2, bh2 = max(1, int(w * (0.88 + 0.12 * t))), max(1, int(h * (0.88 + 0.12 * t)))
        za = a.resize((aw, ah), Image.LANCZOS)
        zb = b.resize((bw2, bh2), Image.LANCZOS)
        canvas_a = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas_b = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas_a.alpha_composite(za, ((w - aw) // 2, (h - ah) // 2))
        canvas_b.alpha_composite(zb, ((w - bw2) // 2, (h - bh2) // 2))
        out.append(_frame_to_np(Image.blend(base, Image.blend(canvas_a, canvas_b, t), 0.72)))
    return out


def _transition_flash(a: Image.Image, b: Image.Image, frames: int) -> list[np.ndarray]:
    w, h = a.size
    out = []
    for i in range(frames):
        t = i / max(1, frames - 1)
        if t < 0.5:
            blend_t = t * 2.0
            frame = Image.blend(a, b, blend_t * 0.35)
            flash_alpha = int(190 * (t / 0.5))
        else:
            blend_t = (t - 0.5) * 2.0
            frame = Image.blend(a, b, 0.35 + 0.65 * blend_t)
            flash_alpha = int(190 * (1.0 - blend_t))
        flash = Image.new("RGBA", (w, h), (255, 255, 255, flash_alpha))
        frame.alpha_composite(flash, (0, 0))
        out.append(_frame_to_np(frame))
    return out


def _transition_whip(a: Image.Image, b: Image.Image, frames: int) -> list[np.ndarray]:
    w, h = a.size
    out = []
    for i in range(frames):
        t = _ease(i / max(1, frames - 1))
        dx_a = int(-w * 1.15 * t)
        dx_b = int(w * (1.0 - t))
        blur_amt = max(0, int(10 * (1 - abs(0.5 - t) * 2)))
        fa = a.filter(ImageFilter.GaussianBlur(blur_amt))
        fb = b.filter(ImageFilter.GaussianBlur(blur_amt))
        frame = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        frame.alpha_composite(fa, (dx_a, 0))
        frame.alpha_composite(fb, (dx_b, 0))
        out.append(_frame_to_np(frame))
    return out


STYLE_TRANSITIONS = {
    "Cinematic Hero Reveal": _transition_zoom,
    "Color Splash Burst": _transition_flash,
    "Floating Studio Shot": _transition_fade,
    "Product-in-Environment": _transition_slide,
    "Luxury Dark Editorial": _transition_fade,
    "Tech Spec Reveal": _transition_whip,
    "Reflective Premium Floor": _transition_zoom,
    "Urban Street Hype": _transition_flash,
    "Hyperreal Macro Reveal": _transition_zoom,
    "Brand Launch Trailer": _transition_whip,
}


def _layout_left_text_right_product(base, spec, accent=(255, 255, 255)):
    w, h = spec.size
    f = _fonts(w)
    d = ImageDraw.Draw(base)
    left = int(w * 0.08)
    top = int(h * 0.10)
    d.text((left, top), spec.brand.upper(), font=f["brand"], fill=accent + (255,))
    y = _draw_multiline(base, (left, top + 48), spec.headline, f["title"], (255, 255, 255, 255), int(w * 0.40))
    y = _draw_multiline(base, (left, y + 10), spec.tagline, f["body"], (235, 235, 235, 230), int(w * 0.36))
    _draw_cta(d, left, min(h - 120, y + 16), spec.cta, f["small"])
    return {"product_box": (int(w * 0.48), int(h * 0.54)), "anchor": (0.72, 0.56)}


def _layout_centered_hero(base, spec, accent=(255, 255, 255)):
    w, h = spec.size
    f = _fonts(w)
    d = ImageDraw.Draw(base)
    d.text((int(w * 0.08), int(h * 0.08)), spec.brand.upper(), font=f["brand"], fill=accent + (240,))
    y = _draw_multiline(base, (int(w * 0.10), int(h * 0.14)), spec.headline, f["title"], (255, 255, 255, 255), int(w * 0.78))
    y = _draw_multiline(base, (int(w * 0.10), y + 8), spec.tagline, f["body"], (240, 240, 240, 230), int(w * 0.70))
    _draw_cta(d, int(w * 0.10), min(int(h * 0.82), y + 14), spec.cta, f["small"])
    return {"product_box": (int(w * 0.58), int(h * 0.42)), "anchor": (0.50, 0.57)}


def _layout_top_product_bottom_cta(base, spec, accent=(255, 255, 255)):
    w, h = spec.size
    f = _fonts(w)
    d = ImageDraw.Draw(base)
    d.text((int(w * 0.08), int(h * 0.07)), spec.brand.upper(), font=f["brand"], fill=accent + (255,))
    y = _draw_multiline(base, (int(w * 0.10), int(h * 0.60)), spec.headline, f["title"], (255, 255, 255, 255), int(w * 0.80))
    y = _draw_multiline(base, (int(w * 0.10), y + 6), spec.tagline, f["body"], (240, 240, 240, 225), int(w * 0.80))
    _draw_cta(d, int(w * 0.10), min(int(h * 0.90), y + 12), spec.cta, f["small"])
    return {"product_box": (int(w * 0.56), int(h * 0.38)), "anchor": (0.50, 0.30)}


def _layout_split_vertical(base, spec, accent=(180, 230, 255)):
    w, h = spec.size
    f = _fonts(w)
    d = ImageDraw.Draw(base)
    panel_x = int(w * 0.06)
    panel_y = int(h * 0.10)
    panel_w = int(w * 0.36)
    panel_h = int(h * 0.80)
    d.rounded_rectangle((panel_x, panel_y, panel_x + panel_w, panel_y + panel_h), radius=34, fill=(255, 255, 255, 14), outline=(255, 255, 255, 42), width=2)
    d.text((panel_x + 24, panel_y + 20), spec.brand.upper(), font=f["brand"], fill=accent + (255,))
    y = _draw_multiline(base, (panel_x + 24, panel_y + 78), spec.headline, f["title"], (255, 255, 255, 255), panel_w - 48)
    y = _draw_multiline(base, (panel_x + 24, y + 8), spec.tagline, f["body"], (235, 235, 235, 225), panel_w - 48)
    _draw_cta(d, panel_x + 24, min(panel_y + panel_h - 60, y + 12), spec.cta, f["small"], fill=(130, 220, 255, 240), text_fill=(10, 20, 25, 255))
    return {"product_box": (int(w * 0.44), int(h * 0.44)), "anchor": (0.73, 0.50)}


def _layout_magazine_stack(base, spec, accent=(255, 255, 255)):
    w, h = spec.size
    f = _fonts(w)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((int(w * 0.06), int(h * 0.08), int(w * 0.94), int(h * 0.92)), radius=42, outline=(255, 255, 255, 42), width=2)
    d.text((int(w * 0.10), int(h * 0.12)), spec.brand.upper(), font=f["brand"], fill=accent + (245,))
    y = _draw_multiline(base, (int(w * 0.10), int(h * 0.18)), spec.headline, f["huge"], (255, 255, 255, 180), int(w * 0.44))
    y = _draw_multiline(base, (int(w * 0.10), y + 10), spec.tagline, f["body"], (240, 240, 240, 225), int(w * 0.42))
    _draw_cta(d, int(w * 0.10), min(int(h * 0.48), y + 12), spec.cta, f["small"])
    return {"product_box": (int(w * 0.48), int(h * 0.46)), "anchor": (0.72, 0.60)}


def _layout_full_bleed_product(base, spec, accent=(255, 255, 255)):
    w, h = spec.size
    f = _fonts(w)
    d = ImageDraw.Draw(base)
    d.text((int(w * 0.08), int(h * 0.09)), spec.brand.upper(), font=f["brand"], fill=accent + (255,))
    d.text((int(w * 0.08), int(h * 0.18)), spec.headline.upper(), font=f["huge"], fill=(255, 255, 255, 165))
    y = _draw_multiline(base, (int(w * 0.08), int(h * 0.38)), spec.tagline, f["body"], (245, 245, 245, 230), int(w * 0.42))
    _draw_cta(d, int(w * 0.08), min(int(h * 0.60), y + 12), spec.cta, f["small"])
    return {"product_box": (int(w * 0.66), int(h * 0.62)), "anchor": (0.66, 0.56)}


def _truncate_words(text: str, max_words: int) -> str:
    words = (text or "").split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _truncate_words(text: str, max_words: int) -> str:
    words = (text or "").split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _wrap_text_limited(draw, text, font, max_width, max_lines=2):
    words = (text or "").split()
    if not words:
        return []

    lines = []
    current = words[0]

    for word in words[1:]:
        trial = current + " " + word
        box = draw.textbbox((0, 0), trial, font=font)
        width = box[2] - box[0]
        if width <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break

    if len(lines) < max_lines and current:
        lines.append(current)

    return lines[:max_lines]


def _draw_multiline_limited(base, xy, text, font, fill, max_width, max_lines=2, line_gap=4):
    draw = ImageDraw.Draw(base)
    lines = _wrap_text_limited(draw, text, font, max_width, max_lines=max_lines)
    x, y = xy
    lh = _line_height(draw, font)
    cy = y
    for line in lines:
        draw.text((x, cy), line, font=font, fill=fill)
        cy += lh + line_gap
    return cy



def _layout_corner_clean(base, spec, accent=(255, 255, 255)):
    w, h = spec.size
    f = _fonts(w)
    d = ImageDraw.Draw(base)

    panel_x = int(w * 0.06)
    panel_y = int(h * 0.05)
    panel_w = int(w * 0.34)
    panel_h = int(h * 0.22)

    d.rounded_rectangle(
        (panel_x, panel_y, panel_x + panel_w, panel_y + panel_h),
        radius=24,
        fill=(0, 0, 0, 78),
        outline=(255, 255, 255, 26),
        width=1,
    )

    brand_text = _truncate_words((spec.brand or "").upper(), 2)
    headline_text = _truncate_words(spec.headline, 5)
    tagline_text = _truncate_words(spec.tagline, 10)
    cta_text = _truncate_words(spec.cta or "SHOP NOW", 2)

    d.text(
        (panel_x + 16, panel_y + 12),
        brand_text,
        font=f["brand"],
        fill=accent + (240,),
    )

    y = _draw_multiline_limited(
        base,
        (panel_x + 16, panel_y + 42),
        headline_text,
        f["title"],
        (255, 255, 255, 255),
        panel_w - 32,
        max_lines=2,
        line_gap=2,
    )

    y = _draw_multiline_limited(
        base,
        (panel_x + 16, y + 4),
        tagline_text,
        f["body"],
        (235, 235, 235, 225),
        panel_w - 32,
        max_lines=2,
        line_gap=2,
    )

    cta_y = panel_y + panel_h - 42
    _draw_cta(
        d,
        panel_x + 16,
        cta_y,
        cta_text,
        f["small"],
    )

    return {
        "product_box": (int(w * 0.54), int(h * 0.50)),
        "anchor": (0.73, 0.56),
    }

def _layout_for_style(base: Image.Image, spec: RenderSpec, style: str):

    if style == "Cinematic Hero Reveal":
        return _layout_corner_clean(base, spec)

    if style == "Color Splash Burst":
        return _layout_corner_clean(base, spec)

    if style == "Floating Studio Shot":
        return _layout_centered_hero(base, spec)

    if style == "Product-in-Environment":
        return _layout_magazine_stack(base, spec)

    if style == "Luxury Dark Editorial":
        return _layout_corner_clean(base, spec)

    if style == "Tech Spec Reveal":
        return _layout_corner_clean(base, spec)   # ← changed

    if style == "Reflective Premium Floor":
        return _layout_corner_clean(base, spec)

    if style == "Urban Street Hype":
        return _layout_full_bleed_product(base, spec)

    if style == "Hyperreal Macro Reveal":
        return _layout_magazine_stack(base, spec)

    if style == "Brand Launch Trailer":
        return _layout_centered_hero(base, spec)

    return _layout_corner_clean(base, spec)


def _place_product(
    base,
    product,
    box,
    anchor,
    t,
    blur=26,
    opacity=120,
    base_scale=1.0,
    zoom_strength=0.05,
    amp_x=0,
    amp_y=0,
    pulse=0.0,
    glow_alpha=18,
):
    w, h = base.size

    boosted_box = (int(box[0] * 1.12), int(box[1] * 1.12))
    product = _contain_resize(product, boosted_box)

    # only smooth zoom, no shake
    scale = base_scale + zoom_strength * t
    nw = max(1, int(product.size[0] * scale))
    nh = max(1, int(product.size[1] * scale))
    prod = product.resize((nw, nh), Image.LANCZOS)

    # fixed anchor position
    px = int(w * anchor[0] - prod.size[0] / 2)
    py = int(h * anchor[1] - prod.size[1] / 2)

    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = px + prod.size[0] // 2, py + prod.size[1] // 2
    rr = int(max(prod.size) * 0.72)
    gd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(255, 255, 255, glow_alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(30))
    base.alpha_composite(glow, (0, 0))

    sh = _make_shadow((prod.size[0] + 48, prod.size[1] + 48), blur=blur, opacity=opacity)
    base.alpha_composite(sh, (px - 24, py + 24))
    base.alpha_composite(prod, (px, py))
    return px, py, prod


def _scene_frame(product, bg_img, spec, logo, t, scene_index, style):
    base = _moving_background(spec, bg_img, t, style, scene_index)
    _draw_logo(base, logo, spec)
    info = _layout_for_style(base, spec, style)

    if style == "Cinematic Hero Reveal":
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=28, opacity=124, base_scale=0.98, zoom_strength=0.06, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=18)

    elif style == "Color Splash Burst":
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=24, opacity=116, base_scale=1.00, zoom_strength=0.08, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=26)

    elif style == "Floating Studio Shot":
        base.alpha_composite(Image.new("RGBA", spec.size, (255, 255, 255, 10)), (0, 0))
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=30, opacity=108, base_scale=1.02, zoom_strength=0.04, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=16)

    elif style == "Product-in-Environment":
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=26, opacity=116, base_scale=1.00, zoom_strength=0.05, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=14)

    elif style == "Luxury Dark Editorial":
        base.alpha_composite(_editorial_vignette(spec.size, 110), (0, 0))
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=32, opacity=132, base_scale=1.00, zoom_strength=0.035, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=12)

    elif style == "Tech Spec Reveal":
        base.alpha_composite(_spec_lines_overlay(spec.size, t), (0, 0))
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=20, opacity=112, base_scale=1.00, zoom_strength=0.06, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=20)

    elif style == "Reflective Premium Floor":
        px, py, prod = _place_product(base, product, info["product_box"], info["anchor"], t, blur=24, opacity=118, base_scale=1.00, zoom_strength=0.04, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=14)
        refl = prod.transpose(Image.FLIP_TOP_BOTTOM).copy()
        alpha = Image.new("L", refl.size, 82)
        refl.putalpha(alpha)
        refl = refl.filter(ImageFilter.GaussianBlur(3))
        floor_mask = Image.new("L", refl.size, 0)
        fd = ImageDraw.Draw(floor_mask)
        fd.rectangle((0, 0, refl.size[0], refl.size[1] // 2), fill=120)
        refl.putalpha(floor_mask.filter(ImageFilter.GaussianBlur(18)))
        base.alpha_composite(refl, (px, py + prod.size[1] - 8))

    elif style == "Urban Street Hype":
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=18, opacity=112, base_scale=1.02, zoom_strength=0.09, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=24)

    elif style == "Hyperreal Macro Reveal":
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=30, opacity=126, base_scale=1.12, zoom_strength=0.12, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=12)

    elif style == "Brand Launch Trailer":
        base.alpha_composite(_neon_grid_overlay(spec.size, t), (0, 0))
        _place_product(base, product, info["product_box"], (0.50, 0.56), t, blur=24, opacity=118, base_scale=1.00, zoom_strength=0.07, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=20)

    else:
        _place_product(base, product, info["product_box"], info["anchor"], t, blur=26, opacity=120, base_scale=1.0, zoom_strength=0.05, amp_x=0, amp_y=0, pulse=0.0, glow_alpha=18)

    return base


def _scene_frame_builder(style: str) -> Callable:
    return lambda product, bg_img, spec, logo, t, scene_index: _scene_frame(product, bg_img, spec, logo, t, scene_index, style)


def _find_ffmpeg() -> Optional[str]:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path and os.path.exists(ffmpeg_path):
            return ffmpeg_path
    except Exception:
        pass
    return None


def _mux_audio_tracks(
    silent_video_path: str,
    final_output_path: str,
    video_duration: float,
    voice_path: Optional[str] = None,
    music_path: Optional[str] = None,
    voice_volume: float = 1.0,
    music_volume: float = 0.20,
    music_fade_in: float = 0.5,
    music_fade_out: float = 0.8,
) -> str:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return silent_video_path

    cmd = [ffmpeg, "-y", "-i", silent_video_path]

    input_count = 1
    has_voice = bool(voice_path and os.path.exists(voice_path) and os.path.getsize(voice_path) > 0)
    has_music = bool(music_path and os.path.exists(music_path) and os.path.getsize(music_path) > 0)

    if has_voice:
        cmd += ["-i", voice_path]
        voice_input_idx = input_count
        input_count += 1
    else:
        voice_input_idx = None

    if has_music:
        cmd += ["-stream_loop", "-1", "-i", music_path]
        music_input_idx = input_count
        input_count += 1
    else:
        music_input_idx = None

    if not has_voice and not has_music:
        return silent_video_path

    filter_parts = []
    audio_labels = []

    if has_voice:
        filter_parts.append(
            f"[{voice_input_idx}:a]volume={max(0.0, voice_volume):.3f}[voicea]"
        )
        audio_labels.append("[voicea]")

    if has_music:
        fade_out = max(0.0, min(music_fade_out, max(0.0, video_duration - 0.1)))
        fade_out_start = max(0.0, video_duration - fade_out)

        music_filter = f"volume={max(0.0, music_volume):.3f}"
        if music_fade_in > 0:
            music_filter += f",afade=t=in:st=0:d={music_fade_in:.3f}"
        if fade_out > 0:
            music_filter += f",afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"

        filter_parts.append(
            f"[{music_input_idx}:a]{music_filter}[musica]"
        )
        audio_labels.append("[musica]")

    if len(audio_labels) == 1:
        filter_parts.append(f"{audio_labels[0]}anull[finala]")
    else:
        filter_parts.append(
            f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:duration=first:dropout_transition=2[finala]"
        )

    cmd += [
        "-filter_complex",
        ";".join(filter_parts),
        "-map", "0:v:0",
        "-map", "[finala]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        final_output_path,
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return final_output_path
    except Exception:
        return silent_video_path


def render_fast_ad(images: list[Image.Image], logo: Optional[Image.Image], spec: RenderSpec, out_path: str) -> str:
    if not images:
        raise ValueError("No images provided.")

    ordered_images = [img.convert("RGBA") for img in images]
    products = [_extract_product(img) for img in ordered_images]

    scene_count = min(3, len(ordered_images))
    selected_images = ordered_images[:scene_count]

    styles = choose_styles_for_ad(
        selected_images,
        spec.style if not spec.auto_style else "Auto",
        seed=spec.style_seed,
    )

    # product labels for catchy per-image tagline generation
    product_labels = [_guess_product_label(prod) for prod in products[:scene_count]]

    scene_frames = max(20, int((spec.total_duration / max(1, scene_count + 1)) * spec.fps))
    transition_frames = max(8, int(spec.fps * 0.55))

    all_frames: list[np.ndarray] = []
    scene_last_frames: list[Image.Image] = []

    # uses catchy lines automatically for each image
    scene_copies = generate_scene_copies(
        brand=spec.brand,
        image_count=scene_count,
        user_headline=spec.headline if spec.headline != "NEW ARRIVAL" else "",
        user_tagline=spec.tagline if spec.tagline != "Premium design. Smart styling." else "",
        user_cta=spec.cta,
        product_labels=product_labels,
        seed=spec.style_seed,
    )

    scene_styles_used: list[str] = []
    for idx, (img, prod) in enumerate(zip(selected_images, products[:scene_count])):
        style = styles[idx if idx < len(styles) else -1]
        scene_styles_used.append(style)

        copy_data = scene_copies[idx]
        scene_spec = RenderSpec(
            **{
                **spec.__dict__,
                "headline": copy_data["headline"],
                "tagline": copy_data["tagline"],
                "cta": copy_data["cta"],
                "style": style,
            }
        )

        builder = _scene_frame_builder(style)
        scene_frames_imgs = []
        for fidx in range(scene_frames):
            t = _ease(fidx / max(1, scene_frames - 1))
            frame = builder(prod, img, scene_spec, logo, t, idx)
            scene_frames_imgs.append(frame)
            all_frames.append(_frame_to_np(frame))
        scene_last_frames.append(scene_frames_imgs[-1])

    final_frames: list[np.ndarray] = []
    cursor = 0
    for i, style in enumerate(scene_styles_used):
        start = cursor
        end = start + scene_frames
        final_frames.extend(all_frames[start:end])
        cursor = end
        if i < len(scene_last_frames) - 1:
            transition_fn = STYLE_TRANSITIONS.get(style, _transition_fade)
            final_frames.extend(transition_fn(scene_last_frames[i], scene_last_frames[i + 1], transition_frames))

    outro_style = scene_styles_used[-1] if scene_styles_used else "Cinematic Hero Reveal"
    final_bg = _moving_background(spec, ordered_images[0], 1.0, outro_style, 0)
    _draw_logo(final_bg, logo, spec)
    d = ImageDraw.Draw(final_bg)

    title_x = int(spec.size[0] * 0.08)
    title_y = int(spec.size[1] * 0.06)
    final_title_font = _safe_font(max(26, spec.size[0] // 15), True)
    final_body_font = _safe_font(max(14, spec.size[0] // 30), False)
    final_cta_font = _safe_font(max(14, spec.size[0] // 34), True)

    final_title_text = "MORE TO EXPLORE"
    d.text((title_x, title_y), final_title_text, font=final_title_font, fill=(255, 255, 255, 245))
    title_box = d.textbbox((title_x, title_y), final_title_text, font=final_title_font)
    title_bottom = title_box[3]

    final_tagline = scene_copies[-1]["tagline"] if scene_copies else spec.tagline
    final_cta = scene_copies[-1]["cta"] if scene_copies else spec.cta

    tagline_y = _draw_multiline(
        final_bg,
        (title_x, title_bottom + int(spec.size[1] * 0.02)),
        final_tagline,
        final_body_font,
        (235, 235, 235, 225),
        int(spec.size[0] * 0.42),
        line_gap=4,
    )
    _draw_cta(d, title_x, tagline_y + 10, final_cta, final_cta_font)

    gal = _gallery(ordered_images, spec.size, cols=2)
    gal_x = (spec.size[0] - gal.size[0]) // 2
    gal_y = int(spec.size[1] * 0.56)
    final_bg.alpha_composite(gal, (gal_x, gal_y))

    shine = Image.new("RGBA", spec.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shine)
    sd.rectangle((int(spec.size[0] * 0.15), int(spec.size[1] * 0.52), int(spec.size[0] * 0.85), int(spec.size[1] * 0.94)), fill=(255, 255, 255, 14))
    shine = shine.rotate(-8, expand=False).filter(ImageFilter.GaussianBlur(26))
    final_bg.alpha_composite(shine, (0, 0))

    if scene_last_frames:
        transition_fn = STYLE_TRANSITIONS.get(outro_style, _transition_fade)
        final_frames.extend(transition_fn(scene_last_frames[-1], final_bg, transition_frames))

    for _ in range(scene_frames):
        final_frames.append(_frame_to_np(final_bg))

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    video_duration = len(final_frames) / float(spec.fps)

    needs_audio_mux = bool(spec.voice_path or spec.music_path)

    if needs_audio_mux:
        tmp_dir = Path(tempfile.mkdtemp(prefix="dynoad_render_"))
        silent_video_path = str(tmp_dir / "silent_video.mp4")
        imageio.mimsave(silent_video_path, final_frames, fps=spec.fps)

        final_result = _mux_audio_tracks(
            silent_video_path=silent_video_path,
            final_output_path=out_path,
            video_duration=video_duration,
            voice_path=spec.voice_path,
            music_path=spec.music_path,
            voice_volume=spec.voice_volume,
            music_volume=spec.music_volume,
            music_fade_in=spec.music_fade_in,
            music_fade_out=spec.music_fade_out,
        )

        if final_result != out_path:
            shutil.copyfile(silent_video_path, out_path)

        return out_path

    imageio.mimsave(out_path, final_frames, fps=spec.fps)
    return out_path