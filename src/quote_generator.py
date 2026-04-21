"""
Quote retrieval — unified flow for all themes.

Each run randomly picks a mode:
  - real_author   : Gemini finds a real quote by a known person (non-obvious sources preferred)
  - social_viral  : Gemini finds/writes a quote in the style of viral social media posts
  - llm_generated : Gemini writes an original quote (short and concrete encouraged)

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

MAX_ATTEMPTS       = 2
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
    "morning":     '"believe in yourself", "chase your dreams", "rise and shine", "hustle hard", "surviving", "warrior", "every day is a gift"',
    "wisdom":      '"everything happens for a reason", "be the change", "time heals all wounds", "your journey", "best version of yourself", "broken into pieces"',
    "love":        '"soulmates", "love conquers all", "you complete me", "you deserve better", "red flags"',
    "mindfulness": '"be present", "let it go", "inner peace", "heal yourself", "your healing journey"',
    "goodnight":   '"count your blessings", "tomorrow is a new day", "sweet dreams", "you survived today"',
    "latenight":   '"time heals", "let go and move on", "you deserve better", "surviving", "healing is not linear", "warrior"',
    "womenpower":  '"boss babe", "girl boss", "she believed she could", "women are strong", "girl power", "empowered women empower women", "know your worth", "her vibe", "toxic", "healed", "healing journey", "unbothered"',
}


def _build_real_prompt(category: str, max_words: int, topic_block: str) -> str:
    cliches = _CLICHE_MAP.get(category, '"overused clichés"')
    return f"""\
You are finding and evaluating real quotes for @_daily_dose_of_wisdom__, \
an Indian Instagram page for emotionally intelligent youth aged 18-35.

Find 3 DIFFERENT real quotes — each actually written or spoken by a known person. \
Prefer filmmakers, musicians, comedians, athletes, novelists, or contemporary thinkers \
over the usual Rumi / Stoics / Einstein pool — those are overexposed. A sharp line from \
a film, a lyric that works standalone, or a line from a novelist almost nobody quotes are all valid.

{topic_block}

Rules for each quote:
- REAL quote by a REAL, named person — not "Unknown" or "Anonymous"
- Maximum {max_words} words total. Hard limit.
- Must resonate with an Indian aged 18-35 in 2025 — timeless but not cliché
- Must feel RARE — not one of the top 1000 most quoted lines on the internet
- No clichés: {cliches}
- Short is fine — a complete 6-word quote beats a padded 20-word one
- All 3 must be from different authors and different emotional angles

Score each on 4 dimensions (1-10): virality, engagement, uniqueness (1-4 if widely circulated), freshness.
Hard rule: uniqueness < 6 → reject. Generic self-help → reject.

Then pick the single best-scoring quote and return ONLY that one as JSON — no markdown, no explanation:
{{"quote":"PLAIN TEXT ONLY — the exact words, nothing else. No quotation marks (\", ", "), \
no attribution suffix (no '- Author', '— Author'), no leading/trailing punctuation added by you. \
Just the raw words as spoken/written.","author":"Full Name","score":<avg 1-10>,\
"virality":<1-10>,"engagement":<1-10>,"uniqueness":<1-10>,"freshness":<1-10>,\
"reason":"<one sentence>","accept":<true if score>=7 AND uniqueness>=6, else false>}}
"""


def _build_social_prompt(category: str, max_words: int, topic_block: str) -> str:
    cliches = _CLICHE_MAP.get(category, '"overused clichés"')
    return f"""\
You are writing quotes in the style of things that go genuinely viral on social media \
for @_daily_dose_of_wisdom__, an Indian Instagram page for emotionally intelligent youth aged 18-35.

Think Reddit threads, Twitter/X posts, Tumblr, Pinterest, Instagram captions — the kind \
of line a real 25-year-old wrote from experience that thousands of people screenshot because \
they felt seen. Not profound philosophy. Not a motivational poster. Just one true thing said simply.

{topic_block}

Write 3 DIFFERENT candidates. Each should feel like:
- Something a real person said, not a writer performing wisdom
- The kind of line you text a friend and they reply "damn"
- Simple enough that the visual does half the work — short is often better
- Warm and specific, not vague and grand

Rules for each:
- Maximum {max_words} words. Short quotes (4-8 words) are especially welcome.
- Concrete over abstract — one precise feeling, not a life philosophy
- No clichés: {cliches}
- Banned words: "surviving", "journey", "heal", "broken", "warrior", "storm", "chapter", "version of yourself"
- All 3 must explore different feelings or angles
- Author field must be "Original"

Score each on 4 dimensions (1-10): virality, engagement, uniqueness, freshness.
Hard rule: uniqueness < 6 → reject. Generic self-help → reject.

Then pick the single best-scoring quote and return ONLY that one as JSON — no markdown, no explanation:
{{"quote":"PLAIN TEXT ONLY — no quotation marks, no attribution, just the words.","author":"Original","score":<avg 1-10>,\
"virality":<1-10>,"engagement":<1-10>,"uniqueness":<1-10>,"freshness":<1-10>,\
"reason":"<one sentence>","accept":<true if score>=7 AND uniqueness>=6, else false>}}
"""


def _build_llm_prompt(category: str, max_words: int, topic_block: str) -> str:
    cliches = _CLICHE_MAP.get(category, '"overused clichés"')
    return f"""\
You are writing original quotes for @_daily_dose_of_wisdom__, \
an Indian Instagram page for emotionally intelligent youth aged 18-35.

