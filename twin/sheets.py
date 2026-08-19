"""Drawing sheets: the thing you actually issue.

A plan on a screen is a view. A SHEET is a document: it has a size, a
scale you can put a rule against, a title block that says whose building
it is and what state the drawing is in, dimensions you can build from,
and schedules that count what is on it. Until this file existed the
project could measure a house and price it but could not hand anybody a
drawing, which is the one artefact a building control officer, a
neighbour, a client and a bricklayer all actually read.

THREE RULES, AND THEY ARE THE WHOLE DESIGN.

1. TRUE SCALE OR NOTHING. Every sheet is drawn at a standard metric
   scale — 1:20, 1:50, 1:100, 1:200 — and the geometry is placed by
   arithmetic on paper millimetres, not by fitting to the page. A
   drawing at 1:87 because that is what fitted is worse than no drawing:
   somebody will scale off it. If the building does not fit on the paper
   at the coarsest standard scale, this says so and refuses, rather than
   inventing a scale.

2. NOTHING ON THE SHEET THAT IS NOT IN THE MODEL. The title block prints
   the address if the model has one and DATA NOT AVAILABLE if it does
   not. There is no client name field filled with a plausible name, no
   invented drawing number, no fake revision history. Every sheet
   carries the same classification key the rest of the software uses,
   so a wall measured from LIDAR and a wall the user dragged are
   distinguishable ON THE PAPER, not just on screen.

3. GEOMETRY FIRST, PDF SECOND. Each sheet is built as a list of
   primitives in paper millimetres and only then written to PDF. That is
   what makes "is this drawing actually at 1:100" a test you can write
   rather than a claim you make: the primitives are numbers, and the
   test measures them. It also means the same sheet can be drawn to a
   canvas later without a second implementation.

WHAT IS DELIBERATELY NOT HERE. Hatching to BS 1192 line types, drawn
door swings on the sheet (they are on the interactive plan), a revision
cloud workflow, and CAD-grade dimension witness-line gaps. Those are
presentation; this is the document. It is honestly a preliminary set —
every sheet says so in the status field until a person changes it.
"""
from __future__ import annotations

import math
import zlib

# ------------------------------------------------------------------ units
MM = 72.0 / 25.4                      # a millimetre, in PDF points

#: Landscape paper, in millimetres. ISO A series, long edge first.
PAPER = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}

#: The scales a UK drawing is allowed to be at. 1:100 and 1:50 do almost
#: all domestic work; 1:200 is a site plan; 1:20 is a detail.
SCALES = (20, 50, 100, 200, 500)

#: ISO 3098 lettering, in millimetres of paper.
TEXT_S = 2.0
TEXT_M = 2.5
TEXT_L = 3.5
TEXT_XL = 5.0

#: The one classification key, the same four words used everywhere else.
CLASS_INK = {
    "verified":  (0.10, 0.55, 0.25),
    "derived":   (0.15, 0.40, 0.75),
    "estimated": (0.80, 0.55, 0.05),
    "user":      (0.65, 0.20, 0.65),
}
CLASS_ORDER = ("verified", "derived", "estimated", "user")
CLASS_MEANS = {
    "verified": "measured from a survey source",
    "derived": "computed from measured data",
    "estimated": "assumed — check on site",
    "user": "drawn by the user",
}

NOT_AVAILABLE = "DATA NOT AVAILABLE"


class SheetError(ValueError):
    """A sheet that cannot be drawn honestly is not drawn."""


# ------------------------------------------------------- primitives
def line(a, b, w=0.25, grey=0.0, dash=None, ink=None):
    return {"op": "line", "a": [round(a[0], 4), round(a[1], 4)],
            "b": [round(b[0], 4), round(b[1], 4)], "w": w,
            "ink": ink or (grey, grey, grey), "dash": dash}


def poly(pts, w=0.25, close=False, fill=None, ink=(0, 0, 0), dash=None):
    return {"op": "poly", "pts": [[round(p[0], 4), round(p[1], 4)]
                                  for p in pts],
            "w": w, "close": close, "fill": fill, "ink": ink, "dash": dash}


def text(at, s, size=TEXT_M, bold=False, anchor="start", rot=0.0,
         ink=(0, 0, 0)):
    return {"op": "text", "at": [round(at[0], 4), round(at[1], 4)],
            "s": str(s), "size": size, "bold": bold, "anchor": anchor,
            "rot": rot, "ink": ink}


# ------------------------------------------------------------ geometry
def roof_z(blk, x, y):
    """Height of a block's roof surface above ground at a plan point.

    Exact, not sampled: every roof this model knows is a function of the
    distance from the eaves, so the section and the elevations can ask
    for the height at a point instead of guessing at the ridge.

      gabled   slopes from two opposite eaves; the ends are vertical
      hipped   slopes from all four eaves — the straight skeleton
      mono     one plane climbing from the low edge to the high one
      flat     the top of the wall

    Returns metres above the building's zero (ground floor level).
    """
    top = (blk.base_level + blk.storeys) * blk.storey_height
    spec = blk.roof or {}
    kind = spec.get("kind", "gabled")
    if kind == "flat" or not kind:
        return top
    t = math.tan(math.radians(float(spec.get("pitch_deg", 30.0))))
    x0, y0 = blk.x, blk.y
    x1, y1 = blk.x + blk.width, blk.y + blk.depth
    if not (x0 - 1e-9 <= x <= x1 + 1e-9 and y0 - 1e-9 <= y <= y1 + 1e-9):
        return None                       # not over this block at all
    dx = min(x - x0, x1 - x)
    dy = min(y - y0, y1 - y)
    if kind == "hipped":
        # The straight skeleton of a rectangle: orientation-free.
        return top + max(0.0, min(dx, dy)) * t
    # THE MODEL SAYS WHICH WAY THE ROOF RUNS, AND THE MODEL WINS.
    # Extend sets ridge_along on every extension it makes and the 3D
    # honours it; the first version of this function guessed from the
    # longer plan side instead, so a lean-to on a narrow, deep rear
    # extension was drawn climbing sideways along the frontage — the 3D
    # and the paper disagreeing about the same "one authoritative
    # model". Absent from the spec, the ridge follows the longer side.
    ra = spec.get("ridge_along")
    if ra not in ("x", "y"):
        ra = "y" if blk.depth >= blk.width else "x"
    if kind == "monopitch":
        # The slope runs ACROSS the ridge direction; high_side "min"
        # puts the high edge at the low coordinate, as render3d does.
        high = spec.get("high_side", "min")
        if ra == "x":
            run = (y1 - y) if high == "min" else (y - y0)
        else:
            run = (x1 - x) if high == "min" else (x - x0)
        return top + max(0.0, run) * t
    # gabled: slope across the ridge, vertical gable ends along it.
    return top + (dy if ra == "x" else dx) * t


def _principal(bld):
    """The block a section should be cut through: the biggest one."""
    if not bld.blocks:
        raise SheetError("there is no building to draw")
    return max(bld.blocks, key=lambda b: b.area())


def _crossed(bld, axis, at):
    out = []
    for b in bld.blocks:
        lo, hi = ((b.y, b.y + b.depth) if axis == "x"
                  else (b.x, b.x + b.width))
        if lo - 1e-9 <= at <= hi + 1e-9:
            out.append(b)
    return out


