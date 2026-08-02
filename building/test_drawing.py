"""Tests for Drawing Mode — measuring off a 2D PDF.

The arithmetic here is easy and the scale is not. A wrong scale produces a
complete, plausible, uniformly wrong bill of quantities — nothing in the
output looks odd, because every number is wrong together. So most of these
tests are about the scale refusing to be guessed at.

Run: python building/test_drawing.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import drawing as D  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


def pts(mm):
    """Millimetres on paper -> PDF points."""
    return mm / D.MM_PER_POINT


# ---- 1. reading the scale note --------------------------------------------
for text, want in [("Scale 1:50", 50), ("1:100", 100), ("SCALE 1 : 20", 20),
                   ("scale 1/50 @ A1", 50), ("Drawing at 1:1250", 1250),
                   ("Proposed Extension  1:100  @ A3", 100)]:
    check(f"1a {text!r} -> 1:{want}", D.parse_scale_note(text) == want,
          str(D.parse_scale_note(text)))

check("1b no scale in the text", D.parse_scale_note("Proposed Extension") is None)
check("1c empty", D.parse_scale_note("") is None)
check("1d absurd ratio refused", D.parse_scale_note("1:99999") is None)

# "Do not scale" is an instruction, not decoration.
for text in ("NTS", "N.T.S.", "Not to scale", "DO NOT SCALE — 1:50"):
    check(f"1e {text!r} is not-to-scale", D.is_not_to_scale(text))
    check(f"1f {text!r} yields no ratio", D.parse_scale_note(text) is None)

check("1g sheet size read from the note", D.parse_sheet_note("1:50 @ A1") == "A1")
check("1h sheet in brackets", D.parse_sheet_note("1:100 (A3)") == "A3")
check("1i no sheet stated", D.parse_sheet_note("1:50") is None)


# ---- 2. detecting the actual sheet ----------------------------------------
for name, (short, long) in D.PAPER_SIZES_MM.items():
    check(f"2a portrait {name}", D.detect_paper_size(pts(short), pts(long)) == name)
    check(f"2b landscape {name}", D.detect_paper_size(pts(long), pts(short)) == name)

check("2c a non-standard page is not forced into a size",
      D.detect_paper_size(pts(500), pts(700)) is None)
check("2d nothing in, nothing out", D.detect_paper_size(None, None) is None)


# ---- 3. THE TRAP: a sheet printed down ------------------------------------
# An architect issues at A1, everyone else prints and emails A3, and the title
# block still says A1 because the title block is part of the drawing. Measure
# at the stated scale and every length is half, every area a quarter.
ratio, note = D.effective_scale(50, "A1", "A3")
check("3a A1 drawing on A3 paper doubles the ratio", abs(ratio - 100) < 0.5,
      str(ratio))
check("3b and it says so plainly", note and "1:100" in note, str(note))
check("3c naming the area error too", note and "4.00x" in note, str(note))

ratio, note = D.effective_scale(100, "A3", "A1")
check("3d scaled UP is handled as well", abs(ratio - 50) < 0.5, str(ratio))

ratio, note = D.effective_scale(50, "A1", "A1")
check("3e matching sheets need no correction", ratio == 50 and note is None)
ratio, note = D.effective_scale(50, None, "A3")
check("3f no stated sheet means no correction", ratio == 50 and note is None)


# ---- 4. dimension strings -------------------------------------------------
for text, want in [("3600", 3600.0), ("3600mm", 3600.0), ("3.6m", 3600.0),
                   ("360cm", 3600.0), ("3,600", 3600.0), ("12000", 12000.0)]:
    got = D.parse_dimension(text)
    check(f"4a {text!r} -> {want}mm", got is not None and abs(got - want) < 1e-6,
          str(got))

# A bare small number on a drawing is a room label or a door number far more
# often than it is a 12mm dimension.
check("4b a bare small number is not a dimension",
      D.parse_dimension("12") is None)
check("4c but 12mm stated explicitly is", D.parse_dimension("12mm") == 12.0)
check("4d text is not a dimension", D.parse_dimension("KITCHEN") is None)
check("4e a zero is not a dimension", D.parse_dimension("0") is None)


# ---- 5. calibrating against a dimension -----------------------------------
# A wall annotated 3600mm, drawn 72mm long on paper -> 1:50.
ratio = D.scale_from_dimension(pts(72.0), 3600.0)
check("5a calibration recovers the ratio", abs(ratio - 50) < 0.01, str(ratio))

check("5b a near-miss snaps to a standard scale",
      D.nearest_common_scale(49.7) == 50)
check("5c and so does the other side", D.nearest_common_scale(101.5) == 100)
# Forcing 1:73 to 1:100 would be inventing a number.
check("5d something genuinely odd is NOT snapped",
      D.nearest_common_scale(73.0) is None, str(D.nearest_common_scale(73.0)))

for bad in ((0, 3600), (-5, 3600), (100, 0), (100, -1)):
    try:
        D.scale_from_dimension(*bad)
        check(f"5e {bad} refused", False)
    except D.DrawingError:
        check(f"5e {bad} refused", True)


# ---- 6. resolving the scale -----------------------------------------------
s = D.resolve_scale(note_text="Proposed Extension  Scale 1:50 @ A1",
                    page_size_pt=(pts(594), pts(841)))
check("6a title block on the right sheet", s.ratio == 50, str(s.ratio))
check("6b source recorded", s.source == "title_block")

# The trap, end to end.
s = D.resolve_scale(note_text="Scale 1:50 @ A1",
                    page_size_pt=(pts(297), pts(420)))
check("6c A1 note on an A3 page resolves to 1:100", abs(s.ratio - 100) < 0.5,
      str(s.ratio))
check("6d and the correction is in the notes",
      any("1:100" in n for n in s.notes), str(s.notes))

# Calibration beats the title block, and agreement is stated.
s = D.resolve_scale(note_text="Scale 1:50",
                    calibration={"measured_points": pts(72.0),
                                 "stated_mm": 3600.0})
check("6e agreement is reported", s.source == "calibration+note", s.source)
check("6f and said out loud", any("agree" in n for n in s.notes), str(s.notes))

# THE refusal. If the note and the drawing disagree, one of them describes a
# different sheet, and measuring on either is a guess.
try:
    D.resolve_scale(note_text="Scale 1:50",
                    calibration={"measured_points": pts(36.0),
                                 "stated_mm": 3600.0})
    check("6g disagreement refused", False)
except D.DrawingError as e:
    check("6g disagreement refused", "disagree" in str(e), str(e))
    check("6h refusal quantifies it", "%" in str(e))

try:
    D.resolve_scale(note_text="Proposed layout — DO NOT SCALE")
    check("6i a not-to-scale sheet is refused", False)
except D.DrawingError as e:
    check("6i a not-to-scale sheet is refused", "not to scale" in str(e))

try:
    D.resolve_scale(note_text="Proposed Extension, ground floor")
    check("6j no scale anywhere is refused", False)
except D.DrawingError as e:
    check("6j no scale anywhere is refused", "no drawing scale" in str(e))
    check("6k and explains the consequence", "entirely wrong" in str(e), str(e))

s = D.resolve_scale(override_ratio=50)
check("6l an override is accepted", s.ratio == 50 and s.source == "override")


# ---- 7. nothing is measured on an unconfirmed scale -----------------------
# An auto-detected scale is bimodal — exactly right, or wrong by a whole
# factor. A 2x error passes every sanity check a builder would apply, because
# every number on the quote is consistently wrong together.
unconfirmed = D.Scale(50, "title_block")
check("7a a fresh scale is not confirmed", not unconfirmed.confirmed)
try:
    D.measure_area([(0, 0), (100, 0), (100, 100), (0, 100)], unconfirmed)
    check("7b measuring on it is refused", False)
except D.DrawingError as e:
    check("7b measuring on it is refused", "not been confirmed" in str(e))
    check("7c and says how to proceed", "confirm_scale=true" in str(e))

confirmed = D.Scale(50, "title_block", confirmed=True)
check("7d a confirmed scale measures", D.require_confirmation(confirmed))


# ---- 8. the arithmetic ----------------------------------------------------
# At 1:50, one point is 0.3528mm on paper = 17.64mm real.
s50 = D.Scale(50, "test", confirmed=True)
check("8a metres per point", abs(s50.metres_per_point - 0.01764) < 1e-5,
      str(s50.metres_per_point))

# A room drawn 72mm x 36mm on paper at 1:50 is 3.6m x 1.8m = 6.48 m2.
room = [(0, 0), (pts(72), 0), (pts(72), pts(36)), (0, pts(36))]
r = D.measure_area(room, s50, name="Kitchen")
check("8b area is right", abs(r["area_m2"] - 6.48) < 0.01, str(r["area_m2"]))
check("8c perimeter is right", abs(r["perimeter_m"] - 10.8) < 0.01,
      str(r["perimeter_m"]))
check("8d name carried", r["name"] == "Kitchen")

# Winding direction must not matter — a room traced clockwise is the same room.
check("8e winding direction is irrelevant",
      abs(D.measure_area(list(reversed(room)), s50)["area_m2"] - 6.48) < 0.01)

# Deductions. Forgetting an opening is the commonest takeoff error there is,
# so the subtraction happens here rather than in the caller's head.
hole = [(pts(10), pts(10)), (pts(20), pts(10)),
        (pts(20), pts(20)), (pts(10), pts(20))]
r = D.measure_area(room, s50, name="Wall", deductions=[hole])
check("8f gross recorded separately", abs(r["gross_area_m2"] - 6.48) < 0.01)
check("8g deduction applied", abs(r["deductions_m2"] - 0.25) < 0.01,
      str(r["deductions_m2"]))
check("8h net is gross minus deductions",
      abs(r["area_m2"] - (r["gross_area_m2"] - r["deductions_m2"])) < 0.01)

# A deduction bigger than the thing it comes out of is a tracing error.
try:
    D.measure_area(hole, s50, deductions=[room])
    check("8i over-deduction refused", False)
except D.DrawingError as e:
    check("8i over-deduction refused", "larger than" in str(e))

try:
    D.measure_area([(0, 0), (10, 10)], s50)
    check("8j a line has no area", False)
except D.DrawingError as e:
    check("8j a line has no area", "does not enclose" in str(e))

tiny = [(0, 0), (1, 0), (1, 1), (0, 1)]
check("8k a stray mark is flagged, not silently priced",
      "warning" in D.measure_area(tiny, s50))

# Lengths.
run = [(0, 0), (pts(72), 0), (pts(72), pts(36))]
l = D.measure_length(run, s50, name="Skirting")
check("8l length is right", abs(l["length_m"] - 5.4) < 0.01, str(l["length_m"]))
check("8m segments counted", l["segments"] == 2)
closed = D.measure_length(room, s50, closed=True)
check("8n a closed run is a perimeter",
      abs(closed["length_m"] - 10.8) < 0.01, str(closed["length_m"]))
try:
    D.measure_length([(0, 0)], s50)
    check("8o one point has no length", False)
except D.DrawingError:
    check("8o one point has no length", True)

# Scale changes everything, proportionally — the whole point.
s100 = D.Scale(100, "test", confirmed=True)
check("8p double the ratio, quadruple the area",
      abs(D.measure_area(room, s100)["area_m2"] - 25.92) < 0.02,
      str(D.measure_area(room, s100)["area_m2"]))


# ---- 9. counting is honest about itself -----------------------------------
# Counting is what the benchmarks say machines are worst at (0.40-0.55 on
# doors and windows), so this records marks rather than claiming detection.
c = D.count_items([(1, 1), (2, 2), (3, 3)], name="Sockets")
check("9a counted", c["count"] == 3)
check("9b and says it was not automatic", "not detected" in c["method"])
check("9c nothing marked is zero", D.count_items([])["count"] == 0)
check("9d None is zero", D.count_items(None)["count"] == 0)


# ---- 10. scanned pages ----------------------------------------------------
check("10a a page with no vectors and no text reads as scanned",
      D.looks_scanned({"vector": False, "words": []}))
check("10b a vector page does not",
      not D.looks_scanned({"vector": True, "words": []}))
check("10c a text-bearing page does not",
      not D.looks_scanned({"vector": False, "words": [{}] * 20}))


# ---- 11. handler entry ----------------------------------------------------
class _Prog:
    def stage(self, *a, **k):
        pass


import tempfile  # noqa: E402
OUT = os.path.join(tempfile.gettempdir(), "drawing-test")

# Inspect: no quantities until the scale is agreed.
arts, extra = D.run(
    {"scale_note": "Proposed Extension  1:50 @ A1",
     "page_size_pt": [pts(594), pts(841)],
     "traced": {"areas": [{"name": "Kitchen", "ring": room}]},
     "scan_id": "t1"}, _Prog(), OUT)
d = extra["drawing"]
check("11a unconfirmed scale yields no quantities",
      d["status"] == "scale_unconfirmed", str(d.get("status")))
check("11b and no areas are reported", "areas" not in d)
check("11c but it says what to do next", "confirm_scale=true" in d["next"])
check("11d an artifact is still written", os.path.exists(arts[0][0]))

# Measure: same job, scale confirmed.
arts, extra = D.run(
    {"scale_note": "Proposed Extension  1:50 @ A1",
     "page_size_pt": [pts(594), pts(841)],
     "confirm_scale": True,
     "traced": {
         "areas": [{"name": "Kitchen", "ring": room}],
         "lengths": [{"name": "Skirting", "path": run}],
         "counts": [{"name": "Sockets", "positions": [(1, 1), (2, 2)]}]},
     "scan_id": "t2"}, _Prog(), OUT)
d = extra["drawing"]
check("11e confirmed scale measures", d["status"] == "measured")
check("11f area totalled", abs(d["totals"]["area_m2"] - 6.48) < 0.01,
      str(d["totals"]["area_m2"]))
check("11g length totalled", abs(d["totals"]["length_m"] - 5.4) < 0.01)
check("11h counts totalled", d["totals"]["count"] == 2)
check("11i basis is stated honestly",
      "decided by the person" in d["basis"], d["basis"])

# The trap, all the way through the handler.
arts, extra = D.run(
    {"scale_note": "Scale 1:50 @ A1", "page_size_pt": [pts(297), pts(420)],
     "confirm_scale": True,
     "traced": {"areas": [{"name": "Kitchen", "ring": room}]},
     "scan_id": "t3"}, _Prog(), OUT)
d = extra["drawing"]
check("11j an A1 note on A3 paper measures at 1:100",
      abs(d["totals"]["area_m2"] - 25.92) < 0.02, str(d["totals"]["area_m2"]))
check("11k and the correction is surfaced as a warning",
      any("A3" in w for w in extra["warnings"]), str(extra["warnings"]))

for bad, phrase in [({}, "drawing_url"),
                    ({"scale_note": "no scale here",
                      "traced": {"areas": []}}, "no drawing scale")]:
    try:
        D.run(bad, _Prog(), OUT)
        check(f"11l refused: {phrase}", False)
    except D.DrawingError as e:
        check(f"11l refused: {phrase}", phrase.split()[0] in str(e), str(e))

# Validation before any network work, as everywhere else in this worker.
try:
    D.run({"drawing_url": "file:///etc/passwd", "confirm_scale": True},
          _Prog(), OUT)
    check("11m a local-file URL is refused", False)
except Exception as e:
    check("11m a local-file URL is refused",
          "http" in str(e).lower() or "scheme" in str(e).lower(), str(e)[:80])


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
