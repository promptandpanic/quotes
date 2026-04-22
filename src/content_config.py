"""
Loads topics.yml and styles.yml at startup.
Provides helpers used by quote_generator and design_director.
"""
import random
from pathlib import Path
import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"

# ── Load once at import ──────────────────────────────────────────────────────

def _load(filename: str) -> dict:
    path = _CONFIG_DIR / filename
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)

_topics = _load("topics.yml")["categories"]
_styles = _load("styles.yml")["styles"]

# Evocative scene hints for featured authors — NO human figures, symbols and atmosphere only
_AUTHOR_IMAGE_HINTS = {
    "Rumi": (
        "Persian manuscript unrolling in golden candlelight, intricate Islamic geometric patterns, "
        "swirling whirling-dervish fabric trails without any figure, rose petals on dark stone floor, "
        "warm amber and deep crimson palette. Painterly oil illustration, no people."
    ),
    "Swami Vivekananda": (
        "Saffron robes draped over ancient stone temple steps, single flame oil lamp, lotus pond "
        "at dawn with Himalayan peaks in mist, Om symbol carved in weathered stone. "
        "Painterly Indian miniature style, no human figures."
    ),
    "Kabir Das": (
        "Handloom weaving threads catching morning light in a humble mud-walled workshop, "
        "earthen oil lamp, marigold garland on a wooden loom, soft village dawn colours — "
        "ochre, terracotta, warm gold. Madhubani folk art illustration, no people."
    ),
    "APJ Abdul Kalam": (
        "Rocket launching into a vast starry night sky over the Indian coast, books and technical "
        "blueprints on a lit desk, crescent moon, warm amber desk lamp glow against deep navy. "
        "Watercolour illustration style, no human figures."
    ),
    "Khalil Gibran": (
        "Ancient Lebanese cedar tree alone on a cliff above the Mediterranean at dusk, open book "
        "with ink quill, moody indigo and burnt sienna sky, distant lighthouse. "
        "Romantic oil-painting illustration, no people."
    ),
    "Paulo Coelho": (
        "Desert caravan trail winding toward a distant horizon at golden hour, single lantern on "
        "cracked earth, open road, sparse stars appearing in a deep orange-to-indigo sky. "
        "Warm watercolour travel illustration, no human figures."
    ),
    "Chanakya": (
        "Ancient Pataliputra palace courtyard at night, clay oil lamps on stone steps, rolled "
        "Sanskrit scrolls, iron chess pieces on a stone slab, moonlight through carved stone "
        "lattice. Indian ink-wash illustration, no people."
    ),
    "Rabindranath Tagore": (
        "Lush Bengal riverbank at dawn — water hyacinth, mango grove, a wooden writing desk "
        "with ink and parchment by an open window, soft golden light filtering through leaves. "
        "Impressionist watercolour illustration, no human figures."
    ),
    "Osho": (
        "Zen garden with raked sand patterns, single burning incense stick, abstract light "
        "geometry dissolving into deep space, lotus floating on still dark water, soft purple "
        "and white palette. Dreamlike abstract painterly illustration, no people."
    ),
    "Maya Angelou": (
        "Vintage typewriter on a warm walnut desk surrounded by open poetry books with ink "
        "annotations, magnolia flowers in bloom, warm amber lamp glow, rich burgundy and gold "
        "palette. Painterly literary illustration, no human figures."
    ),
    "Malala Yousafzai": (
        "Stack of school books with a bright candle flame, open notebook and quill, "
        "educational symbols, warm golden light against deep teal darkness. "
        "Watercolour illustration, no people."
    ),
    "Chimamanda Ngozi Adichie": (
        "Vibrant West African kente cloth patterns framing an open book, ink quill, "
        "bold geometric shapes in crimson, gold, and deep green, warm candlelight. "
        "Graphic editorial illustration, no human figures."
    ),
    "Frida Kahlo": (
        "Vibrant Mexican folk art motifs — marigold flowers, colourful embroidery patterns, "
        "mirror frame decorated with painted vines and butterflies, warm terracotta and cobalt palette. "
        "Bold painterly illustration inspired by Mexican folk art, no people."
    ),
    "Indira Gandhi": (
        "Lotus flower on a still pool at dawn with Indian Parliament silhouette in mist, "
        "saffron and white palette, Indian flag colours, ancient stone steps by water. "
        "Painterly watercolour illustration, no human figures."
    ),
    "Arundhati Roy": (
        "Kerala backwaters at dusk — still dark water reflecting purple sky, open manuscript "
        "pages floating like petals, banyan tree roots, tropical monsoon atmosphere, "
        "deep violet and jade palette. Atmospheric watercolour illustration, no people."
    ),
    "Simone de Beauvoir": (
        "Parisian café table at dawn — untouched black coffee, philosophical manuscript pages, "
        "ink pen, bare window overlooking grey-blue Paris rooftops, single warm lamp against "
        "cool morning light, muted navy and cream palette. Moody editorial illustration, no people."
    ),
}

