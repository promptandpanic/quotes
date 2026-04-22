"""
Gemini multimodal quality check — looks at the composed image before posting.

Scoring philosophy:
  - Image is the scroll-stopping HOOK — judged independently on visual merit
  - Quote is the WISDOM — judged independently on emotional impact
  - Harmony (image mood matching quote) is a bonus, not a requirement
  - Text readability is a hard gate — invisible text always rejects

Dimensions (see _JUDGE_PROMPT for details):
  image_hook       25%  — scroll-stopping visual power, independent of quote
  image_quality    20%  — aesthetics, composition, art style execution
  text_readability 20%  — clarity and legibility of the quote text overlay (hard gate ≥5)
  quote_impact     25%  — emotional punch, relatability, not clichéd
  image_text_harmony 10% — bonus: does image mood enhance the quote? never penalised if low
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_MIN_READABILITY = 5   # hard gate — illegible text always rejects
_MIN_SCORE       = 6   # minimum weighted score to accept

_JUDGE_PROMPT = '''\
You are a quality reviewer for @_daily_dose_of_wisdom__, \
an Indian Instagram quotes page for emotionally intelligent youth aged 18-35.

Judge this composed post AS IT WILL APPEAR on a mobile phone screen.

Quote displayed: "{text}"
Author: {author}

IMPORTANT PHILOSOPHY:
The image is the scroll-stopping HOOK — it does not need to literally illustrate the quote.
A beautiful or striking image that has nothing to do with the quote is fine.
The quote stands on its own as emotional wisdom.
BONUS points if image mood enhances the quote — but NEVER penalise mismatches.

Score each dimension 1-10 (be honest and strict):

1. image_hook
   Does this image stop someone from scrolling before they even read the text?
   Score high for: visually striking, unusual, beautiful, distinctive art style.
   Score low for: generic, boring, cluttered, or obviously AI-bland.

2. image_quality
   Is the image aesthetically beautiful and well-composed?
   Art style executed cleanly? No muddy AI artifacts, no unintended text/logos in image?
   DEDUCT heavily for: watermarks, AI-generated text bleeding through, technical artifacts.
   DEDUCT -4 for: any visible artist signature, handwritten name, copyright mark, or studio
   watermark painted into the artwork itself (bottom corner signatures, © symbols, etc.).

3. text_readability
   Can you clearly read every word of the quote in the overlay?
   Score 1-3 if text is invisible, tiny, or barely legible.
   Score 4-6 if readable but contrast or size is marginal.
   Score 7-10 only if text is large, clear, and high-contrast.
   DEDUCT -4 if background contains watermarks or typography artifacts behind the quote.

4. quote_impact
   Is the quote emotionally powerful, relatable, and save-worthy?
   Would an Indian aged 18-35 feel something reading this?
   Score low for: generic clichés, overused internet quotes, hollow motivational filler.
   Score high for: specific, emotionally precise, something someone would screenshot.

5. image_text_harmony
   Does the image mood or energy enhance the quote's emotional feel?
   This is a BONUS dimension — a 5/10 here is perfectly fine.
   Score 8-10 only if the image and quote feel like they were made for each other.
   Never score below 4 just because they don't match — mismatches are acceptable.

Respond ONLY with valid JSON (no markdown, no extra text):
{{"image_hook":<1-10>,"image_quality":<1-10>,"text_readability":<1-10>,\
"quote_impact":<1-10>,"image_text_harmony":<1-10>,\
"has_signature":<true if any artist signature/watermark/copyright mark is visible in the artwork>,\
"issues":"<main issue if any, empty string if none>",\
"accept":<true or false>}}
'''

_ARTIFACT_KEYWORDS = (
    "watermark", "artifact", "text artifact", "label", "template",
    "placeholder", "code", "typography bleeding", "gibberish", "symbol",
    "technical text", "ai-generated text", "generated text",
    "signature", "signed", "copyright", "©",
)


def judge_image(image_bytes: bytes, quote: dict) -> dict:
    """
    Send composed image to Gemini Vision for quality assessment.
    Returns scores on 5 dimensions plus an accept/reject verdict.
    Defaults to accept=True if Gemini is unavailable.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"score": 8, "issues": "", "accept": True}

    try:
        from google import genai
        from google.genai import types
        from src.config import GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK

        client = genai.Client(api_key=api_key)
        text   = quote.get("text", "")[:200].replace('"', "'")
        author = quote.get("author", "Unknown")
        prompt = _JUDGE_PROMPT.format(text=text, author=author)
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            types.Part(text=prompt),
        ]
        cfg = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        raw = None
        for model in [GEMINI_TEXT_MODEL, GEMINI_TEXT_MODEL_FALLBACK]:
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=cfg,
                )
                raw = response.text.strip()
                break
            except Exception as exc:
                if model == GEMINI_TEXT_MODEL_FALLBACK:
                    raise
                logger.warning(f"Judge primary model failed: {exc} — retrying with {GEMINI_TEXT_MODEL_FALLBACK}")

        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            result = json.loads(m.group())

            image_hook    = int(result.get("image_hook", 7))
            image_quality = int(result.get("image_quality", 7))
            readability   = int(result.get("text_readability", 7))
            quote_impact  = int(result.get("quote_impact", 7))
            harmony       = int(result.get("image_text_harmony", 6))

            # Weighted score: image (45%) + readability (20%) + quote (25%) + harmony bonus (10%)
            weighted = round(
                0.25 * image_hook
                + 0.20 * image_quality
                + 0.20 * readability
                + 0.25 * quote_impact
                + 0.10 * harmony
            )

            result["score"]            = weighted
            result["image_hook"]       = image_hook
            result["image_quality"]    = image_quality
            result["text_readability"] = readability
            result["quote_impact"]     = quote_impact
            result["image_text_harmony"] = harmony

            issues_lower  = result.get("issues", "").lower()
            has_artifact  = any(kw in issues_lower for kw in _ARTIFACT_KEYWORDS)
            has_signature = bool(result.get("has_signature", False))

            result["accept"] = (
                weighted >= _MIN_SCORE
                and readability >= _MIN_READABILITY
                and not has_artifact
                and not has_signature
            )

            issues = result.get("issues", "")
            logger.info(
                f"  Judge: score={weighted}  "
                f"hook={image_hook}  quality={image_quality}  "
                f"readability={readability}  impact={quote_impact}  "
                f"harmony={harmony}"
                + ("  | ⚠ SIGNATURE DETECTED" if has_signature else "")
                + (f"  | {issues}" if issues else "")
            )
            return result

    except Exception as exc:
        logger.warning(f"Judge failed: {exc} — accepting by default")

    return {"score": 8, "issues": "", "accept": True}
