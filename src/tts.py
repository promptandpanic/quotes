"""
Text-to-speech narration with cascading provider fallback.

Provider priority is set by TTS_PROVIDERS (comma-separated list):
  elevenlabs  — ElevenLabs API (premium neural quality)
  edge        — Microsoft Edge TTS via edge-tts (disabled by default; set EDGE_TTS_ENABLED=true)
  none        — silent/music-only (no narration)

Default fallback: ElevenLabs → music only.  Edge-TTS is opt-in via EDGE_TTS_ENABLED secret.

Voice gender comes from the creative brief (AI-selected per quote sentiment).
Falls back to TTS_STATIC_VOICE_GENDER when the AI doesn't specify.

Returns MP3 bytes or None (silent/music-only).
"""
import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _providers() -> list[str]:
    from src.config import TTS_PROVIDERS
    return [p.strip().lower() for p in TTS_PROVIDERS.split(",") if p.strip()]


def _resolve_gender(voice_gender: str | None) -> str:
    from src.config import TTS_STATIC_VOICE_GENDER
    g = (voice_gender or TTS_STATIC_VOICE_GENDER).lower().strip()
    return g if g in ("male", "female") else TTS_STATIC_VOICE_GENDER


# ---------------------------------------------------------------------------
# ElevenLabs
# ---------------------------------------------------------------------------

def _resolve_elevenlabs_voice(gender: str, theme: str) -> str:
    from src.config import (
        ELEVENLABS_THEME_VOICES,
        ELEVENLABS_VOICE_FEMALE,
        ELEVENLABS_VOICE_MALE,
    )
    return (
        ELEVENLABS_THEME_VOICES.get(f"{theme}:{gender}")
        or (ELEVENLABS_VOICE_MALE if gender != "female" else ELEVENLABS_VOICE_FEMALE)
    )


def _elevenlabs_keys() -> list[str]:
    """Return list of API keys from ELEVENLABS_API_KEY (comma-separated for rotation)."""
    from src.config import ELEVENLABS_API_KEY
    return [k.strip() for k in ELEVENLABS_API_KEY.split(",") if k.strip()]


def _elevenlabs(text: str, gender: str, theme: str = "") -> bytes | None:
    from src.config import ELEVENLABS_MODEL
    keys = _elevenlabs_keys()
    if not keys:
        logger.debug("ElevenLabs: ELEVENLABS_API_KEY not set — skipping")
        return None

    voice_id = _resolve_elevenlabs_voice(gender, theme)
    import requests

    for i, key in enumerate(keys):
        key_label = f"key {i+1}/{len(keys)}"
        try:
            resp = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "model_id": ELEVENLABS_MODEL,
                    "voice_settings": {
                        "stability": 0.45,
                        "similarity_boost": 0.80,
                        "style": 0.35,
                        "use_speaker_boost": True,
                    },
                },
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info(
                    f"✓ TTS: ElevenLabs ({key_label}, {theme or 'default'}/{gender}, "
                    f"voice={voice_id[:8]}…)"
                )
                return resp.content
            if resp.status_code in (429, 402):
                logger.warning(f"ElevenLabs {key_label}: quota/limit reached — trying next key")
            elif resp.status_code == 401:
                logger.warning(f"ElevenLabs {key_label}: invalid key — trying next key")
            else:
                logger.warning(f"ElevenLabs {key_label}: HTTP {resp.status_code}: {resp.text[:150]}")
        except Exception as exc:
            logger.warning(f"ElevenLabs {key_label}: {exc}")

    logger.warning("ElevenLabs: all keys exhausted — falling through to next provider")
    return None


# ---------------------------------------------------------------------------
# edge-tts (Microsoft neural, free)
# ---------------------------------------------------------------------------

async def _edge_synth_async(text: str, voice: str) -> bytes:
    import edge_tts
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp = Path(f.name)
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(tmp))
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


def _edge_tts(text: str, gender: str) -> bytes | None:
    from src.config import EDGE_TTS_ENABLED, EDGE_TTS_VOICE_FEMALE, EDGE_TTS_VOICE_MALE
    if not EDGE_TTS_ENABLED:
        logger.debug("edge-tts: disabled (set EDGE_TTS_ENABLED=true to enable)")
        return None
    voice = EDGE_TTS_VOICE_MALE if gender != "female" else EDGE_TTS_VOICE_FEMALE
    try:
        import edge_tts  # noqa: F401 — confirm package installed
        data = asyncio.run(_edge_synth_async(text, voice))
        if data:
            logger.info(f"✓ TTS: edge-tts ({gender}, voice={voice})")
            return data
        return None
    except ImportError:
        logger.warning("edge-tts not installed — skipping")
        return None
    except RuntimeError as exc:
        # asyncio.run() fails if there's already a running event loop
        logger.warning(f"edge-tts event loop conflict: {exc}")
        return None
    except Exception as exc:
        logger.warning(f"edge-tts failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def synthesize(text: str, voice_gender: str | None = None, theme: str = "") -> bytes | None:
    """
    Synthesize speech for text.  Returns MP3 bytes or None (silent).

    voice_gender: "male" | "female" | None — falls back to TTS_STATIC_VOICE_GENDER.
    theme: used to select per-theme voices (e.g. "latenight", "morning").
    Providers are tried in TTS_PROVIDERS order; first success is returned.
    Reaching "none" in the list means intentionally silent.
    """
    if not text or not text.strip():
        return None

    gender = _resolve_gender(voice_gender)
    logger.info(f"TTS: synthesizing ({theme or 'default'}/{gender}, {len(text.split())} words)…")

    for provider in _providers():
        if provider == "elevenlabs":
            result = _elevenlabs(text, gender, theme=theme)
            if result is not None:
                return result
        elif provider == "edge":
            result = _edge_tts(text, gender)
            if result is not None:
                return result
        elif provider == "none":
            logger.info("TTS: silent (reached 'none' provider)")
            return None

    logger.info("TTS: all providers exhausted — silent")
    return None
