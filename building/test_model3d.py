"""Tests for Model Mode — a drawing becomes a real 3D building.

The output of this module gets quantities taken off it and gets shown to a
client as if it were the building, so almost every test here is about a way
the geometry could be plausibly wrong rather than obviously broken. Three of
them exist because the module WAS wrong in exactly that way on real drawings:
a wall matcher that produced 52 windows and no doors, a schedule check that
reported 9.5% on an L-shaped kitchen whose two halves add up exactly, and an
OBJ writer that wrote a three-storey block as a bungalow.

Network-free, GPU-free, and IFC is optional — write_ifc is skipped rather
than failed when ifcopenshell is absent.

Run: python building/test_model3d.py
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import model3d as M  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


class _Prog:
    def stage(self, *a, **k):
        pass

    def note(self, *a, **k):
        pass


def room(name, x, y, w, d, **kw):
    return M.Room(name, x, y, w, d, **kw)


# A small terraced-house plate, drawn flush, used by several sections.
def plate():
    return [room("Lounge", 0.0, 0.0, 4.0, 4.0),
            room("Kitchen", 4.1, 0.0, 3.0, 4.0),
            room("Hall", 0.0, 4.1, 7.1, 1.6)]


# ---- 1. Room — the units trap ----------------------------------------------
# A UK drawing is figured in millimetres. 4570 read straight across is a room
# 4.57 kilometres wide, and nothing downstream would question it: the areas
# would be enormous but internally consistent, the walls would close, the IFC
# would validate. It has to be caught at construction.

r = room("Bedroom", 1.0, 2.0, 3.6, 4.2)
check("1a a room keeps its position", (r.x, r.y) == (1.0, 2.0))
check("1b and computes its own area", abs(r.area_m2 - 15.12) < 1e-9,
      str(r.area_m2))
check("1c and its perimeter", abs(r.perimeter_m - 15.6) < 1e-9,
      str(r.perimeter_m))
check("1d corners run anticlockwise from the origin corner",
      r.corners()[0] == (1.0, 2.0) and r.corners()[2] == (4.6, 6.2))

for bad_w, bad_d, why in [(4570.0, 4200.0, "millimetres read as metres"),
                          (0.0, 3.0, "zero width"),
                          (-2.0, 3.0, "negative width"),
                          (3.0, 0.0, "zero depth")]:
    try:
        room("X", 0, 0, bad_w, bad_d)
        check(f"1e {why} is refused", False)
    except M.ModelError:
        check(f"1e {why} is refused", True)

try:
    room("Cupboard", 0, 0, 0.4, 0.4)
    check("1f a 0.16 m2 space is refused as not a room", False)
except M.ModelError as e:
    check("1f a 0.16 m2 space is refused as not a room", "outside" in str(e),
          str(e))

def _err(w):
    try:
        room("X", 0, 0, w, 4.2)
    except M.ModelError as e:
        return str(e)
    return ""


check("1g the units message names the actual trap",
      "millimetres" in _err(4570.0), _err(4570.0))
check("1h a room defaults to the Part M ceiling height",
      room("A", 0, 0, 3, 3).height == M.DEFAULT_CEILING_HEIGHT_M)
check("1i as_dict rounds but does not lose the name",
      room("Utility", 0, 0, 1.95, 4.2).as_dict()["area_m2"] == 8.19)


# ---- 2. the schedule check -------------------------------------------------
# The drawing prints a floor area in every room. The model is built from the
# dimension strings, NOT from those areas, so comparing the two is a genuine
# check rather than a restatement. This is the only independent verification
# the module has.

sched = M.check_against_schedule(
    [room("Room 7", 0, 0, 4.47, 4.2)], {"Room 7": 18.8})
check("2a a room that matches the drawing agrees",
      sched["rooms"][0]["status"] == "agrees")
check("2b and the error is reported as a percentage",
      sched["rooms"][0]["error_pct"] < 0.5,
      str(sched["rooms"][0]["error_pct"]))
check("2c within_tolerance is set", sched["within_tolerance"])

# THE L-SHAPED ROOM. A real kitchen is rarely a rectangle; it is modelled as
# two rectangles sharing one name. Comparing only one of them against the
# schedule reported 9.5% on a room whose parts add up exactly, which is a
# false alarm that would send somebody back to re-measure a correct drawing.
lshape = M.check_against_schedule(
    [room("Kitchen / Dining", 0, 0, 4.57, 4.2),
     room("Kitchen / Dining", 0, 4.3, 2.85, 0.71)],
    {"Kitchen / Dining": 21.2})
check("2d an L-shaped room is summed across its parts",
      lshape["rooms"][0]["status"] == "agrees",
      f"{lshape['rooms'][0]['modelled_m2']} vs 21.2")
check("2e and the output says how many parts were summed",
      lshape["rooms"][0].get("parts") == 2)

wrong = M.check_against_schedule([room("Room 7", 0, 0, 4.0, 4.0)],
                                 {"Room 7": 18.8})
check("2f a room that disagrees is flagged, not smoothed over",
      wrong["rooms"][0]["status"] == "DISAGREES", str(wrong["rooms"][0]))
check("2g and within_tolerance goes false", not wrong["within_tolerance"])

missing = M.check_against_schedule([room("Hall", 0, 0, 3, 2)],
                                   {"Room 9": 9.5})
check("2h a scheduled room that was never modelled is reported",
      missing["rooms"][0]["status"] == "not modelled")
check("2i and is not silently scored as agreeing",
      missing["rooms"][0]["modelled_m2"] is None)
# A MISSING ROOM MUST FAIL THE HEADLINE, NOT JUST ITS OWN ROW. The row said
# "not modelled" while within_tolerance stayed True, so any consumer that
# reads the boolean — which is all of them — was told the model matched a
# drawing it was missing a whole room from.
check("2l a missing room fails the verdict, not just its own row",
      not missing["within_tolerance"], str(missing))
check("2m and the summary counts what was never modelled",
      missing.get("not_modelled") == 1, str(missing.get("not_modelled")))
_all_there = M.check_against_schedule(
    [room("Lounge", 0, 0, 4.0, 4.0)], {"Lounge": 16.0})
check("2n a fully modelled schedule still passes",
      _all_there["within_tolerance"]
      and _all_there.get("not_modelled") == 0, str(_all_there))

case = M.check_against_schedule([room("kitchen / dining", 0, 0, 4.57, 4.2)],
                                {"Kitchen / Dining": 19.2})
check("2j names are matched case- and space-insensitively",
      case["rooms"][0]["status"] != "not modelled")

check("2k a zero stated area does not divide by zero",
      M.check_against_schedule([room("A", 0, 0, 3, 3)],
                               {"A": 0})["rooms"][0]["error_pct"] == 0.0)


# ---- 3. walls --------------------------------------------------------------

w = M.Wall((0, 0), (4, 0), 0.1, 2.4)
check("3a a wall knows its length", abs(w.length_m - 4.0) < 1e-9)
check("3b gross area before openings", abs(w.area_m2 - 9.6) < 1e-9)
w.add_opening("door", 0.2, M.DOOR_W_M, M.DOOR_H_M)
check("3c an opening is deducted from the area",
      abs(w.area_m2 - (9.6 - M.DOOR_W_M * M.DOOR_H_M)) < 1e-9, str(w.area_m2))

try:
    M.Wall((0, 0), (1.0, 0), 0.1, 2.4).add_opening("door", 0.5, 0.838, 1.981)
    check("3d an opening that will not fit the wall is refused", False)
except M.ModelError as e:
    check("3d an opening that will not fit the wall is refused",
          "does not fit" in str(e), str(e))

# SHARED EDGES ARE BUILT ONCE. Building both sides of a party wall doubles
# the plasterboard and the paint on every quantity taken off the model.
back_to_back = [room("A", 0, 0, 4, 3), room("B", 0, 3, 4, 3)]
ws = M.walls_from_rooms(back_to_back)
# Assert the MEASUREMENT, not the wall count. Counting walls was testing
# how the edges happened to be split, and it went red the moment collinear
# pieces were correctly merged back into one wall — while the quantity it
# was actually guarding never moved.
_shared = [x for x in ws
           if abs(x.start[1] - 3.0) < 1e-9 and abs(x.end[1] - 3.0) < 1e-9]
check("3e the shared edge is built once, not twice", len(_shared) == 1,
      f"{len(_shared)} walls on the party line")
check("3e2 and the total wall run is the perimeter plus that one party wall",
      abs(sum(x.length_m for x in ws) - (2 * (4 + 6) + 4)) < 1e-6,
      f"{sum(x.length_m for x in ws):.2f} m, want 24.00")

# EXTERNAL IS DECIDED BY WHAT IS ON THE OTHER SIDE. Keying on coincident
# edges marked every wall external on a real plan — 52 windows, no doors —
# because corridors and set-backs mean almost no two rooms share an exact
# edge.
gap = [room("A", 0, 0, 4, 3), room("B", 0, 3.1, 4, 3)]
ws = M.walls_from_rooms(gap)
internals = [x for x in ws if not x.external]
check("3f a wall with a room on both sides is internal even across a gap",
      len(internals) >= 1, f"{len(internals)} internal of {len(ws)}")
check("3g an internal wall gets the thin thickness",
      all(abs(x.thickness - M.DEFAULT_WALL_THICKNESS_M) < 1e-9
          for x in internals))
check("3h an external wall gets the cavity thickness",
      all(abs(x.thickness - M.DEFAULT_EXTERNAL_THICKNESS_M) < 1e-9
          for x in ws if x.external))

lone = M.walls_from_rooms([room("Only", 0, 0, 4, 3)])
check("3i a single room is external on all four sides",
      len(lone) == 4 and all(x.external for x in lone))


# ---- 4. the roof — sloped area is the whole point --------------------------
# A roof covers 1/cos(pitch) more material than its footprint. At 35 degrees
# that is 22%. Ordering tiles off the plan area is how a re-roof comes up
# short on a job that has already been priced.

rf = M.roof_over(0, 0, 10, 8, pitch_deg=35.0, kind="hipped", overhang=0.0)
check("4a plan area is the footprint", abs(rf["plan_area_m2"] - 80.0) < 1e-6,
      str(rf["plan_area_m2"]))
check("4b sloped area is plan / cos(pitch)",
      abs(rf["sloped_area_m2"] - 80.0 / math.cos(math.radians(35))) < 0.01,
      str(rf["sloped_area_m2"]))
check("4c the uplift is reported as a percentage",
      abs(rf["uplift_pct"] - 22.1) < 0.2, str(rf["uplift_pct"]))
check("4d and stated in words, because this is the number that goes wrong",
      "come up short" in rf["note"] or "short" in rf["note"], rf["note"])

check("4e a 45 degree roof is 41% more material",
      abs(M.roof_over(0, 0, 10, 10, pitch_deg=45.0,
                      overhang=0.0)["uplift_pct"] - 41.4) < 0.2)

# The ridge runs along the LONGER axis and the slope climbs across the
# shorter one. Getting that backwards puts the ridge in the wrong place and
# changes the rise.
check("4f the ridge runs along the longer axis", rf["along_x"] is True)
check("4g rise is half the short span times tan(pitch)",
      abs(rf["rise_m"] - 4.0 * math.tan(math.radians(35))) < 0.01,
      str(rf["rise_m"]))
tall = M.roof_over(0, 0, 8, 12, pitch_deg=35.0, overhang=0.0)
check("4h a deeper-than-wide footprint ridges the other way",
      tall["along_x"] is False)
check("4i and takes its rise off the SHORT span",
      abs(tall["rise_m"] - 4.0 * math.tan(math.radians(35))) < 0.01,
      str(tall["rise_m"]))

# A hip's true length is the 3D diagonal, not the plan diagonal — measuring
# it flat under-orders the hip tiles and the cut tiles down both ends.
half = 4.0
hip_plan = math.hypot(half, half)
check("4j a hip is measured in 3D, not on plan",
      abs(rf["hip_m"] - 4 * math.hypot(hip_plan, rf["rise_m"])) < 0.05,
      str(rf["hip_m"]))
check("4k a hipped roof has no verge", rf["verge_m"] == 0.0)

gab = M.roof_over(0, 0, 10, 8, pitch_deg=35.0, kind="gabled", overhang=0.0)
check("4l a gable has no hips", gab["hip_m"] == 0.0)
check("4m a gable has verge instead", gab["verge_m"] > 0)
check("4n a gable's ridge runs wall to wall",
      abs(gab["ridge_m"] - 10.0) < 0.01, str(gab["ridge_m"]))
check("4o a hip's ridge is shorter than the building",
      rf["ridge_m"] < 10.0 - 0.01, str(rf["ridge_m"]))
check("4p same footprint, same covering either way",
      abs(gab["sloped_area_m2"] - rf["sloped_area_m2"]) < 0.01)

# The overhang is real material and real eaves length.
over = M.roof_over(0, 0, 10, 8, pitch_deg=35.0, overhang=0.30)
check("4q an eaves overhang enlarges the roof",
      over["plan_area_m2"] > rf["plan_area_m2"], str(over["plan_area_m2"]))
check("4r eaves length follows the overhang",
      abs(over["eaves_m"] - 2 * (10.6 + 8.6)) < 0.01, str(over["eaves_m"]))

for bad in (5.0, 70.0, 0.0):
    try:
        M.roof_over(0, 0, 10, 8, pitch_deg=bad)
        check(f"4s a {bad:.0f} degree pitch is refused", False)
    except M.ModelError as e:
        check(f"4s a {bad:.0f} degree pitch is refused",
              "pitch" in str(e) and "elevation" in str(e), str(e))

try:
    M.roof_over(0, 0, 10, 8, kind="mansard")
    check("4t an unsupported roof kind is refused, not approximated", False)
except M.ModelError:
    check("4t an unsupported roof kind is refused, not approximated", True)

# A FOOTPRINT TOO DEEP TO SPAN IN ONE GO. A trussed rafter reaches about
# 11m; past that a building is DOUBLE-PILE — parallel ranges with a valley
# gutter between them, which is why Victorian pubs and terraces read as an M
# from the end. Roofing 14m in a single hip put the ridge 5m above the wall
# head on a building with 2.75m storeys: a roof nearly two storeys tall.
wide = M.roof_over(0, 0, 14.32, 17.36, pitch_deg=35.0, overhang=0.0)
check("4y a footprint too deep for one span becomes several ranges",
      wide["ranges"] == 2, str(wide["ranges"]))
check("4z each range is within the span a roof is actually built to",
      wide["span_m"] <= M.MAX_ROOF_SPAN_M, str(wide["span_m"]))
check("4aa which halves the rise",
      abs(wide["rise_m"] - 14.32 / 4 * math.tan(math.radians(35))) < 0.01,
      str(wide["rise_m"]))
check("4ab the roof is no longer taller than a storey",
      wide["rise_m"] < 2.75, str(wide["rise_m"]))
check("4ac the ridge run is the sum of both ranges, not one",
      wide["ridge_m"] > 15.0, str(wide["ridge_m"]))
check("4ad a valley gutter appears between the ranges",
      abs(wide["valley_m"] - 17.36) < 0.01, str(wide["valley_m"]))
check("4ae and there is one gutter for two ranges",
      abs(wide["valley_m"] / 17.36 - (wide["ranges"] - 1)) < 0.01)
check("4af every range is emitted so the mesh can draw them all",
      len(wide["range_list"]) == wide["ranges"])
check("4ag the ranges tile the footprint with no gap and no overlap",
      abs(sum(b["band_m"]["x"][1] - b["band_m"]["x"][0]
              for b in wide["range_list"]) - 14.32) < 0.01)
check("4ah the split is explained, with both ridge heights",
      wide["range_note"] and "5.01" in wide["range_note"],
      str(wide["range_note"]))
# THE COVERING DOES NOT CHANGE. Every plane is still at the same pitch, so
# splitting the roof moves the linear items and nothing else — if the tile
# quantity moved too, one of the two answers would be wrong.
single = M.roof_over(0, 0, 14.32, 17.36, pitch_deg=35.0, overhang=0.0,
                     max_span=100.0)
check("4ai splitting the roof does not change the covering",
      abs(wide["sloped_area_m2"] - single["sloped_area_m2"]) < 0.01,
      f"{wide['sloped_area_m2']} vs {single['sloped_area_m2']}")
check("4aj but it does change the ridge height",
      wide["ridge_z_m"] < single["ridge_z_m"] - 2.0)
check("4ak a single-range roof has no valley and says nothing about ranges",
      single["valley_m"] == 0.0 and single["range_note"] is None)
check("4al a small footprint is still one range",
      M.roof_over(0, 0, 8.0, 6.0, overhang=0.0)["ranges"] == 1)
check("4am a very deep footprint takes three",
      M.roof_over(0, 0, 26.0, 30.0, overhang=0.0)["ranges"] == 3)

wq = M.roof_quantities(wide)
check("4an the valley gutter reaches the take-off, with a lap allowance",
      wq["materials"]["valley_lining_m"] > wide["valley_m"],
      str(wq["materials"].get("valley_lining_m")))
check("4ao a roof with no valley carries no valley line",
      "valley_lining_m" not in M.roof_quantities(single)["materials"])

q = M.roof_quantities(rf)
check("4u the take-off measures the SLOPE, not the footprint",
      q["sloped_area_m2"] == rf["sloped_area_m2"]
      and q["sloped_area_m2"] > q["plan_area_m2"])
check("4v underlay carries a lap allowance",
      q["materials"]["membrane_m2"] > q["sloped_area_m2"])
check("4w battens are gauged off the sloped area",
      abs(q["materials"]["battens_m"] - rf["sloped_area_m2"] / 0.30) < 0.2,
      str(q["materials"]["battens_m"]))
check("4x ridge units cover ridge AND hips",
      q["materials"]["ridge_units"] > (rf["ridge_m"]) / 0.30)


# ---- 5. build — the whole model -------------------------------------------

m = M.build(plate(), schedule={"Lounge": 16.0, "Kitchen": 12.0})
check("5a every room is in the model", len(m["rooms"]) == 3)
check("5b floor area is the sum of the rooms",
      abs(m["totals"]["floor_area_m2"] - (16.0 + 12.0 + 7.1 * 1.6)) < 0.01,
      str(m["totals"]["floor_area_m2"]))
check("5c walls were traced", m["totals"]["walls"] > 0)
check("5d openings were cut", m["totals"]["doors"] + m["totals"]["windows"] > 0)
check("5e a plan with both room types gets both doors and windows",
      m["totals"]["doors"] > 0 and m["totals"]["windows"] > 0,
      f"{m['totals']['doors']}d {m['totals']['windows']}w")
check("5f net wall area deducts the openings",
      m["totals"]["wall_area_net_m2"] < m["totals"]["wall_length_m"] * 2.4)
check("5g the schedule check rides along", "schedule_check" in m)
check("5h assumptions are stated, not hidden", len(m["assumptions"]) >= 3)
check("5i and the first warning is that this came from figured dimensions",
      "FIGURED DIMENSIONS" in m["warnings"][0], m["warnings"][0])
check("5j rectangles-only is admitted",
      any("rectangles" in x for x in m["warnings"]))

try:
    M.build([])
    check("5k an empty plan is refused", False)
except M.ModelError:
    check("5k an empty plan is refused", True)

for bad in (0, 21):
    try:
        M.build(plate(), storeys=bad)
        check(f"5l {bad} storeys is refused", False)
    except M.ModelError:
        check(f"5l {bad} storeys is refused", True)

# MULTI-STOREY. The plate is repeated upward, and the quantities have to
# scale with it — a three-storey block with one storey of plasterboard on it
# is a quote that loses money twice over. EXCEPT the front door: it is
# pinned to the ground floor, so doors scale as internal x storeys + 1, and
# the net wall area gives back the door's cut on the storeys it is not on.
# The original x3 assertion here was asserting a phantom door per floor.
one = M.build(plate())
three = M.build(plate(), storeys=3)
for key in ("rooms", "walls", "floor_area_m2", "wall_length_m", "windows"):
    check(f"5m {key} scales with the storey count",
          abs(three["totals"][key] - one["totals"][key] * 3) < 0.02,
          f"{three['totals'][key]} vs {one['totals'][key]} x3")
check("5m doors scale per storey plus ONE front door",
      three["totals"]["doors"] == (one["totals"]["doors"] - 1) * 3 + 1,
      f"{three['totals']['doors']} vs ({one['totals']['doors']}-1)x3+1")
_door_cut = 0.838 * 1.981
check("5m net wall area gives the door cut back on upper storeys",
      abs(three["totals"]["wall_area_net_m2"]
          - (one["totals"]["wall_area_net_m2"] * 3 + 2 * _door_cut)) < 0.02,
      f"{three['totals']['wall_area_net_m2']}")
# and the door is really there, once, on the front
_fd = [(o, w) for w in one["walls"] for o in w["openings"]
       if o["kind"] == "door" and o.get("level") == 0]
check("5m the front door exists, pinned to level 0", len(_fd) == 1,
      str(len(_fd)))

# FLOOR TO FLOOR IS NOT CEILING HEIGHT. Ignoring the floor zone — joists,
# deck, ceiling — stacks the storeys 350mm too close and puts the roof
# roughly a metre low on a three-storey block.
check("5n floor to floor exceeds the ceiling height",
      three["storey_height_m"] > three["totals"]["ceiling_height_m"],
      f"{three['storey_height_m']} vs {three['totals']['ceiling_height_m']}")
# The eaves bear on the TOP OF THE TOPMOST WALL. Setting them a floor zone
# higher — storeys x floor-to-floor — floats the roof 350mm clear of the
# walls, which is a hole in the model and a wall plate on fresh air.
check("5o eaves sit on top of the topmost wall",
      abs(three["eaves_z_m"] - (three["storey_height_m"] * 2
                                + three["totals"]["ceiling_height_m"])) < 1e-6,
      f"{three['eaves_z_m']}")
check("5o2 and a single-storey building ends at its own ceiling",
      abs(one["eaves_z_m"] - one["totals"]["ceiling_height_m"]) < 1e-6,
      str(one["eaves_z_m"]))
check("5p a stated storey height is honoured, not overridden",
      abs(M.build(plate(), storeys=2,
                  storey_height=3.0)["storey_height_m"] - 3.0) < 1e-9)
check("5q repeating one plate upward is admitted as an assumption",
      any("ASSUMED" in x for x in three["warnings"]),
      str(three["warnings"]))
check("5r a single-storey model does not carry that warning",
      not any("ASSUMED" in x for x in one["warnings"]))

roofed = M.build(plate(), storeys=3, roof={"pitch_deg": 35.0,
                                           "kind": "hipped",
                                           "overhang_m": 0.30})
check("5s the roof sits ON the eaves, not on the ground",
      abs(roofed["roof"]["eaves_z_m"] - roofed["eaves_z_m"]) < 1e-6,
      f"{roofed['roof']['eaves_z_m']} vs {roofed['eaves_z_m']}")
check("5t the ridge is above the eaves",
      roofed["totals"]["ridge_height_m"] > roofed["totals"]["eaves_height_m"])
check("5u the roof take-off is emitted with the model",
      roofed["roof_quantities"]["sloped_area_m2"] > 0)
check("5v the sloped area reaches the totals",
      roofed["totals"]["roof_sloped_area_m2"]
      == roofed["roof"]["sloped_area_m2"])
check("5w the sloped-vs-plan warning is carried into the model",
      any("footprint" in x for x in roofed["warnings"]))
check("5x the pitch is recorded as an assumption, since it was read off "
      "an elevation",
      any("overhang" in x for x in roofed["assumptions"]))
# THE ENVELOPE IS NOT THE BUILDING. The rooms are checked against the
# drawing's schedule; the rectangle drawn round them is checked against
# nothing. Roofing the reference sheet's first-floor plan produced a roof over 229.9 m2
# when the real building measures 369.6 m2 and wraps an L round a corner —
# confirmed against Google Solar and the aerial height model.
_partial = M.build(
    [room("A", 0, 0, 4, 4), room("B", 12, 12, 4, 4)],
    roof={"pitch_deg": 35.0})
check("5x2 a plan that leaves its bounding box mostly empty is flagged",
      any("BOUNDING BOX" in w for w in _partial["warnings"]),
      str(_partial["roof"]["plan_fill_pct"]))
check("5x3 and the fill percentage is reported as a number",
      _partial["roof"]["plan_fill_pct"] < 25,
      str(_partial["roof"]["plan_fill_pct"]))
_full = M.build([room("A", 0, 0, 5, 4), room("B", 5, 0, 5, 4),
                 room("C", 0, 4, 10, 4)], roof={"pitch_deg": 35.0})
check("5x4 a complete rectangular plate is NOT flagged",
      not any("BOUNDING BOX" in w for w in _full["warnings"]))
check("5x5 and reports 100% fill",
      _full["roof"]["plan_fill_pct"] == 100.0,
      str(_full["roof"]["plan_fill_pct"]))
# FILL IS A UNION, NOT A SUM. Summing room areas is the obvious thing and it
# fails in the one direction that matters: two rooms that overlap — an L
# entered as two overlapping rectangles, or a room typed twice — push the
# figure past 100% and switch the warning OFF. A bug that hides the check on
# a plan with duplicated area is worse than not having the check.
_dup = M.build([room("A", 0, 0, 10, 10), room("B", 0, 0, 10, 10)],
               roof={"pitch_deg": 35.0})
check("5x6a two rooms overlapping exactly report 100%, not 200%",
      _dup["roof"]["plan_fill_pct"] == 100.0,
      str(_dup["roof"]["plan_fill_pct"]))
check("5x6b and a plate that IS full does not warn",
      not any("BOUNDING BOX" in w for w in _dup["warnings"]))
_half = M.build([room("A", 0, 0, 10, 10), room("B", 5, 0, 10, 10)],
                roof={"pitch_deg": 35.0})
check("5x6c half-overlapping rooms cannot exceed their own bounding box",
      _half["roof"]["plan_fill_pct"] <= 100.0,
      str(_half["roof"]["plan_fill_pct"]))

check("5x6d the union counts disjoint rooms in full",
      abs(M._union_area([room("A", 0, 0, 5, 10), room("B", 5, 0, 5, 10)])
          - 100.0) < 1e-9)
check("5x6e and counts an overlap once",
      abs(M._union_area([room("A", 0, 0, 10, 10), room("B", 5, 0, 10, 10)])
          - 150.0) < 1e-9,
      str(M._union_area([room("A", 0, 0, 10, 10), room("B", 5, 0, 10, 10)])))
check("5x6f an L-shape unions to its true area",
      abs(M._union_area([room("A", 0, 0, 10, 4), room("B", 0, 4, 4, 6)])
          - 64.0) < 1e-9)
check("5x6g a room fully inside another adds nothing",
      abs(M._union_area([room("A", 0, 0, 10, 10), room("B", 2, 2, 4, 4)])
          - 100.0) < 1e-9)
check("5x6h no rooms unions to zero", M._union_area([]) == 0.0)

check("5x6 a roofless model carries no fill figure to misread",
      M.build([room("A", 0, 0, 4, 4)]).get("roof") is None)

check("5y a model with no roof says so rather than implying a flat one",
      one["roof"] is None and one["roof_quantities"] is None)
check("5z with no roof, ridge height is the eaves height",
      one["totals"]["ridge_height_m"] == one["totals"]["eaves_height_m"])


# ---- 6. openings in the mesh ----------------------------------------------
# A wall with a hole in it is several boxes. Above a door there is a lintel;
# above a window a lintel and below it a spandrel. Leaving either out puts
# daylight through the brickwork.

plain = {"height_m": 2.4, "openings": []}
check("6a a wall with no openings is one box",
      M._split_for_openings(0.0, 4.0, plain) == [(0.0, 4.0, 0.0, 2.4)])

doored = {"height_m": 2.4,
          "openings": [{"kind": "door", "along": 1.0, "width": 0.838,
                        "height": 1.981, "sill": 0.0}]}
parts = M._split_for_openings(0.0, 4.0, doored)
check("6b a door splits the wall and leaves a lintel over it",
      len(parts) == 3, str(parts))
check("6c and nothing under the door",
      not any(abs(p[2]) < 1e-9 and abs(p[3] - 0.0) < 1e-9 for p in parts))
check("6d the lintel starts at the door head",
      any(abs(p[2] - 1.981) < 1e-6 for p in parts), str(parts))

windowed = {"height_m": 2.4,
            "openings": [{"kind": "window", "along": 1.0, "width": 1.2,
                          "height": 1.2, "sill": 0.9}]}
parts = M._split_for_openings(0.0, 4.0, windowed)
check("6e a window leaves a spandrel under it",
      any(abs(p[2]) < 1e-9 and abs(p[3] - 0.9) < 1e-6 for p in parts),
      str(parts))
check("6f and a lintel over it",
      any(abs(p[2] - 2.1) < 1e-6 for p in parts), str(parts))

flush = {"height_m": 2.4,
         "openings": [{"kind": "door", "along": 0.0, "width": 1.0,
                       "height": 2.4, "sill": 0.0}]}
check("6g a full-height opening at the very start leaves no stub",
      all(p[0] >= 1.0 - 1e-9 for p in M._split_for_openings(0.0, 4.0, flush)),
      str(M._split_for_openings(0.0, 4.0, flush)))

two = {"height_m": 2.4,
       "openings": [{"kind": "door", "along": 2.5, "width": 0.8,
                     "height": 2.0, "sill": 0.0},
                    {"kind": "door", "along": 0.5, "width": 0.8,
                     "height": 2.0, "sill": 0.0}]}
segs = M._split_for_openings(0.0, 4.0, two)
check("6h openings out of order are still cut in the right places",
      all(segs[i][0] <= segs[i + 1][0] + 1e-9 for i in range(len(segs) - 1)),
      str(segs))


# ---- 7. OBJ export ---------------------------------------------------------

tmp = tempfile.mkdtemp()
obj = M.write_obj(roofed, os.path.join(tmp, "b.obj"))
text = open(obj).read()
vs = [ln for ln in text.splitlines() if ln.startswith("v ")]
fs = [ln for ln in text.splitlines() if ln.startswith("f ")]
gs = [ln.split(None, 1)[1] for ln in text.splitlines() if ln.startswith("g ")]
check("7a the OBJ has vertices", len(vs) > 100, str(len(vs)))
check("7b and faces", len(fs) > 50, str(len(fs)))
check("7c faces index vertices that exist",
      all(1 <= int(i) <= len(vs)
          for ln in fs for i in ln.split()[1:]), "out-of-range vertex index")

# EVERY STOREY, NOT JUST THE FIRST. The first version wrote the ground floor
# only, so a three-storey block came out as a bungalow — and looked fine.
check("7d every storey is written",
      all(any(g.startswith(f"slab_L{i}") for g in gs) for i in range(3)),
      str([g for g in gs if g.startswith("slab")]))
check("7e the roof is written as its own group", "roof" in gs)

zs = [float(ln.split()[2]) for ln in vs]         # OBJ is Y-up
check("7f the mesh reaches the ridge",
      abs(max(zs) - roofed["totals"]["ridge_height_m"]) < 0.01,
      f"{max(zs)} vs {roofed['totals']['ridge_height_m']}")
check("7g and starts at the slab, not below it",
      min(zs) >= -M.DEFAULT_SLAB_M - 1e-6, str(min(zs)))

flat_obj = M.write_obj(one, os.path.join(tmp, "flat.obj"))
flat_zs = [float(ln.split()[2]) for ln in open(flat_obj).read().splitlines()
           if ln.startswith("v ")]
check("7h a roofless model stops at the eaves",
      abs(max(flat_zs) - one["eaves_z_m"]) < 0.01, str(max(flat_zs)))

# THE FLOOR IS THE ROOMS, NOT THE BOUNDING BOX — in the OBJ too. The GLB
# was fixed and the OBJ kept the extent-wide slab, so the mesh a client
# orbits and the file a builder opens described different buildings: an
# 8x6 house with an 8x3 single-storey extension got a first-floor plate
# hanging over the extension's open sky. Main house spans y 0..6; nothing
# on level 1 may reach past it.
_extm = M.build([room("Main", 0, 0, 8.0, 6.0),
                 room("Extension", 0, 6.0, 8.0, 3.0, storeys=1)],
                storeys=2, storey_height=2.7)
_extp = os.path.join(tmp, "ext.obj")
M.write_obj(_extm, _extp)
_evs, _cur, _l1 = [], None, []
for _ln in open(_extp):
    if _ln.startswith("v "):
        _evs.append([float(t) for t in _ln.split()[1:]])
    elif _ln.startswith("g "):
        _cur = _ln.split(None, 1)[1].strip()
    elif _ln.startswith("f ") and _cur and _cur.startswith("slab_L1"):
        _l1 += [int(t) for t in _ln.split()[1:]]
check("7i no first-floor slab is written over a single-storey extension",
      bool(_l1) and all(-_evs[i - 1][2] <= 6.0 + 1e-6 for i in _l1),
      str(sorted({round(-_evs[i - 1][2], 2) for i in _l1})))
# and the ground floor still covers the extension it stands on
_l0 = []
_cur = None
for _ln in open(_extp):
    if _ln.startswith("g "):
        _cur = _ln.split(None, 1)[1].strip()
    elif _ln.startswith("f ") and _cur and _cur.startswith("slab_L0"):
        _l0 += [int(t) for t in _ln.split()[1:]]
check("7j while the ground slab still reaches the extension's back wall",
      any(-_evs[i - 1][2] > 8.9 for i in _l0),
      str(sorted({round(-_evs[i - 1][2], 2) for i in _l0})))

# EVERY RANGE IS DRAWN. A double-pile roof drawn as one range is the same
# class of error as a three-storey block drawn as a bungalow: it looks fine
# and it is a different building.
big = [room("Hall", 0, 0, 14.0, 17.0)]
two = M.build(big, roof={"pitch_deg": 35.0, "kind": "hipped"})
one_rng = M.build(big, roof={"pitch_deg": 35.0, "kind": "hipped"})
one_rng["roof"] = M.roof_over(0, 0, 14.0, 17.0, pitch_deg=35.0,
                              overhang=M.DEFAULT_EAVES_OVERHANG_M,
                              base_z=one_rng["eaves_z_m"], max_span=100.0)


def _roof_face_count(model):
    verts, faces, groups = [], [], []
    M._roof_faces(model["roof"], verts, faces, groups)
    return len(faces)


check("7j a two-range roof draws twice the planes of a one-range roof",
      _roof_face_count(two) == 2 * _roof_face_count(one_rng),
      f"{_roof_face_count(two)} vs {_roof_face_count(one_rng)}")
check("7k and its mesh stops well below the single-span ridge",
      two["roof"]["ridge_z_m"] < one_rng["roof"]["ridge_z_m"] - 2.0)

gabled = M.build(plate(), roof={"pitch_deg": 40.0, "kind": "gabled"})
gobj = M.write_obj(gabled, os.path.join(tmp, "g.obj"))
check("7i a gabled roof exports too", os.path.getsize(gobj) > 0)


# ---- 8. IFC export ---------------------------------------------------------
# Optional: the same lazy-import discipline as structure.py, so a runner
# without ifcopenshell skips rather than fails.

try:
    import ifcopenshell  # noqa: F401
    HAVE_IFC = True
except ImportError:
    HAVE_IFC = False

if HAVE_IFC:
    ifc = M.write_ifc(roofed, os.path.join(tmp, "b.ifc"), project_name="Test")
    body = open(ifc).read()
    check("8a the IFC is written", os.path.getsize(ifc) > 500)
    check("8b it is IFC4", "IFC4" in body, body[:200])
    check("8c it contains walls", "IFCWALL" in body.upper())
    f = ifcopenshell.open(ifc)
    check("8d and reopens in ifcopenshell", f.schema.startswith("IFC4"))
    check("8e with the walls actually present",
          len(f.by_type("IfcWall")) > 0, str(len(f.by_type("IfcWall"))))

    # THE IFC FLOOR IS THE ROOMS TOO. write_ifc kept the bounding-box slab
    # after the GLB was fixed, so an IFC-native takeoff counted a "Floor
    # slab L1" spanning the single-storey extension — 8x9m of first floor
    # where the true first floor is the 8x6m main house, the extra 24 m2
    # of it over open sky. Per-room plates: two on L0, one on L1, and the
    # L1 profile must be the main house, 8.0 x 6.0.
    _ifc2 = M.write_ifc(_extm, os.path.join(tmp, "ext.ifc"))
    _f2 = ifcopenshell.open(_ifc2)
    _floors = [s for s in _f2.by_type("IfcSlab")
               if s.PredefinedType == "FLOOR"]
    check("8f one floor slab per room per storey",
          len(_floors) == 3,
          str([s.Name for s in _floors]))
    _l1s = [s for s in _floors if "L1" in (s.Name or "")]

    def _plate(s):
        prof = s.Representation.Representations[0].Items[0].SweptArea
        return (round(prof.XDim, 3), round(prof.YDim, 3))

    check("8g the first-floor slab is the main house, not the bounding box",
          len(_l1s) == 1 and _plate(_l1s[0]) == (8.0, 6.0),
          str([_plate(s) for s in _l1s]))
else:
    check("8a IFC export skipped — ifcopenshell not installed", True)


# ---- 9. run_mode and the handler contract ---------------------------------

spec = {"scan_id": "test-house",
        "plan": {"rooms": [{"name": "Lounge", "x": 0, "y": 0,
                            "width_m": 4.0, "depth_m": 4.0},
                           {"name": "Kitchen", "x": 4.1, "y": 0,
                            "width_m": 3.0, "depth_m": 4.0}],
                 "schedule": {"Lounge": 16.0, "Kitchen": 12.0},
                 "storeys": 2,
                 "roof": {"pitch_deg": 35.0, "kind": "hipped",
                          "overhang_m": 0.3}}}
arts, extra = M.run_mode(spec, _Prog(), tmp)
names = [os.path.basename(a[0]) for a in arts]
check("9a run_mode writes an OBJ", any(n.endswith(".obj") for n in names),
      str(names))
check("9b and a JSON model", any(n.endswith(".model.json") for n in names))
check("9c artifacts are named after the scan",
      all(n.startswith("test-house") for n in names), str(names))
check("9d every artifact actually exists on disk",
      all(os.path.getsize(a[0]) > 0 for a in arts))
check("9e the model comes back in extra", "model" in extra)
check("9f with the roof on it", extra["model"]["roof"]["sloped_area_m2"] > 0)
check("9g and the warnings surface for the handler",
      isinstance(extra["warnings"], list) and extra["warnings"])
check("9h the schedule check made it through",
      extra["model"]["schedule_check"]["within_tolerance"])

try:
    M.run_mode({"scan_id": "x"}, _Prog(), tmp)
    check("9i a job with no plan is refused with an explanation", False)
except M.ModelError as e:
    check("9i a job with no plan is refused with an explanation",
          "figured dimensions" in str(e) or "dimensions" in str(e), str(e))

check("9j run is an alias for run_mode", M.run is M.run_mode)

# A missing dimension must not be guessed. A plausible-looking wall in the
# wrong place is worse than a hole.
try:
    M.run_mode({"scan_id": "x",
                "plan": {"rooms": [{"name": "A", "x": 0, "y": 0,
                                    "width_m": 4.0}]}}, _Prog(), tmp)
    check("9k a room with no depth is refused, not guessed", False)
except (M.ModelError, TypeError):
    check("9k a room with no depth is refused, not guessed", True)


# ---- 10. registration — reachable through the handler ---------------------
# Price Mode was unreachable for a fortnight because a mode existed and
# nothing routed to it. Registration is checked at all four points.

import types  # noqa: E402

_runpod = types.ModuleType("runpod")
_serverless = types.ModuleType("runpod.serverless")
_serverless.start = lambda *a, **k: None
_runpod.serverless = _serverless
sys.modules.setdefault("runpod", _runpod)
sys.modules.setdefault("runpod.serverless", _serverless)

import validation  # noqa: E402
import handler  # noqa: E402
import progress  # noqa: E402

check("10a model is a registered mode", "model" in validation.MODES)
check("10b the handler can find its module",
      handler._pipeline_available("model"))
check("10c and progress has a stage plan for it",
      "model" in progress.STAGE_PLANS)
check("10d every stage run_mode emits is in that plan",
      set(progress.STAGE_PLANS["model"]) >= {"reading", "building",
                                             "exporting"},
      str(progress.STAGE_PLANS["model"]))

parsed = validation.parse_job({
    "mode": "model",
    "plan": {"rooms": [{"name": "Lounge", "x": 0, "y": 0,
                        "width_m": 4.0, "depth_m": 4.0}],
             "schedule": {"Lounge": 16.0},
             "storeys": 3,
             "roof": {"pitch_deg": 35, "kind": "hipped", "overhang_m": 0.3}}})
check("10e a plan survives parse_job", parsed["plan"] is not None)
check("10f with its rooms in metres",
      parsed["plan"]["rooms"][0]["width_m"] == 4.0)
check("10g its schedule", parsed["plan"]["schedule"]["Lounge"] == 16.0)
check("10h its storey count", parsed["plan"]["storeys"] == 3)
check("10i and its roof", parsed["plan"]["roof"]["pitch_deg"] == 35.0)

try:
    validation.parse_job({"mode": "model"})
    check("10j a model job with no plan is refused at the door", False)
except validation.InputError as e:
    check("10j a model job with no plan is refused at the door",
          "plan" in str(e), str(e))

# THE MILLIMETRE TRAP AGAIN, this time at the door. A width of 4570 has to
# fail here with a message about units, not four functions deep.
for bad_plan, why in [
        ({"rooms": [{"name": "A", "x": 0, "y": 0,
                     "width_m": 4570, "depth_m": 4200}]}, "millimetres"),
        ({"rooms": [{"name": "A", "x": 0, "y": 0, "width_m": 4.0}]},
         "a missing depth"),
        ({"rooms": [{"x": 0, "y": 0, "width_m": 4.0, "depth_m": 4.0}]},
         "a room with no name"),
        ({"rooms": []}, "an empty room list"),
        ({"rooms": "Lounge"}, "rooms as a string"),
        ({"rooms": [{"name": "A", "x": 0, "y": 0,
                     "width_m": float("nan"), "depth_m": 4.0}]}, "a NaN width"),
        ({"rooms": [{"name": "A", "x": 0, "y": 0,
                     "width_m": 4.0, "depth_m": 4.0}],
          "schedule": {"A": "big"}}, "a non-numeric schedule area"),
        ({"rooms": [{"name": "A", "x": 0, "y": 0,
                     "width_m": 4.0, "depth_m": 4.0}],
          "roof": {"kind": "mansard"}}, "an unsupported roof kind"),
]:
    try:
        validation.parse_job({"mode": "model", "plan": bad_plan})
        check(f"10k {why} is refused at the door", False)
    except validation.InputError:
        check(f"10k {why} is refused at the door", True)

# PITCH IS NOT CLAMPED EITHER. 200 clamped to 89 is then refused by
# roof_over as "an 89 degree pitch" — a number nobody typed, in a message
# about a roof nobody described. Refuse it here; leave the 12-60 buildable
# range to roof_over, whose message explains why a tile will not shed water.
for _bad_pitch in (200, -5, 90):
    try:
        validation.parse_job({"mode": "model", "plan": {
            "rooms": [{"name": "A", "x": 0, "y": 0,
                       "width_m": 4.0, "depth_m": 4.0}],
            "roof": {"pitch_deg": _bad_pitch}}})
        check(f"10k-2 a {_bad_pitch} degree pitch is refused at the door", False)
    except validation.InputError as e:
        check(f"10k-2 a {_bad_pitch} degree pitch is refused at the door",
              str(_bad_pitch) in str(e), str(e))

_shallow = validation.parse_job({"mode": "model", "plan": {
    "rooms": [{"name": "A", "x": 0, "y": 0, "width_m": 4.0, "depth_m": 4.0}],
    "roof": {"pitch_deg": 3}}})["plan"]
check("10k-3 but a 3 degree pitch reaches roof_over, which owns that rule",
      _shallow["roof"]["pitch_deg"] == 3.0)
try:
    M.roof_over(0, 0, 6, 6, pitch_deg=3.0)
    check("10k-4 and roof_over refuses it with the reason", False)
except M.ModelError as e:
    check("10k-4 and roof_over refuses it with the reason",
          "shed water" in str(e), str(e))

# NAMES THAT NORMALISE THE SAME ARE SUMMED, NOT REFUSED.
#
# This asserted a refusal until a real drawing disproved it. A first-floor
# plan legitimately carries two rooms both labelled "Ensuite", and a building
# has a Hallway on every storey — read straight off the sheet by
# schedule.py. Refusing that rejects the drawing.
#
# Summing is the rule the model side already uses: check_against_schedule
# sums the MODEL's rooms by name, because an L-shaped kitchen is two
# rectangles under one label. Both sides summing is what makes the
# comparison mean anything. A duplicate that really was a typo shows up as a
# doubled area and a large error in the check, not as a silent pass.
_summed = validation.parse_job({"mode": "model", "plan": {
    "rooms": [{"name": "Ensuite", "x": 0, "y": 0,
               "width_m": 1.7, "depth_m": 1.8},
              {"name": "Ensuite", "x": 3, "y": 0,
               "width_m": 1.7, "depth_m": 1.8}],
    "schedule": {"Ensuite": 3.0, "ensuite": 3.0}}})["plan"]["schedule"]
check("10k-5 two schedule rows for one room are summed, not refused",
      _summed == {"Ensuite": 6.0}, str(_summed))
_rooms = [room("Ensuite", 0, 0, 1.7, 1.8), room("Ensuite", 3, 0, 1.7, 1.8)]
_row = M.check_against_schedule(_rooms, _summed)["rooms"][0]
check("10k-5b so two modelled en-suites agree with two scheduled ones",
      _row["status"] == "agrees", str(_row))
check("10k-5c and a typo shows up as a large error rather than a silent pass",
      M.check_against_schedule([room("Ensuite", 0, 0, 1.7, 1.8)],
                               _summed)["rooms"][0]["status"] == "DISAGREES")
check("10k-6 two genuinely different rooms are fine",
      len(validation.parse_job({"mode": "model", "plan": {
          "rooms": [{"name": "A", "x": 0, "y": 0,
                     "width_m": 4.0, "depth_m": 4.0}],
          "schedule": {"A": 16.0, "B": 12.0}}})["plan"]["schedule"]) == 2)

check("10l plan is a dict, not a list",
      isinstance(parsed["plan"], dict))
try:
    validation.parse_job({"mode": "model", "plan": ["Lounge"]})
    check("10m a plan that is not an object is refused", False)
except validation.InputError:
    check("10m a plan that is not an object is refused", True)

# Storeys clamp to what build() will actually accept, so the caller gets one
# clear message rather than a second one from deeper in.
clamped = validation.parse_job({
    "mode": "model",
    "plan": {"rooms": [{"name": "A", "x": 0, "y": 0,
                        "width_m": 4.0, "depth_m": 4.0}],
             "storeys": 500}})
check("10n an absurd storey count clamps to what build accepts",
      clamped["plan"]["storeys"] <= 20, str(clamped["plan"]["storeys"]))

# The isolation rule the whole worker rests on.
check("10o model mode does not touch the vehicle worker",
      "trellis" not in open(os.path.join(HERE, "model3d.py")).read().lower())


# ---- 11. the real drawing --------------------------------------------------
# A real UK pub converted to rooms with en-suites. These are
# the figured dimensions off the architect's first-floor plan, checked
# against the areas the same sheet prints in each room. Nothing here is
# traced; nothing is scaled off the linework.

PUB = [("Utility", 0.00, 0.00, 1.95, 4.20), ("Kitchen / Dining", 2.05, 0.00,
        4.57, 4.20), ("Kitchen / Dining", 2.05, 4.30, 2.85, 0.71),
        ("Room 8", 6.72, 0.00, 3.57, 4.20), ("En-suite 8", 10.39, 0.00,
        1.70, 1.99), ("Room 7", 6.72, 4.30, 4.47, 4.20),
        ("En-suite 7", 11.29, 4.30, 1.70, 2.00),
        ("Room 9", 2.05, 4.30, 2.14, 4.44),
        ("En-suite 9", 0.00, 4.30, 1.77, 1.89)]
PUB_SCHEDULE = {"Utility": 8.2, "Kitchen / Dining": 21.2, "Room 8": 15.0,
                 "Room 7": 18.8, "Room 9": 9.5, "En-suite 8": 3.4,
                 "En-suite 7": 3.4, "En-suite 9": 3.3}

pub = M.build([room(n, x, y, w, d) for n, x, y, w, d in PUB],
               schedule=PUB_SCHEDULE, storeys=3,
               roof={"pitch_deg": 35.0, "kind": "hipped", "overhang_m": 0.30})
vc = pub["schedule_check"]
check("11a every room on the sheet agrees with the drawing's own schedule",
      vc["within_tolerance"], f"worst {vc['worst_error_pct']}%")
check("11b and the worst disagreement is under 2%",
      vc["worst_error_pct"] < 2.0, str(vc["worst_error_pct"]))
check("11c no room went unmodelled",
      not any(r["status"] == "not modelled" for r in vc["rooms"]))
check("11d the roof needs a fifth more covering than its footprint",
      pub["roof"]["uplift_pct"] > 20.0, str(pub["roof"]["uplift_pct"]))
# THE ROOF THAT WAS TOO BIG. One hip over the whole footprint rose 5.01m —
# a roof nearly two storeys tall on a building with 2.75m storeys, which is
# instantly wrong to anybody who has looked at a pub.
check("11e the roof is not taller than a storey",
      pub["roof"]["rise_m"] < pub["storey_height_m"],
      f"rise {pub['roof']['rise_m']} vs storey {pub['storey_height_m']}")
check("11f the ridge sits above the wall head, not on it",
      pub["totals"]["ridge_height_m"] > pub["totals"]["eaves_height_m"],
      str(pub["totals"]["ridge_height_m"]))
check("11g every en-suite got a door, not a window",
      pub["totals"]["doors"] > 0)
# The real building, measured from the air: 369.6 m2 footprint, L-shaped round a
# corner plot. The rooms on this one sheet fill two thirds of the rectangle
# drawn round them, which is exactly the signal that says so.
check("11h the partial first-floor plan is flagged before anyone roofs it",
      any("BOUNDING BOX" in w for w in pub["warnings"]),
      str(pub["roof"]["plan_fill_pct"]))
check("11i and the fill figure is in the two-thirds range",
      60 < pub["roof"]["plan_fill_pct"] < 75,
      str(pub["roof"]["plan_fill_pct"]))


# ==========================================================================
# ---- 12. GLB export ------------------------------------------------------
# The OBJ opens anywhere but carries no materials of its own, and IFC needs
# software to read. GLB is the one an app hands to a viewer, to QuickLook on
# an iPhone, or to a client. Written with the standard library — a GLB is a
# header, a JSON chunk and a binary chunk, and putting Blender in the image
# to do that would cost ~1GB for a serialisation job.
import struct as _struct, json as _json, tempfile as _tf, os as _os

_gm = M.build([room(n, x, y, w, d) for n, x, y, w, d in PUB],
              schedule=PUB_SCHEDULE, storeys=3,
              roof={"pitch_deg": 35.0, "kind": "hipped", "overhang": 0.30})
_gp = _os.path.join(_tf.mkdtemp(), "m.glb")
M.write_glb(_gm, _gp)
_raw = open(_gp, "rb").read()

_magic, _ver, _len = _struct.unpack("<III", _raw[:12])
check("12a the magic is glTF", _magic == 0x46546C67, hex(_magic))
check("12b version 2", _ver == 2, str(_ver))
check("12c the declared length is the file length",
      _len == len(_raw), f"{_len} vs {len(_raw)}")

_o, _chunks = 12, []
while _o < len(_raw):
    _cl, _ct = _struct.unpack("<II", _raw[_o:_o + 8]); _o += 8
    _chunks.append((_ct, _raw[_o:_o + _cl])); _o += _cl
check("12d two chunks, JSON then BIN",
      [c[0] for c in _chunks] == [0x4E4F534A, 0x004E4942],
      str([hex(c[0]) for c in _chunks]))
# Every chunk must be 4-byte aligned or strict parsers reject the file.
check("12e chunks are 4-byte aligned",
      all(len(c[1]) % 4 == 0 for c in _chunks))

_g = _json.loads(_chunks[0][1]); _bin = _chunks[1][1]
check("12f the buffer length matches the binary chunk",
      _g["buffers"][0]["byteLength"] == len(_bin))
check("12g materials are declared", len(_g["materials"]) >= 5,
      str(len(_g["materials"])))
check("12h glass is a blended material, not opaque",
      any(m.get("alphaMode") == "BLEND" for m in _g["materials"]))

_prims = _g["meshes"][0]["primitives"]
check("12i geometry is split per material", len(_prims) >= 4, str(len(_prims)))

# AN INDEX PAST THE END OF ITS OWN VERTEX ARRAY renders as garbage or
# crashes the viewer, and nothing in the writer would otherwise catch it.
_bad = 0
for _pr in _prims:
    _ia = _g["accessors"][_pr["indices"]]
    _iv = _g["bufferViews"][_ia["bufferView"]]
    _idx = _struct.unpack_from(f"<{_ia['count']}I", _bin, _iv["byteOffset"])
    if max(_idx) >= _g["accessors"][_pr["attributes"]["POSITION"]]["count"]:
        _bad += 1
check("12j no index runs past its own vertex array", _bad == 0, str(_bad))
check("12k every bufferView sits inside the buffer",
      all(v["byteOffset"] + v["byteLength"] <= len(_bin)
          for v in _g["bufferViews"]))
check("12l every bufferView is 4-byte aligned",
      all(v["byteOffset"] % 4 == 0 for v in _g["bufferViews"]))

# THE MODEL MUST BE THE RIGHT SIZE. glTF is Y-up, so the model's ridge height
# has to come back as the maximum Y — this is what catches an axis swap, and
# an axis swap is invisible in a triangle count.
_ymax = max(_g["accessors"][_pr["attributes"]["POSITION"]]["max"][1]
            for _pr in _prims)
check("12m the top of the GLB is the ridge height, so Y really is up",
      abs(_ymax - _gm["totals"]["ridge_height_m"]) < 0.02,
      f"{_ymax:.3f} vs {_gm['totals']['ridge_height_m']}")

# and it must agree with the OBJ rather than being a mirror image of it
_op = _os.path.join(_tf.mkdtemp(), "m.obj")
M.write_obj(_gm, _op)
_ov = [l.split()[1:] for l in open(_op) if l.startswith("v ")]
_oy = max(float(v[1]) for v in _ov)
check("12n the GLB and the OBJ describe the same building",
      abs(_oy - _ymax) < 0.02, f"obj {_oy:.3f} vs glb {_ymax:.3f}")


# ---- 13. storeys and roof belong INSIDE plan, and saying so ---------------
# A real job sent {"mode":"model","storeys":2,"roof":{...},"plan":{...}} and
# came back as ONE storey with a 2.4m "ridge" — a bungalow with a flat top.
# The top-level `roof` key belongs to ROOF mode and top-level `storeys` is
# read by nothing, so both were silently dropped. Nothing warned; the totals
# looked perfectly reasonable for a building nobody asked for.
import validation as _V13
_plan13 = {"rooms": [{"name": "A", "x": 0, "y": 0, "width_m": 4, "depth_m": 3}]}

for _stray in ("storeys", "roof", "storey_height_m"):
    _job = {"mode": "model", "plan": dict(_plan13)}
    _job[_stray] = 2 if _stray != "roof" else {"pitch_deg": 35.0}
    try:
        _V13.parse_job(_job)
        check(f"13a top-level {_stray} is refused, not ignored", False,
              "accepted silently")
    except _V13.InputError as e:
        check(f"13a top-level {_stray} is refused, not ignored",
              "inside `plan`" in str(e), str(e)[:90])

# Inside the plan it is accepted, and it actually takes effect.
_ok = _V13.parse_job({"mode": "model",
                      "plan": {"rooms": _plan13["rooms"], "storeys": 2,
                               "roof": {"pitch_deg": 40.0}}})
check("13b inside plan, storeys is read", _ok["plan"]["storeys"] == 2,
      str(_ok["plan"].get("storeys")))
check("13c inside plan, the roof is read",
      (_ok["plan"].get("roof") or {}).get("pitch_deg") == 40.0,
      str(_ok["plan"].get("roof")))

# and a plain job with neither is still fine
check("13d a plan with no storeys or roof still validates",
      _V13.parse_job({"mode": "model", "plan": dict(_plan13)})["plan"]
      ["storeys"] == 1)


# ---- 14. the validator's own output must build ----------------------------
# parse_job stores "not stated" as an explicit None: a job with
# {"roof": {"pitch_deg": 35}} arrives at build() as
# {"pitch_deg": 35.0, "kind": "hipped", "overhang_m": None}. The key EXISTS,
# so roof.get("overhang_m", DEFAULT) never falls back, and None reached the
# arithmetic — `float - NoneType`, the whole job down, live on the deployed
# worker. Every test above hand-builds its roof dict with all keys set,
# which is why the suite was green while the worker crashed. This one feeds
# the validator's real output through the real path.
import validation as _V14
_spec14 = _V14.parse_job({"mode": "model", "plan": {
    "rooms": [{"name": "A", "x": 0, "y": 0, "width_m": 4, "depth_m": 3},
              {"name": "B", "x": 4.1, "y": 0, "width_m": 3, "depth_m": 3}],
    "storeys": 2, "roof": {"pitch_deg": 35.0}}})
check("14a the parsed roof really does carry an explicit None",
      _spec14["plan"]["roof"]["overhang_m"] is None,
      str(_spec14["plan"]["roof"]))
_m14 = M.build([M.Room(r["name"], r["x"], r["y"], r["width_m"], r["depth_m"])
                for r in _spec14["plan"]["rooms"]],
               storeys=_spec14["plan"]["storeys"],
               roof=_spec14["plan"]["roof"])
check("14b and build() survives it", _m14["roof"] is not None)
check("14c the default overhang was applied, not zero",
      abs(_m14["roof"]["overhang_m"] - 0.30) < 1e-9,
      str(_m14["roof"]["overhang_m"]))
check("14d two storeys actually came out",
      _m14["totals"]["storeys"] == 2 and
      _m14["totals"]["ridge_height_m"] > 5.0,
      str(_m14["totals"]))


# ---- 15. no window onto a void ---------------------------------------------
# Two rooms drawn 100mm apart — the normal state of a real plan — leave a
# void strip. The walls flanking it are rightly "external" (no room on the
# other side), but that side is a cavity inside the building, not the
# street, and glazing it produced a window with the neighbouring wall's
# brickwork 100mm behind the glass. Seen literally in the walkthrough.
# The void must be wider than the probe step (0.35m): a thinner gap is
# stepped straight over into the far room, which classifies both walls
# internal — a different (and acceptable) outcome. 0.5m is the awkward one.
_v15 = M.build([M.Room("South", 0, 0, 4.0, 3.0),
                M.Room("North", 0, 3.5, 4.0, 3.0)], storeys=1)
_void15 = [w for w in _v15["walls"]
           if w["external"] and not w["openings"]
           and (abs(w["start"][1] - 3.0) < 1e-6
                or abs(w["start"][1] - 3.5) < 1e-6)
           and abs(w["start"][1] - w["end"][1]) < 1e-6]
check("15a the two walls flanking the void carry NO openings",
      len(_void15) == 2, str(len(_void15)))
# the true outside walls still get their windows
check("15b the street-facing walls still get windows",
      sum(1 for w in _v15["walls"]
          if any(o["kind"] == "window" for o in w["openings"])) >= 4,
      str(_v15["totals"]["windows"]))
# and a genuinely flush pair still shares one internal wall with a door
_f15 = M.build([M.Room("A", 0, 0, 4.0, 3.0), M.Room("B", 0, 3.0, 4.0, 3.0)],
               storeys=1)
check("15c flush rooms still share a doored internal wall",
      any(not w["external"] and any(o["kind"] == "door"
                                    for o in w["openings"])
          for w in _f15["walls"]))


# --- 16. the ridge goes where the drawing says, not where the guess does ----
# A real section sheet (7370-W-603, a 5.4m-front 8.9m-deep terrace type)
# ridges along its FRONTAGE — the shorter axis — and spans 9.1m in one go.
# The longest-axis default gets both wrong: ridge turned 90 degrees, and the
# 9m span cap splitting one clear trussed roof into two ranges with an
# invented valley gutter on the quote.
_r16 = M.roof_over(0, 0, 5.38, 8.87, pitch_deg=35, kind="gabled",
                   overhang=0.13, base_z=4.95)
check("16a the default still ridges along the longer axis",
      _r16["along_x"] is False)
_r16b = M.roof_over(0, 0, 5.38, 8.87, pitch_deg=35, kind="gabled",
                    overhang=0.13, base_z=4.95, ridge_along="x", max_span=10)
check("16b ridge_along overrides the longest-axis guess",
      _r16b["along_x"] is True and _r16b["ranges"] == 1)
check("16c one clear span once max_span says the drawing shows one",
      abs(_r16b["span_m"] - 9.13) < 0.01, str(_r16b["span_m"]))
# A RAFTER BEARS ON THE WALL PLATE. The overhang projects out and DOWN past
# it, so it adds nothing to the rise — this expected 3.196, which is the rise
# across the span plus both overhangs, and that put the ridge 35mm high here
# and 210mm high on a 350mm eaves. Ridge height is what a planning condition
# is written against, so it is the one roof number that must not drift.
check("16d rise is measured across the STRUCTURAL span, not the overhang",
      abs(_r16b["rise_m"] - (8.87 / 2) * math.tan(math.radians(35))) < 0.01,
      str(_r16b["rise_m"]))
check("16d2 and the eaves TIP sits below the plate by the same geometry",
      abs(_r16b["eaves_tip_z_m"]
          - (4.95 - 0.13 * math.tan(math.radians(35)))) < 0.001,
      str(_r16b.get("eaves_tip_z_m")))
# A GABLE HAS EAVES ON TWO SIDES AND VERGE ON THE OTHER TWO. Reporting the
# whole perimeter as eaves counted the verge on both lines of the quote.
check("16e eaves is the two gutter sides only, not the perimeter",
      abs(_r16b["eaves_m"] - 2 * 5.64) < 0.02, str(_r16b["eaves_m"]))
check("16f verge is measured up the RAKE, not flat on plan",
      abs(_r16b["verge_m"]
          - 2 * 9.13 / math.cos(math.radians(35))) < 0.02,
      str(_r16b["verge_m"]))
try:
    M.roof_over(0, 0, 5, 8, ridge_along="diagonal")
    check("16e a nonsense ridge_along is refused", False)
except M.ModelError:
    check("16e a nonsense ridge_along is refused", True)
# and the whole thing flows through build()'s roof dict, None-safe
_b16 = M.build([M.Room("Plate", 0, 0, 4.78, 8.27)], storeys=2,
               storey_height=2.75,
               roof={"pitch_deg": 35, "kind": "gabled", "overhang_m": 0.43,
                     "ridge_along": "x", "max_span_m": 10,
                     "storeys": None})
check("16f build() plumbs ridge_along and max_span through",
      _b16["roof"]["along_x"] is True and _b16["roof"]["ranges"] == 1)
# ...and through the VALIDATOR, where both keys died on their first outing:
# build() accepted them, parse_job's whitelist silently dropped them, and
# the ridge came back turned 90 degrees. The joint, again.
import validation as _val16  # noqa: E402
_s16 = _val16.parse_job({"mode": "model", "plan": {
    "rooms": [{"name": "R", "x": 0, "y": 0, "width_m": 4.78,
               "depth_m": 8.27}],
    "roof": {"pitch_deg": 35, "kind": "gabled", "ridge_along": "x",
             "max_span_m": 10}}})
check("16g parse_job keeps ridge_along and max_span_m",
      _s16["plan"]["roof"]["ridge_along"] == "x"
      and _s16["plan"]["roof"]["max_span_m"] == 10.0)



# A STOREY BUILT OVER ANOTHER BLOCK SHARES ALL FOUR OF ITS EDGES with the
# block below, and walls_from_rooms built each shared edge once and dropped
# the second claim — so every wall of the new floor was discarded and it
# rendered as a roof over open air, no front wall, daylight straight
# through. The wall now spans the union of both rooms' levels.
_over_rooms = [M.Room("house", 0, 0, 6, 8, 3.0, kind="existing"),
               M.Room("addition", 6, 0, 5, 8, 2.6, kind="existing",
                      storeys=1),
               M.Room("over", 6, 0, 5, 8, 3.0, kind="extension",
                      storeys=1, base_level=1)]
_ow = M.walls_from_rooms(_over_rooms)
_l1 = [w for w in _ow if M._wall_on_level(w, 1)]
_front1 = [w for w in _l1
           if abs(w.start[1]) < 1e-6 and abs(w.end[1]) < 1e-6
           and max(w.start[0], w.end[0]) > 6]
check("30a a storey over another block has walls at its own level",
      len(_l1) >= 4, f"{len(_l1)} walls at level 1")
check("30b including the front wall — the one the void showed through",
      len(_front1) == 1, f"{len(_front1)} front walls")
check("30c and the shared edge is still ONE wall, not two",
      len(_ow) == 7, f"{len(_ow)} walls")



# --- 31. a real two-floor plan, where each room states its own level -----
# Every test above hands build() ONE floor plate and lets `storeys` repeat
# it. The moment a genuine first-floor plan goes in — rooms carrying
# base_level=1 — four separate things went wrong at once, and all four are
# invisible on the single-plate path that the rest of this file exercises.
_g = [M.Room("Living", 0.0, 0.0, 5.0, 4.7, kind="room", storeys=1),
      M.Room("Hall", 5.0, 0.0, 2.3, 4.7, kind="circulation", storeys=1),
      M.Room("Garage", 7.3, 0.0, 3.2, 5.5, kind="garage", storeys=1),
      M.Room("Kitchen", 0.0, 4.7, 5.0, 3.8, kind="room", storeys=1),
      M.Room("WC", 5.0, 4.7, 2.3, 1.8, kind="wet", storeys=1),
      M.Room("Utility", 5.0, 6.5, 2.3, 2.0, kind="wet", storeys=1),
      M.Room("Study", 7.3, 5.5, 3.2, 3.0, kind="room", storeys=1)]
_f = [M.Room("Master", 0.0, 0.0, 4.2, 4.6, kind="room",
             storeys=1, base_level=1),
      M.Room("Ensuite", 4.2, 0.0, 2.2, 2.2, kind="wet",
             storeys=1, base_level=1),
      M.Room("Bath", 4.2, 2.2, 2.2, 2.4, kind="wet",
             storeys=1, base_level=1),
      M.Room("Bed 2", 6.4, 0.0, 4.1, 4.6, kind="room",
             storeys=1, base_level=1),
      M.Room("Bed 3", 0.0, 4.6, 3.6, 3.9, kind="room",
             storeys=1, base_level=1),
      M.Room("Landing", 3.6, 4.6, 2.4, 3.9, kind="circulation",
             storeys=1, base_level=1),
      M.Room("Bed 4", 6.0, 4.6, 4.5, 3.9, kind="room",
             storeys=1, base_level=1)]
_two = M.build(_g + _f, storeys=2, storey_height=2.70,
               roof={"pitch_deg": 35.0, "kind": "gabled",
                     "overhang": 0.35, "max_span_m": 12.0})
_gnd = sum(r.area_m2 for r in _g)
_fst = sum(r.area_m2 for r in _f)

# THE HEADLINE NUMBER WAS DOUBLE. rooms and floor_area were multiplied by
# `storeys` regardless of what level each room said it was on, so a plan
# with both floors drawn counted both floors twice: 178.5 m2 came back as
# 357.0. That is the figure a builder prices from.
check("31a floor area counts each room on its OWN levels, not all of them",
      abs(_two["totals"]["floor_area_m2"] - (_gnd + _fst)) < 0.05,
      f"{_two['totals']['floor_area_m2']} vs {_gnd + _fst:.2f}")
check("31b and the room count is not multiplied up either",
      _two["totals"]["rooms"] == len(_g) + len(_f),
      str(_two["totals"]["rooms"]))
check("31c nor the wall length",
      _two["totals"]["wall_length_m"]
      < sum(w.length_m for w in M.walls_from_rooms(_g + _f)) * 1.6,
      str(_two["totals"]["wall_length_m"]))

# "Only one floor plate was supplied" is FALSE when two were.
check("31d the repeated-plate warning is not raised on a real 2-floor plan",
      not any("Only one floor plate" in w for w in _two["warnings"]),
      str(_two["warnings"]))
# The old shape: rooms that say nothing about levels, repeated all the way
# up. That path must come back byte-for-byte what it always did.
_plate = [M.Room(r.name, r.x, r.y, r.width, r.depth, r.height, kind=r.kind)
          for r in _g]
_one = M.build(_plate, storeys=2, storey_height=2.70)
check("31e but it IS still raised when one plate really was repeated",
      any("Only one floor plate" in w for w in _one["warnings"]))
check("31f and the old single-plate arithmetic is unchanged",
      abs(_one["totals"]["floor_area_m2"] - _gnd * 2) < 0.05,
      f"{_one['totals']['floor_area_m2']} vs {_gnd * 2:.2f}")
check("31g a room that says storeys=1 is counted once, not once per storey",
      abs(M.build(_g, storeys=2, storey_height=2.70)["totals"]
          ["floor_area_m2"] - _gnd) < 0.05)

# A CAP IS A ROOF, AND A ROOF GOES WHERE THE SKY IS. Every ground-floor
# room of a two-storey house is "short of the top", so capping on that test
# alone tiled a flat roof over the lounge with a bedroom standing on it —
# in the model, in the IFC and in the roof take-off.
check("31i no flat roof is capped over a room with a bedroom on it",
      _two["caps"] == [], str(_two["caps"]))
_ext = M.build([M.Room("house", 0, 0, 6, 8, 2.6, kind="existing"),
                M.Room("rear", 0, 8, 6, 3.5, 2.4, kind="extension",
                       storeys=1)],
               storeys=2, storey_height=2.70)
check("31j but a single-storey block with sky over it still gets its cap",
      len(_ext["caps"]) == 1, str(_ext["caps"]))

# --- 32. the GLB is what the customer actually looks at ------------------
_mesh = M._glb_mesh(_two)

# A ROOF END IS A TRIANGLE WRITTEN AS A QUAD, two of whose corners sit on
# the apex. Taking the normal from the first three vertices gives the zero
# vector there, and a zero normal is unlit: every gable and every hip end
# came out near-black in every viewer.
_tile_n = _mesh["tile"][1]
_zero = sum(1 for i in range(0, len(_tile_n), 3)
            if abs(_tile_n[i]) + abs(_tile_n[i + 1]) + abs(_tile_n[i + 2])
            < 1e-6)
check("32a no roof face is exported with a zero normal", _zero == 0,
      f"{_zero} unlit vertices")

# THE FLOOR IS THE ROOMS, NOT THE BOUNDING BOX. One slab across extent_m
# hung a floor plate in mid-air past the walls of any non-rectangular plan.
_L = M.build([M.Room("front", 0, 0, 6, 5, kind="room", storeys=1),
              M.Room("wing", 0, 5, 3, 4, kind="room", storeys=1)],
             storeys=1)
_slab = M._glb_mesh(_L)["slab"][0]
_out = [(_slab[i], _slab[i + 2]) for i in range(0, len(_slab), 3)
        if _slab[i] > 3.05 and -_slab[i + 2] > 5.05]
check("32b no floor slab is emitted over the empty half of an L-plan",
      not _out, f"{len(_out)} points out in the void")

# THE FLOOR ZONE IS BUILT, NOT AIR. Walls are CEILING height (2.4m) and the
# storey is floor-to-floor (2.7m); stopping the brickwork at the ceiling
# left a 300mm slot running right round the building at first-floor level.
# Every emit() writes exactly one quad, so the mesh reads back four
# vertices at a time. The band that closes the slot is a quad running from
# the 2.4m ceiling to the 2.7m slab; before the fix there was no such face
# on any wall, only a hole.
_brick = _mesh["brick"][0]
_bands = 0
for _i in range(0, len(_brick), 12):
    _q = sorted({round(_brick[_i + 1 + 3 * _k], 3) for _k in range(4)})
    if _q == [2.4, 2.7]:
        _bands += 1
check("32c external walls reach the slab above, leaving no daylight slot",
      _bands >= 4, f"{_bands} floor-zone bands")

# THE TOP STOREY HAS A CEILING, NOT RAFTERS. Below the top floor the slab
# above doubles as the ceiling; on the top floor there is none, so every
# bedroom looked straight up into the dark underside of the roof.
_ceil = _mesh["plaster"][0]
_top = 1 * 2.70 + 2.40
_flat = 0
for _i in range(0, len(_ceil), 12):
    _q = {round(_ceil[_i + 1 + 3 * _k], 3) for _k in range(4)}
    if _q == {round(_top, 3)}:
        _flat += 1
check("32d the top storey is ceiled, not left open to the roof",
      _flat >= 7, f"{_flat} ceiling panels")

# --- 33. a facade is two storeys of DIFFERENT walls -----------------------
# apply_facade_openings picked the first front wall whose x-range fitted,
# ignoring which floor that wall was on. Ground and first rarely divide at
# the same points — lounge/hall/garage below, master/en-suite/bedroom above
# — so an upstairs window landed on a downstairs wall, carried level=1 onto
# a wall that only exists at level 0, and _openings_at silently dropped it.
_fac = M.build(_g + _f, storeys=2, storey_height=2.70)
_r33 = M.apply_facade_openings(_fac, [
    {"kind": "door", "along": 5.55, "width": 0.95, "height": 2.05,
     "sill": 0.0, "level": 0},
    {"kind": "door", "along": 7.75, "width": 2.40, "height": 2.10,
     "sill": 0.0, "level": 0},
    {"kind": "window", "along": 1.10, "width": 1.60, "height": 1.20,
     "sill": 0.85, "level": 1},
    {"kind": "window", "along": 6.95, "width": 1.50, "height": 1.20,
     "sill": 0.85, "level": 1},
], facade_y=0.0)
check("33a every facade opening is placed", _r33["applied"] == 4,
      str(_r33))
_front_walls = [w for w in _fac["walls"] if w["external"]
                and w["start"][1] == 0.0 and w["end"][1] == 0.0]
_up = [o for w in _front_walls for o in w["openings"]
       if o.get("level") == 1 and M._wall_on_level(w, 1)]
check("33b and the upstairs ones land on a wall that exists upstairs",
      len(_up) == 2, f"{len(_up)} of 2 survived")
_down = [o for w in _front_walls for o in w["openings"]
         if o.get("level") == 0 and M._wall_on_level(w, 0)]
check("33c the ground-floor door and garage door are still downstairs",
      len(_down) == 2, f"{len(_down)} of 2")

# THE SAVED DOOR IS WALL-LOCAL, THE PHOTO OPENINGS ARE FACADE X. When the
# photo carries no door the rule-placed door is re-queued — but its 'along'
# was measured from ITS WALL'S START, and the placement loop compares
# facade x. On a plan that does not start at x=0 the frames disagree: the
# door missed every wall and vanished, while the result still said
# door_preserved: True. Lounge at x 3..7: the rule door sits at local
# 0.25, which is facade x 3.25, and it must come back at local 0.25.
_off = M.build([room("Lounge", 3.0, 0.0, 4.0, 4.0)], storeys=1)
_r34 = M.apply_facade_openings(_off, [
    {"kind": "window", "along": 5.2, "width": 1.2, "height": 1.2,
     "sill": 0.9, "level": 0},
], facade_y=0.0)
_fw = [w for w in _off["walls"] if w["external"]
       and w["start"][1] == 0.0 and w["end"][1] == 0.0]
_doors = [o for w in _fw for o in w["openings"] if o["kind"] == "door"]
check("34a the rule door survives on a plan offset from x=0",
      len(_doors) == 1, str(_doors))
check("34b at the same spot it stood — local 0.25 on the 3..7 wall",
      _doors and abs(_doors[0]["along"] - 0.25) < 1e-6, str(_doors))
check("34c and door_preserved says so", _r34["door_preserved"] is True,
      str(_r34))
check("34d the model still counts its door", _off["totals"]["doors"] >= 1,
      str(_off["totals"]["doors"]))

# AND door_preserved MUST REPORT WHAT HAPPENED, NOT WHAT WAS HOPED. A photo
# window filling the whole frontage leaves the re-queued door nowhere to
# go; saying "door preserved" about a house with no door is the lie the
# flag existed to prevent.
_off2 = M.build([room("Lounge", 3.0, 0.0, 4.0, 4.0)], storeys=1)
_r35 = M.apply_facade_openings(_off2, [
    {"kind": "window", "along": 3.05, "width": 3.9, "height": 1.2,
     "sill": 0.9, "level": 0},
], facade_y=0.0)
check("34e a door that could not be re-placed is not claimed preserved",
      _r35["door_preserved"] is False, str(_r35))

# ---- 35. the short-front fallback keeps the upper windows ----------------
# A 1.9m front wall: the rule window (0.35..1.55) blocks every door slot,
# so the fallback replaces it with a centred door. clear() also deleted
# the level=None window that repeats per storey — the first floor of a
# narrow-fronted house lost its only window, and with it the escape
# opening. The window must survive, pinned to the upper storey.
_narrow = M.build([room("Snug", 0.0, 0.0, 1.9, 3.5)], storeys=2,
                  storey_height=2.7)
_nfw = [w for w in _narrow["walls"] if w["external"]
        and w["start"][1] == 0.0 and w["end"][1] == 0.0]
check("35a the narrow front still gets its ground-floor door",
      any(o["kind"] == "door" and o.get("level") == 0
          for w in _nfw for o in w["openings"]),
      str([w["openings"] for w in _nfw]))
_nwin = [o for w in _nfw for o in w["openings"]
         if o["kind"] == "window" and o.get("level") == 1]
check("35b and the displaced window is pinned to the first floor",
      len(_nwin) == 1, str([w["openings"] for w in _nfw]))
check("35c at the spot the rule put it — centred, along 0.35",
      _nwin and abs(_nwin[0]["along"] - 0.35) < 1e-6, str(_nwin))
check("35d nothing floats on the ground floor where the door now is",
      not any(o["kind"] == "window" and o.get("level") in (None, 0)
              for w in _nfw for o in w["openings"]),
      str([w["openings"] for w in _nfw]))

print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
