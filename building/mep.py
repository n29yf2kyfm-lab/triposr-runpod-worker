"""Every pipe and wire, ROUTED — not estimated.

The gap this closes. heatloss.py sizes and places radiators, electrics.py
places sockets and the consumer unit, ventilation.py places fans. All of
that is real design, and until now none of it was MODELLED: the pipes and
cables existed only as rules of thumb in the bill ("8 m of T&E per
socket"), and nothing downstream could draw them, clash them or count
them truthfully.

This module routes them. Every run is an orthogonal polyline in the
building's own coordinates, at the height services actually occupy — the
floor void for distribution, the ceiling void for lighting, a riser at
the stack — so the lengths are measured off a route rather than guessed
from a per-item average, and a viewer or an IFC export has something to
carry.

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


def _inside(model, x, y):
    ex, ey = model["extent_m"]["x"], model["extent_m"]["y"]
    return ex[0] - 1e-6 <= x <= ex[1] + 1e-6 and ey[0] - 1e-6 <= y <= ey[1] + 1e-6


def _leg(model, a, b, z):
    """Two-leg orthogonal route from a to b at height z.

    Takes whichever leg order keeps the corner inside the building; a
    service that leaves the envelope and comes back is not a route.
    """
    (ax, ay), (bx, by) = a, b
    c1, c2 = (bx, ay), (ax, by)
    corner = c1 if _inside(model, *c1) else (c2 if _inside(model, *c2) else c1)
    pts = [(ax, ay, z)]
    if abs(corner[0] - ax) > 1e-6 or abs(corner[1] - ay) > 1e-6:
        pts.append((corner[0], corner[1], z))
    pts.append((bx, by, z))
    return pts


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

    Against an external wall, because a combi needs a flue.
    """
    for kinds in (("wet",), ("kitchen",)):
        for r in _rooms_of_kind(model, kinds, level=0):
            name = (r.get("name") or "").lower()
            if kinds == ("wet",) and not name.startswith("util"):
                continue
            ex = model["extent_m"]
            # nearest external face of this room
            x = r["x"] + 0.35 if abs(r["x"] - ex["x"][0]) < 0.35 \
                else r["x"] + r["width_m"] - 0.35
            y = r["y"] + r["depth_m"] - 0.35 \
                if abs(r["y"] + r["depth_m"] - ex["y"][1]) < 0.35 \
                else r["y"] + 0.35
            return {"type": "boiler", "kind": "combi", "room": r["name"],
                    "x": round(x, 3), "y": round(y, 3), "z": 1.5, "level": 0}
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
        runs += [_run("heating", svc, f"{PRIMARY_MM}mm copper", 0,
                      _leg(model, src, (riser_at["x"], riser_at["y"]),
                           -FLOOR_VOID_M), "boiler to riser")
                 for svc in ("flow", "return")]

    for hr in heat.get("rooms", []):
        rad = hr.get("radiator")
        if not rad:
            continue
        lv = int(rad.get("level") or 0)
        z = lv * per - FLOOR_VOID_M
        origin = src if lv == 0 else (riser_at["x"], riser_at["y"])
        target = (rad["x"], rad["y"])
        for svc, off in (("flow", -0.05), ("return", 0.05)):
            pts = _leg(model, origin, target, z)
            # rise to the radiator tails
            pts.append((target[0] + off, target[1], lv * per + RAD_TAIL_M))
            runs.append(_run("heating", svc, f"{BRANCH_MM}mm copper", lv, pts,
                             f"to {hr['name']} radiator "
                             f"({rad.get('output_W')} W)"))
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
            pts = _leg(model, node, (s["x"], s["y"]), z)
            # THE SAFE ZONE: the last leg to an accessory is a vertical
            # drop/rise in line with it (BS 7671 522.6.202)
            pts.append((s["x"], s["y"], lv * per + s.get("h", 0.45)))
            runs.append(_run("power", "ring final", RING_MM2, lv, pts,
                             f"{room['name']} outlet"))
            node = (s["x"], s["y"])
        runs.append(_run("power", "ring final", RING_MM2, lv,
                         _leg(model, node, (src[0], src[1]), z),
                         "ring returns to the consumer unit"))

    # lighting: one pendant per room, fed in the ceiling void
    storeys = int(model.get("storeys") or 1)
    for lv in range(storeys):
        z = lv * per + per - CEILING_VOID_M
        node = (src[0], src[1])
        for r in model["rooms"]:
            if int(r.get("base_level") or 0) != lv or r.get("kind") == "garage":
                continue
            c = _centre(r)
            runs.append(_run("power", "lighting", LIGHT_MM2, lv,
                             _leg(model, node, c, z),
                             f"{r['name']} pendant"))
            node = c
    for r in _rooms_of_kind(model, ("kitchen",), level=0):
        c = _centre(r)
        runs.append(_run("power", "cooker radial", COOKER_MM2, 0,
                         _leg(model, src, c, -FLOOR_VOID_M),
                         "45A cooker point"))
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
            pts = _leg(model, c, (stack["x"], stack["y"]), z_start)
            run_len = _length([(p[0], p[1], 0) for p in pts])
            # fall to the stack: the connection sits LOWER than the fitting
            pts[-1] = (pts[-1][0], pts[-1][1], z_start - run_len * WASTE_FALL)
            runs.append(_run("drainage", svc, f"{size}mm PVCu", lv, pts,
                             f"{r['name']} at 1:40 fall"))

    ey = model["extent_m"]["y"]
    runs.append(_run("drainage", "underground drain", f"{SOIL_MM}mm", None,
                     [(stack["x"], stack["y"], -0.6),
                      (stack["x"], ey[1] + 4.0, -0.9)],
                     "stack base to the boundary connection, 1:40 min"))
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
        if hr.get("radiator"):
            terminals.append({"type": "radiator", "room": hr["name"],
                              "level": hr["radiator"]["level"],
                              "x": hr["radiator"]["x"],
                              "y": hr["radiator"]["y"],
                              "output_W": hr["radiator"]["output_W"]})
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
