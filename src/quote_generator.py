"""
Quote retrieval — Gemini recalls REAL quotes by known authors.

Primary flow: ask Gemini to surface a real, attributed quote that fits the topic.
Fallback: curated pool in config/curated_quotes.yml.

Returns: {text, author, highlight, source}
  source: "gemini_real" | "curated" | "fallback"
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

MAX_ATTEMPTS     = 4
LATENIGHT_MIN_SCORE = 7
RETRY_DELAY      = 2

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
# Prompt builder — asks Gemini to FIND a real quote
# ---------------------------------------------------------------------------

def _build_prompt(category: str, max_words: int, topic_block: str) -> str:
    cliche_map = {
        "morning":    '"believe in yourself", "chase your dreams", "rise and shine", "hustle hard"',
        "wisdom":     '"everything happens for a reason", "be the change", "time heals all wounds"',
        "love":       '"soulmates", "love conquers all", "you complete me"',
        "mindfulness":'"be present", "let it go", "inner peace"',
        "goodnight":  '"count your blessings", "tomorrow is a new day", "sweet dreams"',
        "latenight":  '"time heals", "let go and move on", "you deserve better"',
    }
    cliches = cliche_map.get(category, '"overused clichés"')

    return f"""\
You are finding real quotes for @_daily_dose_of_wisdom__, an Indian Instagram page \
for emotionally intelligent youth aged 18-35.

Find ONE real quote — actually written or spoken by a known person (author, philosopher, \
filmmaker, poet, scientist, athlete, historical figure, or contemporary thinker). \
The quote must be genuinely attributed — you must be confident the person said it.

{topic_block}

Rules:
- REAL quote by a REAL, named person — not "Unknown" or "Anonymous" if at all possible
- Maximum {max_words} words total. Hard limit.
- Must resonate with an Indian aged 18-35 in 2025 — timeless but not cliché
- Avoid massively overexposed lines people have seen a thousand times
- No clichés: {cliches}
- Return ONLY valid JSON — no markdown, no explanation:
  {{"quote": "the exact quote text", "author": "Full Name"}}
"""


# ---------------------------------------------------------------------------
# Late-night validation prompt (unchanged logic)
# ---------------------------------------------------------------------------

_LATENIGHT_VALIDATION = """\
You are a strict quality judge for @_daily_dose_of_wisdom__, \
an Indian Instagram page for youth aged 18-35.

Quote: "{quote}" — {author}

Score 1-10 on each (real quotes by known authors start at a baseline of 6):
1. resonance    — would an Indian aged 18-35 feel this at 2 AM?
2. precision    — captures ONE specific feeling with real detail (not vague)
3. freshness    — not overexposed online; feels surprising to encounter
4. clean        — zero filler phrases

