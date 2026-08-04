"""Read a drawing's own room schedule straight off the sheet.

Model Mode checks the rooms it builds against the areas an architect printed
beside them, and that check is the only independent verification the whole
pipeline has. Until now those areas had to be typed in by hand — which means
the check is only as good as somebody's patience at 7am.

A schedule is a TABLE, and a table is the one thing on a drawing that is
genuinely machine-readable: ruled, aligned, and carrying its own units.

WHY THIS DOES NOT SCRAPE THE PAGE TEXT. The obvious approach — regex the
extracted text for "NAME LEVEL AREA" — reads the schedule and the drawing at
the same time, because pdfplumber returns words in page order and the plan
sits beside the table. Tried on a real sheet it produced rooms called
"13 m2 Bathroom", "204.7 SF Ensuite" and "1 : 100 Hallway": room labels from
the plan, welded onto schedule rows. Everything here works inside the
table's own bounding box for that reason.

WHAT IT REFUSES TO DO. It does not correct spellings. A real sheet came back
with a room called "we" — almost certainly "WC" — and "Bedroom4" with no
space. Both are left exactly as printed, because a parser that quietly
improves the drawing is a parser you can no longer check against it.
"""
import re

# A level cell reads "1. Ground Floor", "2. First Floor", "3. Loft Floor".
# The leading ordinal is what actually distinguishes them; the name after it
# is for a human.
LEVEL = re.compile(r'^(\d+)\.\s*(.+?)(?:\s+floor)?$', re.I)
NUMBER = re.compile(r'^\d+(?:\.\d+)?$')
UNITS = ("m2", "m²", "sqm", "m^2")

# How far left of its unit a number may sit and still belong to it. Wide
# enough for "34  m2", narrow enough that the next column cannot reach.
UNIT_GAP_PT = 25.0
ROW_TOLERANCE_PT = 4.0

# A schedule with more rows than this is not a room schedule — it is a
# door schedule, a finishes schedule, or a drawing register.
MAX_ROWS = 400


class ScheduleError(ValueError):
    """Raised when a page holds nothing that is a room schedule."""


def _clean(cell):
    """Collapse the whitespace a PDF inserts at line breaks, nothing more."""
    return re.sub(r'\s+', ' ', (cell or '')).strip()


def find_schedule_table(page):
    """The largest ruled table on the page, or None.

    Largest by area is a crude rule and a reliable one: a room schedule is
    the biggest table on a sheet that has one, and the alternative — the
    title block — is short and wide rather than tall.
    """
    tables = page.find_tables()
    if not tables:
        return None
    return max(tables, key=lambda t: ((t.bbox[2] - t.bbox[0])
                                      * (t.bbox[3] - t.bbox[1])))


def _areas_by_row(page, table):
    """Every (y, area) pair inside the table, found by position.

    The grid detector drops the area cell on rows whose rule lines are
    faint — 8 of 20 on the sheet this was written against. The numbers are
    on the page regardless, so they are read from their coordinates instead:
    find each unit token, then the number immediately to its left on the
    same line.
    """
    words = page.crop(table.bbox).extract_words()
    out = []
    for unit in words:
        if unit["text"].lower() not in UNITS:
            continue
        near = [w for w in words
                if NUMBER.match(w["text"])
                and abs(w["top"] - unit["top"]) < ROW_TOLERANCE_PT
                and 0 < unit["x0"] - w["x1"] < UNIT_GAP_PT]
        if near:
            # The nearest one — a row may carry an imperial conversion too.
            best = max(near, key=lambda w: w["x1"])
            out.append((unit["top"], float(best["text"])))
    out.sort()
    return out


