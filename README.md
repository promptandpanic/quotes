# Daily Dose of Wisdom — Instagram Bot

Fully automated Instagram Reels bot for **@_daily_dose_of_wisdom__**  
Posts **6 quote Reels per day** (IST-timed) with AI-generated visuals — zero manual effort.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GitHub Actions (6x/day)                             │
│                                                                             │
│  cron fires → sets THEME env var → python main.py                          │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  main.py  —  Pipeline Orchestrator                                          │
│                                                                             │
│  1.  Select theme (by THEME env var or closest UTC hour)                    │
│  2.  Load DB → compute active posted hashes (repeat window)                 │
│  3.  Pull 90-day topic hints to avoid repetition                            │
│  4.  Generate quote                                                         │
│  5.  Design brief loop (up to 3 attempts):                                  │
│        a. Creative brief (font, layout, image_prompt, overlay)              │
│        b. Generate background image                                         │
│        c. Compose image (pixel-accurate text overlay)                       │
│        d. Judge image → accept (score ≥ 6) or retry                        │
│  6.  Gradient fallback if all 3 attempts fail                               │
│  7.  Create Reel video (ffmpeg)                                             │
│  8.  Upload video to GitHub Releases (temp public URL)                      │
│  9.  Post Reel + custom thumbnail to Instagram                              │
│  10. Delete temp GitHub Release asset                                       │
│  11. Record quote in DB → save                                              │
│  12. Notify (email)                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data flow through the pipeline

```
THEME env var
  │
  ▼
src/config.py ──────────── THEMES dict → theme name, IST label, utc_hour
  │
  ▼
src/db_manager.py ───────── posted_quotes.json (via GitHub API)
  │                            → active hashes (repeat window)
  │                            → recent topic hints (90 days)
  ▼
src/quote_generator.py ──── Gemini finds a REAL quote by a known author
  │   reads:
  │   ├── config/topics.yml          ← topic areas, day-of-week topics,
  │   │                                 cultural traditions, red/green flags,
  │   │                                 spiritual teachers, workout topics
  │   ├── config/curated_quotes.yml  ← real attributed quotes (fallback pool)
  │   └── src/config.py FALLBACK_QUOTES  ← hardcoded emergency fallback
  │
  │   returns: { text, author, highlight, image_hint, source }
  │                                         ↑
  │                           image_hint flows from wisdom tradition pick
  │                           (e.g. "Japanese wisdom" → sumi-e ink painting)
  ▼
src/design_director.py ──── Gemini acts as creative director → render spec
  │   reads:
  │   └── config/styles.yml          ← visual styles, category mapping, weight
  │
  │   returns: { font, font_size, layout, text_zone, overlay,
  │              image_prompt, highlight, highlight_color, decoration, ... }
  ▼
src/image_generator.py ──── Background image (style bracket stripped first)
  │   ├── Imagen 4 Fast          (primary, ~$0.02/image)
  │   ├── Gemini Flash Image     (free fallback)
  │   ├── Pollinations.ai        (free fallback)
  │   └── PIL gradient           (zero-dependency final fallback)
  │
src/image_composer.py ───── Pixel-accurate text overlay (PIL + font metrics)
  │   reads:
  │   └── assets/fonts/          ← auto-downloaded at first run
  │
src/image_judge.py ─────── Gemini vision → score 1-10
  │                            accept if score ≥ 6, else retry up to 3×
  ▼
src/video_creator.py ───── ffmpeg → 9:16 MP4 Reel
  │   ├── sentence_reveal layout: lines fade in one by one
  │   ├── fade layout: full image crossfade, text visible throughout
  │   └── assets/audio/{theme}.mp3       ← per-theme audio (falls back to background.mp3)
  │
src/github_uploader.py ──── Upload MP4 to GitHub Releases (public temp URL)
  │
src/instagram_poster.py ─── Post Reel via Instagram Graph API
  │   ├── build_caption() → Gemini writes hook + 20 hashtags
  │   └── post_reel(video_url, caption, thumb_url) → custom thumbnail
  │
src/db_manager.py ────────── Mark quote posted → save DB
  │
src/notifier.py ─────────── Gmail success/failure email
```

---

## Posting schedule

| IST | UTC cron | Theme |
|---|---|---|
| 06:00 | `30 0 * * *` | Morning Motivation |
| 11:00 | `30 5 * * *` | Life Wisdom |
| 14:00 | `30 8 * * *` | Love & Relationships |
| 17:00 | `30 11 * * *` | Mindfulness & Inner Peace |
| 21:00 | `30 15 * * *` | Goodnight & Gratitude |
| 01:00 | `30 19 * * *` | Late Night Feels |

---

