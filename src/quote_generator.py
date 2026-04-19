"""
Quote retrieval — unified flow for all themes.

Each run randomly picks a mode:
  - real_author   : Gemini finds a real quote by a known person
  - llm_generated : Gemini writes an original quote

All quotes pass through a quality gate before acceptance.
Fallback: curated pool in config/curated_quotes.yml.

Returns: {text, author, highlight, source}
  source: "gemini_real" | "gemini_original" | "curated" | "fallback"
"""
import hashlib
import logging
import os
import random
import re
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

MAX_ATTEMPTS       = 6
IMAGE_JUDGE_MAX    = 3   # kept in image_judge.py — noted here for clarity
MIN_QUALITY_SCORE  = 7
MIN_UNIQUENESS     = 6   # hard floor — generic/overexposed quotes always rejected
RETRY_DELAY        = 2


# ---------------------------------------------------------------------------
# Load curated fallback pool
# ---------------------------------------------------------------------------

def _load_curated() -> dict[str, list[dict]]:
    path = Path(__file__).parent.parent / "config" / "curated_quotes.yml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("quotes", {})

_CURATED_POOL = _load_curated()


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_CLICHE_MAP = {
    "morning":     '"believe in yourself", "chase your dreams", "rise and shine", "hustle hard"',
    "wisdom":      '"everything happens for a reason", "be the change", "time heals all wounds"',
    "love":        '"soulmates", "love conquers all", "you complete me"',
    "mindfulness": '"be present", "let it go", "inner peace"',
    "goodnight":   '"count your blessings", "tomorrow is a new day", "sweet dreams"',
    "latenight":   '"time heals", "let go and move on", "you deserve better"',
}


def _build_real_prompt(category: str, max_words: int, topic_block: str) -> str:
    cliches = _CLICHE_MAP.get(category, '"overused clichés"')
    return f"""\
You are finding real quotes for @_daily_dose_of_wisdom__, an Indian Instagram page \
for emotionally intelligent youth aged 18-35.

Find ONE real quote — actually written or spoken by a known person (author, philosopher, \
filmmaker, poet, scientist, athlete, historical figure, or contemporary thinker). \
The quote must be genuinely attributed — you must be confident the person said it.

{topic_block}

Rules:
- REAL quote by a REAL, named person — not "Unknown" or "Anonymous"
- Maximum {max_words} words total. Hard limit.
- Must resonate with an Indian aged 18-35 in 2025 — timeless but not cliché
- Must feel RARE — not one of the top 1000 most quoted lines on the internet
- Avoid massively overexposed lines people have seen a thousand times
- No clichés: {cliches}
- Return ONLY valid JSON — no markdown, no explanation:
  {{"quote": "the exact quote text", "author": "Full Name"}}
"""


def _build_llm_prompt(category: str, max_words: int, topic_block: str) -> str:
    cliches = _CLICHE_MAP.get(category, '"overused clichés"')
    return f"""\
You are writing an original quote for @_daily_dose_of_wisdom__, an Indian Instagram page \
for emotionally intelligent youth aged 18-35.

Write ONE original quote — something that feels like it was written by a thoughtful, \
specific human mind. It should feel surprising and earned, not like a motivational poster.

{topic_block}

Rules:
- ORIGINAL — not attributed to any real person
- Maximum {max_words} words total. Hard limit.
- Specific and concrete — one precise feeling or truth, not a vague generality
- Must resonate with an Indian aged 18-30 at an emotional gut level
- Should feel like something you have NEVER seen on Instagram before
- No clichés: {cliches}
- Return ONLY valid JSON — no markdown, no explanation:
  {{"quote": "the quote text", "author": "Original"}}
"""


# ---------------------------------------------------------------------------
# Universal quality validation
# ---------------------------------------------------------------------------

