"""One-off: post a pre-generated 3-slide carousel to Instagram.

Reads slides from disk, uploads them to the GitHub Releases CDN, builds
the caption, then fires the carousel + records the quote hash to the DB
so it won't be re-generated.

Usage:
    python scripts/post_local_carousel.py <slide1.jpg> <slide2.jpg> <slide3.jpg>
"""
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

from src.config import THEMES
from src.db_manager import DBManager
from src.github_uploader import GitHubUploader
from src.instagram_poster import build_caption, post_carousel

# ---- Inputs: the quote + theme to post ----
QUOTE = {
    "text":      "One day you'll realise your father started asking your opinion because he ran out of people older than him to ask.",
    "author":    "Florence Welch",
    "highlight": "he ran out of people older than him to ask",
}
THEME_KEY = "latenight"

# Caption is generated live via build_caption so hashtags / hook stay in
# sync with the current provider cascade and config.
logger.info("Generating caption via build_caption…")
CAPTION = build_caption(QUOTE, THEMES[THEME_KEY])
print("\n" + "─" * 60)
print("CAPTION:")
print("─" * 60)
print(CAPTION)
print("─" * 60 + "\n")

if len(sys.argv) < 2:
    sys.exit("Usage: python scripts/post_local_carousel.py <slide1> [slide2 ...]")

slide_paths = [Path(p) for p in sys.argv[1:]]
for p in slide_paths:
    if not p.exists():
        sys.exit(f"Missing file: {p}")

uploader = GitHubUploader()
slide_urls: list[str] = []
stamp = str(int(time.time()))
for i, path in enumerate(slide_paths, 1):
    data = path.read_bytes()
    logger.info(f"Uploading slide {i} ({len(data)//1024}KB)…")
    url = uploader.upload(data, filename=f"carousel_{stamp}_slide_{i}.jpg")
    if not url:
        sys.exit(f"Upload of slide {i} failed")
    slide_urls.append(url)

logger.info("Waiting 5s for GitHub CDN to propagate…")
time.sleep(5)

logger.info("Posting carousel to Instagram…")
post_id = post_carousel(slide_urls, CAPTION)

if not post_id:
    uploader.cleanup()
    sys.exit("❌ Instagram post failed")

logger.info(f"✅ Posted! Post ID: {post_id}")
uploader.cleanup()

# Record to DB so the quote isn't re-posted
logger.info("Recording in DB…")
db = DBManager()
db.load()
db.mark_posted(QUOTE, THEME_KEY, style="carousel_drawer")
if db.save():
    logger.info("✓ DB updated")
else:
    logger.warning("DB save returned False — check token/repo settings")

logger.info(f"✅ Done — https://www.instagram.com/p/{post_id}/")
