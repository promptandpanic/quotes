#!/usr/bin/env python3
"""
Generate 7 theme fallback images (assets/static/{theme}.jpg) using HuggingFace FLUX.1-schnell.
Uses the full style description from styles.yml verbatim as the image prompt.

Best-fit style chosen per theme (highest weight, strongest thematic match):
  morning     → silhouette_landscape
  wisdom      → metaphorical_digital
  love        → watercolour_ink
  mindfulness → paper_cut_shadowbox
  goodnight   → nocturnal_aesthetic
  latenight   → nocturnal_aesthetic  (variant 2)
  womenpower  → women_vivid_art

Usage:
    HF_API_KEY=hf_... python scripts/generate_static_fallbacks.py
"""
import io
import os
import sys
import time
from pathlib import Path

import random
import requests
import yaml
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

HF_API_KEY  = os.environ.get("HF_API_KEY", "")
MODEL_ID    = os.environ.get("HF_MODEL_ID", "black-forest-labs/FLUX.1-schnell")
API_URL     = f"https://router.huggingface.co/hf-inference/models/{MODEL_ID}"
OUTPUT_DIR  = Path("assets/static")
WIDTH, HEIGHT = 768, 1344

# Theme → style name to use from styles.yml
THEME_STYLE_MAP = {
    "morning":     "silhouette_landscape",
    "wisdom":      "ghibli_anime",
    "love":        "cozy_aesthetic",
    "mindfulness": "paper_cut_shadowbox",
    "goodnight":   "nocturnal_aesthetic",
    "latenight":   "dark_surreal",
    "womenpower":  "women_vivid_art",
}

# No-text enforcement appended to every prompt
_NO_TEXT = (
    "\n\nCRITICAL: absolutely no text, letters, words, numbers, watermarks, signatures,"
    " labels, or typography of any kind anywhere in the image."
    " Pure visual only."
)


def load_styles() -> dict:
    styles_path = Path("config/styles.yml")
    if not styles_path.exists():
        print("ERROR: config/styles.yml not found. Run from repo root.")
        sys.exit(1)
    with open(styles_path) as f:
        data = yaml.safe_load(f)
    return data["styles"]


def call_hf(prompt: str) -> bytes | None:
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "width":               WIDTH,
            "height":              HEIGHT,
            "num_inference_steps": 4,
            "guidance_scale":      0.0,
            "seed":                random.randint(0, 2**32 - 1),
        },
    }
    for attempt in range(1, 4):
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 10_000:
            return resp.content
        if resp.status_code == 503:
            try:
                wait = float(resp.json().get("estimated_time", 20)) + 2
            except Exception:
                wait = 22
            print(f"    Model loading — waiting {wait:.0f}s (attempt {attempt}/3)…")
            time.sleep(wait)
            continue
        if resp.status_code == 429:
            print(f"    Rate limited — waiting 30s (attempt {attempt}/3)…")
            time.sleep(30)
            continue
        print(f"    ERROR {resp.status_code}: {resp.text[:200]}")
        return None
    return None


def save_jpg(raw: bytes, path: Path) -> bool:
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        # Resize to full 1080×1920 for the fallback
        img = img.resize((1080, 1920), Image.LANCZOS)
        img.save(path, format="JPEG", quality=92)
        kb = path.stat().st_size // 1024
        print(f"    Saved → {path}  ({img.size[0]}×{img.size[1]}, {kb} KB)")
        return True
    except Exception as exc:
        print(f"    Save error: {exc}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", help="Comma-separated themes to regenerate (default: all)")
    args = parser.parse_args()

    if not HF_API_KEY:
        print("ERROR: HF_API_KEY not set.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = load_styles()

    run_map = THEME_STYLE_MAP
    if args.theme:
        requested = [t.strip() for t in args.theme.split(",")]
        unknown = [t for t in requested if t not in THEME_STYLE_MAP]
        if unknown:
            print(f"ERROR: Unknown themes: {unknown}. Valid: {list(THEME_STYLE_MAP.keys())}")
            sys.exit(1)
        run_map = {t: THEME_STYLE_MAP[t] for t in requested}

    print(f"\nGenerating {len(run_map)} theme fallback image(s) via {MODEL_ID}")
    print(f"Output: {OUTPUT_DIR}/  ({WIDTH}×{HEIGHT} → upscaled to 1080×1920)\n")

    failed = []
    for theme, style_name in run_map.items():
        out_path = OUTPUT_DIR / f"{theme}.jpg"
        print(f"[{theme}]  style: {style_name}")

        if style_name not in styles:
            print(f"    ERROR: style '{style_name}' not found in styles.yml")
            failed.append(theme)
            continue

        # Full description verbatim + no-text enforcement
        description = styles[style_name]["description"].strip()
        prompt = description + _NO_TEXT
        print(f"    Prompt length: {len(prompt)} chars")

        raw = call_hf(prompt)
        if raw:
            save_jpg(raw, out_path)
        else:
            print(f"    FAILED — {theme}.jpg not updated")
            failed.append(theme)

        time.sleep(4)   # courtesy pause between calls

    print(f"\n{'='*50}")
    print(f"Done: {len(run_map) - len(failed)}/{len(run_map)} images generated")
    if failed:
        print(f"Failed themes: {failed}")
        print("Re-run with the same command to retry failed themes only.")


if __name__ == "__main__":
    main()
