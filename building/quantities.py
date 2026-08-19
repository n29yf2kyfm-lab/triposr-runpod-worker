"""Whole-house bill of quantities from the measured model.

The estimator's arithmetic, coded: how many bricks, blocks, tiles,
battens, boards, litres and metres a design actually takes. Every line
records its BASIS — the rate and the measured quantity it multiplied —
so a builder queried on a number follows it back to the geometry, and a
wrong bill is diagnosable instead of merely wrong.

Rates are UK standard estimating figures (sources in
docs/ESTIMATING_RATES.md, learned 2026-08-14):
  - 60 bricks/m2 in stretcher bond (215x65 + 10mm joints); 9.9
    aircrete blocks/m2 (440x215).
  - Mortar 0.55 m3 per 1000 bricks laid; 1:4 mix at ~400 kg cement and
    ~1,800 kg building sand per m3.
  - Wall ties 2.5/m2 (AD A / PD 6697 900x450 staggered) + edge/opening
    uplift.
  - Interlocking concrete tiles 10.5/m2 at 345 mm gauge (2.9 m
    batten/m2); plain tiles 60/m2 at 100 mm gauge (10 m/m2); natural
    slate 500x250 ~20/m2 at 205 mm gauge (4.9 m/m2).
  - Emulsion 12 m2 per litre per coat on finished surfaces; mist +2
    coats on new plaster effectively halves first-coat coverage.
  - Plasterboard 12.5 mm in 2400x1200 sheets (2.88 m2); skim both
    walls and ceilings.
  - T&E cable ~8 m per socket outlet on ring finals, ~6 m per lighting
    point; 15 mm copper ~7 m per radiator both flows averaged over a
    two-storey plan, plus 22 mm primaries.

Waste allowances are explicit and separate, never hidden in the rate.
This module measures NEW BUILD of the modelled dwelling; it does not
price, sequence, or claim site conditions — takeoff.py owns money.
"""

BRICKS_PER_M2 = 60.0            # stretcher bond, half-brick leaf
BLOCKS_PER_M2 = 9.9             # 440x215 block, 10mm joints
MORTAR_M3_PER_1000_BRICKS = 0.55
MORTAR_M3_PER_M2_BLOCK = 0.012
CEMENT_KG_PER_M3 = 400.0        # 1:4 mix
SAND_KG_PER_M3 = 1800.0
WALL_TIES_PER_M2 = 2.5
TIE_EDGE_UPLIFT = 1.10          # extra rows at openings and corners

ROOF_COVERINGS = {
    "concrete_interlocking": {"per_m2": 10.5, "batten_m_per_m2": 2.9,
                              "gauge_mm": 345},
    "plain_tile": {"per_m2": 60.0, "batten_m_per_m2": 10.0,
                   "gauge_mm": 100},
    "natural_slate": {"per_m2": 20.0, "batten_m_per_m2": 4.9,
                      "gauge_mm": 205},
}
MEMBRANE_LAP = 1.15
RIDGE_UNIT_M = 0.45             # bedded ridge tile length

PLASTERBOARD_SHEET_M2 = 2.88    # 2400 x 1200
PAINT_M2_PER_L = 12.0
PAINT_COATS = 2.0
NEW_PLASTER_MIST_FACTOR = 1.4   # mist coat on fresh skim
SKIRTING_DOOR_ALLOW_M = 0.90    # opening per internal door in skirting

CABLE_M_PER_SOCKET = 8.0        # 2.5mm2 T&E, ring final average
CABLE_M_PER_LIGHT = 6.0         # 1.5mm2 T&E
LIGHTS_PER_ROOM = 1.25          # pendants + a few spots, averaged
PIPE15_M_PER_RAD = 7.0          # flow+return tails averaged
PIPE22_FACTOR = 0.6             # primaries as fraction of plan length

WASTE = {"bricks": 0.05, "blocks": 0.05, "tiles": 0.05, "slate": 0.08,
         "board": 0.10, "timber": 0.075, "cable": 0.10, "pipe": 0.10}


def _line(item, qty, unit, basis, waste_key=None):
    waste = WASTE.get(waste_key, 0.0)
    out_qty = qty * (1.0 + waste)
    return {
        "item": item, "quantity": round(out_qty, 1), "unit": unit,
        "net_quantity": round(qty, 1), "waste_pct": round(waste * 100, 1),
        "basis": basis,
    }


def _levels_of(room, storeys):
    base = int(room.get("base_level") or 0)
    n = room.get("storeys")
    top = storeys if n is None else base + int(n)
    return range(base, min(top, storeys))