# Image hints per wisdom tradition — passed to design director so it can
# choose an illustration style that matches the cultural context
_TRADITION_IMAGE_HINTS = {
    "Indian wisdom": (
        "Indian Madhubani or miniature painting style — lotus flowers, peacock, ancient temple, "
        "or Vedic symbols. Vibrant illustrated folk art, NOT photorealistic."
    ),
    "Japanese wisdom": (
        "Japanese sumi-e ink painting — minimalist zen garden, bamboo grove, cherry blossoms, "
        "or torii gate in mist. Ink wash illustrated style."
    ),
    "Chinese proverb": (
        "Traditional Chinese ink wash painting — misty mountain peaks, pine trees, flowing river, "
        "or dragon motif. Brushstroke illustrated style."
    ),
    "elder wisdom": (
        "Painterly portrait of an ancient wise elder — long white beard, deep wrinkles, "
        "warm candlelight glow. Oil-painting or pencil illustration style, NOT a photograph."
    ),
    "nature wisdom": (
        "Serene nature illustration — lush forest, flowing river, quiet mountain, or patient animal "
        "in its habitat. Soft painterly brushwork, warm natural light. Illustrated, NOT photorealistic."
    ),
}


# ── Topics ───────────────────────────────────────────────────────────────────

def get_max_words(category: str) -> int:
    return _topics.get(category, {}).get("max_words", 28)


