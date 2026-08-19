"""The join: a twin edited on screen, run through the real engine.

Stage 2's point. The building/ package already knows how to check a
design against Part B escape, Part K stairs, Part L fabric, Part F
ventilation and Part O overheating, to take off a bill of quantities,
and to write IFC. None of that was reachable from a map. This module
converts a Building into what that engine wants, runs it, and converts
the answers back with provenance attached.

WHAT IS HONEST ABOUT THIS. The engine measures rectangles. A twin built
from a traced footprint carries the real outline AND the rectangle
fitted to it, and model.from_footprint already reports the difference
when it matters. Anything computed here is therefore `derived` at best,
never `verified`, and the note travels with the number.
"""
from __future__ import annotations

from .model import to_engine_rooms
from .provenance import CLASS_DERIVED, Missing, Provenance, Sourced


def _roof_spec(bld):
    """The tallest block's roof drives the main roof, as it does on site."""
    blk = max(bld.blocks, key=lambda b: (b.storeys, b.area()))
    r = dict(blk.roof or {})
    if r.get("kind") in (None, "flat"):
        return None
    return {"pitch_deg": r.get("pitch_deg", 30.0),
            "kind": r.get("kind", "gabled"),
            "overhang": r.get("overhang", 0.3),
            "ridge_along": r.get("ridge_along", "y"),
            "high_side": r.get("high_side", "min"),
            "max_span_m": 9.0}


def build_engine_model(bld):
    """Run building/model3d over the twin. Returns (model, M) or raises."""
    rooms, M = to_engine_rooms(bld)
    if not rooms:
        raise ValueError("nothing to build")
    storeys = max(b.base_level + b.storeys for b in bld.blocks)
    sh = max(b.storey_height for b in bld.blocks)
    model = M.build(rooms, storeys=storeys, storey_height=sh,
                    roof=_roof_spec(bld))
    # Openings the user placed. The engine indexes along a wall, and the
    # twin indexes along a block edge, so they are matched by geometry
    # rather than by name — names drift, coordinates do not.
    for op in bld.openings:
        blk = bld.block(op.block_id)
        if blk is None:
            continue
        edge_pts = {e[1]: e[2] for e in blk.edges()}
        pts = edge_pts.get(op.edge)
        if not pts:
            continue
        (x0, y0), (x1, y1) = pts
        best, bestd = None, 1e9
        for w in model["walls"]:
            if not w.get("external"):
                continue
            d = (min(abs(w["start"][0] - x0) + abs(w["start"][1] - y0),
                     abs(w["start"][0] - x1) + abs(w["start"][1] - y1))
                 + min(abs(w["end"][0] - x1) + abs(w["end"][1] - y1),
                       abs(w["end"][0] - x0) + abs(w["end"][1] - y0)))
            if d < bestd:
                best, bestd = w, d
        if best is not None and bestd < 2.0:
            along = min(max(0.0, op.along_m),
                        max(0.0, best["length_m"] - op.width))
            best["openings"].append({
                "kind": "door" if op.kind in ("door", "bifold") else "window",
                "along": round(along, 3), "width": op.width,
                "height": op.height, "sill": op.sill, "level": op.level})
    return model, M