## Where to make changes

### Quote topics → `config/topics.yml`

The main editorial file. Edit freely — no code changes needed.

```yaml
categories:

  morning:
    max_words: 20          # hard cap enforced in prompt + validation
    topics:                # general pool, Gemini picks from these
      - "add your topic here"

    workout_topics:        # injected ~30% of morning posts
      - "gym consistency — showing up even when motivation is zero"

    day_topics:            # injected automatically based on IST day
      monday:
        - "Monday blues — finding momentum when the weekend just ended"
      saturday:
        - "Saturday wins — getting ahead while the world sleeps in"

  wisdom:
    max_words: 28
    topics:
      - "..."
    cultural_topics:       # ~40% of wisdom posts pick one tradition
      - tradition: "Japanese wisdom"
        topics:
          - "wabi-sabi — finding beauty in imperfection"

      # To add a new tradition, copy this block:
      - tradition: "Persian wisdom"
        topics:
          - "Rumi — on love, longing, and the soul's journey"

  love:
    red_green_flag_topics:   # ~35% of love posts use this format
      - "green flag: someone who stays consistent even when you're difficult"
      - "red flag: love that arrives only when they need something"

  mindfulness:
    spiritual_topics:        # ~40% of mindfulness posts quote a teacher
      - "Sadhguru (Jaggi Vasudev) — on the nature of the mind"
      - "Eckhart Tolle — on presence, ego, and the pain body"
```

**To add a new category** (e.g. "career"): add a top-level key here, then add it to `THEMES` in `src/config.py` and a new cron line in `.github/workflows/post_quotes.yml`.

---

### Visual styles → `config/styles.yml`

Controls what images Gemini designs. Edit freely — no code changes needed.

```yaml
styles:

  my_new_style:
    description: >
      Exactly what you want the image to look like — be specific.
      Include: art style, subjects, colours, mood, which area (top/center/bottom
      35%) stays dark for text. This goes directly into the image prompt.
    categories: [morning, wisdom]   # which themes can use this style
    weight: high                    # high / medium / low
```

A style only appears in Gemini's prompt when the current theme is in its `categories` list.

**Current styles:**

| Style | Categories | Weight |
|---|---|---|
| `indian_flat_illustration` | morning, wisdom, mindfulness, latenight | high |
| `indian_vector_girl` | love, goodnight | high |
| `indian_vector_couple` | love, goodnight | high |
| `watercolour_ink` | love, mindfulness, goodnight, wisdom | high |
| `minimalist_nature` | mindfulness, wisdom, goodnight, latenight | high |
| `cozy_aesthetic` | goodnight, latenight, love, mindfulness | high |
| `whimsical_sketch` | wisdom, love, goodnight, latenight | medium |
| `minimalist_vector` | morning, wisdom, mindfulness | medium |
| `india_landscape` | morning, wisdom, love | medium |
| `pixel_art` | latenight, wisdom, morning | medium |
| `paper_cut` | wisdom, mindfulness, goodnight | medium |
| `abstract_fluid` | latenight, mindfulness, wisdom | medium |
| `double_exposure` | latenight, love, wisdom | medium |
| `dark_surreal` | latenight, wisdom | low |

> **Image rule applied globally:** All images use illustrations, paintings, flat vector art, ink sketches, or abstract art. Photorealistic humans and portrait photography are explicitly blocked in every prompt.

---

### Curated / fallback quotes → `config/curated_quotes.yml`

Real attributed quotes used when Gemini is unavailable.

```yaml
quotes:
  morning:
    - text: "The secret of getting ahead is getting started."
      author: "Mark Twain"
  wisdom:
    - text: "..."
      author: "..."
  # love, mindfulness, goodnight, latenight — same structure
```

---

### Change post timing → `.github/workflows/post_quotes.yml`

Edit the `cron` lines (all times are UTC, IST = UTC + 5:30):

```yaml
schedule:
  - cron: "30 2 * * *"   # 08:00 IST — change to whatever time you want
```

Also update `utc_hour` for the matching theme in `src/config.py` so the fallback auto-detection stays in sync.

---

### Change AI models (no code change)

