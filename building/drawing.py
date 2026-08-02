"""Drawing Mode — measure quantities off a 2D PDF or DXF.

The gap this closes: most jobs arrive as drawings, and until now nothing here
could read one. Roof mode works from LIDAR and reconstruct works from a
capture, but a builder handed a PDF of a proposed extension had nothing.

ASSISTED, NOT AUTOMATIC, and that is a deliberate reading of the evidence
rather than a shortcut. Published benchmarks put frontier models at 0.40-0.55
on counting doors and windows in real drawings (AECV-Bench, Jan 2026), and
GPT-4o at 48.9% on issued-for-construction sheets (DrawingVQA, CVPR-F 2026).
The vendor claim of "98% automatic recognition" traces to a study limited to
architectural drawings; the peer-reviewed comparison reports ~70% time saved
within a 5% margin, which is a different and far more honest number.

So the split here is:

  ARITHMETIC   given a correct scale and a traced boundary, area and length
               are sub-1% accurate. That is geometry, not intelligence.
  JUDGEMENT    which lines are a wall, which room is the kitchen, how many
               sockets. Left to the person, who is right more often.

THE SCALE IS EVERYTHING. A wrong scale is a 100% error on every quantity on
the sheet; a misread wall is 2%. So scale is never inferred silently, is
always cross-checked where a second source exists, and is always handed back
for confirmation before a single quantity is reported.

Pure stdlib for all the geometry and scale reasoning. PDF and DXF parsing are
lazily imported behind validation, as everywhere else in this worker.
"""
import math
import os
import re

# --- units -----------------------------------------------------------------
# PDF user space is 1/72 inch by definition, so a "point" is a fixed physical
# length on the page and everything else follows from it.
MM_PER_POINT = 25.4 / 72.0

# ISO paper sizes in mm, portrait (short edge first). A drawing is nearly
# always one of these, and which one it is turns out to matter enormously.
PAPER_SIZES_MM = {
    "A0": (841.0, 1189.0),
    "A1": (594.0, 841.0),
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
}

# Position in the ISO A series, used to compute exact ratios between sheets.
PAPER_SERIES = {"A0": 0, "A1": 1, "A2": 2, "A3": 3, "A4": 4}

# How close a page has to be to a nominal size to be called that size.
PAPER_TOLERANCE_MM = 6.0


def _paper_linear_ratio(stated_sheet, actual_sheet):
    """How much larger the stated sheet is than the actual one, linearly.

    Computed from the SERIES INDEX rather than from the published millimetre
    sizes. ISO 216 defines each step as halving the area, so the linear ratio
    is exactly sqrt(2) per step — but the published sizes are rounded to whole
    millimetres, and 841/420 comes out at 2.0024 instead of 2. That 0.2% is
    harmless in itself and pointless to carry into every quantity on a sheet.
    """
    steps = PAPER_SERIES[actual_sheet] - PAPER_SERIES[stated_sheet]
    return math.sqrt(2.0) ** steps

# Scales that actually appear on UK building drawings.
COMMON_SCALES = (1, 5, 10, 20, 50, 100, 200, 500, 1000, 1250, 2500)

# Two scale sources must agree within this to be trusted together.
SCALE_AGREEMENT = 0.02

# Below this, a traced ring is a stray mark rather than a room.
MIN_AREA_M2 = 0.05


class DrawingError(ValueError):
    """Raised when a drawing cannot be measured honestly.

    Deliberately fatal. Every quantity on a sheet is multiplied by the scale,
    so a drawing measured at the wrong scale produces a complete, plausible,
    uniformly wrong bill — the worst failure this product can have, because
    nothing in the output looks odd.
    """


# --- reading the scale off the sheet ---------------------------------------

# "1:50", "1 : 100", "Scale 1/50", "SCALE 1:20 @ A1"
_SCALE_NOTE = re.compile(r"\b1\s*[:/]\s*(\d{1,4})\b")

# The same ratio, but explicitly labelled as the drawing scale. Preferred
# over any bare 1:N, because a sheet carries several ratios that are not the
# scale — see _GRADIENT below.
_SCALE_LABELLED = re.compile(
    r"\bscales?\b\s*[:=]?\s*(?:@?\s*[A-Z0-9]*\s*)??1\s*[:/]\s*(\d{1,4})\b",
    re.I)

