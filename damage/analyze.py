"""The analysis engine: photos + vehicle spec -> structured findings.

This is the part every competitor calls "the AI". What separates a premium
result from a toy one is not the model — they can all call a VLM — it is the
STRUCTURE the model is forced to produce and how ruthlessly that structure is
validated afterwards. FairMoto is the bar: for each finding it gives the
panel, a severity, the specific EVIDENCE it saw, the HIDDEN damage it infers
with a probability, and MODEL-SPECIFIC risks ("autopilot camera
recalibration required" on a Tesla windshield). That is what this prompt
demands and what the parser guarantees.

Two design commitments:

  * A GUESS IS NEVER PRESENTED AS AN OBSERVATION. Visible damage carries
    evidence; inferred sub-surface damage carries a probability and a
    rationale and lives in a separate `hidden_damage` list. The report renders
    them differently. (The building product holds the same line about measured
    vs inferred services; same principle, different domain.)

  * THE BACKEND IS SWAPPABLE AND ABSENT-SAFE. `analyze()` takes an injected
    `vision_fn` so the deterministic pipeline and its tests run with no model
    at all. The default backend targets a Qwen2.5-VL served locally (Apache
    2.0, the VLM the repo already standardises on in MARKET.md), selected by
    env — but the handler also accepts pre-computed `findings`, so the whole
    scoring/pricing/fusion/report chain is exercisable without a GPU.
"""
import json
import re

from taxonomy import (canonical_panel, canonical_damage, clamp_severity,
                      PANELS, DAMAGE_TYPES)

# The instruction. Kept explicit and example-shaped because VLMs comply with a
# shown schema far more reliably than with a described one. {panels} and
# {damage_types} are injected so the model uses OUR ids and the parser rarely
# has to fall back to fuzzy mapping.
SYSTEM_PROMPT = """\
You are a senior vehicle damage appraiser. You are given photographs of ONE \
vehicle{vehicle_line}, taken by its owner for an insurance / resale / rental \
condition inspection. Report only what the images support.

Return STRICT JSON, no prose and no markdown fences, matching exactly:

{{
  "vehicle_observed": {{"body_style": "", "colour": "", "notes": ""}},
  "images": [
    {{"index": 0, "panels_visible": ["front_bumper"], "tags": ["good_lighting"]}}
  ],
  "findings": [
    {{
      "panel": "<one of the panel ids below>",
      "damage_type": "<one of the damage ids below>",
      "severity": <integer 1-10>,
      "confidence": <0.0-1.0>,
      "image_index": <int>,
      "bbox": [x, y, w, h],           // normalised 0-1 in that image, or null
      "evidence": ["what you actually see, each a short phrase"],
      "hidden_damage": [
        {{"system": "e.g. ADAS camera", "probability": 0.6,
          "rationale": "why this is likely given the visible damage",
          "est_cost_high": <number or null>}}
      ],
      "model_specific_risks": ["e.g. autopilot camera recalibration required"],
      "repair_note": "one short line on the likely repair"
    }}
  ],
  "summary": "one or two sentences a human would read first"
}}

Rules:
- severity is 1-10: 1-2 cosmetic, 3-4 minor, 5-6 moderate, 7-8 major, \
9-10 structural/safety/write-off risk.
- EVERY finding needs at least one concrete `evidence` phrase describing what \
is visible. No evidence, no finding.
- `hidden_damage` is for consequences you INFER, not see: a sensor behind a \
cracked bumper, a bent rail behind a shoved wheel. Give each a probability and \
a rationale. If you see nothing to infer, use an empty list.
- `model_specific_risks` uses knowledge of THIS make/model: ADAS/radar behind \
grilles and windshields, aluminium panels that cannot be PDR'd, EV battery \
proximity, run-flat tyres. Empty list if none apply.
- Use ONLY these panel ids: {panels}
- Use ONLY these damage_type ids: {damage_types}
- Prefer the most specific panel. If genuinely unsure of the panel, use \
"body_other". Never omit a real finding for lack of a perfect label.
- Tag each image with any of: good_lighting, low_light, indoor_lighting, \
reflection, water_droplets, dirt, shadow, blurry, too_far, harsh_sunlight.
"""


