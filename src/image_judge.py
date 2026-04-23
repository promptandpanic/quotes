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
   DEDUCT -5 for: ANY written character or text-like artifact embedded in the background
   artwork — hashtags (#), at-signs, code fragments, pseudo-code, URLs, numbers, equations,
   letters, words, or decorative glyphs/runes/strokes that read as written characters.
   This is separate from the overlay quote text — only judge what is painted INTO the image.

3. text_readability
   Can you clearly read every word of the quote in the overlay?
   Score 1-3 if text is invisible, tiny, or barely legible.
   Score 4-6 if readable but contrast or size is marginal.
   Score 7-10 only if text is large, clear, high-contrast, AND the text zone is visually
   clean — free from illustration lines, artwork, or busy detail behind the words.
   DEDUCT -4 if background contains watermarks or typography artifacts behind the quote.
   DEDUCT -3 if illustration elements, line art, or busy visual detail overlap the text
   zone and create visual clutter — even if individual words are technically legible.
   The text area must feel clean and unobstructed for a score above 6.

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
"has_text_artifact":<true if ANY written character is embedded in the background artwork: \
hashtags (#), at-signs, code, pseudo-code, URLs, numbers, equations, letters, words, or \
decorative glyphs/runes that read as written characters. IGNORE the overlay quote text — \
only flag characters painted INTO the image itself.>,\
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
    Send composed image to a vision-capable LLM for quality assessment.
    Returns scores on 5 dimensions plus an accept/reject verdict.
    Defaults to accept=True if every provider fails.
    """
    try:
        from src.llm import generate_vision

        text   = quote.get("text", "")[:200].replace('"', "'")
        author = quote.get("author", "Unknown")
        prompt = _JUDGE_PROMPT.format(text=text, author=author)

        raw = generate_vision(prompt, image_bytes, mime_type="image/jpeg", role="image_judge")

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

            issues_lower      = result.get("issues", "").lower()
            has_artifact      = any(kw in issues_lower for kw in _ARTIFACT_KEYWORDS)
            has_signature     = bool(result.get("has_signature", False))
            has_text_artifact = bool(result.get("has_text_artifact", False))

            result["accept"] = (
                weighted >= _MIN_SCORE
                and readability >= _MIN_READABILITY
                and not has_artifact
                and not has_signature
                and not has_text_artifact
            )

            issues = result.get("issues", "")
            logger.info(
                f"  Judge: score={weighted}  "
                f"hook={image_hook}  quality={image_quality}  "
                f"readability={readability}  impact={quote_impact}  "
                f"harmony={harmony}"
                + ("  | ⚠ SIGNATURE DETECTED" if has_signature else "")
                + ("  | ⚠ TEXT ARTIFACT IN IMAGE" if has_text_artifact else "")
                + (f"  | {issues}" if issues else "")
            )
            return result

    except Exception as exc:
        logger.warning(f"Judge failed: {exc} — accepting by default")

    return {"score": 8, "issues": "", "accept": True}
