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
check("3e two rooms back to back share one wall, not two", len(ws) == 7,
      str(len(ws)))

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
# is a quote that loses money twice over.
one = M.build(plate())
three = M.build(plate(), storeys=3)
for key in ("rooms", "walls", "floor_area_m2", "wall_length_m",
            "wall_area_net_m2", "doors", "windows"):
    check(f"5m {key} scales with the storey count",
          abs(three["totals"][key] - one["totals"][key] * 3) < 0.02,
          f"{three['totals'][key]} vs {one['totals'][key]} x3")

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
check("7d every storey is written", all(f"slab_L{i}" in gs for i in range(3)),
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


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
