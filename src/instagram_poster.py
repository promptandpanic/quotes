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
# Carousel post
# ---------------------------------------------------------------------------

def post_carousel(image_urls: list[str], caption: str) -> str | None:
    """
    Create a 2-10 slide carousel from a list of publicly accessible image URLs.
    Creates each child container with is_carousel_item=true, then parents them
    into a CAROUSEL container.
    Returns post ID on success, None on failure.
    """
    if not (2 <= len(image_urls) <= 10):
        logger.error(f"Carousel needs 2-10 images, got {len(image_urls)}")
        return None

    token   = _access_token()
    user_id = _user_id()

    # Create each child container
    child_ids: list[str] = []
    for idx, url in enumerate(image_urls):
        logger.info(f"  Carousel child {idx+1}/{len(image_urls)}…")
        resp = requests.post(
            f"{GRAPH_BASE}/{user_id}/media",
            data={
                "image_url":        url,
                "is_carousel_item": "true",
                "access_token":     token,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Carousel child {idx+1} failed: {resp.status_code} {resp.text[:200]}")
            return None
        cid = resp.json().get("id")
        if not cid:
            logger.error(f"Carousel child {idx+1}: no id in response {resp.text[:200]}")
            return None
        child_ids.append(cid)

    # Create the parent carousel container
    logger.info("  Creating carousel parent container…")
    parent_payload = {
        "media_type":   "CAROUSEL",
        "children":     ",".join(child_ids),
        "caption":      caption,
        "location_id":  _LOCATION_ID,
        "access_token": token,
    }
    resp = requests.post(f"{GRAPH_BASE}/{user_id}/media", data=parent_payload, timeout=30)
    if resp.status_code != 200 and "location_id" in parent_payload:
        logger.warning(f"Carousel parent failed with location — retrying without: {resp.text[:200]}")
        parent_payload.pop("location_id")
        resp = requests.post(f"{GRAPH_BASE}/{user_id}/media", data=parent_payload, timeout=30)
    if resp.status_code != 200:
        logger.error(f"Carousel parent failed: {resp.status_code} {resp.text[:300]}")
        return None

    container_id = resp.json().get("id")
    logger.info(f"Carousel container: {container_id}. Polling…")

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

Then pick exactly 4 additional hashtags for deep Indian-audience reach. \
Meta's current algorithm prefers a small set of HIGHLY RELEVANT tags over \
large bundles — pick precision over volume. Mix these types:
1. One Indian Reels discovery tag (e.g. #ReelsIndia or #IndianReels — pick ONE, not both)
2. Two emotion / feeling tags — what an Indian 18-35 would search right after \
   feeling what this quote expresses. Specific, mid-size (500K–10M posts).
3. One niche community tag — smaller targeted community (100K–1M posts) for deep reach

Must not duplicate or semantically overlap the anchor tags above. \
No generic mega-tags (#love #life #india #quotes #motivation).
No branding or page-name tags.

Return ONLY valid JSON:
{{"hook": "<2-3 line caption>", "hashtags": ["tag1", "tag2", "tag3", "tag4"]}}
"""


def build_caption(quote: dict, theme_cfg: dict) -> str:
    text        = quote["text"].strip()
    _raw_author = quote.get("author", "").strip()
    _SKIP_AUTHOR = {"unknown", "anonymous", "original", "original thought", ""}
    author      = "" if _raw_author.lower() in _SKIP_AUTHOR else _raw_author
    author_line = f"— {author}\n\n" if author else ""
    theme_name  = theme_cfg.get("name", "Daily Wisdom")
    anchor_tags = theme_cfg.get("hashtags", [])

    try:
        import json
        import re
        from src.llm import generate_text

        prompt = _CAPTION_PROMPT.format(
            text=text[:300].replace('"', "'"),
            author=author,
            theme=theme_name,
            anchor_tags=", ".join(anchor_tags) if anchor_tags else "none",
        )
        raw = generate_text(prompt, role="caption")
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            hook = data.get("hook", "").strip()
            dynamic_tags = [f"#{t.lstrip('#')}" for t in data.get("hashtags", [])[:4]]
            # De-dupe case-insensitively against anchor tags before combining
            seen = {t.lower() for t in anchor_tags}
            dynamic_tags = [t for t in dynamic_tags if t.lower() not in seen]
            all_tags = anchor_tags + dynamic_tags
            all_tags = all_tags[:7]   # cap to 7 total — Meta prefers small focused sets
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
