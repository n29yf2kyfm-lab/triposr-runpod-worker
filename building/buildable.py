"""Is this plan actually buildable, or does it just close geometrically?

WHY THIS EXISTS. model3d will happily build a house with no staircase in it.
It did: a four-bed detached, 178.5 m2, two floors, roof, elevations, IFC,
GLB, a take-off — and the hall and the landing overlapped by 0.10 m2, so no
flight could ever reach the first floor. Two of the four bedrooms had 600mm
and 0mm of wall onto the landing, which is to say no door. The kitchen and
the hall met at a single point. None of that is a geometry error; every
rectangle closed. It is a DESIGN error, and nothing in the pipeline looked
for it.

So this module asks the questions a building control officer asks on the
first pass, in the order they ask them, and answers each with the number
that fails rather than an opinion:

  * can a compliant private stair physically fit, and does it arrive
    somewhere you are allowed to arrive?
  * can you get from the front door to every room without walking through
    a bedroom, and without an inner room off a kitchen?
  * can you get out of every first-floor bedroom through a window?
  * is there so much glass that the house overheats?

WHAT IT WILL NOT DO. It will not approve anything. A clean run here means
"none of the things that get plans rejected on sight are present", not
"this complies" — F, L, drainage, structure and a dozen other things are
outside it and stay outside it. Every finding names its Approved Document
so the builder can go and read the clause rather than take this on trust.

Pure: no network, no GPU, stdlib only.
"""
import math

# --- what a door needs ------------------------------------------------------
# An 838mm leaf in a lined opening wants about 940mm of structural wall.
# Part M wants 775mm CLEAR through it, which an 838 leaf gives with about
# 50mm to spare. Below 940mm of shared wall there is no doorway, and a room
# with no doorway is not a room.
DOOR_LEAF_M = 0.838
DOOR_STRUCTURAL_M = 0.94
PART_M_CLEAR_M = 0.775

# --- Part K, private stair --------------------------------------------------
MAX_RISE_M = 0.220
MIN_GOING_M = 0.220
MAX_PITCH_DEG = 42.0
MIN_2R_G_M, MAX_2R_G_M = 0.550, 0.700
STAIR_WIDTH_M = 0.900          # not a regulation minimum, but what is built
HEADROOM_M = 2.000

# --- Part B, escape through a window ---------------------------------------
ESCAPE_MIN_AREA_M2 = 0.33
ESCAPE_MIN_CLEAR_M = 0.450
ESCAPE_MAX_SILL_M = 1.100
ESCAPE_STOREY_LIMIT_M = 4.500  # above this a window is not an escape route

# --- Part O, simplified method, moderate risk, cross-ventilated -------------
# Glazing as a percentage of floor area, by the orientation of the most
# glazed facade. West is the tight one because the sun is low and in your
# face all afternoon.
OVERHEAT_LIMIT_PCT = {"N": 18.0, "E": 18.0, "S": 15.0, "W": 11.0}

HABITABLE = {"room", "bedroom", "living", "kitchen", "dining", "study",
             "office"}
CIRCULATION = {"circulation", "hall", "landing", "corridor"}
WET = {"wet", "bathroom", "ensuite", "wc", "utility"}


def _rect(r):
    return (r["x"], r["y"], r["x"] + r["width_m"], r["y"] + r["depth_m"])


def _level_span(r, storeys):
    base = r.get("base_level") or 0
    n = r.get("storeys")
    return base, (storeys if n is None else base + int(n))


def _on_level(r, level, storeys):
    lo, hi = _level_span(r, storeys)
    return lo <= level < hi


def shared_wall_m(a, b):
    """How much wall two rooms actually have in common, in metres.

    Zero means they touch at a corner or not at all — and two rooms that
    meet at a point cannot have a door between them however adjacent they
    look on the drawing. This is the measurement the whole circulation
    check rests on.
    """
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    # vertical party line
    for ax, bx in ((ax0, bx1), (ax1, bx0)):
        if abs(ax - bx) < 1e-6:
            lo, hi = max(ay0, by0), min(ay1, by1)
            if hi - lo > 1e-6:
                return hi - lo
    # horizontal party line
    for ay, by in ((ay0, by1), (ay1, by0)):
        if abs(ay - by) < 1e-6:
            lo, hi = max(ax0, bx0), min(ax1, bx1)
            if hi - lo > 1e-6:
                return hi - lo
    return 0.0


