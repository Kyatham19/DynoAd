from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def generate_voiceover(
    text: str,
    out_path: str,
    voice_id: Optional[str] = None,
    model_id: str = "eleven_flash_v2_5",
) -> str:
    """
    Generate voiceover using ElevenLabs and save it as mp3.
    Returns the saved file path.
    """
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("Voice text is empty.")

    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not found in .env")

    if not voice_id:
        voice_id = "JBFqnCBsd6RMkjVDRZzb"

    try:
        from elevenlabs.client import ElevenLabs
    except Exception as e:
        raise RuntimeError(
            f"ElevenLabs SDK import failed: {e}. Run: pip install elevenlabs"
        ) from e

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if out_file.exists():
        out_file.unlink()

    try:
        client = ElevenLabs(api_key=api_key)
        audio_stream = client.text_to_speech.convert(
            text=clean_text,
            voice_id=voice_id,
            model_id=model_id,
            output_format="mp3_44100_128",
        )
    except Exception as e:
        raise RuntimeError(f"ElevenLabs generation failed: {e}") from e

    bytes_written = 0
    try:
        with open(out_file, "wb") as f:
            if isinstance(audio_stream, (bytes, bytearray)):
                f.write(audio_stream)
                bytes_written += len(audio_stream)
            else:
                for chunk in audio_stream:
                    if not chunk:
                        continue
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    f.write(chunk)
                    bytes_written += len(chunk)
    except Exception as e:
        raise RuntimeError(f"Failed to save generated audio: {e}") from e

    if bytes_written == 0 or not out_file.exists() or out_file.stat().st_size == 0:
        raise RuntimeError("Generated audio file is empty.")

    return str(out_file)