def _wall_height(model, room):
    h = room.get("height_m")
    return float(h) if h else float(model.get("storey_height_m") or 2.4)


def _external(model):
    """Net external wall area, opening areas/counts, perimeter at dpc.

    The model's per-wall net_area_m2 is a ONE-storey plane less every
    level's openings (its plane bookkeeping), so the buildable area is
    computed here from first principles: length x storey height x
    storeys, less each opening — a level-None opening repeats on every
    storey the wall stands. Sanity anchor: a 3-bed detached lands in
    the 7,000-10,000 facing-brick band the trade quotes.
    """
    storeys = int(model.get("storeys") or 1)
    net = openings_a = perim = 0.0
    n_open = 0
    for w in model["walls"]:
        # A PARTY WALL IS NOT FACING BRICKWORK. It exports external=True
        # (it is an envelope plane), but nobody lays facing brick or
        # cavity ties against the neighbour's house — it is blockwork,
        # measured by _party_area and billed as its own line. Counting it
        # here charged every semi ~3,000 phantom facing bricks on the
        # flank, while the roof code above the same wall was carefully
        # zeroing its upstand for exactly that reason.
        if w.get("party"):
            if 0 in _levels_of(w, storeys):
                perim += float(w["length_m"])     # it still needs DPC
            continue
        # A WALL CAN BE INTERNAL LOW DOWN AND BRICKWORK HIGHER UP. Over a
        # single-storey rear extension the first-floor wall behind it
        # faces open sky, and the plan probe cannot see that: it finds a
        # room on both sides in PLAN and calls the whole wall internal.
        # model3d exports shared_storeys for exactly this, and the GLB
        # mesh and heatloss both already read it — the take-off did not,
        # so a 3 m rear extension came back 63 bricks instead of a
        # thousand, silently.
        shared = w.get("shared_storeys")
        levels = list(_levels_of(w, storeys))
        # storeys=None on a wall means "stands on every storey above its
        # base" — model3d's convention. Reading it as 1 halved the brick
        # order on every plain two-storey job.
        faces = [lv for lv in levels
                 if w.get("external") or (shared is not None and lv >= shared)]
        if not faces:
            continue
        n_st = len(faces)
        gross = float(w["length_m"]) * float(w["height_m"]) * n_st
        wall_open = 0.0
        for o in w.get("openings", []):
            if o.get("level") is None:
                reps = n_st
            elif int(o["level"]) in faces:
                reps = 1
            else:
                continue            # an opening on the plastered storeys
            wall_open += o["width"] * o["height"] * reps
            n_open += reps
        net += max(0.0, gross - wall_open)
        openings_a += wall_open
        if 0 in faces:
            perim += float(w["length_m"])
    return net, openings_a, n_open, perim


def _party_area(model):
    """Storey-height party wall area, for the party blockwork line."""
    storeys = int(model.get("storeys") or 1)
    return sum(float(w["length_m"]) * float(w["height_m"])
               * len(_levels_of(w, storeys))
               for w in model["walls"] if w.get("party"))


def _party_overlap(model, axis, line, lo, hi):
    """Metres of party wall lying on the line axis=line between lo..hi.

    Fractional on purpose: a neighbour half the depth of the plot shares
    half the flank, and the un-shared half is real facing brickwork. The
    binary version of this check zeroed the WHOLE monopitch upstand the
    moment any party wall touched its line.
    """
    total = 0.0
    other = 1 - axis
    for w in model["walls"]:
        if not w.get("party"):
            continue
        if not (abs(w["start"][axis] - line) < 0.35
                and abs(w["end"][axis] - line) < 0.35):
            continue
        w0 = min(w["start"][other], w["end"][other])
        w1 = max(w["start"][other], w["end"][other])
        total += max(0.0, min(hi, w1) - max(lo, w0))
    return total


