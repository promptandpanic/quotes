"""
Entry point for the Instagram Quotes Bot.

Usage (GitHub Actions sets the THEME env var):
    python main.py

Local dry-run (saves image + video to output/, skips posting):
    DRY_RUN=true THEME=morning python main.py
    DRY_RUN=true python main.py   # auto-selects theme by UTC hour
"""
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # loads .env for local dev; no-op in GitHub Actions (secrets injected via env)

from src.config import THEMES
from src.db_manager import DBManager
from src.design_director import generate_brief
from src.github_uploader import GitHubUploader
from src.image_composer import compose
from src.image_generator import get_image
from src.image_judge import judge_image
from src.instagram_poster import build_caption, post_image, post_reel
from src.notifier import notify_failure, notify_success
from src.quote_generator import generate_quote
from src.video_creator import create_reel

MAX_DESIGN_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Set DRY_RUN=true to skip all posting and save outputs locally instead.
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Theme selection
# ---------------------------------------------------------------------------

def _select_theme() -> tuple[str, dict]:
    theme_key = os.environ.get("THEME", "").lower().strip()
    if theme_key and theme_key in THEMES:
        return theme_key, THEMES[theme_key]

    utc_hour = datetime.now(timezone.utc).hour
    closest = min(THEMES.items(), key=lambda kv: abs(kv[1]["utc_hour"] - utc_hour))
    logger.info(f"THEME not set — using closest match: {closest[0]} (UTC hour {utc_hour})")
    return closest[0], closest[1]


# ---------------------------------------------------------------------------
# Dry-run output saver
# ---------------------------------------------------------------------------

def _clean_output() -> None:
    """Remove old images and videos from the output directory before each run."""
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    removed = 0
    for f in out_dir.glob("*"):
        if f.suffix in (".jpg", ".jpeg", ".mp4", ".png"):
            f.unlink()
            removed += 1
    if removed:
        logger.info(f"Cleaned output/ ({removed} old file(s) removed)")


