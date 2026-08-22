"""Input validation for the damage worker — copied in pattern, not imported.

Same two jobs as every worker here: a bad type returns a clear message instead
of a traceback, and unbounded input can't take the box down (an inspection
asking for 500 images would OOM the VLM). Plus the SSRF guard the building
worker earned — a worker that fetches any URL a caller names is a proxy into
the private network it runs in.

The one contract choice worth calling out: `findings` may be supplied directly
in place of `image_urls`. That is not a test affordance bolted on — it is how
the deterministic half of the product (scoring, pricing, 3D fusion, report)
stays usable without a GPU, and how a caller who already ran detection
elsewhere reuses this worker's scoring and reporting. Exactly the move the
building worker makes by accepting `quantities` directly instead of always
deriving them.
"""

MODES = ("inspect", "compare", "report")

# Region for repair pricing (see repair.py). Distinct from the vehicle's
# driving-side market, which lives on the vehicle spec.
PRICING_REGIONS = ("us", "uk", "eu", "asia", "mena", "au")

MAX_IMAGES = 40            # a thorough walk-around is ~12-20; 40 is generous
DEFAULT_MAX_IMAGES = 40
MAX_FINDINGS = 500         # a hail-damaged panel can carry dozens


class InputError(ValueError):
    """Malformed job input -> clean {"error": ...} instead of a traceback."""


class UnsafeURLError(InputError):
    """A URL the worker must not fetch on a caller's behalf."""


ALLOWED_URL_SCHEMES = ("http", "https")


def _one_of(value, name, allowed, default=None):
    if value is None:
        return default
    if value not in allowed:
        raise InputError(
            f"{name} must be one of {', '.join(allowed)} — got {value!r}")
    return value


def _str_list(value, name, max_len):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise InputError(f"{name} must be a list of strings")
    out = [str(v).strip() for v in value if str(v).strip()]
    if len(out) > max_len:
        raise InputError(
            f"{name} has {len(out)} entries; the cap is {max_len}. Split the "
            f"capture into multiple inspections.")
    return out


def _vehicle(value):
    """Normalise the optional vehicle spec. Free-form but type-checked."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InputError(
            'vehicle must be an object, e.g. {"make":"Tesla","model":"Model 3",'
            '"year":2022,"market":"us"}')
    out = {}
    for k in ("make", "model", "trim", "colour", "color", "body_style",
              "market", "region", "vin"):
        if value.get(k) not in (None, ""):
            out[k] = str(value[k]).strip()
    if value.get("year") not in (None, ""):
        try:
            out["year"] = int(value["year"])
        except (TypeError, ValueError):
            raise InputError(f"vehicle.year must be a number, got "
                             f"{value['year']!r}")
    return out or None


def _findings(value):
    """Accept a pre-computed findings array (skips the VLM stage)."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise InputError("findings must be a list of finding objects")
    if len(value) > MAX_FINDINGS:
        raise InputError(f"findings has {len(value)} entries; the cap is "
                         f"{MAX_FINDINGS}.")
    for i, f in enumerate(value):
        if not isinstance(f, dict):
            raise InputError(f"findings[{i}] must be an object")
    return value


def check_fetchable_url(url, field="url"):
    """Refuse a URL the worker should not fetch. Blocks non-HTTP schemes and
    any host resolving into loopback/private/link-local/reserved space (where
    cloud metadata and internal services live)."""
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
            f"{parsed.scheme or 'no'} scheme.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError(f"{field} has no host")
    try:
        infos = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80),
            proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise UnsafeURLError(f"{field}: cannot resolve {host!r} ({e})")
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (address.is_private or address.is_loopback or address.is_reserved
                or address.is_link_local or address.is_multicast
                or address.is_unspecified):
            raise UnsafeURLError(
                f"{field} resolves to {address}, a private or reserved "
                f"address. The worker only fetches public URLs.")
    return text


