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

from src.config import (
    AUDIO_FILE,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    REEL_DURATION_SEC,
    TTS_MUSIC_VOLUME,
)
from src.image_composer import compose, compose_base, compose_partial, get_reveal_counts

logger = logging.getLogger(__name__)

FPS            = 25
# INTRO_SEC is the silent background-only buffer before the quote appears.
# Set to 0 so frame 0 already shows the full composed quote — critical for
# Instagram because it drives both the auto-picked cover and the decision
# viewers make in the first second of watching.
INTRO_SEC      = 0.0
TYPING_DUR     = 1.2    # total time for text to appear (line by line)
XFADE_TYPING   = 0.35   # crossfade between typing steps — smooth dissolve
FADE_DUR_SEC   = 2.0    # quote → base xfade at end
BASE_HOLD_SEC  = 0.3    # base shows alone after fade completes
HANDLE_IN_SEC  = 0.5    # handle appears this many secs after fade starts

HANDLE         = "@_daily_dose_of_wisdom__"
HANDLE_FONT    = Path("assets/fonts/bebas.ttf")
HANDLE_SIZE    = 62
FOLLOW_SIZE    = 44


def _audio_filter_parts(
    music_idx: int | None,
    tts_idx: int | None,
    total: float,
    tts_delay_ms: int = 2000,
) -> tuple[list[str], str]:
    """
    Build ffmpeg filter_complex parts for audio mixing.
    Returns (parts_list, output_label) — label is '' when there is no audio.

    When TTS is present the music plays at full volume during the intro,
    then smoothly ducks to TTS_MUSIC_VOLUME over 0.4s as the voice starts.
    """
    fade_st = max(0.0, total - 1.5)
    tts_start = tts_delay_ms / 1000.0
    duck_start = max(0.0, tts_start - 0.2)
    duck_end   = tts_start + 0.2
    vol        = TTS_MUSIC_VOLUME
    # Linear ramp: full volume → TTS_MUSIC_VOLUME over 0.4s around tts_start
    duck_expr  = (
        f"if(lt(t,{duck_start:.2f}),1.0,"
        f"if(lt(t,{duck_end:.2f}),"
        f"(1.0+({vol}-1.0)*(t-{duck_start:.2f})/{duck_end-duck_start:.2f}),"
        f"{vol}))"
    )

    if music_idx is not None and tts_idx is not None:
        return [
            f"[{music_idx}:a]volume='{duck_expr}'[music_ducked]",
            f"[{tts_idx}:a]adelay={tts_delay_ms}|{tts_delay_ms}[tts_del]",
            f"[music_ducked][tts_del]amix=inputs=2:duration=longest:"
            f"dropout_transition=0,afade=t=out:st={fade_st:.2f}:d=1.5[aout]",
        ], "[aout]"
    elif music_idx is not None:
        return [
            f"[{music_idx}:a]afade=t=out:st={fade_st:.2f}:d=1.5[aout]",
        ], "[aout]"
    elif tts_idx is not None:
        return [
            f"[{tts_idx}:a]adelay={tts_delay_ms}|{tts_delay_ms},"
            f"afade=t=out:st={fade_st:.2f}:d=1.5[aout]",
        ], "[aout]"
    return [], ""


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

def _sample_bg_luminance(base_pil: Image.Image) -> int:
    """Mean luminance (0-255) of the vertical centre band where the handle sits."""
    W, H = base_pil.size
    band = base_pil.crop((0, int(H * 0.38), W, int(H * 0.62))).convert("L")
    px = band.resize((32, 16)).getdata()
    return sum(px) // len(px)


