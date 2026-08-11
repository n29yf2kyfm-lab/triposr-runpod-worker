"""Pin findings onto the 3D model — the capability none of the rivals have.

Every competitor ends at a 2D result: a box on a photo, a list, a PDF. This
platform already turns a car into a real 3D model (trellis2/). Fusion is the
join: it takes the findings and places each one as a PIN in the coordinate
frame of that model, so the app shows a rotatable car with the damage marked
ON it — the same object, inspected. A fleet manager scrubbing returns, an
insurer triaging a claim, a buyer 300 miles away: all of them read a 3D map
faster than a stack of photos.

WHAT THIS PRODUCES: a list of pins, each carrying
  - anchor (x,y,z) in the normalised car frame (taxonomy panel anchors)
  - normal: which way the pin faces, so a decal sits flat on the body
  - the finding it represents (severity, colour, label) for the label bubble
  - the source image + bbox, so tapping a pin opens the photo it came from

HONEST LIMITATION, stated plainly (the repo's house rule — an overlay that
claims precision it lacks is worse than one that admits it): the anchor is the
PANEL's canonical location, not the pixel-exact dent position on this specific
body. Photo-to-model pixel registration (solving the camera pose against the
mesh) is a heavier, later step. Panel-level placement is honest, useful, and
correct at the granularity a viewer actually needs — a pin on the front-left
fender, not floating 4 cm off the real crease. `precision: "panel"` is stamped
on every pin so the app never implies more.
"""
from taxonomy import PANELS, severity_band, clamp_severity

# The forward axis of the pinned model, so the app can align our car frame
# (+z forward) to whatever axis the loaded GLB uses. trellis2 bakes into a
# unit AABB with no guaranteed heading, so the app confirms the heading once
# (from the reference image / a quick auto-orient) and applies this mapping.
FRAME = {
    "convention": "right-handed, +x=vehicle-right, +y=up, +z=forward",
    "extent": [[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
    "note": "Anchors are in this normalised car frame. Align the loaded GLB's "
            "forward axis to +z once, then the pins land on the right panels.",
}


def _panel_normal(anchor):
    """Outward direction for a decal at this anchor.

    Cheap and good enough: the dominant axis of the anchor points outward for
    body sides / front / rear; roof and bonnet read as up-facing. This keeps a
    scratch decal lying along the panel instead of poking through it.
    """
    x, y, z = anchor
    ax, ay, az = abs(x), abs(y), abs(z)
    if ay >= ax and ay >= az and y > 0.25:
        return [0.0, 1.0, 0.0]                      # roof / upper bonnet: up
    if ax >= az:
        return [1.0 if x >= 0 else -1.0, 0.0, 0.0]  # a side panel
    return [0.0, 0.0, 1.0 if z >= 0 else -1.0]      # front / rear


def pin_for(finding, index=0):
    """Build one pin dict from a normalised finding."""
    panel = finding.get("panel") or "body_other"
    label, region, anchor = PANELS.get(panel, ("Body", "other", (0.0, 0.0, 0.0)))
    sev = clamp_severity(finding.get("severity", 5))
    band, colour = severity_band(sev)
    return {
        "id": f"pin_{index}",
        "panel": panel,
        "panel_label": label,
        "region": region,
        "anchor": list(anchor),
        "normal": _panel_normal(anchor),
        "severity": sev,
        "severity_band": band,
        "colour": colour,
        "damage_type": finding.get("damage_type"),
        "label": f"{finding.get('damage_label', 'Damage')} · sev {sev}",
        "has_hidden_damage": bool(finding.get("hidden_damage")),
        "source_image_index": finding.get("image_index"),
        "source_bbox": finding.get("bbox"),
        "precision": "panel",
    }


def build_pins(findings):
    """All pins for a finding list, plus a per-panel cluster count so the app
    can badge a panel that has several findings instead of stacking pins."""
    pins = [pin_for(f, i) for i, f in enumerate(findings)]
    per_panel = {}
    for p in pins:
        per_panel[p["panel"]] = per_panel.get(p["panel"], 0) + 1
    return {
        "frame": FRAME,
        "pins": pins,
        "panel_counts": per_panel,
        "count": len(pins),
    }


def fuse(findings, glb_url=None):
    """Top-level: pins + the model they attach to.

    glb_url is the trellis2 output for this vehicle (the app usually already
    has it from the 3D job). It is passed through, not fetched — fusion is
    geometry, not I/O. When absent, the pins are still valid in the car frame
    and the app can attach them to any model of the same vehicle.
    """
    result = build_pins(findings)
    result["glb_url"] = glb_url
    result["fused"] = bool(glb_url)
    if not glb_url:
        result["note"] = (
            "No glb_url supplied — pins are in the normalised car frame and "
            "attach to any 3D model of this vehicle. Run the trellis2 vehicle "
            "job (image-to-3D from the same photos, or the make/model spec) "
            "and pass its glb_url to bind them.")
    return result
