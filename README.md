# DynoAd

DynoAd is an AI-powered system that converts product images into professional advertisement videos using computer vision and automated content generation.


## Style included
- giant masked intro text filled with image collage
- lime circle title reveal
- bold white kinetic typography
- center product hero shot with glow/shadow
- citrus burst text scene
- final packshot scene with CTA and optional logo

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Quick demo
```bash
python demo_run.py
```

## Notes
- Transparent PNG product images give the best result.
- JPGs also work; the script tries a lightweight background cleanup.
- Optional music is merged with ffmpeg if it is installed on your machine.
