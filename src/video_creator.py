"""
Animated Reel sequence:
  0–2s      : background only, Ken Burns zoom
  2–3.2s    : quote types in line-by-line (Ken Burns continuous)
  3.2–13s   : quote holds
  13–15s    : quote xfades back to image, Follow+handle zooms in from centre

Audio: theme-specific loop throughout.
"""
import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.config import AUDIO_FILE, IMAGE_HEIGHT, IMAGE_WIDTH, REEL_DURATION_SEC
from src.image_composer import compose_base, compose_partial, get_reveal_counts

logger = logging.getLogger(__name__)

FPS            = 25
INTRO_SEC      = 2.0    # background-only intro
TYPING_DUR     = 1.2    # total time for text to appear (line by line)
XFADE_TYPING   = 0.08   # crossfade between typing steps
FADE_DUR_SEC   = 2.0    # quote → base xfade at end
BASE_HOLD_SEC  = 0.3    # base shows alone after fade completes
HANDLE_IN_SEC  = 0.5    # handle appears this many secs after fade starts

HANDLE         = "@_daily_dose_of_wisdom__"
HANDLE_FONT    = Path("assets/fonts/bebas.ttf")
HANDLE_SIZE    = 62
FOLLOW_SIZE    = 44


def _audio_path(theme: str) -> str:
    theme_file = Path(f"assets/audio/{theme}.mp3").resolve()
    if theme_file.exists():
        return str(theme_file)
    return str(Path(AUDIO_FILE).resolve())


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _scale_crop() -> str:
    W, H = IMAGE_WIDTH, IMAGE_HEIGHT
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"


def _zoompan_at(total_frames: int, start_frame: int) -> str:
    """Ken Burns with z offset so zoom is continuous across xfade cuts."""
    W, H = IMAGE_WIDTH, IMAGE_HEIGHT
    return (
        f"zoompan=z='min(1+0.0005*(on+{start_frame}),1.12)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={total_frames}:s={W}x{H}:fps={FPS}"
    )


# ---------------------------------------------------------------------------
# Handle zoom animation frames (PIL)
# ---------------------------------------------------------------------------