def _render_handle_zoom_frames(handle_dir: Path, n_frames: int,
                               base_pil: Image.Image) -> None:
    """Write n_frames PNGs of Follow+handle scaling from 25% to 100%.
    Text colour and stroke adapt to the base image's luminance in the
    handle band so the end card stays legible on any background."""
    W, H = IMAGE_WIDTH, IMAGE_HEIGHT

    # Light bg → dark text + light stroke; dark bg → white text + dark stroke.
    lum = _sample_bg_luminance(base_pil)
    if lum > 140:
        text_rgb, stroke_rgb = (25, 25, 25), (255, 255, 255)
    else:
        text_rgb, stroke_rgb = (255, 255, 255), (0, 0, 0)

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

        sw_f   = max(1, int(3 * scale))
        sw_h   = max(1, int(4 * scale))
        fill_t = (*text_rgb, alpha)
        fill_s = (*stroke_rgb, alpha)

        draw.text(((W - fw) // 2, top_y), ftxt, font=ff,
                  fill=fill_t, stroke_width=sw_f, stroke_fill=fill_s)
        draw.text(((W - hw) // 2, top_y + fh_h + gap), HANDLE, font=fh,
                  fill=fill_t, stroke_width=sw_h, stroke_fill=fill_s)

        img.save(handle_dir / f"h{i:03d}.png")


# ---------------------------------------------------------------------------
# Fade animation — typing reveal + Ken Burns + handle zoom end card
# ---------------------------------------------------------------------------

def _create_reel_fade(image_bytes: bytes, quote: dict, brief: dict, theme: str = "",
                      tts_bytes: bytes | None = None) -> bytes | None:
    total     = REEL_DURATION_SEC
    audio     = _audio_path(theme)
    has_audio = Path(audio).exists()
    W, H      = IMAGE_WIDTH, IMAGE_HEIGHT

    counts   = get_reveal_counts(quote, brief)
    n_steps  = len(counts)
    # Clamp so per_step always exceeds XFADE_TYPING — prevents broken ffmpeg filter graph
    per_step = max(XFADE_TYPING + 0.05, TYPING_DUR / n_steps)

    base_pil = compose_base(image_bytes, brief)

    # Engagement-first: when INTRO_SEC == 0 we skip the typing reveal and
    # show the fully-composed quote from frame 0. This way the Reel's first
    # frame (also the Explore cover) already contains the quote — viewers
    # can decide to stop scrolling in the first second.
    if INTRO_SEC <= 0.01:
        full_fb  = compose(image_bytes, quote, brief)
        full_pil = Image.open(io.BytesIO(full_fb)).convert("RGB")
        hold_dur = total - FADE_DUR_SEC - BASE_HOLD_SEC
        frames_and_durs: list[tuple[Image.Image, float]] = [
            (full_pil, hold_dur + FADE_DUR_SEC),      # +FADE because xfade into base consumes it
            (base_pil, FADE_DUR_SEC + BASE_HOLD_SEC),
        ]
        cfs = [FADE_DUR_SEC]
    else:
        # Legacy typing-reveal path — kept in case INTRO_SEC is ever reintroduced.
        # output_dur = sum(durs) - sum(cfs)
        text_hold = (total - INTRO_SEC
                     - n_steps * (per_step - XFADE_TYPING)
                     - FADE_DUR_SEC - BASE_HOLD_SEC)
        frames_and_durs = [(base_pil, INTRO_SEC)]
        for i, count in enumerate(counts):
            fb  = compose_partial(image_bytes, quote, brief, n_lines=count)
            pil = Image.open(io.BytesIO(fb)).convert("RGB")
            dur = per_step if i < n_steps - 1 else per_step + text_hold
            frames_and_durs.append((pil, dur))
        frames_and_durs.append((base_pil, FADE_DUR_SEC + BASE_HOLD_SEC))
        cfs = [XFADE_TYPING] * (len(frames_and_durs) - 2) + [FADE_DUR_SEC]

    N    = len(frames_and_durs)
    durs = [d for _, d in frames_and_durs]

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
        _render_handle_zoom_frames(handle_dir, n_handle_frames, base_pil)

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

        tts_idx = None
        if tts_bytes:
            tts_file = tmpdir / "tts.mp3"
            tts_file.write_bytes(tts_bytes)
            tts_idx = handle_idx + 1 + (1 if has_audio else 0)
            cmd += ["-i", str(tts_file)]

        # --- filter graph ---
        parts = []

        # Compute zoompan start_frame for each input (keeps zoom continuous)
        stream_dur   = durs[0]
        start_frames = [0]
        for i, cf in enumerate(cfs):
            sf = max(0, int((stream_dur - cf) * FPS))
            start_frames.append(sf)
            stream_dur += durs[i + 1] - cf

        skip_kenburns = brief.get("skip_kenburns", False)
        for i, sf in enumerate(start_frames):
            # Ken Burns only on intro/fade-out background frames — text frames stay static
            # so longer quotes don't drift out of frame as the zoom increases.
            # skip_kenburns=True disables zoom entirely (used for handwriting/script fonts
            # and simple_text_card style where motion reduces readability).
            if not skip_kenburns and (i == 0 or i == N - 1):
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

        audio_parts, audio_out = _audio_filter_parts(
            audio_idx, tts_idx, total,
            tts_delay_ms=int(INTRO_SEC * 1000),
        )
        parts.extend(audio_parts)

        filt = ";".join(parts)
        cmd += ["-filter_complex", filt, "-map", "[vout]"]
        if audio_out:
            cmd += ["-map", audio_out, "-c:a", "aac", "-b:a", "128k"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-t", str(total), out_p]

        has_any_audio = has_audio or bool(tts_bytes)
        if INTRO_SEC <= 0.01:
            mode_label = f"quote@t=0 → hold → fade@{fade_starts_at:.1f}s → handle"
        else:
            mode_label = (f"{INTRO_SEC}s base → {n_steps}-step typing → "
                          f"hold → fade@{fade_starts_at:.1f}s → handle")
        logger.info(
            f"Reel: {total}s | {mode_label} | "
            f"music={'yes' if has_audio else 'no'}  tts={'yes' if tts_bytes else 'no'}"
        )
        return _run_ffmpeg(cmd, out_p, total, has_any_audio)


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


def _create_reel_reveal(image_bytes: bytes, quote: dict, brief: dict, theme: str = "",
                        tts_bytes: bytes | None = None) -> bytes | None:
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

        audio_idx = None
        if has_audio:
            audio_idx = N
            cmd += ["-stream_loop", "-1", "-i", audio]

        tts_idx = None
        if tts_bytes:
            tts_file = tmpdir / "tts.mp3"
            tts_file.write_bytes(tts_bytes)
            tts_idx = N + (1 if has_audio else 0)
            cmd += ["-i", str(tts_file)]

        # Build video filter, then append audio filter parts
        parts = _build_xfade_filter(N, durs, cf).split(";")
        audio_parts, audio_out = _audio_filter_parts(
            audio_idx, tts_idx, total,
            tts_delay_ms=int(INTRO_SEC * 1000),
        )
        parts.extend(audio_parts)

        filt = ";".join(parts)
        cmd += ["-filter_complex", filt, "-map", "[vout]"]
        if audio_out:
            cmd += ["-map", audio_out, "-c:a", "aac", "-b:a", "128k"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-t", str(total), out_p]

        has_any_audio = has_audio or bool(tts_bytes)
        logger.info(
            f"Reveal Reel: {N} frames, {total}s | "
            f"music={'yes' if has_audio else 'no'}  tts={'yes' if tts_bytes else 'no'}"
        )
        return _run_ffmpeg(cmd, out_p, total, has_any_audio)


# ---------------------------------------------------------------------------
# ffmpeg runner
# ---------------------------------------------------------------------------

def _run_ffmpeg(cmd, out_p, total, has_audio) -> bytes | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            logger.error(f"ffmpeg error:\n{result.stderr[-2000:]}")
            return None
        out = Path(out_p)
        kb  = out.stat().st_size // 1024
        logger.info(f"✓ Reel ready ({total}s, {kb}KB, audio={'yes' if has_audio else 'no'})")
        return out.read_bytes()
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out")
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

    # Generate TTS once — skip if theme disables voice narration or quote has no real author
    from src.config import THEMES
    from src.tts import synthesize
    _SKIP_AUTHOR = {"unknown", "anonymous", "original", "original thought", ""}
    _author = quote.get("author", "").strip().lower()
    tts_enabled = (
        THEMES.get(theme, {}).get("tts", True)
        and _author not in _SKIP_AUTHOR
    )
    if not tts_enabled:
        logger.info("TTS: skipped — no attributed author (music only)")
    tts_bytes = synthesize(quote.get("text", ""), brief.get("voice_gender"), theme=theme) if tts_enabled else None

    animation = brief.get("animation", "fade")
    logger.info(f"Reel animation: {animation}")
    if animation == "reveal":
        result = _create_reel_reveal(image_bytes, quote, brief, theme=theme,
                                     tts_bytes=tts_bytes)
        if result is None:
            logger.info("Reveal failed — falling back to fade animation")
            result = _create_reel_fade(image_bytes, quote, brief, theme=theme,
                                       tts_bytes=tts_bytes)
        return result
    return _create_reel_fade(image_bytes, quote, brief, theme=theme,
                             tts_bytes=tts_bytes)