Respond ONLY with valid JSON, no markdown:
{{"score":<avg int>,"resonance":<1-10>,"precision":<1-10>,"freshness":<1-10>,"clean":<1-10>,"reason":"<one sentence>"}}
"""

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
    """Extract (quote, author) from Gemini JSON response."""
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
# Daytime themes
# ---------------------------------------------------------------------------

def generate_themed_quote(theme: str, posted_hashes: set,
                           recent_hints: list[str] | None = None) -> dict | None:
    from src.content_config import get_max_words, get_topic_info

    try:
        client = _gemini_client()
    except RuntimeError:
        return None

    max_words  = get_max_words(theme)
    info       = get_topic_info(theme)
    topic_block = info["topic_block"]
    image_hint  = info["image_hint"]
    base_prompt = _build_prompt(theme, max_words, topic_block)
    prompt      = _append_avoid_hint(base_prompt, recent_hints or [])

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _call(client, prompt)
            parsed = _parse_quote_json(raw)
            if not parsed:
                time.sleep(RETRY_DELAY)
                continue
            text, author = parsed
            wc = len(text.split())
            if wc < 4 or wc > max_words + 5:
                time.sleep(RETRY_DELAY)
                continue
            if _hash(text) in posted_hashes:
                time.sleep(RETRY_DELAY)
                continue
            highlight = _extract_highlight(text)
            logger.info(f"  ✓ Real quote (attempt {attempt}): \"{text[:70]}\" — {author}")
            logger.info(f"    highlight: \"{highlight}\"")
            return {
                "text": text,
                "author": author,
                "highlight": highlight,
                "image_hint": image_hint,
                "source": "gemini_real",
            }
        except Exception as exc:
            logger.warning(f"  Gemini attempt {attempt} failed: {exc}")
            time.sleep(RETRY_DELAY)

    return None


# ---------------------------------------------------------------------------
# Late-night — with quality validation
# ---------------------------------------------------------------------------

def _validate_latenight(client, text: str, author: str) -> dict:
    import json
    prompt = _LATENIGHT_VALIDATION.format(
        quote=text.replace('"', '\\"'),
        author=author
    )
    raw = _call(client, prompt)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Bad JSON: {raw[:150]}")
    return json.loads(match.group())


def generate_latenight_quote(posted_hashes: set,
                              recent_hints: list[str] | None = None) -> dict:
    from src.content_config import get_max_words, get_topic_info

    try:
        client = _gemini_client()
    except RuntimeError as exc:
        logger.error(f"Gemini unavailable: {exc}")
        return _pick_curated("latenight", posted_hashes) or _handcrafted_fallback(posted_hashes)

    max_words   = get_max_words("latenight")
    info        = get_topic_info("latenight")
    topic_block = info["topic_block"]
    base_prompt = _build_prompt("latenight", max_words, topic_block)
    prompt      = _append_avoid_hint(base_prompt, recent_hints or [])
    best: dict | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info(f"Late-night retrieval (attempt {attempt}/{MAX_ATTEMPTS})…")
        try:
            raw = _call(client, prompt)
            parsed = _parse_quote_json(raw)
            if not parsed:
                time.sleep(RETRY_DELAY)
                continue
            text, author = parsed
            wc = len(text.split())
            if wc < 6 or wc > max_words + 5:
                time.sleep(RETRY_DELAY)
                continue
            if _hash(text) in posted_hashes:
                time.sleep(RETRY_DELAY)
                continue

            logger.info(f"  Retrieved: \"{text[:80]}\" — {author}")
            scores = _validate_latenight(client, text, author)
            score  = int(scores.get("score", 0))
            logger.info(
                f"  Score {score}/10  resonance={scores.get('resonance')}  "
                f"precision={scores.get('precision')}  freshness={scores.get('freshness')}  "
                f"clean={scores.get('clean')} | {scores.get('reason', '')}"
            )

            candidate = {
                "text": text,
                "author": author,
                "highlight": _extract_highlight(text),
                "score": score,
                "source": "gemini_real",
            }

            if score >= LATENIGHT_MIN_SCORE:
                logger.info("  ✓ Accepted")
                return candidate

            if best is None or score > best["score"]:
                best = candidate
        except Exception as exc:
            logger.warning(f"  Attempt {attempt} error: {exc}")
        time.sleep(RETRY_DELAY)

    if best:
        logger.warning(f"Using best-scoring latenight quote (score {best['score']})")
        return best

    return _pick_curated("latenight", posted_hashes) or _handcrafted_fallback(posted_hashes)


# ---------------------------------------------------------------------------
# Universal entry point
# ---------------------------------------------------------------------------

def generate_quote(theme: str, posted_hashes: set,
                   recent_hints: list[str] | None = None) -> dict:
    if theme == "latenight":
        return generate_latenight_quote(posted_hashes, recent_hints)

    q = generate_themed_quote(theme, posted_hashes, recent_hints)
    if q:
        return q

    logger.warning("Gemini unavailable — using curated fallback pool")
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
