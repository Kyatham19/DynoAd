import random

CATCHY_TEMPLATES = [
    "Unleash the Power of {}",
    "{} That Turns Heads",
    "Experience the Magic of {}",
    "Elevate Your Style with {}",
    "Where Innovation Meets {}",
    "{} Like Never Before",
    "The Future of {} Starts Here",
    "Step Into the World of {}",
    "Designed for Those Who Love {}",
    "The Ultimate {} Experience",
]

def generate_taglines(products):
    taglines = []

    for p in products:
        template = random.choice(CATCHY_TEMPLATES)
        tagline = template.format(p.title())
        taglines.append(tagline)

    return taglines