def _roof_masonry(model):
    """(brick_m2, party_m2) of masonry between the wall plate and the
    roof planes — the gable triangles and the monopitch upstand.

    Which pile each panel lands in depends on what stands under it: a
    gable end over a party wall (every mid-terrace, and a semi ridged to
    the party line) is the party wall carried up, not facing brick.
    """
    rf = model.get("roof") or {}
    kind = rf.get("kind")
    above = float(rf.get("gable_area_m2") or 0.0)
    upstand = float(rf.get("upstand_area_m2") or 0.0)
    if not (above or upstand):
        return 0.0, 0.0
    fp = rf.get("footprint_m") or {}
    over = float(rf.get("overhang_m") or 0.0)
    along_x = rf.get("along_x")
    brick, party = 0.0, 0.0

    # The raking panels stand on the two walls at the ends of the ridge
    # axis. The wall-plate lines sit one overhang inside the roof
    # footprint (roof_over expanded it); a monopitch's high side was not
    # expanded, but its raking ends were, so the same inset holds.
    end_axis = 0 if along_x else 1               # x for ridge-along-x
    lo_l, hi_l = fp.get("xy"[1 - end_axis], [0.0, 0.0])
    lines = [fp["xy"[end_axis]][0] + over, fp["xy"[end_axis]][1] - over]
    per_end = above / 2.0
    for line in lines:
        shared = _party_overlap(model, end_axis, line,
                                lo_l + over, hi_l - over)
        if shared > 0.0:
            party += per_end                     # the wall carried up
        else:
            brick += per_end

    if kind == "monopitch" and upstand:
        # The upstand runs along the HIGH edge — the ridge line's fixed
        # coordinate — and splits by how much of it the neighbour shares.
        ridge = rf.get("ridge") or [[0.0, 0.0], [0.0, 0.0]]
        axis = 1 if along_x else 0
        line = ridge[0][axis]
        # The ridge line spans the COVERING, verge overhang included; the
        # upstand is masonry, which stops at the wall ends — and so does
        # the neighbour. Windowing on the covering length left ~6% of a
        # fully-shared party upstand billed as facing brick.
        w0 = min(ridge[0][1 - axis], ridge[1][1 - axis]) + over
        w1 = max(ridge[0][1 - axis], ridge[1][1 - axis]) - over
        length = max(1e-9, w1 - w0)
        frac = min(1.0, _party_overlap(model, axis, line, w0, w1) / length)
        party += upstand * frac
        brick += upstand * (1.0 - frac)
    return brick, party


def masonry(model):
    net, _, n_open, perim = _external(model)
    # THE GABLE IS PART OF THE WALL. _external measures storey by storey
    # and stops at the wall plate; the panel between the plate and the
    # roof planes is masonry too, and it was never in the bill. It splits
    # by what stands under it: facing brickwork on an external wall, the
    # party wall carried up where the neighbour is.
    rf = model.get("roof") or {}
    brick_above, party_above = _roof_masonry(model)
    net += brick_above
    # THE PARTY WALL IS ITS OWN LINE. Blockwork both leaves, no facing
    # brick, no ties to the outside — priced and ordered differently from
    # the envelope, which is why hiding it inside the brick number was
    # wrong in both directions at once.
    party_m2 = _party_area(model) + party_above
    party_blocks = party_m2 * BLOCKS_PER_M2 * 2.0
    bricks = net * BRICKS_PER_M2
    blocks = net * BLOCKS_PER_M2
    mortar = (bricks / 1000.0) * MORTAR_M3_PER_1000_BRICKS \
        + (net + party_m2 * 2.0) * MORTAR_M3_PER_M2_BLOCK
    cement_bags = mortar * CEMENT_KG_PER_M3 / 25.0
    sand_t = mortar * SAND_KG_PER_M3 / 1000.0
    ties = net * WALL_TIES_PER_M2 * TIE_EDGE_UPLIFT
    out = [
        _line("Facing bricks", bricks, "no",
              f"{BRICKS_PER_M2:.0f}/m2 stretcher bond x {net:.1f} m2 net "
              f"external wall"
              + (f", including {brick_above:.1f} m2 above the wall "
                 f"plate under the {rf.get('kind')} roof"
                 if brick_above else ""), "bricks"),
        _line("100mm blocks (inner leaf)", blocks, "no",
              f"{BLOCKS_PER_M2}/m2 x {net:.1f} m2", "blocks"),
    ]
    if party_m2:
        out.append(_line(
            "100mm blocks (party wall, both leaves)", party_blocks, "no",
            f"{party_m2:.1f} m2 party wall x 2 leaves x {BLOCKS_PER_M2}/m2"
            + (f", including {party_above:.1f} m2 carried up past the "
               f"wall plate" if party_above else "")
            + " — no facing leaf, no external cavity ties", "blocks"))
    out += [
        _line("Mortar", mortar, "m3",
              f"{MORTAR_M3_PER_1000_BRICKS} m3/1000 bricks + "
              f"{MORTAR_M3_PER_M2_BLOCK} m3/m2 blockwork"),
        _line("Cement 25kg bags", cement_bags, "bags",
              f"1:4 mix, {CEMENT_KG_PER_M3:.0f} kg/m3 mortar"),
        _line("Building sand", sand_t, "t",
              f"{SAND_KG_PER_M3:.0f} kg/m3 mortar"),
        _line("Cavity wall ties", ties, "no",
              f"{WALL_TIES_PER_M2}/m2 x {net:.1f} m2 x "
              f"{TIE_EDGE_UPLIFT} edge uplift"),
        _line("DPC 100mm roll", perim, "m",
              f"ground-floor external perimeter {perim:.1f} m, party "
              f"wall included — it stands on a footing too"),
        _line("Lintels", n_open, "no", "one per external opening"),
    ]
    return out


