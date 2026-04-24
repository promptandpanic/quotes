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

from src.carousel_composer import compose_carousel
from src.config import THEMES
from src.db_manager import DBManager
from src.design_director import generate_brief
from src.github_uploader import GitHubUploader
from src.image_composer import compose
from src.image_generator import get_image
from src.image_judge import judge_image
from src.instagram_poster import build_caption, post_carousel, post_image, post_reel
from src.notifier import notify_failure, notify_success
from src.quote_generator import generate_quote
from src.video_creator import create_reel

MAX_DESIGN_ATTEMPTS = 3


def _log_model_summary() -> None:
    """Print which model/provider handled each role during this run."""
    from src.llm import get_usage_summary
    entries = get_usage_summary()
    if not entries:
        return
    logger.info("=" * 55)
    logger.info("  Model usage summary")
    logger.info("-" * 55)
    for e in entries:
        logger.info(f"  {e['role']:20s} ← {e['provider']:12s} {e['model']}")
    logger.info("=" * 55)

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
        # Explicit THEME overrides the enabled flag — supports manual/test runs.
        return theme_key, THEMES[theme_key]

    utc_hour = datetime.now(timezone.utc).hour
    # Only auto-match among enabled themes so disabled slots don't get picked
    # when the UTC-hour is closest to their scheduled time.
    enabled_themes = {k: v for k, v in THEMES.items() if v.get("enabled", True)}
    if not enabled_themes:
        enabled_themes = THEMES
    closest = min(enabled_themes.items(),
                  key=lambda kv: abs(kv[1]["utc_hour"] - utc_hour))
    logger.info(f"THEME not set — using closest enabled match: {closest[0]} (UTC hour {utc_hour})")
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
                  quote: dict, brief: dict, theme_key: str, caption: str,
                  carousel_slides: list[bytes] | None = None) -> None:
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

    if carousel_slides:
        for i, data in enumerate(carousel_slides, 1):
            p = out_dir / f"{theme_key}_{stamp}_slide{i}.jpg"
            p.write_bytes(data)
            logger.info(f"[DRY_RUN] Carousel slide {i} saved → {p}")

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

    # Skip disabled themes when fired automatically (no explicit THEME env var).
    # Lets you keep cron-job.org triggers in place while the theme is paused.
    if not theme_cfg.get("enabled", True) and not os.environ.get("THEME", "").strip():
        logger.info(f"Theme '{theme_key}' is disabled (config.py) — exiting without posting.")
        return True

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

    # 4. Generate quote (provider picked by TEXT_PROVIDER_ORDER)
    logger.info("Generating quote…")
    quote = generate_quote(theme_key, posted_hashes, recent_hints)
    src = quote.get("source", "?")
    author = quote.get("author", "")
    logger.info(f"Quote [{src}]: \"{quote['text'][:80]}…\"  — {author}")

    # 5–7. Creative direction → image generation → compose → judge (up to 2 attempts)
    best: dict | None = None  # {"image": bytes, "brief": dict, "raw": bytes, "score": int, "hard_gate_failure": bool, "accepted": bool}

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
        score    = verdict.get("score", 0)
        accepted = verdict.get("accept", False)
        hard_gate = verdict.get("hard_gate_failure", False)

        candidate = {"image": final_image, "brief": brief, "raw": image_bytes_raw,
                     "score": score, "hard_gate_failure": hard_gate, "accepted": accepted}

        # "Best" preference: any non-hard-gate image beats any hard-gate image,
        # regardless of score. Within the same hard-gate category, higher score wins.
        if best is None:
            best = candidate
        elif best["hard_gate_failure"] and not hard_gate:
            best = candidate
        elif best["hard_gate_failure"] == hard_gate and score > best["score"]:
            best = candidate

        if accepted:
            logger.info(f"  ✓ Accepted (score {score}/10)")
            break
        logger.warning(
            f"  ✗ Rejected (score {score}/10)"
            + (f": {verdict['issues']}" if verdict.get("issues") else "")
            + (" — retrying" if attempt < MAX_DESIGN_ATTEMPTS else " — using best result")
        )

    # Enforce hard gate across retries: if every attempt violated a hard gate
    # (signature, text artifact, corrupted text), never publish one of those —
    # substitute the theme's static image or a gradient instead.
    if best is not None and not best.get("accepted") and best.get("hard_gate_failure"):
        logger.warning("All attempts failed hard gates — substituting static theme image")
        from src.image_generator import _static_image, _gradient_fallback
        static_raw = _static_image(theme_key) or _gradient_fallback(theme_key)
        static_image = compose(static_raw, quote, best["brief"])
        best = {"image": static_image, "brief": best["brief"], "raw": static_raw,
                "score": best["score"], "hard_gate_failure": False, "accepted": True}

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
                "raw": fallback_raw, "score": 0,
                "hard_gate_failure": False, "accepted": True}

    final_image     = best["image"]
    brief           = best["brief"]
    image_bytes_raw = best["raw"]

    # Resolve post format. Precedence: FORMAT env var > theme "format" key > "reel".
    # Values: "reel" | "carousel" | "image".
    post_format = (os.environ.get("FORMAT") or theme_cfg.get("format") or "reel").lower()
    if post_format not in {"reel", "carousel", "image"}:
        logger.warning(f"Unknown FORMAT={post_format} — defaulting to reel")
        post_format = "reel"
    logger.info(f"Post format: {post_format}")

    # 8. Compose carousel slides (if selected) — animated Reel (if reel)
    carousel_slides: list[bytes] | None = None
    video_bytes = None
    if post_format == "carousel":
        logger.info("Composing 3-slide carousel…")
        carousel_slides = compose_carousel(image_bytes_raw, quote, brief)
        logger.info(f"✓ Carousel: {len(carousel_slides)} slides, "
                    f"sizes={[len(s)//1024 for s in carousel_slides]}KB")
    elif theme_cfg.get("video", True) and post_format == "reel":
        logger.info("Creating animated Reel…")
        video_bytes = create_reel(image_bytes_raw, quote, brief, theme=theme_key)
    else:
        logger.info("Video skipped (image-only theme or FORMAT=image)")

    # --- DRY_RUN: save locally and exit ---
    if DRY_RUN:
        caption = build_caption(quote, theme_cfg)
        _save_locally(final_image, video_bytes, quote, brief, theme_key, caption,
                      carousel_slides=carousel_slides)
        _log_model_summary()
        logger.info("✅ Dry-run complete. Check output/ directory.")
        return True

    # 9. Build caption
    caption = build_caption(quote, theme_cfg)
    post_id = None

    uploader = GitHubUploader()

    # 10a. Carousel path
    if carousel_slides:
        logger.info(f"Uploading {len(carousel_slides)} carousel slides…")
        slide_urls: list[str] = []
        for i, data in enumerate(carousel_slides, 1):
            url = uploader.upload(data, filename=f"slide_{i}.jpg")
            if not url:
                logger.error(f"Slide {i} upload failed — aborting carousel")
                slide_urls = []
                break
            slide_urls.append(url)
        if slide_urls:
            import time
            time.sleep(5)  # let GitHub CDN propagate
            logger.info("Posting carousel to Instagram…")
            post_id = post_carousel(slide_urls, caption)
            uploader.cleanup()

    # 10b. Reel path
    if not post_id and video_bytes:
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
    _log_model_summary()
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
