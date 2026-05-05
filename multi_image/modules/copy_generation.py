from __future__ import annotations

import random


HEADLINES = [
    "Step into a new era of everyday comfort.",
    "Upgrade your style with something built to stand out.",
    "Where performance meets effortless street style.",
    "Designed for comfort and made to turn heads.",
    "Move through the day with confidence and style.",
    "A fresh take on modern everyday fashion.",
    "Built for movement and styled for impact.",
    "Experience comfort that keeps up with your lifestyle.",
    "Make every step feel like the right choice.",
    "A new standard in style, comfort, and performance.",
    "Crafted to elevate the way you move every day.",
    "Bring home the perfect blend of comfort and edge.",
]

TAGLINES = [
    "Clean design with premium comfort you can feel all day.",
    "Smart styling that fits effortlessly into your daily routine.",
    "Engineered for movement while keeping your look sharp.",
    "Minimal design that delivers maximum everyday comfort.",
    "The perfect balance of performance and street-ready style.",
    "Built with premium materials for everyday confidence.",
    "Modern design that works wherever life takes you.",
    "Comfort and style combined into one bold statement.",
    "A design that adapts to every step you take.",
    "Style that feels just as good as it looks.",
    "Designed to move with you from morning to night.",
    "Premium comfort meets a look that never goes unnoticed.",
]

CTAS = [
    "Shop now",
    "Explore now",
    "Discover more",
    "View collection",
    "Get yours",
    "Shop the drop",
]


def generate_copy(
    brand: str,
    user_headline: str,
    user_tagline: str,
    user_cta: str,
) -> tuple[str, str, str]:
    headline = (user_headline or "").strip() or random.choice(HEADLINES)
    tagline = (user_tagline or "").strip() or random.choice(TAGLINES)
    cta = (user_cta or "").strip() or random.choice(CTAS)
    return headline, tagline, cta


def generate_scene_copies(
    brand: str,
    image_count: int,
    user_headline: str = "",
    user_tagline: str = "",
    user_cta: str = "",
):
    scene_copies = []
    used_headlines = set()
    used_taglines = set()

    for _ in range(image_count):
        if user_headline.strip():
            headline = user_headline.strip()
        else:
            headline = random.choice(HEADLINES)
            while headline in used_headlines and len(used_headlines) < len(HEADLINES):
                headline = random.choice(HEADLINES)

        if user_tagline.strip():
            tagline = user_tagline.strip()
        else:
            tagline = random.choice(TAGLINES)
            while tagline in used_taglines and len(used_taglines) < len(TAGLINES):
                tagline = random.choice(TAGLINES)

        cta = user_cta.strip() if user_cta.strip() else random.choice(CTAS)

        used_headlines.add(headline)
        used_taglines.add(tagline)

        scene_copies.append({
            "headline": headline,
            "tagline": tagline,
            "cta": cta,
        })

    return scene_copies