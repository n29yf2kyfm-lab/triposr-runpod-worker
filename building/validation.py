"""Input validation and clamping for the building worker.

Copied in pattern (deliberately NOT imported) from trellis2/handler.py — see
PLAN.md §2.3. The vehicle worker is live; editing it to share code would
rebuild and redeploy its production image. A few hundred duplicated lines
cost far less than breaking a working product.

Two jobs here, both learned from the vehicle worker:
  1. A bad type returns a clear message instead of a traceback.
  2. Extreme values are clamped so a caller cannot OOM the worker — a scan
     job asking for 100M points or 50k frames would take the box down.
"""

# Reconstruction quality tiers. "fast" is the feed-forward path
# (MapAnything), "quality" adds COLMAP refinement, "survey" adds a Gaussian
# splat pass. Cost and wall-clock rise steeply left to right.
QUALITY_TIERS = ("fast", "quality", "survey")

# Job modes — one worker, routed by mode. See PLAN.md Part 1.
MODES = (
    "reconstruct",   # capture bundle -> registered metric point cloud
    "structure",     # point cloud -> IFC (walls, slabs, openings, rooms)
    "services",      # open-scan point cloud -> pipe/cable runs -> IFC systems
    "register",      # align two scans (open<->closed, room<->room)
    "roof",          # aerial LIDAR / drone -> roof planes, pitch, areas
    "price",         # IFC/RoomPlan -> quantities -> priced quote
    "supply",        # quantities -> merchant basket + RFQ
    "condition",     # imagery + thermal -> 3D-located defects
    "design",        # footprint + rules -> massing, planning checks
    "valuation",     # address -> sold comparables -> value, extension uplift
    "drawing",       # 2D PDF/DXF -> confirmed scale -> measured quantities
    "planning",      # address -> site designations -> can this be built?
    "model",         # drawing's figured dimensions -> 3D building -> OBJ/IFC
    "render",        # gps + measured zone -> proposal drawn on real aerial
    "propose",       # address -> measured house + designed extension in 3D
    "scan",          # phone splat export (.ply) -> verified, positioned scan
)

# Roof capture sources, cheapest and easiest first.
#
# "lidar_open" is the important one: the Environment Agency's National LIDAR
# Programme covers ~99% of England at 1m resolution with +/-15cm vertical
# RMSE, as free open data with no account needed. That is enough for roof
# pitch, plane areas, ridge/hip/valley lines and chimney positions — i.e.
# enough to price a re-roof — from nothing but an address. No drone, no CAA
# paperwork, no site visit.
#
# Drone is deliberately LAST. UK rules from January 2026 require a Flyer ID
# and Operator ID, an A2 CofC for closer work, and impose separation
# distances that make close roof surveys impractical on a normal residential
# street with legacy aircraft.
ROOF_SOURCES = ("lidar_open", "ground", "drone", "auto")

# Scale sources, in order of trust. LiDAR depth is metric directly; the
# anchor path derives scale from known-size objects (UK brick coursing,
# socket heights) — see PLAN.md Part 6.
SCALE_SOURCES = ("lidar", "anchors", "gps", "manual")

# Frame caps. Feed-forward reconstruction scales VRAM with frame count, so
# an unbounded request is an OOM. 48GB comfortably handles ~600 frames at
# 1024px; beyond that the job must tile. Enforced, not advisory.
MAX_FRAMES = 2000
DEFAULT_MAX_FRAMES = 600

# Point cloud caps — a 100M-point cloud will not survive serialisation.
MAX_POINTS = 50_000_000
DEFAULT_MAX_POINTS = 8_000_000


class InputError(ValueError):
    """Raised for malformed job input. The handler turns this into a clean
    {"error": ...} response rather than a traceback."""


class NoDataError(ValueError):
    """The input was fine; the source simply has nothing for it.

    "No recorded sales at this postcode" is not a fault. Price Paid starts in
    1995 and a new development genuinely has no history — that is the true
    answer, and it is useful. Raising it as an error made RunPod mark the job
    FAILED, which is why this endpoint reads 14 completed against 13 failed
    when nothing had actually broken.

    It matters more than tidiness. An app on the other end cannot tell a
    crashed worker from an honest "nothing here" if both come back as a
    failure, so it either retries something that will never succeed or shows
    the user a breakage that is really an answer. The handler turns this into
    a COMPLETED job with status "no_data" and the reason attached.

    Reserved for absence of DATA. A source that could not be reached is a
    failure and must stay one — a timed-out planning register is not the same
    statement as "this site has no designations", and conflating them is how
    someone builds without checking.
    """


def _int(value, name, default=None, lo=None, hi=None):
    """Parse an int, clamp it, and name the field in any error."""
    if value is None:
        value = default
    if value is None:
        return None
    try:
        out = int(value)
    except (TypeError, ValueError, OverflowError):
        raise InputError(f"{name} must be an integer, got {value!r}")
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def _float(value, name, default=None, lo=None, hi=None):
    """Parse a float, clamp it, and name the field in any error.

    NaN IS REFUSED RATHER THAN CLAMPED, and the difference is not academic.
    max() and min() both return their *first* argument when the other is NaN,
    so clamping a NaN to [lo, hi] silently yields `lo` — the bottom of the
    range. A build_cost of NaN became £100, and the extension valuation then
    reported that the job paid for itself several times over. A quantity that
    is not a number has to stop here; there is no safe value to guess.

    Infinity is refused for the same reason: it clamps to `hi`, which is a
    cap chosen as a sanity bound, not as an answer.
    """
    if value is None:
        value = default
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        raise InputError(f"{name} must be a number, got {value!r}")
    if out != out:
        raise InputError(
            f"{name} is not a number (NaN). Check the value that produced it "
            f"— clamping it to the nearest bound would hide the fault.")
    if out in (float("inf"), float("-inf")):
        raise InputError(f"{name} is infinite, which is not a measurement")
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def _one_of(value, name, allowed, default=None):
    if value is None:
        return default
    if value not in allowed:
        raise InputError(
            f"{name} must be one of {', '.join(allowed)} — got {value!r}")
    return value