def parse_job(job_input):
    """Validate a raw job input into a normalised spec. Raises InputError with
    an actionable message on anything malformed."""
    if not isinstance(job_input, dict):
        raise InputError("input must be an object")

    mode = _one_of(job_input.get("mode"), "mode", MODES, default="inspect")

    spec = {
        "mode": mode,
        "scan_id": (str(job_input.get("scan_id") or "").strip() or None),
        "project_id": (str(job_input.get("project_id") or "").strip() or None),
        "vehicle": _vehicle(job_input.get("vehicle")),
        "image_urls": _str_list(job_input.get("image_urls"), "image_urls",
                                MAX_IMAGES),
        "image_b64s": job_input.get("image_b64s") or [],
        "findings": _findings(job_input.get("findings")),
        # pricing region; falls back to the vehicle market, then to US in
        # repair.py — never hard-fails for a missing region.
        "region": _one_of(
            (str(job_input.get("region")).strip().lower()
             if job_input.get("region") else None),
            "region", PRICING_REGIONS, default=None),
        # the trellis2 3D model to pin findings onto (optional).
        "glb_url": (str(job_input.get("glb_url") or "").strip() or None),
        "want_html": bool(job_input.get("want_html", True)),
        "want_fusion": bool(job_input.get("want_fusion", True)),
        # Annotated images: "both" (heat wash + boxes), "box", "heat", "light",
        # or None to skip. Only rendered for findings that carry a bbox.
        "overlay": job_input.get("overlay", "both"),
        # Paint-depth-gauge readings, one entry per panel measured. Optional
        # and independent of the photos: an inspector can send readings with
        # no images at all, or images with no readings. See
        # paint_thickness.normalize_reading for the per-entry shape. Left
        # deliberately loose here — that module coerces and, crucially, KEEPS
        # a no-reading entry, because "the gauge would not read" is the most
        # diagnostic result it produces.
        "paint_readings": (job_input.get("paint_readings")
                           if isinstance(job_input.get("paint_readings"), list)
                           else None),
        "paint_system": (str(job_input.get("paint_system") or "").strip().lower()
                         or None),
        # compare mode: the baseline to diff against.
        "baseline_findings": _findings_or_none(
            job_input.get("baseline_findings")),
        "baseline_scan_id": (str(job_input.get("baseline_scan_id") or "").strip()
                             or None),
    }

    if not isinstance(spec["image_b64s"], list):
        raise InputError("image_b64s must be a list of base64 strings")
    if len(spec["image_b64s"]) > MAX_IMAGES:
        raise InputError(f"image_b64s has {len(spec['image_b64s'])} entries; "
                         f"the cap is {MAX_IMAGES}.")

    # SSRF-check every URL the worker might fetch. Deferred DNS-rebinding is
    # the known gap (documented on the building worker); this stops the
    # straightforward attempt, which is the one that gets made.
    for u in spec["image_urls"]:
        check_fetchable_url(u, "image_urls[]")
    if spec["glb_url"]:
        check_fetchable_url(spec["glb_url"], "glb_url")

    _check_required(spec)
    return spec


def _findings_or_none(value):
    return _findings(value) if value is not None else None


def _check_required(spec):
    mode = spec["mode"]
    has_images = bool(spec["image_urls"] or spec["image_b64s"])
    has_findings = spec["findings"] is not None

    has_readings = bool(spec.get("paint_readings"))

    if mode == "inspect" and not (has_images or has_findings or has_readings):
        raise InputError(
            "inspect needs image_urls / image_b64s to analyse, a "
            "pre-computed findings array to score, price and report, or "
            "paint_readings from a paint depth gauge.")

    if mode == "report" and not has_findings:
        raise InputError(
            "report mode re-renders an existing inspection — pass its "
            "findings array (and optionally vehicle, region, glb_url).")

    if mode == "compare":
        if not (has_images or has_findings):
            raise InputError(
                "compare needs the current capture: image_urls / image_b64s "
                "or a findings array.")
        if not (spec["baseline_findings"] or spec["baseline_scan_id"]):
            raise InputError(
                "compare needs a baseline to diff against: baseline_findings "
                "(the earlier inspection's findings) or baseline_scan_id.")
    return spec
