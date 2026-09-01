"""Attribute each damage finding to the panel it actually sits on.

THE GAP THIS CLOSES

Two models already run on every inspection. The damage detector says "a dent,
here". The panel detector says "that region is the near-side rear door". They
have never been introduced. detect.detections_to_findings sets

    "panel": panel_hint or d.get("panel") or "body_other"

so a finding's panel comes from the CAPTURE GRID -- the operator telling the
app which panel a photo shows -- and from nowhere else. Without a hint every
finding is body_other, and fusion.pin_for then places every 3D pin on the
body_other anchor at (0, 0, 0): the middle of the car. A rotatable model with
eleven pins stacked at the origin.

That is the difference between "a box on a photo" and "a dent on the
near-side rear door", which is the output an assessor actually prices.

MATCHING IS BY CONTAINMENT, NOT IoU

A 40px dent inside a 600px door has an IoU of about 0.004 -- IoU asks whether
two boxes are the same box, and here they are deliberately not. The question
is what fraction of the DAMAGE lies inside the PANEL, which is the
intersection over the damage area alone. A dent wholly inside a door scores
1.0 against that door however large the door is.

Panels overlap: a rocker underlaps a door, a fender meets a bumper. When two
panels both contain a finding, the SMALLER wins, because the smaller box is
the more specific claim. Ties on containment alone would otherwise hand every
finding to whichever big panel happened to be listed first.

SIDE IS NEVER GUESSED

Eleven of the twenty-one panel classes need a side -- "fender" alone cannot
become front_left_fender. panels.side_of derives it from the capture hint and
returns None when the hint does not say. This module keeps that discipline: a
sided panel with no known side degrades to body_other rather than inventing a
side, because a pin on the wrong flank of the car is worse than a pin in the
middle that admits it does not know.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "training"))

# Fraction of the damage box that must lie inside a panel box to count.
# Below this the finding straddles a seam or the panel box is wrong, and
# body_other is the honest answer.
MIN_CONTAINMENT = 0.5


def containment(inner, outer):
    """Fraction of `inner`'s area that lies inside `outer`. Both [x1,y1,x2,y2]."""
    ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return inter / area if area > 0 else 0.0


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def best_panel(damage_box, panels, min_containment=MIN_CONTAINMENT):
    """(panel_dict, containment) for the panel this damage sits on, or (None, 0).

    Among panels that contain enough of the damage, the SMALLEST wins: it is
    the most specific claim about where the damage is.
    """
    hits = []
    for p in panels:
        c = containment(damage_box, p["box"])
        if c >= min_containment:
            hits.append((c, p))
    if not hits:
        return None, 0.0
    c, p = min(hits, key=lambda cp: (_area(cp[1]["box"]), -cp[0]))
    return p, c


def attribute(findings, panels_per_image, image_sizes, hints=None):
    """Set finding['panel'] from the panel detector. Returns (findings, report).

    `findings` are normalised findings carrying `image_index` and `bbox`
    (normalised 0-1, [x, y, w, h] -- the shape detections_to_findings emits).
    `panels_per_image` maps image_index -> [{name, box, score}] in that image's
    OWN pixels, which is what panels.detect_panels returns.
    `image_sizes` maps image_index -> (width, height), REQUIRED because the two
    coordinate systems differ and the frame must not be guessed.

    An earlier draft inferred the frame from the extent of the panel boxes.
    That is wrong whenever the panels do not reach the edges -- a car
    photographed with sky above it and tarmac below reports a frame the height
    of the car, and every finding below the car's midline is then rescaled onto
    the wrong panel. It also happens to be self-fulfilling: a finding at 0.9 of
    a frame defined as the panel extent is inside that panel by construction,
    so the bug cannot fail its own test. Callers hold the real size; they pass
    it.

    A finding that already carries a real panel from the capture grid keeps it:
    the operator naming the panel they photographed is better evidence than a
    box overlap, and this must not overwrite it. Only body_other is filled in.
    """
    import panels as panels_mod

    hints = hints or {}
    filled = kept = unresolved = no_side = 0
    per_panel = {}

    for f in findings:
        current = f.get("panel") or "body_other"
        if current != "body_other":
            kept += 1
            continue

        idx = f.get("image_index", 0)
        found = panels_per_image.get(idx) or []
        bbox = f.get("bbox")
        if not found or not bbox or len(bbox) != 4:
            unresolved += 1
            continue

        # findings carry normalised xywh; panel boxes are pixel xyxy.
        size = image_sizes.get(idx)
        if not size:
            unresolved += 1
            continue
        W, H = size
        x, y, w, h = bbox
        dmg = [x * W, y * H, (x + w) * W, (y + h) * H]

        p, c = best_panel(dmg, found)
        if p is None:
            unresolved += 1
            continue

        side = panels_mod.side_of(hints.get(idx))
        name = panels_mod.taxonomy_panel(p["name"], side)
        if name == "body_other":
            # taxonomy_panel refuses to guess a side. Record that separately
            # from "no panel found" -- the fix for one is a capture hint, for
            # the other a better panel model, and conflating them hides both.
            no_side += 1
            continue

        f["panel"] = name
        f["panel_source"] = "detector"
        f["panel_confidence"] = round(float(p.get("score", 0.0)), 3)
        f["panel_containment"] = round(c, 3)
        filled += 1
        per_panel[name] = per_panel.get(name, 0) + 1

    report = {
        "findings": len(findings),
        "panel_from_capture_hint": kept,
        "panel_from_detector": filled,
        "no_panel_matched": unresolved,
        "panel_needs_side_unknown": no_side,
        "per_panel": per_panel,
    }
    return findings, report