def section_lines(bld):
    """Where to cut, and which way each section looks.

    A section is cut ACROSS the span, because that is the cut that shows
    the roof as a pitch rather than a flat line — cut the other way and
    the drawing says nothing about the thing it exists to explain. So
    A-A is always across the principal block's span.

    ONE SECTION IS OFTEN NOT ENOUGH, and this is not a nicety. A rear
    extension sits BEHIND the house: a cross-section through the middle
    of the original misses it completely, and a set whose only section
    does not cut the proposed work is a set that has not been checked.
    So a second cut, B-B, is added at right angles whenever it picks up
    blocks the first one misses — which is exactly the long section an
    architect would draw for the same reason.
    """
    p = _principal(bld)
    across_x = p.width <= p.depth      # span is the shorter side
    axis = "x" if across_x else "y"
    at = (p.y + p.depth / 2.0) if across_x else (p.x + p.width / 2.0)
    first = {"axis": axis, "at": round(at, 3), "label": "A-A",
             "note": "cut across the span of the main building"}
    cuts = [first]

    missed = [b for b in bld.blocks if b not in _crossed(bld, axis, at)]
    if missed:
        other = "y" if axis == "x" else "x"
        # Cut where the most of what A-A MISSED is picked up — counting
        # all crossed blocks let a candidate that crossed none of the
        # missed ones win on bulk — preferring a line that also passes
        # through the main building so the two sections read together.
        best, best_score = None, (-1, -1)
        for b in missed + [p]:
            cand = ((b.x + b.width / 2.0) if other == "y"
                    else (b.y + b.depth / 2.0))
            got = _crossed(bld, other, cand)
            score = (len([m for m in missed if m in got]),
                     1 if p in got else 0)
            if score > best_score:
                best, best_score = cand, score
        cuts.append({"axis": other, "at": round(best, 3), "label": "B-B",
                     "note": ("long section — cut to pick up the parts "
                              "A-A does not pass through")})
    return cuts


def section_line(bld):
    """The primary cut. Kept because callers ask for "the" section."""
    return section_lines(bld)[0]


def _extent(bld, level=None):
    xs, ys = [], []
    for b in bld.blocks:
        if level is not None and not (
                b.base_level <= level < b.base_level + b.storeys):
            continue
        xs += [b.x, b.x + b.width]
        ys += [b.y, b.y + b.depth]
    if not xs:
        raise SheetError(f"nothing stands on level {level}")
    return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------- sheet
class Sheet:
    """One page: paper, frame, title block, and a place to draw."""

    #: millimetres of paper kept clear round the edge, and for the strip
    #: the title block lives in.
    MARGIN = 10.0
    TITLE_W = 62.0
    TITLE_H = 74.0

    def __init__(self, paper="A3", title="", number="", bld=None,
                 status="PRELIMINARY — NOT FOR CONSTRUCTION", date=None,
                 revision=None, notes=()):
        if paper not in PAPER:
            raise SheetError(
                f"{paper} is not a paper size I have — "
                f"{', '.join(PAPER)}")
        self.paper = paper
        self.w, self.h = PAPER[paper]
        self.title = title
        self.number = number
        self.status = status
        self.date = date
        self.revision = revision
        self.bld = bld
        self.notes = list(notes)
        self.items = []
        self.scale = None

    # -- the drawing area, once the frame and title block are out ----
    def area(self):
        m = self.MARGIN
        return (m + 4.0, m + 4.0,
                self.w - m - self.TITLE_W - 4.0, self.h - m - 4.0)

    def add(self, *items):
        for i in items:
            if isinstance(i, list):
                self.items.extend(i)
            else:
                self.items.append(i)

    # -- the frame and the title block -------------------------------
    def frame(self):
        m, W, H = self.MARGIN, self.w, self.h
        self.add(poly([(m, m), (W - m, m), (W - m, H - m), (m, H - m)],
                      w=0.5, close=True))
        tx = W - m - self.TITLE_W
        self.add(line((tx, m), (tx, H - m), w=0.5))
        self._title_block(tx, m)
        self.add(text((m + 1.0, m - 3.6), self.credit(), size=TEXT_S,
                      ink=(0.45, 0.45, 0.45)))
        return self

    def credit(self):
        """The attribution the source's licence requires, on the paper.

        An ODbL footprint carries its attribution wherever it goes, and
        a drawing issued to a planning department is exactly the "goes"
        the licence means. Printing it under the frame is the cheapest
        possible way to comply, and leaving it off is the sort of thing
        that is nobody's problem until it is.
        """
        src = (self.bld.source or {}) if self.bld is not None else {}
        if not src:
            return ("Geometry source not recorded — this sheet carries no "
                    "attribution because the model carries no provenance.")
        bits = []
        lic = src.get("licence")
        from . import licences as _lic
        known = bool(lic) and lic in _lic.LICENCES
        attr = _lic.attributions([lic]) if known else []
        bits.append(attr[0] if attr else (src.get("source_provider")
                                          or "source unknown"))
        if src.get("source_dataset"):
            bits.append(str(src["source_dataset"]))
        if lic and not known:
            # A licence key nobody recognises cannot be complied with by
            # guessing at its attribution line. Say which key it was so
            # somebody can add it, rather than printing a credit that
            # may be the wrong one.
            bits.append(f"licence {lic!r} IS NOT IN THE REGISTRY — "
                        f"attribution unverified")
        if src.get("source_identifier"):
            bits.append(str(src["source_identifier"]))
        if lic:
            bits.append(f"licence: {lic}")
        if src.get("observation_date"):
            bits.append(f"observed {src['observation_date']}")
        return _fit(" · ".join(bits), self.w - 2 * self.MARGIN - 2, TEXT_S)

    def _row(self, x, y, w, label, value, ink=(0, 0, 0)):
        self.add(text((x + 2.0, y + 6.4), label.upper(), size=TEXT_S,
                      ink=(0.45, 0.45, 0.45)))
        self.add(text((x + 2.0, y + 1.8), value, size=TEXT_M, ink=ink))
        self.add(line((x, y), (x + w, y), w=0.2, grey=0.6))

    def _title_block(self, x, y0):
        """Everything a person needs to know about the sheet in hand.

        Empty fields print DATA NOT AVAILABLE. A drawing with a blank
        address is a drawing of nowhere, and the blank is information.
        """
        W = self.TITLE_W
        top = self.h - self.MARGIN
        b = self.bld
        addr = (b.address if b is not None and b.address else None)
        src = (b.source or {}) if b is not None else {}
        origin = src.get("provider") or src.get("source_provider")
        dataset = src.get("dataset") or src.get("source_dataset")

        y = top
        y -= 11.0
        self.add(text((x + 2.0, y + 3.0), "PROPERTY DIGITAL TWIN",
                      size=TEXT_M, bold=True))
        self.add(line((x, y), (x + W, y), w=0.4))

        # The address gets two lines before it gets an ellipsis: a
        # drawing that says "94 Parkfield Road, Birmingham B8 3\u2026" is a
        # drawing of an address somebody has to guess at.
        y -= 13.0
        self.add(text((x + 2.0, y + 10.4), "PROJECT / ADDRESS", size=TEXT_S,
                      ink=(0.45, 0.45, 0.45)))
        lines = _wrap(addr or NOT_AVAILABLE, W - 4.0, TEXT_M)[:2]
        for i, ln in enumerate(lines):
            self.add(text((x + 2.0, y + 5.8 - i * 4.0),
                          _fit(ln, W - 4.0, TEXT_M), size=TEXT_M))
        self.add(line((x, y), (x + W, y), w=0.2, grey=0.6))

        rows = [
            ("drawing", self.title or NOT_AVAILABLE),
            ("drawing no.", self.number or NOT_AVAILABLE),
            ("scale", (f"1:{self.scale} @ {self.paper}" if self.scale
                       else "not to scale")),
            ("date", self.date or NOT_AVAILABLE),
            ("revision", self.revision or "—"),
            ("geometry from", (f"{origin} · {dataset}" if origin and dataset
                               else origin or NOT_AVAILABLE)),
        ]
        for label, value in rows:
            y -= 9.0
            self._row(x, y, W, label, _fit(value, W - 4.0, TEXT_M))

        # Status band — loud, because it is the field that stops a
        # preliminary drawing being built from.
        y -= 10.0
        self.add(poly([(x, y), (x + W, y), (x + W, y + 8.0), (x, y + 8.0)],
                      close=True, fill=(0.93, 0.85, 0.20), w=0.2))
        self.add(text((x + W / 2, y + 2.8),
                      _fit(self.status, W - 3, TEXT_S, bold=True),
                      size=TEXT_S, bold=True, anchor="middle"))

        # Classification key.
        y -= 6.0
        self.add(text((x + 2.0, y), "HOW EACH LINE IS KNOWN", size=TEXT_S,
                      bold=True, ink=(0.35, 0.35, 0.35)))
        for k in CLASS_ORDER:
            y -= 5.2
            self.add(poly([(x + 2.0, y), (x + 6.0, y),
                           (x + 6.0, y + 3.0), (x + 2.0, y + 3.0)],
                          close=True, fill=CLASS_INK[k], w=0.15))
            self.add(text((x + 7.5, y + 0.4),
                          f"{k} — {CLASS_MEANS[k]}", size=TEXT_S))

        # Scale warning, then whatever notes the caller passed.
        y -= 7.0
        notes = [f"Printed true to scale at {self.paper}. Check the scale "
                 f"bar before measuring; work to figured dimensions where "
                 f"given."] + list(self.notes)
        floor = self.MARGIN + 4.0
        for i, n in enumerate(notes):
            if i:
                y -= 2.0
            for chunk in _wrap(n, W - 4.5, TEXT_S):
                if y < floor:
                    self.add(text((x + 2.0, y), "…", size=TEXT_S,
                                  ink=(0.3, 0.3, 0.3)))
                    return
                self.add(text((x + 2.0, y), chunk, size=TEXT_S,
                              ink=(0.3, 0.3, 0.3)))
                y -= 3.4

    # -- furniture ---------------------------------------------------
    def scale_bar(self, x, y, scale, metres=5.0):
        """A bar that is the length it says it is, at this sheet's scale.

        The only honest check on a print: a printer set to "fit to page"
        silently rescales everything, and the bar is what catches it.
        """
        mm = metres * 1000.0 / scale
        steps = 5
        for i in range(steps):
            x0 = x + mm * i / steps
            x1 = x + mm * (i + 1) / steps
            self.add(poly([(x0, y), (x1, y), (x1, y + 1.6), (x0, y + 1.6)],
                          close=True, w=0.2,
                          fill=(0, 0, 0) if i % 2 == 0 else (1, 1, 1)))
        self.add(text((x, y - 3.2), "0", size=TEXT_S, anchor="middle"))
        self.add(text((x + mm, y - 3.2), f"{metres:g} m", size=TEXT_S,
                      anchor="middle"))
        self.add(text((x + mm / 2, y + 2.4), f"scale 1:{scale}",
                      size=TEXT_S, anchor="middle", ink=(0.4, 0.4, 0.4)))
        return mm

    def north(self, x, y, bearing_deg, r=7.0):
        """North, at the building's TRUE bearing — not straight up.

        The plan is drawn in the building's own frame, so north is at
        whatever angle the house sits at. Drawing it up the page would be
        a lie about the orientation, and orientation is half of a Part O
        overheating argument.
        """
        a = math.radians(-bearing_deg)
        ux, uy = math.sin(a), math.cos(a)
        px, py = -uy, ux
        self.add(poly([(x + ux * r, y + uy * r),
                       (x + px * r * 0.38, y + py * r * 0.38),
                       (x - ux * r * 0.25, y - uy * r * 0.25),
                       (x - px * r * 0.38, y - py * r * 0.38)],
                      close=True, fill=(0, 0, 0), w=0.2))
        self.add(text((x + ux * (r + 3.4), y + uy * (r + 3.4) - 1.2), "N",
                      size=TEXT_M, bold=True, anchor="middle"))

    def as_dict(self):
        return {"paper": self.paper, "size_mm": [self.w, self.h],
                "title": self.title, "number": self.number,
                "scale": self.scale, "items": self.items}