Write 3 DIFFERENT original quotes. Each should feel like something a thoughtful person \
said once and never repeated — not assembled from parts of other quotes. Specific and earned, not performed.

{topic_block}

Rules for each:
- ORIGINAL — not attributed to any real person
- Maximum {max_words} words total. Hard limit.
- Short is valid — if the feeling is complete in 5 words, stop at 5. Short quotes let the visual carry the post.
- Concrete over abstract: "you still made the tea on the worst morning" beats "strength lives in small moments"
- Must resonate with an Indian aged 18-30 at a gut level
- No Pinterest-assembled philosophy — warm simple lines are fine if they're genuinely fresh
- No clichés: {cliches}
- Banned words: "surviving", "journey", "heal", "broken", "warrior", "storm", "chapter", "version of yourself"
- All 3 must be emotionally distinct from each other

Score each on 4 dimensions (1-10): virality, engagement, uniqueness, freshness.
Hard rule: uniqueness < 6 → reject. Generic self-help → reject.

Then pick the single best-scoring quote and return ONLY that one as JSON — no markdown, no explanation:
{{"quote":"PLAIN TEXT ONLY — no quotation marks, no attribution, just the words.","author":"Original","score":<avg 1-10>,\
"virality":<1-10>,"engagement":<1-10>,"uniqueness":<1-10>,"freshness":<1-10>,\
"reason":"<one sentence>","accept":<true if score>=7 AND uniqueness>=6, else false>}}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash(text: str) -> str:
    return hashlib.md5(text.lower().strip().encode()).hexdigest()[:16]


_QUOTE_CHARS = '\u201c\u201d\u2018\u2019\"\'\u00ab\u00bb\u201e\u201f'

def _clean_text(text: str) -> str:
    """Strip quotation marks and author attributions from quote text.

    Dashes INSIDE the quote (e.g. "self-doubt", "day — night") are preserved
    because the pattern only matches a trailing separator followed by a
    Capitalised Name with no further separators.
    """
    text = text.strip().strip(_QUOTE_CHARS).strip()
    # Strip trailing author attribution: separator + space + Capitalised Name
    # e.g. " - Krishnamurti", " — Rumi", " ~ Unknown", " – Osho"
    text = re.sub(r'\s*[-\u2014\u2013~]\s*[A-Z][^-\u2014\u2013~\n]{1,60}$', '', text).strip()
    text = text.strip(_QUOTE_CHARS).strip()
    return text


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
    from src.config import GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK
    from google.genai import types
    cfg = types.GenerateContentConfig(
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for model in [GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK]:
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
            return resp.text.strip()
        except Exception as exc:
            if model == GEMINI_TEXT_MODEL_FALLBACK:
                raise
            logger.warning(f"Primary text model failed: {exc} — retrying with {GEMINI_TEXT_MODEL_FALLBACK}")
    raise RuntimeError("unreachable")


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

    # womenpower: original voice only — real attribution breaks the personal tone
    _modes = ["social_viral", "llm_generated"] if theme == "womenpower" else ["real_author", "social_viral", "llm_generated"]
    mode = random.choice(_modes)
    logger.info(f"  Mode: {mode}")

    if mode == "real_author":
        base_prompt = _build_real_prompt(theme, max_words, topic_block)
    elif mode == "social_viral":
        base_prompt = _build_social_prompt(theme, max_words, topic_block)
    else:
        base_prompt = _build_llm_prompt(theme, max_words, topic_block)
    prompt = _append_avoid_hint(base_prompt, recent_hints or [])

    best: dict | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info(f"  Quote attempt {attempt}/{MAX_ATTEMPTS}…")
        try:
            import json as _json
            raw = _call(client, prompt)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                time.sleep(RETRY_DELAY)
                continue
            data = _json.loads(m.group())
            text   = _clean_text(data.get("quote", ""))
            author = data.get("author", "").strip()
            if not text or not author:
                time.sleep(RETRY_DELAY)
                continue

            wc = len(text.split())
            if wc < 3 or wc > max_words + 5:
                logger.info(f"    Skipped — word count {wc}")
                time.sleep(RETRY_DELAY)
                continue
            if _hash(text) in posted_hashes:
                logger.info("    Skipped — already posted")
                time.sleep(RETRY_DELAY)
                continue

            score      = int(data.get("score", 0))
            uniqueness = int(data.get("uniqueness", 0))
            accept     = bool(data.get("accept", False)) and uniqueness >= MIN_UNIQUENESS
            logger.info(
                f"    \"{text[:80]}\" — {author}"
            )
            logger.info(
                f"    Quality: score={score}  virality={data.get('virality')}  "
                f"engagement={data.get('engagement')}  uniqueness={uniqueness}  "
                f"freshness={data.get('freshness')} | {data.get('reason', '')}"
            )

            candidate = {
                "text":       text,
                "author":     author,
                "highlight":  _extract_highlight(text),
                "image_hint": image_hint,
                "score":      score,
                "source":     "gemini_real" if mode == "real_author" else "gemini_social" if mode == "social_viral" else "gemini_original",
            }

            if accept:
                logger.info(f"  ✓ Accepted (score {score}, uniqueness {uniqueness})")
                return candidate

            if best is None or score > best["score"]:
                best = candidate

        except Exception as exc:
            err = str(exc)
            if "RESOURCE_EXHAUSTED" in err or "429" in err:
                logger.warning(f"  429 / quota exhausted — skipping Gemini entirely")
                return None
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
