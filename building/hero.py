"""The photoreal shot, made FROM the measured model rather than instead of it.

Two things a builder needs from one job: a model that is right, and a picture
the client will react to. They pull in opposite directions. Geometry has to
come from measurement; realism is exactly the thing measurement cannot give.

So the pipeline splits the job in two and never lets the second half touch
the first:

    measured model -> preview.render()  -> exact geometry, flat shading
                   -> gemini restyle    -> brick, glass, sky, shadows
                   -> structural guard  -> did it move the building?

The restyle is given the render as its input image and told, in as many ways
as the prompt will carry, that every edge is fixed. This is the same idea as
driving a diffusion model from a depth or line image: the composition is
handed over, not invented.

WHY THE GUARD IS NOT OPTIONAL. This project has watched an image model slab a
whole terrace when asked to extend one house, twice, on the live endpoint,
with a red constraint outline drawn on the input. Nothing in the prompt
prevents that; the model is not doing geometry, it is doing plausibility. So
the output is measured against the input it was supposed to preserve, and a
picture that has quietly rebuilt the house is thrown away in favour of the
render that is correct. A pretty lie is worse than a plain truth here — the
whole product rests on the drawing being right.
"""
import base64
import math
import os
import sys


GEMINI_MODEL = "gemini-3.1-flash-image-preview"
GEMINI_API = ("https://generativelanguage.googleapis.com/v1beta/models/"
              f"{GEMINI_MODEL}:generateContent")

# Coarse grid the structural guard compares over. 24x24 is fine enough to
# catch a wall that has moved a metre and coarse enough not to fire on the
# brick texture and window reflections the restyle is SUPPOSED to add.
GUARD_GRID = 24

# Below this correlation between the render's structure and the photoreal
# one's, the image is not the same building. Chosen from measured pairs: a
# faithful restyle scores well above it, and the failure mode this exists to
# catch — a redrawn or duplicated building — falls far below.
GUARD_MIN_CORRELATION = 0.55


class HeroError(RuntimeError):
    """The photoreal pass could not be made, or could not be trusted."""


def _requests():
    import requests
    return requests


def gemini_key():
    return os.environ.get("GOOGLE_AI_API_KEY", "")


def _prompt(model, time_of_day="day"):
    """The instruction, written around what must NOT change.

    THE ROOF SENTENCES ARE READ FROM THE MODEL, NOT FROM A TEMPLATE. This
    used to hard-code "There is ONE roof... do not add a second ridge...
    or any valley" and "the low flat-roofed block" — true for the common
    case, and an argument with the measured render the moment roof_over
    legitimately splits a deep plan into parallel ranges with a valley
    between them, or the extension is a storey of the house rather than a
    flat-topped outrigger. A prompt that forbids a valley the render
    actually shows is instructing the restyle to erase measured geometry —
    the one failure this whole module exists to prevent. So the fixed-
    geometry clauses are derived from model["roof"] (ranges, kind) and the
    model's flat caps, and only ever assert what the render really draws.
    """
    fit = model.get("extension_fit") or {}
    built = fit.get("built_m") or {}
    storeys = model.get("storeys", 2)
    roof = model.get("roof") or None
    caps = model.get("caps") or []
    light = {
        "day": ("bright overcast British daylight, soft shadows, "
                "clean midday sky with light cloud"),
        "dusk": ("golden hour just after sunset, warm interior lights glowing "
                 "through the windows, deep blue sky"),
        "morning": "clear early morning light, long soft shadows, pale sky",
    }.get(time_of_day, "bright overcast British daylight")

    if roof:
        ranges = int(roof.get("ranges") or 1)
        kind = roof.get("kind") or "pitched"
        if ranges > 1:
            roof_rule = (
                f"- The main roof is measured as {ranges} parallel {kind} "
                "ranges with a valley gutter where they meet. Every ridge "
                "and every valley stays exactly where drawn — do not merge "
                "the ranges into one roof, and do not add ranges that are "
                "not drawn.\n")
        else:
            roof_rule = (
                "- There is ONE pitched roof over the tall block. Do not "
                "add a second ridge, a cross-gable, a hip that is not "
                "already drawn, or any valley.\n")
        main_roof = "a pitched concrete-tile roof"
    else:
        roof_rule = (
            "- The main block has a FLAT top, exactly as drawn. Do not add "
            "a ridge, a pitch or a gable.\n")
        main_roof = "a flat roof, exactly as drawn"

    # The extension is only "flat-roofed" when the model actually caps it —
    # a block that stops short of the building's top gets a flat cap; a
    # full-height or built-over extension sits under the main roof and
    # calling it flat contradicts the render.
    if caps:
        ext_rule = (
            "- The low flat-roofed block spans exactly the width already "
            "drawn. Do not shorten, narrow or reshape it.\n")
        ext_label = "The lower flat-roofed block"
        ext_surface = ("same brick, dark grey single-ply membrane roof, "
                       "slim aluminium-framed glazing")
    else:
        ext_rule = (
            "- The extension block spans exactly the footprint already "
            "drawn. Do not shorten, narrow or reshape it.\n")
        ext_label = "The extension block"
        ext_surface = ("same brick, roof exactly as drawn, slim "
                       "aluminium-framed glazing")

    return (
        "RETEXTURE THIS EXACT IMAGE. Do not re-render it, do not re-compose "
        "it, do not reinterpret it. Treat the picture as a photograph whose "
        "surfaces are to be repainted in place, pixel for pixel.\n\n"
        "It is a measured architectural massing render of a real British "
        "house with a proposed extension. The shapes in it are survey data.\n\n"
        "ABSOLUTE CONSTRAINT — THE GEOMETRY IS FIXED AND MEASURED:\n"
        "- Keep the silhouette identical. Every roofline, eaves line, ridge, "
        "corner and wall edge stays on exactly the same pixels.\n"
        + roof_rule
        + ext_rule +
        "- Do NOT add buildings, storeys, dormers, porches, chimneys, "
        "garages, bay windows or roof lights.\n"
        "- Do NOT move the camera, change the framing, or alter any "
        "proportion.\n"
        "- Windows and doors stay in the openings already drawn. Do not add "
        "openings to a blank wall or remove one that is there.\n\n"
        "WHAT TO CHANGE — SURFACES AND LIGHT ONLY:\n"
        f"- The {storeys}-storey block is red-brown facing brick with "
        f"realistic mortar courses and {main_roof}.\n"
        f"- {ext_label} is the proposed extension, "
        f"{built.get('width', '')}m by {built.get('depth', '')}m — "
        f"{ext_surface}.\n"
        "- Windows become real glass with reflections and visible frames.\n"
        "- Add UK domestic context on the ground only: lawn, a paved patio, "
        "a fence line at the plot edge.\n"
        f"- Lighting: {light}.\n\n"
        "Photographic quality, architectural photography, sharp focus, "
        "correct perspective. No text, no labels, no watermarks, no people."
    )


