import streamlit as st
import os
import json
import asyncio
import edge_tts
import fal_client
import urllib.request
from dotenv import load_dotenv
from google import genai
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoFileClip, ImageClip, CompositeVideoClip

st.set_page_config(page_title="Dynoad Engine", layout="wide")

load_dotenv()
FAL_KEY = os.getenv("FAL_KEY")
if FAL_KEY:
    os.environ["FAL_KEY"] = FAL_KEY

class DynoadEngine:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            st.error("Gemini API Key missing in .env")
        self.client = genai.Client(api_key=api_key)

    def detect_and_script(self, image_path, target_product_name, product_description):
        """Analyzes product, verifies presence using description, and generates script + headline."""
        img = Image.open(image_path)
        
        prompt = f"""
        Analyze this image carefully. 
        1. Is there a '{target_product_name}' clearly visible in this image? 
        2. Does the item in the image visually match this specific description: "{product_description}"?
        
        Answer only with a JSON object.
        
        If YES to both (it is the product AND matches the description):
        {{
            "verified": true,
            "headline": "A punchy, viral 3-4 word title for the video (e.g. 'Must Have Kicks!')",
            "script": "Write a punchy, viral 10-second voiceover script to sell this {target_product_name} highlighting these features: {product_description}."
        }}
        
        If NO (either it's not the product, or it doesn't match the description):
        {{
            "verified": false,
            "error_message": "The image provided does not match the product '{target_product_name}' or the description '{product_description}'."
        }}
        
        Return ONLY the raw JSON. Do not use markdown formatting or code blocks.
        """
        
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, img]
        )
        
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        try:
            return json.loads(response_text)
        except Exception:
            return {"verified": False, "error_message": "AI Analysis failed to parse."}

    async def create_voice(self, text, output_path, voice_id):
        """Generates voiceover using the dynamically selected voice."""
        communicate = edge_tts.Communicate(text, voice_id)
        await communicate.save(output_path)
        return output_path

    def combine_assets(self, product_path, avatar_path, output_path, format_type):
        """Composites the scene. Images are already rotated by the UI before saving."""
        import rembg 
        
        if format_type == "Reel/Short (9:16)":
            canvas_w, canvas_h = 720, 1280
        else:
            canvas_w, canvas_h = 1280, 720

        canvas = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
        
        # Load pre-rotated product
        product = Image.open(product_path).convert("RGBA")

        prod_ratio = product.width / product.height
        new_prod_w = int(canvas_w * 0.8)
        new_prod_h = int(new_prod_w / prod_ratio)
        product = product.resize((new_prod_w, new_prod_h), Image.Resampling.LANCZOS)

        prod_x = (canvas_w - new_prod_w) // 2
        prod_y = (canvas_h - new_prod_h) // 2
        canvas.paste(product, (prod_x, prod_y), product)

        # Process pre-rotated avatar
        avatar_img = Image.open(avatar_path)
        avatar_no_bg = rembg.remove(avatar_img).convert("RGBA")
        
        av_h = int(canvas_h * 0.4)
        av_w = int(av_h * (avatar_no_bg.width / avatar_no_bg.height))
        avatar_resized = avatar_no_bg.resize((av_w, av_h), Image.Resampling.LANCZOS)

        canvas.paste(avatar_resized, (canvas_w - av_w, canvas_h - av_h), avatar_resized)
        
        canvas.save(output_path, "JPEG")
        return output_path

    def generate_video(self, audio_path, combined_image_path):
        image_url = fal_client.upload_file(combined_image_path)
        audio_url = fal_client.upload_file(audio_path)
        handler = fal_client.submit(
            "fal-ai/bytedance/omnihuman/v1.5", 
            arguments={"image_url": image_url, "audio_url": audio_url},
        )
        return handler.get()['video']['url']

    def overlay_headline(self, video_url, headline_text, output_path):
        """Downloads the AI video and overlays text cleanly using MoviePy."""
        raw_video_path = "output/raw_fal_video.mp4"
        urllib.request.urlretrieve(video_url, raw_video_path)

        video_clip = VideoFileClip(raw_video_path)
        w, h = video_clip.size

        txt_img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
        draw = ImageDraw.Draw(txt_img)
        try:
            font = ImageFont.truetype("arialbd.ttf", 70)
        except:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), headline_text, font=font)
        tw = bbox[2] - bbox[0]
        
        draw.text(((w - tw) // 2 + 3, 83), headline_text, fill="black", font=font)
        draw.text(((w - tw) // 2, 80), headline_text, fill="white", font=font)

        temp_txt_path = "output/temp_text_overlay.png"
        txt_img.save(temp_txt_path)

        txt_clip = ImageClip(temp_txt_path).with_duration(video_clip.duration)
        final_clip = CompositeVideoClip([video_clip, txt_clip])
        final_clip.write_videofile(output_path, fps=24, logger=None)

        return output_path

# ==========================================
# STREAMLIT UI
# ==========================================
st.title("🎬 Dynoad: AI Ad Generator")

# --- Initialize Session State Variables ---
if "engine" not in st.session_state:
    st.session_state.engine = DynoadEngine()
if "generated_script" not in st.session_state:
    st.session_state.generated_script = None
if "generated_headline" not in st.session_state:
    st.session_state.generated_headline = None
if "prod_rot" not in st.session_state:
    st.session_state.prod_rot = 0
if "av_rot" not in st.session_state:
    st.session_state.av_rot = 0

# --- SIDEBAR SETTINGS ---
st.sidebar.header("Video Settings")
video_format = st.sidebar.selectbox("Aspect Ratio", ["Reel/Short (9:16)", "Landscape (16:9)"])

# Added Voice Selection Dictionary
voice_options = {
    "🇺🇸 US Female (Jenny)": "en-US-JennyNeural",
    "🇺🇸 US Male (Guy)": "en-US-GuyNeural",
    "🇺🇸 US Female (Aria)": "en-US-AriaNeural",
    "🇺🇸 US Male (Christopher)": "en-US-ChristopherNeural",
    "🇬🇧 UK Female (Sonia)": "en-GB-SoniaNeural",
    "🇬🇧 UK Male (Ryan)": "en-GB-RyanNeural",
    "🇦🇺 AU Female (Natasha)": "en-AU-NatashaNeural",
    "🇦🇺 AU Male (William)": "en-AU-WilliamNeural"
}
st.sidebar.header("Audio Settings")
selected_voice_label = st.sidebar.selectbox("Select Voiceover", list(voice_options.keys()))
selected_voice_id = voice_options[selected_voice_label]

st.sidebar.header("Product Details")
target_name = st.sidebar.text_input("Product Name", placeholder="e.g., Nike Air Force 1")
product_description = st.sidebar.text_area("Product Description (For AI Verification)", placeholder="e.g., White high-top sneakers with a black swoosh logo.")

# --- MAIN UI ---
col1, col2 = st.columns(2)
with col1:
    product_file = st.file_uploader("Product Image", type=["jpg", "png", "jpeg"])
    if product_file:
        p_img = Image.open(product_file)
        if st.button("↻ Rotate Product"):
            # Rotate by -90 degrees and loop back to 0
            st.session_state.prod_rot = (st.session_state.prod_rot - 90) % 360
            st.rerun()
        if st.session_state.prod_rot != 0:
            p_img = p_img.rotate(st.session_state.prod_rot, expand=True)
        st.image(p_img, use_container_width=True)

with col2:
    avatar_file = st.file_uploader("Avatar Face", type=["jpg", "png", "jpeg"])
    if avatar_file:
        a_img = Image.open(avatar_file)
        if st.button("↻ Rotate Avatar"):
            st.session_state.av_rot = (st.session_state.av_rot - 90) % 360
            st.rerun()
        if st.session_state.av_rot != 0:
            a_img = a_img.rotate(st.session_state.av_rot, expand=True)
        st.image(a_img, use_container_width=True)

if product_file and avatar_file and target_name and product_description:
    if st.button("1. Verify Product & Write Script"):
        os.makedirs("output", exist_ok=True)
        
        # Save the fully rotated images directly to the hard drive so the AI and the video generator use the right angles
        p_img.convert("RGB").save("output/temp_product.jpg", "JPEG")
        a_img.convert("RGB").save("output/temp_avatar.jpg", "JPEG")
            
        with st.spinner(f"Verifying {target_name} against description..."):
            result = st.session_state.engine.detect_and_script("output/temp_product.jpg", target_name, product_description)
            
            if result.get("verified"):
                st.session_state.generated_script = result.get("script")
                st.session_state.generated_headline = result.get("headline", "Limited Offer!")
                st.success(f"✅ Verified! AI Hook Generated.")
                st.rerun()
            else:
                st.error(f"❌ Cannot generate ad: {result.get('error_message')}")
                st.session_state.generated_script = None

    if st.session_state.generated_script:
        final_headline = st.text_input("Edit AI Headline:", value=st.session_state.generated_headline)
        final_script = st.text_area("Edit AI Script:", value=st.session_state.generated_script, height=150)
        
        if st.button("2. Render AI Video"):
            audio_path = os.path.join("output", "temp_voice.mp3")
            combined_img_path = os.path.join("output", "combined_scene.jpg")
            final_ad_path = os.path.join("output", "FINAL_AD.mp4")
            
            with st.status("Rendering Final Ad...", expanded=True) as status:
                st.write("✂️ Compositing base scene...")
                # We removed the rotation argument here because the saved image is already rotated!
                st.session_state.engine.combine_assets(
                    "output/temp_product.jpg", 
                    "output/temp_avatar.jpg", 
                    combined_img_path,
                    video_format
                )
                
                st.write(f"🎙️ Synthesizing voiceover ({selected_voice_label})...")
                asyncio.run(st.session_state.engine.create_voice(final_script, audio_path, selected_voice_id))
                
                st.write("🎥 Animating avatar (ByteDance Omnihuman 1.5)...")
                try:
                    video_url = st.session_state.engine.generate_video(audio_path, combined_img_path)
                    
                    st.write("🔤 Adding crisp, clean headline overlay...")
                    st.session_state.engine.overlay_headline(video_url, final_headline, final_ad_path)
                    
                    status.update(label="✅ Ad Ready!", state="complete")
                    st.success("Video generated successfully!")
                    st.video(final_ad_path)
                except Exception as e:
                    st.error(f"Error during video processing: {e}")
                    status.update(label="❌ Generation Failed", state="error")