"""Find the car's panels, then let paint_mismatch measure between them.

WHY THIS MODULE EXISTS SEPARATELY FROM detect.py
------------------------------------------------
Two models, two jobs. The damage detector answers "what is wrong and where";
this one answers "which panel am I looking at". They are trained on different
data, have different class vocabularies, and fail in different ways, so they
get different env vars and different sessions. Running one model with the
other's labels.txt is how a run once produced confidently mislabelled
predictions while looking perfectly healthy.

    DAMAGE_PANEL_MODEL    path to the panel ONNX
    DAMAGE_PANEL_LABELS   comma-separated, placeholder first
    DAMAGE_PANEL_SIZE     input side (560)

COMPARISONS NEVER CROSS PHOTOGRAPHS, AND THAT IS THE WHOLE CORRECTNESS STORY
----------------------------------------------------------------------------
paint_mismatch works because two adjacent panels in ONE frame share their
lighting: same sun, same exposure, same white balance, same angle to the sky.
Take the hood from a photo shot into the sun and the fender from one shot in
shade and the measured dE is a fact about the photographer, not the paint. On
a corpus where undamaged panels already sat 11-17 dE from their own
surroundings, that error is larger than the effect being measured.

So compare_panels is called once per image and never across images, and the
findings are merged afterwards. A mismatch that only appears in one photo of
four is reported with that stated, rather than averaged into confidence.

THE DETECTOR HAS NO SIDE, SO NEITHER DOES THE FINDING
-----------------------------------------------------
The panel classes are `front_door`, `fender`, `quarter_panel` — there is no
`front_LEFT_door`, because the training data never distinguished them and a
photograph of a door does not say which side of the car it is on unless you
can see the rest of the car.

taxonomy.canonical_panel will happily map `front_door` to `front_left_door`,
and `back_door` to `front_left_door` as well. Both are guesses and the second
is simply wrong. So this module does NOT use it for these names. With a side
hint from the capture grid — which already asks the user for "front", "left
rear" and so on — the finding lands on the real panel; without one it lands on
`body_other`, which is honest, rather than on a left-hand panel that may not
be the damaged one.
"""
import os

try:                                   # package import
    from . import paint_mismatch as pm
except ImportError:                    # flat import, as the worker runs it
    import paint_mismatch as pm

# Panels whose taxonomy id does not depend on which side of the car you are
# standing on.
_SIDELESS = {
    "hood": "hood",
    "roof": "roof",
    "trunk": "tailgate",
    "front_bumper": "front_bumper",
    "back_bumper": "rear_bumper",
    "grille": "grille",
    "windshield": "windshield",
    "back_windshield": "rear_windshield",
    "license_plate": "body_other",
}

# Panels that need a side. The template is filled from the hint; with no hint
# the finding goes to body_other rather than guessing a side.
_SIDED = {
    "fender": "front_{s}_fender",
    "front_door": "front_{s}_door",
    "back_door": "rear_{s}_door",
    "quarter_panel": "{s}_quarter_panel",
    "rocker_panel": "{s}_rocker",
    "mirror": "{s}_mirror",
    "front_wheel": "front_{s}_wheel",
    "back_wheel": "rear_{s}_wheel",
    "headlight": "front_{s}_headlight",
    "tail_light": "rear_{s}_light",
    "front_window": "{s}_front_glass",
}

# dE at which a mismatch is as bad as this scale goes. Beyond DE_STRONG the
# difference is already obvious to a customer; 12 is a different colour.
_DE_CEILING = 12.0

DEFAULT_MIN_CONFIDENCE = 0.30


