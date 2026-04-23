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

# Bhubaneswar, Odisha — Facebook Place ID
_LOCATION_ID = "108645072500373"


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
    """Publish a ready media container and return the post ID.

    Retries up to 3 times with exponential backoff on network timeouts and
    connection errors, as recommended by Meta for transient API failures.
    """
    url  = f"{GRAPH_BASE}/{_user_id()}/media_publish"
    data = {"creation_id": container_id, "access_token": _access_token()}

    for attempt in range(3):
        try:
            resp = requests.post(url, data=data, timeout=60)
            if resp.status_code == 200:
                post_id = resp.json().get("id")
                logger.info(f"✓ Published! Post ID: {post_id}")
                return post_id
            logger.error(f"Publish failed: {resp.status_code} {resp.text[:300]}")
            return None
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as exc:
            wait = 10 * (2 ** attempt)  # 10s → 20s → 40s
            if attempt < 2:
                logger.warning(f"Publish attempt {attempt + 1} failed ({exc}) — retrying in {wait}s…")
                time.sleep(wait)
            else:
                logger.error(f"Publish failed after 3 attempts: {exc}")
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
        "media_type":    "REELS",
        "video_url":     video_url,
        "caption":       caption,
        "share_to_feed": "true",
        "location_id":   _LOCATION_ID,
        "access_token":  _access_token(),
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
    if resp.status_code != 200 and "location_id" in payload:
        logger.warning(f"Reel container failed with location — retrying without: {resp.text[:200]}")
        payload.pop("location_id")
        resp = requests.post(f"{GRAPH_BASE}/{_user_id()}/media", data=payload, timeout=30)
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
    img_payload = {
        "image_url":   image_url,
        "caption":     caption,
        "location_id": _LOCATION_ID,
        "access_token": _access_token(),
    }
    resp = requests.post(f"{GRAPH_BASE}/{_user_id()}/media", data=img_payload, timeout=30)
    if resp.status_code != 200 and "location_id" in img_payload:
        logger.warning(f"Image container failed with location — retrying without: {resp.text[:200]}")
        img_payload.pop("location_id")
        resp = requests.post(f"{GRAPH_BASE}/{_user_id()}/media", data=img_payload, timeout=30)
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
an Indian Reels page for emotionally intelligent youth aged 18-35.

Quote posted: "{text}"
Author: {author}
Theme: {theme}

Already using these hashtags (do NOT repeat or overlap with these):
{anchor_tags}

Write a short, warm caption (2-3 lines max) that:
- Opens with a one-line hook that adds context or reflection — NOT the quote itself
- Invites the reader to save it, share it, or tag someone
- Ends with a soft call-to-action (e.g. "Save this for the days you need it.")
- Feels human — not corporate, not preachy

Then pick exactly 18 additional hashtags for maximum Indian Reels reach. \
Mix these four types — do NOT include any branding or page-name tags:
1. Indian Reels discovery (4 tags): e.g. #ReelsIndia #IndianReels #ReelItFeelIt #IndiaReels
2. Emotion/feeling (6 tags): what someone in India searches RIGHT AFTER feeling what this quote expresses — specific, mid-size (500K–10M posts)
3. Topic/theme (5 tags): the subject matter — relationships, self-growth, healing, etc.
4. Niche community (3 tags): smaller targeted communities (100K–1M posts) for deep reach

Must not duplicate or semantically overlap the anchor tags above. \
No generic mega-tags (#love #life #india #quotes #motivation alone).

Return ONLY valid JSON:
{{"hook": "<2-3 line caption>", "hashtags": ["tag1", "tag2", "...18 total"]}}
"""


def build_caption(quote: dict, theme_cfg: dict) -> str:
    text        = quote["text"].strip()
    _raw_author = quote.get("author", "").strip()
    _SKIP_AUTHOR = {"unknown", "anonymous", "original", "original thought", ""}
    author      = "" if _raw_author.lower() in _SKIP_AUTHOR else _raw_author
    author_line = f"— {author}\n\n" if author else ""
    theme_name  = theme_cfg.get("name", "Daily Wisdom")
    anchor_tags = theme_cfg.get("hashtags", [])

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
                anchor_tags=", ".join(anchor_tags) if anchor_tags else "none",
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
                dynamic_tags = [f"#{t.lstrip('#')}" for t in data.get("hashtags", [])[:18]]
                all_tags = anchor_tags + dynamic_tags
                # Instagram cap: 30 hashtags
                all_tags = all_tags[:30]
                hashtag_str = " ".join(all_tags)
                caption = (
                    f'"{text}"\n'
                    f"{author_line}"
                    f"{hook}\n\n"
                    f"@_daily_dose_of_wisdom__\n\n"
                    f"{hashtag_str}"
                )
                logger.info(f"  ✓ AI caption generated (anchors: {len(anchor_tags)}, dynamic: {len(dynamic_tags)})")
                return caption[:2200]
        except Exception as exc:
            logger.warning(f"Caption generation failed: {exc} — using static fallback")

    hashtag_str = " ".join(anchor_tags)
    return (
        f'"{text}"\n'
        f"{author_line}"
        f"✨ {theme_name} | @_daily_dose_of_wisdom__\n\n"
        f"{hashtag_str}"
    )[:2200]
