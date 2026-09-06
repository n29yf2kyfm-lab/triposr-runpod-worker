"""A photoreal impression of the measured building — and the line that
separates it from the measurement.

WHY THIS FILE IS CAREFUL. Everything else in this platform is a claim
about a real house that somebody could be held to: an area, a height, a
regulation verdict, a price. This file makes a PICTURE, and a picture is
the one output a client will believe without reading the caption. So the
rule here is the same rule as the rest of the codebase, applied to the
one output where it is easiest to get lazy about it:

    THE GEOMETRY IS MEASURED. THE APPEARANCE IS INVENTED.

Three things hold that line:

1. THE DEPTH MAP. The app renders depth straight from the measured
   model, and the preferred backend is a depth-conditioned diffusion
   model (SDXL + ControlNet-depth, in visual_worker/) that cannot move a
   wall because the wall's position is an input, not a suggestion. The
   free-form backend (Gemini) is a fallback: it is ASKED to keep the
   geometry, and given the depth map too, but nothing makes it.

2. THE FIDELITY CHECK. Whatever produced the picture, it is scored
   against the massing's own edges (fidelity.py) and REFUSED if the
   roof line, eaves or corners moved. A drifted picture is not a worse
   picture; it is a falsified survey with good lighting.

3. THE CAPTION IN THE PIXELS. Every image leaves with the disclaimer
   burned into it, sized and wrapped to fit, because a caption beside
   the image is gone the moment somebody screenshots the panel into a
   WhatsApp message to a client.

Nothing downstream reads the picture. No quantity is derived from it.

KEYS are read from the environment and never reach a browser. The
RunPod endpoint id is checked by name against the vehicle project's
endpoints and refused if it matches: that project must not be touched.
"""
from __future__ import annotations

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from .. import licences

API = "https://generativelanguage.googleapis.com/v1beta/models"
KEY_ENV = "GEMINI_API_KEY"
RUNPOD_KEY_ENV = "RUNPOD_API_KEY"
RUNPOD_ENDPOINT_ENV = "RUNPOD_DEPTH_ENDPOINT_ID"

# The vehicle project's endpoints. This app must never call them.
VEHICLE_ENDPOINTS = frozenset({"nd0fagqlr5z2ur", "ng8oiz4p2l0xa0"})

# Gemini preference order. Each is tried in turn and the reason for
# each refusal is kept, so a failure says WHICH door was shut.
MODELS = (
    "gemini-3-pro-image",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
)

# One call may take this long; the whole chain may take BUDGET_S. Three
# models at 300 s each was a fifteen-minute ceiling behind a button that
# says "up to a minute or two" — a hung socket must not hold a builder's
# browser for a quarter of an hour.
TIMEOUT_S = 90
BUDGET_S = 150

CAPTION = ("ARTIST'S IMPRESSION — generated, not a photograph. "
           "Geometry is measured; materials, windows and setting are invented.")


class NotAvailable(RuntimeError):
    """Raised with a reason a person can act on, never swallowed."""


@dataclass(frozen=True)
class Impression:
    png: bytes
    model: str
    prompt: str
    backend: str = "gemini"
    classification: str = "estimated"
    licence: str = "google-gemini-api"
    caption: str = CAPTION
    attribution: str = "Image generated with Google Gemini"
    fidelity: Optional[dict] = None
    notes: tuple = field(default_factory=tuple)


# ------------------------------------------------------------ availability

def key_present() -> bool:
    return bool(os.environ.get(KEY_ENV))


def depth_backend_configured() -> tuple:
    """(ok, reason) for the depth-conditioned RunPod worker."""
    ep = (os.environ.get(RUNPOD_ENDPOINT_ENV) or "").strip()
    if not ep:
        return (False, f"no {RUNPOD_ENDPOINT_ENV} — the depth-conditioned "
                       f"worker in visual_worker/ is not deployed yet")
    if ep in VEHICLE_ENDPOINTS:
        return (False, f"{RUNPOD_ENDPOINT_ENV} points at the vehicle "
                       f"project's endpoint {ep!r} — refusing; deploy "
                       f"visual_worker/ on its own endpoint")
    if not os.environ.get(RUNPOD_KEY_ENV):
        return (False, f"no {RUNPOD_KEY_ENV} in the environment")
    return (True, "")


