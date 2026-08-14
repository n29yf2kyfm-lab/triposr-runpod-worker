"""Room-by-room heat loss and emitter sizing for the measured model.

Every number here is derived from geometry the model actually carries —
wall areas net of the openings that were placed, glazing that exists,
volumes from measured plans. Nothing is per-square-metre folklore.

The method is the standard steady-state calculation every heating
engineer's software performs (BS EN 12831 in spirit, simplified in the
ways noted below), at the design external temperature, with Part L 2021
new-build notional U-values. The output is W per room and a radiator that
would carry it, positioned under the room's largest window the way a
heating engineer would place it.

Simplifications, stated so nobody mistakes this for an SAP run:
  - internal partitions are adiabatic (both sides heated, usual practice);
  - thermal bridging is a flat 15% uplift on fabric loss (y-value method
    needs junction schedules the model does not carry);
  - ventilation loss uses fixed air-change rates per room use, not a
    blower-door result;
  - no solar or internal gains — this is the DESIGN loss, sized for a
    -3 C morning with the sun down, which is what the radiator must meet.
"""

import math

# ---------------------------------------------------------------- climate
# CIBSE design external temperature for the West Midlands. -3 C is the
# figure Birmingham heating engineers size to; coastal jobs differ.
DESIGN_EXTERNAL_C = -3.0

# Design internal temperatures, CIBSE Guide A / BS EN 12831 usage.
ROOM_TEMP_C = {
    "living": 21.0, "room": 21.0, "dining": 21.0, "study": 21.0,
    "office": 21.0, "kitchen": 18.0,
    "bedroom": 18.0,
    "bathroom": 22.0, "ensuite": 22.0, "wet": 22.0,
    "wc": 18.0, "utility": 18.0,
    "circulation": 18.0, "hall": 18.0, "landing": 18.0, "corridor": 18.0,
}

# Air change rates per hour by use — the EN 12831 minimum-ventilation
# figures customarily used for radiator sizing.
ACH = {
    "living": 0.5, "room": 0.5, "dining": 0.5, "study": 0.5, "office": 0.5,
    "kitchen": 1.5, "bathroom": 1.5, "ensuite": 1.5, "wet": 1.5,
    "wc": 1.5, "utility": 1.0,
    "circulation": 1.0, "hall": 1.0, "landing": 1.0, "corridor": 1.0,
}

# Part L 2021 (England) notional dwelling specification, W/m2K.
U_VALUES = {
    "wall": 0.18, "roof": 0.11, "floor": 0.13,
    "window": 1.2, "door": 1.0,
}

BRIDGING_UPLIFT = 1.15      # flat allowance for junction thermal bridges
AIR_HEAT_WM3K = 0.33        # volumetric heat capacity of air, W per m3K

# Radiator outputs at delta-T 50, W per metre of length, 600 mm high
# panels — mid-range catalogue figures (Stelrad/Myson class).
RAD_W_PER_M = {"K1": 1100.0, "K2": 1900.0, "K3": 2500.0}
RAD_DEPTH_M = {"K1": 0.077, "K2": 0.125, "K3": 0.160}
RAD_MAX_LEN_M = 2.0
# 70/60 flow/return against a ~20 C room gives delta-T ~45: the standard
# derating from catalogue delta-T 50 figures.
DT_CORRECTION = (45.0 / 50.0) ** 1.3
TOWEL_RAIL_W = 450.0        # 500x800 towel rail at delta-T 50
MIN_EMITTER_W = 120.0       # below this a room needs no emitter of its own


def _room_temp(kind, name):
    name = (name or "").lower()
    if name.startswith(("bed", "master")):
        return ROOM_TEMP_C["bedroom"]
    if name.startswith("bath"):
        return ROOM_TEMP_C["bathroom"]
    # the generic wet kind covers WCs and utilities, which are kept at
    # 18 C, not a bathroom's 22 — the name disambiguates, as in Part F
    if name.startswith(("wc", "util")):
        return 18.0
    return ROOM_TEMP_C.get(kind, 21.0)


def _ach(kind, name):
    name = (name or "").lower()
    if name.startswith(("bed", "master")):
        return 0.5
    return ACH.get(kind, 0.5)