def assess(bld, *, region=None, vat="standard", calibrate_per_m2=None):
    """Regs gate + quantities + a priced estimate for the current design."""
    out = {"available": True}
    try:
        model, M = build_engine_model(bld)
    except Exception as e:
        return {"available": False, "status": "DATA NOT AVAILABLE",
                "reason": "the design could not be built into a model",
                "detail": f"{type(e).__name__}: {e}"}

    prov = Provenance(
        source_provider="twin", source_dataset="user design",
        licence="ogl-3.0", confidence=0.6,
        processing_method="building/model3d over the twin's fitted "
                          "rectangles; areas are indicative where the "
                          "traced outline is not rectangular")

    try:
        import buildable as B
        chk = B.check(model)
        out["compliance"] = {
            "buildable": chk["buildable"],
            "counts": chk["counts"],
            "findings": [{"severity": f["severity"], "code": f["code"],
                          "message": f["message"]}
                         for f in chk["findings"]],
        }
        # A MASSING IS NOT A FAILED DESIGN. The gate needs rooms — a
        # hall for a stair to rise from, a habitable room to escape from
        # — and a block model has none, so it refuses every time. Saying
        # "not buildable" without that context reads as "your extension
        # is illegal", which is a different and untrue statement.
        # WHETHER THIS IS A MASSING IS A FACT ABOUT THE MODEL, not a
        # guess from the finding codes. Once rooms are drawn, a Part O
        # glazing refusal is a real answer about a real design, and
        # filing it under "massing" would tell the user to ignore a
        # finding they should act on.
        codes = {f["code"] for f in chk["findings"]}
        massing_only = (not bld.has_rooms()) and bool(codes) and codes <= {
            "CIRC-NONE", "K-NOHALL", "O-GLAZING", "B-NOESCAPE",
            "INNER-ROOM", "K-NOSTAIR", "CIRC-ISLAND", "CIRC-INNER2"}
        out["compliance"]["stage"] = "massing" if massing_only else "design"
        out["compliance"]["note"] = (
            "This is a MASSING model — solid blocks with no room layout "
            "yet. The regulations gate needs rooms (a hall for the stair, "
            "habitable rooms for escape windows), so these refusals are "
            "about what has not been drawn yet, not about the extension "
            "being unlawful. Draw the rooms to get a real answer."
            if massing_only else
            "Checked against the room layout as drawn.")
    except Exception as e:
        out["compliance"] = {"available": False,
                             "reason": f"regs check unavailable: {e}"}

    try:
        extra = M._with_buildability(model)
        M._absorb_buildability(model, extra)
    except Exception:
        pass

    import quantities as Q
    try:
        bill = Q.bill(model)
        out["quantities"] = {
            "groups": {k: [{"item": L["item"], "quantity": L["quantity"],
                            "unit": L["unit"], "basis": L["basis"]}
                           for L in v if L["quantity"]]
                       for k, v in bill["groups"].items()},
            "notes": bill["notes"],
        }
    except Exception as e:
        out["quantities"] = {"available": False,
                             "reason": f"take-off unavailable: {e}"}

    # PRICE IT. The bill is measured; estimate.py turns it into money and
    # — crucially — declares its own coverage, its rate provenance and a
    # range, so a partial or uncalibrated estimate cannot pose as a quote.
    try:
        import estimate as E
        card = E.RateCard(region=region or E.DEFAULT_REGION)
        if calibrate_per_m2:
            card, _rep = E.calibrate(
                Q.bill(model), max(1.0, float(
                    (model.get("totals") or {}).get("floor_area_m2") or 1.0)),
                known_per_m2=float(calibrate_per_m2), card=card)
        priced = E.price_bill(
            Q.bill(model), card,
            estimate_class=("order_of_magnitude"
                            if out.get("compliance", {}).get("stage")
                            == "massing" else "concept"),
            vat=vat or "standard")
        gia = float((model.get("totals") or {}).get("floor_area_m2") or 0.0)
        priced["per_m2"] = E.per_m2(priced, gia) if gia else None
        out["estimate"] = priced
    except Exception as e:
        out["estimate"] = {"available": False,
                           "reason": f"pricing unavailable: {e}"}

    t = model.get("totals") or {}
    out["totals"] = {
        "floor_area_m2": t.get("floor_area_m2"),
        "eaves_height_m": t.get("eaves_height_m"),
        "ridge_height_m": t.get("ridge_height_m"),
    }
    out["warnings"] = model.get("warnings", [])[:8]
    out["classification"] = CLASS_DERIVED
    out["provenance"] = prov.as_dict()
    return out