# Ratios that are NOT the drawing scale. "FALL 1:40" is on nearly every UK
# ground-floor and drainage plan and "GRADIENT 1:12" on any sheet with a
# ramp; taking the first 1:N on the page read a 1:100 drawing as 1:40, which
# is every length out by 20% and every area by 44%, delivered with a
# confident explanatory note.
_GRADIENT = re.compile(
    r"\b(?:falls?|gradients?|slopes?|pitch(?:es)?|grade|mix|ratio|"
    r"crossfall|camber)\b[^.;\n]{0,24}?1\s*[:/]\s*\d{1,4}\b", re.I)

# Scales an architect actually draws at — BS 1192 / RIBA convention. A 1:40
# or 1:12 is not among them, which is a second, independent reason to
# distrust a drainage fall that has wandered into the scale slot.
STANDARD_SCALES = (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 1250, 2500)

# "NTS" or "not to scale" — a statement that the drawing HAS no scale.
_NOT_TO_SCALE = re.compile(
    r"\b(n\.?t\.?s\.?|not\s+to\s+scale)\b", re.I)

# "DO NOT SCALE FROM THIS DRAWING" — universal UK boilerplate, printed on
# essentially every professionally issued sheet INCLUDING ones that state
# their scale. It instructs the reader to use the figured dimensions in
# preference to measuring; it does not mean the drawing is unscaled.
# Treating it as "not to scale" refused every real drawing this mode exists
# to read.
_DO_NOT_SCALE_BOILERPLATE = re.compile(
    r"\bdo\s+not\s+scale\b", re.I)

# The sheet a scale was drawn FOR must be MARKED as such: "@ A1", "(A1)",
# "at A1", "A1 original". A bare " A2" matches a room label, a grid
# reference or "REV A3", and rescaled the whole sheet by 41% on a length and
# 100% on an area.
_SHEET_NOTE = re.compile(
    r"(?:@|\bat\b|\bon\b|\(|\bsheet\b\s*:?|\bsize\b\s*:?|\bpaper\b\s*:?)"
    r"\s*(A[0-4])\b"
    r"|\b(A[0-4])\s*(?:sheet|size|original|paper)\b", re.I)


def _ratio_candidates(text):
    """Every 1:N on the sheet, with the reason to trust or distrust it."""
    blob = str(text)
    excluded = set()
    for match in _GRADIENT.finditer(blob):
        for inner in _SCALE_NOTE.finditer(match.group(0)):
            excluded.add(match.start() + inner.start())

    labelled = {m.start(1) for m in _SCALE_LABELLED.finditer(blob)}

    out = []
    for match in _SCALE_NOTE.finditer(blob):
        try:
            ratio = int(match.group(1))
        except ValueError:
            continue
        if not 1 <= ratio <= 5000:
            continue
        out.append({
            "ratio": ratio,
            "at": match.start(),
            "gradient": match.start() in excluded,
            "labelled": match.start(1) in labelled,
            "standard": ratio in STANDARD_SCALES,
        })
    return out


def parse_scale_note(text):
    """Find a drawing scale in a block of text. None if absent.

    Returns the ratio denominator: "1:50" -> 50.

    A sheet carries several ratios and only one of them is the scale. They
    are ranked rather than taken in reading order: a ratio labelled "SCALE"
    beats an unlabelled one, a standard architectural scale beats a
    non-standard number, and a ratio sitting after the word "fall" or
    "gradient" is discarded outright.
    """
    if not text:
        return None
    candidates = [c for c in _ratio_candidates(text) if not c["gradient"]]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (not c["labelled"], not c["standard"],
                                   c["at"]))
    return candidates[0]["ratio"]


def parse_sheet_note(text):
    """Find the sheet size a scale was drawn FOR — the "@ A1" in "1:50 @ A1".

    The marker is required. Without one, "BEDROOM A2" on a genuinely A3
    sheet rescaled every length by 41% and every area by 100%, and reported
    it in a confident note explaining the correction it had just invented.
    """
    if not text:
        return None
    match = _SHEET_NOTE.search(str(text))
    if not match:
        return None
    return (match.group(1) or match.group(2)).upper()