Set these as GitHub Secrets or in `.env`:

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_TEXT_MODEL` | `gemini-3-flash-preview` | Used for quotes, briefs, captions, judge |
| `GEMINI_IMAGE_MODEL` | `imagen-4.0-fast-generate-001` | Set to `gemini-2.5-flash-image` for $0/month |

---

### Change repeat prevention window

Default: 10 days. Set `REPEAT_WINDOW_DAYS=30` in GitHub Secrets to extend.

---

### Add or change fonts

**Who decides the font?** You control which fonts are *available*; Gemini picks which one best fits each quote's emotion.

**Two-file change to add a font:**

1. **`src/image_composer.py` — `_FONT_URLS` dict** — add the font name and its TTF download URL (gstatic.com is reliable; GitHub google/fonts URLs often 404):
   ```python
   "myfont": "https://fonts.gstatic.com/s/myfont/.../MyFont-Bold.ttf",
   ```

2. **`src/design_director.py` — `_BRIEF_PROMPT`** — add it to the AVAILABLE FONTS section with a description so Gemini knows when to pick it:
   ```
   myfont — short style description → best themes or moods
   ```
   Also add it to the `"font":` enum line in the JSON spec at the bottom of the prompt.

**Currently available fonts (14 total):**

| Font | Style | Best for |
|------|-------|----------|
| `bebas` | All-caps ultra-bold display | Morning energy, power |
| `anton` | Condensed heavy poster | Punchy one-liners |
| `oswald` | Condensed bold editorial | Wisdom, stoic quotes |
| `montserrat` | Geometric bold, versatile | Any theme |
| `cinzel` | Classical Roman capitals | Ancient wisdom, philosophy |
| `raleway` | Elegant geometric bold | Sophisticated, premium |
| `josefin` | Minimal geometric | Minimalist, clean wisdom |
| `playfair` | Elegant bold serif | Love, poetry, reflection |
| `merriweather` | Sturdy readable serif | Wisdom, goodnight, long quotes |
| `cormorant` | Ultra-elegant high-contrast serif | Luxury, intimate love |
| `dancing` | Flowing bold script | Love, warmth, celebration |
| `satisfy` | Casual elegant script | Goodnight, soft wisdom |
| `specialelite` | Typewriter grit | Late-night honesty |
| `lato` | Clean neutral sans | Calm, mindfulness |

Fonts are auto-downloaded to `assets/fonts/` on first use. If a requested font fails to download, the renderer falls back to `lato` at the correct size (never a bitmap fallback).

---

## GitHub deployment

### Requirements

- **Public** GitHub repository (Instagram fetches video from GitHub Releases — must be public)
- Instagram **Business or Creator** account (not personal)
- Facebook Page linked to your Instagram account

### One-time Meta setup

**Step 1 — Get your Instagram Business Account ID**

In [Graph API Explorer](https://developers.facebook.com/tools/explorer/):
```
GET /me/accounts                                    ← find your Page ID
GET /{page-id}?fields=instagram_business_account   ← copy the id value
```

**Step 2 — Generate a long-lived access token**

In Graph API Explorer, select your app, add permissions:
`instagram_basic` · `instagram_content_publish` · `pages_read_engagement`

Generate a short-lived token, then exchange it for 60 days:
```bash
curl "https://graph.facebook.com/v21.0/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id=YOUR_APP_ID
  &client_secret=YOUR_APP_SECRET
  &fb_exchange_token=YOUR_SHORT_LIVED_TOKEN"
```

> Token expires after 60 days — set a calendar reminder.  
> For a permanent token: create a **System User** in Meta Business Suite.

**Step 3 — Get a Gemini API key**

[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) → Create API key (free tier).

### Add GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value | Required |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio key | Yes |
| `INSTAGRAM_ACCESS_TOKEN` | 60-day Meta token | Yes |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Numeric IG account ID | Yes |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions | — |
| `SMTP_USERNAME` | Gmail address for notifications | Optional |
| `SMTP_PASSWORD` | Gmail App Password (16-char) | Optional |
| `NOTIFY_EMAILS` | Comma-separated recipient emails | Optional |
| `REPEAT_WINDOW_DAYS` | Days before a quote can repeat (default: `10`) | Optional |
| `GEMINI_TEXT_MODEL` | Override text model | Optional |
| `GEMINI_IMAGE_MODEL` | Override image model | Optional |

**Gmail App Password:** Google Account → Security → 2-Step Verification → App passwords → create one → copy the 16-char code.

### Add audio (optional but recommended)

Each theme plays its own background track. Drop a file named `{theme}.mp3` into `assets/audio/` and it's picked up automatically — no code change needed. If a theme file is missing, the bot falls back to `background.mp3`.

| Theme | File | Vibe | Search terms |
|-------|------|------|--------------|
| morning | `morning.mp3` | Uplifting acoustic / bright piano | `"uplifting morning acoustic"` · `"inspiring piano loop"` |
| wisdom | `wisdom.mp3` | Ambient sitar + tabla drone | `"ambient sitar drone"` · `"indian classical ambient"` |
| love | `love.mp3` | Soft warm piano / acoustic guitar | `"romantic soft piano"` · `"tender love music"` |
| mindfulness | `mindfulness.mp3` | Tibetan singing bowls + nature | `"tibetan singing bowl loop"` · `"meditation ambient nature"` |
| goodnight | `goodnight.mp3` | Gentle lullaby piano | `"gentle piano lullaby"` · `"sleep soft piano"` |
| latenight | `latenight.mp3` | Lo-fi melancholic / rain ambience | `"lofi melancholic sad"` · `"3am rain piano"` |
| *(fallback)* | `background.mp3` | Any calm instrumental | used when a theme file is missing |

**Free royalty-free sources:** [pixabay.com/music](https://pixabay.com/music) · [mixkit.co/free-music-tracks](https://mixkit.co/free-music-tracks) · [uppbeat.io](https://uppbeat.io)

Trim any download to ~20 seconds with ffmpeg:
```bash
ffmpeg -i downloaded.mp3 -t 20 -c:a libmp3lame -q:a 2 assets/audio/morning.mp3
```

### Test manually

Repo → **Actions → Post Daily Quotes → Run workflow** → pick a theme → Run workflow.

---

## Local development

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO
cd YOUR_REPO

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Create a .env file:
GEMINI_API_KEY=...
INSTAGRAM_ACCESS_TOKEN=...
INSTAGRAM_BUSINESS_ACCOUNT_ID=...
GITHUB_TOKEN=...
GITHUB_REPOSITORY=your-username/your-repo

# Dry-run: generates image + video in output/, skips Instagram post
DRY_RUN=true THEME=morning python main.py
DRY_RUN=true THEME=wisdom python main.py
DRY_RUN=true python main.py    # auto-selects theme by UTC hour
```

