"""Plain English in, a designed room schedule out.

WHAT THIS IS FOR. A builder standing in a driveway says "two beds plus an
en-suite on top, and rooms in the loft". Nobody wants to fill in a form with
extension_type, storeys, base_level and a room array — and the moment they
have to, the tool stops being usable on site. This turns the sentence into
the structured brief the rest of the pipeline already speaks, and lays the
rooms out inside the footprint the model MEASURED.

WHAT IT REFUSES TO DO. It never silently drops a word it did not understand:
anything unparsed comes back in `unrecognised` so the caller can show it
rather than quietly building something the customer did not ask for. And it
never pretends a schedule fits: when the rooms need more floor than the
measured footprint has, `fits` is False and the shortfall is in metres
squared, because "you asked for 4 beds in 41m2" is the answer a builder
needs, not a silently shrunken bedroom.

WHERE THE SIZES COME FROM. UK practice, not invention:
  * a double bedroom is usually 11-20m2; below 11 it will not take a double
    bed with circulation, and building control's space standards echo that
  * an en-suite is 3-5m2 (shower, WC, basin); a family bathroom 5-8m2
  * circulation (landing, stairs head) eats roughly a tenth of a floor
The allocator gives every room its minimum first, then shares what is left
in proportion, so a tight footprint produces small-but-legal rooms rather
than one huge bedroom and a cupboard.
"""
import re


# Minimum and target floor areas, m2. Minimum is what the room needs to
# function; target is what it gets when there is room to be generous.
ROOM_SIZES = {
    "bedroom":       {"min": 11.0, "target": 15.0, "label": "Bedroom"},
    "master":        {"min": 13.0, "target": 18.0, "label": "Master bedroom"},
    "ensuite":       {"min": 3.0,  "target": 4.5,  "label": "En-suite"},
    "bathroom":      {"min": 5.0,  "target": 7.0,  "label": "Bathroom"},
    "wc":            {"min": 1.5,  "target": 2.2,  "label": "WC"},
    "kitchen":       {"min": 8.0,  "target": 14.0, "label": "Kitchen"},
    "dining":        {"min": 8.0,  "target": 12.0, "label": "Dining room"},
    "living":        {"min": 12.0, "target": 18.0, "label": "Living room"},
    "office":        {"min": 6.0,  "target": 9.0,  "label": "Office"},
    "utility":       {"min": 3.0,  "target": 5.0,  "label": "Utility"},
    "dressing":      {"min": 4.0,  "target": 6.0,  "label": "Dressing room"},
}

# Fraction of a floor lost to landing, stairs head and walls.
CIRCULATION_FRACTION = 0.10

# Word -> room key. Longest phrases first so "en suite" is not read as a
# bare "suite", and "shower room" does not become "room".
ROOM_WORDS = [
    # "en-suite bathroom" is ONE room, not an en-suite AND a bathroom. The
    # compound has to be claimed before the bare words, or the commonest
    # phrasing anyone says — "two beds plus an en-suite bathroom" — silently
    # designs a second, separate family bathroom nobody asked for.
    (r"\ben[-\s]?suite\s+(?:bath(?:room)?|shower\s*room)s?\b", "ensuite"),
    (r"\bmaster\s+(?:bed(?:room)?|suite)\b", "master"),
    (r"\ben[-\s]?suites?\b", "ensuite"),
    (r"\bshower\s+rooms?\b", "ensuite"),
    (r"\bbath(?:room)?s?\b", "bathroom"),
    (r"\b(?:downstairs\s+)?(?:w\.?c\.?|toilet|cloakroom)\b", "wc"),
    (r"\bbed(?:room)?s?\b", "bedroom"),
    (r"\bkitchens?\b", "kitchen"),
    (r"\bdining\b", "dining"),
    (r"\b(?:living|lounge|sitting|family)\s*(?:room)?\b", "living"),
    (r"\b(?:office|study)\b", "office"),
    (r"\butility\b", "utility"),
    (r"\bdressing\s*(?:room)?\b", "dressing"),
]

# Where the work goes. "on top" and "over" mean a storey on an existing
# single-storey block — the most common UK job and the one the pipeline
# places against a MEASURED addition.
PLACEMENT_WORDS = [
    (r"\b(?:on\s+top|over\s+the\s+(?:garage|kitchen|extension|side)|"
     r"above\s+the\s+(?:garage|kitchen|extension)|first\s+floor\s+over)\b",
     "over"),
    (r"\b(?:rear|back|behind)\b", "rear"),
    (r"\b(?:side|flank)\b", "side"),
    (r"\bwrap[-\s]?around\b", "wrap"),
]

NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "a": 1, "an": 1, "single": 1, "double": 2, "triple": 3}

LOFT_RE = re.compile(
    r"\b(?:loft|attic|room[s]?\s+in\s+(?:the\s+)?roof|dormer|"
    r"roof\s+conversion)\b", re.I)


def _count_before(text, match_start, default=1):
    """The number word or digit immediately before a room word."""
    head = text[:match_start].rstrip()
    m = re.search(r"(\d+)\s*(?:x\s*)?$", head)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([a-z]+)\s*$", head)
    if m and m.group(1) in NUMBERS:
        return NUMBERS[m.group(1)]
    return default