def is_not_to_scale(text):
    """True if the sheet states it has no scale.

    "DO NOT SCALE FROM THIS DRAWING" does not count on its own, and the
    distinction is the difference between this mode working and refusing
    every drawing put in front of it. That phrase is boilerplate on
    essentially every professionally issued UK sheet, including ones that
    print their scale two lines below it: it tells the reader to prefer the
    figured dimensions, not that the drawing is unscaled.

    "NTS" with no scale anywhere on the sheet IS a refusal — there is
    genuinely nothing to measure against.
    """
    if not text:
        return False
    blob = str(text)
    if not _NOT_TO_SCALE.search(blob):
        return False
    # An explicit scale on the same sheet outranks it: the NTS most likely
    # belongs to a detail view, and which view is being measured is exactly
    # what confirmation exists to settle.
    return parse_scale_note(blob) is None


def has_do_not_scale_note(text):
    """Whether the sheet carries the standard "do not scale" instruction."""
    return bool(text and _DO_NOT_SCALE_BOILERPLATE.search(str(text)))


def mixed_scale_warning(text):
    """Whether a sheet states a scale AND says some part is not to scale."""
    if not text:
        return False
    return bool(_NOT_TO_SCALE.search(str(text))) and \
        parse_scale_note(text) is not None


def detect_paper_size(width_pt, height_pt):
    """Which ISO sheet a PDF page actually is, or None.

    Orientation-independent: a landscape A1 and a portrait A1 are both A1.
    """
    if not width_pt or not height_pt:
        return None
    short = min(width_pt, height_pt) * MM_PER_POINT
    long = max(width_pt, height_pt) * MM_PER_POINT
    for name, (nominal_short, nominal_long) in PAPER_SIZES_MM.items():
        if (abs(short - nominal_short) <= PAPER_TOLERANCE_MM
                and abs(long - nominal_long) <= PAPER_TOLERANCE_MM):
            return name
    return None


def effective_scale(stated_ratio, stated_sheet, actual_sheet):
    """Correct a stated scale for a sheet that was printed at a different size.

    THE trap this module exists to catch, and the reason drawings get measured
    wrong in practice. A drawing noted "1:50 @ A1" that arrives as an A3 PDF
    is not 1:50 — A3 is half the linear size of A1, so it is 1:100. Every
    length comes out half, every area a quarter.

    It happens constantly: architects issue at A1, everyone else prints and
    emails A3, and the title block still says A1 because the title block is
    part of the drawing.

    Returns (ratio, note). The note is None when nothing was corrected.
    """
    if not stated_ratio:
        return None, None
    if not stated_sheet or not actual_sheet or stated_sheet == actual_sheet:
        return stated_ratio, None

    try:
        factor = _paper_linear_ratio(stated_sheet, actual_sheet)
    except KeyError:
        return stated_ratio, None

    corrected = stated_ratio * factor
    return corrected, (
        f"The title block says 1:{stated_ratio:g} at {stated_sheet}, but this "
        f"page is {actual_sheet}. Printed down, the true scale is "
        f"1:{corrected:g}. Measuring at 1:{stated_ratio:g} would put every "
        f"length out by {factor:.2f}x and every area by {factor ** 2:.2f}x.")


def nearest_common_scale(ratio, tolerance=0.05):
    """Snap a derived ratio to a standard drawing scale, if it is close.

    A scale calibrated from a dimension string lands on something like 49.7;
    real drawings are 1:50. Snapping removes measurement noise — but only
    when it is genuinely close, because forcing 1:73 to 1:100 would be
    inventing a number.
    """
    if not ratio or ratio <= 0:
        return None
    best = min(COMMON_SCALES, key=lambda c: abs(c - ratio))
    return best if abs(best - ratio) / ratio <= tolerance else None


# --- dimension strings -----------------------------------------------------

# UK drawings annotate in millimetres, usually bare: "3600". Sometimes
# "3600mm", "3.6m", "3,600".
_DIM = re.compile(
    r"^\s*(\d{1,3}(?:[,\s]\d{3})+|\d+(?:\.\d+)?)\s*(mm|cm|m)?\s*$", re.I)


