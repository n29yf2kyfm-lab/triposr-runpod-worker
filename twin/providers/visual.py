"""A photoreal impression of the measured building — and the line that
separates it from the measurement.

WHY THIS FILE IS CAREFUL. Everything else in this platform is a claim
about a real house that somebody could be held to: an area, a height, a
regulation verdict, a price. This file makes a PICTURE, and a picture is
the one output a client will believe without reading the caption. So the
rule here is the same rule as the rest of the codebase, applied to the
one output where it is easiest to get lazy about it:

    THE GEOMETRY IS MEASURED. THE APPEARANCE IS INVENTED.

The model is sent the massing render and told, in the prompt, that the
volume is survey data and must not be altered. What it adds — brick,
tiles, windows, doors, a lawn, a sky — is nowhere in the survey. Nobody
has looked at this house. So every image that leaves this module comes
back with a caption burned INTO THE PIXELS, not attached beside them,
because the pixels are what gets screenshotted into a WhatsApp message
to a client. An impression that loses its caption becomes a photograph
of a house that does not exist, and this trade already has enough of
those.

WHAT IT WILL NOT DO. It will not be offered as a survey, it will not be
used to derive a quantity, and it does not feed anything downstream. It
is a selling picture, declared as one.

THE KEY is read from the environment and never reaches a browser.
"""
from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from .. import licences

API = "https://generativelanguage.googleapis.com/v1beta/models"
KEY_ENV = "GEMINI_API_KEY"

# Preference order. The pro model draws better; the flash models are
# cheaper and are the fallback when pro is not enabled on the key. Each
# is tried in turn and the reason for each refusal is kept, so a failure
# tells the user WHICH door was shut rather than "unavailable".
MODELS = (
    "gemini-3-pro-image",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
)

TIMEOUT_S = 300

CAPTION = ("ARTIST'S IMPRESSION — generated, not a photograph. "
           "Geometry is measured; materials, windows and setting are invented.")


class NotAvailable(RuntimeError):
    """Raised with a reason a person can act on, never swallowed."""


@dataclass(frozen=True)
class Impression:
    png: bytes
    model: str
    prompt: str
    classification: str = "estimated"
    licence: str = "google-gemini-api"
    caption: str = CAPTION
    attribution: str = "Image generated with Google Gemini"
    notes: tuple = field(default_factory=tuple)


def key_present() -> bool:
    return bool(os.environ.get(KEY_ENV))


def usable() -> tuple:
    """(ok, reason). Checked before the UI offers the button."""
    if not key_present():
        return (False, f"no {KEY_ENV} in the environment — this is a paid "
                       f"Google API and it needs your own key")
    bad = licences.check("google-gemini-api", licences.USE_RENDER,
                         licences.USE_COMMERCIAL, raises=False)
    if bad:
        return (False, "; ".join(bad))
    return (True, "")


# ---------------------------------------------------------------- prompt

def _era(address: str) -> str:
    """No date is known, so say so rather than inventing a period."""
    return ("Match the prevailing style of the street it stands on: an "
            "ordinary British suburban house, not an architect's showpiece")


def brief(facts: dict) -> str:
    """The prompt. Written so the measured numbers are the constraint and
    the invented material is clearly the free part."""
    w = facts.get("width_m")
    d = facts.get("depth_m")
    st = facts.get("storeys")
    eaves = facts.get("eaves_m")
    ridge = facts.get("ridge_m")
    roof = facts.get("roof_kind") or "pitched"
    place = facts.get("place") or "England"

    dims = []
    if w and d:
        dims.append(f"footprint {w:.2f} m by {d:.2f} m")
    if st:
        dims.append(f"{st} storey{'s' if st != 1 else ''}")
    if eaves:
        dims.append(f"eaves {eaves:.2f} m")
    if ridge:
        dims.append(f"ridge {ridge:.2f} m")

    return (
        "The attached image is a MASSING MODEL of a real house, built "
        "from survey data. Re-render the same building as a "
        "photorealistic architectural visualisation.\n\n"
        "HARD CONSTRAINTS — the geometry is measured. Do not change it:\n"
        f"- {'; '.join(dims) if dims else 'keep every dimension as shown'}.\n"
        f"- The roof is {roof}. Keep the ridge line, the pitch and the "
        "eaves exactly where they are in the image.\n"
        "- Keep the camera position, the angle and the outline identical, "
        "so the result can be laid over the model.\n"
        "- Do NOT add, remove, widen or heighten any volume. No new "
        "wings, dormers, porches, conservatories or extensions.\n\n"
        "MATERIALS AND SETTING — invent these, plausibly:\n"
        f"- {_era(facts.get('address', ''))}, in {place}.\n"
        "- Facing brick or render as suits the street, a tiled pitched "
        "roof, white domestic windows in a sensible rhythm, a front door, "
        "gutters, downpipes and a chimney if the ridge allows one.\n"
        "- Mown lawn, a drive, low boundary planting.\n"
        "- Bright overcast British daylight, soft shadows, eye level.\n"
        "- Photographic. No people, no cars, no signage, no text, no "
        "watermark, no border."
    )


