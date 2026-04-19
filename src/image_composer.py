"""
Pure renderer — executes whatever Gemini's creative brief specifies.

Text layout is 100% math-driven — no LLM wrap guesses:
  pixel_wrap()   — word-wraps to exact canvas width using font metrics
  _fit_text()    — auto-sizes font so the block always fits the zone
  get_reveal_counts() — computes per-sentence line counts for reveal animation,
                        using the same font/wrap logic as _draw_text so they
                        always match

Public API:
  compose(image_bytes, quote, brief)             → JPEG bytes  (all text)
  compose_partial(image_bytes, quote, brief, n)  → JPEG bytes  (first n lines only)
  compose_base(image_bytes, brief)               → PIL Image   (overlay, no text)
  get_reveal_counts(quote, brief)                → list[int]   (cumulative line counts)
"""
import io
import logging
import re
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.config import IMAGE_HEIGHT, IMAGE_WIDTH, WATERMARK_TEXT

logger = logging.getLogger(__name__)

FONTS_DIR    = Path("assets/fonts")
MARGIN_X     = 60                              # left + right padding (px each side)
TEXT_MAX_W   = IMAGE_WIDTH - 2 * MARGIN_X      # 960px usable text width

# Max block height per text zone — text auto-shrinks only as last resort
_ZONE_MAX_H = {
    "top":    int(IMAGE_HEIGHT * 0.60),
    "center": int(IMAGE_HEIGHT * 0.82),
    "bottom": int(IMAGE_HEIGHT * 0.72),
}

_FONT_URLS = {
    # Display / bold
    "bebas":        ("bebas.ttf",            "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf"),
    "oswald":       ("oswald_bold.ttf",      "https://fonts.gstatic.com/s/oswald/v57/TK3_WkUHHAIjg75cFRf3bXL8LICs1xZogUE.ttf"),
    "montserrat":   ("montserrat_bold.ttf",  "https://fonts.gstatic.com/s/montserrat/v31/JTUHjIg1_i6t8kCHKm4532VJOt5-QNFgpCuM70w-.ttf"),
    "raleway":      ("raleway_bold.ttf",     "https://fonts.gstatic.com/s/raleway/v37/1Ptxg8zYS_SKggPN4iEgvnHyvveLxVs9pYCP.ttf"),
    "anton":        ("anton.ttf",            "https://fonts.gstatic.com/s/anton/v27/1Ptgg87LROyAm0K0.ttf"),
    "cinzel":       ("cinzel_bold.ttf",      "https://fonts.gstatic.com/s/cinzel/v26/8vIU7ww63mVu7gtR-kwKxNvkNOjw-jHgTYo.ttf"),
    "josefin":      ("josefin_bold.ttf",     "https://fonts.gstatic.com/s/josefinsans/v34/Qw3PZQNVED7rKGKxtqIqX5E-AVSJrOCfjY46_N_XXME.ttf"),
    # Serif
    "playfair":     ("playfair_bold.ttf",    "https://fonts.gstatic.com/s/playfairdisplay/v40/nuFRD-vYSZviVYUb_rj3ij__anPXDTnCjmHKM4nYO7KN_qiTbtY.ttf"),
    "playfair_it":  ("playfair_it.ttf",      "https://fonts.gstatic.com/s/playfairdisplay/v40/nuFvD-vYSZviVYUb_rj3ij__anPXJzDwcbmjWBN2PKeiukDQ.ttf"),
    "merriweather": ("merriweather_bold.ttf","https://fonts.gstatic.com/s/merriweather/v33/u-4D0qyriQwlOrhSvowK_l5UcA6zuSYEqOzpPe3HOZJ5eX1WtLaQwmYiScCmDxhtNOKl8yDrOSAqEw.ttf"),
    "cormorant":    ("cormorant_bold.ttf",   "https://fonts.gstatic.com/s/cormorantgaramond/v21/co3smX5slCNuHLi8bLeY9MK7whWMhyjYrGFEsdtdc62E6zd5LDfOjw.ttf"),
    # Script
    "dancing":      ("dancing.ttf",          "https://fonts.gstatic.com/s/dancingscript/v29/If2cXTr6YS-zF4S-kcSWSVi_sxjsohD9F50Ruu7B1i0HTQ.ttf"),
    "satisfy":      ("satisfy.ttf",          "https://fonts.gstatic.com/s/satisfy/v22/rP2Hp2yn6lkG50LoOZQ.ttf"),
    # Texture / character
    "specialelite": ("specialelite.ttf",     "https://github.com/google/fonts/raw/main/apache/specialelite/SpecialElite-Regular.ttf"),
    # Utility (always downloaded — fallback font)
    "lato":         ("lato.ttf",             "https://github.com/google/fonts/raw/main/ofl/lato/Lato-Regular.ttf"),
    "lato_bold":    ("lato_bold.ttf",        "https://github.com/google/fonts/raw/main/ofl/lato/Lato-Bold.ttf"),
    "lato_light":   ("lato_light.ttf",       "https://github.com/google/fonts/raw/main/ofl/lato/Lato-Light.ttf"),
}