_QUALITY_PROMPT = '''\
You are a strict quality judge for @_daily_dose_of_wisdom__, \
an Indian Instagram page for emotionally intelligent youth aged 18-35.

Quote: "{quote}" — {author}
Theme: {theme}
Mode: {mode}

Score 1-10 on each — be honest and strict:

1. virality     — Would people screenshot and share this? Does it land like something \
worth saving?
2. engagement   — Would an Indian aged 18-30 feel this in their chest? \
(18-30 is the primary target; 18-45 is acceptable)
3. uniqueness   — Is this quote rare and hard to find? \
Score 1-4 if it's widely circulated online. Score 7+ only if genuinely obscure or original.
4. freshness    — Does it feel completely different from generic Instagram quotes? \
No motivational-poster energy.

Hard rules:
- uniqueness < 6 → always reject regardless of other scores
- Generic self-help language → always reject

Respond ONLY with valid JSON (no markdown):
{{"score":<integer average 1-10>,"virality":<1-10>,"engagement":<1-10>,\
"uniqueness":<1-10>,"freshness":<1-10>,"reason":"<one sentence>",\
"accept":<true if score>=7 AND uniqueness>=6, else false>}}
'''


def _validate_quote(client, text: str, author: str, theme: str, mode: str) -> dict:
    import json
    prompt = _QUALITY_PROMPT.format(
        quote=text.replace('"', '\\"'),
        author=author,
        theme=theme,
        mode=mode,
    )
    raw = _call(client, prompt)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"Bad JSON from validator: {raw[:150]}")
    result = json.loads(m.group())
    result["accept"] = bool(result.get("accept", False)) and int(result.get("uniqueness", 0)) >= MIN_UNIQUENESS
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash(text: str) -> str:
    return hashlib.md5(text.lower().strip().encode()).hexdigest()[:16]


def _clean_text(text: str) -> str:
    return text.strip().strip('"\'').strip("\u201c\u201d\u2018\u2019").strip()


def _extract_highlight(text: str) -> str:
    parts = [p.strip() for p in re.split(r"[.!?—–]", text) if p.strip()]
    if len(parts) > 1:
        last = parts[-1]
        words = last.split()
        if 3 <= len(words) <= 6:
            return last
        if len(words) > 6:
            return " ".join(words[:5])
    words = text.split()
    if len(words) <= 6:
        return text
    return " ".join(words[-5:])


def _gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    from google import genai
    return genai.Client(api_key=api_key)


def _call(client, prompt: str) -> str:
    from src.config import GEMINI_TEXT_MODEL
    resp = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=prompt)
    return resp.text.strip()


def _append_avoid_hint(prompt: str, recent_hints: list[str]) -> str:
    if not recent_hints:
        return prompt
    lines = "\n".join(f"- {h}…" for h in recent_hints[-20:])
    return prompt + f"\n\nAvoid quotes on the same theme or idea as these recent posts:\n{lines}\n"


def _parse_quote_json(raw: str) -> tuple[str, str] | None:
    import json
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group())
        q = _clean_text(data.get("quote", ""))
        a = data.get("author", "").strip()
        if q and a:
            return q, a
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Curated fallback
# ---------------------------------------------------------------------------

def _pick_curated(category: str, posted_hashes: set) -> dict | None:
    pool = _CURATED_POOL.get(category, [])
    if not pool:
        return None
    available = [q for q in pool if _hash(q["text"]) not in posted_hashes]
    if not available:
        available = pool
    item = dict(random.choice(available))
    item.setdefault("highlight", _extract_highlight(item["text"]))
    item["source"] = "curated"
    return item


# ---------------------------------------------------------------------------
# Core generation — unified flow for all themes
# ---------------------------------------------------------------------------