def build_prompt(vehicle=None):
    """Render the system prompt for a specific (or unknown) vehicle."""
    vehicle_line = ""
    if vehicle:
        ident = " ".join(str(vehicle[k]) for k in ("year", "make", "model",
                                                    "trim") if vehicle.get(k))
        if ident.strip():
            vehicle_line = f" — a {ident.strip()}"
    return SYSTEM_PROMPT.format(
        vehicle_line=vehicle_line,
        panels=", ".join(PANELS.keys()),
        damage_types=", ".join(DAMAGE_TYPES.keys()),
    )


def _extract_json(text):
    """Pull the JSON object out of a model response.

    Handles the three things VLMs do: clean JSON, ```json fenced JSON, and
    JSON with a sentence before or after it. Returns a dict or raises
    ValueError with the raw head so a bad response is diagnosable.
    """
    if isinstance(text, (dict, list)):
        return text
    s = str(text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    # find the outermost {...}
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object in model response: {s[:200]!r}")
    blob = s[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as e:
        raise ValueError(f"model response was not valid JSON ({e}): "
                         f"{blob[:200]!r}")


def _resolve_side(panel_str, market):
    """Turn driver/passenger into left/right using the vehicle's market.

    LHD markets (US, EU, most of the world): driver = left, passenger = right.
    RHD markets (uk, au, jp, in, za, ie): driver = right, passenger = left.
    Done before canonicalising so a "driver door" pins on the correct side.
    """
    if not panel_str:
        return panel_str
    s = str(panel_str).lower()
    if "driver" not in s and "passenger" not in s:
        return panel_str
    rhd = str(market or "").lower() in (
        "uk", "gb", "au", "nz", "jp", "japan", "in", "india", "za", "ie",
        "ireland", "th", "thailand", "sg", "hk")
    driver_side = "right" if rhd else "left"
    passenger_side = "left" if rhd else "right"
    return s.replace("driver", driver_side).replace("passenger", passenger_side)


def normalize_findings(raw, vehicle=None, market=None):
    """Validate + normalise the model's findings into the canonical shape.

    Every finding is coerced onto a taxonomy panel and damage id, severity
    clamped 1-10, evidence guaranteed non-empty-or-dropped, probabilities
    clamped. A finding with no evidence is discarded (the prompt forbids it,
    but the parser enforces it — the whole "never guess as observation" line
    depends on this being mechanical, not trusted).
    """
    market = market or (vehicle or {}).get("market") or (vehicle or {}).get("region")
    out = []
    for f in raw or []:
        if not isinstance(f, dict):
            continue
        evidence = [str(e).strip() for e in (f.get("evidence") or [])
                    if str(e).strip()]
        if not evidence:
            # no observation -> not a reportable finding
            continue
        panel_in = _resolve_side(f.get("panel"), market)
        panel = canonical_panel(panel_in) or "body_other"
        dtype = canonical_damage(f.get("damage_type"))
        sev = clamp_severity(f.get("severity", 5))
        conf = _clamp01(f.get("confidence"), 0.7)

        hidden = []
        for hd in f.get("hidden_damage") or []:
            if not isinstance(hd, dict):
                continue
            system = str(hd.get("system") or "").strip()
            if not system:
                continue
            hidden.append({
                "system": system,
                "probability": _clamp01(hd.get("probability"), 0.3),
                "rationale": str(hd.get("rationale") or "").strip(),
                "est_cost_high": _num_or_none(hd.get("est_cost_high")),
            })

        out.append({
            "panel": panel,
            "region": PANELS.get(panel, (None, "other"))[1],
            "damage_type": dtype,
            "damage_label": DAMAGE_TYPES.get(dtype, ("Other",))[0],
            "severity": sev,
            "confidence": conf,
            "image_index": _int_or_none(f.get("image_index")),
            "bbox": _bbox_or_none(f.get("bbox")),
            "evidence": evidence,
            "hidden_damage": hidden,
            "model_specific_risks": [str(r).strip() for r in
                                     (f.get("model_specific_risks") or [])
                                     if str(r).strip()],
            "repair_note": str(f.get("repair_note") or "").strip(),
        })
    return out


def normalize_images(raw):
    """Normalise the per-image blocks (panels_visible + tags)."""
    out = []
    for i, im in enumerate(raw or []):
        if not isinstance(im, dict):
            continue
        out.append({
            "index": im.get("index", i),
            "panels": [canonical_panel(p) or p for p in
                       (im.get("panels_visible") or im.get("panels") or [])],
            "tags": [str(t).strip() for t in (im.get("tags") or [])
                     if str(t).strip()],
        })
    return out


def analyze(image_urls, vehicle=None, vision_fn=None, market=None):
    """Run the analysis. Returns (findings, images, meta).

    `vision_fn(prompt, image_urls) -> str|dict` is the injected backend. When
    None, the default backend is resolved from env (see get_backend); tests
    always inject a fake so no model is loaded.
    """
    if vision_fn is None:
        vision_fn = get_backend()
    prompt = build_prompt(vehicle)
    raw = vision_fn(prompt, image_urls)
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        raise ValueError("model response JSON was not an object")
    market = market or (vehicle or {}).get("market") or (vehicle or {}).get("region")
    findings = normalize_findings(parsed.get("findings"), vehicle, market)
    images = normalize_images(parsed.get("images"))
    meta = {
        "summary": str(parsed.get("summary") or "").strip(),
        "vehicle_observed": parsed.get("vehicle_observed") or {},
    }
    return findings, images, meta


# --- backend resolution ---------------------------------------------------

def get_backend():
    """Resolve the vision backend from the environment.

    DAMAGE_BACKEND=anthropic (MOST ACCURATE) -> a frontier Claude vision model
      via the Anthropic API. Needs ANTHROPIC_API_KEY; no GPU. On a live test the
      small local model scored a car with a shattered windshield 99/100 ("minor
      bumper scratch") — it pattern-matched "car inspection" instead of reading
      the image. A frontier model reads the same photo correctly (windshield /
      shattered_glass / severe) and does not hallucinate damage on clean panels.
      Costs per scan. Model via DAMAGE_VLM_MODEL (default claude-opus-5).
    DAMAGE_BACKEND=openrouter (FREE, no GPU) -> a free hosted open vision model
      (default Gemma 4 31B). $0 per scan and no GPU, in exchange for a rate cap
      (20/min; 50/day, or 1,000/day after a one-time $10 credit purchase). At
      ~31B it is far more capable than the 7B local fallback below — that
      failure was a model-SIZE problem, not a self-hosting one. Needs
      OPENROUTER_API_KEY.
    DAMAGE_BACKEND=qwen (default) -> a local Qwen2.5-VL via transformers. Fast
      and self-hosted, but UNRELIABLE at the actual assessment (see above) —
      treat it as a cheap fallback, not the product's judgement.

    Kept as a lazy factory so importing this module never pulls torch or the
    Anthropic SDK, and so swapping the served model is one env var, not a code
    change. The findings-only job path bypasses this entirely.
    """
    import os
    backend = os.environ.get("DAMAGE_BACKEND", "qwen").lower()
    if backend in ("anthropic", "claude"):
        return _anthropic_backend()
    if backend in ("openrouter", "free", "gemma"):
        return _openrouter_backend()
    if backend in ("qwen", "qwen2.5-vl", "qwenvl"):
        return _qwen_backend()
    raise RuntimeError(
        f"unknown DAMAGE_BACKEND={backend!r}. Set DAMAGE_BACKEND=anthropic "
        f"(most accurate; needs ANTHROPIC_API_KEY), =openrouter (free, no GPU; "
        f"needs OPENROUTER_API_KEY), or =qwen, or pass image analysis "
        f"pre-computed as `findings` in the job input to skip the vision stage "
        f"entirely.")


def _anthropic_backend():
    """Vision_fn backed by a frontier Claude vision model (Anthropic API).

    No GPU, no model download — this is why choosing it also removes the whole
    cold-start / warm-worker problem the local path carries: the worker becomes
    an API proxy that can scale to zero cheaply. Requires ANTHROPIC_API_KEY in
    the endpoint env. The client is built once and cached on first call."""
    state = {}

    def vision_fn(prompt, image_urls):
        import os
        from anthropic import Anthropic
        model = os.environ.get("DAMAGE_VLM_MODEL", "claude-opus-5")
        if "client" not in state:
            state["client"] = Anthropic()   # reads ANTHROPIC_API_KEY from env
        content = list(_anthropic_image_blocks(image_urls))
        content.append({"type": "text",
                        "text": "Analyse the vehicle in these photos and "
                                "return ONLY the JSON described above."})
        msg = state["client"].messages.create(
            model=model,
            max_tokens=8192,
            system=prompt,
            messages=[{"role": "user", "content": content}],
        )
        if getattr(msg, "stop_reason", None) == "refusal":
            raise RuntimeError("vision model declined this request "
                               "(stop_reason=refusal)")
        return "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")

    return vision_fn


def _anthropic_image_blocks(image_urls):
    """Image content blocks for the Messages API: URLs pass through as url
    sources; local files (base64 job inputs) are inlined as base64."""
    import base64
    import mimetypes
    blocks = []
    for u in image_urls:
        s = str(u)
        if s.startswith(("http://", "https://")):
            blocks.append({"type": "image",
                           "source": {"type": "url", "url": s}})
        else:
            media_type = mimetypes.guess_type(s)[0] or "image/jpeg"
            with open(s, "rb") as f:
                data = base64.standard_b64encode(f.read()).decode("ascii")
            blocks.append({"type": "image",
                           "source": {"type": "base64",
                                      "media_type": media_type, "data": data}})
    return blocks


def _openrouter_backend():
    """Vision_fn backed by a FREE hosted open model via OpenRouter.

    This is the zero-marginal-cost path: no GPU, no model download, and no
    per-scan fee. OpenRouter serves several open vision models at $0 (default
    here: Gemma 4 31B — see DAMAGE_VLM_MODEL). At ~31B it is roughly four times
    the size of the local Qwen-7B that scored a shattered-windshield car 99/100,
    which is the whole reason that fallback is not trusted: the failure there
    was model SIZE, not self-hosting.

    Cost is $0/scan, but the free tier is RATE LIMITED, and those limits are the
    real design constraint (verified Aug 2026):
        * 20 requests/minute, always.
        * 50 requests/day on an account that has never bought credits.
        * 1,000 requests/day once the account has purchased $10 of credits at
          any point — a lifetime unlock, not a running balance.
    A 429 is therefore an expected operating condition, not a bug, so it is
    surfaced with that context instead of a bare HTTP error.

    Speaks the OpenAI chat-completions shape and needs only `requests`, which
    the slim CPU image already installs — adding this backend costs no new
    dependency and no image rebuild. Set OPENROUTER_API_KEY on the endpoint.
    """
    def vision_fn(prompt, image_urls):
        import os
        import json as _json
        import requests
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError(
                "DAMAGE_BACKEND=openrouter needs OPENROUTER_API_KEY in the "
                "endpoint env (the free tier still authenticates).")
        model = os.environ.get("DAMAGE_VLM_MODEL", "google/gemma-4-31b-it:free")
        content = list(_openai_image_blocks(image_urls))
        content.append({"type": "text",
                        "text": "Analyse the vehicle in these photos and "
                                "return ONLY the JSON described above."})
        r = requests.post(
            os.environ.get("OPENROUTER_BASE_URL",
                           "https://openrouter.ai/api/v1") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            data=_json.dumps({
                "model": model,
                "max_tokens": 8192,
                "messages": [{"role": "system", "content": prompt},
                             {"role": "user", "content": content}],
            }),
            timeout=180)
        if r.status_code == 429:
            raise RuntimeError(
                f"{model} rate-limited (429). The free tier allows 20 req/min "
                f"and 50 req/day, or 1,000/day once the account has ever "
                f"purchased $10 of credits. Retry later, switch "
                f"DAMAGE_VLM_MODEL to another free model, or fall back to a "
                f"paid backend.")
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise RuntimeError(f"openrouter error: {body['error']}")
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"openrouter returned no choices: {body}")
        return (choices[0].get("message") or {}).get("content") or ""

    return vision_fn


