"""
Generate background images.

Priority:
  1. Gemini Imagen 4 Fast  (native 9:16, ~768×1408, ~$0.02/image — primary)
  2. Gemini Flash Image     (free, square → center-cropped to 9:16)
  3. Pollinations.ai        (free fallback, variable quality)
  4. PIL gradient           (zero-dependency final fallback)

Model is controlled by GEMINI_IMAGE_MODEL in .env:
  imagen-4.0-fast-generate-001  ← default, best quality, ~$3.60/mo at 6 posts/day
  gemini-2.5-flash-image         ← free tier, lower quality

The code auto-detects which API to use based on the model name prefix.
"""
import hashlib
import io
import logging
import os
import random
from urllib.parse import quote as url_encode

import requests
from PIL import Image, ImageDraw, ImageFilter

from src.config import GEMINI_IMAGE_MODEL, IMAGE_HEIGHT, IMAGE_WIDTH

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gemini Imagen 4 Fast — native 9:16, high quality
# ---------------------------------------------------------------------------

def _imagen(prompt: str) -> bytes | None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_images(
            model=GEMINI_IMAGE_MODEL,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="9:16",
            ),
        )
        if response.generated_images:
            data = response.generated_images[0].image.image_bytes
            logger.info(f"✓ {GEMINI_IMAGE_MODEL} image ({len(data)//1024}KB)")
            return data
    except Exception as exc:
        logger.warning(f"Imagen generation failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Gemini Flash Image — free tier, returns 1024×1024 → center-crop to 9:16
# ---------------------------------------------------------------------------

def _gemini_flash_image(prompt: str) -> bytes | None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    flash_model = "gemini-2.5-flash-image"
    try:
        from google import genai
        from google.genai import types
        import base64

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=flash_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            ),
        )
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                data = part.inline_data.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                # Square image → center-crop to 9:16
                img = Image.open(io.BytesIO(data)).convert("RGB")
                w, h = img.size
                target_w = int(h * 9 / 16)
                if target_w < w:
                    left = (w - target_w) // 2
                    img = img.crop((left, 0, left + target_w, h))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                logger.info(f"✓ {flash_model} image (center-cropped to 9:16)")
                return buf.getvalue()
    except Exception as exc:
        logger.warning(f"Gemini Flash Image failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Pollinations.ai — free fallback
# ---------------------------------------------------------------------------

def _pollinations(prompt: str, quote_text: str = "") -> bytes | None:
    seed = int(hashlib.md5((quote_text or prompt).encode()).hexdigest()[:8], 16) % 999983
    try:
        encoded = url_encode(prompt[:500])
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width={IMAGE_WIDTH}&height={IMAGE_HEIGHT}"
            f"&model=flux-dev&seed={seed}&nologo=true&nofeed=true"
        )
        logger.info(f"Pollinations (flux-dev, seed={seed})…")
        resp = requests.get(url, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 50_000:
            logger.info(f"✓ Pollinations ({len(resp.content)//1024}KB)")
            return resp.content
        logger.warning(f"Pollinations: status={resp.status_code} size={len(resp.content)}")
    except Exception as exc:
        logger.warning(f"Pollinations failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# PIL gradient — zero-dependency final fallback
# ---------------------------------------------------------------------------

_GRADIENT_PALETTES = {
    "morning":     [(255, 120, 20),  (200, 50, 80),   (70, 15, 120)],
    "wisdom":      [(80, 40, 10),    (160, 90, 20),   (25, 10, 50)],
    "love":        [(210, 50, 90),   (170, 30, 130),  (55, 10, 80)],
    "mindfulness": [(10, 110, 110),  (25, 160, 140),  (10, 55, 85)],
    "goodnight":   [(10, 10, 65),    (20, 5, 110),    (5, 5, 30)],
    "latenight":   [(5, 5, 20),      (30, 10, 60),    (0, 0, 10)],
}


def _gradient_fallback(theme: str) -> bytes:
    palette = _GRADIENT_PALETTES.get(theme, _GRADIENT_PALETTES["wisdom"])
    img = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(IMAGE_HEIGHT):
        t = y / IMAGE_HEIGHT
        if t < 0.5:
            frac, c1, c2 = t * 2, palette[0], palette[1]
        else:
            frac, c1, c2 = (t - 0.5) * 2, palette[1], palette[2]
        r = int(c1[0] * (1 - frac) + c2[0] * frac)
        g = int(c1[1] * (1 - frac) + c2[1] * frac)
        b = int(c1[2] * (1 - frac) + c2[2] * frac)
        draw.line([(0, y), (IMAGE_WIDTH, y)], fill=(r, g, b))
    img = img.filter(ImageFilter.GaussianBlur(radius=3))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_image(theme: str, image_prompt: str, quote_text: str = "") -> bytes:
    """Return sharp 9:16 JPEG bytes for the background image."""
    import re as _re
    # Strip the style tag like "[indian_vector_girl]" — it's metadata for us,
    # not for the image model. Sending it causes Imagen to render it as text.
    clean_prompt = _re.sub(r'^\[[\w_]+\]\s*', '', image_prompt).strip()

    no_text = (
        " CRITICAL: absolutely no text, letters, numbers, words, labels, watermarks, "
        "signs, banners, or typography of any kind anywhere in the image. "
        "No photorealistic humans or portrait photography — use illustrations, paintings, "
        "flat vector art, ink sketches, or abstract art instead. "
        "Pure visual only — zero written characters."
    )
    if len(clean_prompt) > 100:
        prompt = clean_prompt.rstrip(" .") + "." + no_text
    else:
        prompt = clean_prompt + no_text + " Illustrated or painterly style, 9:16 portrait."

    # Route by model type
    if "imagen" in GEMINI_IMAGE_MODEL:
        logger.info(f"Image gen — {GEMINI_IMAGE_MODEL} (native 9:16)")
        img = _imagen(prompt)
        if img:
            return _ensure_size(img)
        # Fallback chain
        logger.info("Imagen failed — trying Gemini Flash Image…")
        img = _gemini_flash_image(prompt)
        if img:
            return _ensure_size(img)
    else:
        # gemini-2.5-flash-image or similar
        logger.info(f"Image gen — {GEMINI_IMAGE_MODEL}")
        img = _gemini_flash_image(prompt)
        if img:
            return _ensure_size(img)

    logger.info("Gemini image failed — trying Pollinations…")
    img = _pollinations(prompt, quote_text)
    if img:
        return _ensure_size(img)

    logger.info("Using gradient fallback")
    return _gradient_fallback(theme)


def _ensure_size(img_bytes: bytes) -> bytes:
    """Center-fill crop to exact 1080×1920."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    if img.size == (IMAGE_WIDTH, IMAGE_HEIGHT):
        return img_bytes
    img_ratio = img.width / img.height
    target_ratio = IMAGE_WIDTH / IMAGE_HEIGHT
    if img_ratio > target_ratio:
        new_h = IMAGE_HEIGHT
        new_w = int(new_h * img_ratio)
    else:
        new_w = IMAGE_WIDTH
        new_h = int(new_w / img_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - IMAGE_WIDTH) // 2
    top  = (new_h - IMAGE_HEIGHT) // 2
    img  = img.crop((left, top, left + IMAGE_WIDTH, top + IMAGE_HEIGHT))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()