# ---------------------------------------------------------- text metrics
#: Helvetica advance widths, in 1/1000 em, for the printable ASCII we
#: use. Enough to centre a label and to know when one will not fit.
_W = {**{c: 556 for c in "abcdeghknopqsuy"}, **{c: 500 for c in "0123456789"},
      **{c: 222 for c in "il'|"}, **{c: 278 for c in " !,.:;"},
      **{c: 333 for c in "()[]{}/\\ft-"}, **{c: 611 for c in "ABDEHKNPRSTVXY"},
      **{c: 722 for c in "CGOQUw"}, **{c: 833 for c in "Mm"},
      **{c: 944 for c in "W"}, **{c: 278 for c in "I·"},
      **{c: 667 for c in "FJLZ"}, **{c: 556 for c in "vxz£"},
      **{c: 500 for c in "rj"}, **{c: 333 for c in "²"},
      **{c: 584 for c in "+=<>~×"}, **{c: 400 for c in "°"},
      **{c: 1000 for c in "—…"}}


#: Cap height -> font size. ISO 3098 lettering is quoted as the height
#: of a capital; Helvetica's cap height is about 0.72 em, so a 2.5 mm
#: letter needs a 3.4 mm font. Getting this wrong is not cosmetic: every
#: width below is computed from it, and a 26% under-estimate is why text
#: ran out of the title block and level markers sat under their arrows.
FONT_K = 1.35
BOLD_K = 1.06


def text_width(s, size, bold=False):
    """Millimetres of paper a string will take, near enough to place it."""
    return (sum(_W.get(c, 556) for c in str(s)) / 1000.0
            * size * FONT_K * (BOLD_K if bold else 1.0))


def _fit(s, width_mm, size, bold=False):
    s = str(s)
    if text_width(s, size, bold) <= width_mm:
        return s
    while s and text_width(s + "…", size, bold) > width_mm:
        s = s[:-1]
    return s + "…"


def _wrap(s, width_mm, size, bold=False):
    out, cur = [], ""
    for word in str(s).split():
        trial = (cur + " " + word).strip()
        if cur and text_width(trial, size, bold) > width_mm:
            out.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        out.append(cur)
    return out


# ------------------------------------------------------------ scaling
def fits(width_m, height_m, avail_w, avail_h, scale):
    return (width_m * 1000.0 / scale <= avail_w
            and height_m * 1000.0 / scale <= avail_h)


def pick_scale(width_m, height_m, avail_w, avail_h, prefer=None):
    """The finest standard scale that fits — never a custom one.

    A REQUESTED SCALE IS A REQUIREMENT, NOT A HINT. If the caller names
    one it is used or refused; falling back quietly is how a set ends up
    with its ground floor at 1:100 and its first floor at 1:50, which
    nobody notices until two dimensions are compared with a rule.

    Returns the scale, or None if it will not go on the paper. The
    caller's job is then to say so; a drawing that quietly shrank to
    1:137 to fit is a drawing somebody will mis-measure.
    """
    if prefer is not None:
        if prefer not in SCALES:
            raise SheetError(
                f"1:{prefer} is not a standard scale — use one of "
                + ", ".join(f"1:{x}" for x in SCALES))
        return prefer if fits(width_m, height_m, avail_w, avail_h,
                              prefer) else None
    for s in SCALES:
        if fits(width_m, height_m, avail_w, avail_h, s):
            return s
    return None


def _placer(x0, y0, x1, y1, scale, bounds):
    """Model metres -> paper millimetres, centred in the drawing area."""
    mnx, mny, mxx, mxy = bounds
    k = 1000.0 / scale
    cx, cy = (mnx + mxx) / 2.0, (mny + mxy) / 2.0
    px, py = (x0 + x1) / 2.0, (y0 + y1) / 2.0

    def to_paper(x, y):
        return (px + (x - cx) * k, py + (y - cy) * k)
    return to_paper, k


# --------------------------------------------------------- dimensions
def dim_line(a, b, offset, to_paper, *, side=1, size=TEXT_S, label=None):
    """A dimension between two model points, offset onto clear paper.

    UK convention: figured dimensions in MILLIMETRES, because a
    dimension in metres reads as a typo the moment somebody drops the
    decimal point on a photocopy.
    """
    ax, ay = to_paper(*a)
    bx, by = to_paper(*b)
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L * offset * side, dx / L * offset * side
    p0, p1 = (ax + nx, ay + ny), (bx + nx, by + ny)
    metres = math.hypot(b[0] - a[0], b[1] - a[1])
    out = [
        line((ax, ay), p0, w=0.15, grey=0.45),
        line((bx, by), p1, w=0.15, grey=0.45),
        line(p0, p1, w=0.2, grey=0.15),
    ]
    # Oblique ticks, drawn at 45 degrees ACROSS the line — the previous
    # arithmetic rotated the offset vector the wrong way and produced
    # collinear whiskers lying ON the dimension line: no terminator at
    # all where the witness lines land, on every dimension of every
    # sheet.
    ux, uy = dx / L, dy / L
    mag = abs(offset) or 1.0
    hx, hy = nx / mag, ny / mag              # unit, towards the offset
    tk = 1.2 / math.sqrt(2.0)
    for p in (p0, p1):
        out.append(line((p[0] - (ux + hx) * tk, p[1] - (uy + hy) * tk),
                        (p[0] + (ux + hx) * tk, p[1] + (uy + hy) * tk),
                        w=0.35, grey=0.15))
    s = label if label is not None else mm_text(metres)
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    rot = math.degrees(math.atan2(dy, dx))
    if rot > 90 or rot <= -90:
        rot += 180
    off = 1.1
    out.append(text((mx + hx * off, my + hy * off),
                    s, size=size, anchor="middle", rot=rot))
    return out


