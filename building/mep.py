"""Every pipe and wire, ROUTED — not estimated.

The gap this closes. heatloss.py sizes and places radiators, electrics.py
places sockets and the consumer unit, ventilation.py places fans. All of
that is real design, and until now none of it was MODELLED: the pipes and
cables existed only as rules of thumb in the bill ("8 m of T&E per
socket"), and nothing downstream could draw them, clash them or count
them truthfully.

This module routes them. Every run is an orthogonal polyline in the
building's own coordinates (drainage additionally falls at its gradient
along those plan-orthogonal legs), at the height services actually
occupy — the floor void for distribution, the ceiling void for lighting,
a riser at the stack — so the lengths are measured off a route rather
than guessed from a per-item average, and a viewer or an IFC export has
something to carry. Routes are kept inside the room-covered plan, not
merely the bounding box — on an L-shaped plan those differ by a notch of
open air — and where no orthogonal corner can stay inside, the run says
so on its note instead of pretending.

WHAT THIS IS NOT. These are DESIGN routes, not an installer's first fix.
They are orthogonal, they take the sensible leg order, and they do not
yet know where the joists run, so they cannot claim clash-free
coordination — that needs a structural model of the floor and is the next
piece of work, flagged in the report rather than glossed over. What they
are is buildable, measurable, and honest about which is which.
"""
import math

# Where services live, relative to each storey's finished floor level.
FLOOR_VOID_M = 0.08         # distribution below the floor finish
CEILING_VOID_M = 0.06       # lighting above the ceiling line
RAD_TAIL_M = 0.15           # radiator tails above floor
SOCKET_DROP = "vertical"    # BS 7671 522.6.202: drops are vertical

# Pipe sizes (mm) — two-pipe wet system, UK domestic convention.
PRIMARY_MM = 22             # boiler flow/return primaries
BRANCH_MM = 15              # radiator tails
SOIL_MM = 110               # soil stack and underground drain
WASTE_WC_MM = 110
WASTE_BATH_MM = 40
WASTE_BASIN_MM = 32
WASTE_FALL = 1.0 / 40.0     # 1:40, the steepest of the AD H band

# Cables.
RING_MM2 = "2.5mm2 T&E"
LIGHT_MM2 = "1.5mm2 T&E"
COOKER_MM2 = "6mm2 T&E"

WET = {"wet", "bathroom", "ensuite", "wc", "utility"}
CIRC = {"circulation", "hall", "landing", "corridor"}


def _dist(a, b):
    return math.dist(a, b)


