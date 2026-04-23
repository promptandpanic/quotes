"""
LLM abstraction with provider cascade — mirrors image_generator's pattern.

Two public functions:
  generate_text(prompt)                       — text-in, text-out
  generate_vision(prompt, image_bytes, mime)  — text + image in, text out

Providers are tried in order; first one that returns non-empty text wins.
If all fail, raises RuntimeError.

Env vars:
  TEXT_PROVIDER_ORDER     default "gemini,moonshot"
  VISION_PROVIDER_ORDER   default "gemini,moonshot"
  GEMINI_API_KEY
  GEMINI_TEXT_MODEL            (from config.py)
  GEMINI_TEXT_MODEL_FALLBACK   (from config.py)
  MOONSHOT_API_KEY
  MOONSHOT_BASE_URL        default "https://api.moonshot.ai/v1"
  MOONSHOT_TEXT_MODEL      default "moonshot-v1-32k"   (or falls back to MOONSHOT_MODEL)
  MOONSHOT_VISION_MODEL    default "moonshot-v1-128k-vision-preview"
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_TEXT_ORDER   = "gemini,moonshot"
_DEFAULT_VISION_ORDER = "gemini,moonshot"

# ---------------------------------------------------------------------------
# Usage tracking — lets main.py print an end-of-run summary of
# which model was actually used for each role.
# ---------------------------------------------------------------------------

_usage_log: list[dict] = []


def record_model_used(role: str, provider: str, model: str) -> None:
    """Register that `provider`/`model` produced the output for `role`.
    image_generator and other non-LLM providers call this directly."""
    _usage_log.append({"role": role, "provider": provider, "model": model})


def get_usage_summary() -> list[dict]:
    """Return the list of (role, provider, model) entries recorded this run."""
    return list(_usage_log)


def clear_usage() -> None:
    _usage_log.clear()


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------

def _gemini_text(prompt: str) -> tuple[str, str] | None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
        from src.config import GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK

        client = genai.Client(api_key=api_key)
        cfg = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for model in [GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK]:
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
                text = (resp.text or "").strip()
                if text:
                    return text, model
            except Exception as exc:
                logger.warning(f"Gemini text ({model}) failed: {exc}")
                if model == GEMINI_TEXT_MODEL_FALLBACK:
                    return None
    except Exception as exc:
        logger.warning(f"Gemini text provider error: {exc}")
    return None


def _gemini_vision(prompt: str, image_bytes: bytes, mime_type: str) -> tuple[str, str] | None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
        from src.config import GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK

        client = genai.Client(api_key=api_key)
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            types.Part(text=prompt),
        ]
        cfg = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for model in [GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK]:
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=cfg)
                text = (resp.text or "").strip()
                if text:
                    return text, model
            except Exception as exc:
                logger.warning(f"Gemini vision ({model}) failed: {exc}")
                if model == GEMINI_TEXT_MODEL_FALLBACK:
                    return None
    except Exception as exc:
        logger.warning(f"Gemini vision provider error: {exc}")
    return None


# ---------------------------------------------------------------------------
# Moonshot (Kimi) — OpenAI-compatible API
# ---------------------------------------------------------------------------

def _moonshot_client():
    api_key = os.environ.get("MOONSHOT_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("Moonshot: openai package not installed — run `pip install openai`")
        return None
    base_url = os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def _moonshot_text(prompt: str) -> tuple[str, str] | None:
    client = _moonshot_client()
    if client is None:
        return None
    model = os.environ.get("MOONSHOT_TEXT_MODEL") or os.environ.get("MOONSHOT_MODEL", "kimi-k2.6")
    try:
        # Kimi K2 models only accept temperature=1, so we omit it.
        # thinking: disabled — Kimi K2 otherwise does hidden reasoning that
        # turns a 1s call into a 15s call; safe/no-op on v1-* models.
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            timeout=60.0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        text = (resp.choices[0].message.content or "").strip()
        return (text, model) if text else None
    except Exception as exc:
        logger.warning(f"Moonshot text ({model}) failed: {exc}")
        return None


def _moonshot_vision(prompt: str, image_bytes: bytes, mime_type: str) -> tuple[str, str] | None:
    client = _moonshot_client()
    if client is None:
        return None
    model = os.environ.get("MOONSHOT_VISION_MODEL", "moonshot-v1-128k-vision-preview")
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text",      "text": prompt},
                ],
            }],
            temperature=0.3,
            timeout=60.0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        text = (resp.choices[0].message.content or "").strip()
        return (text, model) if text else None
    except Exception as exc:
        logger.warning(f"Moonshot vision ({model}) failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_TEXT_PROVIDERS = {
    "gemini":   _gemini_text,
    "moonshot": _moonshot_text,
}

_VISION_PROVIDERS = {
    "gemini":   _gemini_vision,
    "moonshot": _moonshot_vision,
}


def _order(env_var: str, default: str) -> list[str]:
    return [p.strip().lower() for p in os.environ.get(env_var, default).split(",") if p.strip()]


def generate_text(prompt: str, role: str = "text") -> str:
    """Try each provider in TEXT_PROVIDER_ORDER until one returns non-empty text.
    `role` is a short label ("quote_generation", "creative_brief", ...) used
    by the end-of-run usage summary."""
    for name in _order("TEXT_PROVIDER_ORDER", _DEFAULT_TEXT_ORDER):
        fn = _TEXT_PROVIDERS.get(name)
        if fn is None:
            logger.warning(f"Unknown text provider in TEXT_PROVIDER_ORDER: {name}")
            continue
        logger.info(f"  LLM text [{role}] → {name}")
        result = fn(prompt)
        if result:
            text, model = result
            record_model_used(role, name, model)
            return text
        logger.info(f"  {name} returned nothing — trying next provider")
    raise RuntimeError("All text providers failed — check API keys and TEXT_PROVIDER_ORDER")


def generate_vision(prompt: str, image_bytes: bytes,
                    mime_type: str = "image/jpeg",
                    role: str = "vision") -> str:
    """Try each provider in VISION_PROVIDER_ORDER until one returns non-empty text."""
    for name in _order("VISION_PROVIDER_ORDER", _DEFAULT_VISION_ORDER):
        fn = _VISION_PROVIDERS.get(name)
        if fn is None:
            logger.warning(f"Unknown vision provider in VISION_PROVIDER_ORDER: {name}")
            continue
        logger.info(f"  LLM vision [{role}] → {name}")
        result = fn(prompt, image_bytes, mime_type)
        if result:
            text, model = result
            record_model_used(role, name, model)
            return text
        logger.info(f"  {name} returned nothing — trying next provider")
    raise RuntimeError("All vision providers failed — check API keys and VISION_PROVIDER_ORDER")
