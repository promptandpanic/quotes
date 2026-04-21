# Daily Dose of Wisdom — Instagram Bot

Fully automated Instagram Reels bot for **@_daily_dose_of_wisdom__**  
Posts **7 quote Reels per day** with AI-generated visuals — zero manual effort.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              cron-job.org (7x/day, IST timings)                             │
│                                                                             │
│  scheduled job → POST /actions/workflows/{workflow}/dispatches → GitHub     │
│  Actions runs (workflow_dispatch) → THEME env var → python main.py          │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  main.py  —  Pipeline Orchestrator                                          │
│                                                                             │
│  1.  Select theme (THEME env var or matched cron schedule)                  │
│  2.  Load DB → active posted hashes (repeat window)                         │
│  3.  Pull 90-day topic hints + recent styles → avoid repetition             │
│  4.  Generate quote (Gemini: real author or original, scored in 1 call)     │
│  5.  Design brief loop (up to 3 attempts):                                  │
│        a. Creative brief (font, layout, image_prompt, overlay, colors)      │
│        b. Generate background image (provider chain, configurable order)    │
│        c. Compose image (pixel-accurate text overlay)                       │
│        d. Judge image (5-dimension score) → accept or retry                 │
│  6.  Gradient fallback if all 3 attempts fail                               │
│  7.  Create Reel video (ffmpeg, 15s, 9:16)                                  │
│  8.  Upload video to GitHub Releases (temp public URL)                      │
│  9.  Post Reel + custom thumbnail to Instagram                              │
│  10. Delete temp GitHub Release asset                                       │
│  11. Record quote + style in DB → save                                      │
│  12. Notify via email                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data flow

```
THEME env var
  │
  ▼
src/config.py ──────────── THEMES dict → name, IST label, hashtags
  │
  ▼
src/db_manager.py ───────── posted_quotes.json (GitHub Contents API)
  │                            → active hashes (repeat window)
  │                            → recent topic hints (90 days)
  │                            → recent styles (for design director rotation)
  ▼
src/quote_generator.py ──── ONE Gemini call: finds/writes quote + scores it
  │   reads:
  │   ├── config/topics.yml          ← topics, day-of-week, cultural traditions
  │   ├── config/curated_quotes.yml  ← 50 curated quotes per theme (fallback)
  │   └── src/config.py FALLBACK_QUOTES  ← hardcoded emergency fallback
  │
  │   returns: { text, author, highlight, image_hint, source }
  ▼
src/design_director.py ──── Gemini creative director → full render spec
  │   reads:
  │   └── config/styles.yml          ← 17 visual styles, weights, category map
  │
  │   returns: { font, font_size, layout, text_zone, overlay,
  │              image_prompt, highlight, highlight_color, author_color,
  │              decoration, mood_note, animation }
  ▼
src/image_generator.py ──── Background image (configurable provider order)
  │   1. Leonardo AI     — primary (Flux 2 Pro paid / Phoenix free fallback)
  │   2. Gemini Imagen   — paid, native 9:16
  │   3. Gemini Flash    — free tier
  │   4. Pollinations    — free, no key needed
  │   5. Static images   — assets/static/{theme}.jpg (pre-generated)
  │   6. PIL gradient    — zero-dependency final fallback
  │
src/image_composer.py ───── Pixel-accurate PIL text overlay
  │   reads: assets/fonts/ (auto-downloaded at first run)
  │
src/image_judge.py ─────── Gemini vision — 5-dimension weighted score
  │   image_hook 25% + image_quality 20% + text_readability 20%
  │   + quote_impact 25% + image_text_harmony 10%
  │   accept if weighted ≥ 6 AND readability ≥ 5
  ▼
src/video_creator.py ───── ffmpeg → 9:16 MP4 Reel (15s)
  │   ├── sentence_reveal: lines fade in one by one
  │   └── fade / full_card: crossfade image, text visible throughout
  │   reads: assets/audio/{theme}.mp3 (falls back to background.mp3)
  │
src/github_uploader.py ──── Upload MP4 to GitHub Releases (public temp URL)
  │
src/instagram_poster.py ─── Post Reel via Instagram Graph API
  │   ├── build_caption() → Gemini writes hook + 20 hashtags (1 call)
  │   └── post_reel(video_url, caption, thumb_url)
  │
src/db_manager.py ────────── mark_posted(quote, theme, style) → save DB
  │
src/notifier.py ─────────── Gmail success/failure email
```

---

## Posting schedule

Schedules are managed via cron-job.org and based on India (IST) timings.