def _levels_of(room, storeys):
    base = int(room.get("base_level") or 0)
    n = room.get("storeys")
    top = storeys if n is None else base + int(n)
    return range(base, min(top, storeys))


def _envelope(model, room, level):
    """External wall runs bounding this room at this level.

    Yields (wall, lo, hi, openings) where lo..hi is the overlapped span in
    plan coordinates along the wall's axis and openings are the wall's
    openings that fall inside that span at this level, with their absolute
    position along the axis added as "at".
    """
    rx0, ry0 = room["x"], room["y"]
    rx1, ry1 = rx0 + room["width_m"], ry0 + room["depth_m"]
    for w in model["walls"]:
        if not w.get("external") or w.get("party"):
            continue
        (ax, ay), (bx, by) = w["start"], w["end"]
        if abs(ax - bx) < 1e-6:                      # runs along y
            if not (abs(ax - rx0) < 1e-6 or abs(ax - rx1) < 1e-6):
                continue
            lo, hi = max(min(ay, by), ry0), min(max(ay, by), ry1)
            base = min(ay, by)
        elif abs(ay - by) < 1e-6:                    # runs along x
            if not (abs(ay - ry0) < 1e-6 or abs(ay - ry1) < 1e-6):
                continue
            lo, hi = max(min(ax, bx), rx0), min(max(ax, bx), rx1)
            base = min(ax, bx)
        else:                                        # pragma: no cover
            continue
        if hi - lo < 1e-6:
            continue
        ops = []
        for o in w.get("openings", []):
            if o.get("level") not in (None, level):
                continue
            at = base + o["along"]
            if at + 1e-6 < lo or at + o["width"] - 1e-6 > hi:
                continue
            ops.append(dict(o, at=at))
        yield w, lo, hi, ops


def _wall_height(model, room):
    h = room.get("height_m")
    return float(h) if h else float(model.get("storey_height_m") or 2.4)


def _place_radiator(model, room, level, need_w):
    """Put the radiator where a heating engineer would: under the biggest
    window on an external wall, or failing that on the longest clear
    external run. Returns the plan rectangle the viewer can draw."""
    best = None                # (window_width, wall, opening)
    runs = []                  # (clear_len, wall, lo, hi)
    for w, lo, hi, ops in _envelope(model, room, level):
        for o in ops:
            if o["kind"] != "window" or o.get("sill", 0) < 0.72:
                continue       # a radiator is 600 high on 100 legs
            if best is None or o["width"] > best[0]:
                best = (o["width"], w, o)
        if not ops:
            runs.append((hi - lo, w, lo, hi))
    kind = "K1" if need_w <= 0.9 * RAD_W_PER_M["K1"] else "K2"
    length = need_w / RAD_W_PER_M[kind]
    if length > RAD_MAX_LEN_M:
        kind = "K3"
        length = need_w / RAD_W_PER_M[kind]
    length = min(max(0.4, math.ceil(length * 10) / 10), RAD_MAX_LEN_M)
    output = round(RAD_W_PER_M[kind] * length)

    if best:
        _, w, o = best
        length = min(length, max(0.4, o["width"] - 0.05))
        at = o["at"] + o["width"] / 2
    elif runs:
        runs.sort(reverse=True)
        clear, w, lo, hi = runs[0]
        length = min(length, max(0.4, clear - 0.2))
        at = (lo + hi) / 2
    else:
        return None            # no external wall to hang it on
    output = round(RAD_W_PER_M[kind] * length)

    (ax, ay), (bx, by) = w["start"], w["end"]
    depth = RAD_DEPTH_M[kind] + 0.04             # wall clearance
    inset = w.get("thickness_m", 0.3) / 2 + depth / 2 + 0.01
    if abs(ax - bx) < 1e-6:                      # wall runs along y
        side = 1.0 if room["x"] + room["width_m"] / 2 > ax else -1.0
        cx, cy, rw, rd, axis = ax + side * inset, at, depth, length, "y"
    else:
        side = 1.0 if room["y"] + room["depth_m"] / 2 > ay else -1.0
        cx, cy, rw, rd, axis = at, ay + side * inset, length, depth, "x"
    return {"type": kind, "len_m": round(length, 2), "output_W": output,
            "level": level, "axis": axis,
            "x": round(cx, 3), "y": round(cy, 3),
            "w": round(rw, 3), "d": round(rd, 3)}