def side_of(hint):
    """'left' / 'right' / None from a capture-grid panel hint.

    Deliberately conservative: 'rear' alone says nothing about side, so it
    returns None rather than defaulting. A default here would put every
    unsided finding on the left-hand panels of every car.
    """
    if not hint:
        return None
    h = str(hint).lower()
    # UK trade shorthand, the same substitution taxonomy.py already makes.
    # Without it a British capture hint -- "nearside rear door" is how an
    # assessor writes it, and this product prices in GBP -- resolved to no
    # side, and every sided panel silently degraded to body_other. The two
    # modules disagreeing about the same vocabulary is worse than either
    # convention alone.
    #
    # Deliberately NOT extended to driver/passenger: that mapping flips with
    # the market, analyze.py resolves it against the vehicle's market before
    # a hint reaches here, and guessing it in this function would put damage
    # on the wrong flank of every left-hand-drive car.
    h = h.replace("nearside", "left").replace("offside", "right")
    h = h.replace("n/s", "left").replace("o/s", "right")
    if "left" in h:
        return "left"
    if "right" in h:
        return "right"
    return None


def taxonomy_panel(name, side=None):
    """Detector class -> taxonomy panel id, or body_other when unknowable."""
    n = str(name).strip().lower()
    if n in _SIDELESS:
        return _SIDELESS[n]
    if n in _SIDED and side in ("left", "right"):
        return _SIDED[n].format(s=side)
    return "body_other"


def detect_panels(img, session=None, min_confidence=None):
    """[{name, box, score}] for one open image, in its own pixel coordinates.

    Returns the panel boxes in the form compare_panels wants. No tiling here:
    a panel occupies a large share of the frame, so the whole-image pass sees
    it perfectly well, and tiling would cut every panel into fragments that
    the damage-oriented stitching rules were never meant to reassemble.
    """
    try:
        from .detect import onnx_detect_image
    except ImportError:
        from detect import onnx_detect_image
    floor = (DEFAULT_MIN_CONFIDENCE if min_confidence is None
             else min_confidence)
    if session is None:
        session = _session()
    labels = _labels()
    size = int(os.environ.get("DAMAGE_PANEL_SIZE", "560"))
    dets = onnx_detect_image(img, session=session, input_size=size,
                             labels=labels, min_confidence=floor)
    out = []
    for d in dets:
        x1, y1, x2, y2 = d["box"]
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        out.append({"name": str(d["label"]).lower(),
                    "box": (x1, y1, x2 - x1, y2 - y1),
                    "score": float(d["score"])})
    return out


_STATE = {}


def _session():
    import onnxruntime
    path = os.environ.get("DAMAGE_PANEL_MODEL")
    if not path:
        raise RuntimeError(
            "panel comparison needs DAMAGE_PANEL_MODEL pointing at the panel "
            "detector ONNX. Without it paint_mismatch has no panels to "
            "compare and is skipped, not guessed.")
    if _STATE.get("path") != path:
        _STATE["path"] = path
        _STATE["sess"] = onnxruntime.InferenceSession(
            path, providers=["CPUExecutionProvider"])
    return _STATE["sess"]


def _labels():
    raw = os.environ.get("DAMAGE_PANEL_LABELS", "")
    return [s.strip() for s in raw.split(",") if s.strip()] or None


def _severity(de, strong):
    """dE -> the 1-10 severity the rest of the pipeline speaks.

    A mismatch is never severity 1-3: by the time it clears DE_SUSPECT a
    trained eye can see it on adjacent panels, and the finding's whole purpose
    is to make someone look. It also never reaches 10 on its own, because a
    colour difference is evidence of a repair, not of a broken car — and
    paint_thickness is what tells the two apart.
    """
    lo, hi = 4, 8
    span = max(1e-6, _DE_CEILING - strong)
    frac = max(0.0, min(1.0, (de - strong) / span))
    base = lo if de < strong else lo + 1
    return int(max(lo, min(hi, round(base + frac * (hi - base)))))