def _openai_image_blocks(image_urls):
    """Image blocks in the OpenAI chat-completions shape.

    Remote URLs pass through; local files (the base64 job-input path) are
    inlined as data URIs, because a hosted model cannot reach this worker's
    disk."""
    import base64
    import mimetypes
    blocks = []
    for u in image_urls:
        s = str(u)
        if s.startswith(("http://", "https://")):
            url = s
        else:
            media_type = mimetypes.guess_type(s)[0] or "image/jpeg"
            with open(s, "rb") as f:
                data = base64.standard_b64encode(f.read()).decode("ascii")
            url = f"data:{media_type};base64,{data}"
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


def _qwen_backend():
    """Return a vision_fn backed by Qwen2.5-VL. Model load is deferred to
    first call and cached — the worker only pays for it when a photo job
    actually arrives, matching how trellis2 lazy-loads its pipeline."""
    state = {}

    def vision_fn(prompt, image_urls):
        import os
        model_id = os.environ.get("DAMAGE_VLM_MODEL",
                                  "Qwen/Qwen2.5-VL-7B-Instruct")
        if "model" not in state:
            from transformers import (AutoProcessor,
                                      Qwen2_5_VLForConditionalGeneration)
            state["processor"] = AutoProcessor.from_pretrained(model_id)
            state["model"] = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_id, torch_dtype="auto", device_map="auto")
        processor, model = state["processor"], state["model"]
        content = [{"type": "image", "image": u} for u in image_urls]
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]
        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=_load_images(image_urls),
                           return_tensors="pt").to(model.device)
        out = model.generate(**inputs, max_new_tokens=2048)
        trimmed = out[:, inputs.input_ids.shape[1]:]
        return processor.batch_decode(trimmed, skip_special_tokens=True)[0]

    return vision_fn