def parse_page(page):
    """Rooms from one page's schedule.

    Returns {"rooms": [{name, level, level_no, area_m2}], "levels": {...},
    "warnings": [...]} or raises ScheduleError if the page has no schedule.
    """
    table = find_schedule_table(page)
    if table is None:
        raise ScheduleError(
            "no ruled table on this page — a room schedule is a table, and "
            "without one there is nothing here to read")

    grid = table.extract()
    if len(grid) > MAX_ROWS:
        raise ScheduleError(
            f"the largest table has {len(grid)} rows, which is not a room "
            f"schedule")

    areas = _areas_by_row(page, table)
    rooms, warnings = [], []

    for i, row in enumerate(table.rows):
        cells = [_clean(c) for c in (grid[i] if i < len(grid) else [])]
        if len(cells) < 2 or not cells[0] or not cells[1]:
            continue
        level = LEVEL.match(cells[1])
        if not level:
            continue                      # a header, or a stray ruled row

        y0, y1 = row.bbox[1], row.bbox[3]
        area = next((v for top, v in areas
                     if y0 - 2 <= top <= y1 + 2), None)
        if area is None:
            warnings.append(
                f"{cells[0]!r} on {cells[1]!r} has no readable area — the "
                f"row is on the sheet but its figure could not be located.")
            continue

        rooms.append({
            "name": cells[0],
            "level": cells[1],
            "level_no": int(level.group(1)),
            "area_m2": area,
        })

    if not rooms:
        raise ScheduleError(
            "found a table but no rows in it read as 'name, level, area'")

    levels = {}
    for r in rooms:
        levels.setdefault(r["level"], 0.0)
        levels[r["level"]] += r["area_m2"]

    # THE SAME ROOM NAME ON EVERY FLOOR IS NORMAL, NOT AN ERROR. A real
    # schedule has a Hallway on the ground, the first and the loft, and two
    # En-suites on the same storey. Anything keyed on name alone silently
    # merges them; anything that refuses duplicates rejects a valid drawing.
    seen = {}
    for r in rooms:
        key = (r["level_no"], r["name"].strip().lower())
        seen[key] = seen.get(key, 0) + 1
    repeated = [k for k, n in seen.items() if n > 1]
    if repeated:
        warnings.append(
            f"{len(repeated)} room name(s) appear more than once on the same "
            f"level. They are kept separate — but check the sheet, because a "
            f"schedule normally names two rooms on one floor distinctly.")

    return {
        "rooms": rooms,
        "levels": {k: round(v, 2) for k, v in levels.items()},
        "total_area_m2": round(sum(r["area_m2"] for r in rooms), 2),
        "warnings": warnings,
    }


def parse(path, page_number=None):
    """Rooms from a PDF. Tries every page unless one is named."""
    try:
        import pdfplumber
    except ImportError:
        raise ScheduleError(
            "reading a schedule needs pdfplumber, which is not installed")

    best, errors = None, []
    with pdfplumber.open(path) as pdf:
        pages = ([pdf.pages[page_number]] if page_number is not None
                 else pdf.pages)
        for i, page in enumerate(pages):
            try:
                got = parse_page(page)
            except ScheduleError as e:
                errors.append(f"page {i}: {e}")
                continue
            got["page"] = (page_number if page_number is not None else i)
            # The page with the most rooms wins: a sheet can carry a small
            # revision table as well as the schedule.
            if best is None or len(got["rooms"]) > len(best["rooms"]):
                best = got
    if best is None:
        raise ScheduleError("; ".join(errors) or "no schedule found")
    return best


def as_check_input(parsed, level_no=None):
    """Reshape into what model3d.check_against_schedule expects.

    Model Mode works one floor plate at a time, so a whole-building schedule
    has to be narrowed to the level being modelled. Passing all of it would
    compare a ground-floor plan against every room in the building and
    report the upper floors as missing.
    """
    rooms = parsed["rooms"]
    if level_no is not None:
        rooms = [r for r in rooms if r["level_no"] == level_no]

    # DUPLICATE NAMES SUM, THEY DO NOT OVERWRITE. A real first-floor plan
    # carries two rooms both labelled "Ensuite"; assigning them into a dict
    # by name drops one, and the check then compares two modelled en-suites
    # against one stated area and reports a 100% error on a correct drawing.
    #
    # Summing is not a workaround, it is the same rule the other side already
    # uses: check_against_schedule sums the MODEL's rooms by name, because an
    # L-shaped kitchen is two rectangles under one label. Both sides summing
    # is what makes the comparison mean anything.
    out = {}
    for r in rooms:
        out[r["name"]] = out.get(r["name"], 0.0) + r["area_m2"]
    return {k: round(v, 2) for k, v in out.items()}


def levels(parsed):
    """The storeys the schedule describes, in order."""
    seen = {}
    for r in parsed["rooms"]:
        seen.setdefault(r["level_no"], r["level"])
    return [{"level_no": n, "level": seen[n],
             "rooms": sum(1 for r in parsed["rooms"] if r["level_no"] == n),
             "area_m2": round(sum(r["area_m2"] for r in parsed["rooms"]
                                  if r["level_no"] == n), 2)}
            for n in sorted(seen)]