def get_topic_info(category: str) -> dict:
    """
    Returns {'topic_block': str, 'image_hint': str}.
    topic_block is injected into the quote prompt.
    image_hint is stored in the quote dict and used by the design director.
    """
    cfg = _topics.get(category, {})
    image_hint = ""

    # ── MORNING ──────────────────────────────────────────────────────────────
    if category == "morning":
        base = list(cfg.get("topics", []))
        extras: list[str] = []

        if random.random() < 0.30:
            extras.extend(cfg.get("workout_topics", []))

        pool = extras + base if extras else base
        random.shuffle(pool)
        lines = "\n".join(f"  - {t}" for t in pool[:12])
        topic_block = f"Pick from these topic areas. Prioritise the top of the list:\n{lines}"
        return {"topic_block": topic_block, "image_hint": image_hint}

    # ── WISDOM ───────────────────────────────────────────────────────────────
    if category == "wisdom":
        base     = list(cfg.get("topics", []))
        cultural = cfg.get("cultural_topics", [])
        authors  = cfg.get("featured_authors", [])

        roll = random.random()

        # 25% — featured author spotlight
        if authors and roll < 0.25:
            pick = random.choice(authors)
            name, note = pick["name"], pick["note"]
            topic_block = (
                f"TODAY: Find a quote by {name.upper()}.\n"
                f"Context: {note}\n\n"
                f"Rules:\n"
                f"  - Must be a REAL, verifiable quote genuinely attributed to {name}\n"
                f"  - Choose a lesser-known gem — not their most circulated line\n"
                f"  - Must resonate emotionally with an Indian aged 18-35 today"
            )
            author_image_hint = _AUTHOR_IMAGE_HINTS.get(name, "")
            return {"topic_block": topic_block, "image_hint": author_image_hint}

        # 40% — cultural tradition
        if cultural and roll < 0.65:
            tradition  = random.choice(cultural)
            trad_name  = tradition["tradition"]
            trad_topics = tradition["topics"]
            t_lines    = "\n".join(f"    - {t}" for t in trad_topics)
            image_hint = _TRADITION_IMAGE_HINTS.get(trad_name, "")
            topic_block = (
                f"TODAY focus on: {trad_name.upper()}\n"
                f"Find a real quote from this tradition. Topics in this tradition:\n{t_lines}\n\n"
                f"Also available (lower priority):\n"
                + "\n".join(f"  - {t}" for t in base[:4])
            )
            return {"topic_block": topic_block, "image_hint": image_hint}

        lines = "\n".join(f"  - {t}" for t in base)
        topic_block = f"Pick from these topic areas (rotate variety):\n{lines}"
        return {"topic_block": topic_block, "image_hint": image_hint}

    # ── LOVE ─────────────────────────────────────────────────────────────────
    if category == "love":
        base = list(cfg.get("topics", []))
        rg   = list(cfg.get("red_green_flag_topics", []))

        if rg and random.random() < 0.35:
            random.shuffle(rg)
            lines = "\n".join(f"  - {t}" for t in rg[:6])
            topic_block = (
                "TODAY: Red flag / Green flag content — very high engagement.\n"
                f"Focus on one of these angles:\n{lines}"
            )
            return {"topic_block": topic_block, "image_hint": image_hint}

        random.shuffle(base)
        lines = "\n".join(f"  - {t}" for t in base)
        topic_block = f"Pick from these topic areas (rotate variety):\n{lines}"
        return {"topic_block": topic_block, "image_hint": image_hint}

    # ── MINDFULNESS ──────────────────────────────────────────────────────────
    if category == "mindfulness":
        base      = list(cfg.get("topics", []))
        spiritual = list(cfg.get("spiritual_topics", []))

        if spiritual and random.random() < 0.40:
            random.shuffle(spiritual)
            lines = "\n".join(f"  - {t}" for t in spiritual[:5])
            topic_block = (
                "TODAY: Find a real verified quote from a well-known meditation or spiritual teacher.\n"
                f"Focus on one of these themes:\n{lines}\n\n"
                "IMPORTANT: Attribute the quote correctly to the real person who said it."
            )
            return {"topic_block": topic_block, "image_hint": image_hint}

        lines = "\n".join(f"  - {t}" for t in base)
        topic_block = f"Pick from these topic areas (rotate variety):\n{lines}"
        return {"topic_block": topic_block, "image_hint": image_hint}

    # ── WOMENPOWER ───────────────────────────────────────────────────────────
    if category == "womenpower":
        base = list(cfg.get("topics", []))
        random.shuffle(base)
        lines = "\n".join(f"  - {t}" for t in base[:20])
        fmt   = cfg.get("format_hint", "").strip()
        topic_block = (
            f"{fmt}\n\n" if fmt else ""
        ) + (
            "Pick ONE of these emotional angles and write from it:\n" + lines
        )
        return {"topic_block": topic_block, "image_hint": image_hint}

    # ── GENERIC (goodnight, latenight) ───────────────────────────────────────
    if "topics" in cfg:
        lines = "\n".join(f"  - {t}" for t in cfg["topics"])
        topic_block = f"Pick from these topic areas (rotate variety):\n{lines}"
        return {"topic_block": topic_block, "image_hint": image_hint}

    if "topic_groups" in cfg:
        groups = cfg["topic_groups"]
        lines = []
        for g in groups:
            pct = g.get("weight", 10)
            lines.append(f"\n  {g['name'].upper().replace('_', ' ')} (~{pct}% of posts):")
            if g.get("format_hint"):
                lines.append(f"    FORMAT: {g['format_hint']}")
            for t in g["topics"]:
                lines.append(f"    - {t}")
        topic_block = (
            "RANDOMLY select from these topic areas using approximate percentages:\n"
            + "\n".join(lines)
        )
        return {"topic_block": topic_block, "image_hint": image_hint}

    return {"topic_block": "", "image_hint": ""}


def get_topic_prompt_block(category: str) -> str:
    """Backward-compatible wrapper — returns only the topic block string."""
    return get_topic_info(category)["topic_block"]


# ── Styles ───────────────────────────────────────────────────────────────────

_WEIGHT_ORDER = {"high": 3, "medium": 2, "low": 1}


def get_styles_for_category(category: str) -> list[dict]:
    result = []
    for name, cfg in _styles.items():
        if category in cfg.get("categories", []):
            result.append({"name": name, **cfg})
    result.sort(key=lambda s: _WEIGHT_ORDER.get(s.get("weight", "medium"), 2), reverse=True)
    return result


def build_style_prompt_block(category: str) -> str:
    styles = get_styles_for_category(category)
    if not styles:
        return ""

    lines = ["IMAGE STYLE — choose the one that will make this post unmissable."]
    lines.append("Pick based on THIS SPECIFIC QUOTE's emotion. Rotate freely.\n")

    for s in styles:
        desc = s["description"].strip().split("\n")[0].strip()
        weight_note = " ★" if s.get("weight") == "high" else ""
        lines.append(f"  {s['name']}{weight_note}")
        lines.append(f"      {desc}")

    lines.append(
        '\nState the chosen style in brackets at the START of your image_prompt, '
        'e.g. "[cozy_aesthetic]".'
    )
    return "\n".join(lines)