def parse_dimension(text):
    """Read an annotated dimension as MILLIMETRES. None if it is not one.

    A bare number on a building drawing is millimetres by UK convention, and
    a bare number under about 30 is far more likely to be a room label, a
    grid reference or a door number than a 12mm dimension — so it is refused
    rather than guessed at.
    """
    if text is None:
        return None
    match = _DIM.match(str(text))
    if not match:
        return None
    try:
        value = float(re.sub(r"[,\s]", "", match.group(1)))
    except ValueError:
        return None
    if value <= 0:
        return None

    unit = (match.group(2) or "").lower()
    if unit == "m":
        return value * 1000.0
    if unit == "cm":
        return value * 10.0
    # Bare number: millimetres, but only if it is a plausible dimension.
    if not unit and value < 30:
        return None
    return value


def scale_from_dimension(measured_points, stated_mm):
    """Derive the drawing ratio from one annotated dimension.

    The strongest scale evidence available, because it comes from the drawing
    itself rather than from a title block that may describe a different sheet.
    """
    if measured_points is None or measured_points <= 0:
        raise DrawingError("the measured span must be positive")
    if stated_mm is None or stated_mm <= 0:
        raise DrawingError("the stated dimension must be positive")
    paper_mm = measured_points * MM_PER_POINT
    return stated_mm / paper_mm


# --- the scale itself ------------------------------------------------------

class Scale:
    """A drawing scale, and how confident we are allowed to be about it."""

    def __init__(self, ratio, source, notes=None, confirmed=False):
        if ratio is None or ratio <= 0:
            raise DrawingError("a drawing scale must be a positive ratio")
        self.ratio = float(ratio)
        self.source = source
        self.notes = list(notes or [])
        # Nothing is measured until a person has agreed the scale. See
        # require_confirmation() for why this is not merely advisory.
        self.confirmed = bool(confirmed)

    @property
    def metres_per_point(self):
        """One PDF point, in real-world metres."""
        return MM_PER_POINT * self.ratio / 1000.0

    def length_m(self, points):
        return points * self.metres_per_point

    def area_m2(self, square_points):
        return square_points * (self.metres_per_point ** 2)

    def as_dict(self):
        return {
            "ratio": f"1:{self.ratio:g}",
            "ratio_value": round(self.ratio, 3),
            "source": self.source,
            "confirmed": self.confirmed,
            "metres_per_point": round(self.metres_per_point, 8),
            "notes": self.notes,
        }