def _save_locally(image_bytes: bytes, video_bytes: bytes | None,
                  quote: dict, brief: dict, theme_key: str, caption: str) -> None:
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    img_path = out_dir / f"{theme_key}_{stamp}.jpg"
    img_path.write_bytes(image_bytes)
    logger.info(f"[DRY_RUN] Image saved → {img_path}")

    if video_bytes:
        vid_path = out_dir / f"{theme_key}_{stamp}.mp4"
        vid_path.write_bytes(video_bytes)
        logger.info(f"[DRY_RUN] Video saved → {vid_path}")

    logger.info(f"[DRY_RUN] Quote : \"{quote['text']}\"")
    ov = brief.get("overlay", {})
    logger.info(f"[DRY_RUN] font={brief.get('font')} size={brief.get('font_size')} "
                f"overlay={ov.get('type')} anim={brief.get('animation')} "
                f"zone={brief.get('text_zone')}")
    logger.info(f"[DRY_RUN] Highlight: \"{brief.get('highlight')}\"")
    logger.info(f"[DRY_RUN] Mood note: {brief.get('mood_note', '')}")

    # Print caption ready to copy-paste for manual upload
    print("\n" + "─" * 60)
    print("CAPTION (copy-paste for Instagram):")
    print("─" * 60)
    print(caption)
    print("─" * 60 + "\n")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run() -> bool:
    logger.info("=" * 55)
    logger.info("  Instagram Quotes Bot — starting")
    if DRY_RUN:
        logger.info("  [DRY_RUN mode — no posts will be made]")
    logger.info("=" * 55)
    _clean_output()

    # 1. Theme
    theme_key, theme_cfg = _select_theme()
    logger.info(f"Theme: {theme_cfg['name']}  ({theme_cfg['ist_label']})")

    # 2. Load DB — only quotes within the repeat window count as "used"
    db = DBManager()
    db.load()
    posted_hashes = db.active_hashes()
    logger.info(f"Repeat window: {__import__('src.config', fromlist=['REPEAT_WINDOW_DAYS']).REPEAT_WINDOW_DAYS} days  ({len(posted_hashes)} active hashes)")

    # 3. Pull recent topic hints and styles to prevent repetition
    recent_hints  = db.recent_topic_hints(days=90, max_hints=30)
    recent_styles = db.recent_styles(max_entries=20)
    if recent_hints:
        logger.info(f"Passing {len(recent_hints)} recent topic hints to avoid repetition")
    if recent_styles:
        logger.info(f"Passing {len(recent_styles)} recent style names to design director")

    # 4. Generate quote (all themes now use Gemini)
    logger.info("Generating quote with Gemini…")
    quote = generate_quote(theme_key, posted_hashes, recent_hints)
    src = quote.get("source", "?")
    author = quote.get("author", "")
    logger.info(f"Quote [{src}]: \"{quote['text'][:80]}…\"  — {author}")

    # 5–7. Creative direction → image generation → compose → judge (up to 2 attempts)
    best: dict | None = None  # {"image": bytes, "brief": dict, "raw": bytes, "score": int}

    for attempt in range(1, MAX_DESIGN_ATTEMPTS + 1):
        logger.info(f"Design attempt {attempt}/{MAX_DESIGN_ATTEMPTS}…")

        brief = generate_brief(quote, theme_key, recent_styles=recent_styles)

        logger.info("Generating background image…")
        image_bytes_raw = get_image(
            theme=theme_key,
            image_prompt=brief["image_prompt"],
            quote_text=quote["text"],
        )

        final_image = compose(image_bytes_raw, quote, brief)
        logger.info("✓ Static image composed")

        logger.info("Judging image quality…")
        verdict = judge_image(final_image, quote)
        score   = verdict.get("score", 0)

        if best is None or score > best["score"]:
            best = {"image": final_image, "brief": brief,
                    "raw": image_bytes_raw, "score": score}

        if verdict.get("accept"):
            logger.info(f"  ✓ Accepted (score {score}/10)")
            break
        logger.warning(
            f"  ✗ Rejected (score {score}/10)"
            + (f": {verdict['issues']}" if verdict.get("issues") else "")
            + (" — retrying" if attempt < MAX_DESIGN_ATTEMPTS else " — using best result")
        )

    if best is None:
        # Emergency fallback: gradient background + default brief, always posts
        logger.warning("All design attempts produced no image — using gradient fallback")
        from src.image_generator import _gradient_fallback
        from src.design_director import _DEFAULTS
        fallback_raw = _gradient_fallback(theme_key)
        fallback_brief = dict(_DEFAULTS.get(theme_key, _DEFAULTS["wisdom"]))
        # Ensure layout params are populated
        fallback_brief.setdefault("layout", "full_card")
        fallback_brief.setdefault("font_size", 76)
        fallback_brief.setdefault("text_zone", "center")
        fallback_brief.setdefault("animation", "fade")
        fallback_brief.setdefault("highlight", quote.get("highlight", ""))
        fallback_brief.setdefault("text_color", "#FFFFFF")
        fallback_brief.setdefault("highlight_color", "#FFD700")
        fallback_brief.setdefault("decoration", "none")
        fallback_brief.setdefault("overlay", {"type": "gradient_bottom", "opacity": 180, "color": "#000000"})
        fallback_image = compose(fallback_raw, quote, fallback_brief)
        best = {"image": fallback_image, "brief": fallback_brief,
                "raw": fallback_raw, "score": 0}

    final_image     = best["image"]
    brief           = best["brief"]
    image_bytes_raw = best["raw"]

    # 8. Animated Reel video
    logger.info("Creating animated Reel…")
    video_bytes = create_reel(image_bytes_raw, quote, brief, theme=theme_key)

    # --- DRY_RUN: save locally and exit ---
    if DRY_RUN:
        caption = build_caption(quote, theme_cfg)
        _save_locally(final_image, video_bytes, quote, brief, theme_key, caption)
        logger.info("✅ Dry-run complete. Check output/ directory.")
        return True

    # 9. Build caption
    caption = build_caption(quote, theme_cfg)
    post_id = None

    # 10. Try Reel first
    uploader = GitHubUploader()
    if video_bytes:
        logger.info(f"Uploading Reel ({len(video_bytes) // 1024} KB)…")
        video_url = uploader.upload(video_bytes)

        if video_url:
            thumb_url = uploader.upload(final_image, filename="thumb.jpg")
            import time
            time.sleep(5)  # let GitHub CDN propagate
            logger.info("Posting Reel to Instagram…")
            post_id = post_reel(video_url, caption, thumb_url=thumb_url)
            uploader.cleanup()
        else:
            logger.warning("Video URL unavailable — falling back to image post")

    # 11. Image fallback — upload image to GitHub Releases for a public URL
    if not post_id:
        logger.info("Posting static image to Instagram…")
        image_url = uploader.upload(final_image, filename="cover.jpg")
        if image_url:
            import time
            time.sleep(3)
            post_id = post_image(image_url, caption)
            uploader.cleanup()

    if not post_id:
        logger.error("❌ Instagram post failed")
        notify_failure(theme_cfg["name"], quote, "Instagram API did not return a post ID")
        return False

    # 12. Record and save — extract style name from image_prompt prefix e.g. "[ghibli_anime] ..."
    import re as _re
    _style_m = _re.match(r'\[(\w+)\]', brief.get("image_prompt", ""))
    style_used = _style_m.group(1) if _style_m else ""
    db.mark_posted(quote, theme_key, style=style_used)
    saved = db.save()
    if saved:
        logger.info("✓ Quote recorded in DB")
    else:
        logger.warning("DB save returned False — check token/repo settings")

    notify_success(theme_cfg["name"], quote, post_id)
    logger.info(f"✅ Done! Post ID: {post_id}")
    return True


if __name__ == "__main__":
    try:
        success = run()
    except Exception as exc:
        logger.exception("Unhandled exception in run()")
        try:
            theme_key, theme_cfg = _select_theme()
            notify_failure(theme_cfg["name"], None, f"Unhandled error: {exc}")
        except Exception:
            pass
        sys.exit(1)
    sys.exit(0 if success else 1)
