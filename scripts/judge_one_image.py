"""Run both judges against a single image file and print their verdicts.
Usage: python scripts/judge_one_image.py /path/to/image.jpg [quote text]"""
import json
import logging
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.WARNING)

from src.image_judge import _JUDGE_PROMPT
from src.llm import _gemini_vision, _moonshot_vision

path = Path(sys.argv[1])
quote_text = sys.argv[2] if len(sys.argv) > 2 else "Sometimes the best part of a long day is the five minutes in the auto before you have to go inside."
author = "Original"

data = path.read_bytes()
mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
prompt = _JUDGE_PROMPT.format(text=quote_text, author=author)

for name, fn in [("Gemini", _gemini_vision), ("Moonshot", _moonshot_vision)]:
    print(f"\n--- {name} ---")
    try:
        res = fn(prompt, data, mime)
        if res is None:
            print("  (no response)")
            continue
        raw, model = res
        print(f"  model: {model}")
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            print(f"  raw: {raw[:400]}")
            continue
        v = json.loads(m.group())
        print(f"  scores   : hook={v.get('image_hook')} quality={v.get('image_quality')} "
              f"read={v.get('text_readability')} impact={v.get('quote_impact')} "
              f"harmony={v.get('image_text_harmony')}")
        print(f"  signature: {v.get('has_signature')}")
        print(f"  text_art : {v.get('has_text_artifact')}")
        print(f"  structure: {v.get('subject_structure')!r}")
        print(f"  anatomy  : {v.get('has_anatomy_flaw')}")
        print(f"  issues   : {v.get('issues')!r}")
    except Exception as exc:
        print(f"  error: {exc}")