def _generate_with_validation(
    theme: str,
    posted_hashes: set,
    recent_hints: list[str] | None = None,
) -> dict | None:
    from src.content_config import get_max_words, get_topic_info

    try:
        client = _gemini_client()
    except RuntimeError:
        return None

    max_words   = get_max_words(theme)
    info        = get_topic_info(theme)
    topic_block = info["topic_block"]
    image_hint  = info["image_hint"]

    mode = random.choice(["real_author", "llm_generated"])
    logger.info(f"  Mode: {mode}")

    base_prompt = (
        _build_real_prompt(theme, max_words, topic_block)
        if mode == "real_author"
        else _build_llm_prompt(theme, max_words, topic_block)
    )
    prompt = _append_avoid_hint(base_prompt, recent_hints or [])

    best: dict | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info(f"  Quote attempt {attempt}/{MAX_ATTEMPTS}…")
        try:
            raw    = _call(client, prompt)
            parsed = _parse_quote_json(raw)
            if not parsed:
                time.sleep(RETRY_DELAY)
                continue

            text, author = parsed
            wc = len(text.split())
            if wc < 4 or wc > max_words + 5:
                logger.info(f"    Skipped — word count {wc}")
                time.sleep(RETRY_DELAY)
                continue
            if _hash(text) in posted_hashes:
                logger.info("    Skipped — already posted")
                time.sleep(RETRY_DELAY)
                continue

            logger.info(f"    Retrieved: \"{text[:80]}\" — {author}")

            scores = _validate_quote(client, text, author, theme, mode)
            score      = int(scores.get("score", 0))
            uniqueness = int(scores.get("uniqueness", 0))
            logger.info(
                f"    Quality: score={score}  virality={scores.get('virality')}  "
                f"engagement={scores.get('engagement')}  uniqueness={uniqueness}  "
                f"freshness={scores.get('freshness')} | {scores.get('reason', '')}"
            )

            candidate = {
                "text":       text,
                "author":     author,
                "highlight":  _extract_highlight(text),
                "image_hint": image_hint,
                "score":      score,
                "source":     "gemini_real" if mode == "real_author" else "gemini_original",
            }

            if scores.get("accept"):
                logger.info(f"  ✓ Accepted (score {score}, uniqueness {uniqueness})")
                return candidate

            if best is None or score > best["score"]:
                best = candidate

        except Exception as exc:
            logger.warning(f"  Attempt {attempt} error: {exc}")
        time.sleep(RETRY_DELAY)

    if best:
        logger.warning(f"  Using best available (score {best['score']}) — quality gate not met")
        return best

    return None


# ---------------------------------------------------------------------------
# Universal entry point
# ---------------------------------------------------------------------------

def generate_quote(theme: str, posted_hashes: set,
                   recent_hints: list[str] | None = None) -> dict:
    q = _generate_with_validation(theme, posted_hashes, recent_hints)
    if q:
        return q

    logger.warning("Gemini unavailable or exhausted — using curated fallback pool")
    curated = _pick_curated(theme, posted_hashes)
    if curated:
        return curated

    from src.config import FALLBACK_QUOTES
    pool = list(FALLBACK_QUOTES.get(theme, FALLBACK_QUOTES["wisdom"]))
    random.shuffle(pool)
    for item in pool:
        if _hash(item["text"]) not in posted_hashes:
            item = dict(item)
            item.setdefault("highlight", _extract_highlight(item["text"]))
            item["source"] = "fallback"
            return item
    item = dict(random.choice(pool))
    item.setdefault("highlight", _extract_highlight(item["text"]))
    item["source"] = "fallback"
    return item


# ---------------------------------------------------------------------------
# Handcrafted emergency fallback
# ---------------------------------------------------------------------------

_HANDCRAFTED = [
    {"text": "The wound is the place where the light enters you.", "author": "Rumi"},
    {"text": "Not all those who wander are lost.", "author": "J.R.R. Tolkien"},
    {"text": "We accept the love we think we deserve.", "author": "Stephen Chbosky"},
    {"text": "You can't stop the waves, but you can learn to surf.", "author": "Jon Kabat-Zinn"},
    {"text": "Almost everything will work again if you unplug it for a few minutes — including you.", "author": "Anne Lamott"},
    {"text": "Done is better than perfect.", "author": "Sheryl Sandberg"},
    {"text": "In today's rush we all think too much, seek too much, want too much and forget about the joy of just being.", "author": "Eckhart Tolle"},
]


def _handcrafted_fallback(posted_hashes: set) -> dict:
    pool = [q for q in _HANDCRAFTED if _hash(q["text"]) not in posted_hashes] or _HANDCRAFTED
    item = dict(random.choice(pool))
    item["highlight"] = _extract_highlight(item["text"])
    item["source"] = "fallback"
    return item