def adjacency(rooms, storeys, level):
    """Room-to-room shared wall lengths on one level."""
    on = [r for r in rooms if _on_level(r, level, storeys)]
    out = {}
    for i, a in enumerate(on):
        for b in on[i + 1:]:
            m = shared_wall_m(a, b)
            if m > 1e-6:
                out[(a["name"], b["name"])] = round(m, 3)
    return out


def _finding(code, severity, message, number=None, fix=None, ref=None,
             room=None):
    return {"code": code, "severity": severity, "message": message,
            "number": number, "fix": fix, "ref": ref, "room": room}


# --- the staircase ----------------------------------------------------------

def stair_geometry(storey_height_m):
    """The flight a 2.70m storey actually needs, or why it cannot have one.

    Part K bounds a private stair four ways at once and they fight: a rise
    that satisfies the 220mm cap can still break the 42 degree pitch, and a
    going that fixes the pitch can break the 2R+G rule at the other end. The
    arithmetic below finds the SHORTEST flight that satisfies all four, so
    "it does not fit" means it genuinely does not fit rather than that the
    first guess was unlucky.
    """
    h = float(storey_height_m)
    risers = max(2, int(math.ceil(h / MAX_RISE_M - 1e-9)))
    for n in range(risers, risers + 6):
        rise = h / n
        if rise > MAX_RISE_M + 1e-9:
            continue
        # pitch <= 42 degrees sets a floor under the going
        g_pitch = rise / math.tan(math.radians(MAX_PITCH_DEG))
        lo = max(MIN_GOING_M, g_pitch, MIN_2R_G_M - 2 * rise)
        hi = MAX_2R_G_M - 2 * rise
        if lo - hi > 1e-9:
            continue                      # the four rules have no overlap
        going = lo
        return {"risers": n, "rise_m": round(rise, 4),
                "going_m": round(going, 4),
                "pitch_deg": round(math.degrees(math.atan(rise / going)), 2),
                "two_r_plus_g_m": round(2 * rise + going, 4),
                "flight_m": round((n - 1) * going, 3),
                "width_m": STAIR_WIDTH_M,
                # Below 2.0m headroom you are into the ceiling above, so the
                # trimmed opening has to start this far along the flight.
                "void_starts_m": round(
                    max(0.0, (storey_height_m - HEADROOM_M) / rise) * going, 3)}
    return None