# Browser-like headers, carried over from trellis2/handler.py's fetch_image().
# A bare python-requests User-Agent is rejected outright by a lot of image
# hosts: a live job died with "403 Forbidden" fetching a Wikimedia photo, which
# is exactly the failure the vehicle worker had already solved. Users paste
# URLs from wherever their photos live, so this is the common case, not an edge.
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DamageScan-Worker/1.0)",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}


def _load_images(image_urls):
    from io import BytesIO
    import requests
    from PIL import Image
    imgs = []
    for u in image_urls:
        if str(u).startswith(("http://", "https://")):
            r = requests.get(u, headers=FETCH_HEADERS, timeout=30)
            r.raise_for_status()
            imgs.append(Image.open(BytesIO(r.content)).convert("RGB"))
        else:
            imgs.append(Image.open(u).convert("RGB"))
    return imgs


# --- small coercers -------------------------------------------------------

def _clamp01(v, default):
    if isinstance(v, str):
        v = v.strip().rstrip("%").strip()   # tolerate "40%" / "40 %"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x > 1.0:            # given as a percentage
        x /= 100.0
    return max(0.0, min(1.0, x))


def _num_or_none(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _bbox_or_none(v):
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return None
    try:
        x, y, w, h = (float(c) for c in v)
    except (TypeError, ValueError):
        return None
    # clamp to the unit square; drop degenerate boxes
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.0, min(1.0 - x, w))
    h = max(0.0, min(1.0 - y, h))
    if w <= 0 or h <= 0:
        return None
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]