def floor_plan(bld):
    """Per-storey plan geometry, in building-frame metres.

    The floor plan and the 3D read THE SAME blocks — this returns a view
    of the model, not a second drawing that could disagree with it.
    """
    storeys = max((b.base_level + b.storeys for b in bld.blocks), default=1)
    levels = []
    for lvl in range(storeys):
        blocks, walls = [], []
        for b in bld.blocks:
            if not (b.base_level <= lvl < b.base_level + b.storeys):
                continue
            blocks.append({"id": b.id, "name": b.name, "ring": b.ring(),
                           "classification": b.classification,
                           "area_m2": round(b.area(), 2)})
            for eid, ename, pts, normal in b.edges():
                # A wall between two blocks on this level is internal.
                mx = (pts[0][0] + pts[1][0]) / 2 + normal[0] * 0.2
                my = (pts[0][1] + pts[1][1]) / 2 + normal[1] * 0.2
                external = not any(
                    o is not b
                    and o.base_level <= lvl < o.base_level + o.storeys
                    and o.x - 1e-6 <= mx <= o.x + o.width + 1e-6
                    and o.y - 1e-6 <= my <= o.y + o.depth + 1e-6
                    for o in bld.blocks)
                walls.append({"id": eid, "block": b.id, "edge": ename,
                              "points": pts, "external": external,
                              "length_m": round(
                                  ((pts[1][0] - pts[0][0]) ** 2 +
                                   (pts[1][1] - pts[0][1]) ** 2) ** 0.5, 2)})
        ops = [o.as_dict() for o in bld.openings if o.level == lvl]
        rooms = [r.as_dict() for r in bld.rooms_on(lvl)]
        # Partitions: the internal walls implied by the room rectangles.
        parts = []
        for r in bld.rooms_on(lvl):
            for eid, ename, pts, _n in (
                    (f"{r.id}:front", "front",
                     [[r.x, r.y], [r.x + r.width, r.y]], None),
                    (f"{r.id}:right", "right",
                     [[r.x + r.width, r.y],
                      [r.x + r.width, r.y + r.depth]], None),
                    (f"{r.id}:rear", "rear",
                     [[r.x + r.width, r.y + r.depth],
                      [r.x, r.y + r.depth]], None),
                    (f"{r.id}:left", "left",
                     [[r.x, r.y + r.depth], [r.x, r.y]], None)):
                parts.append({"id": eid, "room": r.id, "edge": ename,
                              "points": pts,
                              "length_m": round(
                                  ((pts[1][0] - pts[0][0]) ** 2 +
                                   (pts[1][1] - pts[0][1]) ** 2) ** 0.5, 2)})
        levels.append({"level": lvl, "blocks": blocks, "walls": walls,
                       "rooms": rooms, "partitions": parts,
                       "openings": ops,
                       "room_area_m2": round(
                           sum(r["area_m2"] for r in rooms), 2),
                       "area_m2": round(sum(b["area_m2"] for b in blocks), 2)})
    return {"available": True, "levels": levels,
            "storey_height_m": max((b.storey_height for b in bld.blocks),
                                   default=2.65)}


def massing(bld):
    """Solids for the 3D view: one prism per block plus a roof spec.

    Emitted in building-frame metres with the anchor and bearing beside
    them, so the client can place the model on the earth without
    reimplementing the projection.
    """
    solids = []
    for b in bld.blocks:
        base = b.base_level * b.storey_height
        top = base + b.storeys * b.storey_height
        r = dict(b.roof or {})
        solids.append({
            "id": b.id, "name": b.name, "ring": b.ring(),
            "base_m": round(base, 3), "eaves_m": round(top, 3),
            "storeys": b.storeys, "storey_height": b.storey_height,
            "classification": b.classification,
            "roof": {"kind": r.get("kind", "flat"),
                     "pitch_deg": r.get("pitch_deg", 0.0),
                     "ridge_along": r.get("ridge_along", "y"),
                     "high_side": r.get("high_side", "min"),
                     "classification": r.get("classification", "estimated")},
        })
    return {"available": True, "solids": solids,
            "anchor": {"lat": bld.anchor_lat, "lon": bld.anchor_lon,
                       "bearing_deg": bld.bearing_deg},
            "ground_m_aod": bld.ground_m_aod,
            "traced_ring": bld.traced_ring}