def _quantities(value):
    """Validate a measured-quantities map.

    A quantity is what gets ordered and what gets charged, so a malformed one
    must fail here rather than turn into a delivery.

    ZERO IS ALLOWED, and the first version got this wrong in a way that broke
    the product's main chain. Roof mode emits its full measurement set every
    time, so a plain gable — the commonest roof in Britain — comes back with
    hip_m: 0 and valley_m: 0 because it genuinely has neither. Refusing zero
    meant roof output could not be fed to price mode at all, which is the one
    path the two modes exist to make. Zero means "this element is not there",
    and takeoff.py already reads it that way: it emits no line for a
    zero-length element rather than a £0 one.

    Negative and non-finite are still refused. Those cannot mean anything.

    Values that are not numbers pass through, because roof mode's quantities
    carry a nested `materials` block and a covering name alongside the
    measurements, and this validator has no business flattening the shape its
    own consumer expects. Nested blocks are walked rather than waved through,
    though: takeoff.py floats whatever it finds in `materials`, so a string
    "nan" one level down became a bare NaN token in the delivered quote — not
    valid JSON, and rejected by most consumers.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InputError(
            "quantities must be an object mapping product to amount, e.g. "
            '{"battens": 503.3, "membrane": 158.0}')
    out = {}
    for key, amount in value.items():
        name = str(key).strip()
        if not name:
            raise InputError("quantities has an entry with no product name")
        if isinstance(amount, dict):
            out[name] = _quantities(amount) or {}
            continue
        if isinstance(amount, str):
            # A covering name is a legitimate string. A string that parses as
            # a non-finite number is not — it is a NaN wearing quotes.
            try:
                probe = float(amount)
            except (TypeError, ValueError, OverflowError):
                out[name] = amount
                continue
            if probe != probe or probe in (float("inf"), float("-inf")):
                raise InputError(
                    f"quantities[{name!r}] is {amount!r}, which is not a "
                    f"finite number")
            out[name] = amount
            continue
        if isinstance(amount, list) or amount is None:
            out[name] = amount
            continue
        try:
            number = float(amount)
        except (TypeError, ValueError, OverflowError):
            raise InputError(
                f"quantities[{name!r}] must be a number — got {amount!r}")
        if number != number or number in (float("inf"), float("-inf")):
            raise InputError(f"quantities[{name!r}] is not a finite number")
        if number < 0:
            raise InputError(
                f"quantities[{name!r}] is {number}. A quantity cannot be "
                f"negative.")
        out[name] = number
    return out or None


MAX_OBSERVATIONS = 200

# Model mode caps. A plan is typed in from a drawing by hand, so these are
# generous limits on a human's patience rather than on the machine.
MAX_PLAN_ROOMS = 2000
# model3d.build refuses more than this, so clamping any higher would only
# swap a clear validation message for a later one.
MAX_STOREYS = 20
# A room bigger than this is a warehouse, not a room, and is far more likely
# to be a millimetre figure that was not divided by a thousand.
MAX_ROOM_SIDE_M = 200.0
MIN_ROOM_SIDE_M = 0.30


def _plan(value):
    """Validate a Model Mode plan: the rooms typed off a drawing.

    Every room is a name, a position and a size in METRES. Millimetres are
    the trap here — a drawing is figured in mm, and 4570 read straight across
    is a room 4.57km wide that no downstream check would question. The side
    bounds below catch exactly that, which is why they are tighter than the
    machine needs.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InputError(
            'plan must be an object: {"rooms": [...], "schedule": {...}}')

    entries = value.get("rooms")
    if not isinstance(entries, (list, tuple)) or not entries:
        raise InputError(
            'plan.rooms must be a non-empty list of '
            '{"name": ..., "x": ..., "y": ..., "width_m": ..., "depth_m": ...}')
    if len(entries) > MAX_PLAN_ROOMS:
        raise InputError(
            f"plan.rooms has {len(entries)} entries; the cap is "
            f"{MAX_PLAN_ROOMS}")

    rooms = []
    for i, item in enumerate(entries):
        if not isinstance(item, dict):
            raise InputError(f"plan.rooms[{i}] must be an object")
        name = str(item.get("name") or "").strip()
        if not name:
            raise InputError(
                f"plan.rooms[{i}] has no name — the name is what the room "
                f"schedule is checked against, so it has to match the drawing")
        room = {"name": name}
        for key, lo, hi in (("x", -MAX_ROOM_SIDE_M, MAX_ROOM_SIDE_M),
                            ("y", -MAX_ROOM_SIDE_M, MAX_ROOM_SIDE_M)):
            room[key] = _float(item.get(key), f"plan.rooms[{i}].{key}",
                               0.0, lo, hi)
        for key in ("width", "depth"):
            got = item.get(f"{key}_m", item.get(key))
            # NOT CLAMPED. Every other size in this file clamps to a sanity
            # bound, and here that would be the bug: a drawing is figured in
            # millimetres, so 4570 typed straight across is the commonest
            # mistake there is — and clamping it to 200 m turns an obvious
            # fault into a plausible room that nothing downstream questions.
            side = _float(got, f"plan.rooms[{i}].{key}_m")
            if side is None:
                raise InputError(
                    f"plan.rooms[{i}] ({name}) has no {key}_m. Take it from "
                    f"the drawing's figured dimensions, in metres.")
            if not MIN_ROOM_SIDE_M <= side <= MAX_ROOM_SIDE_M:
                raise InputError(
                    f"plan.rooms[{i}] ({name}) is {side:g} m {key}, outside "
                    f"the {MIN_ROOM_SIDE_M}–{MAX_ROOM_SIDE_M:.0f} m a room "
                    f"can be. Check the units: a drawing is figured in "
                    f"MILLIMETRES, so 4570 means 4.57.")
            room[f"{key}_m"] = side
        height = _float(item.get("height_m"), f"plan.rooms[{i}].height_m",
                        None, 1.5, 20.0)
        if height is not None:
            room["height_m"] = height
        room["kind"] = str(item.get("kind") or "room").strip() or "room"
        # WHICH FLOORS THE ROOM IS ON. Without these two, a real two-floor
        # plan submitted through the API silently collapsed into repeated
        # plates: the model, the take-off and every buildability check ran
        # against a different building from the one the caller described.
        n = item.get("storeys")
        if n is not None:
            room["storeys"] = _int(n, f"plan.rooms[{i}].storeys", None,
                                   1, MAX_STOREYS)
        base = item.get("base_level")
        if base is not None:
            room["base_level"] = _int(base, f"plan.rooms[{i}].base_level",
                                      0, 0, MAX_STOREYS - 1)
        rooms.append(room)

    out = {"rooms": rooms}

    schedule = value.get("schedule")
    if schedule is not None:
        if not isinstance(schedule, dict):
            raise InputError(
                'plan.schedule must be an object mapping room name -> the '
                'floor area printed on the drawing, in m2')
        checked, seen = {}, {}
        for name, area in schedule.items():
            key = str(name).strip()
            if not key:
                raise InputError("plan.schedule has an entry with no name")
            number = _float(area, f"plan.schedule[{key!r}]", None,
                            0.1, MAX_ROOM_SIDE_M ** 2)
            if number is None:
                raise InputError(
                    f"plan.schedule[{key!r}] must be an area in m2")
            # NAMES THAT NORMALISE THE SAME ARE SUMMED, NOT REFUSED.
            #
            # Refusing them was wrong on a real drawing: a first-floor plan
            # legitimately carries two rooms both labelled "Ensuite", and a
            # building has a Hallway on every storey. Rejecting that rejects
            # the sheet.
            #
            # Summing is the rule the other side already uses —
            # check_against_schedule sums the MODEL's rooms by name, because
            # an L-shaped kitchen is two rectangles under one label. Both
            # sides summing is what makes the comparison mean anything. And
            # when a duplicate really was a typo, the doubled area shows up
            # as a large error in the check rather than as a silent pass.
            norm = " ".join(key.lower().split())
            if norm in seen:
                checked[seen[norm]] = round(checked[seen[norm]] + number, 3)
            else:
                seen[norm] = key
                checked[key] = number
        out["schedule"] = checked

    out["storeys"] = _int(value.get("storeys"), "plan.storeys", 1, 1,
                          MAX_STOREYS)
    # A ROOM CANNOT START AT OR ABOVE THE BUILDING'S TOP. Left unchecked,
    # the job ran and the room silently vanished from every total — the
    # model builder refuses this too, but the API should say no at the door
    # with the field name rather than fail mid-job.
    for i, r in enumerate(rooms):
        if r.get("base_level", 0) >= out["storeys"]:
            raise InputError(
                f"plan.rooms[{i}] ({r['name']}): base_level "
                f"{r['base_level']} needs plan.storeys of at least "
                f"{r['base_level'] + 1}, and the plan says "
                f"{out['storeys']}.")
    # Ground-floor entrance door, on by default — a dwelling has one, and
    # the first real render came back without. False for outbuildings and
    # single-room plates where an invented entrance would be wrong.
    out["front_door"] = bool(value.get("front_door", True))
    out["height_m"] = _float(value.get("height_m"), "plan.height_m", None,
                             1.5, 20.0)
    out["storey_height_m"] = _float(value.get("storey_height_m"),
                                    "plan.storey_height_m", None, 1.8, 25.0)

    # PARTY WALLS: which boundary lines are shared with the neighbour, so a
    # semi's shared flank is not treated as sky. [["x", 0.0], ["y", 8.5]].
    party = value.get("party_walls")
    if party is not None:
        if not isinstance(party, (list, tuple)):
            raise InputError('plan.party_walls must be a list of '
                             '[axis, coordinate] pairs, e.g. [["x", 0.0]]')
        out_party = []
        for i, edge in enumerate(party):
            if (not isinstance(edge, (list, tuple))
                    or len(edge) not in (2, 3)
                    or edge[0] not in ("x", "y")):
                raise InputError(
                    f'plan.party_walls[{i}] must be ["x"|"y", metres], '
                    f'optionally with a [from, to] span along the other '
                    f'axis: ["x", 0.0, [0.0, 9.88]]')
            pair = [edge[0], _float(edge[1], f"plan.party_walls[{i}]",
                                    0.0, -1000.0, 1000.0)]
            # The span bounds a party wall that does NOT run the whole
            # line — the case a rear extension creates the moment it
            # passes the neighbour's back wall.
            if len(edge) == 3:
                span = edge[2]
                if (not isinstance(span, (list, tuple)) or len(span) != 2):
                    raise InputError(
                        f'plan.party_walls[{i}] span must be [from, to] '
                        f'in metres along the other axis')
                lo = _float(span[0], f"plan.party_walls[{i}].from",
                            0.0, -1000.0, 1000.0)
                hi = _float(span[1], f"plan.party_walls[{i}].to",
                            0.0, -1000.0, 1000.0)
                if hi <= lo:
                    raise InputError(
                        f'plan.party_walls[{i}] span runs {lo} to {hi} — '
                        f'the second figure must be the larger')
                pair.append([lo, hi])
            out_party.append(pair)
        out["party_walls"] = out_party

    roof = value.get("roof")
    if roof is not None:
        if roof is True:
            roof = {}
        if not isinstance(roof, dict):
            raise InputError(
                'plan.roof must be an object: '
                '{"pitch_deg": 35, "kind": "hipped", "overhang_m": 0.3}')
        # NOT CLAMPED, for the same reason room widths are not: a pitch of 200
        # clamped to 89 is then refused by roof_over as "an 89 degree pitch",
        # which is not the number anybody typed. Refuse it here and say so;
        # leave the 12-60 buildable range to roof_over, whose message explains
        # why a tile will not shed water below it.
        _pitch = _float(roof.get("pitch_deg"), "plan.roof.pitch_deg")
        if _pitch is not None and not 0.0 <= _pitch < 90.0:
            raise InputError(
                f"plan.roof.pitch_deg is {_pitch:g}. A roof pitch is an angle "
                f"from horizontal, between 0 and 90 degrees — a UK tiled roof "
                f"is normally 12 to 60.")
        out["roof"] = {
            "pitch_deg": _pitch,
            "kind": _one_of(roof.get("kind"), "plan.roof.kind",
                            ("hipped", "gabled", "monopitch"),
                            default="hipped"),
            "overhang_m": _float(roof.get("overhang_m"),
                                 "plan.roof.overhang_m", None, 0.0, 2.0),
            # Both exist because a real section sheet needed them, and both
            # DIED HERE on their first outing — build() accepted them but
            # this whitelist silently dropped them, so the ridge came back
            # turned 90 degrees. The fourth appearance of the dead-input
            # pattern in this codebase: a documented field is not a wired
            # field until a job has been seen using it.
            "ridge_along": _one_of(roof.get("ridge_along"),
                                   "plan.roof.ridge_along", ("x", "y"),
                                   default=None),
            "max_span_m": _float(roof.get("max_span_m"),
                                 "plan.roof.max_span_m", None, 2.0, 30.0),
            # Only a monopitch has a high side. Passing it on a gable is
            # harmless (roof_over ignores it), so it is validated for shape
            # rather than refused for context the validator cannot see.
            "high_side": _one_of(roof.get("high_side"),
                                 "plan.roof.high_side", ("min", "max"),
                                 default=None),
        }
    return out