def fit_stair(rooms, storeys, storey_height_m, level=0):
    """Put the flight somewhere real, and check what it arrives in.

    Returns (stair, findings). `stair` is None when nothing fits.
    """
    geo = stair_geometry(storey_height_m)
    findings = []
    if geo is None:
        return None, [_finding(
            "K-GEOM", "refuse",
            f"No private stair satisfies Part K at a {storey_height_m:.2f}m "
            f"floor-to-floor: the rise, going, pitch and 2R+G limits have no "
            f"overlap.", number=f"{storey_height_m:.2f}m",
            fix="Change the floor-to-floor height.",
            ref="AD K Table 1.1")]

    need = geo["flight_m"] + STAIR_WIDTH_M     # flight plus a top landing
    below = [r for r in rooms
             if _on_level(r, level, storeys) and r.get("kind") in CIRCULATION]
    above = [r for r in rooms
             if _on_level(r, level + 1, storeys)
             and r.get("kind") in CIRCULATION]

    if not below:
        findings.append(_finding(
            "K-NOHALL", "refuse",
            "There is no circulation space on the entrance storey for a "
            "stair to rise from.",
            fix="Give the plan a hall.", ref="AD K Section 1"))
        return None, findings

    best = None
    for room in below:
        x0, y0, x1, y1 = _rect(room)
        w, d = x1 - x0, y1 - y0
        for axis in ("y", "x"):
            run = d if axis == "y" else w
            across = w if axis == "y" else d
            if run + 1e-9 < need or across + 1e-9 < STAIR_WIDTH_M:
                continue
            # Flight against the low edge, landing at the head.
            if axis == "y":
                head = (x0 + STAIR_WIDTH_M / 2.0, y0 + geo["flight_m"])
                foot = (x0 + STAIR_WIDTH_M / 2.0, y0)
            else:
                head = (x0 + geo["flight_m"], y0 + STAIR_WIDTH_M / 2.0)
                foot = (x0, y0 + STAIR_WIDTH_M / 2.0)
            cand = {"in_room": room["name"], "axis": axis,
                    "foot": [round(v, 3) for v in foot],
                    "head": [round(v, 3) for v in head],
                    "spare_m": round(run - need, 3), **geo}
            if best is None or cand["spare_m"] > best["spare_m"]:
                best = cand

    if best is None:
        room = max(below, key=lambda r: r["width_m"] * r["depth_m"])
        findings.append(_finding(
            "K-FIT", "refuse",
            f"A compliant flight is {geo['flight_m']:.2f}m plus a "
            f"{STAIR_WIDTH_M:.2f}m landing = {need:.2f}m, and the largest "
            f"circulation space ({room['name']}, "
            f"{room['width_m']:.2f} x {room['depth_m']:.2f}m) cannot take it "
            f"in either direction.",
            number=f"{need:.2f}m needed",
            fix="Lengthen the hall, or turn the flight with a half-landing.",
            ref="AD K Table 1.1, para 1.22", room=room["name"]))
        return None, findings

    # THE FLIGHT HAS TO ARRIVE SOMEWHERE YOU ARE ALLOWED TO ARRIVE. This is
    # the check nothing in the pipeline was doing, and it is the one that
    # caught a stair landing in the family bathroom.
    hx, hy = best["head"]
    landed = None
    for r in above:
        x0, y0, x1, y1 = _rect(r)
        if x0 - 1e-6 <= hx <= x1 + 1e-6 and y0 - 1e-6 <= hy <= y1 + 1e-6:
            landed = r
            break
    if landed is None:
        arrived_in = [r["name"] for r in rooms
                      if _on_level(r, level + 1, storeys)
                      and _rect(r)[0] - 1e-6 <= hx <= _rect(r)[2] + 1e-6
                      and _rect(r)[1] - 1e-6 <= hy <= _rect(r)[3] + 1e-6]
        findings.append(_finding(
            "K-LANDING", "refuse",
            f"The flight fits in the {best['in_room']} but arrives at "
            f"({hx:.2f}, {hy:.2f}) — which on the floor above is "
            + (f"the {arrived_in[0]}" if arrived_in else "not a room at all")
            + ". A stair has to come up into circulation.",
            number=f"head at ({hx:.2f}, {hy:.2f})",
            fix="Move the landing over the hall, or move the hall under the "
                "landing. This is a floor replan, not an edit.",
            ref="AD K Section 1; AD B Vol 1 Section 2",
            room=best["in_room"]))
        best["lands_in"] = arrived_in[0] if arrived_in else None
        return best, findings

    best["lands_in"] = landed["name"]
    return best, findings


# --- circulation ------------------------------------------------------------