def _length(points):
    return sum(_dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def _run(system, service, size, level, points, note=None):
    pts = [[round(p[0], 3), round(p[1], 3), round(p[2], 3)] for p in points]
    out = {"system": system, "service": service, "size": size,
           "level": level, "points": pts, "length_m": round(_length(pts), 2)}
    if note:
        out["note"] = note
    return out


# A point counts as in the building when it lies in a room, give or
# take a wall's worth of slack either side.
WALL_TOL_M = 0.35


def _room_on_level(model, r, level):
    """model3d's storey convention: storeys=None means every storey
    above base_level, an int caps the room at its own top."""
    base = int(r.get("base_level") or 0)
    n = r.get("storeys")
    total = int(model.get("storeys") or 1)
    top = total if n is None else min(base + int(n), total)
    return base <= level < top


def _inside(model, x, y, level=None):
    """Is (x, y) actually in the building on this level?

    The first cut tested the extent bounding box, which on an L-shaped
    plan approves the notch — open air — so routes were drawn through
    it. The building is the rooms, not the box around them: a point is
    inside only when some room on the level covers it (within a wall's
    tolerance). level=None means any level will do.
    """
    for r in model["rooms"]:
        if level is not None and not _room_on_level(model, r, level):
            continue
        if (r["x"] - WALL_TOL_M <= x <= r["x"] + r["width_m"] + WALL_TOL_M
                and r["y"] - WALL_TOL_M <= y <= r["y"] + r["depth_m"]
                + WALL_TOL_M):
            return True
    return False


def _leg(model, a, b, z, level=None):
    """Two-leg orthogonal route from a to b at height z.

    Takes whichever leg order keeps the corner inside the building; a
    service that leaves the envelope and comes back is not a route.
    Returns (points, warning): when NEITHER corner lands in a room there
    is no honest two-leg route, and rather than silently drawing one
    through open air (which this once did) the route is emitted with a
    warning the caller must carry on the run.
    """
    (ax, ay), (bx, by) = a, b
    c1, c2 = (bx, ay), (ax, by)
    warn = None
    if _inside(model, c1[0], c1[1], level):
        corner = c1
    elif _inside(model, c2[0], c2[1], level):
        corner = c2
    else:
        corner = c1
        warn = ("ROUTE LEAVES THE BUILDING: neither orthogonal corner "
                "lands in a room on this level")
    pts = [(ax, ay, z)]
    if abs(corner[0] - ax) > 1e-6 or abs(corner[1] - ay) > 1e-6:
        pts.append((corner[0], corner[1], z))
    pts.append((bx, by, z))
    return pts, warn


def _note(base, warn):
    return f"{base} — {warn}" if warn else base


def _rooms_of_kind(model, kinds, level=None):
    out = []
    for r in model["rooms"]:
        if r.get("kind") not in kinds:
            continue
        if level is not None and int(r.get("base_level") or 0) != level:
            continue
        out.append(r)
    return out


def _centre(r):
    return (r["x"] + r["width_m"] / 2.0, r["y"] + r["depth_m"] / 2.0)


def plant(model):
    """Where the boiler goes: utility if there is one, else the kitchen.

    Against an external wall, because a combi needs a flue — and
    "external" means the room face actually sits on the envelope. This
    once tested only the left and back faces, so a room touching
    neither got its boiler on an internal partition while the record
    still implied a flue could go there. All four faces are checked
    now, and when none reaches the extent the boiler is still placed
    but the record says the flue is unresolved instead of pretending.
    """
    for kinds in (("wet",), ("kitchen",)):
        for r in _rooms_of_kind(model, kinds, level=0):
            name = (r.get("name") or "").lower()
            if kinds == ("wet",) and not name.startswith("util"):
                continue
            ex = model["extent_m"]
            x0, x1 = r["x"], r["x"] + r["width_m"]
            y0, y1 = r["y"], r["y"] + r["depth_m"]
            cx, cy = _centre(r)
            faces = []
            if abs(x0 - ex["x"][0]) < WALL_TOL_M:
                faces.append((x0 + 0.35, cy))
            if abs(x1 - ex["x"][1]) < WALL_TOL_M:
                faces.append((x1 - 0.35, cy))
            if abs(y1 - ex["y"][1]) < WALL_TOL_M:
                faces.append((cx, y1 - 0.35))
            if abs(y0 - ex["y"][0]) < WALL_TOL_M:
                faces.append((cx, y0 + 0.35))
            out = {"type": "boiler", "kind": "combi", "room": r["name"],
                   "z": 1.5, "level": 0}
            if faces:
                bx, by = faces[0]
            else:
                bx, by = x1 - 0.35, cy
                out["note"] = ("no external wall: room touches no face of "
                               "the envelope, flue position unresolved")
            out["x"], out["y"] = round(bx, 3), round(by, 3)
            return out
    return None


def stack_position(model):
    """The soil stack: at the wet rooms, on an external wall where it can
    be a vent pipe. Wet rooms stacked over each other is the whole reason
    plans put them there."""
    wets = [r for r in model["rooms"] if r.get("kind") in WET]
    if not wets:
        return None
    ex, ey = model["extent_m"]["x"], model["extent_m"]["y"]
    best, score = None, None
    for r in wets:
        cx, cy = _centre(r)
        # distance to the nearest external wall — small is good
        d = min(abs(cx - ex[0]), abs(ex[1] - cx),
                abs(cy - ey[0]), abs(ey[1] - cy))
        # prefer upstairs wet rooms: the stack must reach the highest one
        lv = int(r.get("base_level") or 0)
        s = d - lv * 0.5
        if score is None or s < score:
            best, score = r, s
    cx, cy = _centre(best)
    # push to the nearest external face
    if min(abs(cx - ex[0]), abs(ex[1] - cx)) <= min(abs(cy - ey[0]),
                                                    abs(ey[1] - cy)):
        cx = ex[0] + 0.2 if abs(cx - ex[0]) < abs(ex[1] - cx) else ex[1] - 0.2
    else:
        cy = ey[0] + 0.2 if abs(cy - ey[0]) < abs(ey[1] - cy) else ey[1] - 0.2
    return {"room": best["name"], "x": round(cx, 3), "y": round(cy, 3)}


def heating(model, heat, boiler=None):
    """Wet system routed RADIALLY: a 15mm flow and return from the plant
    (via the riser upstairs) to each radiator the heat design sized.

    That is a manifold layout — standard in new build with a plant
    cupboard — and it is what the geometry here actually describes, so it
    is what the report says. A spine-and-branch layout, where one pair of
    primaries loops the building and radiators tee off it, uses
    materially less pipe; when materials matter more than balancing, that
    is the cheaper design and this module does not yet draw it.
    """
    if not heat:
        return []
    boiler = boiler or plant(model)
    if not boiler:
        return []
    per = float(model.get("storey_height_m") or 2.4)
    storeys = int(model.get("storeys") or 1)
    runs = []
    src = (boiler["x"], boiler["y"])

    riser_at = stack_position(model) or {"x": src[0], "y": src[1]}
    if storeys > 1:
        z0 = -FLOOR_VOID_M
        z1 = (storeys - 1) * per - FLOOR_VOID_M
        for svc in ("flow", "return"):
            runs.append(_run("heating", svc, f"{PRIMARY_MM}mm copper", None,
                             [(riser_at["x"], riser_at["y"], z0),
                              (riser_at["x"], riser_at["y"], z1)],
                             "riser to the upper storey"))
        for svc in ("flow", "return"):
            pts, warn = _leg(model, src, (riser_at["x"], riser_at["y"]),
                             -FLOOR_VOID_M, level=0)
            runs.append(_run("heating", svc, f"{PRIMARY_MM}mm copper", 0,
                             pts, _note("boiler to riser", warn)))

    for hr in heat.get("rooms", []):
        # A big bathroom carries TWO emitters — the towel rail plus the
        # panel sized for the balance — and each needs its own pair of
        # tails, or the bill under-counts the copper the plumber lays.
        for rad in (hr.get("radiator"), hr.get("towel_rail")):
            if not rad:
                continue
            kind = ("towel rail" if rad.get("type") == "towel"
                    else "radiator")
            lv = int(rad.get("level") or 0)
            z = lv * per - FLOOR_VOID_M
            origin = src if lv == 0 else (riser_at["x"], riser_at["y"])
            target = (rad["x"], rad["y"])
            for svc, off in (("flow", -0.05), ("return", 0.05)):
                pts, warn = _leg(model, origin, target, z, level=lv)
                # rise to the radiator tails: jog the 50mm flow/return
                # offset horizontally in the void FIRST, then rise
                # vertically — done as one move this was a diagonal, which
                # broke the promise that every run is orthogonal
                pts.append((target[0] + off, target[1], z))
                pts.append((target[0] + off, target[1],
                            lv * per + RAD_TAIL_M))
                runs.append(_run("heating", svc, f"{BRANCH_MM}mm copper",
                                 lv, pts,
                                 _note(f"to {hr['name']} {kind} "
                                       f"({rad.get('output_W')} W)", warn)))
    return runs


def power(model, elec):
    """Ring finals in the floor void with vertical drops to each outlet,
    lighting circuits in the ceiling void, and a cooker radial."""
    if not elec:
        return []
    cu = elec.get("consumer_unit")
    if not cu:
        return []
    per = float(model.get("storey_height_m") or 2.4)
    runs = []
    src = (cu["x"], cu["y"])

    by_level = {}
    for r in elec.get("rooms", []):
        by_level.setdefault(int(r["level"]), []).extend(
            [(s, r) for s in r.get("placed", [])])

    for lv, sockets in sorted(by_level.items()):
        if not sockets:
            continue
        z = lv * per - FLOOR_VOID_M
        # the ring: CU -> each outlet in plan order -> back to the CU
        order = sorted(sockets, key=lambda sr: (sr[0]["y"], sr[0]["x"]))
        node = src if lv == 0 else (cu["x"], cu["y"])
        if lv > 0:                       # riser to the upper floor ring
            runs.append(_run("power", "ring final riser", RING_MM2, None,
                             [(src[0], src[1], -FLOOR_VOID_M),
                              (src[0], src[1], z)],
                             f"consumer unit to level {lv}"))
        for s, room in order:
            pts, warn = _leg(model, node, (s["x"], s["y"]), z, level=lv)
            # THE SAFE ZONE: the last leg to an accessory is a vertical
            # drop/rise in line with it (BS 7671 522.6.202)
            pts.append((s["x"], s["y"], lv * per + s.get("h", 0.45)))
            runs.append(_run("power", "ring final", RING_MM2, lv, pts,
                             _note(f"{room['name']} outlet", warn)))
            node = (s["x"], s["y"])
        pts, warn = _leg(model, node, (src[0], src[1]), z, level=lv)
        runs.append(_run("power", "ring final", RING_MM2, lv, pts,
                         _note("ring returns to the consumer unit", warn)))
        if lv > 0:
            # a ring is TWO legs at the consumer unit. The outgoing
            # riser above fed the ring up; the return must come back
            # down, or the measured copper is a storey short and the
            # routed "ring" is a single-leg radial.
            runs.append(_run("power", "ring final riser", RING_MM2, None,
                             [(src[0], src[1], z),
                              (src[0], src[1], -FLOOR_VOID_M)],
                             f"level {lv} ring returns to the "
                             "consumer unit"))

    # lighting: one pendant per room, fed in the ceiling void
    storeys = int(model.get("storeys") or 1)
    for lv in range(storeys):
        z = lv * per + per - CEILING_VOID_M
        rooms_here = [r for r in model["rooms"]
                      if int(r.get("base_level") or 0) == lv
                      and r.get("kind") != "garage"]
        if not rooms_here:
            continue
        if lv > 0:
            # the upper lighting circuit starts at the consumer unit,
            # which lives at level 0 — without this riser the circuit
            # dangled unfed in the upper ceiling void and its vertical
            # run was never counted, unlike the ring finals which
            # always drew theirs.
            runs.append(_run("power", "lighting riser", LIGHT_MM2, None,
                             [(src[0], src[1], -FLOOR_VOID_M),
                              (src[0], src[1], z)],
                             f"consumer unit to level {lv} lighting"))
        node = (src[0], src[1])
        for r in rooms_here:
            c = _centre(r)
            pts, warn = _leg(model, node, c, z, level=lv)
            runs.append(_run("power", "lighting", LIGHT_MM2, lv, pts,
                             _note(f"{r['name']} pendant", warn)))
            node = c
    for r in _rooms_of_kind(model, ("kitchen",), level=0):
        c = _centre(r)
        pts, warn = _leg(model, src, c, -FLOOR_VOID_M, level=0)
        runs.append(_run("power", "cooker radial", COOKER_MM2, 0, pts,
                         _note("45A cooker point", warn)))
    return runs


def drainage(model):
    """Soil stack, waste branches at fall, and the drain to the boundary."""
    stack = stack_position(model)
    if not stack:
        return [], None
    per = float(model.get("storey_height_m") or 2.4)
    storeys = int(model.get("storeys") or 1)
    runs = []
    top = (storeys - 1) * per + per + 0.9      # vent above the eaves line
    runs.append(_run("drainage", "soil stack", f"{SOIL_MM}mm PVCu", None,
                     [(stack["x"], stack["y"], -0.6),
                      (stack["x"], stack["y"], top)],
                     "ventilated stack, terminating above the roof"))

    for r in model["rooms"]:
        if r.get("kind") not in WET:
            continue
        lv = int(r.get("base_level") or 0)
        name = (r.get("name") or "").lower()
        c = _centre(r)
        if name.startswith("util"):
            fittings = [("waste", WASTE_BASIN_MM)]
        elif name.startswith("wc"):
            fittings = [("soil", WASTE_WC_MM), ("waste", WASTE_BASIN_MM)]
        elif name.startswith("ensuite"):
            fittings = [("soil", WASTE_WC_MM), ("waste", WASTE_BATH_MM)]
        else:
            fittings = [("soil", WASTE_WC_MM), ("waste", WASTE_BATH_MM),
                        ("waste", WASTE_BASIN_MM)]
        for svc, size in fittings:
            z_start = lv * per + 0.15
            pts, warn = _leg(model, c, (stack["x"], stack["y"]), z_start,
                             level=lv)
            # fall to the stack: 1:40 along the WHOLE route, not just
            # the last point. Dropping only the end left the leg round
            # the corner dead level, and a level waste pipe does not
            # drain — every segment now falls at the stated gradient.
            fell, cum = [pts[0]], 0.0
            for prev, p in zip(pts, pts[1:]):
                cum += _dist((prev[0], prev[1]), (p[0], p[1]))
                fell.append((p[0], p[1], z_start - cum * WASTE_FALL))
            runs.append(_run("drainage", svc, f"{size}mm PVCu", lv, fell,
                             _note(f"{r['name']} at 1:40 fall", warn)))

    ey = model["extent_m"]["y"]
    # the drop is computed from the routed length, because a fixed
    # 0.3m drop labelled "1:40 min" went shallower than 1:40 as soon
    # as the run passed 12m — the geometry must match its own label
    drain_len = (ey[1] + 4.0) - stack["y"]
    runs.append(_run("drainage", "underground drain", f"{SOIL_MM}mm", None,
                     [(stack["x"], stack["y"], -0.6),
                      (stack["x"], ey[1] + 4.0,
                       -0.6 - drain_len * WASTE_FALL)],
                     "stack base to the boundary connection, at 1:40"))
    return runs, stack


def design(model, heat=None, elec=None, vent=None):
    """Route the lot; returns runs, terminals and honest totals."""
    heat = heat if heat is not None else model.get("heat")
    elec = elec if elec is not None else model.get("elec")
    vent = vent if vent is not None else model.get("vent")

    boiler = plant(model)
    runs = []
    runs += heating(model, heat, boiler)
    runs += power(model, elec)
    drain_runs, stack = drainage(model)
    runs += drain_runs

    totals = {}
    for r in runs:
        key = f"{r['system']}:{r['size']}"
        totals[key] = round(totals.get(key, 0.0) + r["length_m"], 2)

    terminals = []
    if boiler:
        terminals.append(boiler)
    if stack:
        terminals.append({"type": "soil stack", **stack})
    for hr in (heat or {}).get("rooms", []):
        for key, tname in (("radiator", "radiator"),
                           ("towel_rail", "towel rail")):
            e = hr.get(key)
            if e:
                terminals.append({"type": tname, "room": hr["name"],
                                  "level": e["level"], "x": e["x"],
                                  "y": e["y"],
                                  "output_W": e["output_W"]})
    for f in (vent or {}).get("extract_fans", []):
        terminals.append({"type": "extract fan", "room": f["name"],
                          "level": f["level"], "x": f["x"], "y": f["y"],
                          "extract_ls": f["extract_ls"]})
    for a in (elec or {}).get("alarms", []):
        terminals.append({"type": f"{a['type']} alarm", "room": a["name"],
                          "level": a["level"], "x": a["x"], "y": a["y"]})
    if elec and elec.get("consumer_unit"):
        terminals.append({"type": "consumer unit",
                          **elec["consumer_unit"], "level": 0})

    return {
        "runs": runs,
        "terminals": terminals,
        "totals_m": totals,
        "counts": {"runs": len(runs), "terminals": len(terminals)},
        "notes": [
            "Routes are orthogonal DESIGN runs at service-void level "
            f"({FLOOR_VOID_M * 1000:.0f}mm below floor finish, "
            f"{CEILING_VOID_M * 1000:.0f}mm above the ceiling line), not an "
            "installer's first fix.",
            "Cable drops to accessories are vertical, in the BS 7671 "
            "522.6.202 safe zone.",
            "Waste branches fall 1:40 toward the stack.",
            "Heating is drawn RADIALLY (a pair per radiator from the "
            "plant, i.e. a manifold system). A spine-and-branch layout "
            "would use materially less pipe.",
            "NOT CLASH-CHECKED against joists or trusses — the model does "
            "not carry a structural floor yet. Coordination is the next "
            "piece of work, not a claim this makes.",
        ],
    }


def describe(d):
    lines = [f"{d['counts']['runs']} routed runs, "
             f"{d['counts']['terminals']} terminals"]
    for k in sorted(d["totals_m"]):
        lines.append(f"  {k:<34} {d['totals_m'][k]:>8.2f} m")
    lines += ["  " + n for n in d["notes"]]
    return "\n".join(lines)