def design(model):
    """Design heat loss and emitters for every room on every level."""
    storeys = int(model.get("storeys") or 1)
    dt_out = DESIGN_EXTERNAL_C
    rooms_out, total_w = [], 0.0
    for room in model["rooms"]:
        kind = room.get("kind", "room")
        name = room.get("name", "room")
        if kind == "garage":
            # unheated space: no emitter, excluded from the design loss.
            # (Simplification: walls between house and garage are treated
            # as adiabatic like other partitions; a colder-than-house
            # garage makes that slightly optimistic for adjoining rooms.)
            continue
        ti = _room_temp(kind, name)
        dt = ti - dt_out
        h = _wall_height(model, room)
        area = float(room["area_m2"])
        for level in _levels_of(room, storeys):
            gross = glazed = door_a = 0.0
            glaz_list = []
            for w, lo, hi, ops in _envelope(model, room, level):
                gross += (hi - lo) * h
                for o in ops:
                    a = o["width"] * o["height"]
                    if o["kind"] == "door":
                        door_a += a
                    else:
                        glazed += a
                        glaz_list.append(o)
            wall_net = max(0.0, gross - glazed - door_a)
            fabric_wk = (wall_net * U_VALUES["wall"]
                         + glazed * U_VALUES["window"]
                         + door_a * U_VALUES["door"])
            if level == storeys - 1:
                fabric_wk += area * U_VALUES["roof"]
            if level == 0:
                fabric_wk += area * U_VALUES["floor"]
            fabric_wk *= BRIDGING_UPLIFT
            vent_wk = AIR_HEAT_WM3K * _ach(kind, name) * area * h
            loss = (fabric_wk + vent_wk) * dt
            total_w += loss

            need = loss / DT_CORRECTION
            rad = None
            if loss >= MIN_EMITTER_W:
                if name.lower().startswith("bath") or kind in ("bathroom",
                                                              "ensuite"):
                    rad = {"type": "towel", "len_m": 0.5,
                           "output_W": round(TOWEL_RAIL_W), "level": level,
                           "axis": "x", "x": round(room["x"] + 0.45, 3),
                           "y": round(room["y"] + room["depth_m"] - 0.12, 3),
                           "w": 0.5, "d": 0.12}
                    if TOWEL_RAIL_W < need:
                        extra = _place_radiator(model, room, level,
                                                need - TOWEL_RAIL_W)
                        if extra:
                            rad = extra
                else:
                    rad = _place_radiator(model, room, level, need)
            rooms_out.append({
                "name": name, "level": level, "temp_C": ti,
                "floor_m2": round(area, 2), "volume_m3": round(area * h, 1),
                "wall_net_m2": round(wall_net, 2),
                "glazing_m2": round(glazed, 2),
                "glazing_pct_floor": round(100 * glazed / area, 1),
                "fabric_WK": round(fabric_wk, 1),
                "vent_WK": round(vent_wk, 1),
                "loss_W": round(loss),
                "radiator": rad,
            })
    # Boiler/heat-pump headline: space heating at design + a note that a
    # combi is sized by hot water, not by this number.
    out = {
        "design_external_C": dt_out,
        "u_values": dict(U_VALUES),
        "rooms": rooms_out,
        "totals": {
            "loss_W": round(total_w),
            "loss_kW": round(total_w / 1000, 2),
            "w_per_m2": round(
                total_w / max(1e-9, float(
                    model["totals"]["floor_area_m2"])), 1),
        },
        "notes": [
            "Design loss at %.0f C external, Part L 2021 notional "
            "U-values, 15%% bridging uplift." % dt_out,
            "Radiators sized at 70/60 flow/return (delta-T 45 correction "
            "on catalogue delta-T 50 outputs), placed under the largest "
            "window where one exists.",
            "A combi boiler is chosen on hot-water demand, not this "
            "figure; for a heat pump, emitters need resizing to a lower "
            "flow temperature.",
        ],
    }
    return out
