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
_MIN_SCORE       = 7   # minimum weighted score to accept (mediocre images get retried)

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
   DEDUCT -4 for: clear anatomy / structural impossibility in a single subject — see
   the ANATOMY CHECK below.

ANATOMY / STRUCTURE CHECK (catch AI-fusion errors, but don't overreach):
Before scoring, pause and ask: could the main subject physically exist?
Scan the image deliberately for these specific AI-generation failures:

PEOPLE & ANIMALS — flag if you see:
  - a single person/animal with a wrong NUMBER of body parts: three arms, three
    legs, two heads, six fingers on one hand, two faces on one head
  - limbs that belong to one person but appear attached to another, or two
    bodies visually merged/sharing a limb

VEHICLES — flag if you see:
  - a single vehicle with TWO front ends, TWO cockpits, TWO steering wheels,
    or two driver cabins facing opposite directions
  - duplicate headlights/wheels/doors in impossible positions (e.g. wheels
    visible on both ends where only one end should have them)
  - an auto-rickshaw / tuk-tuk / car / bike whose body looks like two
    vehicles of the same kind fused into one — this is a common AI error
  - more wheels than the vehicle type should have (a regular auto-rickshaw
    has 3 wheels; a car has 4 visible at most from one angle)

OBJECTS — flag if you see:
  - two animals or objects of the same kind fused at the body
  - duplicate critical features on one object (two handles on one mug where
    only one is expected, two spouts on one kettle)

DO NOT flag any of the following — they are valid:
  - surreal / metaphorical compositions (tree growing from a teacup, ink
    turning into a bird, a door floating in water)
  - multiple distinct and SEPARATE subjects in the scene — two separate
    people, two parked cars, a group photo — as long as EACH one is
    structurally coherent on its own
  - stylised or exaggerated proportions that read as a deliberate art style
    (chibi, cubist, impressionist brushwork, long-limbed fashion illustration)
  - partial occlusion, shadows, reflections, silhouettes, motion blur
  - abstract or symbolic imagery

Rule of thumb: if a viewer would instantly say "wait, that's not possible" about
ONE subject's own body, flag it. If the weirdness is intentional-looking art
style or a metaphor, DO NOT flag. When genuinely in doubt, DO NOT flag.

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
"subject_structure":"<one short sentence factually describing the main subject's physical \
structure — no judgement yet. For a person: how many heads/arms/legs are visible. For a \
vehicle: how many front ends, driver cabins, and total wheels are visible. For animals: \
limb count. Example: 'one auto-rickshaw, 3 wheels, one front end, one driver cabin' or \
'one person with 2 arms and 2 legs'.>,\
"has_anatomy_flaw":<based on what you wrote in subject_structure, is the single main \
subject physically possible? true ONLY for a clear physical impossibility in ONE subject \
as described in the ANATOMY CHECK above (extra limbs on one body, a vehicle with two \
front ends, fused bodies, wrong number of wheels for the vehicle type, etc.). False for \
surreal/abstract/metaphorical imagery or multiple distinct separate subjects. When in \
doubt, false.>,\
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
            has_anatomy_flaw  = bool(result.get("has_anatomy_flaw", False))

            # Signature alone is a soft fail when the image is otherwise excellent (score ≥ 8):
            # corner signatures cost ~$0.05 to retry but rarely change between attempts, and
            # an 8-9/10 image is better posted than thrown away. Below 8, still treat as hard.
            signature_only = has_signature and not (has_artifact or has_text_artifact or has_anatomy_flaw)
            soft_signature = signature_only and weighted >= 8

            result["hard_gate_failure"] = (
                has_artifact or has_text_artifact or has_anatomy_flaw
                or (has_signature and not soft_signature)
            )

            result["accept"] = (
                weighted >= _MIN_SCORE
                and readability >= _MIN_READABILITY
                and not result["hard_gate_failure"]
            )

            issues = result.get("issues", "")
            logger.info(
                f"  Judge: score={weighted}  "
                f"hook={image_hook}  quality={image_quality}  "
                f"readability={readability}  impact={quote_impact}  "
                f"harmony={harmony}"
                + ("  | ⚠ SIGNATURE DETECTED" if has_signature else "")
                + ("  | ⚠ TEXT ARTIFACT IN IMAGE" if has_text_artifact else "")
                + ("  | ⚠ ANATOMY FLAW" if has_anatomy_flaw else "")
                + (f"  | {issues}" if issues else "")
            )
            return result

    except Exception as exc:
        logger.warning(f"Judge failed: {exc} — accepting by default")

    return {"score": 8, "issues": "", "accept": True, "hard_gate_failure": False}