def mm_text(metres):
    """A figured dimension, in millimetres, the way a drawing writes it.

    No thousands separator: "2,772" printed at 2 mm lettering reads as
    2.772 the moment a sheet is photocopied, and a dimension that can be
    read two ways is worse than none.
    """
    return f"{round(metres * 1000):d}"


def _runs(values, lo, hi, tol=1e-6):
    """Sorted unique division positions across a span, ends included."""
    pts = sorted({round(v, 4) for v in list(values) + [lo, hi]
                  if lo - tol <= v <= hi + tol})
    return pts


# ------------------------------------------------------------- sheets
def plan_sheet(bld, level=0, paper="A3", scale=None, date=None,
               number=None, status=None, dimensions=True):
    """A floor plan at a real scale, dimensioned, with the section line."""
    sh = Sheet(paper=paper, bld=bld, date=date,
               title=f"Floor plan — level {level}",
               number=number or f"PL-{level + 1:02d}",
               status=status or "PRELIMINARY — NOT FOR CONSTRUCTION")
    x0, y0, x1, y1 = sh.area()
    mnx, mny, mxx, mxy = _extent(bld, level)
    # Room for dimension strings on two sides, plus the scale bar.
    pad = 26.0
    s = pick_scale(mxx - mnx, mxy - mny,
                   (x1 - x0) - pad, (y1 - y0) - pad, prefer=scale)
    if s is None:
        raise SheetError(
            f"this building is {mxx - mnx:.1f} x {mxy - mny:.1f} m and will "
            f"not fit on {paper} "
            + (f"at 1:{scale} — use a bigger sheet (A2 or A1), or let the "
               f"scale be chosen" if scale else
               "at any standard scale — use a bigger sheet (A2 or A1) or "
               "draw one wing at a time"))
    sh.scale = s
    to_paper, k = _placer(x0 + pad * 0.6, y0 + pad * 0.7,
                          x1, y1, s, (mnx, mny, mxx, mxy))

    # Rooms first, so walls sit on top of the fills.
    for r in bld.rooms_on(level):
        ring = [to_paper(px, py) for px, py in r.ring()]
        fill = {"circulation": (0.93, 0.93, 0.88),
                "kitchen": (0.90, 0.94, 0.98),
                "wet": (0.88, 0.95, 0.95),
                "store": (0.95, 0.93, 0.90)}.get(r.kind, (0.99, 0.98, 0.96))
        sh.add(poly(ring, close=True, fill=fill, w=0.15,
                    ink=(0.55, 0.55, 0.55)))
        cx, cy = to_paper(r.x + r.width / 2.0, r.y + r.depth / 2.0)
        sh.add(text((cx, cy + 1.2), r.name, size=TEXT_M, bold=True,
                    anchor="middle"))
        sh.add(text((cx, cy - 2.2), f"{r.area():.1f} m²", size=TEXT_S,
                    anchor="middle", ink=(0.35, 0.35, 0.35)))
        sh.add(text((cx, cy - 5.2),
                    f"{r.width:.2f} × {r.depth:.2f}", size=TEXT_S,
                    anchor="middle", ink=(0.5, 0.5, 0.5)))

    # Blocks: external walls heavy, in the classification's own ink.
    for b in bld.blocks:
        if not (b.base_level <= level < b.base_level + b.storeys):
            continue
        ring = [to_paper(px, py) for px, py in b.ring()]
        sh.add(poly(ring, close=True, w=0.6,
                    ink=CLASS_INK.get(b.classification, (0, 0, 0))))

    # Openings, as a gap symbol on the wall they are in.
    for o in bld.openings:
        if o.level != level:
            continue
        b = bld.block(o.block_id)
        if b is None:
            continue
        seg = _edge_points(b, o.edge)
        if seg is None:
            continue
        (ax, ay), (bx, by) = seg
        L = math.hypot(bx - ax, by - ay) or 1.0
        ux, uy = (bx - ax) / L, (by - ay) / L
        p0 = (ax + ux * o.along_m, ay + uy * o.along_m)
        p1 = (p0[0] + ux * o.width, p0[1] + uy * o.width)
        sh.add(line(to_paper(*p0), to_paper(*p1), w=1.1,
                    ink=(1, 1, 1)))
        sh.add(line(to_paper(*p0), to_paper(*p1), w=0.3,
                    ink=(0.1, 0.35, 0.7)))

    if dimensions:
        sh.add(_plan_dimensions(bld, level, to_paper,
                                (mnx, mny, mxx, mxy), k))

    # The section line, so the section sheet is locatable on the plan.
    # Every cut in the set is marked on the plan, run out well clear of
    # the dimension strings so the label is not sitting on a figure.
    over = 22.0 * s / 1000.0            # 22 mm of paper, in model metres
    for cut in section_lines(bld):
        if cut["axis"] == "x":
            a, b_ = (mnx - over, cut["at"]), (mxx + over, cut["at"])
        else:
            a, b_ = (cut["at"], mny - over), (cut["at"], mxy + over)
        sh.add(line(to_paper(*a), to_paper(*b_), w=0.5, grey=0.2,
                    dash=[3.0, 1.2, 0.8, 1.2]))
        for p, sgn in ((a, -1), (b_, 1)):
            px, py = to_paper(*p)
            dx = 2.6 * sgn if cut["axis"] == "x" else 0.0
            dy = 0.0 if cut["axis"] == "x" else 2.6 * sgn
            sh.add(text((px + dx, py + dy - 0.9), cut["label"], size=TEXT_M,
                        bold=True, anchor="middle"))

    sh.north(x1 - 12.0, y1 - 14.0, bld.bearing_deg)
    sh.scale_bar(x0 + 2.0, y0 + 4.0, s)
    sh.add(text((x0 + 2.0, y1 - 4.0),
                f"LEVEL {level} — {sum(b.area() for b in bld.blocks if b.base_level <= level < b.base_level + b.storeys):.1f} m² gross",
                size=TEXT_L, bold=True))
    sh.frame()
    return sh


def _edge_points(b, edge):
    x0, y0, x1, y1 = b.x, b.y, b.x + b.width, b.y + b.depth
    return {"front": ((x0, y0), (x1, y0)),
            "rear": ((x1, y1), (x0, y1)),
            "left": ((x0, y1), (x0, y0)),
            "right": ((x1, y0), (x1, y1))}.get(edge)


def _plan_dimensions(bld, level, to_paper, bounds, k):
    """Overall, then the room divisions, on two sides of the plan.

    Two strings and not four: a domestic plan dimensioned on all four
    sides is unreadable at A3, and the two that matter are the ones a
    setting-out is taken from.
    """
    mnx, mny, mxx, mxy = bounds
    out = []
    xs, ys = set(), set()
    for b in bld.blocks:
        if b.base_level <= level < b.base_level + b.storeys:
            xs |= {b.x, b.x + b.width}
            ys |= {b.y, b.y + b.depth}
    for r in bld.rooms_on(level):
        xs |= {r.x, r.x + r.width}
        ys |= {r.y, r.y + r.depth}

    # Running dimensions along the bottom, then the overall below them.
    run_x = _runs(xs, mnx, mxx)
    for a, b in zip(run_x, run_x[1:]):
        if (b - a) * 1000.0 / 1.0 < 1e-6:
            continue
        out += dim_line((a, mny), (b, mny), 7.0, to_paper, side=-1)
    if len(run_x) > 2:
        out += dim_line((mnx, mny), (mxx, mny), 15.0, to_paper, side=-1)

    run_y = _runs(ys, mny, mxy)
    for a, b in zip(run_y, run_y[1:]):
        out += dim_line((mnx, a), (mnx, b), 7.0, to_paper, side=1)
    if len(run_y) > 2:
        out += dim_line((mnx, mny), (mnx, mxy), 15.0, to_paper, side=1)
    return out