_font_cache: dict = {}


def _ensure_fonts() -> None:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for key, (filename, url) in _FONT_URLS.items():
        path = FONTS_DIR / filename
        if not path.exists():
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200:
                    path.write_bytes(r.content)
                    logger.info(f"  ✓ Font: {filename}")
            except Exception as exc:
                logger.warning(f"  ✗ Font {filename}: {exc}")


def _font(key: str, size: int) -> ImageFont.FreeTypeFont:
    ck = f"{key}_{size}"
    if ck not in _font_cache:
        _ensure_fonts()
        filename = _FONT_URLS.get(key, ("",))[0]
        path = FONTS_DIR / filename
        try:
            _font_cache[ck] = ImageFont.truetype(str(path), size)
        except Exception:
            # Fall back to lato (always present) — never use the 11px bitmap default
            lato_path = FONTS_DIR / _FONT_URLS["lato"][0]
            try:
                logger.warning(f"Font '{key}' unavailable — falling back to lato at {size}pt")
                _font_cache[ck] = ImageFont.truetype(str(lato_path), size)
            except Exception:
                _font_cache[ck] = ImageFont.truetype(str(FONTS_DIR / _FONT_URLS["lato_bold"][0]), size)
    return _font_cache[ck]


# ---------------------------------------------------------------------------
# Drawing utilities
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple:
    # Gemini sometimes appends description text — extract just the hex code
    m = re.search(r'#([0-9A-Fa-f]{6})', str(hex_color))
    if m:
        h = m.group(1)
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    return (255, 200, 50)


def _tw(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return draw.textbbox((0, 0), text, font=font)[2]


def _centered_x(draw, text, font, width=IMAGE_WIDTH) -> int:
    return (width - _tw(draw, text, font)) // 2


def pixel_wrap(text: str, font: ImageFont.FreeTypeFont,
               max_width: int = TEXT_MAX_W) -> list[str]:
    """Pixel-accurate word wrap — guaranteed to never exceed max_width."""
    words = text.split()
    lines: list[str] = []
    cur: list[str] = []
    for word in words:
        candidate = " ".join(cur + [word])
        bb = font.getbbox(candidate)
        w = bb[2] - bb[0]
        if w <= max_width:
            cur.append(word)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [word]   # single word may still be wide — force it on its own line
    if cur:
        lines.append(" ".join(cur))
    return lines or [text]


def _layout_lines(disp_text: str, font: ImageFont.FreeTypeFont,
                  layout: str) -> list[str]:
    """Wrap text.  sentence_reveal wraps each sentence separately so sentence
    boundaries always coincide with line boundaries."""
    if layout == "sentence_reveal":
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', disp_text.strip())
                     if s.strip()]
        if len(sentences) > 1:
            lines: list[str] = []
            for sent in sentences:
                lines.extend(pixel_wrap(sent, font))
            return lines
    return pixel_wrap(disp_text, font)


def _fit_text(disp_text: str, font_key: str, font_size: int,
              layout: str, zone: str) -> tuple[list[str], ImageFont.FreeTypeFont, int]:
    """Return (lines, font, size) using the largest font where the block fits the zone.
    Minimum floor is 80pt — text is never shrunk below that regardless of fit."""
    max_h = _ZONE_MAX_H.get(zone, int(IMAGE_HEIGHT * 0.75))
    for size in range(font_size, 80, -2):
        f = _font(font_key, size)
        lines = _layout_lines(disp_text, f, layout)
        if len(lines) * int(size * 1.28) <= max_h:
            return lines, f, size
    # Floor: always render at minimum 82pt — let it overflow rather than shrink text
    size = 82
    f = _font(font_key, size)
    return _layout_lines(disp_text, f, layout), f, size


def _sanitize(text: str) -> str:
    """Replace/strip characters that fonts can't render (would show as □ boxes)."""
    import unicodedata
    # Common punctuation substitutions
    text = (text
            .replace('\u2014', ' - ')   # em-dash
            .replace('\u2013', '-')     # en-dash
            .replace('\u2026', '...')   # ellipsis
            .replace('\u00e9', 'e').replace('\u00e8', 'e').replace('\u00ea', 'e')
            .replace('\u00e0', 'a').replace('\u00e2', 'a')
            .replace('\u00f4', 'o').replace('\u00fb', 'u')
            )
    # Strip emojis and all non-BMP characters (emoji are U+1F000+)
    return "".join(
        ch for ch in text
        if ord(ch) < 0x10000 and unicodedata.category(ch) not in ("So", "Cs")
    )