def usable() -> tuple:
    """(ok, reason). Checked before the UI offers the button."""
    d_ok, d_why = depth_backend_configured()
    if d_ok:
        return (True, "")
    if not key_present():
        return (False, f"no {KEY_ENV} in the environment — this is a paid "
                       f"Google API and it needs your own key "
                       f"(and {d_why})")
    bad = licences.check("google-gemini-api", licences.USE_RENDER,
                         licences.USE_COMMERCIAL, raises=False)
    if bad:
        return (False, "; ".join(bad))
    return (True, "")


# ---------------------------------------------------------------- prompt

# No build date is known, so the prompt says so rather than inventing a
# period.
ERA = ("Match the prevailing style of the street it stands on: an "
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
        f"- {ERA}, in {place}.\n"
        "- Facing brick or render as suits the street, a tiled pitched "
        "roof, white domestic windows in a sensible rhythm, a front door, "
        "gutters, downpipes and a chimney if the ridge allows one.\n"
        "- Mown lawn, a drive, low boundary planting.\n"
        "- Bright overcast British daylight, soft shadows, eye level.\n"
        "- Photographic. No people, no cars, no signage, no text, no "
        "watermark, no border."
    )


def short_brief(facts: dict) -> str:
    """For the diffusion backend, which wants a description, not an
    instruction — the geometry arrives as the depth map."""
    st = facts.get("storeys")
    place = facts.get("place") or "England"
    return (f"photograph of a {st or ''} storey detached house in {place}, "
            f"red-brown facing brick, plain tiled {facts.get('roof_kind') or 'pitched'} "
            f"roof, white upvc windows, front door, gutters and downpipes, "
            f"mown lawn and a block-paved drive, bright overcast daylight, "
            f"soft shadows, eye level, architectural photography, sharp, "
            f"realistic").replace("  ", " ")


# ------------------------------------------------------------- gemini

