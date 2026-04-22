"""Central config: themes, timing, image dimensions, and constants."""
import os
from datetime import timezone, timedelta

# ---------------------------------------------------------------------------
# AI model selection (override via .env / GitHub Secrets)
# ---------------------------------------------------------------------------

# Text models
GEMINI_TEXT_MODEL          = os.environ.get("GEMINI_TEXT_MODEL",          "gemini-3-flash-preview")
GEMINI_TEXT_MODEL_FALLBACK = os.environ.get("GEMINI_TEXT_MODEL_FALLBACK", "gemini-2.5-flash")

# Image models — Leonardo is tried first (free), then Gemini
GEMINI_IMAGE_MODEL          = os.environ.get("GEMINI_IMAGE_MODEL",          "imagen-4.0-fast-generate-001")
GEMINI_IMAGE_MODEL_FALLBACK = os.environ.get("GEMINI_IMAGE_MODEL_FALLBACK", "gemini-3.1-flash-image-preview")

IST = timezone(timedelta(hours=5, minutes=30))

# Each theme maps to a UTC hour matching its GitHub Actions cron.
# IST = UTC + 5:30:
#   07:00 AM IST = 01:30 UTC  →  utc_hour=1
#   12:00 PM IST = 06:30 UTC  →  utc_hour=6
#   03:00 PM IST = 09:30 UTC  →  utc_hour=9
#   06:00 PM IST = 12:30 UTC  →  utc_hour=12
#   09:00 PM IST = 15:30 UTC  →  utc_hour=15
#   01:30 AM IST = 20:00 UTC  →  utc_hour=19

THEMES = {
    "morning": {
        "name":      "Morning Motivation",
        "utc_hour":  1,
        "ist_label": "07:00 AM IST",
        "hashtags": [
            "#MorningMotivation", "#GoodMorningIndia", "#DailyMotivation",
            "#Motivation", "#GrowthMindset", "#PositiveVibes",
            "#IndianYouth", "#MorningVibes", "#Inspiration", "#SelfImprovement",
        ],
    },
    "wisdom": {
        "name":      "Life Wisdom",
        "utc_hour":  6,
        "ist_label": "12:00 PM IST",
        "hashtags": [
            "#Wisdom", "#LifeQuotes", "#IndianWisdom",
            "#DeepThoughts", "#QuoteOfTheDay", "#DailyWisdom",
            "#LifeLesson", "#ThinkDeep", "#IndianYouth", "#InspirationDaily",
        ],
    },
    "love": {
        "name":      "Love & Relationships",
        "utc_hour":  9,
        "ist_label": "03:00 PM IST",
        "hashtags": [
            "#LoveQuotes", "#Relationships", "#IndianLove",
            "#HeartQuotes", "#RelationshipQuotes", "#LoveAndLife",
            "#CoupleGoals", "#DesiLove", "#LoveVibes", "#HeartfeltQuotes",
        ],
    },
    "mindfulness": {
        "name":      "Mindfulness & Inner Peace",
        "utc_hour":  12,
        "ist_label": "06:00 PM IST",
        "hashtags": [
            "#Mindfulness", "#InnerPeace", "#MentalHealthIndia",
            "#SelfCare", "#Meditation", "#SelfLove",
            "#MindfulLiving", "#InnerHealing", "#WellnessIndia", "#MentalHealth",
        ],
    },
    "goodnight": {
        "name":      "Goodnight & Gratitude",
        "utc_hour":  15,
        "ist_label": "09:00 PM IST",
        "hashtags": [
            "#GoodNightIndia", "#GoodNight", "#NightVibes",
            "#Gratitude", "#NightThoughts", "#GoodNightQuotes",
            "#SleepWell", "#GratitudeDaily", "#NightOwl", "#Bedtime",
        ],
    },
    "latenight": {
        "name":      "Late Night Feels",
        "utc_hour":  19,
        "ist_label": "01:30 AM IST",
        "hashtags": [
            "#LateNightThoughts", "#MidnightThoughts", "#Overthinking",
            "#3amThoughts", "#LateNightFeels", "#NightThoughts",
            "#DeepThoughts", "#MidnightVibes", "#InsomniaThoughts", "#LateNight",
        ],
    },
    "womenpower": {
        "name":      "She Feels",
        "utc_hour":  4,
        "ist_label": "10:00 AM IST",
        "tts":       False,  # background music only — no voice narration
        "hashtags": [
            "#WomenOfIndia", "#IndianWomen", "#GirlsWhoFeel",
            "#Womanhood", "#SheFeels", "#WomenQuotes",
            "#FeminineEnergy", "#GirlsTalk", "#Women", "#SheFelt",
        ],
    },
}