def section_sheet(bld, paper="A3", scale=None, date=None, number=None,
                  status=None, cut=None):
    """A cut through the building: storey heights, roof, levels.

    The section is where a drawing stops being a picture of a footprint
    and starts being a building: it is the sheet that shows head height
    under a stair, whether the ridge clears the neighbour, and what the
    roof pitch actually is.
    """
    cut = cut or section_line(bld)
    axis, at = cut["axis"], cut["at"]
    sh = Sheet(paper=paper, bld=bld, date=date,
               title=f"Section {cut['label']}",
               number=number or f"SE-{'AB'.index(cut['label'][0]) + 1:02d}",
               status=status or "PRELIMINARY — NOT FOR CONSTRUCTION",
               notes=[cut["note"]])
    x0, y0, x1, y1 = sh.area()

    crossed = _crossed(bld, axis, at)
    if not crossed:
        raise SheetError("the section line misses the building")

    u0 = min((b.x if axis == "x" else b.y) for b in crossed)
    u1 = max((b.x + b.width if axis == "x" else b.y + b.depth)
             for b in crossed)
    zmax = max(_profile_z(b, u, axis, at) or 0.0
               for b in crossed
               for u in _section_us(b, axis, at))
    pad = 26.0
    s = pick_scale(u1 - u0, zmax + 1.0, (x1 - x0) - pad, (y1 - y0) - pad,
                   prefer=scale)
    if s is None:
        raise SheetError(
            f"the section is {u1 - u0:.1f} m long and {zmax:.1f} m high; "
            f"it will not fit on {paper} "
            + (f"at 1:{scale}" if scale else "at any standard scale"))
    sh.scale = s
    to_paper, k = _placer(x0 + pad * 0.6, y0 + pad * 0.7, x1, y1, s,
                          (u0, -0.5, u1, zmax + 0.5))

    # Ground line, drawn past the building on both sides.
    g0 = to_paper(u0 - 1.0, 0.0)
    g1 = to_paper(u1 + 1.0, 0.0)
    sh.add(line(g0, g1, w=0.7))
    for i in range(int((u1 - u0 + 2.0) / 0.4) + 1):
        hx, hy = to_paper(u0 - 1.0 + i * 0.4, 0.0)
        sh.add(line((hx, hy), (hx - 1.6, hy - 1.6), w=0.2, grey=0.5))

    heights = set()
    for b in crossed:
        bu0 = b.x if axis == "x" else b.y
        bu1 = bu0 + (b.width if axis == "x" else b.depth)
        base = b.base_level * b.storey_height
        top = (b.base_level + b.storeys) * b.storey_height
        ink = CLASS_INK.get(b.classification, (0, 0, 0))
        # The walls and floors that the cut passes through.
        sh.add(poly([to_paper(bu0, base), to_paper(bu1, base),
                     to_paper(bu1, top), to_paper(bu0, top)],
                    close=True, w=0.6, ink=ink))
        for lv in range(b.base_level, b.base_level + b.storeys + 1):
            z = lv * b.storey_height
            heights.add(round(z, 3))
            sh.add(line(to_paper(bu0, z), to_paper(bu1, z), w=0.4,
                        grey=0.25))
        # The roof, at the CUT's own break points — exact, not smoothed.
        prof = [(u, _profile_z(b, u, axis, at))
                for u in _section_us(b, axis, at)]
        prof = [(u, z) for u, z in prof if z is not None]
        if prof:
            sh.add(poly([to_paper(u, z) for u, z in prof], w=0.6, ink=ink))
            heights.add(round(max(z for _u, z in prof), 3))
            sh.add(line(to_paper(prof[0][0], prof[0][1]),
                        to_paper(prof[0][0], top), w=0.4, ink=ink))
            sh.add(line(to_paper(prof[-1][0], prof[-1][1]),
                        to_paper(prof[-1][0], top), w=0.4, ink=ink))

    # Level markers up the left: FFL, each floor, eaves, ridge.
    lx = u0 - 1.4
    for z in sorted(heights):
        px, py = to_paper(lx, z)
        ex, _ = to_paper(u1 + 0.6, z)
        sh.add(line((px, py), (ex, py), w=0.15, grey=0.6,
                    dash=[2.0, 1.5]))
        sh.add(poly([(px, py), (px + 2.0, py + 1.4), (px + 2.0, py - 1.4)],
                    close=True, fill=(0, 0, 0), w=0.15))
        sh.add(text((px - 1.6, py - 0.9), f"+{z * 1000:.0f}", size=TEXT_S,
                    anchor="end"))

    for b in crossed:
        spec = b.roof or {}
        if spec.get("kind") not in (None, "flat"):
            bu0 = b.x if axis == "x" else b.y
            bu1 = bu0 + (b.width if axis == "x" else b.depth)
            mid = (bu0 + bu1) / 2.0
            top = (b.base_level + b.storeys) * b.storey_height
            px, py = to_paper(mid, top + 0.35)
            sh.add(text((px, py), f"{spec.get('pitch_deg', 30):g}° "
                                  f"{spec.get('kind', 'gabled')}",
                        size=TEXT_S, anchor="middle", ink=(0.4, 0.4, 0.4)))

    sh.add(dim_line((u0, 0.0), (u1, 0.0), 14.0,
                    lambda u, z: to_paper(u, z), side=-1))
    sh.scale_bar(x0 + 2.0, y0 + 4.0, s)
    sh.add(text((x0 + 2.0, y1 - 4.0),
                f"SECTION {cut['label']} — heights in mm above ground "
                f"floor level", size=TEXT_L, bold=True))
    sh.frame()
    return sh


def _profile_us(b, axis):
    """Where the roof SILHOUETTE (max over the far axis) bends.

    For the elevations: a hip's silhouette rises for half the far span
    then runs level, so the bends are at half_v from each end; a gable
    or monopitch bends at most at mid-span. Exact for the silhouette —
    a section through a specific cut line needs _section_us instead.
    """
    u0 = b.x if axis == "x" else b.y
    u1 = u0 + (b.width if axis == "x" else b.depth)
    v0 = b.y if axis == "x" else b.x
    v1 = v0 + (b.depth if axis == "x" else b.width)
    us = {u0, u1, (u0 + u1) / 2.0}
    half_v = (v1 - v0) / 2.0
    for u in (u0 + half_v, u1 - half_v):
        if u0 <= u <= u1:
            us.add(u)
    return sorted(us)


def _section_us(b, axis, at):
    """Where the roof profile bends ALONG A SPECIFIC CUT.

    A hip cut 1 m from its eave goes level 1 m in from each end — not at
    half the far span, which is only where it bends when the cut happens
    to bisect the block. The first version used the silhouette's break
    points for sections too, and drew the roof up to 5 mm low between
    them on a sheet whose docstring promises "exact, not smoothed".
    """
    u0 = b.x if axis == "x" else b.y
    u1 = u0 + (b.width if axis == "x" else b.depth)
    v0 = b.y if axis == "x" else b.x
    v1 = v0 + (b.depth if axis == "x" else b.width)
    dv = min(at - v0, v1 - at)
    us = {u0, u1, (u0 + u1) / 2.0}
    for u in (u0 + dv, u1 - dv):
        if u0 <= u <= u1:
            us.add(u)
    return sorted(us)


def _profile_z(b, u, axis, at):
    return roof_z(b, u, at) if axis == "x" else roof_z(b, at, u)


def _depth_key(b, facing):
    """How far back a block sits from the viewer of this elevation."""
    return {"front": b.y,
            "rear": -(b.y + b.depth),
            "left": b.x,
            "right": -(b.x + b.width)}[facing]