def roof(model, covering="concrete_interlocking"):
    q = model.get("roof_quantities") or {}
    rf = model.get("roof") or {}
    area = float(q.get("sloped_area_m2") or rf.get("sloped_area_m2") or 0.0)
    ridge = float(rf.get("ridge_m") or 0.0)
    eaves = float(rf.get("eaves_m") or 0.0)
    # roof_over has measured the verge — raking, at 1/cos(pitch) — since
    # the day it learnt gables, and nothing ever billed it. A gable with
    # no dry-verge on the order is a roof that cannot be finished.
    verge = float(rf.get("verge_m") or 0.0)
    spec = ROOF_COVERINGS[covering]
    wkey = "slate" if covering == "natural_slate" else "tiles"
    return [
        _line(f"Roof covering ({covering.replace('_', ' ')})",
              area * spec["per_m2"], "no",
              f"{spec['per_m2']}/m2 x {area:.1f} m2 sloped at "
              f"{spec['gauge_mm']}mm gauge", wkey),
        _line("Treated battens 25x50", area * spec["batten_m_per_m2"], "m",
              f"{spec['batten_m_per_m2']} m/m2 x {area:.1f} m2", "timber"),
        _line("Breather membrane", area * MEMBRANE_LAP, "m2",
              f"{area:.1f} m2 x {MEMBRANE_LAP} laps"),
        _line("Ridge tiles", ridge / RIDGE_UNIT_M if ridge else 0.0, "no",
              f"{ridge:.1f} m ridge / {RIDGE_UNIT_M} m unit", "tiles"),
        # A MONOPITCH'S TOP EDGE IS NOT A RIDGE. What it buys depends on
        # what it meets — ridge tiles where it meets the other half of a
        # pair, cover flashing and a tray where it abuts a wall — and
        # converting it silently to ridge tiles ordered ~25 units a
        # lean-to cannot fit anywhere. Billed in metres; the survey of
        # what the edge abuts decides the product.
        _line("Monopitch top edge (ridge OR flashing)",
              float(rf.get("high_edge_m") or 0.0), "m",
              "ridge tiles if it meets the neighbouring slope, code 4 "
              "lead flashing + cavity tray if it abuts a wall — decide "
              "on site, not in this bill"),
        _line("Gutter + fittings", eaves, "m", f"eaves length {eaves:.1f} m"),
        _line("Dry verge / barge", verge, "m",
              f"raking verge {verge:.1f} m at {rf.get('pitch_deg')} deg "
              f"(measured on the slope, not on plan)"),
    ]


def finishes(model):
    storeys = int(model.get("storeys") or 1)
    wall_a = ceil_a = floor_a = skirt = 0.0
    doors_int = 0
    for room in model["rooms"]:
        h = _wall_height(model, room)
        per = float(room.get("perimeter_m")
                    or 2 * (room["width_m"] + room["depth_m"]))
        area = float(room["area_m2"])
        for _ in _levels_of(room, storeys):
            wall_a += per * h
            ceil_a += area
            floor_a += area
            skirt += max(0.0, per - SKIRTING_DOOR_ALLOW_M)
            doors_int += 1
    doors_int = max(0, doors_int - 1)      # the entrance door is external
    board = (wall_a + ceil_a) / PLASTERBOARD_SHEET_M2
    paint_l = (wall_a + ceil_a) * PAINT_COATS * NEW_PLASTER_MIST_FACTOR \
        / PAINT_M2_PER_L
    return [
        _line("Plasterboard 12.5mm sheets", board, "no",
              f"({wall_a:.0f} m2 walls + {ceil_a:.0f} m2 ceilings) / "
              f"{PLASTERBOARD_SHEET_M2} m2 sheet", "board"),
        _line("Skim plaster", wall_a + ceil_a, "m2",
              "all boarded faces skimmed"),
        _line("Emulsion", paint_l, "L",
              f"{PAINT_COATS:.0f} coats + mist at {PAINT_M2_PER_L:.0f} "
              "m2/L on new plaster"),
        _line("Floor screed/deck", floor_a, "m2", "all room areas"),
        _line("Skirting", skirt, "m",
              "room perimeters less door openings", "timber"),
        _line("Internal door sets 762mm", doors_int, "no",
              "one per room less the entrance; 838mm where Part M "
              "access asks (ESTIMATE - internal doors are not yet "
              "geometric)"),
    ]


