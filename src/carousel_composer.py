"""
Carousel post composer — 5 slides built for save/swipe engagement.

Why carousels for quote content:
  - IG feed carousels drive significantly more saves than Reels for text-based
    content because viewers can swipe through and screenshot a specific slide.
  - Each swipe is a dwell-time signal the ranker weighs heavily.

Narrative design — each slide earns its swipe:
  1. SETUP  — first clause / cliffhanger (drives swipe to slide 2)
  2. PUNCH  — the brief's highlight phrase in accent colour
  3. QUOTE  — full quote on sharp AI art with a backdrop card
  4. SAVE   — explicit save / tag prompt
  5. FOLLOW — "Follow for more" final CTA

Visual identity: every slide honours `brief.font` and `brief.highlight_color`
so the carousel feels like one consistent piece.
"""
import io
import logging
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.config import IMAGE_HEIGHT, IMAGE_WIDTH
from src.image_composer import _font, compose

logger = logging.getLogger(__name__)

SLIDE_W = 1080
SLIDE_H = 1350

HANDLE = "@_daily_dose_of_wisdom__"

# Fonts that don't hold up at the huge display sizes the setup / punch /
# follow slides use — fall back to a solid serif that scales cleanly.
_UNSTABLE_AT_LARGE = {
    "dancing", "satisfy", "pacifico",
    "caveat", "kalam", "indieflower", "specialelite",
}


# ---------------------------------------------------------------------------
# Background preparation
# ---------------------------------------------------------------------------

