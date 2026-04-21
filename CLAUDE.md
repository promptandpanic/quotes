# Instagram Quotes Bot — @_daily_dose_of_wisdom__

Fully automated Instagram quote video bot. Posts 7x/day via GitHub Actions, generates original quotes with Gemini, creates AI background images, composes text overlays, adds TTS narration, and posts as Reels.

---

## Quick orientation

```
main.py                     entry point — orchestrates the full pipeline
src/
  config.py                 THEMES dict (posting schedule, hashtags, TTS voices)
  content_config.py         loads topics.yml + styles.yml; builds prompts for Gemini
  quote_generator.py        generates quote text via Gemini
  design_director.py        Gemini acts as creative director → returns full render spec (font, overlay, image prompt)
  image_generator.py        image provider cascade: Leonardo → Gemini Imagen → Gemini Flash → Pollinations → static fallback → PIL gradient
  image_composer.py         PIL-based composer: overlays text, highlight phrase, author, watermark
  image_judge.py            Gemini judges the composed image (score/10); bad scores trigger retry
  video_creator.py          FFmpeg-based Reel creator: Ken Burns animation + TTS audio + background music
  tts.py                    TTS cascade: ElevenLabs → edge-tts → silent
  instagram_poster.py       Instagram Graph API: posts Reel or static image
  db_manager.py             posted-quotes DB in GitHub repo (data/posted_quotes.json)
  github_uploader.py        uploads media to GitHub Releases for a public CDN URL
config/
  topics.yml                topic pools per category (what to write about)
  styles.yml                visual style descriptions sent to Gemini (22 styles)
  curated_quotes.yml        hand-picked fallback quotes (used ~20% of posts)
assets/
  static/                   pre-generated fallback images per theme (last resort before PIL gradient)
  audio/background.mp3      background music for Reels
  fonts/                    bundled Google Fonts (loaded by image_composer)
```

---

## Themes / posting schedule

| Key | Name | IST time | UTC hour | Notes |
|---|---|---|---|---|
| `morning` | Morning Motivation | 07:00 AM | 1 | Reel + TTS |
| `wisdom` | Life Wisdom | 12:00 PM | 6 | Reel + TTS |
| `love` | Love & Relationships | 03:00 PM | 9 | Reel + TTS |
| `mindfulness` | Mindfulness & Inner Peace | 06:00 PM | 12 | Reel + TTS |
| `goodnight` | Goodnight & Gratitude | 09:00 PM | 15 | Reel + TTS |
| `latenight` | Late Night Feels | 01:30 AM | 19 | Reel + TTS |
| `womenpower` | She Feels | 10:00 AM | 4 | **Image only** — no Reel, no TTS |

---

## Visual styles (styles.yml)

22 named styles, each with a rich description Gemini uses to write the `image_prompt`. Gemini picks the best style for each quote's emotion. All styles have 3 fields:

- `description` — full creative brief (sent verbatim to Gemini)
- `categories` — which themes can use this style
- `weight` — `high` / `medium` / `low` (probability signal to Gemini)

**Womenpower** only uses `women_line_art` (minimal ink) and `women_vivid_art` (floral portrait). Gemini picks based on the quote's emotional tone — raw/minimal gets line_art, vivid/expressive gets vivid_art.

The "such as:" examples in style descriptions are creative suggestions, not instructions. Gemini varies them freely based on the specific quote.

---

## Topic system (topics.yml)

Each category has `topics` (flat list) or `topic_groups` (weighted groups with ~% hints for Gemini). `latenight` uses weighted groups:

| Group | Weight | Notes |
|---|---|---|
| relationships_loss | 21% | |
| ambition_parental_pressure | 25% | |
| identity_belonging | 17% | |
| nostalgia_change | 13% | |
| existential_overthinking | 10% | |
| emotional_reveal | 9% | "Seen Without Saying" — silence, clarity, emotional truth |
| microstory_quotes | 5% | One-sentence scene fragments (micro-fiction format, not quotes) |

`microstory_quotes` has a `format_hint` field that gets passed to the quote generator, telling Gemini to write a scene fragment rather than a statement.

---

## Pipeline flow

```
1. Select theme (THEME env var or nearest UTC hour)
2. Load DB → get posted hashes + recent styles (prevents repetition)
3. generate_quote()  — Gemini writes the quote using topic_block
4. Loop up to 3 attempts:
   a. generate_brief()    — Gemini picks style, font, overlay, layout, highlight phrase
   b. get_image()         — generate background via provider cascade
   c. compose()           — PIL overlay: text, highlight, author, watermark
   d. judge_image()       — Gemini scores /10; accept ≥ threshold or keep best
5. create_reel()          — FFmpeg: Ken Burns + TTS audio + ducked background music
6. Post Reel (or image fallback) via Instagram Graph API
7. DB update commit → triggers "chore: update posted-quotes db [skip ci]" auto-commit
```

---

## Running locally

```bash
# dry-run — saves image + video to output/, prints caption
DRY_RUN=true THEME=latenight python main.py

# specific theme
DRY_RUN=true THEME=womenpower python main.py

# auto-selects by current UTC hour
DRY_RUN=true python main.py
```

Required env vars (put in `.env`):
```
GEMINI_API_KEY=...
LEONARDO_API_KEY=...          # optional — Leonardo image provider
ELEVENLABS_API_KEY=...        # optional — TTS narration
INSTAGRAM_ACCESS_TOKEN=...    # not needed for DRY_RUN
INSTAGRAM_BUSINESS_ID=...
GITHUB_TOKEN=...              # for DB save + media upload
```

---

## Key design decisions

- **Gemini is the creative director** — `design_director.py` sends the quote + all available styles to Gemini, which returns a complete render spec (font, color, overlay, image prompt, highlight phrase). No hardcoded style logic.
- **Image providers cascade** — Leonardo (free tier ~150/day) → Gemini Imagen → Gemini Flash → Pollinations → static JPEG → PIL gradient. Set `IMAGE_PROVIDER_ORDER` env var to override.
- **DB is a JSON file in the GitHub repo** (`data/posted_quotes.json`). No external DB needed. Repeat window defaults to 3 days (`REPEAT_WINDOW_DAYS`).
- **womenpower is image-only** — `"video": False` in THEMES config skips Reel creation entirely for that slot.
- **Recent style tracking** — last 20 style names are passed to Gemini to prevent repeated visual styles.

---

## Adding a new theme

1. Add entry to `THEMES` dict in `config.py` (needs `utc_hour`, `name`, `ist_label`, `hashtags`)
2. Add category to `config/topics.yml` under `categories:`
3. Add relevant style names to existing styles' `categories:` lists in `config/styles.yml`, or add new styles
4. Add fallback quotes to `FALLBACK_QUOTES` in `config.py` and `config/curated_quotes.yml`
5. Add GitHub Actions cron job for the UTC hour
6. Generate a static fallback image: `assets/static/{theme_key}.jpg`

---

## Config validation

```bash
# Check styles.yml parses correctly (all 22 styles load)
python3 -c "import yaml; d=yaml.safe_load(open('config/styles.yml')); print(len(d['styles']['styles'] if 'styles' in d.get('styles',{}) else d['styles']), 'styles')"

# Check topics.yml
python3 -c "import yaml; d=yaml.safe_load(open('config/topics.yml')); [print(k, list(v.keys())) for k,v in d['categories'].items()]"
```