def circulation(rooms, storeys, level):
    """Which rooms you can reach, and which you have to walk through.

    An INNER ROOM is one you can only reach through another room. Part B
    tolerates one — a kitchen off a lounge is everywhere — but an inner room
    off an inner room is a refusal, and so is any inner room whose only
    access is through a KITCHEN, because that is where the fire starts.
    """
    on = [r for r in rooms if _on_level(r, level, storeys)]
    by_name = {r["name"]: r for r in on}
    links = {r["name"]: set() for r in on}
    for i, a in enumerate(on):
        for b in on[i + 1:]:
            if shared_wall_m(a, b) + 1e-9 >= DOOR_STRUCTURAL_M:
                links[a["name"]].add(b["name"])
                links[b["name"]].add(a["name"])

    circ = [r["name"] for r in on if r.get("kind") in CIRCULATION]
    findings = []
    if not circ:
        return links, [_finding(
            "CIRC-NONE", "refuse",
            f"Level {level} has no circulation space at all.",
            fix="Add a hall or landing.", ref="AD B Vol 1 Section 2")]

    # YOU DO NOT WALK THROUGH A TOILET TO REACH THE STUDY. A wet room or a
    # garage can be entered but is not a route to anywhere else, and letting
    # the search pass through them made a study buried behind a WC, a garage
    # and a utility look two rooms deep and merely awkward. Only circulation
    # and habitable rooms carry access onward.
    def passable(name):
        k = by_name[name].get("kind")
        return k in CIRCULATION or k in HABITABLE

    depth = {n: 0 for n in circ}
    queue = list(circ)
    while queue:
        n = queue.pop(0)
        if not passable(n) and depth[n] > 0:
            continue
        for m in links[n]:
            if m not in depth:
                depth[m] = depth[n] + 1
                queue.append(m)

    for r in on:
        name = r["name"]
        kind = r.get("kind")
        if name not in depth:
            best = max((shared_wall_m(r, o) for o in on if o is not r),
                       default=0.0)
            if best + 1e-9 < DOOR_STRUCTURAL_M:
                findings.append(_finding(
                    "CIRC-ISLAND", "refuse",
                    f"{name} cannot be entered from anywhere: its longest "
                    f"shared wall with any room is {best:.2f}m, and a doorway "
                    f"needs {DOOR_STRUCTURAL_M:.2f}m.",
                    number=f"{best:.2f}m", room=name,
                    fix="Move a partition so the room presents a full doorway "
                        "to circulation.",
                    ref="AD M Vol 1 para 1.15"))
            else:
                behind = sorted(m for m in links[name] if not passable(m))
                findings.append(_finding(
                    "CIRC-DEADEND", "refuse",
                    f"{name} can only be entered through "
                    f"{', '.join(behind) or 'nothing'} — a wet room or a "
                    f"garage, which is not a route through a house.",
                    number=f"{best:.2f}m of wall, all of it behind "
                           f"{', '.join(behind)}",
                    room=name,
                    fix="Run circulation to it.",
                    ref="AD B Vol 1 para 2.12; AD M Vol 1 para 1.15"))
            continue
        d = depth[name]
        if d >= 2 and kind in HABITABLE:
            # what you walk through to get here
            via = [m for m in links[name] if depth.get(m, 99) == d - 1]
            through_kitchen = any(
                by_name[m].get("kind") in ("kitchen",)
                or "kitchen" in m.lower() for m in via)
            if d >= 3 or through_kitchen:
                findings.append(_finding(
                    "CIRC-INNER2", "refuse",
                    f"{name} is {d} rooms deep from circulation"
                    + (", and the way in is through a kitchen" if
                       through_kitchen else "")
                    + f" (via {', '.join(via) or 'nothing'}).",
                    number=f"depth {d}", room=name,
                    fix="Run circulation to it.",
                    ref="AD B Vol 1 para 2.12"))
            else:
                findings.append(_finding(
                    "CIRC-INNER", "change",
                    f"{name} is an inner room — reached only through "
                    f"{', '.join(via)}.",
                    number=f"depth {d}", room=name,
                    fix="Acceptable under AD B 2.11 with an escape window, "
                        "but it will not sell.",
                    ref="AD B Vol 1 para 2.11"))

    # A BEDROOM ENTERED THROUGH A BEDROOM IS NOT A BEDROOM.
    for r in on:
        name, kind = r["name"], r.get("kind")
        if kind not in HABITABLE or not name.lower().startswith(
                ("bed", "master")):
            continue
        onto = max((shared_wall_m(r, by_name[c]) for c in circ), default=0.0)
        if onto + 1e-9 < DOOR_STRUCTURAL_M:
            findings.append(_finding(
                "M-NODOOR", "refuse",
                f"{name} has {onto:.2f}m of wall onto circulation. A doorway "
                f"needs {DOOR_STRUCTURAL_M:.2f}m, so as drawn it is entered "
                f"through another room.",
                number=f"{onto:.2f}m", room=name,
                fix="Move the partition to give it a full doorway.",
                ref="AD M Vol 1 para 1.15, Table 1.1"))
    return links, findings