def _prepare_base(image_bytes: bytes) -> Image.Image:
    """Center-crop the 9:16 raw image (1080×1920) to 4:5 (1080×1350)."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    target_ratio = SLIDE_W / SLIDE_H
    src_ratio    = w / h
    if abs(src_ratio - target_ratio) < 0.01:
        return img.resize((SLIDE_W, SLIDE_H), Image.LANCZOS)
    if src_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left  = (w - new_w) // 2
        img   = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top   = (h - new_h) // 2
        img   = img.crop((0, top, w, top + new_h))
    return img.resize((SLIDE_W, SLIDE_H), Image.LANCZOS)


def _blur_and_darken(img: Image.Image, blur_radius: int = 22,
                     darken: int = 150) -> Image.Image:
    out = img.filter(ImageFilter.GaussianBlur(radius=blur_radius)).convert("RGBA")
    out.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, darken)))
    return out.convert("RGB")


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _wrap_to_fit(text: str, font_key: str, max_font: int, min_font: int,
                 max_w: int, max_h: int) -> tuple[list[str], ImageFont.ImageFont]:
    """Binary-search font size so wrapped text fits in (max_w × max_h)."""
    def _wrap(f):
        lines, cur = [], ""
        for w in text.split():
            trial = (cur + " " + w).strip()
            bbox  = f.getbbox(trial)
            if bbox[2] - bbox[0] <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    size = max_font
    while size >= min_font:
        f = _font(font_key, size)
        lines = _wrap(f)
        line_h = (f.getbbox("Ay")[3] - f.getbbox("Ay")[1]) + 14
        total_h = line_h * len(lines)
        max_line_w = max(f.getbbox(ln)[2] - f.getbbox(ln)[0] for ln in lines)
        if total_h <= max_h and max_line_w <= max_w:
            return lines, f
        size -= 6
    return lines, f


def _draw_centered_block(img: Image.Image, lines: list[str], font,
                         fill: tuple, y_center: int,
                         stroke_width: int = 0, stroke_fill=None) -> int:
    """Draw wrapped text centred around y_center. Returns the total block height."""
    draw   = ImageDraw.Draw(img)
    line_h = (font.getbbox("Ay")[3] - font.getbbox("Ay")[1]) + 14
    total  = line_h * len(lines)
    y      = y_center - total // 2
    for ln in lines:
        tw = font.getbbox(ln)[2] - font.getbbox(ln)[0]
        x  = (img.size[0] - tw) // 2
        draw.text((x, y), ln, font=font, fill=fill,
                  stroke_width=stroke_width, stroke_fill=stroke_fill)
        y += line_h
    return total


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = (h or "#FFD54F").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (255, 213, 79)   # warm amber fallback


def _safe_font(brief: dict) -> str:
    key = brief.get("font", "playfair") or "playfair"
    if key in _UNSTABLE_AT_LARGE:
        return "playfair"
    if key == "playfair_it":
        return "playfair"
    return key


# ---------------------------------------------------------------------------
# Quote splitting — find a natural setup / punch break
# ---------------------------------------------------------------------------

def _narrative_beats(text: str, highlight: str) -> list[tuple[str, str]]:
    """Return a list of (slide_text, kind) beats to build narrative slides.
    kind: 'plain' → white text on partial-blur
          'punch' → accent-coloured text on partial-blur (the last beat)

    Structure adapts to how the quote is written:
      - 3+ sentences           → one sentence per beat (up to 4)
      - 2 sentences / clauses  → setup + punch
      - 1 sentence w/ highlight → split on highlight → setup + punch
      - 1 sentence no split    → single 'punch' beat (whole quote)

    The final beat is always marked 'punch' so it renders in the brief's
    accent colour — gives the sequence a visible resolution."""
    text = text.strip()
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]

    def _finalise(pieces: list[str]) -> list[tuple[str, str]]:
        clean = [p.rstrip(".!?") for p in pieces if p.strip()]
        if not clean:
            return [(text.rstrip(".!?"), "punch")]
        return [(p, "plain") for p in clean[:-1]] + [(clean[-1], "punch")]

    # 3+ sentences — one per beat, capped at 4 for swipe fatigue
    if len(sentences) >= 3:
        return _finalise(sentences[:4])

    # 2 sentences — classic setup / punch
    if len(sentences) == 2:
        return _finalise(sentences)

    # Single sentence — try highlight split
    hl = (highlight or "").strip().rstrip(".!?,").strip()
    if hl and len(hl.split()) >= 2:
        idx = text.lower().rfind(hl.lower())
        if idx > 0:
            setup = text[:idx].rstrip(" -—–,.;:").strip()
            punch = text[idx:].strip()
            if setup and punch:
                return _finalise([setup, punch])

    # Dash / em-dash split
    for sep in [" — ", " – ", " - "]:
        if sep in text:
            a, b = text.split(sep, 1)
            return _finalise([a.strip(), b.strip()])

    # Comma split — only if each side has 3+ words
    if "," in text:
        a, b = text.split(",", 1)
        if len(a.split()) >= 3 and len(b.split()) >= 3:
            return _finalise([a.strip(), b.strip()])

    # No natural split — just a single beat
    return [(text.rstrip(".!?"), "punch")]


# ---------------------------------------------------------------------------
# Text-card helper — used by the full-quote slide
# ---------------------------------------------------------------------------

def _paint_text_card(image_bytes: bytes, text_zone: str) -> bytes:
    """Paint a dark rounded card into the image's text region so the
    remaining AI art stays crisp and visible outside of it."""
    img  = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    W, H = img.size

    if text_zone == "top":
        y0, y1 = int(H * 0.04), int(H * 0.47)
    elif text_zone == "bottom":
        y0, y1 = int(H * 0.40), int(H * 0.93)
    else:
        y0, y1 = int(H * 0.20), int(H * 0.80)

    x0, x1 = int(W * 0.04), int(W * 0.96)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(
        [x0, y0, x1, y1], radius=36, fill=(0, 0, 0, 190),
    )
    img.alpha_composite(overlay)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Narrative beat slide — one per sentence / clause of the quote.
# Partial blur (lighter than slides 4/5) so the Leonardo art remains
# visible behind the text, while the darken + text stroke still guarantee
# readability. Last beat ('punch') renders in the brief's accent colour.
# ---------------------------------------------------------------------------

def _slide_beat(base: Image.Image, beat_text: str, kind: str,
                brief: dict, is_last: bool) -> bytes:
    img = _blur_and_darken(base, blur_radius=12, darken=135)
    font_key = _safe_font(brief)
    accent   = _hex_to_rgb(brief.get("highlight_color", "#FFD54F"))

    fill = accent if kind == "punch" else (255, 255, 255)
    max_font = 150 if kind == "punch" else 130

    lines, f = _wrap_to_fit(
        beat_text.upper() if font_key == "bebas" else beat_text,
        font_key,
        max_font=max_font, min_font=64,
        max_w=SLIDE_W - 140,
        max_h=int(SLIDE_H * 0.60),
    )
    _draw_centered_block(img, lines, f,
                         fill=fill,
                         y_center=SLIDE_H // 2,
                         stroke_width=3, stroke_fill=(0, 0, 0))

    d = ImageDraw.Draw(img)
    if not is_last:
        hf = _font("lato", 30)
        hint = "swipe →"
        tw = hf.getbbox(hint)[2] - hf.getbbox(hint)[0]
        d.text(((SLIDE_W - tw) // 2, SLIDE_H - 100), hint,
               font=hf, fill=(220, 220, 220))
    hf2 = _font("lato", 24)
    hw_ = hf2.getbbox(HANDLE)[2] - hf2.getbbox(HANDLE)[0]
    d.text(((SLIDE_W - hw_) // 2, SLIDE_H - 52), HANDLE,
           font=hf2, fill=(180, 180, 180))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Slide 3 — FULL QUOTE (sharp art + backdrop card)
# ---------------------------------------------------------------------------

def _slide_quote(image_bytes: bytes, quote: dict, brief: dict) -> bytes:
    zone = brief.get("text_zone", "center")
    carded = _paint_text_card(image_bytes, zone)

    # Suppress the brief's own overlay so it doesn't layer on top of the card.
    card_brief = dict(brief)
    card_brief["overlay"] = {"type": "none"}

    full_9x16 = compose(carded, quote, card_brief)
    img = Image.open(io.BytesIO(full_9x16)).convert("RGB")

    target_h = int(img.width * SLIDE_H / SLIDE_W)
    if zone == "top":
        top = 0
    elif zone == "bottom":
        top = img.height - target_h
    else:
        top = (img.height - target_h) // 2
    img = img.crop((0, top, img.width, top + target_h))
    img = img.resize((SLIDE_W, SLIDE_H), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Slide 4 — SAVE / engagement prompt
# ---------------------------------------------------------------------------

def _slide_save(base: Image.Image, brief: dict) -> bytes:
    img = _blur_and_darken(base, blur_radius=30, darken=185)
    font_key = _safe_font(brief)
    accent   = _hex_to_rgb(brief.get("highlight_color", "#FFD54F"))

    # Heading
    heading = "Save this"
    lines, f = _wrap_to_fit(heading, font_key,
                            max_font=140, min_font=80,
                            max_w=SLIDE_W - 140,
                            max_h=int(SLIDE_H * 0.22))
    _draw_centered_block(img, lines, f,
                         fill=accent,
                         y_center=int(SLIDE_H * 0.38),
                         stroke_width=2, stroke_fill=(0, 0, 0))

    # Sub-prompt
    sub = "for the night you need it back."
    sub_lines, sf = _wrap_to_fit(sub, "lato",
                                 max_font=52, min_font=32,
                                 max_w=SLIDE_W - 180,
                                 max_h=int(SLIDE_H * 0.18))
    _draw_centered_block(img, sub_lines, sf,
                         fill=(235, 235, 235),
                         y_center=int(SLIDE_H * 0.55))

    # Hairline divider
    d  = ImageDraw.Draw(img)
    cx = SLIDE_W // 2
    d.line([(cx - 160, int(SLIDE_H * 0.64)),
            (cx + 160, int(SLIDE_H * 0.64))],
           fill=(150, 150, 150), width=2)

    # Tag prompt
    tag = "Tag someone who lives in this line."
    t_lines, tf = _wrap_to_fit(tag, "lato",
                               max_font=44, min_font=28,
                               max_w=SLIDE_W - 180,
                               max_h=int(SLIDE_H * 0.14))
    _draw_centered_block(img, t_lines, tf,
                         fill=(225, 225, 225),
                         y_center=int(SLIDE_H * 0.73))

    # Handle at bottom
    hf = _font("lato", 24)
    hw_ = hf.getbbox(HANDLE)[2] - hf.getbbox(HANDLE)[0]
    d.text(((SLIDE_W - hw_) // 2, SLIDE_H - 52), HANDLE,
           font=hf, fill=(170, 170, 170))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Slide 5 — FOLLOW CTA
# ---------------------------------------------------------------------------

def _slide_follow(base: Image.Image, brief: dict) -> bytes:
    img = _blur_and_darken(base, blur_radius=30, darken=195)
    font_key = _safe_font(brief)
    accent   = _hex_to_rgb(brief.get("highlight_color", "#FFD54F"))
    d = ImageDraw.Draw(img)

    # "Follow for more"
    heading = "Follow for more"
    lines, f = _wrap_to_fit(heading, font_key,
                            max_font=115, min_font=70,
                            max_w=SLIDE_W - 140,
                            max_h=int(SLIDE_H * 0.18))
    _draw_centered_block(img, lines, f,
                         fill=(255, 255, 255),
                         y_center=int(SLIDE_H * 0.42),
                         stroke_width=2, stroke_fill=(0, 0, 0))

    # Handle in accent
    hf = _font("lato_bold", 52)
    tw = hf.getbbox(HANDLE)[2] - hf.getbbox(HANDLE)[0]
    d.text(((SLIDE_W - tw) // 2, int(SLIDE_H * 0.54)), HANDLE,
           font=hf, fill=accent)

    # Divider
    cx = SLIDE_W // 2
    d.line([(cx - 180, int(SLIDE_H * 0.62)),
            (cx + 180, int(SLIDE_H * 0.62))],
           fill=(160, 160, 160), width=2)

    # Two-line CTA
    f_cta = _font("lato", 42)
    for i, text in enumerate(["Daily feelings that hit right.",
                              "Words you'll want to screenshot."]):
        tw = f_cta.getbbox(text)[2] - f_cta.getbbox(text)[0]
        d.text(((SLIDE_W - tw) // 2, int(SLIDE_H * 0.68) + i * 68),
               text, font=f_cta, fill=(230, 230, 230))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compose_carousel(image_bytes: bytes, quote: dict, brief: dict) -> list[bytes]:
    """Return variable-length carousel:
       [beat_1, beat_2, ..., full_quote, save, follow] JPEG bytes at 1080×1350.

    Number of narrative beats depends on quote structure — 3+ sentence quotes
    get one beat per sentence (up to 4); 2-sentence quotes get setup/punch;
    single-sentence quotes get one beat."""
    base  = _prepare_base(image_bytes)
    beats = _narrative_beats(quote.get("text", ""), brief.get("highlight", ""))

    logger.info(f"  Carousel beats ({len(beats)}):")
    for i, (t, k) in enumerate(beats, 1):
        logger.info(f"    {i}. [{k:5s}] {t[:80]}")

    slides: list[bytes] = []
    for i, (beat_text, kind) in enumerate(beats):
        is_last = (i == len(beats) - 1)
        slides.append(_slide_beat(base, beat_text, kind, brief, is_last))

    slides.append(_slide_quote(image_bytes, quote, brief))
    slides.append(_slide_save(base, brief))
    slides.append(_slide_follow(base, brief))
    return slides
