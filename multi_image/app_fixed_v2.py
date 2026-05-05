from __future__ import annotations

import inspect
import io
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

import streamlit as st
from PIL import Image
from PIL import Image, ImageOps


# ---------------------------------------
# Voice selection helpers
# ---------------------------------------
def choose_voice_from_avatar(avatar_path: str) -> str:
    name = Path(avatar_path).name.lower()
    if "female" in name or "woman" in name or "girl" in name:
        return "female"
    if "male" in name or "man" in name or "boy" in name:
        return "male"
    if "cartoon" in name or "mascot" in name:
        return "cartoon"
    return "female"


def choose_voice_from_presenter(presenter_type: str) -> str:
    label = (presenter_type or "").lower()
    if "female" in label:
        return "female"
    if "male" in label:
        return "male"
    if "cartoon" in label:
        return "cartoon"
    return "female"


def map_voice_model(voice_type: str) -> str:
    voice_type = (voice_type or "").lower().strip()
    mapping = {
        "male": "male",
        "female": "female",
        "cartoon": "cartoon",
    }
    return mapping.get(voice_type, "female")


def fallback_script(brand: str, headline: str, tagline: str, cta: str, tone: str) -> str:
    brand = (brand or "Our Brand").strip()
    headline = (headline or "New Arrival").strip()
    tagline = (tagline or "Premium quality for everyday use.").strip()
    cta = (cta or "Shop now").strip()
    tone_map = {
        "Luxury & Premium": f"Introducing {brand}. {headline}. {tagline} Crafted for people who value premium quality and standout design. {cta}.",
        "Energetic & Bold": f"{brand} is here. {headline}. {tagline} Bold style, bold performance, bold impact. {cta} today.",
        "Minimal & Clean": f"Meet {brand}. {headline}. {tagline} Clean design, smooth experience, effortless choice. {cta}.",
        "Tech & Futuristic": f"Welcome to the future with {brand}. {headline}. {tagline} Smart, sleek, and built for modern life. {cta}.",
        "Warm & Friendly": f"Say hello to {brand}. {headline}. {tagline} Made to fit beautifully into your everyday routine. {cta}.",
    }
    return tone_map.get(tone, f"Introducing {brand}. {headline}. {tagline} Experience the difference today. {cta}.")


# -------------------------------------------------
# flexible imports: renderer
# -------------------------------------------------
_RENDER_IMPORT_ERROR = None

try:
    from render.video_renderer import render_fast_ad, RenderSpec, choose_styles_for_ad
except Exception as e1:
    try:
        from video_renderer import render_fast_ad, RenderSpec, choose_styles_for_ad
    except Exception as e2:
        try:
            from src.render.video_renderer import render_fast_ad, RenderSpec, choose_styles_for_ad
        except Exception as e3:
            render_fast_ad = None
            RenderSpec = None
            choose_styles_for_ad = None
            _RENDER_IMPORT_ERROR = f"""
Renderer import failed.

Tried:
1. from render.video_renderer import ...
2. from video_renderer import ...
3. from src.render.video_renderer import ...

Errors:
- {e1}
- {e2}
- {e3}
"""


# -------------------------------------------------
# flexible imports: voice generation
# -------------------------------------------------
_VOICE_IMPORT_ERROR = None

try:
    from voice_generation import generate_script_with_gemini_from_images, generate_elevenlabs_audio
except Exception as e1:
    try:
        from modules.voice_generation import generate_script_with_gemini_from_images, generate_elevenlabs_audio
    except Exception as e2:
        try:
            from dynoad.voice_generation import generate_script_with_gemini_from_images, generate_elevenlabs_audio
        except Exception as e3:
            generate_script_with_gemini_from_images = None
            generate_elevenlabs_audio = None
            _VOICE_IMPORT_ERROR = f"""
Voice generation import failed.

Tried:
1. from voice_generation import ...
2. from modules.voice_generation import ...
3. from dynoad.voice_generation import ...

Errors:
- {e1}
- {e2}
- {e3}
"""