---

## Project structure

```
├── main.py                          # Orchestrator — runs the full pipeline
│
├── src/
│   ├── config.py                    # THEMES dict, AI model names, constants
│   ├── content_config.py            # Loads YAMLs; topic_info + style helpers
│   ├── quote_generator.py           # Gemini recalls real quotes + fallback pools
│   ├── design_director.py           # Gemini creative brief (font, layout, image_prompt)
│   ├── image_generator.py           # Imagen 4 → Gemini Flash → Pollinations → gradient
│   ├── image_composer.py            # Pixel-accurate PIL text rendering
│   ├── image_judge.py               # Gemini vision judge — accept/reject/retry
│   ├── video_creator.py             # ffmpeg: image + audio → 9:16 MP4 Reel
│   ├── github_uploader.py           # Temp video hosting via GitHub Releases
│   ├── instagram_poster.py          # Graph API: Reel + caption + thumbnail
│   ├── db_manager.py                # posted_quotes.json via GitHub Contents API
│   └── notifier.py                  # Gmail success/failure alerts
│
├── config/                          # ← EDIT THESE (no code changes needed)
│   ├── topics.yml                   #   Quote topics, subcategories, day-of-week
│   ├── styles.yml                   #   Visual styles and category mapping
│   └── curated_quotes.yml           #   Real attributed quotes (fallback pool)
│
├── data/
│   └── posted_quotes.json           # Auto-managed repeat-prevention DB
│
├── assets/
│   ├── audio/background.mp3         # Fallback audio (used when theme file is missing)
│   ├── audio/morning.mp3            # Per-theme audio (optional, auto-detected by name)
│   ├── audio/wisdom.mp3             # …one file per theme, any missing → background.mp3
│   └── audio/{theme}.mp3            # morning|wisdom|love|mindfulness|goodnight|latenight
│   └── fonts/                       # Auto-downloaded at first run
│
└── .github/workflows/
    └── post_quotes.yml              # Cron schedule + secrets wiring
```

---

## Troubleshooting

**Instagram token expired** — Regenerate and update `INSTAGRAM_ACCESS_TOKEN`. Tokens last 60 days.

**"Reel container creation failed"** — Repo must be **public** so Instagram can fetch the video from GitHub Releases.

**Actions not running on schedule** — GitHub pauses Actions on inactive repos. Push any small commit to wake them up.

**Image has watermark text rendered in it** — The `[style_name]` bracket is stripped before sending to Imagen. Verify the `re.sub` at the top of `get_image()` in `src/image_generator.py` is intact.

**Text too small** — Font sizes: `big_center=108pt`, `sentence_reveal=96pt`, `full_card=88pt`. Minimum floor is 82pt. Check `design_director.py` `_DEFAULTS` and `image_composer.py` `_fit_text()`.

**DB save failed** — Confirm `permissions: contents: write` is in the workflow YAML (set by default). Check `GITHUB_TOKEN` is available.

**Repeat quota exhausted** — Lower `REPEAT_WINDOW_DAYS` or add more quotes to `config/curated_quotes.yml`.