def _observations(value):
    """Validate known-object scale anchors.

    Each is {"kind": "brick_course", "measured_units": 0.031, "repeats": 4}:
    what was recognised, how big it came out in model units, and how many of
    them were averaged. These set the scale of the whole model, so a bad one
    is a wrong dimension on every quantity that follows.
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise InputError(
            'scale_observations must be a list of '
            '{"kind": ..., "measured_units": ...} objects')
    if len(value) > MAX_OBSERVATIONS:
        raise InputError(
            f"scale_observations has {len(value)} entries; the cap is "
            f"{MAX_OBSERVATIONS}")
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise InputError(
                f"scale_observations[{i}] must be an object with kind and "
                f"measured_units")
        kind = str(item.get("kind") or "").strip()
        if not kind:
            raise InputError(
                f"scale_observations[{i}] has no kind — name the object that "
                f"was recognised, e.g. brick_course or socket_height")
        measured = _float(item.get("measured_units"),
                          f"scale_observations[{i}].measured_units")
        if measured is None or measured <= 0:
            raise InputError(
                f"scale_observations[{i}].measured_units must be a positive "
                f"size in model units")
        repeats = _int(item.get("repeats"), f"scale_observations[{i}].repeats",
                       default=1, lo=1, hi=10_000)
        out.append({"kind": kind, "measured_units": measured,
                    "repeats": repeats})
    return out


def _str_list(value, name, max_len):
    """Coerce to a list of non-empty strings, with a length cap."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise InputError(f"{name} must be a list of strings")
    out = [str(v).strip() for v in value if str(v).strip()]
    if len(out) > max_len:
        raise InputError(
            f"{name} has {len(out)} entries; the cap is {max_len}. "
            f"Split the capture into multiple jobs or use tiling.")
    return out