def parse(text):
    """A sentence -> {rooms, placement, loft, storeys, unrecognised, ...}.

    Pure: no network, no measurement. The SIZES come later, in schedule(),
    because they depend on the footprint this house actually has.
    """
    if not text or not str(text).strip():
        return {"rooms": [], "placement": None, "loft": False,
                "unrecognised": [], "text": ""}
    t = str(text).lower()

    rooms, spans = [], []
    for pattern, key in ROOM_WORDS:
        for m in re.finditer(pattern, t):
            if any(s <= m.start() < e for s, e in spans):
                continue          # already claimed by a longer phrase
            spans.append((m.start(), m.end()))
            n = _count_before(t, m.start())
            # "master bedroom" is one master, never two rooms.
            for _ in range(max(1, n)):
                rooms.append(key)

    # A plain "two beds" with no master named: the first is the master when
    # it is going upstairs, because that is how the room will be used and
    # sold. Two identical 15m2 boxes is not how anyone builds it.
    if rooms.count("bedroom") >= 2 and "master" not in rooms:
        rooms[rooms.index("bedroom")] = "master"

    placement = None
    for pattern, key in PLACEMENT_WORDS:
        if re.search(pattern, t):
            placement = key
            break

    loft = bool(LOFT_RE.search(t))

    # Storeys: "two storey"/"double storey" is explicit; otherwise one.
    storeys = 1
    m = re.search(r"\b(two|three|2|3)\s*[-\s]?stor(?:e?y|ies)\b", t)
    if m:
        storeys = NUMBERS.get(m.group(1), None) or int(m.group(1))

    # Anything left that looks like a request but was not understood.
    claimed = set()
    for s, e in spans:
        claimed.update(range(s, e))
    leftover = "".join(" " if i in claimed else c for i, c in enumerate(t))
    known = (r"\b(?:and|plus|with|the|a|an|on|top|over|above|rear|back|side|"
             r"loft|attic|roof|dormer|storey|storeys|story|stories|extension|"
             r"conversion|please|want|need|build|add|new|to|of|in|for|my|"
             r"house|home|it|also|room|rooms|" +
             "|".join(NUMBERS) + r"|\d+)\b")
    unrecognised = [w for w in re.findall(r"[a-z]{3,}", leftover)
                    if not re.fullmatch(known, w)]

    return {"rooms": rooms, "placement": placement, "loft": loft,
            "storeys": storeys, "unrecognised": sorted(set(unrecognised)),
            "text": str(text).strip()}


def schedule(rooms, floor_area_m2, circulation=CIRCULATION_FRACTION):
    """Size a room list inside a MEASURED floor area.

    Every room gets its minimum first; the surplus is shared in proportion
    to how much each still wants. Returns (schedule, fits, shortfall_m2) —
    and when it does not fit, the schedule is still returned at minimums so
    a caller can show what would have to give.
    """
    if not rooms:
        return [], True, 0.0
    usable = max(0.0, float(floor_area_m2) * (1.0 - circulation))
    mins = [ROOM_SIZES.get(r, ROOM_SIZES["bedroom"])["min"] for r in rooms]
    tgts = [ROOM_SIZES.get(r, ROOM_SIZES["bedroom"])["target"] for r in rooms]
    need = sum(mins)

    if need > usable:
        out = [{"room": r, "label": ROOM_SIZES.get(r, {}).get("label", r),
                "area_m2": round(m, 1), "at_minimum": True}
               for r, m in zip(rooms, mins)]
        return out, False, round(need - usable, 1)

    spare = usable - need
    want = sum(t - m for t, m in zip(tgts, mins)) or 1.0
    out = []
    for r, mn, tg in zip(rooms, mins, tgts):
        extra = spare * ((tg - mn) / want)
        area = mn + extra
        out.append({"room": r,
                    "label": ROOM_SIZES.get(r, {}).get("label", r),
                    "area_m2": round(area, 1),
                    "at_minimum": False})
    return out, True, 0.0


def to_extension_spec(parsed, default_depth_m=4.0):
    """The structured brief propose.place_extension already understands."""
    placement = parsed.get("placement")
    if not placement:
        # No placement said. Upstairs rooms (beds/en-suite) imply building
        # OVER something; ground-floor rooms imply a rear extension.
        upstairs = {"bedroom", "master", "ensuite", "dressing"}
        rooms = set(parsed.get("rooms") or [])
        placement = "over" if rooms and rooms <= upstairs else "rear"
    spec = {"type": placement, "storeys": int(parsed.get("storeys") or 1)}
    if placement in ("rear", "wrap"):
        spec["depth_m"] = default_depth_m
    return spec


def describe(parsed, sched, fits, shortfall, floor_area_m2, loft_area_m2=None):
    """One human sentence a builder can read back to a customer."""
    if not sched:
        return "Nothing to build — no rooms were recognised in the brief."
    counts = {}
    for row in sched:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    parts = [(f"{n} x {lab}" if n > 1 else lab) for lab, n in counts.items()]
    where = {"over": "as a first floor over the existing single-storey block",
             "rear": "as a rear extension", "side": "as a side extension",
             "wrap": "as a wrap-around extension"}.get(
                 parsed.get("placement") or "over", "")
    msg = f"{', '.join(parts)} {where}, in {floor_area_m2:.1f}m2 of new floor"
    if parsed.get("loft") and loft_area_m2:
        msg += f", plus about {loft_area_m2:.0f}m2 of loft rooms"
    elif parsed.get("loft"):
        msg += ", plus rooms in the loft"
    if not fits:
        msg += (f". IT DOES NOT FIT: {shortfall:.1f}m2 short even at minimum "
                f"room sizes — drop a room, or extend further")
    return msg + "."