def _elevation_us(b, horiz):
    """Break points across an elevation, fine enough to clip against.

    The profile is piecewise linear, so its own breaks would be enough
    to DRAW it — but it has to be cut where a block in front ends, and
    that happens anywhere. A 100 mm step is 1 mm of paper at 1:100 and
    2 mm at 1:50: below the width of the line it is drawn with.
    """
    u0 = b.x if horiz == "x" else b.y
    u1 = u0 + (b.width if horiz == "x" else b.depth)
    us = set(_profile_us(b, horiz))
    n = max(2, int(round((u1 - u0) / 0.1)))
    us |= {u0 + (u1 - u0) * i / n for i in range(n + 1)}
    return sorted(us)


def _visible_runs(profile, seen):
    """Split a profile into the stretches that are not hidden."""
    runs, cur = [], []
    for u, z in profile:
        if seen(u, z):
            cur.append((u, z))
        elif cur:
            if len(cur) > 1:
                runs.append(cur)
            cur = []
    if len(cur) > 1:
        runs.append(cur)
    return runs


def elevation_sheet(bld, facing="front", paper="A3", scale=None, date=None,
                    number=None, status=None):
    """What it looks like from one side. Silhouette, masses, openings."""
    if facing not in ("front", "rear", "left", "right"):
        raise SheetError("an elevation faces front, rear, left or right")
    sh = Sheet(paper=paper, bld=bld, date=date,
               title=f"{facing.title()} elevation", number=number
               or f"EL-{'front rear left right'.split().index(facing) + 1:02d}",
               status=status or "PRELIMINARY — NOT FOR CONSTRUCTION")
    x0, y0, x1, y1 = sh.area()
    horiz = "x" if facing in ("front", "rear") else "y"
    mnx, mny, mxx, mxy = _extent(bld)
    u0, u1 = (mnx, mxx) if horiz == "x" else (mny, mxy)
    zmax = bld.ridge_m()
    pad = 24.0
    s = pick_scale(u1 - u0, zmax + 1.0, (x1 - x0) - pad, (y1 - y0) - pad,
                   prefer=scale)
    if s is None:
        raise SheetError(
            f"this elevation is {u1 - u0:.1f} m wide and will not fit on "
            f"{paper} "
            + (f"at 1:{scale}" if scale else "at any standard scale"))
    sh.scale = s
    to_paper, k = _placer(x0 + pad * 0.6, y0 + pad * 0.7, x1, y1, s,
                          (u0, -0.5, u1, zmax + 0.5))
    flip = facing in ("rear", "left")

    def P(u, z):
        return to_paper(u0 + u1 - u if flip else u, z)

    sh.add(line(P(u0 - 1.0, 0.0), P(u1 + 1.0, 0.0), w=0.7))

    # WHAT YOU CAN ACTUALLY SEE FROM HERE. A rear extension drawn on the
    # front elevation is not a stylistic slip — it says a mass stands in
    # front of the house that does not exist, and a planning officer
    # reads it as the proposal. So the blocks are drawn nearest-first and
    # each one behind is hidden wherever the ones in front already stand
    # taller. Anything wholly hidden is REPORTED on the sheet rather than
    # silently dropped, so nobody thinks the extension was forgotten.
    near_first = sorted(bld.blocks, key=lambda b: _depth_key(b, facing))
    #: what is already drawn in front: (u0, u1, base_z, silhouette prof)
    skyline = []
    hidden = []

    def _sil(prof, u):
        for (ua, za), (ub, zb) in zip(prof, prof[1:]):
            if ua - 1e-9 <= u <= ub + 1e-9:
                if ub - ua < 1e-12:
                    return max(za, zb)
                return za + (zb - za) * (u - ua) / (ub - ua)
        return None

    def seen(u, z):
        """Is (u, z) clear of everything already drawn in front of it?

        Cover is the REAL front silhouette between the block's base and
        its roof line at that very position — not a full-width rectangle
        to its highest point, which was how a 6 m tower behind a hipped
        roof got declared invisible while demonstrably breaking the
        skyline near both hip ends.
        """
        for a, b_, base, prof in skyline:
            if a - 1e-9 <= u <= b_ + 1e-9:
                top_here = _sil(prof, u)
                if (top_here is not None
                        and base - 1e-9 <= z <= top_here - 1e-9):
                    return False
        return True

    def visible_z_runs(u, z_lo, z_hi):
        """The stretches of a vertical edge not behind anything."""
        runs = [(z_lo, z_hi)]
        for a, b_, base, prof in skyline:
            if not (a - 1e-9 <= u <= b_ + 1e-9):
                continue
            top_here = _sil(prof, u)
            if top_here is None:
                continue
            nxt = []
            for lo, hi in runs:
                if top_here <= lo + 1e-9 or base >= hi - 1e-9:
                    nxt.append((lo, hi))
                    continue
                if lo < base - 1e-9:
                    nxt.append((lo, min(hi, base)))
                if hi > top_here + 1e-9:
                    nxt.append((max(lo, top_here), hi))
            runs = nxt
        return [(lo, hi) for lo, hi in runs if hi - lo > 1e-6]

    for b in near_first:
        bu0 = b.x if horiz == "x" else b.y
        bu1 = bu0 + (b.width if horiz == "x" else b.depth)
        base = b.base_level * b.storey_height
        top = (b.base_level + b.storeys) * b.storey_height
        ink = CLASS_INK.get(b.classification, (0, 0, 0))
        other0 = b.y if horiz == "x" else b.x
        other1 = other0 + (b.depth if horiz == "x" else b.width)

        # The whole outline this block would have, roof included.
        prof = []
        for u in _elevation_us(b, horiz):
            zs = []
            for v in (other0, (other0 + other1) / 2.0, other1):
                z = (roof_z(b, u, v) if horiz == "x" else roof_z(b, v, u))
                if z is not None:
                    zs.append(z)
            if zs:
                prof.append((u, max(zs)))
        if not prof:
            prof = [(bu0, top), (bu1, top)]

        if (not any(seen(u, z) for u, z in prof)
                and not any(seen(u, base) for u in (bu0, bu1))
                and not seen((bu0 + bu1) / 2.0, base)):
            hidden.append(b.name)
            skyline.append((bu0, bu1, base, prof))
            continue

        # Every edge is CLIPPED to what stands clear of the blocks in
        # front. Drawing the whole outline and letting the nearer block
        # sit on top of it looks the same on a white screen and is
        # wrong the moment anybody reads the drawing as geometry — the
        # house would appear to run down through the extension roof.
        for seg in _visible_runs(prof, seen):
            sh.add(poly([P(u, z) for u, z in seg], w=0.6, ink=ink))
        for u in (bu0, bu1):
            zt = max((z for uu, z in prof if abs(uu - u) < 1e-6),
                     default=top)
            for lo, hi in visible_z_runs(u, base, zt):
                sh.add(line(P(u, lo), P(u, hi), w=0.5, ink=ink))
        # The eaves line and the ground line of this block, where seen.
        us = _elevation_us(b, horiz)
        for seg in _visible_runs([(u, top) for u in us], seen):
            sh.add(poly([P(u, z) for u, z in seg], w=0.35,
                        ink=(0.55, 0.55, 0.55)))
        for seg in _visible_runs([(u, base) for u in us], seen):
            sh.add(poly([P(u, z) for u, z in seg], w=0.5, ink=ink))
        skyline.append((bu0, bu1, base, prof))

    if hidden:
        sh.notes.append("Not visible on this elevation, behind the "
                        "building: " + ", ".join(sorted(set(hidden))) + ".")

    for o in bld.openings:
        b = bld.block(o.block_id)
        if b is None or o.edge != facing:
            continue
        seg = _edge_points(b, o.edge)
        if seg is None:
            continue
        (ax, ay), (bx, by) = seg
        L = math.hypot(bx - ax, by - ay) or 1.0
        along0 = (ax + (bx - ax) / L * o.along_m if horiz == "x"
                  else ay + (by - ay) / L * o.along_m)
        along1 = along0 + o.width * (1 if (bx - ax) + (by - ay) >= 0 else -1)
        zb = o.level * b.storey_height + o.sill
        ua, ub = min(along0, along1), max(along0, along1)
        # A WINDOW BEHIND THE EXTENSION IS NOT ON THIS ELEVATION. The
        # blocks got hidden-line treatment; leaving their openings out
        # of it drew a window floating inside the extension that stands
        # in front of it. Same test, same skyline.
        if not any(seen(u, z)
                   for u in (ua, (ua + ub) / 2.0, ub)
                   for z in (zb, zb + o.height / 2.0, zb + o.height)):
            continue
        sh.add(poly([P(ua, zb), P(ub, zb),
                     P(ub, zb + o.height), P(ua, zb + o.height)],
                    close=True, w=0.35, fill=(0.86, 0.92, 0.97),
                    ink=(0.1, 0.35, 0.7)))

    sh.add(dim_line((u0, 0.0), (u0, zmax), 12.0,
                    lambda u, z: to_paper(u, z), side=1))
    sh.scale_bar(x0 + 2.0, y0 + 4.0, s)
    sh.add(text((x0 + 2.0, y1 - 4.0), f"{facing.upper()} ELEVATION",
                size=TEXT_L, bold=True))
    sh.frame()
    return sh