# Characters an identifier may contain. Deliberately narrow: scan_id and
# project_id are interpolated into filenames under the output directory AND
# into delivery object keys, so anything that means something to a path or a
# URL has to be excluded at the door.
_IDENTIFIER_OK = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
MAX_IDENTIFIER_LEN = 128


def _identifier(value, name):
    """Validate an id that will be used as a filename and an object key.

    structure, reconstruct and services all build an output path as
    f"{scan_id}.ply" and friends, so a scan_id of "../../etc/x" wrote outside
    the output directory — confirmed, not theoretical. The other modules
    escaped that only by accident, because their template happens to put a
    literal prefix in front ("quote_..") which fails to open rather than
    escaping. Accident is not a control.

    Refused rather than rewritten. Silently stripping the dangerous parts
    would map two different scans onto one filename, and the second would
    overwrite the first.
    """
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > MAX_IDENTIFIER_LEN:
        raise InputError(
            f"{name} is {len(text)} characters; the cap is "
            f"{MAX_IDENTIFIER_LEN}")
    bad = sorted({c for c in text if c not in _IDENTIFIER_OK})
    if bad:
        raise InputError(
            f"{name} may only contain letters, digits, dot, dash and "
            f"underscore — {''.join(repr(c) for c in bad[:5])} is not allowed. "
            f"It is used as a filename and as a delivery key.")
    if text.startswith(".") or ".." in text:
        raise InputError(
            f"{name} must not start with a dot or contain '..' — it is used "
            f"as a filename")
    return text


class UnsafeURLError(InputError):
    """Raised for a URL the worker must not fetch on a caller's behalf."""


# Allowing a caller to name any address the worker can reach turns this
# endpoint into a proxy for the private network it sits in — cloud metadata
# services, internal APIs, anything on localhost — and the fetched content
# comes back in the response. Only ordinary public HTTP(S) is accepted.
ALLOWED_URL_SCHEMES = ("http", "https")