def _render_handle_zoom_frames(handle_dir: Path, n_frames: int) -> None:
    """Write n_frames PNGs of Follow+handle scaling from 25% to 100%."""
    W, H = IMAGE_WIDTH, IMAGE_HEIGHT
    for i in range(n_frames):
        t     = i / max(n_frames - 1, 1)
        ease  = 1 - (1 - t) ** 3          # cubic ease-out
        scale = 0.25 + 0.75 * ease
        alpha = int(255 * min(t * 3, 1))  # fade in over first third

        img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        fs_f = max(10, int(FOLLOW_SIZE * scale))
        fs_h = max(10, int(HANDLE_SIZE * scale))
        try:
            ff = ImageFont.truetype(str(HANDLE_FONT), fs_f)
            fh = ImageFont.truetype(str(HANDLE_FONT), fs_h)
        except Exception:
            ff = fh = ImageFont.load_default()

        ftxt = "Follow"
        fb   = draw.textbbox((0, 0), ftxt, font=ff)
        fw   = fb[2] - fb[0]
        fh_h = fb[3] - fb[1]
        hb   = draw.textbbox((0, 0), HANDLE, font=fh)
        hw   = hb[2] - hb[0]
        hh   = hb[3] - hb[1]

        gap   = max(4, int(18 * scale))
        tot_h = fh_h + gap + hh
        top_y = (H - tot_h) // 2

        draw.text(((W - fw) // 2, top_y),           ftxt,   font=ff, fill=(200, 200, 200, alpha))
        draw.text(((W - hw) // 2, top_y + fh_h + gap), HANDLE, font=fh, fill=(255, 255, 255, alpha))

        img.save(handle_dir / f"h{i:03d}.png")


# ---------------------------------------------------------------------------
# Fade animation — typing reveal + Ken Burns + handle zoom end card
# ---------------------------------------------------------------------------

def _create_reel_fade(image_bytes: bytes, quote: dict, brief: dict, theme: str = "") -> bytes | None:
    total     = REEL_DURATION_SEC
    audio     = _audio_path(theme)
    has_audio = Path(audio).exists()
    W, H      = IMAGE_WIDTH, IMAGE_HEIGHT

    counts  = get_reveal_counts(quote, brief)
    n_steps = len(counts)
    per_step = TYPING_DUR / n_steps

    # Hold time so total output = REEL_DURATION_SEC
    # output_dur = sum(durs) - sum(cfs)
    # cfs = [XFADE_TYPING]*(n_steps) + [FADE_DUR_SEC]
    # The FADE_DUR_SEC cf cancels with BASE_HOLD_SEC in sum(durs)
    text_hold = (total - INTRO_SEC
                 - n_steps * (per_step - XFADE_TYPING)
                 - FADE_DUR_SEC - BASE_HOLD_SEC)

    base_pil = compose_base(image_bytes, brief)

    # Build frame list: base → line steps → base_end
    frames_and_durs: list[tuple[Image.Image, float]] = [(base_pil, INTRO_SEC)]
    for i, count in enumerate(counts):
        fb  = compose_partial(image_bytes, quote, brief, n_lines=count)
        pil = Image.open(io.BytesIO(fb)).convert("RGB")
        dur = per_step if i < n_steps - 1 else per_step + text_hold
        frames_and_durs.append((pil, dur))
    frames_and_durs.append((base_pil, FADE_DUR_SEC + BASE_HOLD_SEC))

    N    = len(frames_and_durs)
    durs = [d for _, d in frames_and_durs]
    cfs  = [XFADE_TYPING] * (N - 2) + [FADE_DUR_SEC]

    total_frames     = int(total * FPS)
    fade_starts_at   = total - FADE_DUR_SEC          # t=13.0
    handle_appears   = fade_starts_at + HANDLE_IN_SEC # t=13.5
    handle_anim_dur  = total - handle_appears          # 1.5s
    n_handle_frames  = max(2, int(handle_anim_dur * FPS))
    sc = _scale_crop()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Save typing frames
        paths = []
        for i, (pil, _) in enumerate(frames_and_durs):
            p = str(tmpdir / f"f{i:02d}.jpg")
            pil.save(p, format="JPEG", quality=95)
            paths.append(p)

        # Render handle zoom PNG sequence
        handle_dir = tmpdir / "handle"
        handle_dir.mkdir()
        _render_handle_zoom_frames(handle_dir, n_handle_frames)

        out_p = str(tmpdir / "reel.mp4")

        # --- ffmpeg command ---
        cmd = ["ffmpeg", "-y"]
        for p, dur in zip(paths, durs):
            cmd += ["-loop", "1", "-t", f"{dur:.4f}", "-i", p]

        handle_idx = N
        cmd += ["-framerate", str(FPS), "-i", str(handle_dir / "h%03d.png")]

        audio_idx = None
        if has_audio:
            audio_idx = N + 1
            cmd += ["-stream_loop", "-1", "-i", audio]

        # --- filter graph ---
        parts = []

        # Compute zoompan start_frame for each input (keeps zoom continuous)
        stream_dur   = durs[0]
        start_frames = [0]
        for i, cf in enumerate(cfs):
            sf = max(0, int((stream_dur - cf) * FPS))
            start_frames.append(sf)
            stream_dur += durs[i + 1] - cf

        for i, sf in enumerate(start_frames):
            # Ken Burns only on intro/fade-out background frames — text frames stay static
            # so longer quotes don't drift out of frame as the zoom increases
            if i == 0 or i == N - 1:
                parts.append(f"[{i}:v]{sc},{_zoompan_at(total_frames, sf)}[v{i}]")
            else:
                parts.append(f"[{i}:v]{sc},setsar=1,fps={FPS}[v{i}]")

        # xfade chain
        prev       = "v0"
        stream_dur = durs[0]
        for i, cf in enumerate(cfs):
            offset = max(0.0, stream_dur - cf)
            label  = f"xf{i+1}" if i < len(cfs) - 1 else "main"
            parts.append(
                f"[{prev}][v{i+1}]xfade=transition=fade:"
                f"duration={cf:.3f}:offset={offset:.3f}[{label}]"
            )
            prev = label
            stream_dur += durs[i + 1] - cf

        # Handle zoom overlay (appears from t=handle_appears)
        parts.append(f"[{handle_idx}:v]scale={W}:{H},setsar=1,fps={FPS}[handle]")
        parts.append(
            f"[main][handle]overlay=0:0:enable='gte(t,{handle_appears:.2f})'[vout]"
        )

        filt = ";".join(parts)
        cmd += ["-filter_complex", filt, "-map", "[vout]"]

        if has_audio:
            cmd += ["-map", f"{audio_idx}:a:0", "-c:a", "aac", "-b:a", "128k",
                    "-af", f"afade=t=out:st={total - 1.5}:d=1.5"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-t", str(total), out_p]

        logger.info(
            f"Reel: {total}s | {INTRO_SEC}s base → {n_steps}-step typing → "
            f"hold → fade@{fade_starts_at:.1f}s → handle zoom | "
            f"audio={'yes' if has_audio else 'no'}"
        )
        return _run_ffmpeg(cmd, out_p, total, has_audio, image_bytes, quote, brief,
                           theme=theme, fallback=False)


# ---------------------------------------------------------------------------
# Reveal animation (sentence-by-sentence, for "reveal" animation mode)
# ---------------------------------------------------------------------------

def _build_xfade_filter(N: int, durs: list[float], cf: float) -> str:
    W, H  = IMAGE_WIDTH, IMAGE_HEIGHT
    parts = []
    for i in range(N):
        parts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}[v{i}]"
        )
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
        stream_dur += durs[i] - cf
    return ";".join(parts)


def _create_reel_reveal(image_bytes: bytes, quote: dict, brief: dict, theme: str = "") -> bytes | None:
    counts    = get_reveal_counts(quote, brief)
    n_segs    = len(counts)
    cf        = 0.5
    audio     = _audio_path(theme)
    has_audio = Path(audio).exists()

    PER_SEG_SEC = 4.0
    HOLD_SEC    = 2.5
    durs  = [INTRO_SEC] + [PER_SEG_SEC] * (n_segs - 1) + [PER_SEG_SEC + HOLD_SEC]
    total = round(sum(durs) - (len(durs) - 1) * cf, 2)

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
        cmd   = ["ffmpeg", "-y"]
        for p, dur in zip(paths, durs):
            cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", p]
        if has_audio:
            cmd += ["-stream_loop", "-1", "-i", audio]

        filt = _build_xfade_filter(N, durs, cf)
        cmd += ["-filter_complex", filt, "-map", "[vout]"]
        if has_audio:
            cmd += ["-map", f"{N}:a:0", "-c:a", "aac", "-b:a", "128k",
                    "-af", f"afade=t=out:st={total - 1.5}:d=1.5"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-t", str(total), out_p]

        logger.info(f"Reveal Reel: {N} frames, {total}s | audio={'yes' if has_audio else 'no'}")
        return _run_ffmpeg(cmd, out_p, total, has_audio, image_bytes, quote, brief,
                           theme=theme, fallback=True)


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
    if not _ffmpeg_available():
        logger.warning("ffmpeg not found — skipping Reel creation")
        return None
    animation = brief.get("animation", "fade")
    logger.info(f"Reel animation: {animation}")
    if animation == "reveal":
        return _create_reel_reveal(image_bytes, quote, brief, theme=theme)
    return _create_reel_fade(image_bytes, quote, brief, theme=theme)