def services(model, heat=None, elec=None, mep=None):
    """Cable and pipe: ROUTED lengths when mep.py has drawn the runs,
    estimating rules only as the fallback.

    The difference matters and is stated per line. A rule of thumb says
    "8 m of twin-and-earth per socket" and is a defensible guess; a routed
    ring says how far the cable actually travels through this house.
    """
    # the pipeline computes heat/elec in the same pass as this bill, so
    # they arrive as arguments there; a saved model carries them itself
    elec = elec if elec is not None else (model.get("elec") or {})
    heat = heat if heat is not None else (model.get("heat") or {})
    mep = mep if mep is not None else (model.get("mep") or {})
    routed = mep.get("totals_m") or {}
    if routed:
        out = []
        for key in sorted(routed):
            system, size = key.split(":", 1)
            waste = "cable" if system == "power" else "pipe"
            out.append(_line(f"{size} ({system})", routed[key], "m",
                             f"routed runs measured off the model, "
                             f"{system} system", waste))
        # Every emitter takes its own pair of tails — a big bathroom's
        # towel rail is a second radiator to the plumber, not a fitting.
        rads = sum(1 for r in heat.get("rooms", [])
                   for e in (r.get("radiator"), r.get("towel_rail")) if e)
        if rads:
            out.append(_line("Radiators (as heat design)", rads, "no",
                             "heatloss.design emitter schedule"))
        term = mep.get("terminals") or []
        stacks = sum(1 for t in term if t.get("type") == "soil stack")
        if stacks:
            out.append(_line("Soil stack + fittings", stacks, "no",
                             "one ventilated stack at the wet rooms"))
        return out
    ext = model.get("extent_m") or {}
    plan_len = float(ext.get("x", [0, 8])[1]) + float(ext.get("y", [0, 8])[1])
    sockets = int(elec.get("sockets_twin_total") or 0)
    rooms_n = sum(1 for _ in model["rooms"])
    lights = rooms_n * LIGHTS_PER_ROOM
    rads = sum(1 for r in heat.get("rooms", [])
               for e in (r.get("radiator"), r.get("towel_rail")) if e)
    out = [
        _line("2.5mm2 T&E cable", sockets * CABLE_M_PER_SOCKET, "m",
              f"{CABLE_M_PER_SOCKET:.0f} m per socket x {sockets}",
              "cable"),
        _line("1.5mm2 T&E cable", lights * CABLE_M_PER_LIGHT, "m",
              f"{CABLE_M_PER_LIGHT:.0f} m per point x {lights:.0f} "
              "lighting points", "cable"),
        _line("15mm copper pipe", rads * PIPE15_M_PER_RAD, "m",
              f"{PIPE15_M_PER_RAD:.0f} m per radiator x {rads}", "pipe"),
        _line("22mm copper primaries", plan_len * 2 * PIPE22_FACTOR, "m",
              f"plan extents x 2 runs x {PIPE22_FACTOR}", "pipe"),
    ]
    if rads:
        out.append(_line("Radiators (as heat design)", rads, "no",
                         "heatloss.design emitter schedule"))
    return out


def bill(model, covering="concrete_interlocking", heat=None, elec=None,
         mep=None):
    """The full bill of quantities, grouped by trade."""
    groups = {
        "masonry": masonry(model),
        "roof": roof(model, covering),
        "finishes": finishes(model),
        "services": services(model, heat=heat, elec=elec, mep=mep),
    }
    return {
        "groups": groups,
        "covering": covering,
        "notes": [
            "Quantities from the measured model; waste shown per line, "
            "never hidden in the rate.",
            "Internal door count is an estimate until internal doors are "
            "geometric.",
            "Cable and pipe come from mep.py's routed runs where they "
            "exist, and from estimating rules only as a fallback; each "
            "line says which.",
            "This bill is measured, not priced. takeoff.py prices "
            "roof-mode takeoffs only; the masonry, finishes and services "
            "trades are unpriced until a rate-card pricing path exists.",
        ],
    }