def check_fetchable_url(url, field="url"):
    """Refuse a URL the worker should not fetch for a caller.

    Blocks non-HTTP schemes (file://, gopher://) and any host that resolves
    into loopback, private, link-local, or otherwise reserved space — which
    is where 169.254.169.254 and every internal service live.

    Checking the URL is not enough on its own — see fetch_checked below. A
    302 from a public host to 169.254.169.254 walks straight past a check
    that only ever looks at the first hop, and requests follows redirects by
    default. Every caller-supplied URL must be fetched through fetch_checked,
    not through requests.get.

    HONEST LIMIT: this resolves the name to check it and the HTTP client
    resolves it again to connect, so a name that changes answer between the
    two calls (DNS rebinding) can still slip past. Closing that needs the
    connection pinned to the vetted address. This stops the straightforward
    attempts, which are the ones that actually get made.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    text = str(url or "").strip()
    if not text:
        raise UnsafeURLError(f"{field} is empty")

    parsed = urlparse(text)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise UnsafeURLError(
            f"{field} must be an http or https URL — got "
            f"{parsed.scheme or 'no'} scheme. Local paths and other schemes "
            f"are not fetched on a caller's behalf.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError(f"{field} has no host")

    try:
        infos = socket.getaddrinfo(host, parsed.port or
                                   (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise UnsafeURLError(f"{field}: cannot resolve {host!r} ({e})")

    # RFC 6598 shared address space: the range carriers and container
    # platforms use for internal NAT. Python reports it as neither private
    # nor reserved, so it has to be named.
    cgnat = ipaddress.ip_network("100.64.0.0/10")

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        mapped = getattr(address, "ipv4_mapped", None)
        for candidate in (address, mapped):
            if candidate is None:
                continue
            if (candidate.is_private or candidate.is_loopback
                    or candidate.is_reserved or candidate.is_link_local
                    or candidate.is_multicast or candidate.is_unspecified
                    or (candidate.version == 4 and candidate in cgnat)):
                raise UnsafeURLError(
                    f"{field} resolves to {address}, which is a private or "
                    f"reserved address. The worker only fetches public URLs.")
    return text


# A redirect chain is still a fetch. Cap it, and check every hop.
MAX_REDIRECTS = 5
_REDIRECT_CODES = (301, 302, 303, 307, 308)


def fetch_checked(url, field="url", timeout=120, stream=False, headers=None):
    """GET a caller-supplied URL, validating the destination at every hop.

    check_fetchable_url on its own guards the first hop only. requests
    follows redirects by default, so a public host the check allows can
    answer 302 Location: http://169.254.169.254/latest/meta-data/ and the
    worker fetches it and returns the body — the whole attack the check
    exists to stop, reinstated by a default argument. Confirmed against a
    local server, not reasoned about.

    Every caller-supplied URL in this worker goes through here. Fixed API
    endpoints the worker chooses itself (Land Registry, OS, postcodes.io) do
    not need it, because no caller controls where they point.
    """
    import requests
    from urllib.parse import urljoin

    current = check_fetchable_url(url, field)
    for _ in range(MAX_REDIRECTS):
        response = requests.get(current, timeout=timeout, stream=stream,
                                headers=headers, allow_redirects=False)
        if response.status_code not in _REDIRECT_CODES:
            return response
        location = response.headers.get("location")
        response.close()
        if not location:
            raise UnsafeURLError(
                f"{field} answered {response.status_code} with no Location")
        current = check_fetchable_url(urljoin(current, location), field)
    raise UnsafeURLError(
        f"{field} redirected more than {MAX_REDIRECTS} times without "
        f"answering")


def parse_job(job_input):
    """Validate a raw job input dict into a normalised job spec.

    Raises InputError with an actionable message on anything malformed.
    Returns a dict with every field present and defaulted.
    """
    if not isinstance(job_input, dict):
        raise InputError("input must be an object")

    mode = _one_of(job_input.get("mode"), "mode", MODES, default="reconstruct")

    spec = {
        "mode": mode,
        "project_id": _identifier(job_input.get("project_id"), "project_id"),
        "scan_id": _identifier(job_input.get("scan_id"), "scan_id"),
        # "open" = first fix, services exposed. "closed" = finished building.
        # The pairing of the two is what produces the X-ray (PLAN.md §1.2).
        "stage": _one_of(job_input.get("stage"), "stage",
                         ("open", "closed", "unknown"), default="unknown"),
        "quality": _one_of(job_input.get("quality"), "quality",
                           QUALITY_TIERS, default="fast"),
        "max_frames": _int(job_input.get("max_frames"), "max_frames",
                           DEFAULT_MAX_FRAMES, 2, MAX_FRAMES),
        "max_points": _int(job_input.get("max_points"), "max_points",
                           DEFAULT_MAX_POINTS, 10_000, MAX_POINTS),
    }

    # --- capture inputs -----------------------------------------------
    spec["video_url"] = (str(job_input.get("video_url") or "").strip() or None)
    spec["image_urls"] = _str_list(job_input.get("image_urls"),
                                   "image_urls", MAX_FRAMES)
    # RoomPlan hands back a parametric USDZ — walls, doors, windows and
    # openings as labelled objects with dimensions, not just a mesh. When
    # present it is the highest-value input we get, and Price Mode can run
    # off it alone without the full BIM pipeline (PLAN.md Phase 2).
    spec["roomplan_url"] = (str(job_input.get("roomplan_url") or "").strip()
                            or None)
    # A local export file, mirroring drawing_path. Same reachability rule
    # learned there: a path field that no mode reads is a documented lie, so
    # model mode's required-inputs check below must accept it wherever the
    # URL form is accepted.
    # A phone scan export — Scaniverse/Polycam/Luma Gaussian splat .ply.
    spec["scan_url"] = (str(job_input.get("scan_url") or "").strip()
                        or None)
    spec["scan_path"] = (str(job_input.get("scan_path") or "").strip()
                         or None)
    spec["roomplan_path"] = (str(job_input.get("roomplan_path") or "").strip()
                             or None)
    spec["depth_url"] = (str(job_input.get("depth_url") or "").strip() or None)
    spec["poses_url"] = (str(job_input.get("poses_url") or "").strip() or None)
    spec["thermal_urls"] = _str_list(job_input.get("thermal_urls"),
                                     "thermal_urls", MAX_FRAMES)
    # An existing cloud, for modes that operate on one rather than build it.
    spec["point_cloud_url"] = (str(job_input.get("point_cloud_url") or "").strip()
                               or None)
    spec["ifc_url"] = (str(job_input.get("ifc_url") or "").strip() or None)

    # --- scale ---------------------------------------------------------
    # Auto-detect by default: LiDAR depth if the capture carries it, else
    # known-object anchors. Never silently fall through to "unscaled" — a
    # model without real dimensions is worthless and dangerous to quote from.
    spec["scale_source"] = _one_of(job_input.get("scale_source"),
                                   "scale_source", SCALE_SOURCES + ("auto",),
                                   default="auto")
    # A manually measured reference, in metres, for scale_source="manual".
    spec["scale_reference_m"] = _float(job_input.get("scale_reference_m"),
                                       "scale_reference_m", None, 0.01, 100.0)
    # Model units per reference unit. Dropped from the whitelist, this
    # silently defaulted to 1.0, which is wrong for any caller whose model
    # is not in metres.
    spec["scale_reference_units"] = _float(
        job_input.get("scale_reference_units"), "scale_reference_units",
        None, 1e-6, 1e6)
    # THE KNOWN-OBJECT ANCHOR PATH. Brick coursing at 4 courses to 300mm,
    # Part M socket and switch heights — the way a capture with no LiDAR
    # gets a real dimension. This was missing from the whitelist entirely,
    # so reconstruct.py always read an empty list and told a caller who had
    # just supplied scale observations to supply scale observations. Same
    # class of bug as the one that made Price Mode unreachable, and the same
    # cause: a field the job needs, silently dropped at the door.
    spec["scale_observations"] = _observations(
        job_input.get("scale_observations"))
    spec["gps"] = job_input.get("gps") or None

    # --- roof ----------------------------------------------------------
    # An address or grid reference is enough to pull open LIDAR coverage,
    # so roof geometry needs no site visit at all for most English property.
    spec["address"] = (str(job_input.get("address") or "").strip() or None)
    spec["roof_source"] = _one_of(job_input.get("roof_source"), "roof_source",
                                  ROOF_SOURCES, default="auto")
    spec["drone_image_urls"] = _str_list(job_input.get("drone_image_urls"),
                                         "drone_image_urls", MAX_FRAMES)
    # Escape hatch for an isolated building with no OSM footprint. Off by
    # default: without a footprint the samples cover the neighbourhood, and
    # a street-sized quantity is worse than no quantity.
    spec["allow_unclipped"] = bool(job_input.get("allow_unclipped", False))

    # --- per-mode extras ------------------------------------------------
    spec["rate_card"] = job_input.get("rate_card") or None
    # Measured quantities, keyed by product. Price mode can work straight
    # from these — a roof job already has them from roof mode, and until the
    # IFC path lands it is the only way to reach Price Mode at all.
    spec["quantities"] = _quantities(job_input.get("quantities"))
    # A whole roof-mode result, so its quantities can be handed straight on
    # without unpacking them, and free-text notes for the quote.
    spec["roof"] = job_input.get("roof") or None
    spec["notes"] = _str_list(job_input.get("notes"), "notes", 100)

    # --- supply ----------------------------------------------------------
    # A price list, either inline or by URL. No scraping: this is the user's
    # own trade prices, a licensed affiliate product feed, or a published
    # list. See supply.py for why the VAT basis is mandatory rather than
    # inferred.
    spec["price_list_csv"] = (job_input.get("price_list_csv") or None)
    spec["price_list_url"] = (str(job_input.get("price_list_url") or "").strip()
                              or None)
    spec["channel"] = _one_of(job_input.get("channel"), "channel",
                              ("trade_account", "invoice", "quote",
                               "affiliate_feed", "published"),
                              default="published")
    spec["vat"] = _one_of(job_input.get("vat"), "vat",
                          ("ex", "inc", "unknown"), default="unknown")
    spec["supplier"] = (str(job_input.get("supplier") or "").strip() or None)

    # --- valuation --------------------------------------------------------
    # Sold comparables come from an address; the floor area ideally comes
    # from the SCAN, which is the whole advantage — everyone else works from
    # an agent's estimate or a decade-old EPC.
    spec["postcode"] = (str(job_input.get("postcode") or "").strip() or None)
    spec["property_type"] = _one_of(job_input.get("property_type"),
                                    "property_type",
                                    ("D", "S", "T", "F", "O"), default=None)
    spec["floor_area_m2"] = _float(job_input.get("floor_area_m2"),
                                   "floor_area_m2", None, 5.0, 2000.0)
    # UKHPI names regions by local authority slug: "birmingham", "england".
    spec["region"] = (str(job_input.get("region") or "").strip().lower()
                      or None)
    spec["max_sales"] = _int(job_input.get("max_sales"), "max_sales",
                             None, 10, 2000)

    # --- planning ---------------------------------------------------------
    # How far to look for designations whose SETTING reaches the site — a
    # listed building next door still constrains the design.
    spec["search_radius_m"] = _float(job_input.get("search_radius_m"),
                                     "search_radius_m", None, 10.0, 1000.0)
    # --- model ------------------------------------------------------------
    # A plan typed off the drawing's figured dimensions. Not traced — traced
    # linework is what the drawing itself tells you not to scale from.
    spec["plan"] = _plan(job_input.get("plan"))
    # Read the room schedule off the drawing itself instead of typing it in.
    # The areas an architect prints beside each room are the only independent
    # check Model Mode has, and a check nobody can be bothered to enter is a
    # check that does not happen.
    spec["schedule_url"] = (str(job_input.get("schedule_url") or "").strip()
                            or None)
    spec["schedule_path"] = (str(job_input.get("schedule_path") or "").strip()
                             or None)
    spec["schedule_level"] = _int(job_input.get("schedule_level"),
                                  "schedule_level", None, 1, 60)

    # --- drawing ----------------------------------------------------------
    # Assisted takeoff. The scale is never inferred silently — see drawing.py.
    # --- structure --------------------------------------------------------
    spec["wall"] = job_input.get("wall") or None
    spec["accessories"] = job_input.get("accessories") or None
    spec["point_cloud_path"] = (
        str(job_input.get("point_cloud_path") or "").strip() or None)
    spec["voxel_m"] = _float(job_input.get("voxel_m"), "voxel_m", None,
                             0.005, 0.5)

    spec["drawing_url"] = (str(job_input.get("drawing_url") or "").strip()
                           or None)
    spec["page"] = _int(job_input.get("page"), "page", 0, 0, 500)
    spec["scale_ratio"] = _float(job_input.get("scale_ratio"), "scale_ratio",
                                 None, 1.0, 5000.0)
    spec["scale_note"] = (str(job_input.get("scale_note") or "").strip()
                          or None)
    # Either `true` (a bare assertion) or the ratio the user actually read
    # off the sheet, which drawing.py cross-checks against the scale it
    # resolved. The value form is the one that cannot go stale.
    _confirm = job_input.get("confirm_scale", False)
    spec["confirm_scale"] = (
        _float(_confirm, "confirm_scale", None, 1.0, 5000.0)
        if isinstance(_confirm, (int, float)) and not isinstance(_confirm, bool)
        else bool(_confirm))
    spec["calibration"] = job_input.get("calibration") or None
    spec["traced"] = job_input.get("traced") or None
    # A local PDF, and the page's true size in points. Without the latter,
    # effective_scale cannot correct a sheet that has been reprinted at a
    # different size — the A1-drawn-printed-at-A3 trap, which is a factor of
    # two on every length.
    spec["drawing_path"] = (str(job_input.get("drawing_path") or "").strip()
                            or None)
    spec["page_size_pt"] = job_input.get("page_size_pt") or None

    # --- render ------------------------------------------------------------
    # The measured rectangle a proposed extension must stay inside, in the
    # house's own frame. Validated hard because the constraint IS the mode:
    # a zone that sailed through malformed would put the proposal on the
    # neighbour's roof with full confidence.
    rz = job_input.get("render_zone")
    if rz is not None:
        if not isinstance(rz, dict):
            raise InputError(
                'render_zone must be an object: {"bearing_deg": ..., '
                '"along0_m": ..., "along1_m": ..., "out0_m": ..., '
                '"out1_m": ...}')
        checked = {
            "bearing_deg": _float(rz.get("bearing_deg"),
                                  "render_zone.bearing_deg", None, 0.0, 360.0),
            "along0_m": _float(rz.get("along0_m"), "render_zone.along0_m",
                               None, -30.0, 30.0),
            "along1_m": _float(rz.get("along1_m"), "render_zone.along1_m",
                               None, -30.0, 30.0),
            "out0_m": _float(rz.get("out0_m"), "render_zone.out0_m",
                             None, -30.0, 30.0),
            "out1_m": _float(rz.get("out1_m"), "render_zone.out1_m",
                             None, -30.0, 30.0),
            "out_positive": bool(rz.get("out_positive", True)),
        }
        missing = [k for k, val in checked.items()
                   if val is None and k != "out_positive"]
        if missing:
            raise InputError(
                f"render_zone is missing {', '.join(missing)} — every edge "
                f"of the constraint rectangle must be stated in metres.")
        for a, b, what in ((checked["along0_m"], checked["along1_m"], "along"),
                           (checked["out0_m"], checked["out1_m"], "out")):
            if b <= a:
                raise InputError(
                    f"render_zone {what}1_m must exceed {what}0_m.")
            if b - a > 12.0:
                raise InputError(
                    f"render_zone spans {b - a:.1f}m in {what} — beyond "
                    f"12m this is not an extension. Check the units.")
        spec["render_zone"] = checked
    else:
        spec["render_zone"] = None
    # The designed-extension brief. It used to pass on an isinstance-dict
    # check alone, so {"ceiling_height_m": "nan"} sailed through to
    # propose's float() — NaN is truthy, so the or-default never applied —
    # and came out the other side as NaN wall heights and a bare NaN token
    # in the exported JSON. That is exactly the class of value _float exists
    # to refuse on every other numeric input, and the brief that DRIVES the
    # designed geometry was the one input that never got it. The fit-to-plot
    # ranges (depth 1-12m, storeys 1-3) stay propose's own, so its measured
    # "reduced"/"moved" answers still happen; this stops what nothing
    # downstream stops — NaN, infinity, and dimensions that are not
    # positive numbers.
    ext = job_input.get("extension")
    if isinstance(ext, dict):
        ext = dict(ext)             # never mutate the caller's input
        for f in ("depth_m", "width_m", "length_m", "return_width_m",
                  "bay_width_m", "ceiling_height_m"):
            if ext.get(f) is not None:
                ext[f] = _float(ext[f], f"extension.{f}")
                if ext[f] <= 0:
                    raise InputError(
                        f"extension.{f} must be a positive dimension in "
                        f"metres, got {ext[f]!r}")
        # A domestic ceiling outside this range is a unit mistake, not a
        # design choice — 2400 arrives when someone types millimetres.
        # Nothing after this point checks it: propose builds the room at
        # whatever height survives here, so 1e6 was a kilometre-tall wall.
        ch = ext.get("ceiling_height_m")
        if ch is not None and not 1.8 <= ch <= 4.5:
            raise InputError(
                f"extension.ceiling_height_m of {ch}m is not a domestic "
                f"ceiling (1.8 to 4.5m). Check the units — metres, not "
                f"millimetres.")
        if ext.get("storeys") is not None:
            ext["storeys"] = _int(ext["storeys"], "extension.storeys")
        if ext.get("type") is not None:
            ext["type"] = _one_of(str(ext["type"]).strip().lower(),
                                  "extension.type",
                                  ("rear", "side", "wrap", "over"))
        if ext.get("side") is not None:
            ext["side"] = _one_of(str(ext["side"]).strip().lower(),
                                  "extension.side", ("east", "west"))
        spec["extension"] = ext
    else:
        spec["extension"] = None
    # The interpreter carrying the bpy module for the Cycles render pass.
    # propose.py reads spec.get("render_python") three times, and this
    # whitelist never passed the field through — so it was documented, read
    # and unreachable, and every caller silently got the default interpreter
    # probe instead of the one they named.
    spec["render_python"] = (str(job_input.get("render_python") or "").strip()
                             or None)

    # A plain-English brief ("single storey rear extension with a bigger
    # kitchen"). brief.py turns it into the structured extension above when
    # no structured one was given — whitelisted here or it is dead input,
    # the same trap render_python fell into.
    spec["brief"] = (str(job_input.get("brief") or "").strip() or None)

    # A 3D-printable scale model of the result. Off unless asked for: an
    # STL is a physical deliverable, not a by-product. 1:50 is the desk
    # model; 1:10 to 1:500 covers everything a printer can hold.
    spec["print_scale"] = _int(job_input.get("print_scale"), "print_scale",
                               None, 10, 500)

    spec["extension_m2"] = _float(job_input.get("extension_m2"),
                                  "extension_m2", None, 1.0, 500.0)
    spec["build_cost"] = _float(job_input.get("build_cost"), "build_cost",
                                None, 100.0, 5_000_000.0)
    spec["tier"] = _one_of(job_input.get("tier"), "tier",
                           ("economy", "standard", "premium"),
                           default="standard")
    spec["registration_target"] = (
        str(job_input.get("registration_target") or "").strip() or None)
    # Design Mode: procedural rules in the CGA lineage — a footprint plus
    # rules produces the massing (PLAN.md §1.6).
    spec["design_rules"] = job_input.get("design_rules") or None

    # STOREYS AND ROOF LIVE INSIDE plan, AND PUTTING THEM OUTSIDE IT USED TO
    # BE SILENT. A job asking for {"storeys": 2, "roof": {...}} at the top
    # level came back as a single storey with no roof — the top-level `roof`
    # key belongs to ROOF mode, and top-level `storeys` is read by nothing.
    # Found by running a real job and reading the totals: 40.87 m2 and a
    # 2.4m "ridge", which is a bungalow with a flat top, not the two-storey
    # house that was asked for.
    #
    # Refused rather than quietly relocated, for the same reason a width
    # outside 0.3-200m is refused: the caller is telling us something about
    # the building, and guessing which of two readings they meant is how a
    # whole extra floor of quantities goes missing.
    if mode == "model":
        # Test the RAW plan, not the parsed one. parse fills plan.storeys
        # with its default of 1, so the parsed plan never looks absent and a
        # top-level storeys sailed through this check on its first outing.
        raw_plan = job_input.get("plan") or {}
        stray = [k for k in ("storeys", "roof", "storey_height_m")
                 if job_input.get(k) is not None
                 and raw_plan.get(k) is None]
        if stray:
            raise InputError(
                f"model mode reads {', '.join(stray)} from inside `plan`, not "
                f"from the top level of the job. As sent, "
                f"{'they were' if len(stray) > 1 else 'it was'} ignored and "
                f"the building would come back wrong — move "
                f"{'them' if len(stray) > 1 else 'it'} into `plan`.")

    _check_required_inputs(spec)
    return spec


def _check_required_inputs(spec):
    """Each mode needs particular inputs. Fail loudly and specifically —
    a job that runs for four minutes and then discovers it has nothing to
    work on is the worst outcome."""
    mode = spec["mode"]
    has_capture = bool(spec["video_url"] or spec["image_urls"]
                       or spec["roomplan_url"])

    if mode == "reconstruct" and not has_capture:
        raise InputError(
            "reconstruct needs a capture: video_url, image_urls, or "
            "roomplan_url.")

    if mode in ("structure", "services") and not (
            spec["point_cloud_url"] or spec["point_cloud_path"]
            or has_capture):
        raise InputError(
            f"{mode} needs point_cloud_url (or a capture to build one from).")

    if mode == "planning" and not (spec["address"] or spec["postcode"]
                                   or spec["gps"]):
        raise InputError(
            "planning needs an address, a postcode, or gps {lat, lon} to "
            "know which site to screen for designations.")

    if mode == "model" and not (spec["plan"] or spec["roomplan_url"]
                                or spec["roomplan_path"]):
        raise InputError(
            "model needs a plan (the rooms typed off the drawing's figured "
            "dimensions, each with a name, an x/y position in metres and a "
            "width_m and depth_m) or a scan: roomplan_url / roomplan_path "
            "pointing at an Apple RoomPlan JSON export.")


    if mode == "register" and not spec["registration_target"]:
        raise InputError(
            "register needs registration_target — the scan_id to align "
            "against (typically the open scan).")

    if mode == "price" and not (spec["ifc_url"] or spec["roomplan_url"]
                                or spec["point_cloud_url"]
                                or spec["quantities"]):
        raise InputError(
            "price needs measured quantities, or something to derive them "
            "from: pass quantities directly (roof mode returns them), or "
            "ifc_url, roomplan_url, or point_cloud_url.")

    if mode == "render":
        if not spec["gps"]:
            raise InputError(
                "render needs gps {lat, lon} of the HOUSE itself — a "
                "postcode centroid lands on the wrong roof. Pin the house "
                "first (the aerial from roof mode shows it).")
        if not spec["render_zone"]:
            raise InputError(
                "render needs render_zone — the measured rectangle the "
                "extension must stay inside. See validation of its fields.")

    if mode == "scan" and not (spec["scan_url"] or spec["scan_path"]):
        raise InputError(
            "scan mode needs scan_url or scan_path — the .ply your scanning "
            "app exported (Scaniverse: Share > Export Model > PLY; Polycam "
            "and Luma export the same). Add address or gps too and the "
            "scan's scale is checked against the mapped footprint.")

    if mode == "propose" and not (spec["address"] or spec["postcode"]
                                  or spec["gps"]):
        raise InputError(
            "propose needs an address, a postcode, or gps. Give it an "
            "address and it will find the outline, the roof and which way "
            "the house faces; on a terrace it needs gps for the house "
            "itself, because the map holds the whole row as one building.")

    if mode == "valuation" and not (spec["postcode"] or spec["address"]):
        raise InputError(
            "valuation needs a postcode (or an address containing one) to "
            "find sold comparables. HM Land Registry Price Paid Data covers "
            "England and Wales only.")

    # drawing_path counts. It is parsed and documented, and drawing.py reads
    # it — but this check demanded a URL, so a job carrying only a local file
    # was refused before it reached the code that would have used it. The
    # same dead-input shape as scale_observations: validated, then
    # unreachable. A worker with the PDF already on its volume, or an app
    # posting an upload the worker has written down, both look like this.
    if mode == "drawing" and not (spec["drawing_url"] or spec["drawing_path"]
                                  or spec["traced"]):
        raise InputError(
            "drawing mode needs drawing_url or drawing_path (a PDF to "
            "inspect), or traced geometry to measure.")

    if mode == "supply" and not (spec["price_list_csv"]
                                 or spec["price_list_url"]):
        raise InputError(
            "supply needs a price list: price_list_csv inline, or "
            "price_list_url pointing at a CSV export from your merchant "
            "account or a licensed product feed.")

    if mode == "condition" and not (spec["image_urls"] or spec["video_url"]
                                    or spec["thermal_urls"]):
        raise InputError(
            "condition needs imagery: image_urls, video_url or thermal_urls.")

    if mode == "roof" and not (spec["address"] or spec["gps"]
                               or spec["drone_image_urls"]
                               or spec["image_urls"]):
        raise InputError(
            "roof needs address or gps (to fetch open LIDAR coverage), or "
            "drone_image_urls / image_urls to reconstruct from.")

    if mode == "design" and not (spec["ifc_url"] or spec["design_rules"]):
        raise InputError(
            "design needs ifc_url (the measured as-built to build on) or "
            "design_rules (a procedural spec).")

    # The open/closed pairing is the product's core feature, and getting it
    # wrong silently is how a scan ends up unusable months later — by which
    # time the wall is boarded and it cannot be recaptured.
    if spec["stage"] == "open" and spec["quality"] == "fast":
        # Not an error: thin services (cable, small-bore pipe) sit near the
        # resolution limit, so a fast pass may miss them. Flagged, not blocked.
        spec.setdefault("warnings", []).append(
            "Open (first-fix) scans capture thin services near the resolution "
            "limit. quality='quality' or 'survey' is strongly recommended — "
            "this wall cannot be recaptured once it is boarded.")

    return spec