def _grid_structure(path, grid=GUARD_GRID):
    """A coarse map of where this image has edges.

    Luminance gradient magnitude, averaged into cells. Materials and light
    change the BRIGHTNESS of a surface everywhere; moving a wall changes
    WHERE the edges are. Comparing edge energy rather than colour is what
    lets the guard allow a restyle and refuse a rebuild.
    """
    from PIL import Image
    img = Image.open(path).convert("L").resize(
        (grid * 8, grid * 8), Image.LANCZOS)
    px = img.load()
    w, h = img.size
    cells = []
    for cy in range(grid):
        for cx in range(grid):
            acc = 0.0
            for y in range(cy * 8, (cy + 1) * 8):
                for x in range(cx * 8, (cx + 1) * 8):
                    if x + 1 >= w or y + 1 >= h:
                        continue
                    gx = px[x + 1, y] - px[x, y]
                    gy = px[x, y + 1] - px[x, y]
                    acc += math.hypot(gx, gy)
            cells.append(acc)
    return cells


def structural_match(before_path, after_path):
    """How much of the render's structure survived the restyle, 0 to 1.

    Pearson correlation of the two edge maps. Returns None if it cannot be
    computed, which is treated as "cannot verify" and not as a pass.
    """
    try:
        a = _grid_structure(before_path)
        b = _grid_structure(after_path)
    except Exception as e:
        print(f"structural guard unavailable: {e}", file=sys.stderr)
        return None
    if len(a) != len(b) or not a:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da = [v - ma for v in a]
    db = [v - mb for v in b]
    num = sum(x * y for x, y in zip(da, db))
    den = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    if den <= 0:
        return None
    return max(-1.0, min(1.0, num / den))