def _selftest():
    ok = fail = 0

    def check(n, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {n}")
        else:
            fail += 1
            print(f"  FAIL  {n}  {detail}")

    # containment, not IoU: a small dent wholly inside a big door is 1.0
    dent = [100, 100, 140, 140]
    door = [0, 0, 600, 600]
    check("a dent inside a door is fully contained",
          containment(dent, door) == 1.0)
    inter = 40 * 40
    union = 40 * 40 + 600 * 600 - inter
    check("...while its IoU is negligible, which is why IoU is not used",
          inter / union < 0.01, f"{inter/union:.4f}")
    check("no overlap is 0", containment([700, 700, 750, 750], door) == 0.0)
    check("half in, half out is 0.5",
          abs(containment([-20, 0, 20, 40], [0, 0, 600, 600]) - 0.5) < 1e-9)

    # the smaller panel wins when both contain the damage
    panels = [{"name": "front_door", "box": [0, 0, 600, 600], "score": .9},
              {"name": "rocker_panel", "box": [80, 80, 200, 200], "score": .8}]
    p, c = best_panel(dent, panels)
    check("the smaller containing panel wins (more specific)",
          p["name"] == "rocker_panel", str(p))
    check("...and its containment is reported", c == 1.0)

    # too little overlap -> nothing
    p, _ = best_panel([550, 550, 700, 700], [panels[0]])
    check("a finding mostly outside every panel matches none", p is None)

    # end to end through attribute(). The frame is 1000x1000 and the door
    # occupies its top-left quarter, so a finding at 0.9 is genuinely off the
    # door -- which an inferred frame could never express.
    SIZES = {0: (1000, 1000)}
    F = [{"image_index": 0, "bbox": [0.2, 0.2, 0.05, 0.05], "panel": "body_other"},
         {"image_index": 0, "bbox": [0.9, 0.9, 0.08, 0.08], "panel": "body_other"},
         {"image_index": 0, "bbox": [0.2, 0.2, 0.05, 0.05], "panel": "hood"}]
    P = {0: [{"name": "front_door", "box": [0, 0, 500, 500], "score": .91}]}
    out, rep = attribute([dict(f) for f in F], P, SIZES,
                         hints={0: "front left door"})
    check("a sided panel resolves with a side from the hint",
          out[0]["panel"] == "front_left_door", out[0]["panel"])
    check("the detector is recorded as the source",
          out[0]["panel_source"] == "detector")
    check("containment and panel confidence are carried",
          out[0]["panel_containment"] == 1.0
          and out[0]["panel_confidence"] == 0.91)
    check("a finding outside every panel stays body_other",
          out[1]["panel"] == "body_other")
    check("a capture-grid panel is never overwritten",
          out[2]["panel"] == "hood")
    check("the report counts each route",
          rep["panel_from_detector"] == 1 and rep["panel_from_capture_hint"] == 1
          and rep["no_panel_matched"] == 1, str(rep))

    # no hint -> a sided panel must NOT invent a side
    out2, rep2 = attribute([dict(F[0])], P, SIZES, hints={})
    check("with no hint a sided panel degrades to body_other, not a guess",
          out2[0]["panel"] == "body_other", out2[0]["panel"])
    check("...and that is counted separately from 'no panel matched'",
          rep2["panel_needs_side_unknown"] == 1 and rep2["no_panel_matched"] == 0,
          str(rep2))

    # a sideless panel needs no hint at all
    P2 = {0: [{"name": "hood", "box": [0, 0, 500, 500], "score": .77}]}
    out3, _ = attribute([dict(F[0])], P2, SIZES, hints={})
    check("a sideless panel resolves without any hint",
          out3[0]["panel"] == "hood", out3[0]["panel"])

    # every name this can emit must be a real fusion anchor, or the pin
    # silently falls back to the origin -- the bug this module exists to fix
    import fusion
    import panels as panels_mod
    emitted = set()
    for n in list(panels_mod._SIDELESS) + list(panels_mod._SIDED):
        for s in ("left", "right", None):
            emitted.add(panels_mod.taxonomy_panel(n, s))
    missing = sorted(e for e in emitted if e not in fusion.PANELS)
    check("every panel name this can emit has a 3D anchor in fusion",
          not missing, str(missing))

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(_selftest())
