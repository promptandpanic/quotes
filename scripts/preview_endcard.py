"""Render the final (100% scale) end-card frame composited over each
static fallback background, so we can visually verify the adaptive colour."""
import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, ".")

from src.video_creator import _render_handle_zoom_frames, IMAGE_WIDTH, IMAGE_HEIGHT

OUT = Path("output")
OUT.mkdir(exist_ok=True)

# One full-scale, fully-opaque end-card frame per background.
bgs = ["latenight.jpg", "wisdom.jpg", "morning.jpg", "womenpower.jpg", "mindfulness.jpg"]

for name in bgs:
    bg_path = Path("assets/static") / name
    if not bg_path.exists():
        continue

    base = Image.open(bg_path).convert("RGB").resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.LANCZOS)

    # Use a temp dir with a single frame (last frame = full scale, full alpha)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        _render_handle_zoom_frames(dp, n_frames=2, base_pil=base)
        overlay = Image.open(dp / "h001.png").convert("RGBA")

    composed = base.convert("RGBA")
    composed.alpha_composite(overlay)
    out_path = OUT / f"endcard_{Path(name).stem}.jpg"
    composed.convert("RGB").save(out_path, quality=92)
    print(f"  → {out_path}")
