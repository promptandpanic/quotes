"""
Post to Instagram via the Graph API.
Supports both Reels (video) and single-image posts.
Falls back from Reel → image automatically.
"""
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

GRAPH_BASE        = "https://graph.facebook.com/v21.0"
MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL_SEC = 10


def _access_token() -> str:
    return os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")


def _user_id() -> str:
    return os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")


def _poll_media_status(container_id: str) -> bool:
    """Poll until media container is ready or timeout."""
    token = _access_token()
    for attempt in range(MAX_POLL_ATTEMPTS):
        resp = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=15,
        )
        if resp.status_code == 200:
            data   = resp.json()
            status = data.get("status_code", "")
            logger.info(f"  Media status [{attempt+1}]: {status}")
            if status == "FINISHED":
                return True
            if status == "ERROR":
                logger.error(f"Media processing error: {data.get('status')}")
                return False
        time.sleep(POLL_INTERVAL_SEC)
    logger.error("Media processing timed out")
    return False


def _publish(container_id: str) -> str | None:
    """Publish a ready media container and return the post ID."""
    resp = requests.post(
        f"{GRAPH_BASE}/{_user_id()}/media_publish",
        data={"creation_id": container_id, "access_token": _access_token()},
        timeout=15,
    )
    if resp.status_code == 200:
        post_id = resp.json().get("id")
        logger.info(f"✓ Published! Post ID: {post_id}")
        return post_id
    logger.error(f"Publish failed: {resp.status_code} {resp.text[:300]}")
    return None


# ---------------------------------------------------------------------------
# Reel
# ---------------------------------------------------------------------------

def post_reel(video_url: str, caption: str,
              thumb_url: str | None = None) -> str | None:
    """
    Create a Reel from a publicly accessible video URL.
    thumb_url: optional custom cover image URL.
    Returns the post ID on success, None on failure.
    """
    payload = {
        "media_type":   "REELS",
        "video_url":    video_url,
        "caption":      caption,
        "share_to_feed": "true",
        "access_token": _access_token(),
    }
    if thumb_url:
        payload["cover_url"] = thumb_url
        logger.info("Using custom thumbnail for Reel")

    logger.info("Creating Reel media container…")
    resp = requests.post(
        f"{GRAPH_BASE}/{_user_id()}/media",
        data=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Reel container creation failed: {resp.status_code} {resp.text[:300]}")
        return None

    container_id = resp.json().get("id")
    logger.info(f"Container created: {container_id}. Waiting for processing…")

    if not _poll_media_status(container_id):
        return None

    return _publish(container_id)


# ---------------------------------------------------------------------------
# Image post
# ---------------------------------------------------------------------------

def post_image(image_url: str, caption: str) -> str | None:
    """
    Post a static image to Instagram using a public URL.
    image_url must be a publicly accessible JPEG URL (e.g. GitHub Releases).
    Returns the post ID on success, None on failure.
    """
    logger.info("Creating image media container…")
    resp = requests.post(
        f"{GRAPH_BASE}/{_user_id()}/media",
        data={
            "image_url":    image_url,
            "caption":      caption,
            "access_token": _access_token(),
        },
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Image container failed: {resp.status_code} {resp.text[:300]}")
        return None

    container_id = resp.json().get("id")
    logger.info(f"Container: {container_id}. Polling…")

    if not _poll_media_status(container_id):
        return None

    return _publish(container_id)


# ---------------------------------------------------------------------------
# Caption builder
# ---------------------------------------------------------------------------

_CAPTION_PROMPT = """\
You write Instagram captions for @_daily_dose_of_wisdom__, \
an Indian page for emotionally intelligent youth aged 18-35.

Quote posted: "{text}"
Author: {author}
Theme: {theme}

Write a short, warm caption (2-3 lines max) that:
- Opens with a one-line hook that adds context or reflection — NOT the quote itself
- Invites the reader to save it, share it, or tag someone
- Ends with a soft call-to-action (e.g. "Save this for the days you need it.")
- Feels human — not corporate, not preachy

Then add 20 highly relevant hashtags for this specific quote (mix of broad + niche \
Indian Instagram tags). Use real tags that people actually search.

Return ONLY valid JSON:
{{"hook": "<2-3 line caption>", "hashtags": ["tag1", "tag2", ...]}}
"""


def build_caption(quote: dict, theme_cfg: dict) -> str:
    text       = quote["text"].strip()
    _raw_author = quote.get("author", "").strip()
    author      = "" if _raw_author.lower() in ("unknown", "anonymous", "") else _raw_author
    theme_name = theme_cfg.get("name", "Daily Wisdom")

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        try:
            import json
            import re
            from google import genai
            from src.config import GEMINI_TEXT_MODEL

            client = genai.Client(api_key=api_key)
            prompt = _CAPTION_PROMPT.format(
                text=text[:300].replace('"', "'"),
                author=author,
                theme=theme_name,
            )
            from google.genai import types as _types
            raw = client.models.generate_content(
                model=GEMINI_TEXT_MODEL,
                contents=prompt,
                config=_types.GenerateContentConfig(
                    automatic_function_calling=_types.AutomaticFunctionCallingConfig(disable=True),
                ),
            ).text
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                data = json.loads(m.group())
                hook = data.get("hook", "").strip()
                tags = data.get("hashtags", [])
                hashtag_str = " ".join(f"#{t.lstrip('#')}" for t in tags[:25])
                caption = (
                    f'"{text}"\n'
                    f"— {author}\n\n"
                    f"{hook}\n\n"
                    f"@_daily_dose_of_wisdom__\n\n"
                    f"{hashtag_str}"
                )
                logger.info(f"  ✓ AI caption generated ({len(tags)} hashtags)")
                return caption[:2200]
        except Exception as exc:
            logger.warning(f"Caption generation failed: {exc} — using static fallback")

    hashtags = " ".join(theme_cfg.get("hashtags", []))
    return (
        f'"{text}"\n'
        f"— {author}\n\n"
        f"✨ {theme_name} | @_daily_dose_of_wisdom__\n\n"
        f"{hashtags}"
    )[:2200]