# -------------------------------------------------
# page config
# -------------------------------------------------
st.set_page_config(page_title="DynoAd Ultra", layout="wide", initial_sidebar_state="collapsed")

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_DIR = Path("assets/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------
# custom CSS
# -------------------------------------------------
def inject_custom_css():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
        .stApp { background: #07070c; color: white; }
        .stApp::before {
            content: "";
            position: fixed;
            inset: 0;
            background:
                radial-gradient(circle at 20% 20%, rgba(109, 40, 217, 0.30), transparent 30%),
                radial-gradient(circle at 80% 80%, rgba(37, 99, 235, 0.25), transparent 30%);
            z-index: -2;
            animation: dynoadMove 14s infinite alternate ease-in-out;
            pointer-events: none;
        }
        @keyframes dynoadMove { 0% { transform: translateY(0px); } 100% { transform: translateY(-80px); } }
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }
        header[data-testid="stHeader"] { background: transparent; }
        section[data-testid="stSidebar"] { display: none; }
        .dyno-nav {
            display:flex; justify-content:space-between; align-items:center; padding:18px 28px;
            border:1px solid rgba(255,255,255,.06); border-radius:18px; background:rgba(17,17,24,.55);
            backdrop-filter: blur(12px); margin-bottom:28px;
        }
        .dyno-logo { color:#c4b5fd; font-weight:700; font-size:1.25rem; letter-spacing:0.2px; }
        .dyno-nav-links { display:flex; gap:28px; color:rgba(255,255,255,.78); font-size:0.95rem; }
        .dyno-avatar { width:38px; height:38px; border-radius:50%; background:linear-gradient(135deg,#9333ea,#3b82f6); box-shadow:0 0 16px rgba(147,51,234,.45); }
        .dyno-hero { text-align:center; padding:45px 12px 40px; margin-bottom:12px; }
        .dyno-tag {
            display:inline-block; padding:10px 16px; border-radius:999px; background:#141420;
            border:1px solid rgba(255,255,255,.06); color:#c4b5fd; font-size:0.92rem; margin-bottom:18px;
        }
        .dyno-hero h1 {
            font-size:clamp(2.4rem,5vw,4.5rem); line-height:1.06; margin:0;
            background:linear-gradient(90deg,#ffffff,#c4b5fd); -webkit-background-clip:text; -webkit-text-fill-color:transparent;
        }
        .dyno-hero p { max-width:760px; margin:18px auto 0; color:rgba(255,255,255,.72); font-size:1.05rem; line-height:1.7; }
        .dyno-card {
            background:rgba(17,17,24,.82); backdrop-filter:blur(12px); border:1px solid rgba(255,255,255,.06);
            border-radius:20px; padding:22px; box-shadow:0 20px 40px rgba(0,0,0,.28); margin-bottom:22px;
        }
        .dyno-card h3 { margin-top:0; margin-bottom:8px; font-size:1.15rem; }
        .dyno-muted { color:rgba(255,255,255,.68); font-size:0.95rem; }
        .dyno-script-box {
            background:#14141d; border:1px solid rgba(255,255,255,.06); border-radius:14px; padding:16px;
            white-space:pre-wrap; line-height:1.65; color:rgba(255,255,255,.88); min-height:220px;
        }
        .dyno-preview-box {
            height:280px; display:flex; align-items:center; justify-content:center; flex-direction:column;
            border-radius:16px; background:linear-gradient(135deg,#1c1c2b,#141422);
            border:1px solid rgba(255,255,255,.05); color:rgba(255,255,255,.70);
        }
        .dyno-play { font-size:2.2rem; margin-bottom:10px; }
        .dyno-timeline-item { margin-bottom:18px; }
        .dyno-timeline-label { font-size:0.95rem; margin-bottom:6px; }
        .dyno-bar { height:8px; border-radius:999px; }
        .purple { background:#9333ea; width:80%; }
        .blue { background:#3b82f6; width:70%; }
        .green { background:#10b981; width:60%; }
        .orange { background:#f59e0b; width:50%; }
        .dyno-tip { margin-top:12px; color:#c4b5fd; font-size:0.9rem; }
        .dyno-style-chip {
            display:inline-block; margin:6px 8px 0 0; padding:8px 12px; border-radius:999px;
            background:rgba(147,51,234,.16); border:1px solid rgba(196,181,253,.18); color:#e9ddff; font-size:0.88rem;
        }
        div[data-testid="stFileUploader"] {
            background:rgba(20,20,32,.65); border:1px dashed rgba(255,255,255,.16); border-radius:16px; padding:6px;
        }
        div[data-testid="stFileUploader"]:hover { border-color:#9333ea; }
        .stButton > button, .stDownloadButton > button {
            width:100%; border:none !important; border-radius:12px !important; padding:0.9rem 1rem !important;
            font-weight:600 !important; background:linear-gradient(90deg,#9333ea,#3b82f6) !important; color:white !important;
            transition:0.25s ease !important; box-shadow:0 8px 24px rgba(80,70,200,0.25);
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            transform:translateY(-1px) scale(1.01); box-shadow:0 14px 30px rgba(80,70,200,0.34);
        }
        .stSelectbox label, .stTextInput label, .stSlider label, .stRadio label, .stFileUploader label {
            color:rgba(255,255,255,.92) !important; font-weight:600 !important;
        }
        .stTextInput input, .stSelectbox div[data-baseweb="select"] > div, .stTextArea textarea {
            background:#14141d !important; color:white !important; border:1px solid rgba(255,255,255,.08) !important; border-radius:12px !important;
        }
        .stAlert { border-radius:14px; }
        .preview-img-wrap img { border-radius:16px !important; border:1px solid rgba(255,255,255,.08); }
        .dyno-subtle-sep { height:1px; background:rgba(255,255,255,.05); margin:12px 0 20px 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -------------------------------------------------
# helpers
# -------------------------------------------------
def _read_uploaded_image(uploaded_file) -> Optional[Image.Image]:
    try:
        data = uploaded_file.getvalue()
        if not data:
            return None
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        return img.convert("RGBA")
    except Exception:
        return None


def _save_uploaded_audio(uploaded_audio) -> Optional[str]:
    if uploaded_audio is None:
        return None
    try:
        audio_dir = Path("temp_audio")
        audio_dir.mkdir(parents=True, exist_ok=True)
        out_path = audio_dir / uploaded_audio.name
        out_path.write_bytes(uploaded_audio.getvalue())
        return str(out_path)
    except Exception:
        return None


def _save_uploaded_video(uploaded_video) -> Optional[str]:
    if uploaded_video is None:
        return None
    try:
        video_dir = Path("temp_video")
        video_dir.mkdir(parents=True, exist_ok=True)
        out_path = video_dir / uploaded_video.name
        out_path.write_bytes(uploaded_video.getvalue())
        return str(out_path)
    except Exception:
        return None


def _load_images(uploaded_files) -> List[Image.Image]:
    images: List[Image.Image] = []
    for f in uploaded_files or []:
        img = _read_uploaded_image(f)
        if img is not None:
            images.append(img)
    return images


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


def _resolve_default_avatar_clip(presenter_type: str) -> Optional[str]:
    avatar_map = {
        "Realistic Male": AVATAR_DIR / "real_male.mp4",
        "Realistic Female": AVATAR_DIR / "real_female.mp4",
        "Cartoon Presenter": AVATAR_DIR / "cartoon.mp4",
    }
    path = avatar_map.get(presenter_type)
    if path and path.exists():
        return str(path)
    return None


def _overlay_avatar_ffmpeg(base_video_path: str, avatar_video_path: str, output_path: str, position: str = "bottom-right", scale_ratio: float = 0.28) -> str:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return base_video_path
    pos_map = {
        "bottom-right": "W-w-24:H-h-24",
        "bottom-left": "24:H-h-24",
        "top-right": "W-w-24:24",
        "top-left": "24:24",
    }
    overlay_pos = pos_map.get(position, "W-w-24:H-h-24")
    filter_complex = f"[1:v]scale=iw*{scale_ratio}:-1[avatar];[0:v][avatar]overlay={overlay_pos}:shortest=1[v]"
    cmd = [
        ffmpeg, "-y", "-i", base_video_path, "-stream_loop", "-1", "-i", avatar_video_path,
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", output_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return output_path
    except Exception:
        return base_video_path


def _safe_generate_script(
    images: List[Image.Image],
    tone: str,
    brand: str,
    headline: str,
    tagline: str,
    cta: str,
    product_description: str = "",
) -> tuple[str, str]:
    if generate_script_with_gemini_from_images is None:
        return fallback_script(brand, headline, tagline, cta, tone), "Gemini module unavailable. Used fallback script."

    try:
        prompt_brand = f"{brand}. {product_description}".strip()

        script_result = generate_script_with_gemini_from_images(
            images=images,
            tone=tone,
            brand=prompt_brand,
            cta=cta,
        )

        if isinstance(script_result, dict):
            generated_script = str(script_result.get("script", "")).strip()
            if generated_script:
                return generated_script, ""
            err = str(script_result.get("error", "Unknown Gemini error"))
            return fallback_script(brand, headline, tagline, cta, tone), f"{err} | Used fallback script."

        return fallback_script(brand, headline, tagline, cta, tone), "Unexpected Gemini response. Used fallback script."

    except Exception as e:
        return fallback_script(brand, headline, tagline, cta, tone), f"{e} | Used fallback script."


def _safe_generate_elevenlabs_audio(script: str, output_path: str, voice_type: str) -> dict:
    if generate_elevenlabs_audio is None:
        return {"audio_path": None, "error": "Audio generator unavailable"}

    try:
        sig = inspect.signature(generate_elevenlabs_audio)
        kwargs = {"script": script, "output_path": output_path}
        voice_model = map_voice_model(voice_type)
        if "voice_type" in sig.parameters:
            kwargs["voice_type"] = voice_type
        if "voice_model" in sig.parameters:
            kwargs["voice_model"] = voice_model
        if "voice_name" in sig.parameters:
            kwargs["voice_name"] = voice_model
        if "voice" in sig.parameters:
            kwargs["voice"] = voice_model
        if "speaker" in sig.parameters:
            kwargs["speaker"] = voice_model
        result = generate_elevenlabs_audio(**kwargs)
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            return {"audio_path": result}
        return {"audio_path": None, "error": "Unexpected audio generator response"}
    except Exception as e:
        return {"audio_path": None, "error": str(e)}


def hero():
    st.markdown(
        """
        <div class="dyno-nav">
            <div class="dyno-logo">✨ DynoAd Ultra</div>
            <div class="dyno-nav-links">
                <div>Dashboard</div>
                <div>Templates</div>
                <div>History</div>
                <div>Settings</div>
            </div>
            <div class="dyno-avatar"></div>
        </div>

        <section class="dyno-hero">
            <div class="dyno-tag">AI Powered Advertisement Generation</div>
            <h1>Generate AI Advertisements<br>in Seconds</h1>
            <p>
                Upload product images and let AI automatically generate
                professional marketing videos with dynamic visuals, script,
                voice, music, and presenter overlays.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def open_card(title: str, subtitle: str | None = None):
    st.markdown('<div class="dyno-card">', unsafe_allow_html=True)
    st.markdown(f"<h3>{title}</h3>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="dyno-muted">{subtitle}</div>', unsafe_allow_html=True)


def close_card():
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# checks
# -------------------------------------------------
if render_fast_ad is None or RenderSpec is None:
    st.error("Video renderer could not be imported.")
    st.code(_RENDER_IMPORT_ERROR or "Unknown renderer import error")
    st.stop()


# -------------------------------------------------
# UI start
# -------------------------------------------------
inject_custom_css()
hero()

if "generated_script" not in st.session_state:
    st.session_state.generated_script = ""
if "final_video_path" not in st.session_state:
    st.session_state.final_video_path = None
if "voice_debug" not in st.session_state:
    st.session_state.voice_debug = ""
if "selected_styles" not in st.session_state:
    st.session_state.selected_styles = []


# -------------------------------------------------
# Main layout
# -------------------------------------------------
left_main, right_main = st.columns([1.25, 1])

with left_main:
    open_card("Upload Product Images", "Drop images here or click to upload.")
    uploaded_images = st.file_uploader(
        "Upload product images",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="images_upload",
        label_visibility="collapsed",
    )
    st.markdown('<div class="dyno-tip">AI now chooses the ad style automatically for each scene. No manual style picker.</div>', unsafe_allow_html=True)
    close_card()

with right_main:
    open_card("Generated Advertisement", "Video preview will appear here once rendering completes.")
    if st.session_state.final_video_path and Path(st.session_state.final_video_path).exists():
        st.video(st.session_state.final_video_path)
    else:
        st.markdown(
            """
            <div class="dyno-preview-box">
                <div class="dyno-play">▶</div>
                <div>Video preview will appear here</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    close_card()

images = _load_images(uploaded_images)

if images:
    open_card("Preview Gallery", "Uploaded product images")
    preview_cols = st.columns(min(4, len(images)))
    for i, img in enumerate(images[:8]):
        with preview_cols[i % len(preview_cols)]:
            st.markdown('<div class="preview-img-wrap">', unsafe_allow_html=True)
            st.image(img, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    close_card()

settings_col, script_col, timeline_col = st.columns([1.1, 1, 1])

with settings_col:
    open_card("Customization")

    brand = st.text_input("Brand", "Dyno")

    product_description = st.text_area(
        "Product Description",
        placeholder="Describe the product, material, features, use case, target audience, colors, benefits...",
        height=120,
    )

    headline = st.text_input("Headline", "NEW ARRIVAL")
    tagline = st.text_input("Tagline", "Premium design. Smart styling.")
    cta = st.text_input("CTA", "SHOP NOW")

    format_choice = st.selectbox(
        "Video Format",
        ["Vertical (720x1280)", "Square (1080x1080)", "Landscape (1280x720)"],
        index=0,
    )

    fps = st.slider("FPS", min_value=8, max_value=30, value=12, step=1)
    total_duration = st.slider("Total Duration (seconds)", min_value=6, max_value=24, value=12, step=1)

    st.caption("Style selection is fully automatic.")

    uploaded_logo = st.file_uploader(
        "Upload logo (optional)",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=False,
        key="logo_uploader",
    )

    st.markdown('<div class="dyno-subtle-sep"></div>', unsafe_allow_html=True)

    close_card()

with script_col:
    open_card("Editable Ad Script")

    default_script = st.session_state.generated_script.strip() or (
        "Scene 1 (0-5s)\nYour product enters with a bold visual hook\n\n"
        "Scene 2 (5-10s)\nThe AI shifts style to match the product mood\n\n"
        "Scene 3 (10-15s)\nA stronger CTA closes the ad with impact"
    )

    editable_script = st.text_area(
        "Edit generated text before rendering",
        value=default_script,
        height=260,
        key="editable_script",
    )

    close_card()

with timeline_col:
    open_card("Advertisement Timeline")
    st.markdown(
        """
        <div class="dyno-timeline-item"><div class="dyno-timeline-label">Hook Frame</div><div class="dyno-bar purple"></div></div>
        <div class="dyno-timeline-item"><div class="dyno-timeline-label">Hero Product Scene</div><div class="dyno-bar blue"></div></div>
        <div class="dyno-timeline-item"><div class="dyno-timeline-label">Dynamic Style Switch</div><div class="dyno-bar green"></div></div>
        <div class="dyno-timeline-item"><div class="dyno-timeline-label">CTA Outro</div><div class="dyno-bar orange"></div></div>
        """,
        unsafe_allow_html=True,
    )
    close_card()


open_card("Audio, Voiceover & Presenter")

audio_col, avatar_col = st.columns(2)

with audio_col:
    audio_mode = st.selectbox(
        "Audio Mode",
        ["No Audio", "Upload Background Music", "AI Voiceover (Gemini + ElevenLabs)"],
        index=0,
    )

    uploaded_music = None
    voice_tone = "Luxury & Premium"
    music_volume = 0.20
    music_fade_in = 0.5
    music_fade_out = 0.8

    if audio_mode == "Upload Background Music":
        uploaded_music = st.file_uploader(
            "Upload Background Music",
            type=["mp3", "wav", "m4a"],
            accept_multiple_files=False,
            key="music_uploader",
        )
        music_volume = st.slider("Music Volume", 0.0, 1.0, 0.20, 0.05)
        music_fade_in = st.slider("Music Fade In", 0.0, 3.0, 0.5, 0.1)
        music_fade_out = st.slider("Music Fade Out", 0.0, 3.0, 0.8, 0.1)

    elif audio_mode == "AI Voiceover (Gemini + ElevenLabs)":
        voice_tone = st.selectbox(
            "Voice Tone",
            [
                "Luxury & Premium",
                "Energetic & Bold",
                "Minimal & Clean",
                "Tech & Futuristic",
                "Warm & Friendly",
            ],
            index=0,
        )

with avatar_col:
    avatar_mode = st.selectbox(
        "Presenter Mode",
        ["No Presenter", "Side Presenter Overlay"],
        index=0,
    )

    avatar_source = "Use built-in avatar"
    presenter_type = "Realistic Female"
    uploaded_avatar_video = None
    avatar_position = "bottom-right"
    avatar_scale = 0.28

    if avatar_mode == "Side Presenter Overlay":
        avatar_source = st.radio(
            "Avatar Source",
            ["Use built-in avatar", "Upload my own avatar video"],
            horizontal=False,
        )

        if avatar_source == "Use built-in avatar":
            presenter_type = st.selectbox(
                "Presenter Type",
                ["Realistic Male", "Realistic Female", "Cartoon Presenter"],
                index=1,
            )
        else:
            uploaded_avatar_video = st.file_uploader(
                "Upload Avatar Video",
                type=["mp4", "mov", "webm"],
                accept_multiple_files=False,
                key="avatar_video_uploader",
            )

        avatar_position = st.selectbox(
            "Avatar Position",
            ["bottom-right", "bottom-left", "top-right", "top-left"],
            index=0,
        )

        avatar_scale = st.slider("Avatar Size", 0.15, 0.45, 0.28, 0.01)

close_card()

# -------------------------------------------------
# Generate button
# -------------------------------------------------
generate_now = st.button("✨ Generate Advertisement", use_container_width=True)
logo = _read_uploaded_image(uploaded_logo) if uploaded_logo is not None else None

if generate_now:
    if not images:
        st.error("Please upload at least one valid product image.")
        st.stop()

    if format_choice == "Vertical (720×1280)":
        size = (720, 1280)
    elif format_choice == "Square (1080×1080)":
        size = (1080, 1080)
    else:
        size = (1280, 720)

    out_path = OUTPUT_DIR / "dynoad_output.mp4"
    final_audio_path = None
    generated_script = ""
    script_error = ""
    script_text = ""
    voice_debug = ""
    selected_voice_type = "female"

    if avatar_mode == "Side Presenter Overlay":
        if avatar_source == "Use built-in avatar":
            selected_voice_type = choose_voice_from_presenter(presenter_type)
        else:
            selected_voice_type = choose_voice_from_avatar(uploaded_avatar_video.name) if uploaded_avatar_video is not None else "female"

    if audio_mode == "Upload Background Music":
        final_audio_path = _save_uploaded_audio(uploaded_music)
        if uploaded_music is not None and not final_audio_path:
            st.warning("Music file could not be saved. Video will be generated without audio.")

        elif audio_mode == "AI Voiceover (Gemini + ElevenLabs)":
            script_text, script_error = _safe_generate_script(
            images=images,
            tone=voice_tone,
            brand=brand,
            headline=headline,
            tagline=tagline,
            cta=cta,
            product_description=product_description,
        )

        generated_script = (st.session_state.get("editable_script") or script_text).strip()

        if script_error:
            st.warning(f"AI script fallback used. Details: {script_error}")

        if generated_script:
            with st.spinner("Generating AI voiceover..."):
                final_script_for_voice = (st.session_state.get("editable_script") or generated_script).strip()

                voice_result = _safe_generate_elevenlabs_audio(
                    script=final_script_for_voice,
                    output_path=str(OUTPUT_DIR / "voiceover.mp3"),
                    voice_type=selected_voice_type,
                )

                final_audio_path = voice_result.get("audio_path")
                voice_debug = f"Voice type selected: {selected_voice_type}"

                if not final_audio_path:
                    st.warning(
                        "Voice generation failed. Video will still be created.\n\n"
                        f"Details: {voice_result.get('error', 'Unknown audio error')}"
                    )
        else:
            st.warning("No script could be generated. Video will be created without voiceover.")

    styles_used = []
    if choose_styles_for_ad is not None:
        try:
            styles_used = choose_styles_for_ad(images[: min(3, len(images))], preferred_style="Auto")
        except Exception:
            styles_used = []

    spec = RenderSpec(
        size=size,
        fps=fps,
        total_duration=total_duration,
        brand=brand,
        headline=headline,
        tagline=tagline,
        cta=cta,
        style="Auto",
        auto_style=True,
        music_path=final_audio_path,
        music_volume=1.0 if audio_mode == "AI Voiceover (Gemini + ElevenLabs)" and final_audio_path else music_volume,
        music_fade_in=0.0 if audio_mode == "AI Voiceover (Gemini + ElevenLabs)" and final_audio_path else music_fade_in,
        music_fade_out=0.0 if audio_mode == "AI Voiceover (Gemini + ElevenLabs)" and final_audio_path else music_fade_out,
    )

    try:
        with st.spinner("Rendering ad video..."):
            result_path = render_fast_ad(images=images, logo=logo, spec=spec, out_path=str(out_path))

        final_video_path = str(result_path)

        if avatar_mode == "Side Presenter Overlay":
            avatar_clip_path = None
            if avatar_source == "Use built-in avatar":
                avatar_clip_path = _resolve_default_avatar_clip(presenter_type)
                if not avatar_clip_path:
                    st.warning(f"No built-in avatar found for '{presenter_type}'. Put files in assets/avatars/: real_male.mp4, real_female.mp4, cartoon.mp4.")
            else:
                avatar_clip_path = _save_uploaded_video(uploaded_avatar_video)
                if uploaded_avatar_video is not None and not avatar_clip_path:
                    st.warning("Avatar video could not be saved.")

            if avatar_clip_path and Path(avatar_clip_path).exists():
                with st.spinner("Adding avatar presenter..."):
                    avatar_output = str(OUTPUT_DIR / "dynoad_with_avatar.mp4")
                    final_video_path = _overlay_avatar_ffmpeg(base_video_path=final_video_path, avatar_video_path=avatar_clip_path, output_path=avatar_output, position=avatar_position, scale_ratio=avatar_scale)

        st.session_state.generated_script = generated_script
        st.session_state.final_video_path = final_video_path
        st.session_state.voice_debug = voice_debug
        st.session_state.selected_styles = styles_used
        st.success("Ad generated successfully!")
        if styles_used:
            st.info("AI selected these scene styles: " + " | ".join(styles_used))
        if voice_debug:
            st.info(voice_debug)
        st.rerun()
    except Exception as e:
        st.exception(e)


# -------------------------------------------------
# Export & Share
# -------------------------------------------------
open_card("Export & Share")

if st.session_state.final_video_path and Path(st.session_state.final_video_path).exists():
    if st.session_state.voice_debug:
        st.caption(st.session_state.voice_debug)

    export_col1, export_col2, export_col3 = st.columns(3)
    with export_col1:
        with open(st.session_state.final_video_path, "rb") as f:
            st.download_button("⬇ Download Video", data=f, file_name=Path(st.session_state.final_video_path).name, mime="video/mp4", use_container_width=True)
    with export_col2:
        st.button("🔗 Share", use_container_width=True)
    with export_col3:
        st.button("✏️ Edit Video", use_container_width=True)
else:
    st.info("Generate an advertisement first to enable export options.")

close_card()