def schedule_sheet(bld, paper="A3", date=None, number="SC-01", status=None,
                   assessment=None):
    """Room and opening schedules — the count behind the drawing.

    A schedule is the sheet a supplier prices off, so every row here is
    read from the model rather than typed: change a partition and the
    schedule changes with it, because there is nowhere else for it to
    come from.
    """
    sh = Sheet(paper=paper, bld=bld, date=date, title="Schedules",
               number=number,
               status=status or "PRELIMINARY — NOT FOR CONSTRUCTION")
    x0, y0, x1, y1 = sh.area()
    y = y1 - 6.0
    dropped = [0]

    def head(s):
        nonlocal y
        y -= 2.0
        sh.add(text((x0, y), s, size=TEXT_L, bold=True))
        y -= 2.4
        sh.add(line((x0, y), (x1, y), w=0.5))
        y -= 1.5

    def row(cells, widths, bold=False, ink=(0, 0, 0), rule=True):
        nonlocal y
        # A row that would walk off the paper is COUNTED, not clipped in
        # silence: the schedule is the sheet a supplier prices off, and
        # rows lost past the bottom edge with no marker are rows nobody
        # prices. The count prints at the foot of the sheet.
        if y - 4.6 < y0 + 8.0:
            dropped[0] += 1
            return
        y -= 4.6
        cx = x0
        for cell, w in zip(cells, widths):
            sh.add(text((cx + 1.0, y), _fit(cell, w - 2.0, TEXT_M),
                        size=TEXT_M, bold=bold, ink=ink))
            cx += w
        if rule:
            sh.add(line((x0, y - 1.4), (x1, y - 1.4), w=0.12, grey=0.75))

    avail = x1 - x0
    head("ROOM SCHEDULE")
    rw = [avail * f for f in (0.10, 0.30, 0.16, 0.16, 0.14, 0.14)]
    row(["LEVEL", "ROOM", "USE", "SIZE (m)", "AREA (m²)", "KNOWN AS"],
        rw, bold=True)
    if not bld.rooms:
        row([NOT_AVAILABLE,
             "no rooms drawn — the model is massing only", "", "", "", ""],
            rw, ink=(0.6, 0.2, 0.2))
    total = 0.0
    for r in sorted(bld.rooms, key=lambda r: (r.level, r.name)):
        total += r.area()
        row([str(r.level), r.name, r.kind,
             f"{r.width:.2f} × {r.depth:.2f}", f"{r.area():.2f}",
             r.classification], rw,
            ink=CLASS_INK.get(r.classification, (0, 0, 0)))
    if bld.rooms:
        row(["", "TOTAL", "", "", f"{total:.2f}", ""], rw, bold=True)

    y -= 6.0
    head("OPENING SCHEDULE")
    ow = [avail * f for f in (0.12, 0.20, 0.16, 0.16, 0.18, 0.18)]
    row(["REF", "TYPE", "IN", "ON", "SIZE (mm)", "SILL (mm)"], ow, bold=True)
    if not bld.openings:
        row([NOT_AVAILABLE, "no windows or doors placed yet", "", "", "", ""],
            ow, ink=(0.6, 0.2, 0.2))
    for i, o in enumerate(sorted(bld.openings,
                                 key=lambda o: (o.level, o.edge, o.along_m)),
                          1):
        b = bld.block(o.block_id)
        ref = {"window": "W", "door": "D", "bifold": "B",
               "rooflight": "R"}.get(o.kind, "O")
        row([f"{ref}{i:02d}", o.kind,
             (b.name if b else o.block_id), f"{o.edge} · L{o.level}",
             f"{round(o.width * 1000)} × {round(o.height * 1000)}",
             f"{round(o.sill * 1000)}"], ow,
            ink=CLASS_INK.get(o.classification, (0, 0, 0)))

    # Areas, straight off the model — the numbers a fee or a bill uses.
    y -= 6.0
    head("AREAS")
    aw = [avail * 0.5, avail * 0.5]
    m = bld.measurements()
    for label, value in (
            ("Footprint", f"{m['footprint_m2']:.2f} m²"),
            ("Gross internal area", f"{m['gia_m2']:.2f} m²"),
            ("Area within drawn rooms", f"{m['room_area_m2']:.2f} m²"),
            ("Eaves height above ground floor",
             f"{round(bld.eaves_m() * 1000)} mm"),
            ("Ridge height above ground floor",
             f"{round(bld.ridge_m() * 1000)} mm")):
        row([label, value], aw)

    if assessment and assessment.get("available"):
        c = (assessment.get("compliance") or {})
        y -= 6.0
        head("REGULATIONS — AS DRAWN")
        findings = c.get("findings") or []
        row([f"Stage: {c.get('stage', 'unknown')}", ""], aw, bold=True)
        if not findings:
            row(["No refusals found against the checks implemented", ""], aw)
        for f in findings[:14]:
            row([f.get("code", ""), _fit(f.get("message", ""),
                                         aw[1] - 2, TEXT_M)],
                aw, ink=((0.6, 0.15, 0.15)
                         if f.get("severity") == "refuse"
                         else (0.55, 0.4, 0.05)))
        if len(findings) > 14:
            row([f"…and {len(findings) - 14} more — see the full report",
                 ""], aw, ink=(0.45, 0.45, 0.45))

    if dropped[0]:
        sh.add(text((x0, y0 + 2.0),
                    f"{dropped[0]} more row(s) did not fit on this sheet "
                    f"— the model holds the full schedule",
                    size=TEXT_M, bold=True, ink=(0.7, 0.15, 0.1)))
    sh.frame()
    return sh


def common_scale(bld, paper="A3", elevations=True):
    """One scale for the whole set — the finest that every sheet takes.

    A set whose ground floor is at 1:100 and whose first floor is at
    1:50 is a set somebody will compare two dimensions on and get a
    wrong answer from. So the scale is chosen once, for the biggest
    thing that has to be drawn, and every sheet uses it.
    """
    probe = Sheet(paper=paper)
    x0, y0, x1, y1 = probe.area()
    needs = []
    levels = sorted({lv for b in bld.blocks
                     for lv in range(b.base_level,
                                     b.base_level + b.storeys)})
    for lv in levels:
        mnx, mny, mxx, mxy = _extent(bld, lv)
        needs.append((mxx - mnx, mxy - mny, 26.0))
    mnx, mny, mxx, mxy = _extent(bld)
    zmax = bld.ridge_m()
    needs.append((max(mxx - mnx, mxy - mny), zmax + 1.0, 26.0))
    if elevations:
        needs.append((max(mxx - mnx, mxy - mny), zmax + 1.0, 24.0))
    for s in SCALES:
        if all(fits(w, h, (x1 - x0) - pad, (y1 - y0) - pad, s)
               for w, h, pad in needs):
            return s
    return None


