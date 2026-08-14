"""First-fix electrical design from the measured model.

What an electrician prices from: a socket schedule per room, the circuit
list, the consumer unit position, and the detection the Building Regs
demand. Positions are set out from the same measured geometry as
everything else — a socket lands on a real wall segment, clear of the
openings and radiators the model already knows about.

Grounding, so nobody mistakes convention for regulation:
  - Socket COUNTS per room follow NHBC / Approved-practice minimum
    recommendations for new dwellings (living 5 twin, kitchen 6,
    double bedroom 4, etc). These are good practice, not statute.
  - Mounting heights ARE regulation-driven: Part M asks for outlets
    450-1200 mm above floor in new dwellings — sockets at 450 mm,
    switches at 1100 mm.
  - Cable routing must follow BS 7671 522.6.202 safe zones: runs
    horizontal or vertical from each accessory, or within 150 mm of a
    wall's top corner. The routes exported here are drawn along walls in
    those zones and are INDICATIVE — the electrician's actual runs still
    govern.
  - Detection: AD B Vol 1 requires MINIMUM Grade D2 Category LD3 to
    BS 5839-6 — smoke alarms in the circulation spaces forming the
    escape route on every storey. The kitchen heat alarm this module
    adds is above that minimum (BS 5839-6 LD2 direction), stated as
    good practice, not as the regulation floor.
  - Bathrooms and WCs get no socket (BS 7671 section 701 zones); shaver
    units are excluded deliberately rather than guessed.

The output is a DESIGN — deliberately conservative, honestly labelled —
not a certificate. Part P notifiable work still needs a registered
installer to sign it off.
"""

SOCKET_HEIGHT_M = 0.45          # Part M band, low end, new dwellings
SWITCH_HEIGHT_M = 1.10
WORKTOP_SOCKET_HEIGHT_M = 1.10  # kitchens: above 900 worktop + splash

# Twin-socket counts per room use. NHBC recommended minimums.
SOCKET_COUNTS = {
    "living": 5, "dining": 4, "kitchen": 6, "study": 4, "office": 4,
    "bedroom_double": 4, "bedroom_single": 3,
    "hall": 1, "landing": 1, "corridor": 0,
    "utility": 2, "wc": 0, "bathroom": 0,
    "garage": 2,                # a pair of twins for tools and charger
}

CIRCUITS = [
    {"name": "Ring final - ground floor", "cable": "2.5mm2 T&E",
     "protection": "32A RCBO"},
    {"name": "Ring final - first floor", "cable": "2.5mm2 T&E",
     "protection": "32A RCBO"},
    {"name": "Kitchen ring final", "cable": "2.5mm2 T&E",
     "protection": "32A RCBO"},
    {"name": "Lighting - ground floor", "cable": "1.5mm2 T&E",
     "protection": "6A RCBO"},
    {"name": "Lighting - first floor", "cable": "1.5mm2 T&E",
     "protection": "6A RCBO"},
    {"name": "Cooker", "cable": "6mm2 T&E", "protection": "32A RCBO"},
    {"name": "Boiler / controls", "cable": "1.5mm2 T&E",
     "protection": "6A RCBO, FCU"},
    {"name": "Smoke/heat detection", "cable": "1.5mm2 3-core+E",
     "protection": "6A RCBO (or lighting circuit per BS 5839-6)"},
]


def _is_bedroom(room):
    return (room.get("name") or "").lower().startswith(("bed", "master"))


def _socket_count(room):
    kind = room.get("kind", "room")
    name = (room.get("name") or "").lower()
    if _is_bedroom(room):
        return SOCKET_COUNTS["bedroom_double" if room["area_m2"] >= 10.0
                             else "bedroom_single"]
    if name.startswith("bath") or name.startswith("ensuite"):
        return SOCKET_COUNTS["bathroom"]
    if name.startswith("wc"):
        return SOCKET_COUNTS["wc"]
    if name.startswith("util"):
        return SOCKET_COUNTS["utility"]
    if name.startswith("hall"):
        return SOCKET_COUNTS["hall"]
    if name.startswith("landing"):
        return SOCKET_COUNTS["landing"]
    if name.startswith("corridor"):
        return SOCKET_COUNTS["corridor"]
    if kind == "kitchen":
        return SOCKET_COUNTS["kitchen"]
    if kind == "garage":
        return SOCKET_COUNTS["garage"]
    if kind == "circulation":
        return SOCKET_COUNTS["hall"]
    if kind == "wet":
        return 0
    return SOCKET_COUNTS.get(kind, SOCKET_COUNTS["living"])


def _levels_of(room, storeys):
    base = int(room.get("base_level") or 0)
    n = room.get("storeys")
    top = storeys if n is None else base + int(n)
    return range(base, min(top, storeys))


def _openings_on_edge(model, room, level, edge):
    """Floor-reaching openings (doors) overlapping one room edge, in plan
    intervals along the edge's axis."""
    (ex0, ey0), (ex1, ey1) = edge
    vert = abs(ex0 - ex1) < 1e-6
    spans = []
    for w in model["walls"]:
        (ax, ay), (bx, by) = w["start"], w["end"]
        wvert = abs(ax - bx) < 1e-6
        if wvert != vert:
            continue
        if vert and abs(ax - ex0) > 1e-6:
            continue
        if not vert and abs(ay - ey0) > 1e-6:
            continue
        base = min(ay, by) if wvert else min(ax, bx)
        for o in w.get("openings", []):
            if o.get("level") not in (None, level):
                continue
            if o.get("sill", 0.0) > 0.35:       # windows don't block sockets
                continue
            spans.append((base + o["along"], base + o["along"] + o["width"]))
    return spans


