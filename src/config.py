"""Central config: themes, timing, image dimensions, and constants."""
import os
from datetime import timezone, timedelta

# ---------------------------------------------------------------------------
# AI model selection (override via .env / GitHub Secrets)
# ---------------------------------------------------------------------------

GEMINI_TEXT_MODEL  = os.environ.get("GEMINI_TEXT_MODEL",  "gemini-3-flash-preview")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "imagen-4.0-fast-generate-001")

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
            "#MorningMotivation", "#GoodMorning", "#DailyQuotes", "#Hustle",
            "#SuccessMindset", "#Inspirational", "#NeverGiveUp", "#India",
            "#DailyDoseOfWisdom", "#QuotesOfTheDay", "#GrowthMindset",
            "#MondayMotivation", "#BeMotivated", "#PositiveVibes",
        ],
    },
    "wisdom": {
        "name":      "Life Wisdom",
        "utc_hour":  6,
        "ist_label": "12:00 PM IST",
        "hashtags": [
            "#Wisdom", "#Philosophy", "#LifeQuotes", "#DeepThoughts",
            "#StoicQuotes", "#IndianWisdom", "#DailyDoseOfWisdom",
            "#AncientWisdom", "#LifeLessons", "#ThinkDeep", "#QuoteOfTheDay",
        ],
    },
    "love": {
        "name":      "Love & Relationships",
        "utc_hour":  9,
        "ist_label": "03:00 PM IST",
        "hashtags": [
            "#LoveQuotes", "#Relationships", "#HeartQuotes", "#Friendship",
            "#TrueLove", "#RelationshipGoals", "#DailyDoseOfWisdom",
            "#LoveIndia", "#InspirationalQuotes", "#QuoteOfTheDay",
        ],
    },
    "mindfulness": {
        "name":      "Mindfulness & Inner Peace",
        "utc_hour":  12,
        "ist_label": "06:00 PM IST",
        "hashtags": [
            "#Mindfulness", "#Meditation", "#InnerPeace", "#Yoga",
            "#ZenQuotes", "#Breathe", "#PresentMoment", "#Calm",
            "#DailyDoseOfWisdom", "#Spirituality", "#QuoteOfTheDay",
        ],
    },
    "goodnight": {
        "name":      "Goodnight & Gratitude",
        "utc_hour":  15,
        "ist_label": "09:00 PM IST",
        "hashtags": [
            "#GoodNight", "#NightQuotes", "#Dreams", "#Gratitude",
            "#Hope", "#DreamBig", "#Thankful", "#DailyDoseOfWisdom",
            "#QuoteOfTheDay", "#SleepWell",
        ],
    },
    "latenight": {
        "name":      "Late Night Feels",
        "utc_hour":  19,
        "ist_label": "01:30 AM IST",
        "hashtags": [
            "#LateNightThoughts", "#HeartbreakQuotes", "#3AMThoughts",
            "#FeelingsQuotes", "#EmotionalQuotes", "#Overthinking",
            "#MidnightThoughts", "#DailyDoseOfWisdom", "#RealTalk",
            "#HeartTalk", "#QuoteOfTheNight",
        ],
    },
}

INSTAGRAM_HANDLE = "_daily_dose_of_wisdom__"
WATERMARK_TEXT   = f"@{INSTAGRAM_HANDLE}"