def _post(model: str, prompt: str, massing_png: bytes, key: str,
          timeout: float = TIMEOUT_S, depth_png: bytes | None = None) -> bytes:
    parts = [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/png",
                         "data": base64.b64encode(massing_png).decode()}},
    ]
    if depth_png:
        parts.append({"text": "The second image is the DEPTH MAP of the "
                              "same view from the same camera — white is "
                              "near, black is far. Every surface in your "
                              "picture must sit exactly where this depth "
                              "map puts it."})
        parts.append({"inline_data": {"mime_type": "image/png",
                                      "data": base64.b64encode(depth_png).decode()}})
    body = {"contents": [{"parts": parts}]}
    req = urllib.request.Request(
        f"{API}/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        raise NotAvailable(_http_reason(model, e))
    # "failed to reach" is the phrase api._out keys the 502 on, so a dead
    # upstream is reported as one rather than as an empty answer.
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NotAvailable(f"{model}: lookup failed to reach the Gemini "
                           f"API ({e})")
    except ValueError as e:
        # A non-JSON body (a proxy's HTML error page, say) is the
        # upstream's fault, not a bad request from our own client.
        raise NotAvailable(f"{model}: the reply was not JSON ({e})")

    for cand in payload.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = (part.get("inlineData") or part.get("inline_data") or {})
            if data.get("data"):
                try:
                    return base64.b64decode(data["data"])
                except ValueError as e:
                    raise NotAvailable(
                        f"{model}: the image in the reply was not "
                        f"valid base64 ({e})")
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


# ------------------------------------------------------------- runpod

def _runpod_depth(prompt: str, massing_png: bytes, depth_png: bytes,
                  timeout: float = TIMEOUT_S) -> tuple:
    """The depth-conditioned worker. Returns (png, model_name)."""
    ok, why = depth_backend_configured()
    if not ok:
        raise NotAvailable(f"depth backend: {why}")
    if not depth_png:
        raise NotAvailable("depth backend: no depth map was supplied — the "
                           "3D view must send its depth pass")
    ep = os.environ[RUNPOD_ENDPOINT_ENV].strip()
    if ep in VEHICLE_ENDPOINTS:          # belt and braces
        raise NotAvailable("depth backend: refusing the vehicle endpoint")
    body = {"input": {
        "prompt": prompt,
        "depth_png_b64": base64.b64encode(depth_png).decode(),
        "image_png_b64": base64.b64encode(massing_png).decode(),
        "control_strength": 0.9,
    }}
    req = urllib.request.Request(
        f"https://api.runpod.ai/v2/{ep}/runsync",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ[RUNPOD_KEY_ENV]}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        raise NotAvailable(f"depth backend: RunPod answered HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NotAvailable(f"depth backend: lookup failed to reach RunPod "
                           f"({e})")
    except ValueError as e:
        raise NotAvailable(f"depth backend: the reply was not JSON ({e})")
    out = payload.get("output") or {}
    if payload.get("status") not in (None, "COMPLETED") or "error" in out:
        raise NotAvailable(f"depth backend: {out.get('error') or payload.get('status')}")
    b64 = out.get("image_png_b64")
    if not b64:
        raise NotAvailable("depth backend: the worker returned no image")
    try:
        return base64.b64decode(b64), f"{out.get('model', 'sdxl')} + {out.get('controlnet', 'controlnet-depth')}"
    except ValueError as e:
        raise NotAvailable(f"depth backend: image was not valid base64 ({e})")


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
        # NOT "better a picture than nothing": an uncaptioned picture is
        # the one output this module exists to prevent.
        raise NotAvailable("Pillow is not installed, so the disclaimer "
                           "cannot be burned into the image — refusing to "
                           "return an uncaptioned impression")
    try:
        im = Image.open(io.BytesIO(png)).convert("RGB")
    except Exception as e:
        raise NotAvailable(f"the reply was not a readable image ({e})")
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

def _check_fidelity(massing_png, raw, mask_png):
    """Score the picture against the geometry it was given. Returns the
    report; raises if the picture drifted. No mask, no scoring — and
    that is recorded rather than silently skipped."""
    try:
        from .. import fidelity
    except ImportError as e:
        return {"passed": None, "reason": f"fidelity check unavailable: {e}"}
    rep = fidelity.edge_recall(massing_png, raw, mask_png)
    if not rep["passed"]:
        raise NotAvailable(rep["reason"])
    return rep


def impression(massing_png: bytes, facts: dict,
               depth_png: bytes | None = None,
               mask_png: bytes | None = None) -> Impression:
    """Massing render in, captioned photoreal impression out.

    Tries the depth-conditioned backend first when it is configured,
    then the Gemini models in order. Every candidate is checked for
    fidelity against the massing before it is accepted. Raises
    NotAvailable with every reason collected. It never returns a
    placeholder image: a picture that quietly is not what it claims is
    the one failure mode this module exists to prevent.
    """
    ok, why = usable()
    if not ok:
        raise NotAvailable(why)
    if not massing_png:
        raise NotAvailable("no massing render was supplied to work from")
    text = brief(facts)
    refusals = []
    deadline = time.monotonic() + BUDGET_S

    def accept(raw, model, backend):
        fid = _check_fidelity(massing_png, raw, mask_png)
        return Impression(png=stamp(raw), model=model, prompt=text,
                          backend=backend, fidelity=fid,
                          licence=("runpod-own-worker" if backend == "depth"
                                   else "google-gemini-api"),
                          attribution=("Image generated with SDXL + "
                                       "ControlNet-depth on our own worker"
                                       if backend == "depth" else
                                       "Image generated with Google Gemini"),
                          notes=tuple(refusals))

    # 1. The geometry-locked path.
    if depth_backend_configured()[0]:
        try:
            raw, name = _runpod_depth(short_brief(facts), massing_png,
                                      depth_png, timeout=TIMEOUT_S)
            return accept(raw, name, "depth")
        except NotAvailable as e:
            refusals.append(str(e))

    # 2. The free-form path, asked nicely and checked afterwards.
    if not key_present():
        raise NotAvailable(" | ".join(refusals) if refusals else why)
    key = os.environ[KEY_ENV]
    for model in MODELS:
        left = deadline - time.monotonic()
        if left < 5:
            refusals.append(f"{model}: not tried, the {BUDGET_S} s budget "
                            f"was spent on the models before it")
            continue
        try:
            raw = _post(model, text, massing_png, key,
                        timeout=min(TIMEOUT_S, left), depth_png=depth_png)
            return accept(raw, model, "gemini")
        except NotAvailable as e:
            refusals.append(str(e))
            continue
    raise NotAvailable(" | ".join(refusals))
