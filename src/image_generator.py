"""
Generate background images.

Priority (default — override via IMAGE_PROVIDER_ORDER env var):
  1. HuggingFace      (FLUX.1-schnell, free tier, excellent quality)
  2. Leonardo AI      (free tier ~150 tokens/day, or paid models)
  3. Gemini Imagen    (paid, excellent quality)
  4. Gemini Flash     (free Gemini tier)
  5. Pollinations.ai  (free, no key needed)
  6. Static images    (assets/static/{theme}.jpg — pre-generated, always works)
  7. PIL gradient     (zero-dependency absolute last resort)

GitHub Variables (Settings → Secrets and variables → Actions → Variables):
  IMAGE_PROVIDER_ORDER  e.g. "huggingface,leonardo,imagen,gemini,pollinations"
  LEONARDO_MODEL_ID     UUID or "flux-pro-2.0" (default: Leonardo Phoenix free)
  HF_MODEL_ID           HuggingFace model ID (default: black-forest-labs/FLUX.1-schnell)
  GEMINI_IMAGE_MODEL    Imagen model name

GitHub Secrets:
  HF_API_KEY, LEONARDO_API_KEY, GEMINI_API_KEY
"""
import hashlib
import io
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote as url_encode

import requests
from PIL import Image, ImageDraw, ImageFilter

from src.config import GEMINI_IMAGE_MODEL, IMAGE_HEIGHT, IMAGE_WIDTH

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent / "assets" / "static"

_NO_TEXT = (
    " CRITICAL: absolutely no text, letters, numbers, words, labels, watermarks, "
    "signs, banners, or typography of any kind anywhere in the image. "
    "No photorealistic humans or portrait photography — use illustrations, paintings, "
    "flat vector art, ink sketches, or abstract art instead. "
    "Pure visual only — zero written characters."
)


# ---------------------------------------------------------------------------
# 1. HuggingFace — FLUX.1-schnell, free tier, excellent quality
# ---------------------------------------------------------------------------

_HF_MODEL_ID = os.environ.get("HF_MODEL_ID", "black-forest-labs/FLUX.1-schnell")
_HF_ROUTER   = "https://router.huggingface.co/hf-inference/models"


