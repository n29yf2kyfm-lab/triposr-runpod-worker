"""Tests for the buildability check.

Every test here is a plan that CLOSES geometrically and still could not be
built. That is the whole point of the module: model3d already proves the
rectangles fit together, and proving the rectangles fit together is not the
same as proving somebody can get up the stairs.

The four-bed at the bottom is the real one — 178.5 m2, two floors, roof,
elevations, IFC, a take-off, and no way to reach the first floor. It went
all the way through the pipeline and out the other side before anybody
noticed.

Pure, no network. Run: python building/test_buildable.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import buildable as B   # noqa: E402
import model3d as M     # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


def room(name, x, y, w, d, kind="room", base=0, storeys=1):
    return {"name": name, "kind": kind, "x": x, "y": y,
            "width_m": w, "depth_m": d, "base_level": base,
            "storeys": storeys, "height_m": 2.4,
            "area_m2": round(w * d, 2)}


def codes(findings):
    return [f["code"] for f in findings]


# --- 1. two rooms meeting at a corner share NO wall -------------------------
# This is the measurement everything else rests on. A hall and a kitchen
# that touch at one point look adjacent on a drawing and cannot have a door
# between them — which is exactly what the four-bed did.
a = room("Hall", 5.0, 0.0, 2.3, 4.7, kind="circulation")
b = room("Kitchen", 0.0, 4.7, 5.0, 3.8, kind="kitchen")
check("1a rooms meeting at a single point share zero wall",
      abs(B.shared_wall_m(a, b)) < 1e-9, str(B.shared_wall_m(a, b)))
c = room("Living", 0.0, 0.0, 5.0, 4.7)
check("1b rooms along a common edge share the overlap",
      abs(B.shared_wall_m(a, c) - 4.7) < 1e-9, str(B.shared_wall_m(a, c)))
check("1c and it is the OVERLAP, not the whole edge",
      abs(B.shared_wall_m(room("A", 0, 0, 4, 3),
                          room("B", 2, 3, 6, 3)) - 2.0) < 1e-9)
check("1d rooms that do not touch share nothing",
      abs(B.shared_wall_m(room("A", 0, 0, 2, 2),
                          room("B", 5, 5, 2, 2))) < 1e-9)


# --- 2. Part K arithmetic ---------------------------------------------------
g = B.stair_geometry(2.70)
check("2a a 2.70m storey gets a compliant flight", g is not None)
check("2b rise is at or under 220mm", g["rise_m"] <= 0.220 + 1e-9,
      str(g["rise_m"]))
check("2c going is at or over 220mm", g["going_m"] >= 0.220 - 1e-9,
      str(g["going_m"]))
check("2d pitch is at or under 42 degrees", g["pitch_deg"] <= 42.0 + 1e-6,
      str(g["pitch_deg"]))
check("2e 2R+G lands between 550 and 700",
      0.550 - 1e-9 <= g["two_r_plus_g_m"] <= 0.700 + 1e-9,
      str(g["two_r_plus_g_m"]))
# THE FOUR RULES FIGHT EACH OTHER. Satisfying the 220mm rise cap can still
# break the pitch, and fixing the pitch can break 2R+G at the other end, so
# the flight has to be searched for rather than assumed.
check("2f the flight is long — this is the space nobody leaves room for",
      g["flight_m"] > 2.6, str(g["flight_m"]))


# --- 3. a stair that fits and lands in the right place ---------------------
good = [room("Hall", 0.0, 0.0, 2.4, 5.0, kind="circulation"),
        room("Living", 2.4, 0.0, 5.0, 5.0),
        room("Landing", 0.0, 0.0, 2.4, 5.0, kind="circulation", base=1),
        room("Bed 1", 2.4, 0.0, 5.0, 5.0, base=1)]
stair, f = B.fit_stair(good, 2, 2.70)
check("3a a hall with a landing over it takes a stair", stair is not None)
check("3b and no finding is raised", f == [], str(codes(f)))
check("3c the stair says where it lands",
      stair and stair["lands_in"] == "Landing", str(stair))


# --- 4. THE ONE THAT SHIPPED — a stair that lands in the bathroom ----------
# The four-bed's hall and landing overlapped by 0.10 m2. The flight fitted
# perfectly well; it just arrived inside the family bathroom. Nothing in the
# pipeline was asking where the top step came out.
bad = [room("Hall", 5.0, 0.0, 2.3, 4.7, kind="circulation"),
       room("Living", 0.0, 0.0, 5.0, 4.7),
       room("Bathroom", 4.2, 2.2, 2.2, 2.4, kind="wet", base=1),
       room("Landing", 3.6, 4.6, 2.4, 3.9, kind="circulation", base=1),
       room("Bed 3", 0.0, 4.6, 3.6, 3.9, base=1)]
stair, f = B.fit_stair(bad, 2, 2.70)
check("4a the flight itself fits", stair is not None)
check("4b but the landing check refuses it", "K-LANDING" in codes(f),
      str(codes(f)))
check("4c and it names the room the stair arrives in",
      any("Bathroom" in x["message"] for x in f), str(f))

# A hall too short for any flight is a different refusal, with the number.
tiny = [room("Hall", 0.0, 0.0, 1.2, 2.0, kind="circulation"),
        room("Landing", 0.0, 0.0, 1.2, 2.0, kind="circulation", base=1)]
stair, f = B.fit_stair(tiny, 2, 2.70)
check("4d a hall too small to take a flight is refused with the metres",
      stair is None and "K-FIT" in codes(f), str(codes(f)))
check("4e no circulation at all is its own refusal",
      "K-NOHALL" in codes(B.fit_stair(
          [room("Living", 0, 0, 5, 5)], 2, 2.70)[1]))


# --- 5. a bedroom with no door is not a bedroom ----------------------------
# The four-bed's master had 600mm onto the landing. A door needs 940mm, so
# it was entered through the bathroom — and the model happily reported a
# door there, because it never measured the wall it was putting it in.
narrow = [room("Landing", 3.6, 4.6, 2.4, 3.9, kind="circulation", base=1),
          room("Master bedroom", 0.0, 0.0, 4.2, 4.6, base=1),
          room("Bathroom", 4.2, 2.2, 2.2, 2.4, kind="wet", base=1),
          room("Bed 3", 0.0, 4.6, 3.6, 3.9, base=1)]
_, f = B.circulation(narrow, 2, 1)
check("5a 600mm of wall onto the landing is refused as a doorway",
      "M-NODOOR" in codes(f), str(codes(f)))
check("5b and the finding carries the measurement",
      any(x["code"] == "M-NODOOR" and "0.60m" in x["message"] for x in f),
      str([x["message"] for x in f if x["code"] == "M-NODOOR"]))

# Push the master/bathroom wall out by 400mm and the complaint goes away.
# (Widening the LANDING instead would overlap Bed 3, which is a different
# fault and would keep the finding alive for the wrong reason.)
wide = [room("Landing", 3.6, 4.6, 2.4, 3.9, kind="circulation", base=1),
        room("Master bedroom", 0.0, 0.0, 4.6, 4.6, base=1),
        room("Bathroom", 4.6, 2.2, 1.8, 2.4, kind="wet", base=1),
        room("Bed 3", 0.0, 4.6, 3.6, 3.9, base=1)]
_, f2 = B.circulation(wide, 2, 1)
check("5c a full metre of wall onto the landing clears it",
      "M-NODOOR" not in codes(f2), str(codes(f2)))


# --- 6. inner rooms, and the one Part B will not have ----------------------
chain = [room("Hall", 0.0, 0.0, 2.0, 8.0, kind="circulation"),
         room("Living", 2.0, 0.0, 4.0, 4.0),
         room("Kitchen", 2.0, 4.0, 4.0, 4.0, kind="kitchen"),
         room("Study", 6.0, 4.0, 3.0, 4.0)]
_, f = B.circulation(chain, 1, 0)
check("6a a room off a kitchen off the hall is refused, not merely noted",
      "CIRC-INNER2" in codes(f), str(codes(f)))
check("6b and the reason says the access room is a kitchen",
      any("kitchen" in x["message"] for x in f if x["code"] == "CIRC-INNER2"))
# One room deep off a hall is normal and must NOT be flagged as a refusal.
plain = [room("Hall", 0.0, 0.0, 2.0, 5.0, kind="circulation"),
         room("Living", 2.0, 0.0, 4.0, 5.0)]
_, f = B.circulation(plain, 1, 0)
check("6c a room straight off the hall raises nothing", f == [], str(codes(f)))
# A room touching nothing but corners cannot be entered at all.
island = [room("Hall", 0.0, 0.0, 2.0, 2.0, kind="circulation"),
          room("Store", 2.0, 2.0, 2.0, 2.0)]
_, f = B.circulation(island, 1, 0)
check("6d a room reachable only across a corner is refused",
      "CIRC-ISLAND" in codes(f), str(codes(f)))


# --- 7. escape windows ------------------------------------------------------
def _model(rooms, openings, storeys=2):
    """A minimal model dict with one external wall carrying openings."""
    return {"rooms": rooms, "storeys": storeys, "storey_height_m": 2.7,
            "walls": [{"external": True, "start": [0.0, 0.0],
                       "end": [6.0, 0.0], "length_m": 6.0, "height_m": 2.4,
                       "openings": openings}],
            "totals": {"floor_area_m2": 60.0}}

bed = room("Bed 1", 0.0, 0.0, 4.0, 4.0, base=1)
big = [{"kind": "window", "along": 0.5, "width": 1.2, "height": 1.1,
        "sill": 0.85, "level": 1}]
check("7a a 1.2 x 1.1m window at 850mm sill is an escape route",
      B.escape(_model([bed], big)) == [],
      str(codes(B.escape(_model([bed], big)))))

high = [{"kind": "window", "along": 0.5, "width": 1.2, "height": 1.1,
         "sill": 1.35, "level": 1}]
check("7b the same window at a 1350mm sill is not",
      "B-ESCAPE" in codes(B.escape(_model([bed], high))))

small = [{"kind": "window", "along": 0.5, "width": 0.7, "height": 0.4,
          "sill": 0.85, "level": 1}]
check("7c and neither is one under 450mm in a direction",
      "B-ESCAPE" in codes(B.escape(_model([bed], small))))
check("7d a bedroom with no window at all is refused",
      "B-ESCAPE" in codes(B.escape(_model([bed], []))))
# A ground-floor bedroom is not asked for an escape window.
check("7e the ground floor is not asked",
      B.escape(_model([room("Bed 1", 0, 0, 4, 4)], [], storeys=1)) == [])


# --- 8. Part O, simplified ---------------------------------------------------
def _glazed(area):
    return {"rooms": [], "storeys": 2, "storey_height_m": 2.7,
            "walls": [{"external": True, "start": [0, 0], "end": [10, 0],
                       "openings": [{"kind": "window", "along": 0.1,
                                     "width": area, "height": 1.0,
                                     "level": 0}]}],
            "totals": {"floor_area_m2": 100.0}}

check("8a 10% glazing passes on any orientation",
      B.overheating(_glazed(10.0), "W") == [])
check("8b 24% fails even facing north, which is the softest limit",
      codes(B.overheating(_glazed(24.0), "N")) == ["O-GLAZING"])
check("8c and failing north is reported as failing on every orientation",
      any("every orientation" in x["message"]
          for x in B.overheating(_glazed(24.0), "N")))
check("8d 16% is a west problem only",
      B.overheating(_glazed(16.0), "N") == []
      and codes(B.overheating(_glazed(16.0), "W")) == ["O-GLAZING"])
check("8e a west failure is a change, not a refusal",
      B.overheating(_glazed(16.0), "W")[0]["severity"] == "change")


# --- 9. THE FOUR-BED, end to end -------------------------------------------
# Built with the real module, exactly as it shipped, and every one of the
# three fatal findings the red team raised is found from the model alone.
R = M.Room
_rooms = [
    R("Living room", 0.0, 0.0, 5.0, 4.7, kind="room", storeys=1),
    R("Hall", 5.0, 0.0, 2.3, 4.7, kind="circulation", storeys=1),
    R("Garage", 7.3, 0.0, 3.2, 5.5, kind="garage", storeys=1),
    R("Kitchen/diner", 0.0, 4.7, 5.0, 3.8, kind="kitchen", storeys=1),
    R("WC", 5.0, 4.7, 2.3, 1.8, kind="wet", storeys=1),
    R("Utility", 5.0, 6.5, 2.3, 2.0, kind="wet", storeys=1),
    R("Study", 7.3, 5.5, 3.2, 3.0, kind="room", storeys=1),
    R("Master bedroom", 0.0, 0.0, 4.2, 4.6, kind="room", storeys=1, base_level=1),
    R("En-suite", 4.2, 0.0, 2.2, 2.2, kind="wet", storeys=1, base_level=1),
    R("Bathroom", 4.2, 2.2, 2.2, 2.4, kind="wet", storeys=1, base_level=1),
    R("Bedroom 2", 6.4, 0.0, 4.1, 4.6, kind="room", storeys=1, base_level=1),
    R("Bedroom 3", 0.0, 4.6, 3.6, 3.9, kind="room", storeys=1, base_level=1),
    R("Landing", 3.6, 4.6, 2.4, 3.9, kind="circulation", storeys=1, base_level=1),
    R("Bedroom 4", 6.0, 4.6, 4.5, 3.9, kind="room", storeys=1, base_level=1),
]
_m = M.build(_rooms, storeys=2, storey_height=2.70,
             roof={"pitch_deg": 35.0, "kind": "gabled", "overhang": 0.35,
                   "max_span_m": 12.0})
_res = B.check(_m)
_c = codes(_res["findings"])
check("9a the house that shipped is not buildable", _res["buildable"] is False)
check("9b the stair lands somewhere it may not", "K-LANDING" in _c, str(_c))
check("9c two bedrooms have no doorway onto circulation",
      sum(1 for x in _res["findings"] if x["code"] == "M-NODOOR") == 2, str(_c))
check("9d and they are the master and bedroom 2",
      {x["room"] for x in _res["findings"] if x["code"] == "M-NODOOR"}
      == {"Master bedroom", "Bedroom 2"},
      str({x["room"] for x in _res["findings"] if x["code"] == "M-NODOOR"}))
check("9e the kitchen is flagged as reached through another room",
      any(x["room"] == "Kitchen/diner" and x["code"].startswith("CIRC")
          for x in _res["findings"]), str(_c))
# Assert WHICH refusals, not how many. A count is hostage to how the
# findings happen to be split, and that is exactly the brittleness that put
# two tests in model3d.py in the position of defending bugs.
_refusals = {x["code"] for x in _res["findings"] if x["severity"] == "refuse"}
check("9f the refusals are the stair, the doorways and the deep rooms",
      _refusals == {"K-LANDING", "M-NODOOR", "CIRC-DEADEND"}, str(_refusals))
# The study touches only the garage, the WC and the utility. It has plenty
# of shared wall — it just has none of it onto anywhere you can walk from.
check("9f2 the study is stuck behind the garage and the wet rooms",
      any(x["code"] == "CIRC-DEADEND" and x["room"] == "Study"
          for x in _res["findings"]),
      str([(x["code"], x["room"]) for x in _res["findings"]]))
check("9g describe() prints something a builder can act on",
      "REFUSE" in B.describe(_res) and "AD K" in B.describe(_res))

# AND THE FIX WORKS. Stack the landing over the hall and give the two
# bedrooms a doorway, and the same check passes — so this is a test of the
# design, not a module that always says no.
_fixed = [r for r in _rooms if r.name not in
          ("Landing", "Bathroom", "En-suite", "Master bedroom", "Bedroom 2",
           "Bedroom 3", "Bedroom 4")]
_fixed += [
    R("Landing", 5.0, 0.0, 2.3, 8.5, kind="circulation", storeys=1, base_level=1),
    R("Master bedroom", 0.0, 0.0, 5.0, 4.7, kind="room", storeys=1, base_level=1),
    R("Bedroom 3", 0.0, 4.7, 5.0, 3.8, kind="room", storeys=1, base_level=1),
    R("Bedroom 2", 7.3, 0.0, 3.2, 4.7, kind="room", storeys=1, base_level=1),
    R("Bedroom 4", 7.3, 4.7, 3.2, 3.8, kind="room", storeys=1, base_level=1),
]
_m2 = M.build(_fixed, storeys=2, storey_height=2.70)
_res2 = B.check(_m2)
_c2 = codes(_res2["findings"])
check("9h a landing stacked over the hall takes the stair",
      "K-LANDING" not in _c2 and "K-FIT" not in _c2, str(_c2))
check("9i and every bedroom then has its own doorway",
      "M-NODOOR" not in _c2, str(_c2))

# --- 10. the pipeline cannot hand over an unbuildable plan quietly --------
class _Prog:
    def stage(self, *a, **k):
        pass


import tempfile   # noqa: E402
_plan = {"rooms": [{"name": r.name, "kind": r.kind, "x": r.x, "y": r.y,
                    "width_m": r.width, "depth_m": r.depth,
                    "storeys": r.storeys, "base_level": r.base_level}
                   for r in _rooms],
         "storeys": 2, "storey_height_m": 2.70}
with tempfile.TemporaryDirectory() as _d:
    _arts, _extra = M.run_mode({"plan": _plan}, _Prog(), _d)
check("10a model mode reports buildability alongside the model",
      "buildable" in _extra and _extra["buildable"]["buildable"] is False,
      str(_extra.get("buildable", {}).get("counts")))
check("10b and every refusal is promoted into the warnings",
      sum(1 for w in _extra["warnings"] if w.startswith("NOT BUILDABLE:"))
      == _extra["buildable"]["counts"]["refuse"],
      str([w for w in _extra["warnings"] if w.startswith("NOT BUILDABLE")]))
check("10c the artifacts still came out — this reports, it does not block",
      bool(_arts))

# --- 11. the review's wiring fixes, locked down ---------------------------
# 11a THE STAIR IS IN THE EXPORTED MODEL. The check used to run after the
# export, so every file on disk described a house with no staircase.
with tempfile.TemporaryDirectory() as _d2:
    _a3, _x3 = M.run_mode({"plan": {
        "rooms": [{"name": "Hall", "kind": "circulation",
                   "x": 0, "y": 0, "width_m": 2.4, "depth_m": 5.0,
                   "storeys": 1},
                  {"name": "Living", "x": 2.4, "y": 0,
                   "width_m": 5.0, "depth_m": 5.0, "storeys": 1},
                  {"name": "Landing", "kind": "circulation",
                   "x": 0, "y": 0, "width_m": 2.4, "depth_m": 5.0,
                   "storeys": 1, "base_level": 1},
                  {"name": "Bed 1", "x": 2.4, "y": 0,
                   "width_m": 5.0, "depth_m": 5.0,
                   "storeys": 1, "base_level": 1}],
        "storeys": 2, "storey_height_m": 2.70}}, _Prog(), _d2)
    import json as _json
    _js = _json.load(open(os.path.join(
        _d2, [f for f in os.listdir(_d2) if f.endswith(".json")][0])))
check("11a the exported JSON carries the fitted stair",
      "stair" in _js and _js["stair"].get("lands_in") == "Landing",
      str(_js.get("stair")))
# The fixture's rule-placed glazing genuinely fails Part O now that every
# storey is counted — which is itself the fix working. What 11b guards is
# ABSORPTION: the file on disk says exactly what the API caller was told.
check("11b and the exported verdict matches what the API caller was told",
      _js.get("buildable", {}).get("buildable")
      == _x3["buildable"]["buildable"]
      and _js["buildable"]["counts"] == _x3["buildable"]["counts"],
      str(_js.get("buildable", {}).get("counts")))
# 11c THE RULES ENGINE RUNS. regs.py was imported by nothing but its own
# tests; now every model job gets its stair judged and purge checked.
check("11c regs findings ride alongside the model",
      "regs" in _x3 and _x3["regs"]["checked"] > 0,
      str(_x3.get("regs", {}).get("counts")))
check("11d and the stair the fitter designed passes the rules engine",
      _x3["regs"]["counts"]["fail"] == 0, str(_x3["regs"]["counts"]))

# 11e PART O COUNTS EVERY STOREY A WINDOW REPEATS ON. A repeated-plate
# window was counted once against an every-storey floor area.
_rep = {"rooms": [], "storeys": 2, "storey_height_m": 2.7,
        "walls": [{"external": True, "start": [0, 0], "end": [10, 0],
                   "openings": [{"kind": "window", "along": 0.1,
                                 "width": 10.0, "height": 1.2,
                                 "level": None}]}],
        "totals": {"floor_area_m2": 100.0}}
check("11e a level=None window is glazing on BOTH storeys",
      codes(B.overheating(_rep, "N")) == ["O-GLAZING"],
      str(B.overheating(_rep, "N")))
# 12.0m2 x2 = 24% fails N; counted once it was 12% and passed silently.

# 11f A PARTY WALL GETS NO RULE WINDOWS. A semi's shared flank was sky.
_semi = M.build([M.Room("Living", 0, 0, 5.0, 5.0, kind="room")],
                storeys=1, party_edges=[["x", 0.0]])
_party = [w for w in _semi["walls"] if w.get("party")]
check("11f the shared flank is marked party and carries no windows",
      len(_party) == 1 and not any(
          o["kind"] == "window" for o in _party[0]["openings"]),
      str(_party))
check("11g void_facing now survives into the wall JSON",
      all("void_facing" in w for w in _semi["walls"]))

# --- 12. edge cases that were bugs -----------------------------------------
# 12a A THREE-STOREY HOUSE NEEDS TWO FLIGHTS. Only level 0's stair was ever
# checked, so a top floor nothing could reach raised no K finding at all.
_r12 = B.check(M.build(
    [M.Room("Hall", 0, 0, 2.4, 5.0, kind="circulation", storeys=1),
     M.Room("Living", 2.4, 0, 5.0, 5.0, storeys=1),
     M.Room("Landing", 0, 0, 2.4, 5.0, kind="circulation",
            storeys=1, base_level=1),
     M.Room("Bed 1", 2.4, 0, 5.0, 5.0, storeys=1, base_level=1),
     M.Room("Bed 2", 0, 0, 7.4, 5.0, storeys=1, base_level=2)],
    storeys=3, storey_height=2.7))
check("12a an unreachable top floor raises a K refusal",
      any(f["code"].startswith("K-") for f in _r12["findings"]),
      str(sorted({f["code"] for f in _r12["findings"]})))
check("12b and every inter-storey flight is reported",
      len(_r12.get("stairs", [])) == 2, str(len(_r12.get("stairs", []))))

# 12c A ROOM ABOVE THE BUILDING'S TOP IS REFUSED, NOT VANISHED. It used to
# stay in the schedule while contributing to no wall, floor or export.
try:
    M.build([M.Room("Living", 0, 0, 5, 5, storeys=1),
             M.Room("Ghost", 0, 0, 5, 5, storeys=1, base_level=3)],
            storeys=1)
    check("12c a room floating above the top storey is refused", False)
except M.ModelError as e:
    check("12c a room floating above the top storey is refused",
          "base_level" in str(e), str(e))

# 12d ...and validation refuses it at the door, naming the field.
import validation as _V
try:
    _V.parse_job({"mode": "model", "plan": {
        "rooms": [{"name": "A", "x": 0, "y": 0, "width_m": 5, "depth_m": 5},
                  {"name": "Ghost", "x": 0, "y": 0, "width_m": 5,
                   "depth_m": 5, "base_level": 4}],
        "storeys": 1}})
    check("12d validation refuses base_level above plan.storeys", False)
except _V.InputError as e:
    check("12d validation refuses base_level above plan.storeys",
          "base_level" in str(e) and "storeys" in str(e), str(e))

# 12e ESCAPE IS A MATTER OF KIND, NOT NAMING. A first-floor habitable room
# with no window passed silently because its name did not start with "bed".
_r12e = B.check(M.build(
    [M.Room("Hall", 0, 0, 2.4, 5.0, kind="circulation", storeys=1),
     M.Room("Living", 2.4, 0, 5.0, 5.0, storeys=1),
     M.Room("Landing", 0, 0, 2.4, 5.0, kind="circulation",
            storeys=1, base_level=1),
     M.Room("Studio", 2.4, 0, 5.0, 5.0, storeys=1, base_level=1)],
    storeys=2, storey_height=2.7, wall_openings=False))
_esc = [f for f in _r12e["findings"] if f["code"] == "B-ESCAPE"]
check("12e a windowless first-floor Studio raises an escape finding",
      any(f["room"] == "Studio" for f in _esc), str(_esc))
check("12f as a change, while a windowless BEDROOM stays a refusal",
      all(f["severity"] == "change" for f in _esc if f["room"] == "Studio")
      and any(x["code"] == "B-ESCAPE" and x["severity"] == "refuse"
              for x in B.check(M.build(
                  [M.Room("Hall", 0, 0, 2.4, 5.0, kind="circulation",
                          storeys=1),
                   M.Room("Living", 2.4, 0, 5.0, 5.0, storeys=1),
                   M.Room("Landing", 0, 0, 2.4, 5.0, kind="circulation",
                          storeys=1, base_level=1),
                   M.Room("Bed 1", 2.4, 0, 5.0, 5.0, storeys=1,
                          base_level=1)],
                  storeys=2, storey_height=2.7,
                  wall_openings=False))["findings"]))

# 12g THE ESCAPE WINDOW AN INNER ROOM LEANS ON IS ACTUALLY CHECKED. The
# CIRC-INNER downgrade cited AD B 2.11's escape-window allowance, but
# escape() starts at level 1, so on the ground floor nobody ever looked for
# the window — a windowless inner study passed on a condition nothing had
# verified.
_inner = [M.Room("Hall", 0, 0, 2.0, 4.0, kind="circulation"),
          M.Room("Living", 2.0, 0, 4.0, 4.0),
          M.Room("Study", 6.0, 0, 3.0, 4.0)]
_rg = B.check(M.build(_inner, storeys=1, wall_openings=False))
_gi = [f for f in _rg["findings"] if f["code"] == "CIRC-INNER"]
check("12g a windowless ground-floor inner room is refused, not noted",
      any(f["room"] == "Study" and f["severity"] == "refuse" for f in _gi),
      str(_gi))
check("12g2 and the refusal says the 2.11 allowance does not apply",
      any("escape window" in f["message"] for f in _gi), str(_gi))
check("12g3 so the plan is not buildable", _rg["buildable"] is False)
# Give the same study its rule glazing (1.2 x 1.2m at a 900mm sill — a
# compliant escape window) and the allowance genuinely holds: back to a
# 'change'.
_rg2 = B.check(M.build(_inner, storeys=1))
check("12g4 with a compliant window the inner room is a change again",
      [f["severity"] for f in _rg2["findings"]
       if f["code"] == "CIRC-INNER"] == ["change"],
      str([(f["code"], f["severity"]) for f in _rg2["findings"]]))

# 12h SEVERITY FOLLOWS THE KIND TOO. 12e made escape COVERAGE a matter of
# kind, not naming — and then a first-floor {name: Nursery, kind: bedroom}
# with no way out was still only a 'change' because the severity was keyed
# on the name starting "bed"/"master". Somebody sleeps in there; what the
# door label says does not change the fire.
_rn = B.check(M.build(
    [M.Room("Hall", 0, 0, 2.4, 5.0, kind="circulation", storeys=1),
     M.Room("Living", 2.4, 0, 5.0, 5.0, storeys=1),
     M.Room("Landing", 0, 0, 2.4, 5.0, kind="circulation",
            storeys=1, base_level=1),
     M.Room("Nursery", 2.4, 0, 5.0, 5.0, kind="bedroom",
            storeys=1, base_level=1)],
    storeys=2, storey_height=2.7, wall_openings=False))
check("12h a windowless first-floor Nursery of kind bedroom is a refusal",
      any(f["code"] == "B-ESCAPE" and f["room"] == "Nursery"
          and f["severity"] == "refuse" for f in _rn["findings"]),
      str([(f["code"], f["severity"], f["room"])
           for f in _rn["findings"]]))
check("12h2 so the renamed bedroom no longer passes the gate",
      _rn["buildable"] is False)

# And the doorway check keys on kind the same way: the narrow fixture from
# section 5, with the master renamed to Nursery and declared kind=bedroom,
# still has only 600mm onto the landing.
_nursery_narrow = [
    room("Landing", 3.6, 4.6, 2.4, 3.9, kind="circulation", base=1),
    room("Nursery", 0.0, 0.0, 4.2, 4.6, kind="bedroom", base=1),
    room("Bathroom", 4.2, 2.2, 2.2, 2.4, kind="wet", base=1),
    room("Bed 3", 0.0, 4.6, 3.6, 3.9, base=1)]
_, _fn = B.circulation(_nursery_narrow, 2, 1)
check("12h3 a kind=bedroom room with 600mm onto circulation gets M-NODOOR",
      any(x["code"] == "M-NODOOR" and x["room"] == "Nursery" for x in _fn),
      str(codes(_fn)))

print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
