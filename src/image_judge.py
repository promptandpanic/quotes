"""
Gemini multimodal quality check — looks at the composed image before posting.

Scores: text readability, visual aesthetics, engagement potential.
Hard gate: readability < 5 always rejects regardless of overall score.
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_MIN_SCORE        = 6
_MIN_READABILITY  = 5   # hard floor — invisible/illegible text always rejects

_JUDGE_PROMPT = '''\
You are a quality reviewer for @_daily_dose_of_wisdom__, \
an Indian Instagram quotes page for emotionally intelligent youth aged 18-35.

Judge this composed post image AS IT WILL APPEAR on a mobile phone screen.

Quote displayed: "{text}"

Score 1-10 on each — be honest and strict:

1. readability  — Can you clearly read every word of the quote?
                  Score 1-3 if text is invisible, tiny, or barely legible.
                  Score 4-6 if readable but contrast or size is marginal.
                  Score 7-10 only if text is large, clear, and high-contrast.
                  DEDUCT -4 if background contains watermarks, AI-generated text,
                  labels, or typography bleeding through behind the quote.

2. aesthetics   — Is the visual design beautiful and professional?

3. engagement   — Would an Indian aged 18-35 stop scrolling for this?

Respond ONLY with valid JSON (no markdown):
{{"score":<integer average 1-10>,"readability":<1-10>,"aesthetics":<1-10>,\
"engagement":<1-10>,"issues":"<main issue if score<7, else empty string>",\
"accept":<true if score>=6 AND readability>=5, else false>}}
'''


def judge_image(image_bytes: bytes, quote: dict) -> dict:
    """
    Send composed image to Gemini Vision for quality assessment.
    Returns {score, readability, aesthetics, engagement, issues, accept}.
    Defaults to accept=True if Gemini is unavailable (don't block on API failure).
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"score": 8, "issues": "", "accept": True}

    try:
        from google import genai
        from google.genai import types
        from src.config import GEMINI_TEXT_MODEL

        client = genai.Client(api_key=api_key)
        prompt = _JUDGE_PROMPT.format(text=quote.get("text", "")[:200].replace('"', "'"))

        response = client.models.generate_content(
            model=GEMINI_TEXT_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                types.Part(text=prompt),
            ],
        )
        raw = response.text.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            result       = json.loads(m.group())
            score        = int(result.get("score", 8))
            readability  = int(result.get("readability", 8))
            result["score"]       = score
            result["readability"] = readability
            # Hard gate: reject if text is not clearly readable regardless of overall score
            result["accept"] = score >= _MIN_SCORE and readability >= _MIN_READABILITY
            issues = result.get("issues", "")
            logger.info(
                f"  Judge: score={score}  "
                f"readability={readability}  "
                f"aesthetics={result.get('aesthetics')}  "
                f"engagement={result.get('engagement')}"
                + (f"  | {issues}" if issues else "")
            )
            return result
    except Exception as exc:
        logger.warning(f"Judge failed: {exc} — accepting by default")

    return {"score": 8, "issues": "", "accept": True}
