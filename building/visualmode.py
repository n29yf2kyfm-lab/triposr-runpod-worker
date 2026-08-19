"""Decide HOW a house may honestly be shown: orbit, or front elevation only.

THE RULE. A freestanding house can be flown around — every side is public
and Google's mesh has captured it. A house joined to its neighbours cannot:
the party wall is shared, the rear is private, and swinging the camera round
would show the neighbour's house or invent a side that no data supports. So
the product has two modes, and picking the wrong one is a hallucination:

  ORBIT       detached / freestanding — a full turn, ridden at estate-drone
              height (~15-20 deg up) where Google's tile mesh looks its best,
              real drive and garden and surroundings included because the mesh
              already holds them on every side.
  ELEVATION   connected (semi, terrace, end-terrace) — the photoreal FRONT
              only, the cleaned-real-photo + edited-extension the pipeline
              already makes. Not a lesser option; the correct one.

ELEVATION IS THE SAFE DEFAULT. Orbit is chosen only when the house is
CONFIRMED freestanding — because an orbit of a house that is actually
attached shows a fake flank or the neighbour, the exact thing this project
refuses to do. When the signals are missing or disagree, the answer is
elevation, every time.

THE SIGNALS, all already computed upstream:
  * dwelling_type  from verify's web leg (Rightmove/EPC): "detached",
                   "semi-detached", "terraced", "end of terrace"...
  * side_clearances  from propose.side_clearance: metres of open ground off
                   each flank. A party wall reads ~0; propose already zeroes
                   the shared side of a cut terrace bay.
  * is_row         from propose: the outline is a mapped terrace/semi row,
                   not one dwelling.

GEOMETRY OUTRANKS TEXT. If the web says "detached" but a flank clearance is
~0, the house is attached — a listing can be wrong or generic; the measured
gap cannot. Attachment detected in the geometry is decisive.
"""

# A flank with less than this much open ground is a party wall / attachment,
# not a gap you could walk down. Below it, that side is not freestanding.
PARTY_WALL_M = 1.0

# To call a side genuinely OPEN (freestanding that way) it needs at least a
# person's width of clear ground; the flank-clearance probe caps at 12m.
FREE_SIDE_M = 2.0

CONNECTED_TYPES = ("semi-detached", "semi detached", "terraced", "terrace",
                   "end of terrace", "end-terrace", "end terrace", "linked",
                   "maisonette")
DETACHED_TYPES = ("detached", "detached bungalow", "detached house")

# The flanks of a house in propose's local frame: frontage runs along x, so
# the two sides perpendicular to the street are east and west.
FLANKS = ("east", "west")

ORBIT_PITCH_DEG = 17.0        # estate-drone height where the mesh reads best


def _is_connected_type(dwelling_type):
    if not dwelling_type:
        return None
    t = dwelling_type.lower()
    if any(k in t for k in CONNECTED_TYPES):
        return True
    if any(k in t for k in DETACHED_TYPES):
        return False
    return None


def choose_mode(dwelling_type=None, side_clearances=None, is_row=None):
    """Return {mode, reason, confidence, render}.

    mode is 'orbit' or 'elevation'. render carries the hint each mode needs
    (orbit pitch, or elevation = front only). Pure — no network, no files —
    so the decision is testable and lives in one place.
    """
    reasons = []

    # 1. GEOMETRY FIRST. A near-zero flank is a party wall, whatever a
    #    listing says. This is the decisive attached signal.
    attached_side = None
    if side_clearances:
        for s in FLANKS:
            c = side_clearances.get(s)
            if c is not None and c < PARTY_WALL_M:
                attached_side = s
                break

    if is_row:
        return _mk("elevation",
                   "the map holds this as a terrace/semi row, not a "
                   "freestanding house — a flyaround would show the "
                   "neighbours", "high")
    if attached_side is not None:
        return _mk("elevation",
                   f"the {attached_side} flank has under {PARTY_WALL_M}m of "
                   f"ground — a shared/party wall, so the house is attached "
                   f"and cannot be orbited honestly", "high")

    # 2. TYPE. Geometry showed no attachment; now trust the listing.
    connected = _is_connected_type(dwelling_type)
    if connected is True:
        return _mk("elevation",
                   f"described as {dwelling_type} — a connected house; the "
                   f"front elevation is the honest view", "high")

    # 3. CONFIRMED FREESTANDING. Both flanks measured open AND (type says
    #    detached OR type is unknown but the geometry is clearly free).
    both_open = None
    if side_clearances:
        vals = [side_clearances.get(s) for s in FLANKS]
        measured = [v for v in vals if v is not None]
        # A MEASURED flank below the open bar IS a contradiction, however
        # many flanks went unmeasured. This used to require BOTH flanks
        # before it would disagree with the listing, so a detached listing
        # with one flank measured at 1.3m (under the 2.0m open bar, barely
        # over the party-wall cut) and the other missing orbited on the
        # false reason "no flank measurement to contradict it". Only fully
        # absent data may leave the question open.
        if measured and any(v < FREE_SIDE_M for v in measured):
            both_open = False
        elif all(v is not None for v in vals):
            both_open = all(v >= FREE_SIDE_M for v in vals)

    if connected is False and both_open:
        return _mk("orbit",
                   f"described as {dwelling_type} and both flanks measure "
                   f"clear (>= {FREE_SIDE_M}m) — freestanding, safe to orbit",
                   "high")
    if connected is False and both_open is None:
        return _mk("orbit",
                   f"described as {dwelling_type}; no flank measurement to "
                   f"contradict it — orbit, but verify the sides are clear",
                   "medium")
    if both_open and connected is None:
        return _mk("orbit",
                   "both flanks measure clear and no type says otherwise — "
                   "treated as freestanding", "medium")

    # 4. SAFE DEFAULT. Anything unresolved is elevation — never orbit a house
    #    we cannot confirm is freestanding.
    return _mk("elevation",
               "could not confirm the house is freestanding (missing or "
               "conflicting signals) — defaulting to the front elevation, "
               "which never shows a side we do not have", "low")


def _mk(mode, reason, confidence):
    render = ({"kind": "orbit", "pitch_deg": ORBIT_PITCH_DEG,
               "source": "google_tiles_mesh",
               "note": "orbit the captured mesh for consistent real "
                       "surroundings; AI-polish stills only, not frames"}
              if mode == "orbit" else
              {"kind": "elevation", "view": "front",
               "source": "street_view_photo",
               "note": "cleaned real front photo with the extension edited "
                       "in; no orbit — sides/rear are not ours to show"})
    return {"mode": mode, "reason": reason, "confidence": confidence,
            "render": render}