def mismatch_findings(images, hints=None, min_confidence=None):
    """Run the panel comparison over each image INDEPENDENTLY.

    images: [PIL.Image] already open, in capture order.
    hints:  optional [panel_hint] parallel to images, used only for the side.

    Returns (findings, block). `block` is the measured section for the report
    and it lists what was COMPARED, not only what failed — "we compared eleven
    adjacent panel pairs across four photographs and one disagreed" is the
    result, and reporting only the one makes it impossible to judge.
    """
    hints = hints or []
    findings, pairs_ok, pairs_flagged, per_image = [], 0, 0, []
    for i, img in enumerate(images):
        hint = hints[i] if i < len(hints) else None
        side = side_of(hint)
        try:
            panels = detect_panels(img, min_confidence=min_confidence)
        except Exception as e:
            per_image.append({"image_index": i, "error":
                              f"{type(e).__name__}: {e}"})
            continue
        named = sorted({p["name"] for p in panels})
        # compare_panels does the adjacency walk and the CIEDE2000 itself; it
        # is given ONE image, never a mix. See the module docstring.
        results = pm.compare_panels(img, panels)
        painted = [p for p in named if _is_painted(p)]
        per_image.append({"image_index": i, "panels_found": named,
                          "painted_panels": painted,
                          "pairs_flagged": len(results)})
        pairs_flagged += len(results)
        for r in results:
            a, b = r["panels"]
            strong = pm.DE_STRONG + (pm.DE_PLASTIC_BONUS
                                     if r["plastic_pair"] else 0.0)
            findings.append({
                "panel": taxonomy_panel(a, side),
                "damage_type": "paint_mismatch",
                "severity": _severity(r["delta_e"], strong),
                # Confidence is about the MEASUREMENT, not the detector's
                # score: the dE is either far past the threshold or it is not.
                "confidence": round(min(0.95, 0.5 + 0.4 * min(
                    1.0, (r["delta_e"] - r["threshold"]) / 4.0)), 3),
                "image_index": i,
                "evidence": [
                    f"{a} and {b} are adjacent panels in this photograph and "
                    f"differ by dE {r['delta_e']} (CIEDE2000), past the "
                    f"{r['threshold']} threshold for this pair"
                    + (" (relaxed because one panel is plastic and takes "
                       "paint differently)" if r["plastic_pair"] else ""),
                    r["note"],
                ] + ([] if side else [
                    "the panel detector does not distinguish left from right "
                    "and no side was supplied with this photo, so the finding "
                    "is not assigned to a specific side"]),
            })
    for e in per_image:
        pairs_ok += max(0, len(e.get("painted_panels", [])) - 1)
    block = {
        "images_examined": len(images),
        "adjacent_pairs_flagged": pairs_flagged,
        "per_image": per_image,
        "method_note": (
            "Colour is compared only between panels that are adjacent IN THE "
            "SAME PHOTOGRAPH, because adjacent panels share their lighting. "
            "Panels from different photos are never compared: the difference "
            "would measure the light, not the paint."),
    }
    return findings, block


def _is_painted(name):
    try:
        from .training.class_map import PAINTED_PANELS
    except Exception:
        try:
            import class_map
            PAINTED_PANELS = class_map.PAINTED_PANELS
        except Exception:
            return False
    return name in PAINTED_PANELS


