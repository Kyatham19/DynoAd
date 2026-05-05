from pathlib import Path

from ad_generator import generate_canva_style_ad

base = Path(__file__).parent
sample_images = sorted(str(p) for p in (base / "sample_images").glob("*.png"))
out = generate_canva_style_ad(
    image_paths=sample_images,
    output_path=str(base / "output" / "demo_generated.mp4"),
    title="FRESH",
    subtitle="SQUEEZE",
    burst_title="CITRUS",
    burst_subtitle="BURST",
    cta="ORDER NOW",
)
print(f"Generated: {out}")