| IST | Theme | Workflow |
|---|---|---|
| 7:30 AM | Morning Motivation | `post_morning.yml` |
| 11:30 AM | Life Wisdom | `post_wisdom.yml` |
| 3:30 PM | Love & Relationships | `post_love.yml` |
| 6:30 PM | Mindfulness & Inner Peace | `post_mindfulness.yml` |
| 8:45 PM | Life Wisdom (Evening) | `post_wisdom_evening.yml` |
| 10:30 PM | Goodnight & Gratitude | `post_goodnight.yml` |
| 1:30 AM | Late Night Feels | `post_latenight.yml` |

---

## GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

### Required

| Secret | Description |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio key — [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| `INSTAGRAM_ACCESS_TOKEN` | 60-day Meta long-lived token |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Numeric Instagram Business/Creator account ID |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions — no action needed |

### Image generation

| Secret | Default | Description |
|---|---|---|
| `LEONARDO_API_KEY` | — | [app.leonardo.ai](https://app.leonardo.ai) → User Settings → API. Enables Leonardo as primary image source. |
| `LEONARDO_MODEL_ID` | `6bef9f1b-29cb-40c7-b9df-32b51c1f67d3` | Leonardo model to use. See model table below. |
| `IMAGE_PROVIDER_ORDER` | `leonardo,imagen,gemini,pollinations` | Comma-separated list controlling which image source is tried first. Change to skip or reorder providers. |

**Leonardo model options:**

| Model | `LEONARDO_MODEL_ID` | Cost | Quality |
|---|---|---|---|
| Leonardo Phoenix (default) | `6bef9f1b-29cb-40c7-b9df-32b51c1f67d3` | Free daily quota | Good |
| Flux Dev | `b2614463-296c-462a-9586-aafdb8f00e36` | Free daily quota | Good |
| **Flux 2 Pro** | `flux-pro-2.0` | ~$0.046/image (paid credit) | Excellent, native 9:16 |

> When `LEONARDO_MODEL_ID=flux-pro-2.0` and the paid quota/credit runs out, the bot automatically falls back to Leonardo Phoenix (free) before leaving Leonardo entirely.

**IMAGE_PROVIDER_ORDER examples:**

```
# Default — Leonardo first, then Gemini
IMAGE_PROVIDER_ORDER=leonardo,imagen,gemini,pollinations

# Skip Leonardo, use Gemini Imagen first
IMAGE_PROVIDER_ORDER=imagen,gemini,pollinations

# Free-only (no paid APIs)
IMAGE_PROVIDER_ORDER=leonardo,gemini,pollinations

# Pollinations only (testing, no keys needed)
IMAGE_PROVIDER_ORDER=pollinations
```

### AI text models

| Secret | Default | Description |
|---|---|---|
| `GEMINI_TEXT_MODEL` | `gemini-2.5-flash-preview-04-17` | Used for quote generation, design briefs, captions, image judging |
| `GEMINI_TEXT_MODEL_FALLBACK` | `gemini-2.0-flash` | Reserved for future fallback wiring |
| `GEMINI_IMAGE_MODEL` | `imagen-4.0-fast-generate-001` | Gemini image model (used when Leonardo unavailable) |
| `GEMINI_IMAGE_MODEL_FALLBACK` | `gemini-2.5-flash-preview-04-17` | Free-tier Gemini image generation |

### Other optional secrets

| Secret | Default | Description |
|---|---|---|
| `REPEAT_WINDOW_DAYS` | `10` | Days before a quote can repeat |
| `SMTP_USERNAME` | — | Gmail address for success/failure notifications |
| `SMTP_PASSWORD` | — | Gmail App Password (16-char, not login password) |
| `NOTIFY_EMAILS` | — | Comma-separated recipient emails |

**Gmail App Password:** Google Account → Security → 2-Step Verification → App passwords → create one named "quotes-bot" → copy the 16-char code.

---

## Where to make changes

### Quote topics → `config/topics.yml`

The main editorial file. Edit freely — no code changes needed.

```yaml
categories:

  morning:
    max_words: 18           # hard cap enforced in prompt + validation
    topics:                 # general pool, Gemini picks from these
      - "add your topic here"

    workout_topics:         # injected ~30% of morning posts
      - "gym consistency — showing up even when motivation is zero"

  wisdom:
    max_words: 24
    topics:
      - "..."
    cultural_topics:        # ~40% of wisdom posts pick one tradition
      - tradition: "Japanese wisdom"
        image_hint: "sumi-e ink painting, washi paper texture"
        topics:
          - "wabi-sabi — finding beauty in imperfection"

  love:
    red_green_flag_topics:  # ~35% of love posts use this format
      - "green flag: someone who stays consistent even when you're difficult"

  mindfulness:
    spiritual_topics:       # ~40% of mindfulness posts quote a teacher
      - "Sadhguru — on the nature of the mind"

  latenight:
    topic_groups:           # weighted random selection
      - weight: 40
        topics:
          - "the 3am thoughts that won't let you sleep"
```

**To add a new theme:** add a top-level key here, add it to `THEMES` in `src/config.py`, add a cron line in `.github/workflows/post_quotes.yml`.

---

### Visual styles → `config/styles.yml`

Controls what images the design director generates. No code changes needed.

```yaml
styles:

  my_new_style:
    description: >
      Describe exactly what the image should look like — art style, subjects,
      colours, mood, which area stays dark for text (top / center / bottom third).
      This goes directly into the image prompt sent to the image model.
    categories: [morning, wisdom]   # which themes can use this style
    weight: high                    # high / medium / low
```

**Current styles (17 total):**

| Style | Categories | Weight |
|---|---|---|
| `minimalist_vector` | morning, wisdom, mindfulness | high |
| `ghibli_anime` | all | high |
| `watercolour_ink` | love, mindfulness, goodnight, wisdom | high |
| `whimsical_sketch` | wisdom, love, goodnight, latenight | high |
| `silhouette_landscape` | morning, wisdom, goodnight, latenight | high |
| `cozy_aesthetic` | goodnight, latenight, love, mindfulness | high |
| `minimalist_nature` | mindfulness, wisdom, goodnight | high |
| `anthropomorphic_vintage` | wisdom, love, goodnight | medium |
| `vector_girl` | love, goodnight, mindfulness, morning | medium |
| `vector_couple` | love, goodnight | medium |
| `nocturnal_aesthetic` | latenight, goodnight | medium |
| `minimalist_line_art` | wisdom, mindfulness, morning | medium |
| `risograph_print` | morning, love, wisdom | medium |
| `metaphorical_digital` | wisdom, latenight, mindfulness | medium |
| `wholesome_doodle` | love, morning, goodnight | medium |
| `double_exposure` | latenight, love, wisdom | low |
| `dark_surreal` | latenight, wisdom | low |

> **Global image rule:** All prompts explicitly block photorealistic humans, portrait photography, text, logos, and watermarks. Illustrations, paintings, flat vector art, ink sketches, and abstract art only.

> **Style rotation:** The DB records which style was used for each post. The design director receives the last 20 styles used and avoids repeating them.

---

### Curated quotes → `config/curated_quotes.yml`

50 hand-picked quotes per theme (300 total) used when Gemini is unavailable.

```yaml
quotes:
  morning:
    - text: "The secret of getting ahead is getting started."
      author: "Mark Twain"
      highlight: "getting started"   # optional — words to emphasise
  # wisdom, love, mindfulness, goodnight, latenight — same structure
```

Unknown or anonymous authors are silently skipped on-screen — no "— Unknown" displayed.

---

### Change post timing

Update the schedule on cron-job.org for the relevant job. Each job maps 1:1 to a workflow file in `.github/workflows/`.

---

### Add or change fonts

**Two-file change:**

1. **`src/image_composer.py` — `_FONT_URLS` dict** — add the font name and TTF download URL:
   ```python
   "myfont": "https://fonts.gstatic.com/s/myfont/.../MyFont-Bold.ttf",
   ```

2. **`src/design_director.py` — `_BRIEF_PROMPT`** — add it to the AVAILABLE FONTS section:
   ```
   myfont — short style description → best themes or moods
   ```

**Currently available fonts (14):**

| Font | Style | Best for |
|---|---|---|
| `bebas` | All-caps ultra-bold | Morning energy, power |
| `anton` | Condensed heavy poster | Punchy one-liners |
| `oswald` | Condensed bold editorial | Wisdom, stoic quotes |
| `montserrat` | Geometric bold | Any theme |
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

Fonts are auto-downloaded to `assets/fonts/` on first use. Falls back to `lato` if a download fails.

---

## Local development

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO
cd YOUR_REPO

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Fill in your keys in .env
```

**Dry-run** — generates image + video in `output/`, prints caption to screen, skips all Instagram posting:

```bash
DRY_RUN=true THEME=morning python main.py
DRY_RUN=true THEME=wisdom python main.py
DRY_RUN=true python main.py    # auto-selects theme by current IST hour
```

The dry-run prints a ready-to-copy caption block at the end:

```
────────────────────────────────────────────────────────────
CAPTION (copy-paste for Instagram):
────────────────────────────────────────────────────────────
"Quote text here."
— Author Name

Hook line that adds context or reflection.
Save this for the days you need it.

@_daily_dose_of_wisdom__

#hashtag1 #hashtag2 ...
────────────────────────────────────────────────────────────
```

Use this to manually upload Reels without spending API tokens on a live post.

---

## One-time Meta setup

**Step 1 — Instagram Business Account ID**

In [Graph API Explorer](https://developers.facebook.com/tools/explorer/):
```
GET /me/accounts                                    ← find your Page ID
GET /{page-id}?fields=instagram_business_account   ← copy the numeric id
```

**Step 2 — Long-lived access token**

In Graph API Explorer, add permissions:
`instagram_basic` · `instagram_content_publish` · `pages_read_engagement`

Generate short-lived token, then exchange for 60 days:
```bash
curl "https://graph.facebook.com/v21.0/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id=YOUR_APP_ID
  &client_secret=YOUR_APP_SECRET
  &fb_exchange_token=YOUR_SHORT_LIVED_TOKEN"
```

> Token expires after 60 days — set a calendar reminder.  
> For a permanent token: create a **System User** in Meta Business Suite.

---

## Add audio (optional but recommended)

Drop a file named `{theme}.mp3` into `assets/audio/` — no code change needed.

| Theme | File | Vibe |
|---|---|---|
| morning | `morning.mp3` | Uplifting acoustic / bright piano |
| wisdom | `wisdom.mp3` | Ambient sitar + tabla drone |
| love | `love.mp3` | Soft warm piano / acoustic guitar |
| mindfulness | `mindfulness.mp3` | Tibetan singing bowls + nature |
| goodnight | `goodnight.mp3` | Gentle lullaby piano |
| latenight | `latenight.mp3` | Lo-fi melancholic / rain ambience |
| *(fallback)* | `background.mp3` | Any calm instrumental |

Free sources: [pixabay.com/music](https://pixabay.com/music) · [mixkit.co](https://mixkit.co/free-music-tracks) · [uppbeat.io](https://uppbeat.io)

Trim to ~20s:
```bash
ffmpeg -i downloaded.mp3 -t 20 -c:a libmp3lame -q:a 2 assets/audio/morning.mp3
```

---

## Project structure

```
├── main.py                          # Orchestrator
│
├── src/
│   ├── config.py                    # THEMES, model names, FALLBACK_QUOTES
│   ├── content_config.py            # Loads YAMLs, topic_info + style helpers
│   ├── quote_generator.py           # Quote gen + quality scoring in one Gemini call
│   ├── design_director.py           # Gemini creative brief (font, layout, colors, prompt)
│   ├── image_generator.py           # Leonardo → Imagen → Gemini → Pollinations → static → gradient
│   ├── image_composer.py            # PIL text overlay, font metrics, author attribution
│   ├── image_judge.py               # Gemini vision — 5-dimension weighted score
│   ├── video_creator.py             # ffmpeg: image + audio → 9:16 MP4 Reel
│   ├── github_uploader.py           # Temp video hosting via GitHub Releases
│   ├── instagram_poster.py          # Graph API: Reel + caption + thumbnail
│   ├── db_manager.py                # posted_quotes.json via GitHub Contents API
│   └── notifier.py                  # Gmail success/failure alerts
│
├── config/                          # ← EDIT THESE freely, no code changes needed
│   ├── topics.yml                   #   Topics, subcategories, cultural traditions
│   ├── styles.yml                   #   17 visual styles with weights + category mapping
│   └── curated_quotes.yml           #   50 curated quotes per theme (300 total)
│
├── data/
│   └── posted_quotes.json           # Auto-managed repeat-prevention DB
│
├── assets/
│   ├── audio/                       # background.mp3 + per-theme mp3s
│   ├── fonts/                       # Auto-downloaded TTF files
│   └── static/                      # Pre-generated fallback images (one per theme)
│
└── .github/workflows/
    └── post_*.yml                   # One workflow per theme, triggered via workflow_dispatch
```

---

## Troubleshooting

**Instagram token expired** — Regenerate and update `INSTAGRAM_ACCESS_TOKEN`. Tokens last 60 days.

**"Reel container creation failed"** — Repo must be **public** so Instagram can fetch the video URL from GitHub Releases.

**Actions not running** — Workflows are triggered via cron-job.org. Check the job's execution log there first. You can also trigger manually via Actions → Run workflow.

**Image has text or watermark baked in** — The `[style_name]` bracket prefix is stripped before sending to any image model. Check the `re.sub` at the top of `get_image()` in `src/image_generator.py` is intact.

**Quote generation always falls back to curated** — Check your Gemini API key and spending cap at [aistudio.google.com/settings/billing](https://aistudio.google.com/settings/billing). A 429 `RESOURCE_EXHAUSTED` error triggers an immediate fallback to the curated pool (no retries wasted).

**DB save failed** — Confirm `permissions: contents: write` is in the workflow YAML. Check `GITHUB_TOKEN` is available in the job env.

**Leonardo images not generating** — Run `DRY_RUN=true` locally and check the log line `Image gen — Leonardo (...)`. A 402 means daily free quota is exhausted; the bot falls back to Phoenix automatically. For Flux 2 Pro, check your paid credit balance at [app.leonardo.ai](https://app.leonardo.ai).