# ------------------------------------------------------------- the call

def _post(model: str, prompt: str, massing_png: bytes, key: str) -> bytes:
    body = {"contents": [{"parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/png",
                         "data": base64.b64encode(massing_png).decode()}},
    ]}]}
    req = urllib.request.Request(
        f"{API}/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        raise NotAvailable(_http_reason(model, e))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NotAvailable(f"{model}: could not reach the Gemini API ({e})")

    for cand in payload.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = (part.get("inlineData") or part.get("inline_data") or {})
            if data.get("data"):
                return base64.b64decode(data["data"])
        fin = cand.get("finishReason")
        if fin and fin not in ("STOP", "MAX_TOKENS"):
            raise NotAvailable(
                f"{model}: the model stopped without an image "
                f"({fin}) — usually its own safety filter on the prompt")
    raise NotAvailable(f"{model}: the reply carried no image")


def _http_reason(model: str, e) -> str:
    """Turn Google's error into something a builder can act on.

    The 429 in particular is NOT a rate limit that will clear on its own
    when it says `limit: 0` — that means the key's project has no image
    quota at all, which is a billing switch, not a wait.
    """
    try:
        detail = json.loads(e.read().decode())["error"]
        msg = detail.get("message", "")
    except Exception:
        msg = ""
    if e.code == 429 and "limit: 0" in msg:
        return (f"{model}: this Google project has NO image quota "
                f"(limit: 0). Image generation is a paid feature — enable "
                f"billing on the project behind the key at "
                f"https://aistudio.google.com/apikey, then it works with "
                f"no code change.")
    if e.code == 429:
        return f"{model}: over the rate limit, try again shortly"
    if e.code in (401, 403):
        return (f"{model}: the key was refused ({e.code}) — check it is a "
                f"Gemini API key and that the Generative Language API is "
                f"enabled on its project")
    if e.code == 404:
        return f"{model}: this model is not available to the key"
    return f"{model}: HTTP {e.code} {msg[:200]}"


# ------------------------------------------------------------- caption

def stamp(png: bytes, text: str = CAPTION) -> bytes:
    """Burn the caption into the pixels.

    A caption in the HTML is lost the moment somebody screenshots the
    panel or right-click-saves the image, which is precisely what will
    happen to a picture this good-looking. In the pixels it survives.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return png                      # better a picture than nothing
    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    pad = 10

    def load(size):
        for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return None

    probe = ImageDraw.Draw(im)

    def width_at(font):
        try:
            box = probe.textbbox((0, 0), text, font=font)
            return box[2] - box[0]
        except Exception:
            return len(text) * 6

    # SHRINK, THEN WRAP. A caption that runs off the right-hand edge is
    # worse than no caption: the sentence that survives the crop reads
    # "ARTIST'S IMPRESSION — generated, not a photo…", and half a
    # disclaimer on a picture is the exact thing being guarded against.
    # So the size comes down to a floor, and whatever still does not fit
    # on one line goes onto the next — the words are never lost.
    avail = max(40, w - 2 * pad)
    size = max(11, min(20, h // 26))
    font = load(size)
    while font is not None and size > 9 and width_at(font) > avail:
        size -= 1
        font = load(size)
    if font is None:
        font = ImageFont.load_default()
        size = 11

    def fits(s):
        try:
            box = probe.textbbox((0, 0), s, font=font)
            return (box[2] - box[0]) <= avail
        except Exception:
            return len(s) * 6 <= avail

    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if fits(trial) or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)

    step = size + 3
    band = len(lines) * step + 9
    out = Image.new("RGB", (w, h + band), (14, 14, 16))
    out.paste(im, (0, 0))
    dr = ImageDraw.Draw(out)
    y = h + 4
    for line in lines:
        dr.text((pad, y), line, fill=(236, 200, 90), font=font)
        y += step
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- entry

def impression(massing_png: bytes, facts: dict) -> Impression:
    """Massing render in, captioned photoreal impression out.

    Raises NotAvailable with a reason. It never returns a placeholder
    image: a picture that quietly is not what it claims is the one
    failure mode this module exists to prevent.
    """
    ok, why = usable()
    if not ok:
        raise NotAvailable(why)
    if not massing_png:
        raise NotAvailable("no massing render was supplied to work from")
    key = os.environ[KEY_ENV]
    text = brief(facts)
    refusals = []
    for model in MODELS:
        try:
            raw = _post(model, text, massing_png, key)
        except NotAvailable as e:
            refusals.append(str(e))
            continue
        return Impression(png=stamp(raw), model=model, prompt=text,
                          notes=tuple(refusals))
    raise NotAvailable(" | ".join(refusals))