def _selftest():
    import numpy as np
    from PIL import Image
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ok   {name}")
        else:
            fail += 1
            print(f"  FAIL {name} {detail}")

    # --- side extraction is conservative ---
    check("left is read from a hint", side_of("front left door") == "left")
    check("right is read from a hint", side_of("REAR RIGHT") == "right")
    check("a sideless hint yields no side", side_of("rear") is None)
    check("no hint yields no side", side_of(None) is None)
    check("'front' alone is not a side", side_of("front") is None)

    # --- panel mapping never invents a side ---
    check("hood needs no side", taxonomy_panel("hood") == "hood")
    check("trunk maps to tailgate", taxonomy_panel("trunk") == "tailgate")
    check("a sided panel without a side is body_other",
          taxonomy_panel("front_door") == "body_other")
    check("a sided panel with a side is placed",
          taxonomy_panel("front_door", "left") == "front_left_door")
    check("back_door does NOT become a front door",
          taxonomy_panel("back_door", "left") == "rear_left_door")
    check("an unknown class is body_other",
          taxonomy_panel("spoiler", "left") == "body_other")
    # Every mapping must be a panel the taxonomy actually knows, or the
    # finding lands on an id nothing downstream can weight or render.
    try:
        from .taxonomy import PANELS
    except ImportError:
        from taxonomy import PANELS
    bad = [v for v in _SIDELESS.values() if v not in PANELS]
    bad += [t.format(s=s) for t in _SIDED.values() for s in ("left", "right")
            if t.format(s=s) not in PANELS]
    check("every mapped panel exists in the taxonomy", not bad, str(bad))

    # --- severity is bounded and monotone ---
    sevs = [_severity(de, 5.0) for de in (5.0, 6.0, 8.0, 12.0, 40.0)]
    check("severity is monotone in dE", sevs == sorted(sevs), str(sevs))
    check("severity never drops below 4", min(sevs) >= 4, str(sevs))
    check("severity never reaches 10", max(sevs) <= 8, str(sevs))

    # --- the end-to-end path, with a stub detector ---
    # Two adjacent panels, obviously different colours, in ONE frame.
    a = np.zeros((200, 400, 3), dtype="uint8")
    a[:, :200] = (150, 40, 40)          # fender: red
    a[:, 200:] = (150, 90, 40)          # front_door: noticeably browner
    img = Image.fromarray(a)
    stub = [{"name": "fender", "box": (10, 10, 180, 180), "score": 0.9},
            {"name": "front_door", "box": (210, 10, 180, 180), "score": 0.9}]

    real_detect = globals()["detect_panels"]
    globals()["detect_panels"] = lambda im, **k: stub
    try:
        f, block = mismatch_findings([img], hints=["front left"])
        check("a genuine colour difference produces a finding", len(f) == 1,
              str(f))
        if f:
            check("the finding is typed paint_mismatch",
                  f[0]["damage_type"] == "paint_mismatch")
            check("the side hint places the panel",
                  f[0]["panel"] == "front_left_fender", f[0]["panel"])
            check("evidence names the measurement",
                  any("dE" in e for e in f[0]["evidence"]))
        # same panels, same colour -> nothing
        b = np.full((200, 400, 3), (150, 40, 40), dtype="uint8")
        f2, _ = mismatch_findings([Image.fromarray(b)], hints=["front left"])
        check("matching paint produces no finding", not f2, str(f2))

        # NO side hint: the finding must not claim a side
        f3, _ = mismatch_findings([img])
        check("without a hint the panel is body_other",
              f3 and f3[0]["panel"] == "body_other",
              str(f3[0]["panel"]) if f3 else "none")
        check("without a hint the evidence says why",
              f3 and any("does not distinguish left from right" in e
                         for e in f3[0]["evidence"]))

        # TWO images are compared separately, never against each other.
        dark = Image.fromarray((np.asarray(img) * 0.45).astype("uint8"))
        f4, block4 = mismatch_findings([img, dark], hints=["front left"] * 2)
        check("each image is examined", block4["images_examined"] == 2)
        check("a shaded copy of the same car does not add a cross-image "
              "finding", len(f4) == 2, f"{len(f4)} findings")
        check("findings carry the image they came from",
              sorted(x["image_index"] for x in f4) == [0, 1])
    finally:
        globals()["detect_panels"] = real_detect

    # --- a broken detector degrades to a note, not an exception ---
    def boom(im, **k):
        raise RuntimeError("no model")
    globals()["detect_panels"] = boom
    try:
        f5, block5 = mismatch_findings([img])
        check("a missing panel model yields no findings, not a crash",
              f5 == [] and "error" in block5["per_image"][0])
    finally:
        globals()["detect_panels"] = real_detect

    check("the block explains the same-photo rule",
          "same photograph" in block["method_note"].lower())

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