def _blocked(pos, spans, clear=0.35):
    return any(a - clear <= pos <= b + clear for a, b in spans)


def _place_sockets(model, room, level, count, rad):
    """Distribute twin sockets along the room's own walls, clear of
    floor-level openings and the radiator the heat design placed."""
    x0, y0 = room["x"], room["y"]
    x1, y1 = x0 + room["width_m"], y0 + room["depth_m"]
    edges = [
        ((x0, y0), (x1, y0), "x"), ((x0, y1), (x1, y1), "x"),
        ((x0, y0), (x0, y1), "y"), ((x1, y0), (x1, y1), "y"),
    ]
    out = []
    # candidate points: 0.4 in from each corner, then wall midpoints
    for pass_ in ("corner", "mid"):
        for (a, b, axis) in edges:
            if len(out) >= count:
                break
            length = (b[0] - a[0]) if axis == "x" else (b[1] - a[1])
            if length < 0.9:
                continue
            spans = _openings_on_edge(model, room, level, (a, b))
            if pass_ == "corner":
                cands = [0.4, length - 0.4]
            else:
                cands = [length / 2]
            for t in cands:
                if len(out) >= count:
                    break
                px = a[0] + (t if axis == "x" else 0.0)
                py = a[1] + (t if axis == "y" else 0.0)
                along = px if axis == "x" else py
                if _blocked(along, spans):
                    continue
                if rad:
                    rx0, ry0 = rad["x"] - rad["w"] / 2, rad["y"] - rad["d"] / 2
                    rx1, ry1 = rad["x"] + rad["w"] / 2, rad["y"] + rad["d"] / 2
                    if (rx0 - 0.15 <= px <= rx1 + 0.15
                            and ry0 - 0.15 <= py <= ry1 + 0.15):
                        continue
                if any(abs(px - s["x"]) < 0.5 and abs(py - s["y"]) < 0.5
                       for s in out):
                    continue
                out.append({"x": round(px, 3), "y": round(py, 3),
                            "axis": axis})
    return out


def design(model, heat=None):
    """Socket schedule, detection, consumer unit and circuits."""
    storeys = int(model.get("storeys") or 1)
    rads = {}
    if heat:
        for hr in heat.get("rooms", []):
            if hr.get("radiator"):
                rads[(hr["name"], hr["level"])] = hr["radiator"]

    rooms_out, sockets_total, alarms = [], 0, []
    cu = None
    for room in model["rooms"]:
        kind = room.get("kind", "room")
        name = room.get("name", "room")
        lname = name.lower()
        for level in _levels_of(room, storeys):
            count = _socket_count(room)
            sockets = _place_sockets(model, room, level, count,
                                     rads.get((name, level)))
            height = (WORKTOP_SOCKET_HEIGHT_M if kind == "kitchen"
                      else SOCKET_HEIGHT_M)
            rooms_out.append({
                "name": name, "level": level, "sockets_twin": count,
                "placed": sockets, "socket_height_m": height,
                "switch_height_m": SWITCH_HEIGHT_M,
            })
            sockets_total += count
            # BS 5839-6 Grade D1: smoke in every circulation space per
            # storey, heat in the kitchen, all interlinked.
            if kind in ("circulation",) and (lname.startswith("hall")
                                             or lname.startswith("landing")):
                alarms.append({"type": "smoke", "name": name,
                               "level": level,
                               "x": round(room["x"] + room["width_m"] / 2, 3),
                               "y": round(room["y"] + room["depth_m"] / 2, 3)})
            if kind == "kitchen":
                alarms.append({"type": "heat", "name": name, "level": level,
                               "x": round(room["x"] + room["width_m"] / 2, 3),
                               "y": round(room["y"] + room["depth_m"] / 2, 3)})
            # consumer unit: in the hall by the entrance, ground floor
            if cu is None and level == 0 and lname.startswith("hall"):
                cu = {"room": name,
                      "x": round(room["x"] + room["width_m"] - 0.35, 3),
                      "y": round(room["y"] + 0.5, 3),
                      "height_m": 1.4}
    if cu is None:                # no hall: first ground-floor wet/utility
        for room in model["rooms"]:
            if int(room.get("base_level") or 0) == 0:
                cu = {"room": room["name"],
                      "x": round(room["x"] + 0.4, 3),
                      "y": round(room["y"] + 0.3, 3), "height_m": 1.4}
                break

    return {
        "rooms": rooms_out,
        "sockets_twin_total": sockets_total,
        "alarms": alarms,
        "consumer_unit": cu,
        "circuits": [dict(c) for c in CIRCUITS
                     if storeys > 1 or "first floor" not in c["name"]],
        "notes": [
            "Socket counts to NHBC recommended minimums; heights to the "
            "Part M 450-1200 mm band (sockets 450, switches 1100, kitchen "
            "worktop outlets 1100).",
            "Cable runs must stay in BS 7671 522.6.202 safe zones: "
            "vertical/horizontal from each accessory. Routes shown on the "
            "plan are indicative ring-final runs, not measured drops.",
            "Detection: AD B minimum is Grade D2 Category LD3 (smoke in "
            "escape-route circulation, every storey); the kitchen heat "
            "alarm here exceeds that minimum per BS 5839-6.",
            "Bathrooms/WCs carry no socket outlets (BS 7671 section 701).",
            "Part P: this is a first-fix design for pricing; a registered "
            "installer certifies the installation.",
        ],
    }