def _shadow_text(draw, xy, text, font, fill, shadow=(0, 0, 0), depth=3):
    x, y = xy
    draw.text((x + depth, y + depth), text, font=font, fill=shadow + (160,))
    draw.text((x, y), text, font=font, fill=fill)


def _gradient_rect(img: Image.Image, y0: int, y1: int,
                   color: tuple = (0, 0, 0), max_alpha: int = 180) -> Image.Image:
    """Gradient from transparent → opaque, top-to-bottom between y0 and y1."""
    rgba = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    height = y1 - y0
    for y in range(y0, y1):
        a = int(max_alpha * ((y - y0) / height) ** 0.55)
        draw.line([(0, y), (IMAGE_WIDTH, y)], fill=(*color, a))
    return Image.alpha_composite(rgba, overlay).convert("RGB")


def _gradient_rect_from_top(img: Image.Image, y0: int, y1: int,
                             color: tuple = (0, 0, 0), max_alpha: int = 180) -> Image.Image:
    """Gradient from opaque at top → transparent at bottom."""
    rgba = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    height = y1 - y0
    for y in range(y0, y1):
        frac = (y - y0) / height
        a = int(max_alpha * (1 - frac) ** 0.55)
        draw.line([(0, y), (IMAGE_WIDTH, y)], fill=(*color, a))
    return Image.alpha_composite(rgba, overlay).convert("RGB")


