"""
Animated Reel — 12-second video.

Two animation modes (Gemini picks):

  fade   — base image (0-2s) → full composed image (2-12s). Simple & bold.
  reveal — base (0-2s), then each SENTENCE fades in one by one.
           Full quote always visible by the end. Complete thoughts, not cut lines.

Audio: Om meditation loop throughout.
"""
import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from src.config import AUDIO_FILE, IMAGE_HEIGHT, IMAGE_WIDTH, REEL_DURATION_SEC
from src.image_composer import compose, compose_base, compose_partial, get_reveal_counts

logger = logging.getLogger(__name__)

FPS           = 25
INTRO_SEC     = 2.0    # background-only intro
CROSSFADE_SEC = 0.5    # xfade between segments
PER_SEG_SEC   = 4.0    # time to read each sentence/group
HOLD_SEC      = 2.5    # final hold after all text is revealed


def _audio_path(theme: str) -> str:
    """Return theme-specific audio if it exists, else the default background track."""
    theme_file = Path(f"assets/audio/{theme}.mp3").resolve()
    if theme_file.exists():
        return str(theme_file)
    return str(Path(AUDIO_FILE).resolve())


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# Reveal helpers
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# ffmpeg filter builder (correct per-filter offsets)
# ---------------------------------------------------------------------------

def _build_xfade_filter(N: int, durs: list[float], cf: float) -> str:
    """
    Build a chained xfade filtergraph for N still-image inputs.

    IMPORTANT: xfade `offset` is measured from the start of THAT filter's
    first input (the accumulated stream so far), NOT from the global start.
    Each transition offset = accumulated_stream_duration - cf.
    """
    W, H = IMAGE_WIDTH, IMAGE_HEIGHT
    parts = []

    # Scale + pad every input to exact canvas size
    for i in range(N):
        parts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}[v{i}]"
        )

    # Chain xfade — offset is relative to the START of the accumulated stream
    stream_dur = durs[0]
    prev = "v0"
    for i in range(1, N):
        offset = max(0.0, stream_dur - cf)
        label  = f"xf{i}" if i < N - 1 else "vout"
        parts.append(
            f"[{prev}][v{i}]xfade=transition=fade:"
            f"duration={cf}:offset={offset:.3f}[{label}]"
        )
        prev = label
        stream_dur += durs[i] - cf  # accumulated output length after this xfade

    return ";".join(parts)


# ---------------------------------------------------------------------------
# Fade animation
# ---------------------------------------------------------------------------

