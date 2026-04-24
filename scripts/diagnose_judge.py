"""
Diagnose whether the image judge is correctly flagging signatures, or
hallucinating them. Generates one image via Leonardo, composes it with
a quote, then asks BOTH Moonshot and Gemini to judge the SAME image.

Usage:
    python scripts/diagnose_judge.py [theme]
"""
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")

# Force Leonardo-only for this diagnostic
os.environ["IMAGE_PROVIDER_ORDER"] = "leonardo"

from src.design_director import generate_brief
from src.image_composer import compose
from src.image_generator import get_image
from src.image_judge import _JUDGE_PROMPT, _ARTIFACT_KEYWORDS, _MIN_READABILITY, _MIN_SCORE
from src.llm import _gemini_vision, _moonshot_vision
from src.quote_generator import generate_quote

import re

theme = (sys.argv[1] if len(sys.argv) > 1 else "latenight").lower()

print(f"\n=== Diagnostic: {theme} ===\n")

quote = generate_quote(theme, posted_hashes=set(), recent_hints=[])
print(f"Quote: {quote['text']}")
print(f"Author: {quote.get('author')}\n")

brief = generate_brief(quote, theme, recent_styles=[])
print(f"Style: {brief.get('image_prompt', '')[:120]}\n")

print("Generating Leonardo image...")
raw = get_image(theme=theme, image_prompt=brief["image_prompt"], quote_text=quote["text"])
print(f"Got raw image: {len(raw)//1024}KB")

composed = compose(raw, quote, brief)

out = Path("output")
out.mkdir(exist_ok=True)
raw_path = out / f"diag_{theme}_raw.jpg"
comp_path = out / f"diag_{theme}_composed.jpg"
raw_path.write_bytes(raw)
comp_path.write_bytes(composed)
print(f"\nRaw     → {raw_path}")
print(f"Composed → {comp_path}\n")

text = quote.get("text", "")[:200].replace('"', "'")
author = quote.get("author", "Unknown")
prompt = _JUDGE_PROMPT.format(text=text, author=author)


def run_judge(fn, name):
    print(f"--- {name} judge ---")
    try:
        result = fn(prompt, composed, "image/jpeg")
        if result is None:
            print("  (no response)\n")
            return
        raw_text, model = result
        print(f"  model: {model}")
        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not m:
            print(f"  raw: {raw_text[:300]}\n")
            return
        v = json.loads(m.group())
        print(f"  scores: hook={v.get('image_hook')} quality={v.get('image_quality')} "
              f"read={v.get('text_readability')} impact={v.get('quote_impact')} "
              f"harmony={v.get('image_text_harmony')}")
        print(f"  has_signature     : {v.get('has_signature')}")
        print(f"  has_text_artifact : {v.get('has_text_artifact')}")
        print(f"  issues            : {v.get('issues')!r}")
        print()
    except Exception as exc:
        print(f"  error: {exc}\n")


# Run on composed image (what the real pipeline judges)
print("### JUDGING COMPOSED IMAGE (what pipeline actually sees)\n")
run_judge(_gemini_vision, "Gemini")
run_judge(_moonshot_vision, "Moonshot")

# Also judge the RAW image (no overlay) to isolate "is there a real signature in the AI output"
print("### JUDGING RAW LEONARDO IMAGE (no text overlay)\n")
prompt_raw = prompt  # same prompt, different pixels
def run_on_raw(fn, name):
    print(f"--- {name} judge (raw) ---")
    try:
        result = fn(prompt_raw, raw, "image/jpeg")
        if result is None:
            print("  (no response)\n")
            return
        raw_text, model = result
        print(f"  model: {model}")
        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if m:
            v = json.loads(m.group())
            print(f"  has_signature     : {v.get('has_signature')}")
            print(f"  has_text_artifact : {v.get('has_text_artifact')}")
            print(f"  issues            : {v.get('issues')!r}\n")
        else:
            print(f"  raw: {raw_text[:300]}\n")
    except Exception as exc:
        print(f"  error: {exc}\n")

run_on_raw(_gemini_vision, "Gemini")
run_on_raw(_moonshot_vision, "Moonshot")

print("\nOpen both images to visually inspect:")
print(f"  open {raw_path}")
print(f"  open {comp_path}")