def restyle(render_path, model, work_dir, key, time_of_day="day",
            out_name="hero.png", reference_photo=None):
    """One geometry-locked restyle. Returns (path, correlation).

    Raises HeroError if the model gives nothing back. A picture that comes
    back CHANGED is not an error here — it is returned with its score so the
    caller can decide, because the caller is the one that knows whether it
    has a correct render to fall back on.

    reference_photo: an actual photo of THIS building. With it, the restyle
    is told to copy the real materials — the brick it actually has, the bay
    cladding it actually has — instead of inventing plausible ones.
    """
    with open(render_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    parts = [{"inline_data": {"mime_type": "image/png", "data": b64}}]
    prompt = _prompt(model, time_of_day)
    if reference_photo and os.path.exists(reference_photo):
        with open(reference_photo, "rb") as f:
            rb64 = base64.b64encode(f.read()).decode()
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": rb64}})
        prompt += (
            " The second image is a real photograph of this exact building:"
            " match its actual materials — brick colour and weathering,"
            " window frames, bay finish, roof tone — rather than inventing"
            " generic ones. The first image's geometry stays exactly as it"
            " is.")
    parts.append({"text": prompt})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"]}}

    r = _requests().post(GEMINI_API, params={"key": key}, json=body,
                         timeout=180)
    if r.status_code == 429:
        raise HeroError(
            "Gemini is rate-limited. The measured model and its renders are "
            "delivered; resend for the photoreal pass.")
    if r.status_code != 200:
        raise HeroError(f"Gemini answered {r.status_code}: {r.text[:200]}")

    parts = (((r.json().get("candidates") or [{}])[0]
              .get("content") or {}).get("parts") or [])
    for p in parts:
        data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
        if data:
            out = os.path.join(work_dir, out_name)
            with open(out, "wb") as f:
                f.write(base64.b64decode(data))
            return out, structural_match(render_path, out)
    raise HeroError("Gemini returned no image for the photoreal pass.")


def layer_onto_mesh(rendered, mask_path, restyled, out_path,
                    sky=(150, 178, 210), sky_bottom=(226, 234, 240)):
    """Force an AI restyle back through the mesh's own silhouette.

    THE FIX FOR THE FAILURE THAT KILLED THE FIRST PHOTOREAL PASS. Asking a
    model not to move the geometry does not work — four attempts came back
    with a redrawn roof and a shrunken extension, and no prompt changed that.
    But the render was made on transparent film, so its alpha channel IS the
    measured silhouette, exact to the pixel. Compositing the restyle THROUGH
    that mask means the building can only occupy the pixels the model says it
    occupies. Anything the AI invented outside the outline — an extra wing, a
    second roof, a neighbouring house — is discarded by construction rather
    than by persuasion.

    What this fixes and what it does not: the silhouette, the footprint, the
    roof pitch as seen and the overall massing become uncorrectable by the
    model. Detail INSIDE the outline is still the AI's, so a ridge line it
    moves within the envelope survives. That is the honest boundary, and it
    is why the structural score is still reported afterwards.
    """
    from PIL import Image

    base = Image.open(rendered).convert("RGB")
    mask = Image.open(mask_path).convert("L").resize(base.size, Image.LANCZOS)
    ai = Image.open(restyled).convert("RGB")
    if ai.size != base.size:
        # Models return their own aspect. Cover-fit and centre-crop rather
        # than squash, or every vertical on the building is stretched.
        sx, sy = base.size[0] / ai.size[0], base.size[1] / ai.size[1]
        s = max(sx, sy)
        ai = ai.resize((max(1, int(ai.size[0] * s)),
                        max(1, int(ai.size[1] * s))), Image.LANCZOS)
        left = (ai.size[0] - base.size[0]) // 2
        top = (ai.size[1] - base.size[1]) // 2
        ai = ai.crop((left, top, left + base.size[0], top + base.size[1]))

    # THE BACKGROUND STAYS OURS. Compositing the AI over a bare gradient
    # would leave the building hanging in the sky, and letting the AI keep
    # the ground hands back the freedom the mask just took away — the run
    # that invented a whole flat-roofed wing put it on the ground plane. So
    # the measured render supplies sky, ground and cast shadow, and the AI
    # supplies surfaces inside the silhouette and nowhere else.
    out = Image.composite(ai, base, mask)
    out.save(out_path)
    return out_path


def make(model, render_path, work_dir, scan, time_of_day="day",
         mask_path=None):
    """Produce a trusted photoreal shot, or explain why there isn't one.

    Returns (artifacts, note). Never raises — a proposal that has its model,
    its files and its measured renders is a delivered proposal, and the
    photoreal pass is the part that is allowed to fail.
    """
    key = gemini_key()
    if not key:
        return [], ("no photoreal pass: GOOGLE_AI_API_KEY is not configured "
                    "on this worker")
    try:
        out, score = restyle(render_path, model, work_dir, key, time_of_day,
                             out_name=f"{scan}.hero.png")
    except HeroError as e:
        return [], f"no photoreal pass: {e}"
    except Exception as e:
        return [], f"no photoreal pass: {type(e).__name__}: {e}"

    # WITH A MASK, THE GUARD STOPS BEING THE LAST LINE OF DEFENCE. Forcing
    # the restyle through the measured silhouette makes the outline correct
    # by construction, so a low structural score no longer means the picture
    # is unusable — it means the AI moved detail INSIDE the envelope, which
    # the composite then bounded. The score is still reported, because
    # detail inside the outline is genuinely the model's invention.
    if mask_path and os.path.exists(mask_path):
        try:
            layered = os.path.join(work_dir, f"{scan}.hero.png")
            layer_onto_mesh(render_path, mask_path, out, layered)
            if layered != out and os.path.exists(out):
                os.remove(out)
            return ([(layered, f"renders/{scan}.hero.png", None)],
                    f"photoreal materials composited through the measured "
                    f"silhouette — the outline, footprint and massing are the "
                    f"model's; surfaces inside it are generated "
                    f"(free-run structure score {score:.2f})"
                    if score is not None else
                    "photoreal materials composited through the measured "
                    "silhouette")
        except Exception as e:
            print(f"masking failed, falling back: {e}", file=sys.stderr)

    if score is None:
        return ([(out, f"renders/{scan}.hero.png", None)],
                "photoreal pass delivered UNVERIFIED — the structural guard "
                "could not run, so check it against the measured render")
    if score < GUARD_MIN_CORRELATION:
        # Kept as evidence, but named so nobody mistakes it for the proposal.
        rejected = os.path.join(work_dir, f"{scan}.hero-rejected.png")
        try:
            os.replace(out, rejected)
        except OSError:
            rejected = out
        return ([(rejected, f"renders/{scan}.hero-rejected.png", None)],
                f"photoreal pass REJECTED: it scored {score:.2f} against the "
                f"measured render (needs {GUARD_MIN_CORRELATION}), which "
                f"means it redrew the building rather than resurfacing it. "
                f"The measured renders are the proposal.")
    return ([(out, f"renders/{scan}.hero.png", None)],
            f"photoreal pass verified against the measured render "
            f"(structure {score:.2f})")


def montage_prompt(fit):
    """The montage instruction, built from the MEASURED brief.

    The best-received image this project ever produced was a hand-typed
    Gemini edit of the real photo — made outside the product, with the
    extension sized by the model's eye rather than by the survey. This keeps
    the part that worked (the real photo constrains the real house) and
    fixes the part that did not: the size and side come from the fit the
    clearance probe approved, stated in metres, not left to imagination.
    """
    built = fit.get("built_m") or {}
    kind = fit.get("type", "rear")
    storeys = int(fit.get("storeys") or 1)
    side = fit.get("side")
    where = {"rear": "at the BACK of the house",
             "side": f"on the {side or 'open'} side of the house",
             "over": "on top of the existing single-storey side element",
             "wrap": "wrapping the rear corner of the house"}.get(kind, kind)
    return (
        "This is a real photograph of a British house.\n\n"
        f"TASK: add a proposed {storeys}-storey {kind} extension {where}, "
        "as an architect's photomontage.\n\n"
        "SIZE — from the survey, not from imagination: "
        f"{built.get('width', '?')} metres wide by "
        f"{built.get('depth', '?')} metres deep, "
        f"{storeys} storey(s) tall, subordinate to the existing house.\n\n"
        "WHAT MUST NOT CHANGE — this is a real property:\n"
        "- The existing house stays EXACTLY as photographed: every window, "
        "door, bay, chimney, roof line and brick.\n"
        "- The camera, perspective, road, drive, boundaries, sky and light "
        "stay as they are.\n"
        "- Neighbouring buildings stay untouched.\n\n"
        "THE EXTENSION: matching brick and mortar coursing, matching roof "
        "material, window frames matching the existing, gutters and "
        "downpipes, correct perspective, shadow consistent with the sun in "
        "the photograph.\n\n"
        "Photorealistic. No text, no labels, no people."
    )


def montage_on_photo(photo_path, fit, key, out_path):
    """Before/after on the real photo. Returns (out_path, note).

    The photo is Street View Static imagery and carries Google's attribution
    in-frame; Google's terms require it stays visible, so nothing here crops
    or removes it and the note says so. The 'before' is the photo itself —
    it is already on disk and is delivered alongside.
    """
    with open(photo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
        {"text": montage_prompt(fit)}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]}}
    r = _requests().post(GEMINI_API, params={"key": key}, json=body,
                         timeout=180)
    if r.status_code != 200:
        raise HeroError(f"montage: Gemini answered {r.status_code}")
    parts = (((r.json().get("candidates") or [{}])[0]
              .get("content") or {}).get("parts") or [])
    for p in parts:
        d = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
        if d:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(d))
            return out_path, (
                "photomontage on Street View imagery — imagery (c) Google, "
                "attribution retained as its terms require; the extension's "
                "stated size is from the survey, its rendering is generated")
    raise HeroError("montage: Gemini returned no image")