def resolve_scale(note_text=None, page_size_pt=None, calibration=None,
                  override_ratio=None):
    """Work out the drawing scale from whatever evidence exists.

    In order of trust:

      OVERRIDE     the user typed it. Trusted, but still unconfirmed.
      CALIBRATION  measured against an annotated dimension ON this sheet.
                   Strongest automatic source — it cannot be wrong about
                   which sheet it describes.
      NOTE         the title block, corrected for the actual page size.

    When both a calibration and a note exist they are cross-checked, and a
    disagreement is reported rather than silently resolved in favour of one.
    """
    notes = []

    if override_ratio:
        return Scale(override_ratio, "override",
                     ["Scale supplied by the user rather than read from the "
                      "drawing."])

    if note_text and is_not_to_scale(note_text):
        raise DrawingError(
            "this sheet states it has no scale, so nothing on it can be "
            "measured. Use a dimensioned sheet, or calibrate against a "
            "known dimension and pass it explicitly.")

    if note_text and mixed_scale_warning(note_text):
        notes.append(
            "This sheet states a scale AND marks something on it not to "
            "scale, which normally means a detail or a section is drawn "
            "differently from the plan. Confirm you are measuring the view "
            "the scale belongs to.")

    if note_text and has_do_not_scale_note(note_text):
        notes.append(
            "The sheet carries the standard \"do not scale from this "
            "drawing\" instruction. That is on essentially every issued UK "
            "sheet and does not mean the drawing is unscaled — it means the "
            "figured dimensions are the authority. Where a dimension is "
            "printed, use it in preference to anything measured here.")

    stated = parse_scale_note(note_text)
    stated_sheet = parse_sheet_note(note_text)
    actual_sheet = detect_paper_size(*page_size_pt) if page_size_pt else None

    from_note = None
    if stated:
        from_note, correction = effective_scale(stated, stated_sheet,
                                                actual_sheet)
        if correction:
            notes.append(correction)
        elif stated_sheet and not actual_sheet:
            notes.append(
                f"The title block says {stated_sheet} but this page is not a "
                f"standard ISO size, so it may have been printed to fit. "
                f"Check the scale against a known dimension.")

    from_calibration = None
    if calibration:
        from_calibration = scale_from_dimension(
            calibration["measured_points"], calibration["stated_mm"])
        snapped = nearest_common_scale(from_calibration)
        if snapped:
            notes.append(
                f"Calibrated to 1:{from_calibration:.1f} from a "
                f"{calibration['stated_mm']:g}mm dimension, snapped to the "
                f"standard 1:{snapped:g}.")
            from_calibration = snapped
        else:
            notes.append(
                f"Calibrated to 1:{from_calibration:.1f} from a "
                f"{calibration['stated_mm']:g}mm dimension. That is not a "
                f"standard drawing scale — check the dimension was measured "
                f"end to end.")

    if from_calibration and from_note:
        disagreement = abs(from_calibration - from_note) / from_calibration
        if disagreement > SCALE_AGREEMENT:
            raise DrawingError(
                f"the title block and the drawing disagree about scale: the "
                f"note reads 1:{from_note:g} but a {calibration['stated_mm']:g}"
                f"mm dimension measures 1:{from_calibration:g}, a "
                f"{disagreement * 100:.0f}% difference. One of them is about "
                f"a different sheet. Measuring on either is a guess — confirm "
                f"which is right before taking any quantity off this drawing.")
        notes.append(
            f"The title block (1:{from_note:g}) and a measured dimension "
            f"(1:{from_calibration:g}) agree.")
        return Scale(from_calibration, "calibration+note", notes)

    if from_calibration:
        return Scale(from_calibration, "calibration", notes)
    if from_note:
        return Scale(from_note, "title_block", notes)

    raise DrawingError(
        "no drawing scale could be found. Supply one directly, or give a "
        "dimension from the sheet to calibrate against — measuring without a "
        "scale would produce a complete bill of quantities that is entirely "
        "wrong and looks entirely normal.")


def require_confirmation(scale):
    """Refuse to measure on an unconfirmed scale.

    Not paranoia. An auto-detected scale is bimodal — it is either exactly
    right or wrong by a whole factor, and there is no middle. A 2x error
    passes every sanity check a builder would apply to a quote, because every
    number on it is consistently wrong together.
    """
    if not scale.confirmed:
        raise DrawingError(
            f"scale {scale.as_dict()['ratio']} (from {scale.source}) has not "
            f"been confirmed. Show it to the user against a known dimension "
            f"and pass confirm_scale=true. Every quantity on this sheet is "
            f"multiplied by it.")
    return True


# --- geometry --------------------------------------------------------------

