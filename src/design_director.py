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
{recent_styles_block}

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

HIGHLIGHT STYLE — how the key phrase is visually distinguished from the rest of the quote:
  color       — key phrase in highlight_color only (clean, safe default)
  italic      — key phrase switches to elegant italic serif (Playfair Italic) — beautiful contrast on bold sans fonts like oswald/montserrat
  underline   — key phrase gets a solid underline bar in highlight_color — editorial, modern
  caps        — key phrase rendered in ALL CAPS — power, emphasis, punchy
  caps_italic — ALL CAPS + italic serif — dramatic editorial feel
  script      — key phrase switches to flowing script font (Dancing Script) — warm, emotional, great for love/goodnight

  Pairing guide:
  - bebas / anton / oswald + italic     → striking serif-on-sans contrast
  - playfair / cormorant + underline    → editorial elegance
  - montserrat / josefin + caps         → clean graphic emphasis
  - any font + script                   → emotional warmth (love, goodnight, latenight)
  - specialelite / lato + color         → keep it simple, texture does the work

IMAGE RULES (always apply):
  - Render with fine detail, visual clarity, and richness — the image should reward close inspection
  - Match the chosen style faithfully — a cozy aesthetic should feel almost tactile, a ghibli scene should feel hand-painted, a line art should feel precisely drawn
  - NEVER photorealistic humans or portrait photography — stylised figures (illustrated, painted, vector, anime) are fine when they serve the mood
  - No text, signs, logos, watermarks, or typography anywhere in the image
  - No generic stock-photo style compositions — every image should feel art-directed and intentional

TEXT PLACEMENT — CRITICAL RULES (read carefully, these directly affect image quality):

  STEP 1 — Decide WHERE the text will live BEFORE writing the image prompt:
  - text_zone: top    → text block sits in the upper 35% of the image
  - text_zone: center → text block sits across the middle third
  - text_zone: bottom → text block sits in the lower 35% of the image

  STEP 2 — Write the image_prompt so that zone is GENUINELY CLEAR:
  - If text_zone is top: the subject/scene must sit in the LOWER half. The top must be open sky,
    plain background, soft texture, or gradual fade — nothing visually complex.
  - If text_zone is bottom: the subject must sit in the UPPER half. Bottom must be clear.
  - If text_zone is center: the subject must hug the left or right edge, or be in extreme
    foreground/background. The center band must be uncluttered.
  - NEVER place the subject in the same zone you intend for text. Text on top of a character,
    face, or focal element is the single most common failure — eliminate it by design.

  STEP 3 — Match the overlay to the text_zone:
  - text_zone: top    → overlay type: gradient_top
  - text_zone: bottom → overlay type: gradient_bottom
  - text_zone: center → overlay type: gradient_center or vignette
  - Light/pale backgrounds (parchment, cream, white) in the text zone need opacity ≥ 180 to
    make white text readable. If background is very pale and overlay is light, use dark text instead.

FONT — match to the image's art style (wrong font breaks the mood entirely):
  - Vintage illustrated / anthropomorphic: cormorant or playfair
  - Watercolour / ink wash: satisfy or cormorant
  - Ghibli / anime: josefin or raleway
  - Cozy aesthetic / warm realism: merriweather or lato
  - Cinematic / dark dramatic: oswald or merriweather
  - Bold graphic poster / vector: bebas or anton
  - Line art / minimalist: josefin or lato
  - Late-night raw emotion: specialelite
  - Love / poetic: dancing or playfair

TEXT LAYOUT — pick ONE based on the quote's length and energy:

  big_center     — SHORT punchy quotes only (≤12 words, single sentence).
                   Huge text, centered on screen, bold and immediate.
                   Video: image fades in with text visible — static powerful hold.
                   Pick this for: morning energy, single-line wisdom, raw impact.

  sentence_reveal — MULTI-SENTENCE quotes (2-4 sentences).
                   Each complete sentence fades in one by one and stays visible.
                   Video: each sentence appears in sequence, full quote visible at end.
                   Pick this for: emotional late-night, wisdom with build-up, love quotes.

  full_card      — MEDIUM quotes (1-2 sentences, 12-30 words).
                   Full text visible from the start, clean hold.
                   Video: image crossfades in revealing all text.
                   Pick this for: mindfulness, goodnight, poetic single thoughts.

──────────────────────────────────────────────
Be specific and emotionally precise. The image must DIRECTLY evoke this quote's feeling.