def _huggingface(prompt: str) -> bytes | None:
    api_key = os.environ.get("HF_API_KEY", "")
    if not api_key:
        return None
    url     = f"{_HF_ROUTER}/{_HF_MODEL_ID}"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "inputs": prompt[:1500],
        "parameters": {
            "width":               768,
            "height":              1344,   # 9:16
            "num_inference_steps": 4,
            "guidance_scale":      0.0,
        },
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code == 503:
            try:
                wait = float(resp.json().get("estimated_time", 20)) + 2
            except Exception:
                wait = 22
            logger.info(f"HuggingFace model loading — waiting {wait:.0f}s…")
            time.sleep(wait)
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 10_000:
            logger.info(f"✓ HuggingFace ({_HF_MODEL_ID}) image ({len(resp.content)//1024}KB)")
            return resp.content
        logger.warning(f"HuggingFace: {resp.status_code} {resp.text[:150]}")
    except Exception as exc:
        logger.warning(f"HuggingFace failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# 2. Leonardo AI — free tier, high quality, 9:16 native
# ---------------------------------------------------------------------------

# Model ID: set LEONARDO_MODEL_ID in .env
#   Leonardo Phoenix (free):  6bef9f1b-29cb-40c7-b9df-32b51c1f67d3  (v1 API, UUID)
#   Flux Dev (free tier):     b2614463-296c-462a-9586-aafdb8f00e36  (v1 API, UUID)
#   Flux 2 Pro (paid, $):     flux-pro-2.0                           (v2 API, string)
_LEONARDO_MODEL_ID      = os.environ.get("LEONARDO_MODEL_ID", "6bef9f1b-29cb-40c7-b9df-32b51c1f67d3")
_LEONARDO_FREE_MODEL_ID = "6bef9f1b-29cb-40c7-b9df-32b51c1f67d3"  # Leonardo Phoenix — always free
_LEONARDO_V1_URL   = "https://cloud.leonardo.ai/api/rest/v1"
_LEONARDO_V2_URL   = "https://cloud.leonardo.ai/api/rest/v2"

# Models confirmed to use v2 API (string IDs, native aspect_ratio: "9:16")
# UUID-based models (Phoenix, Flux Dev) use v1 API with explicit width/height
_LEONARDO_V2_MODELS = {"flux-pro-2.0", "flux-pro-ultra"}


def _leonardo(prompt: str, model_id: str | None = None) -> bytes | None:
    api_key = os.environ.get("LEONARDO_API_KEY", "")
    if not api_key:
        return None

    model_id = model_id or _LEONARDO_MODEL_ID
    is_v2 = model_id in _LEONARDO_V2_MODELS
    base_url = _LEONARDO_V2_URL if is_v2 else _LEONARDO_V1_URL

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "accept":        "application/json",
    }
    try:
        # Step 1: create generation
        if is_v2:
            # v2 API: model at root, all generation params nested under "parameters"
            payload = {
                "public": False,
                "model":  model_id,
                "parameters": {
                    "prompt":   prompt[:1500],
                    "quantity": 1,
                    "width":    810,    # 810×1440 = exact 9:16, max quality
                    "height":   1440,
                },
            }
        else:
            payload = {
                "prompt":          prompt[:1500],
                "modelId":         model_id,
                "width":           832,
                "height":          1472,   # ~9:16
                "num_images":      1,
                "guidance_scale":  7,
                "negative_prompt": (
                    "text, letters, words, watermark, logo, signature, caption, label, "
                    "typography, graffiti, banner, photorealistic human, portrait photo"
                ),
            }

        r = requests.post(f"{base_url}/generations",
                          headers=headers, json=payload, timeout=30)
        if r.status_code == 402:
            logger.warning("Leonardo: daily token quota exhausted")
            return None
        if r.status_code != 200:
            logger.warning(f"Leonardo: API error {r.status_code} {r.text[:120]}")
            return None

        body = r.json()
        # v1 wraps under "sdGenerationJob", v2 wraps under "generate"
        job = body.get("sdGenerationJob") or body.get("generate") or {}
        gen_id = job.get("generationId")
        if not gen_id:
            logger.warning(f"Leonardo: could not find generationId in response: {body}")
            return None
        if is_v2 and job.get("cost"):
            logger.info(f"Leonardo Flux 2 Pro cost: ${job['cost'].get('amount', '?')}")
        logger.info(f"Leonardo generation started ({gen_id[:8]}…)")

        # Step 2: poll until complete (max 90 s — v2 models are slower)
        poll_url = f"{_LEONARDO_V1_URL}/generations/{gen_id}"
        for _ in range(45):
            time.sleep(2)
            poll = requests.get(poll_url, headers=headers, timeout=15)
            gen  = poll.json().get("generations_by_pk", {})
            status = gen.get("status", "")
            if status == "COMPLETE":
                images = gen.get("generated_images", [])
                if images:
                    img_url = images[0]["url"]
                    data = requests.get(img_url, timeout=30).content
                    logger.info(f"✓ Leonardo ({model_id}) image ({len(data)//1024}KB)")
                    return data
                logger.warning("Leonardo: COMPLETE but no images returned")
                return None
            if status == "FAILED":
                logger.warning("Leonardo: generation FAILED")
                return None

        logger.warning("Leonardo: timed out waiting for generation")
    except Exception as exc:
        logger.warning(f"Leonardo failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# 2. Gemini Imagen — paid, native 9:16
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
# 3. Gemini Flash Image — free tier, square → center-crop to 9:16
# ---------------------------------------------------------------------------

_GEMINI_IMAGE_FALLBACK = os.environ.get("GEMINI_IMAGE_MODEL_FALLBACK", "gemini-3.1-flash-image-preview")


def _gemini_flash_image(prompt: str) -> bytes | None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
        import base64

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_GEMINI_IMAGE_FALLBACK,
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
                img = Image.open(io.BytesIO(data)).convert("RGB")
                w, h = img.size
                target_w = int(h * 9 / 16)
                if target_w < w:
                    left = (w - target_w) // 2
                    img = img.crop((left, 0, left + target_w, h))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                logger.info(f"✓ {_GEMINI_IMAGE_FALLBACK} image (center-cropped to 9:16)")
                return buf.getvalue()
    except Exception as exc:
        logger.warning(f"Gemini Flash Image failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# 4. Pollinations.ai — free, no key needed
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
# 5. Static pre-generated images — assets/static/{theme}.jpg
# ---------------------------------------------------------------------------

def _static_image(theme: str) -> bytes | None:
    """
    Return a pre-generated static background.
    Tries theme-specific first (e.g. assets/static/latenight.jpg),
    then any available generic image in the folder.
    """
    if not _STATIC_DIR.exists():
        return None

    candidates = []
    for ext in (".jpg", ".jpeg", ".png"):
        p = _STATIC_DIR / f"{theme}{ext}"
        if p.exists():
            candidates.append(p)

    # Any other static image as last resort
    for p in sorted(_STATIC_DIR.glob("*.jpg")) + sorted(_STATIC_DIR.glob("*.jpeg")):
        if p not in candidates:
            candidates.append(p)

    for p in candidates:
        try:
            data = p.read_bytes()
            logger.info(f"✓ Static fallback image: {p.name}")
            return data
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# 6. PIL gradient — absolute last resort, zero dependencies
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
    """Return sharp 9:16 JPEG bytes. Tries each source in priority order.

    Order controlled by IMAGE_PROVIDER_ORDER env var (comma-separated):
      leonardo, imagen, gemini, pollinations
    Default: leonardo,imagen,gemini,pollinations
    Example: IMAGE_PROVIDER_ORDER=imagen,gemini,pollinations  (skip Leonardo)
    """
    import re as _re
    clean_prompt = _re.sub(r'^\[[\w_]+\]\s*', '', image_prompt).strip()

    if len(clean_prompt) > 100:
        prompt = clean_prompt.rstrip(" .") + "." + _NO_TEXT
    else:
        prompt = clean_prompt + _NO_TEXT + " Illustrated or painterly style, 9:16 portrait."

    order = [
        p.strip().lower()
        for p in os.environ.get("IMAGE_PROVIDER_ORDER", "huggingface,leonardo,imagen,gemini,pollinations").split(",")
        if p.strip()
    ]

    for provider in order:
        if provider == "huggingface" and os.environ.get("HF_API_KEY"):
            logger.info(f"Image gen — HuggingFace ({_HF_MODEL_ID})")
            img = _huggingface(prompt)
            if img:
                return _ensure_size(img)
            logger.info("HuggingFace failed — next provider…")

        elif provider == "leonardo" and os.environ.get("LEONARDO_API_KEY"):
            logger.info(f"Image gen — Leonardo ({_LEONARDO_MODEL_ID})")
            img = _leonardo(prompt)
            if img:
                return _ensure_size(img)
            if _LEONARDO_MODEL_ID != _LEONARDO_FREE_MODEL_ID:
                logger.info(f"Leonardo {_LEONARDO_MODEL_ID} failed — retrying with free Phoenix…")
                img = _leonardo(prompt, model_id=_LEONARDO_FREE_MODEL_ID)
                if img:
                    return _ensure_size(img)
            logger.info("Leonardo failed — next provider…")

        elif provider == "imagen" and "imagen" in GEMINI_IMAGE_MODEL:
            logger.info(f"Image gen — {GEMINI_IMAGE_MODEL}")
            img = _imagen(prompt)
            if img:
                return _ensure_size(img)
            logger.info(f"Imagen failed — next provider…")

        elif provider == "gemini":
            logger.info(f"Image gen — {_GEMINI_IMAGE_FALLBACK}")
            img = _gemini_flash_image(prompt)
            if img:
                return _ensure_size(img)
            logger.info("Gemini image failed — next provider…")

        elif provider == "pollinations":
            logger.info("Image gen — Pollinations")
            img = _pollinations(prompt, quote_text)
            if img:
                return _ensure_size(img)
            logger.info("Pollinations failed — next provider…")

    # 5. Static pre-generated images
    logger.info("Pollinations failed — trying static image bank…")
    img = _static_image(theme)
    if img:
        return _ensure_size(img)

    # 6. PIL gradient (always works)
    logger.info("All image sources failed — using PIL gradient")
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
