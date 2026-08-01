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


def _int(value, name, default=None, lo=None, hi=None):
    """Parse an int, clamp it, and name the field in any error."""
    if value is None:
        value = default
    if value is None:
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise InputError(f"{name} must be an integer, got {value!r}")
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def _float(value, name, default=None, lo=None, hi=None):
    if value is None:
        value = default
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise InputError(f"{name} must be a number, got {value!r}")
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
    must fail here rather than turn into a delivery. Zero and negative are
    refused outright: a zero-quantity line is either a measurement that
    failed or an element that is not there, and both are worth saying out
    loud instead of quietly pricing at nothing.
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
        try:
            number = float(amount)
        except (TypeError, ValueError):
            raise InputError(
                f"quantities[{name!r}] must be a number — got {amount!r}")
        if number != number or number in (float("inf"), float("-inf")):
            raise InputError(f"quantities[{name!r}] is not a finite number")
        if number <= 0:
            raise InputError(
                f"quantities[{name!r}] is {number}. A quantity must be "
                f"positive; drop the line rather than sending a zero.")
        out[name] = number
    return out or None


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
        "project_id": (str(job_input.get("project_id") or "").strip() or None),
        "scan_id": (str(job_input.get("scan_id") or "").strip() or None),
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
    spec["tier"] = _one_of(job_input.get("tier"), "tier",
                           ("economy", "standard", "premium"),
                           default="standard")
    spec["registration_target"] = (
        str(job_input.get("registration_target") or "").strip() or None)
    # Design Mode: procedural rules in the CGA lineage — a footprint plus
    # rules produces the massing (PLAN.md §1.6).
    spec["design_rules"] = job_input.get("design_rules") or None

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
            spec["point_cloud_url"] or has_capture):
        raise InputError(
            f"{mode} needs point_cloud_url (or a capture to build one from).")

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