Return ONLY valid JSON — no markdown, no text outside the JSON:
{{
  "image_prompt": "MUST start with [chosen_style_name] in brackets. Then write 5-6 richly detailed \
sentences: (1) Exact subject and action — who or what is in the scene, what they are doing, \
which specific emotion this conveys. (2) Setting and environment — time of day, location, \
surface textures, weather, atmosphere. (3) Art style execution — the specific technique, \
medium, brushwork, linework, or texture that defines the chosen style. (4) Full colour palette — \
4-5 colours with hex values and names (e.g. midnight blue #1a1a3e, warm ochre #c4832a). \
(5) Lighting — direction, quality, and emotional temperature. \
(6) Composition — EXPLICITLY state: where the subject sits in the 9:16 frame (upper half / \
lower half / left edge / right edge), and which zone (top third / bottom third / center band) \
is kept completely open, uncluttered, and visually simple for the quote text. The open zone \
must match text_zone exactly. Absolutely no text, signs, words, numbers, logos, or watermarks \
anywhere in the image. 9:16 portrait format.",

  "overlay": {{
    "type": "gradient_bottom|gradient_top|gradient_center|solid|vignette",
    "opacity": 140-220,
    "color": "#000000"
  }},

  "font": "bebas|anton|oswald|montserrat|cinzel|raleway|josefin|playfair|merriweather|cormorant|dancing|satisfy|specialelite|lato",
  "text_color": "#RRGGBB — CRITICAL: must have strong contrast against the overlay/background. \
If the overlay is dark (opacity ≥ 140), use near-white (#FFFFFF, #F5F5F5, #FFFAF0). \
If the overlay is light or the background is pale/bright, use near-black (#111111, #1a1a1a). \
NEVER pick a colour similar in brightness to the background — low contrast makes text unreadable.",
  "highlight_color": "#RRGGBB — accent colour for the key phrase. Must contrast with BOTH the \
background AND text_color. Avoid colours close in hue or brightness to text_color.",
  "author_color": "#RRGGBB — colour for the author name. Must be readable against the background. \
Often the highlight_color, a softer tint of it, or a warm off-white. \
Only rendered when a real author exists — skip for Unknown/anonymous.",
  "text_zone": "top|center|bottom — MUST match the open/clear zone described in image_prompt. \
top = subject in lower half, upper third is clear. \
bottom = subject in upper half, lower third is clear. \
center = subject at edges, center band is clear.",
  "decoration": "rule|quote_mark|none",
  "layout": "big_center|sentence_reveal|full_card",
  "highlight": "3-6 most emotionally powerful CONSECUTIVE words from the quote — \
the line someone screenshots",
  "highlight_style": "color|italic|underline|caps|caps_italic|script",
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
        "image_prompt": "[nocturnal_aesthetic] Deep midnight blue sky, large glowing moon, \
soft lanterns and rooftop silhouettes, warm luminous light against indigo darkness, \
lo-fi anime background painting energy — lower 40% open and dark for text. 9:16 portrait.",
        "overlay": {"type": "solid", "opacity": 210, "color": "#000005"},
        "font": "specialelite", "text_color": "#E0E0E0",
        "highlight_color": "#00CFCF", "decoration": "none",
        "layout": "sentence_reveal",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_brief(quote: dict, theme: str, recent_styles: list[str] | None = None) -> dict:
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
            from src.config import GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK
            from src.content_config import build_style_prompt_block

            client = genai.Client(api_key=api_key)
            style_block = build_style_prompt_block(theme)
            image_hint  = quote.get("image_hint", "")
            image_hint_block = (
                f"IMAGE DIRECTION: {image_hint}\n" if image_hint else ""
            )
            if recent_styles:
                unique = list(dict.fromkeys(recent_styles))[-10:]
                recent_styles_block = (
                    f"RECENTLY USED STYLES (last 14 days — avoid repeating unless clearly the best fit):\n"
                    f"  {', '.join(unique)}\n"
                )
            else:
                recent_styles_block = ""
            prompt = _BRIEF_PROMPT.format(
                text=text, theme=theme,
                style_block=style_block,
                image_hint_block=image_hint_block,
                recent_styles_block=recent_styles_block,
            )

            from google.genai import types as _types
            _cfg = _types.GenerateContentConfig(
                automatic_function_calling=_types.AutomaticFunctionCallingConfig(disable=True),
            )
            raw = None
            for _model in [GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK]:
                try:
                    response = client.models.generate_content(
                        model=_model, contents=prompt, config=_cfg,
                    )
                    raw = response.text.strip()
                    break
                except Exception as _exc:
                    if _model == GEMINI_TEXT_MODEL_FALLBACK:
                        raise
                    logger.warning(f"Creative director primary model failed: {_exc} — retrying with {GEMINI_TEXT_MODEL_FALLBACK}")
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
