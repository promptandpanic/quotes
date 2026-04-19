"""
Gemini is the sole creative director.

It receives the quote + theme and returns a full render spec — font, size,
colour, overlay, text position, animation style, image prompt — everything.
Our renderer executes the spec exactly, no preset styles, no overrides.
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt — Gemini decides EVERYTHING
# ---------------------------------------------------------------------------

_BRIEF_PROMPT = '''\
You are the creative director for @_daily_dose_of_wisdom__, an Indian Instagram page \
for emotionally intelligent youth aged 18-35. \
Your audience is HIGHLY visual — they stop for a striking image first, read the quote second.

Your creative decisions render DIRECTLY — pick what would genuinely stop someone mid-scroll.

QUOTE : "{text}"
THEME : {theme}
{image_hint_block}
──────────────────────────────────────────────
{style_block}

──────────────────────────────────────────────
AVAILABLE FONTS (pick the one that best matches the quote's emotion):

  DISPLAY / BOLD — high impact, strong presence
  bebas        — all-caps ultra-bold display             → morning energy, power, raw impact
  anton        — condensed heavy poster font             → punchy one-liners, bold statements
  oswald       — condensed bold, editorial authority     → wisdom, stoic quotes, strong truths
  montserrat   — geometric bold, modern & versatile      → any theme, clean and confident
  cinzel       — classical Roman capitals, timeless      → ancient wisdom, philosophy, gravitas
  raleway      — elegant geometric bold                  → sophisticated, premium feel
  josefin      — minimal geometric, architectural        → minimalist aesthetic, clean wisdom

  SERIF — literary, warm, trustworthy
  playfair     — elegant bold serif, literary warmth     → love, poetry, reflection
  merriweather — sturdy readable serif, journalistic     → wisdom, goodnight, long quotes
  cormorant    — ultra-elegant high-contrast serif       → luxury feel, intimate love quotes

  SCRIPT — flowing, personal, emotional
  dancing      — flowing bold script                     → love, warmth, celebration
  satisfy      — casual elegant script                   → friendly warmth, goodnight, soft wisdom

  TEXTURE / CHARACTER
  specialelite — typewriter grit, raw texture            → late-night honesty, unfiltered emotion
  lato         — clean neutral sans                      → calm, minimal, clarity, mindfulness

AVAILABLE OVERLAYS (ensure text is readable — opacity 140-220):
  gradient_bottom — dark gradient rising from bottom  (pair with text_zone: bottom)
  gradient_top    — dark gradient falling from top    (pair with text_zone: top)
  gradient_center — dark band across middle           (pair with text_zone: center)
  solid           — full dark overlay across image    (for bright/complex backgrounds)
  vignette        — edges darken, centre stays bright (text_zone: center)

DECORATIONS:
  rule       — thin accent-colour horizontal line above the text block
  quote_mark — large decorative " faintly behind text
  none       — clean, let the image breathe

IMAGE RULES (always apply):
  - Illustrations, paintings, flat vector art, ink sketches, or abstract art ONLY
  - NEVER photorealistic humans or faces — no portrait photography, no stock-photo style people
  - Stylised figures (flat vector, illustrated, painted) are fine when they serve the mood
  - No text, signs, logos, watermarks, or typography in the image

TEXT LAYOUT — pick ONE based on the quote's length and energy:

  big_center     — SHORT punchy quotes only (≤12 words, single sentence).
                   Huge text, centered on screen, bold and immediate.
                   Video: image fades in with text visible — static powerful hold.
                   Pick this for: morning energy, single-line wisdom, raw impact.

  sentence_reveal — MULTI-SENTENCE quotes (2-4 sentences).
                   Each complete sentence fades in one by one and stays visible.
                   Text fills bottom zone, large readable size.
                   Video: each sentence appears in sequence, full quote visible at end.
                   Pick this for: emotional late-night, wisdom with build-up, love quotes.

  full_card      — MEDIUM quotes (1-2 sentences, 12-30 words).
                   Full text visible from the start, centered or bottom, clean hold.
                   Text fills the screen comfortably — large and bold.
                   Video: image crossfades in revealing all text, holds for full duration.
                   Pick this for: mindfulness, goodnight, poetic single thoughts.

──────────────────────────────────────────────
Be specific and emotionally precise. The image must DIRECTLY evoke this quote's feeling.

Return ONLY valid JSON — no markdown, no text outside the JSON:
{{
  "image_prompt": "Specific illustrated/painted scene that DIRECTLY reflects this quote's emotion. \
Include: exact subject + action, precise setting, art style (illustration/painting/vector), \
colour palette with 2-3 hex values, which region (e.g. lower 35%) should be \
dark soft bokeh where text will live. No text, signs, words, numbers, logos anywhere. \
Ultra-HD cinematic photography, 9:16 portrait.",

  "overlay": {{
    "type": "gradient_bottom|gradient_top|gradient_center|solid|vignette",
    "opacity": 140-220,
    "color": "#000000"
  }},

  "font": "bebas|anton|oswald|montserrat|cinzel|raleway|josefin|playfair|merriweather|cormorant|dancing|satisfy|specialelite|lato",
  "text_color": "#FFFFFF",
  "highlight_color": "#RRGGBB",
  "decoration": "rule|quote_mark|none",
  "layout": "big_center|sentence_reveal|full_card",
  "highlight": "3-6 most emotionally powerful CONSECUTIVE words from the quote — \
the line someone screenshots",
  "mood_note": "one sentence — the visual feeling that stops someone mid-scroll"
}}
'''

# ---------------------------------------------------------------------------
# Fallback defaults per theme (when Gemini unavailable)
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "morning": {
        "image_prompt": "[minimalist_vector] Bold flat 2D poster illustration — \
blazing sun rising over geometric Indian cityscape silhouette, \
terracotta, saffron, sky-blue palette, strong graphic shapes, \
lower 35% open dark gradient for text. 9:16 portrait.",
        "overlay": {"type": "gradient_bottom", "opacity": 170, "color": "#000000"},
        "font": "bebas", "text_color": "#FFFFFF",
        "highlight_color": "#FF8C00", "decoration": "rule",
        "layout": "big_center",
    },
    "wisdom": {
        "image_prompt": "[whimsical_sketch] Hand-drawn ink sketch of an ancient \
tree with deep roots and sparse branches, warm parchment background, \
loose expressive lines, lower 40% fades to soft cream-shadow for text. 9:16 portrait.",
        "overlay": {"type": "gradient_bottom", "opacity": 180, "color": "#000000"},
        "font": "oswald", "text_color": "#F5F5F5",
        "highlight_color": "#FFD700", "decoration": "rule",
        "layout": "full_card",
    },
    "love": {
        "image_prompt": "[watercolour_ink] Hand-painted watercolour wash of two hands \
almost touching, blush pink, dusty rose, soft violet, ink-line details, \
cold-press paper texture, centre band soft and luminous for text. 9:16 portrait.",
        "overlay": {"type": "vignette", "opacity": 150, "color": "#000000"},
        "font": "playfair", "text_color": "#FFF0F0",
        "highlight_color": "#FF6B8A", "decoration": "quote_mark",
        "layout": "full_card",
    },
    "mindfulness": {
        "image_prompt": "[minimalist_nature] Single lotus flower on still dark water, \
extreme negative space above, muted teal and ivory palette, \
ultra-minimal composition, center open and calm for text. 9:16 portrait.",
        "overlay": {"type": "gradient_center", "opacity": 155, "color": "#000000"},
        "font": "lato", "text_color": "#F0FFFF",
        "highlight_color": "#7FFFD4", "decoration": "none",
        "layout": "full_card",
    },
    "goodnight": {
        "image_prompt": "[cozy_aesthetic] Candlelit wooden desk, open journal, \
chai cup with wisps of steam, warm amber-gold tones, \
bokeh fairy lights behind, lower 40% fades to near-black for text. 9:16 portrait.",
        "overlay": {"type": "solid", "opacity": 195, "color": "#000005"},
        "font": "playfair", "text_color": "#E8E8FF",
        "highlight_color": "#C8A2C8", "decoration": "quote_mark",
        "layout": "sentence_reveal",
    },
    "latenight": {
        "image_prompt": "[abstract_fluid] Deep indigo and teal flowing liquid gradients, \
swirling energy fields, no literal subject — pure colour and emotional temperature \
matching 3 AM introspection. 9:16 portrait.",
        "overlay": {"type": "solid", "opacity": 210, "color": "#000005"},
        "font": "specialelite", "text_color": "#E0E0E0",
        "highlight_color": "#00CFCF", "decoration": "none",
        "layout": "sentence_reveal",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_brief(quote: dict, theme: str) -> dict:
    """
    Ask Gemini to act as creative director and return a full render spec.
    Falls back to theme defaults if Gemini is unavailable.
    """
    text   = quote.get("text", "")
    api_key = os.environ.get("GEMINI_API_KEY", "")

    brief = None
    if api_key:
        try:
            from google import genai
            from src.config import GEMINI_TEXT_MODEL
            from src.content_config import build_style_prompt_block

            client = genai.Client(api_key=api_key)
            style_block = build_style_prompt_block(theme)
            image_hint  = quote.get("image_hint", "")
            image_hint_block = (
                f"IMAGE DIRECTION: {image_hint}\n" if image_hint else ""
            )
            prompt = _BRIEF_PROMPT.format(
                text=text, theme=theme,
                style_block=style_block,
                image_hint_block=image_hint_block,
            )

            response = client.models.generate_content(
                model=GEMINI_TEXT_MODEL,
                contents=prompt,
            )
            raw = response.text.strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                brief = json.loads(m.group())
                logger.info(f"  Gemini layout={brief.get('layout')}  "
                            f"font={brief.get('font')}  "
                            f"highlight: \"{brief.get('highlight')}\"")
                logger.info(f"  mood: {brief.get('mood_note', '')}")
        except Exception as exc:
            logger.warning(f"Creative brief generation failed: {exc} — using defaults")

    if not brief:
        brief = dict(_DEFAULTS.get(theme, _DEFAULTS["wisdom"]))
        brief.setdefault("highlight", quote.get("highlight", ""))
        brief["mood_note"] = "Visually striking and emotionally resonant"

    # Guarantee highlight is set
    if not brief.get("highlight"):
        brief["highlight"] = quote.get("highlight", text.split(".")[0][:40])

    # Normalise overlay
    ov = brief.get("overlay", {})
    if isinstance(ov, str):
        brief["overlay"] = {"type": ov, "opacity": 170, "color": "#000000"}
    brief["overlay"].setdefault("opacity", 170)
    brief["overlay"].setdefault("color", "#000000")

    # Derive rendering parameters from layout type — keeps rendering consistent
    import re as _re
    layout = brief.get("layout", "full_card")
    word_count = len(text.split())
    sentence_count = len([s for s in _re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()])

    # Layout validation: enforce sensible bounds
    if word_count <= 12:
        layout = "big_center"
    elif layout == "big_center" and word_count > 25:
        layout = "sentence_reveal"
    # sentence_reveal only makes sense for multi-sentence quotes;
    # single long sentences mid-split look broken
    if layout == "sentence_reveal" and sentence_count < 2:
        layout = "full_card"
    brief["layout"] = layout

    if layout == "big_center":
        brief["font_size"]  = 108
        brief["text_zone"]  = "center"
        brief["animation"]  = "fade"
    elif layout == "sentence_reveal":
        brief["font_size"]  = 96
        brief["text_zone"]  = brief.get("text_zone", "bottom")
        brief["animation"]  = "reveal"
    else:  # full_card
        brief["font_size"]  = 88
        brief["text_zone"]  = brief.get("text_zone", "center")
        brief["animation"]  = "fade"

    logger.info(
        f"✓ Creative brief — layout={layout}  font={brief.get('font')}  "
        f"overlay={brief.get('overlay', {}).get('type')}  "
        f"zone={brief.get('text_zone')}"
    )

    return brief