def sheet_set(bld, paper="A3", date=None, scale=None, status=None,
              assessment=None, elevations=True):
    """Every sheet the job needs, in issue order, with a manifest.

    Sheets that cannot be drawn are REPORTED, not skipped silently: a
    drawing set with a missing elevation and no explanation is how a
    building gets built with a wall nobody looked at.
    """
    sheets, problems = [], []
    if scale is None:
        scale = common_scale(bld, paper=paper, elevations=elevations)
        if scale is None:
            raise SheetError(
                f"no standard scale draws this building on {paper} — "
                f"try a bigger sheet (A2 or A1)")
    levels = sorted({lv for b in bld.blocks
                     for lv in range(b.base_level,
                                     b.base_level + b.storeys)})
    for lv in levels:
        try:
            sheets.append(plan_sheet(bld, lv, paper=paper, scale=scale,
                                     date=date, status=status))
        except SheetError as e:
            problems.append(f"floor plan level {lv}: {e}")
    for cut in section_lines(bld):
        try:
            sheets.append(section_sheet(bld, paper=paper, scale=scale,
                                        date=date, status=status, cut=cut))
        except SheetError as e:
            problems.append(f"section {cut['label']}: {e}")
    if elevations:
        for facing in ("front", "rear", "left", "right"):
            try:
                sheets.append(elevation_sheet(bld, facing, paper=paper,
                                              scale=scale, date=date,
                                              status=status))
            except SheetError as e:
                problems.append(f"{facing} elevation: {e}")
    if not sheets:
        raise SheetError(
            "not one drawing came out: " + "; ".join(problems))
    sheets.append(schedule_sheet(bld, paper=paper, date=date, status=status,
                                 assessment=assessment))
    return {"sheets": sheets, "problems": problems,
            "manifest": [{"number": s.number, "title": s.title,
                          "scale": s.scale, "paper": s.paper}
                         for s in sheets]}


# --------------------------------------------------------------- PDF
#: The characters this codebase writes that Latin-1 has no room for.
#: WinAnsiEncoding does have them, in the 0x80-0x9F block Latin-1 leaves
#: to control codes — so an em dash encoded naively comes out as "?" and
#: the title block reads "Floor plan ? level 0". Mapped, not stripped.
WINANSI = {"€": 0x80, "‚": 0x82, "ƒ": 0x83, "„": 0x84,
           "…": 0x85, "†": 0x86, "‡": 0x87, "ˆ": 0x88,
           "‰": 0x89, "Š": 0x8a, "‹": 0x8b, "Œ": 0x8c,
           "Ž": 0x8e, "‘": 0x91, "’": 0x92, "“": 0x93,
           "”": 0x94, "•": 0x95, "–": 0x96, "—": 0x97,
           "˜": 0x98, "™": 0x99, "š": 0x9a, "›": 0x9b,
           "œ": 0x9c, "ž": 0x9e, "Ÿ": 0x9f}


def _esc(s):
    """A PDF string literal, in WinAnsi, with the high bytes escaped."""
    out = []
    for ch in str(s):
        if ch in "()\\":
            out.append("\\" + ch)
        elif ch in WINANSI:
            out.append("\\%03o" % WINANSI[ch])
        elif ord(ch) < 32:
            out.append(" ")
        elif ord(ch) < 127:
            out.append(ch)
        else:
            try:
                out.append("\\%03o" % ord(ch.encode("latin-1")))
            except UnicodeEncodeError:
                out.append("?")
    return "".join(out)


def _stream(sheet):
    """One sheet's primitives as a PDF content stream, in points."""
    o = []
    ink = None
    width = None

    def setink(c, stroke=True):
        nonlocal ink
        key = (tuple(c), stroke)
        if key != ink:
            o.append("%.3f %.3f %.3f %s" % (c[0], c[1], c[2],
                                            "RG" if stroke else "rg"))
            ink = key

    for it in sheet.items:
        if it["op"] in ("line", "poly"):
            w = it.get("w", 0.25) * MM
            if w != width:
                o.append("%.3f w" % w)
                width = w
            d = it.get("dash")
            o.append("[%s] 0 d" % " ".join("%.2f" % (v * MM) for v in d)
                     if d else "[] 0 d")
        if it["op"] == "line":
            setink(it["ink"])
            o.append("%.3f %.3f m %.3f %.3f l S"
                     % (it["a"][0] * MM, it["a"][1] * MM,
                        it["b"][0] * MM, it["b"][1] * MM))
        elif it["op"] == "poly":
            pts = it["pts"]
            if not pts:
                continue
            if it.get("fill"):
                setink(it["fill"], stroke=False)
            setink(it["ink"])
            o.append("%.3f %.3f m" % (pts[0][0] * MM, pts[0][1] * MM))
            for p in pts[1:]:
                o.append("%.3f %.3f l" % (p[0] * MM, p[1] * MM))
            if it.get("close"):
                o.append("h")
            o.append("B" if it.get("fill") else "S")
        elif it["op"] == "text":
            setink(it["ink"], stroke=False)
            size = it["size"] * MM * FONT_K   # cap height -> font size
            s = _esc(it["s"])
            w = text_width(it["s"], it["size"], it["bold"]) * MM
            dx = {"start": 0.0, "middle": -w / 2.0, "end": -w}[it["anchor"]]
            x, y = it["at"][0] * MM, it["at"][1] * MM
            font = "/F2" if it["bold"] else "/F1"
            o.append("BT %s %.2f Tf" % (font, size))
            if it["rot"]:
                a = math.radians(it["rot"])
                ca, sa = math.cos(a), math.sin(a)
                o.append("%.5f %.5f %.5f %.5f %.3f %.3f Tm"
                         % (ca, sa, -sa, ca,
                            x + dx * ca, y + dx * sa))
            else:
                o.append("1 0 0 1 %.3f %.3f Tm" % (x + dx, y))
            o.append("(%s) Tj ET" % s)
    return "\n".join(o).encode("latin-1", "replace")


def render_pdf(sheets, compress=True):
    """The sheets as one PDF, written directly. No dependencies.

    PDF is a simple enough container that pulling in a reporting library
    to emit straight lines would be the heavier choice — and this way
    the drawing set ships from the same stdlib-only worker as everything
    else in this project.
    """
    if hasattr(sheets, "items") and hasattr(sheets, "paper"):
        sheets = [sheets]
    sheets = list(sheets)
    if not sheets:
        raise SheetError("a PDF with no sheets in it is not a drawing set")
    objs = [None]                      # 1-indexed

    def add(body):
        objs.append(body)
        return len(objs) - 1

    font_r = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                 b"/Encoding /WinAnsiEncoding >>")
    font_b = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                 b"/Encoding /WinAnsiEncoding >>")
    pages_id = add(b"")                # patched once the kids are known
    kids = []
    for sh in sheets:
        raw = _stream(sh)
        if compress:
            data = zlib.compress(raw)
            extra = b"/Filter /FlateDecode "
        else:
            data, extra = raw, b""
        cid = add(b"<< " + extra + b"/Length " +
                  str(len(data)).encode() + b" >>\nstream\n" + data +
                  b"\nendstream")
        pid = add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.3f %.3f] "
                   "/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> "
                   "/Contents %d 0 R >>"
                   % (pages_id, sh.w * MM, sh.h * MM, font_r, font_b, cid)
                   ).encode())
        kids.append(pid)
    objs[pages_id] = ("<< /Type /Pages /Count %d /Kids [%s] >>"
                      % (len(kids), " ".join("%d 0 R" % k for k in kids))
                      ).encode()
    cat = add(("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode())

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * len(objs)
    for i in range(1, len(objs)):
        offsets[i] = len(out)
        out += ("%d 0 obj\n" % i).encode() + objs[i] + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % len(objs)).encode()
    out += b"0000000000 65535 f \n"
    for i in range(1, len(objs)):
        out += ("%010d 00000 n \n" % offsets[i]).encode()
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs), cat, xref)).encode()
    return bytes(out)


def drawing_set(bld, paper="A3", date=None, scale=None, status=None,
                assessment=None, elevations=True):
    """The whole job: sheets, the PDF bytes, and what could not be drawn."""
    built = sheet_set(bld, paper=paper, date=date, scale=scale,
                      status=status, assessment=assessment,
                      elevations=elevations)
    return {"pdf": render_pdf(built["sheets"]),
            "manifest": built["manifest"],
            "problems": built["problems"]}