# --- escape and overheating -------------------------------------------------

def _openings_of(model, room, level):
    """Windows in the external walls that bound this room."""
    rx0, ry0, rx1, ry1 = _rect(room)
    out = []
    for w in model["walls"]:
        if not w["external"]:
            continue
        (ax, ay), (bx, by) = w["start"], w["end"]
        # does the wall run along one of the room's own edges?
        if abs(ax - bx) < 1e-6:
            if not (abs(ax - rx0) < 1e-6 or abs(ax - rx1) < 1e-6):
                continue
            lo, hi = max(min(ay, by), ry0), min(max(ay, by), ry1)
        elif abs(ay - by) < 1e-6:
            if not (abs(ay - ry0) < 1e-6 or abs(ay - ry1) < 1e-6):
                continue
            lo, hi = max(min(ax, bx), rx0), min(max(ax, bx), rx1)
        else:
            continue
        if hi - lo < 1e-6:
            continue
        for o in w.get("openings", []):
            if o.get("level") not in (None, level):
                continue
            # where does the opening sit along the wall, in plan?
            base = min(ax, bx) if abs(ay - by) < 1e-6 else min(ay, by)
            a0 = base + o["along"]
            if a0 + 1e-6 < lo or a0 + o["width"] - 1e-6 > hi:
                continue
            out.append(o)
    return out


def escape(model):
    """Can you get out of every bedroom above the ground floor?"""
    rooms, storeys = model["rooms"], model.get("storeys", 1)
    per = model.get("storey_height_m", 2.7)
    findings = []
    for level in range(1, storeys):
        if level * per > ESCAPE_STOREY_LIMIT_M:
            findings.append(_finding(
                "B-STOREY", "change",
                f"Level {level} is {level * per:.2f}m above ground, over the "
                f"{ESCAPE_STOREY_LIMIT_M:.1f}m limit for escape through a "
                f"window. It needs a protected stairway instead.",
                number=f"{level * per:.2f}m",
                fix="Protected stair enclosure, or lower the storey.",
                ref="AD B Vol 1 Diagram 2.1"))
            continue
        for r in rooms:
            if not _on_level(r, level, storeys):
                continue
            if not (r.get("kind") in HABITABLE
                    and r["name"].lower().startswith(("bed", "master"))):
                continue
            ok = []
            for o in _openings_of(model, r, level):
                if o["kind"] != "window":
                    continue
                sill = o.get("sill", 0.0)
                area = o["width"] * o["height"]
                if (area + 1e-9 >= ESCAPE_MIN_AREA_M2
                        and o["width"] + 1e-9 >= ESCAPE_MIN_CLEAR_M
                        and o["height"] + 1e-9 >= ESCAPE_MIN_CLEAR_M
                        and sill <= ESCAPE_MAX_SILL_M + 1e-9):
                    ok.append(o)
            if not ok:
                findings.append(_finding(
                    "B-ESCAPE", "refuse",
                    f"{r['name']} has no window that can be escaped through: "
                    f"needs {ESCAPE_MIN_AREA_M2} m2 clear, "
                    f"{ESCAPE_MIN_CLEAR_M * 1000:.0f}mm in both directions, "
                    f"sill under {ESCAPE_MAX_SILL_M * 1000:.0f}mm.",
                    room=r["name"],
                    fix="Enlarge a window or drop its sill.",
                    ref="AD B Vol 1 para 2.10"))
    return findings