def _create_reel_fade(image_bytes: bytes, quote: dict, brief: dict, theme: str = "") -> bytes | None:
    total     = REEL_DURATION_SEC
    text_sec  = total - INTRO_SEC
    cf        = CROSSFADE_SEC
    audio     = _audio_path(theme)
    has_audio = Path(audio).exists()

    base_pil  = compose_base(image_bytes, brief)
    final_b   = compose(image_bytes, quote, brief)
    final_pil = Image.open(io.BytesIO(final_b)).convert("RGB")

    durs = [INTRO_SEC, text_sec]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        base_p  = str(tmpdir / "base.jpg")
        final_p = str(tmpdir / "final.jpg")
        out_p   = str(tmpdir / "reel.mp4")

        base_pil.save(base_p,   format="JPEG", quality=95)
        final_pil.save(final_p, format="JPEG", quality=95)

        filt = _build_xfade_filter(2, durs, cf)

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", f"{INTRO_SEC:.2f}", "-i", base_p,
            "-loop", "1", "-t", f"{text_sec:.2f}",  "-i", final_p,
        ]
        if has_audio:
            cmd += ["-stream_loop", "-1", "-i", audio]

        cmd += ["-filter_complex", filt, "-map", "[vout]"]
        if has_audio:
            cmd += ["-map", "2:a:0", "-c:a", "aac", "-b:a", "128k",
                    "-af", f"afade=t=out:st={total-1.5}:d=1.5"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-t", str(total), out_p]

        logger.info(f"Fade Reel: intro={INTRO_SEC}s + text={text_sec}s  audio={Path(audio).name}")
        return _run_ffmpeg(cmd, out_p, total, has_audio, image_bytes, quote, brief, theme=theme, fallback=False)


# ---------------------------------------------------------------------------
# Reveal animation (sentence-by-sentence)
# ---------------------------------------------------------------------------

def _create_reel_reveal(image_bytes: bytes, quote: dict, brief: dict, theme: str = "") -> bytes | None:
    counts    = get_reveal_counts(quote, brief)
    n_segs    = len(counts)
    cf        = CROSSFADE_SEC
    audio     = _audio_path(theme)
    has_audio = Path(audio).exists()

    # Frame durations: base + uniform per-segment + last segment gets extra hold
    durs = [INTRO_SEC] + [PER_SEG_SEC] * (n_segs - 1) + [PER_SEG_SEC + HOLD_SEC]
    # Natural video duration = content - xfade overlaps
    total = round(sum(durs) - (len(durs) - 1) * cf, 2)

    # Build frames: base + one frame per reveal step (cumulative sentences)
    base_pil = compose_base(image_bytes, brief)
    frames   = [base_pil]

    for count in counts:
        fb = compose_partial(image_bytes, quote, brief, n_lines=count)
        frames.append(Image.open(io.BytesIO(fb)).convert("RGB"))

    N = len(frames)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        paths  = []
        for i, (frame, dur) in enumerate(zip(frames, durs)):
            p = str(tmpdir / f"f{i:02d}.jpg")
            frame.save(p, format="JPEG", quality=95)
            paths.append(p)

        out_p = str(tmpdir / "reel.mp4")

        cmd = ["ffmpeg", "-y"]
        for p, dur in zip(paths, durs):
            cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", p]
        if has_audio:
            cmd += ["-stream_loop", "-1", "-i", audio]

        filt = _build_xfade_filter(N, durs, cf)

        cmd += ["-filter_complex", filt, "-map", "[vout]"]
        audio_idx = N
        if has_audio:
            cmd += ["-map", f"{audio_idx}:a:0", "-c:a", "aac", "-b:a", "128k",
                    "-af", f"afade=t=out:st={total-1.5}:d=1.5"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-t", str(total), out_p]

        logger.info(
            f"Reveal Reel: {N} frames ({n_segs} sentences), "
            f"{PER_SEG_SEC}s/sentence + {HOLD_SEC}s hold = {total}s total, "
            f"audio={Path(audio).name if has_audio else 'none'}"
        )
        return _run_ffmpeg(cmd, out_p, total, has_audio, image_bytes, quote, brief, theme=theme, fallback=True)


# ---------------------------------------------------------------------------
# ffmpeg runner
# ---------------------------------------------------------------------------

def _run_ffmpeg(cmd, out_p, total, has_audio, image_bytes, quote, brief,
                theme: str = "", fallback=False) -> bytes | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            logger.error(f"ffmpeg error:\n{result.stderr[-2000:]}")
            if fallback:
                logger.info("Reveal failed — falling back to fade animation")
                return _create_reel_fade(image_bytes, quote, brief, theme=theme)
            return None
        out = Path(out_p)
        kb  = out.stat().st_size // 1024
        logger.info(f"✓ Reel ready ({total}s, {kb}KB, audio={'yes' if has_audio else 'no'})")
        return out.read_bytes()
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out")
        if fallback:
            return _create_reel_fade(image_bytes, quote, brief)
        return None
    except Exception as exc:
        logger.error(f"ffmpeg exception: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def create_reel(image_bytes: bytes, quote: dict, brief: dict, theme: str = "") -> bytes | None:
    """Return MP4 bytes for a Reel, or None if ffmpeg unavailable."""
    if not _ffmpeg_available():
        logger.warning("ffmpeg not found — skipping Reel creation")
        return None

    animation = brief.get("animation", "fade")
    logger.info(f"Reel animation: {animation}")

    if animation == "reveal":
        return _create_reel_reveal(image_bytes, quote, brief, theme=theme)
    return _create_reel_fade(image_bytes, quote, brief, theme=theme)