INSTAGRAM_HANDLE = "_daily_dose_of_wisdom__"
WATERMARK_TEXT   = f"@{INSTAGRAM_HANDLE}"

IMAGE_WIDTH  = 1080
IMAGE_HEIGHT = 1920   # 9:16 portrait — ideal for Reels

REEL_DURATION_SEC = 15
AUDIO_FILE        = "assets/audio/background.mp3"

REPEAT_WINDOW_DAYS = int(os.environ.get("REPEAT_WINDOW_DAYS", "3"))

# ---------------------------------------------------------------------------
# TTS (Text-to-Speech) — provider cascade and voice selection
# ---------------------------------------------------------------------------

# Comma-separated provider priority list: elevenlabs,edge,none
# Tried left to right; first success is used. "none" = intentionally silent (music only).
# Default: ElevenLabs → music only. Enable edge-tts via EDGE_TTS_ENABLED secret.
TTS_PROVIDERS = os.environ.get("TTS_PROVIDERS", "elevenlabs,edge,none")

# ElevenLabs
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL   = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")

# ElevenLabs global fallback voices (used when no per-theme override matches)
# Male:   Declan Sage (kqVT88a5QfII1HNAEPTJ) — Wise, Captivating
# Female: Autumn Veil (KoVIHoyLDrQyd4pGalbs) — Deep, Thoughtful
ELEVENLABS_VOICE_MALE   = os.environ.get("ELEVENLABS_VOICE_MALE",   "kqVT88a5QfII1HNAEPTJ")
ELEVENLABS_VOICE_FEMALE = os.environ.get("ELEVENLABS_VOICE_FEMALE", "KoVIHoyLDrQyd4pGalbs")

# Per-theme voice overrides — each individually overridable via env var.
# Resolution order: theme+gender override → global fallback above.
ELEVENLABS_THEME_VOICES: dict[str, str] = {
    # morning — rich, smooth energy to start the day
    "morning:male":       os.environ.get("ELEVENLABS_VOICE_MORNING_MALE",       "qNkzaJoHLLdpvgh5tISm"),  # Carter       — Rich, Smooth, Rugged
    "morning:female":     os.environ.get("ELEVENLABS_VOICE_MORNING_FEMALE",     "KoVIHoyLDrQyd4pGalbs"),  # Autumn Veil  — Deep, Thoughtful
    # wisdom — wise, measured, captivating
    "wisdom:male":        os.environ.get("ELEVENLABS_VOICE_WISDOM_MALE",        "kqVT88a5QfII1HNAEPTJ"),  # Declan Sage  — Wise, Captivating
    "wisdom:female":      os.environ.get("ELEVENLABS_VOICE_WISDOM_FEMALE",      "KoVIHoyLDrQyd4pGalbs"),  # Autumn Veil  — Deep, Thoughtful
    # love — warm, smooth, gentle
    "love:male":          os.environ.get("ELEVENLABS_VOICE_LOVE_MALE",          "qNkzaJoHLLdpvgh5tISm"),  # Carter       — Rich, Smooth, Rugged
    "love:female":        os.environ.get("ELEVENLABS_VOICE_LOVE_FEMALE",        "Qggl4b0xRMiqOwhPtVWT"),  # Clara        — Spiritual, Gentle
    # mindfulness — calm, grounded, meditative
    "mindfulness:male":   os.environ.get("ELEVENLABS_VOICE_MINDFULNESS_MALE",   "zO2z8i0srbO9r7GT5C4h"),  # Christopher  — Meditation, ASMR
    "mindfulness:female": os.environ.get("ELEVENLABS_VOICE_MINDFULNESS_FEMALE", "Qggl4b0xRMiqOwhPtVWT"),  # Clara        — Spiritual, Calming
    # goodnight — soft, settled, peaceful
    "goodnight:male":     os.environ.get("ELEVENLABS_VOICE_GOODNIGHT_MALE",     "zO2z8i0srbO9r7GT5C4h"),  # Christopher  — Meditation, ASMR
    "goodnight:female":   os.environ.get("ELEVENLABS_VOICE_GOODNIGHT_FEMALE",   "Qggl4b0xRMiqOwhPtVWT"),  # Clara        — Spiritual, Settled
    # latenight — deep, dark, introspective 3am energy
    "latenight:male":     os.environ.get("ELEVENLABS_VOICE_LATENIGHT_MALE",     "U1Vk2oyatMdYs096Ety7"),  # Michael      — Deep, Dark, Urban
    "latenight:female":   os.environ.get("ELEVENLABS_VOICE_LATENIGHT_FEMALE",   "KoVIHoyLDrQyd4pGalbs"),  # Autumn Veil  — Deep, Thoughtful (3am)
}