def overheating(model, orientation="N"):
    """Part O, simplified method — is there simply too much glass?

    Orientation of the most glazed facade decides the limit, and nobody
    knows it until there is a site. Defaulting to North gives the most
    generous limit there is, so a failure here fails on ANY orientation.
    """
    # A REPEATED-PLATE WINDOW EXISTS ON EVERY STOREY IT REPEATS ON. Openings
    # with level=None were counted once while the floor area below counted
    # every storey, understating glazing by the storey count — a 24% house
    # read as 12% and sailed through. Multiply by the same storey span the
    # wall-area figures use. Walls facing a cavity (void_facing) are not
    # facades and carry no glazing worth counting.
    storeys = model.get("storeys", 1)

    def _wall_levels(w):
        base = w.get("base_level") or 0
        n = w.get("storeys")
        top = storeys if n is None else min(base + int(n), storeys)
        return max(0, top - base)

    glazed = sum(o["width"] * o["height"]
                 * (_wall_levels(w) if o.get("level") is None else 1)
                 for w in model["walls"]
                 if w["external"] and not w.get("void_facing")
                 for o in w.get("openings", []) if o["kind"] == "window")
    floor = model["totals"]["floor_area_m2"]
    if floor <= 0:
        return []
    pct = 100.0 * glazed / floor
    limit = OVERHEAT_LIMIT_PCT.get(orientation, 18.0)
    if pct <= limit + 1e-9:
        return []
    worst = min(OVERHEAT_LIMIT_PCT.values())
    sev = "refuse" if pct > max(OVERHEAT_LIMIT_PCT.values()) else "change"
    return [_finding(
        "O-GLAZING", sev,
        f"Glazing is {pct:.1f}% of floor area against a {limit:.0f}% limit "
        f"for a {orientation}-facing facade"
        + (" — and it fails on every orientation, not just this one."
           if pct > max(OVERHEAT_LIMIT_PCT.values()) else "")
        + f" Removing {glazed - floor * limit / 100.0:.2f} m2 of glass "
          f"brings it inside.",
        number=f"{pct:.1f}% vs {limit:.0f}%",
        fix=f"Cut glazing to {floor * worst / 100.0:.1f} m2 to pass on any "
            f"orientation, or submit TM59 dynamic modelling.",
        ref="AD O Table 1.1, paras 1.6-1.7")]


# --- the whole check --------------------------------------------------------

SEVERITY_ORDER = {"refuse": 0, "change": 1, "query": 2}


def check(model, orientation="N"):
    """Everything above, in the order a plans checker works through it."""
    rooms = model["rooms"]
    storeys = model.get("storeys", 1)
    per = model.get("storey_height_m", 2.7)
    findings, stair = [], None

    if storeys > 1:
        stair, f = fit_stair(rooms, storeys, per, level=0)
        findings += f
    for level in range(storeys):
        _, f = circulation(rooms, storeys, level)
        findings += f
    findings += escape(model)
    findings += overheating(model, orientation)

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9),
                                 f["code"]))
    refusals = [f for f in findings if f["severity"] == "refuse"]
    return {
        "buildable": not refusals,
        "stair": stair,
        "findings": findings,
        "counts": {s: sum(1 for f in findings if f["severity"] == s)
                   for s in ("refuse", "change", "query")},
        "note": ("No refusals found. That is not approval — F, L, drainage, "
                 "structure and the site are outside this check."
                 if not refusals else
                 f"{len(refusals)} finding(s) that get a plan rejected on "
                 f"sight."),
    }


def describe(result):
    """One screen a builder can read before they draw anything else."""
    lines = []
    s = result.get("stair")
    if s and result.get("buildable"):
        lines.append(
            f"Stair: {s['risers']} risers at {s['rise_m'] * 1000:.0f}mm, "
            f"{s['going_m'] * 1000:.0f}mm going, {s['pitch_deg']:.1f} deg, "
            f"{s['flight_m']:.2f}m flight in the {s['in_room']} -> "
            f"{s.get('lands_in')}.")
    for f in result["findings"]:
        tag = {"refuse": "REFUSE", "change": "CHANGE", "query": "QUERY"}[
            f["severity"]]
        lines.append(f"[{tag}] {f['message']}"
                     + (f"  ({f['ref']})" if f.get("ref") else ""))
    lines.append(result["note"])
    return "\n".join(lines)