def _solid_overlay(img: Image.Image, opacity: int,
                   color: tuple = (0, 0, 0)) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (*color, opacity))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _vignette(img: Image.Image, intensity: int = 160) -> Image.Image:
    w, h = img.size
    rgba = img.convert("RGBA")
    vig = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(vig)
    for i in range(min(w, h) // 2, 0, -1):
        alpha = int(intensity * (1 - (i / (min(w, h) / 2))) ** 1.8)
        draw.ellipse([w//2 - i, h//2 - i, w//2 + i, h//2 + i],
                     outline=(0, 0, 0, alpha), width=4)
    return Image.alpha_composite(rgba, vig).convert("RGB")


def _watermark(draw: ImageDraw.ImageDraw) -> None:
    wm_font = _font("lato_light", 22)
    w = _tw(draw, WATERMARK_TEXT, wm_font)
    draw.text(((IMAGE_WIDTH - w) // 2, IMAGE_HEIGHT - 50),
              WATERMARK_TEXT, font=wm_font, fill=(200, 200, 200, 180))


# ---------------------------------------------------------------------------
# Core overlay + text rendering
# ---------------------------------------------------------------------------

def _apply_overlay(img: Image.Image, brief: dict) -> Image.Image:
    ov = brief.get("overlay", {})
    if isinstance(ov, str):
        ov = {"type": ov, "opacity": 170}

    otype   = ov.get("type", "gradient_bottom")
    opacity = int(ov.get("opacity", 170))
    color   = _hex_to_rgb(ov.get("color", "#000000"))

    if otype == "gradient_bottom":
        # Start at 20% so text at bottom always has strong dark backing
        return _gradient_rect(img, int(IMAGE_HEIGHT * 0.20), IMAGE_HEIGHT,
                              color=color, max_alpha=opacity)
    elif otype == "gradient_top":
        return _gradient_rect_from_top(img, 0, int(IMAGE_HEIGHT * 0.60),
                                       color=color, max_alpha=opacity)
    elif otype == "gradient_center":
        # Two-sided: dark at center, fade out top + bottom
        img = _gradient_rect(img, int(IMAGE_HEIGHT * 0.25), int(IMAGE_HEIGHT * 0.78),
                             color=color, max_alpha=opacity)
        return _gradient_rect_from_top(img, int(IMAGE_HEIGHT * 0.22),
                                       int(IMAGE_HEIGHT * 0.52),
                                       color=color, max_alpha=opacity // 2)
    elif otype == "solid":
        return _solid_overlay(img, opacity, color=color)
    elif otype == "vignette":
        return _vignette(img, intensity=opacity)
    return img  # "none"




def _stroke_text(draw, xy, text, font, fill, stroke_color=(0, 0, 0), stroke=3):
    """Draw text with a multi-pixel outline for readability on any background."""
    x, y = xy
    for dx in range(-stroke, stroke + 1):
        for dy in range(-stroke, stroke + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    draw.text((x, y), text, font=font, fill=fill)


def _draw_text(img: Image.Image, quote: dict, brief: dict,
               n_lines: int | None = None) -> Image.Image:
    """
    Render quote text onto img according to brief spec.
    Layout is computed with pixel-accurate font metrics — no heuristics.
    n_lines: show only the first n wrapped lines (for reveal animation).
    """
    text       = _sanitize(quote["text"])
    author     = quote.get("author", "")
    font_key   = brief.get("font", "oswald")
    if font_key == "playfair_it":
        font_key = "playfair"
    txt_color  = _hex_to_rgb(brief.get("text_color", "#FFFFFF"))
    hi_color   = _hex_to_rgb(brief.get("highlight_color", "#FFD700"))
    text_zone  = brief.get("text_zone", "bottom")
    decoration = brief.get("decoration", "none")
    layout     = brief.get("layout", "full_card")
    hi_phrase  = _sanitize(brief.get("highlight") or "").lower()

    upper     = font_key == "bebas"
    disp_text = text.upper() if upper else text

    font_size = max(88, int(brief.get("font_size", 88)))
    all_lines, f, font_size = _fit_text(disp_text, font_key, font_size, layout, text_zone)

    lines  = all_lines[:n_lines] if n_lines is not None else all_lines
    line_h = int(font_size * 1.28)
    # Use full block height for y anchoring (keeps position stable across partial frames)
    block_h = len(all_lines) * line_h

    if text_zone == "top":
        y = int(IMAGE_HEIGHT * 0.08)
    elif text_zone == "center":
        y = (IMAGE_HEIGHT - block_h) // 2
    else:  # bottom
        y = IMAGE_HEIGHT - block_h - 100

    draw = ImageDraw.Draw(img)

    # Decoration
    if decoration == "rule":
        draw.line([(70, y - 20), (IMAGE_WIDTH - 70, y - 20)],
                  fill=(*hi_color, 220), width=3)
    elif decoration == "quote_mark":
        dq_font = _font("playfair", 260)
        draw.text((28, y - 40), "\u201c", font=dq_font, fill=(*hi_color, 30))

    # Text lines — highlight any line that contains the highlight phrase
    for line in lines:
        bb  = f.getbbox(line)
        lw  = bb[2] - bb[0]
        x   = (IMAGE_WIDTH - lw) // 2
        is_hi = hi_phrase and hi_phrase in line.lower()
        fill  = hi_color if is_hi else txt_color
        _stroke_text(draw, (x, y), line, f, fill=fill, stroke_color=(0, 0, 0), stroke=2)
        y += line_h

    # Author attribution (full frame only)
    if n_lines is None and author and not author.startswith("@"):
        a_font = _font("lato_light", 28)
        a_text = f"— {author}"
        bb  = a_font.getbbox(a_text)
        ax  = (IMAGE_WIDTH - (bb[2] - bb[0])) // 2
        draw.text((ax, y + 10), a_text, font=a_font, fill=(180, 180, 180))

    _watermark(draw)
    return img


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_reveal_counts(quote: dict, brief: dict) -> list[int]:
    """
    Cumulative wrapped-line counts per sentence for the reveal animation.
    Uses the exact same font + wrap logic as _draw_text so line indices always match.

    Returns a list like [4, 9] meaning:
      - step 1: show lines 0-3   (first sentence)
      - step 2: show lines 0-8   (full quote)
    """
    font_key  = brief.get("font", "oswald")
    if font_key == "playfair_it":
        font_key = "playfair"
    font_size = max(88, int(brief.get("font_size", 88)))
    text      = _sanitize(quote["text"])
    upper     = font_key == "bebas"
    disp_text = text.upper() if upper else text
    zone      = brief.get("text_zone", "bottom")

    all_lines, f, _ = _fit_text(disp_text, font_key, font_size, "sentence_reveal", zone)

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', disp_text.strip())
                 if s.strip()]

    if len(sentences) <= 1:
        n = len(all_lines)
        if n <= 3:
            return [n]
        mid = (n + 1) // 2
        return [mid, n]

    # Multi-sentence: pixel_wrap each sentence with same font → exact line counts
    cumulative, total = [], 0
    for sent in sentences:
        total += len(pixel_wrap(sent, f))
        cumulative.append(total)
    return cumulative


def compose(image_bytes: bytes, quote: dict, brief: dict) -> bytes:
    """Full compose — all lines rendered."""
    img = _load(image_bytes)
    img = _apply_overlay(img, brief)
    img = _draw_text(img, quote, brief)
    return _to_jpeg(img)


def compose_partial(image_bytes: bytes, quote: dict, brief: dict,
                    n_lines: int) -> bytes:
    """Compose with only the first n_lines visible (for reveal animation)."""
    img = _load(image_bytes)
    img = _apply_overlay(img, brief)
    img = _draw_text(img, quote, brief, n_lines=n_lines)
    return _to_jpeg(img)


def compose_base(image_bytes: bytes, brief: dict) -> Image.Image:
    """Return PIL Image with overlay applied but NO text (for video intro frame)."""
    img = _load(image_bytes)
    return _apply_overlay(img, brief)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if img.size != (IMAGE_WIDTH, IMAGE_HEIGHT):
        img = img.resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.LANCZOS)
    return img


def _to_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()