def polyline_length_points(points):
    """Total length of an open path, in PDF points."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def polygon_area_points(ring):
    """Shoelace area of a closed ring, in square PDF points.

    Absolute, so winding direction does not matter — a room traced clockwise
    is the same room.
    """
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def polygon_perimeter_points(ring):
    """Perimeter of a closed ring, in PDF points."""
    if len(ring) < 2:
        return 0.0
    return polyline_length_points(list(ring) + [ring[0]])


def _segments_cross(a, b, c, d):
    """Whether segment a-b properly crosses segment c-d."""
    def side(p, q, r):
        value = ((q[0] - p[0]) * (r[1] - p[1])
                 - (q[1] - p[1]) * (r[0] - p[0]))
        if abs(value) < 1e-12:
            return 0
        return 1 if value > 0 else -1

    d1, d2 = side(c, d, a), side(c, d, b)
    d3, d4 = side(a, b, c), side(a, b, d)
    # Proper crossing only. Rings share endpoints between consecutive edges
    # by construction, and touching at a shared vertex is not an error.
    return d1 * d2 < 0 and d3 * d4 < 0


def is_self_intersecting(ring):
    """Whether a traced ring crosses itself.

    The shoelace formula returns a confident number for a ring that crosses
    itself, and the number is meaningless: the two lobes have opposite
    winding and partly cancel. A bowtie traced as (0,0) (6,0) (0,4) (2,4)
    comes back as 8.0 with nothing to say the trace was wrong.

    This is a realistic mis-trace, not a contrived one — it is what happens
    when someone clicks two corners of a room in the wrong order, and the
    result looks plausible enough to price.
    """
    points = list(ring)
    count = len(points)
    if count < 4:
        return False
    edges = [(points[i], points[(i + 1) % count]) for i in range(count)]
    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue          # first and last edges share a vertex
            if _segments_cross(*edges[i], *edges[j]):
                return True
    return False


def _point_in_ring(point, ring):
    """Ray casting. True if the point is inside the ring."""
    x, y = point
    inside = False
    count = len(ring)
    for i in range(count):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % count]
        if (y1 > y) != (y2 > y):
            if y2 != y1 and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def measure_area(ring, scale, name=None, deductions=None):
    """One traced region as a real-world area.

    `deductions` are rings subtracted from it — a stairwell out of a floor,
    a window out of a wall elevation. Subtracting them here rather than
    expecting the caller to do the arithmetic is what stops an opening being
    forgotten, which is the commonest takeoff error there is.
    """
    require_confirmation(scale)
    gross_points = polygon_area_points(ring)
    if gross_points <= 0:
        raise DrawingError(
            f"{name or 'this region'} does not enclose an area — a traced "
            f"boundary needs at least three points and must not be a line.")

    # A ring that crosses itself has two lobes of opposite winding, which
    # partly cancel in the shoelace sum. The number that comes out is
    # confident and meaningless, and clicking two corners in the wrong order
    # is exactly how a real trace goes wrong.
    if is_self_intersecting(ring):
        raise DrawingError(
            f"{name or 'this region'} crosses itself, so it does not enclose "
            f"a single area and its shoelace area is meaningless. Re-trace "
            f"the boundary in order round the room.")

    gross = scale.area_m2(gross_points)
    taken = 0.0
    for hole in (deductions or []):
        # A deduction traced outside the region it is deducted from is a
        # mis-click, and subtracting it silently removed 2 m2 for a hole
        # 100m away. Judged on the hole's centroid, which is inside it for
        # any convex opening and for every rectangular one.
        centre = (sum(p[0] for p in hole) / len(hole),
                  sum(p[1] for p in hole) / len(hole))
        if not _point_in_ring(centre, ring):
            raise DrawingError(
                f"{name or 'this region'}: a deduction was traced outside "
                f"the boundary it is being taken out of. Check the openings "
                f"were traced on the right region.")
        taken += scale.area_m2(polygon_area_points(hole))

    net = gross - taken
    if net <= 0:
        raise DrawingError(
            f"{name or 'this region'}: deductions ({taken:.2f} m2) are larger "
            f"than the area they come out of ({gross:.2f} m2). Check the "
            f"openings were traced inside the boundary.")

    result = {
        "name": name,
        "gross_area_m2": round(gross, 3),
        "deductions_m2": round(taken, 3),
        "area_m2": round(net, 3),
        "perimeter_m": round(scale.length_m(polygon_perimeter_points(ring)), 3),
        "points": len(ring),
        "scale": scale.as_dict()["ratio"],
    }
    if net < MIN_AREA_M2:
        result["warning"] = (
            f"{net:.3f} m2 is smaller than a real room or panel — this is "
            f"probably a stray mark or a mis-traced boundary.")
    return result


def measure_length(path, scale, name=None, closed=False):
    """A traced run as a real-world length — skirting, gutter, a wall run."""
    require_confirmation(scale)
    if len(path) < 2:
        raise DrawingError(
            f"{name or 'this run'} needs at least two points to have a length")
    points = (polygon_perimeter_points(path) if closed
              else polyline_length_points(path))
    return {
        "name": name,
        "length_m": round(scale.length_m(points), 3),
        "segments": len(path) - (0 if closed else 1),
        "closed": closed,
        "scale": scale.as_dict()["ratio"],
    }


def count_items(positions, name=None):
    """A counted set — sockets, downlights, doors.

    Counting is the one thing the benchmarks say machines are worst at
    (0.40-0.55 on doors and windows), so this records what a person marked
    rather than pretending to detect anything.
    """
    return {
        "name": name,
        "count": len(positions or []),
        "method": "marked by hand — not detected automatically",
    }


# --- reading a real file ---------------------------------------------------

def extract_page(pdf_path, page_number=0):
    """Vector geometry and text from one PDF page, in PDF points.

    pdfplumber (MIT) is imported lazily and only after validation, as with
    every other third-party dependency in this worker.

    Returns lines, rectangles, curves and words with coordinates, plus the
    page size — enough to detect the sheet, find the scale note, and let a
    caller trace against real geometry rather than a picture.
    """
    if not pdf_path:
        raise DrawingError("no drawing supplied")
    if not os.path.exists(pdf_path):
        raise DrawingError(f"drawing not found: {pdf_path}")
    if page_number < 0:
        raise DrawingError("page_number cannot be negative")

    try:
        import pdfplumber
    except ImportError:
        raise DrawingError(
            "pdfplumber is not installed in this worker, so PDF drawings "
            "cannot be read. Install pdfplumber (MIT) or supply traced "
            "geometry directly.")

    with pdfplumber.open(pdf_path) as pdf:
        if page_number >= len(pdf.pages):
            raise DrawingError(
                f"this drawing has {len(pdf.pages)} page(s); page "
                f"{page_number} was asked for.")
        page = pdf.pages[page_number]
        words = page.extract_words() or []
        return {
            "page": page_number,
            "pages": len(pdf.pages),
            "width_pt": page.width,
            "height_pt": page.height,
            "paper": detect_paper_size(page.width, page.height),
            "lines": [{"x0": l["x0"], "y0": l["y0"],
                       "x1": l["x1"], "y1": l["y1"]} for l in page.lines],
            "rects": [{"x0": r["x0"], "y0": r["y0"],
                       "x1": r["x1"], "y1": r["y1"]} for r in page.rects],
            "curves": len(page.curves),
            "words": [{"text": w["text"], "x0": w["x0"], "top": w["top"]}
                      for w in words],
            "text": " ".join(w["text"] for w in words),
            "vector": bool(page.lines or page.rects or page.curves),
        }


def looks_scanned(page):
    """True if a page carries no vector geometry worth measuring.

    A flattened scan has no lines to snap to and no text to read a scale
    from, and UK Planning Portal downloads are frequently exactly that. It is
    better to say so plainly than to return a confident nothing.
    """
    return not page.get("vector") and len(page.get("words") or []) < 5


# --- handler entry point ---------------------------------------------------

def run(spec, prog, output_dir):
    """Drawing mode entry point.

    Two shapes of job:

      INSPECT   a drawing goes in, and what comes back is the page, the sheet
                size, the scale evidence and whether it is measurable — but
                NO quantities, because the scale has not been agreed yet.
      MEASURE   traced regions and runs come back with the scale confirmed,
                and quantities are produced.

    The split is the whole design, but the claim it used to make for itself
    — that this is "structurally impossible to get a quantity out of without
    a person having seen the scale" — was not true. confirm_scale sat in the
    same request as the tracing, so one call with an auto-detected scale and
    the flag set produced measurements with no round trip and nobody having
    looked at anything.

    What is true now: confirm_scale may carry the RATIO the user read off
    the sheet, and a mismatch against the resolved scale refuses. A caller
    who confirmed 1:50 cannot be handed quantities measured at 1:100 because
    the page size changed between one request and the next. A bare `true` is
    still accepted — a caller who genuinely looked is entitled to say so —
    but only the value form cannot go stale, and the difference is recorded
    in the output as `confirmed_as`.
    """
    import json

    prog.stage("fetching")
    pdf_url = spec.get("drawing_url")
    traced = spec.get("traced")

    if not pdf_url and not traced:
        raise DrawingError(
            "drawing mode needs drawing_url (a PDF to inspect), or traced "
            "geometry to measure.")

    page = None
    if pdf_url:
        import validation
        local = spec.get("drawing_path")
        if local and os.path.exists(local):
            path = local
        else:
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, "drawing.pdf")
            response = validation.fetch_checked(pdf_url, "drawing_url",
                                                timeout=120)
            response.raise_for_status()
            with open(path, "wb") as f:
                f.write(response.content)
        page = extract_page(path, spec.get("page", 0))

    prog.stage("reading")
    note_text = (page or {}).get("text") if page else spec.get("scale_note")
    page_size = ((page["width_pt"], page["height_pt"]) if page else
                 spec.get("page_size_pt"))

    result = {"page": {k: v for k, v in (page or {}).items()
                       if k not in ("lines", "rects", "words", "text")}}
    if page and looks_scanned(page):
        result["scanned"] = True
        result["warning"] = (
            "This page has no vector geometry — it is a scan or a flattened "
            "export. Lines cannot be snapped to and the scale note cannot be "
            "read, so anything measured here has to be traced by hand against "
            "a calibrated dimension.")

    prog.stage("scaling")
    scale = resolve_scale(
        note_text=note_text, page_size_pt=page_size,
        calibration=spec.get("calibration"),
        override_ratio=spec.get("scale_ratio"))
    # BOUND TO THE VALUE, not just asserted. confirm_scale may be `true` —
    # a bare assertion — or the ratio the user actually read off the sheet.
    # When it carries a number, it must agree with the scale that was
    # resolved, so a caller who confirmed 1:50 cannot be handed quantities
    # measured at 1:100 because the sheet was reprinted at A3 between one
    # request and the next. A bare `true` is still accepted, because a
    # caller who genuinely looked is entitled to say so, but the value form
    # is the one that cannot go stale.
    confirmation = spec.get("confirm_scale")
    if isinstance(confirmation, (int, float)) and not isinstance(
            confirmation, bool):
        stated = float(confirmation)
        if stated <= 0:
            raise DrawingError("confirm_scale must be a positive ratio")
        if abs(stated - scale.ratio) > max(0.5, scale.ratio * 0.005):
            raise DrawingError(
                f"you confirmed 1:{stated:g}, but this sheet resolves to "
                f"1:{scale.ratio:g} ({scale.source}). Something changed "
                f"between looking and measuring — most often the page size, "
                f"which halves or doubles the scale. Nothing is measured "
                f"until the two agree.")
        scale.confirmed = True
    else:
        scale.confirmed = bool(confirmation)
    result["scale"] = scale.as_dict()
    result["scale"]["confirmed_as"] = (
        float(confirmation) if isinstance(confirmation, (int, float))
        and not isinstance(confirmation, bool) else None)

    if not scale.confirmed:
        result["status"] = "scale_unconfirmed"
        result["next"] = (
            f"Check {scale.as_dict()['ratio']} against a dimension you can "
            f"read on the sheet, then send the same job back with "
            f"confirm_scale=true to get quantities.")
        prog.stage("exporting")
        return _write(result, spec, output_dir)

    prog.stage("measuring")
    areas, lengths, counts = [], [], []
    for region in (traced or {}).get("areas", []):
        areas.append(measure_area(
            [tuple(p) for p in region["ring"]], scale,
            name=region.get("name"),
            deductions=[[tuple(p) for p in h]
                        for h in region.get("deductions", [])]))
    for run_ in (traced or {}).get("lengths", []):
        lengths.append(measure_length(
            [tuple(p) for p in run_["path"]], scale,
            name=run_.get("name"), closed=run_.get("closed", False)))
    for group in (traced or {}).get("counts", []):
        counts.append(count_items(group.get("positions"),
                                  name=group.get("name")))

    result.update({
        "status": "measured",
        "areas": areas, "lengths": lengths, "counts": counts,
        "totals": {
            "area_m2": round(sum(a["area_m2"] for a in areas), 3),
            "length_m": round(sum(l["length_m"] for l in lengths), 3),
            "count": sum(c["count"] for c in counts),
        },
        "basis": (
            "Measured from a 2D drawing at a confirmed scale. Area and length "
            "are arithmetic and accurate to well under 1%; what each region "
            "represents was decided by the person who traced it."),
    })
    prog.stage("exporting")
    return _write(result, spec, output_dir)


def _write(result, spec, output_dir):
    import json
    import paths
    directory = paths.ensure(output_dir)
    scan = spec.get("scan_id") or "drawing"
    path = os.path.join(directory, f"drawing_{scan}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    warnings = [w for w in [result.get("warning")] if w]
    warnings += result.get("scale", {}).get("notes", [])
    return ([(path, f"drawings/{scan}.json", None)],
            {"drawing": result, "warnings": warnings})