# Microsoft Edge TTS — disabled by default; set EDGE_TTS_ENABLED=true in secrets to enable.
# When disabled the fallback is music-only (no narration).
EDGE_TTS_ENABLED = os.environ.get("EDGE_TTS_ENABLED", "false").lower() == "true"

# edge-tts voice names (Microsoft neural — Indian English)
EDGE_TTS_VOICE_MALE   = os.environ.get("EDGE_TTS_VOICE_MALE",   "en-IN-PrabhatNeural")
EDGE_TTS_VOICE_FEMALE = os.environ.get("EDGE_TTS_VOICE_FEMALE", "en-IN-NeerjaExpressiveNeural")

# Static voice gender used when the AI brief doesn't specify one
# (applies to curated/fallback quotes where design_director hasn't run)
TTS_STATIC_VOICE_GENDER = os.environ.get("TTS_STATIC_VOICE_GENDER", "male")

# Background music volume (0.0–1.0) when TTS narration is active
# ~0.12 (~-18 dB) ducks the music under the spoken voice
TTS_MUSIC_VOLUME = float(os.environ.get("TTS_MUSIC_VOLUME", "0.12"))

GITHUB_DB_PATH    = "data/posted_quotes.json"
MEDIA_RELEASE_TAG = "media-pool"

FALLBACK_QUOTES = {
    "morning": [
        {"text": "It always seems impossible until it's done.", "author": "Nelson Mandela"},
        {"text": "The secret of getting ahead is getting started.", "author": "Mark Twain"},
        {"text": "You don't have to be great to start, but you have to start to be great.", "author": "Zig Ziglar"},
        {"text": "Discipline is choosing between what you want now and what you want most.", "author": "Abraham Lincoln"},
        {"text": "Do something today that your future self will thank you for.", "author": "Sean Patrick Flanery"},
        {"text": "Success is the sum of small efforts, repeated day in and day out.", "author": "Robert Collier"},
        {"text": "Don't count the days. Make the days count.", "author": "Muhammad Ali"},
        {"text": "Fall seven times, stand up eight.", "author": "Japanese Proverb"},
        {"text": "Work hard in silence. Let your success make the noise.", "author": "Frank Ocean"},
        {"text": "Nothing will work unless you do.", "author": "Maya Angelou"},
    ],
    "wisdom": [
        {"text": "Knowing yourself is the beginning of all wisdom.", "author": "Aristotle"},
        {"text": "Yesterday I was clever, so I wanted to change the world. Today I am wise, so I am changing myself.", "author": "Rumi"},
        {"text": "The unexamined life is not worth living.", "author": "Socrates"},
        {"text": "Real knowledge is to know the extent of one's ignorance.", "author": "Confucius"},
        {"text": "The only true wisdom is in knowing you know nothing.", "author": "Socrates"},
        {"text": "Pain is inevitable. Suffering is optional.", "author": "Haruki Murakami"},
        {"text": "Not all those who wander are lost.", "author": "J.R.R. Tolkien"},
        {"text": "We accept the love we think we deserve.", "author": "Stephen Chbosky"},
        {"text": "The journey of a thousand miles begins with one step.", "author": "Lao Tzu"},
        {"text": "In the middle of every difficulty lies opportunity.", "author": "Albert Einstein"},
    ],
    "love": [
        {"text": "The best thing to hold onto in life is each other.", "author": "Audrey Hepburn"},
        {"text": "Where there is love, there is life.", "author": "Mahatma Gandhi"},
        {"text": "A friend is someone who knows all about you and still loves you.", "author": "Elbert Hubbard"},
        {"text": "The greatest happiness of life is the conviction that we are loved.", "author": "Victor Hugo"},
        {"text": "Being deeply loved by someone gives you strength, while loving someone deeply gives you courage.", "author": "Lao Tzu"},
        {"text": "Love does not consist in gazing at each other, but in looking outward together in the same direction.", "author": "Antoine de Saint-Exupéry"},
        {"text": "A loving heart is the truest wisdom.", "author": "Charles Dickens"},
        {"text": "At the touch of love everyone becomes a poet.", "author": "Plato"},
        {"text": "The heart wants what it wants — or else it does not care.", "author": "Emily Dickinson"},
        {"text": "Keep love in your heart. A life without it is like a sunless garden when winter comes.", "author": "Oscar Wilde"},
    ],
    "mindfulness": [
        {"text": "Peace comes from within. Do not seek it without.", "author": "Buddha"},
        {"text": "The present moment is the only moment available to us, and it is the door to all moments.", "author": "Thich Nhat Hanh"},
        {"text": "The mind is everything. What you think, you become.", "author": "Buddha"},
        {"text": "Almost everything will work again if you unplug it for a few minutes — including you.", "author": "Anne Lamott"},
        {"text": "In today's rush, we all think too much, seek too much, want too much and forget about the joy of just being.", "author": "Eckhart Tolle"},
        {"text": "To the mind that is still, the whole universe surrenders.", "author": "Lao Tzu"},
        {"text": "Nature does not hurry, yet everything is accomplished.", "author": "Lao Tzu"},
        {"text": "Out beyond ideas of wrongdoing and rightdoing there is a field. I'll meet you there.", "author": "Rumi"},
        {"text": "This too shall pass.", "author": "Persian Proverb"},
        {"text": "Wherever you are, be all there.", "author": "Jim Elliot"},
    ],
    "goodnight": [
        {"text": "Even the darkest night will end and the sun will rise.", "author": "Victor Hugo"},
        {"text": "Each night, when I go to sleep, I die. And the next morning, when I wake up, I am reborn.", "author": "Mahatma Gandhi"},
        {"text": "Finish each day and be done with it. Tomorrow is a new day.", "author": "Ralph Waldo Emerson"},
        {"text": "The moon is a loyal companion. It never leaves. It's always there, watching, steadfast, knowing us in our light and dark moments.", "author": "Tahereh Mafi"},
        {"text": "Sleep is the best meditation.", "author": "Dalai Lama"},
        {"text": "The best bridge between despair and hope is a good night's sleep.", "author": "E. Joseph Cossman"},
        {"text": "Gratitude unlocks the fullness of life.", "author": "Melody Beattie"},
        {"text": "Each day provides its own gifts.", "author": "Marcus Aurelius"},
        {"text": "Rest when you're weary. Refresh and renew yourself, your body, your mind, your spirit.", "author": "Ralph Marston"},
        {"text": "One must maintain a little bit of summer, even in the middle of winter.", "author": "Henry David Thoreau"},
    ],
    "latenight": [
        {"text": "The wound is the place where the light enters you.", "author": "Rumi"},
        {"text": "Not all those who wander are lost.", "author": "J.R.R. Tolkien"},
        {"text": "We accept the love we think we deserve.", "author": "Stephen Chbosky"},
        {"text": "You can't stop the waves, but you can learn to surf.", "author": "Jon Kabat-Zinn"},
        {"text": "Almost everything will work again if you unplug it for a few minutes — including you.", "author": "Anne Lamott"},
        {"text": "In today's rush we all think too much, seek too much, want too much and forget about the joy of just being.", "author": "Eckhart Tolle"},
        {"text": "Pain is inevitable. Suffering is optional.", "author": "Haruki Murakami"},
        {"text": "The most common form of despair is not being who you are.", "author": "Søren Kierkegaard"},
        {"text": "One must still have chaos in oneself to be able to give birth to a dancing star.", "author": "Friedrich Nietzsche"},
        {"text": "It's okay to not be okay — as long as you are not giving up.", "author": "Karen Salmansohn"},
    ],
    "womenpower": [
        {"text": "She was tired. Not the sleepy kind. The kind that rest doesn't fix.", "author": "Original"},
        {"text": "She said I'm fine so many times she almost forgot she wasn't.", "author": "Original"},
        {"text": "She knew. She just wasn't ready to know yet.", "author": "Original"},
        {"text": "She didn't leave angry. She left quietly, which was so much worse.", "author": "Original"},
        {"text": "She cried in the car again. That's where the real conversations happen.", "author": "Original"},
        {"text": "She laughed it off. She's very good at that.", "author": "Original"},
        {"text": "She chose herself. It felt selfish for about three days. Then it felt like oxygen.", "author": "Original"},
        {"text": "She's everyone's safe place. She wishes she had one too.", "author": "Original"},
        {"text": "She stopped waiting. Not because she didn't care. Because she cared too much to keep going.", "author": "Original"},
        {"text": "She kept giving chances because she kept seeing potential. The potential was never the person.", "author": "Original"},
    ],
}
