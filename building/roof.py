"""Roof Mode — measured roof geometry and takeoff.

Default path needs no drone and no site visit: the Environment Agency's
National LIDAR Programme covers ~99% of England at 1m with +/-15cm vertical
RMSE, as free open data. An address is enough to produce roof pitch, plane
areas, ridge/hip/valley lengths and a materials list.

Pipeline:
    address/gps -> National Grid -> footprint -> DSM & DTM
                -> normalise -> segment planes -> classify edges -> takeoff

HONEST LIMITS, stated in every result:
  * 1m sampling cannot resolve small dormers, porches or narrow roof planes.
  * +/-15cm vertical RMSE means pitch over a short run is uncertain — about
    +/-4 degrees over a 4m rafter run, worse over 2m.
  * The composite is assembled from surveys of different dates. An extension
    built after the last flight will not be there.
Anything derived from this is a strong estimate, not a survey. Where the
number has to be exact, verify on site.
"""
import os
import sys
import json
import math

import osgb
import paths
import roof_geometry as rg
import solar

# --- data sources ----------------------------------------------------------
# There is no formal REST API for EA LIDAR tiles: the portal is manual and
# tile URLs are derivable from the National Grid. Endpoints are therefore
# env-overridable so a change to the service can be corrected on the endpoint
# without rebuilding the image.
EA_WCS = os.environ.get(
    "EA_LIDAR_WCS",
    "https://environment.data.gov.uk/spatialdata/"
    "lidar-composite-digital-surface-model-last-return-dsm-1m/wcs")
EA_DTM_WCS = os.environ.get(
    "EA_LIDAR_DTM_WCS",
    "https://environment.data.gov.uk/spatialdata/"
    "lidar-composite-digital-terrain-model-dtm-1m/wcs")
POSTCODE_API = os.environ.get("POSTCODE_API", "https://api.postcodes.io")
# The OSM Foundation's own map API — a different operator from Overpass, and
# the reason roof mode survives Overpass refusing a datacentre IP range.
OSM_API = os.environ.get("OSM_API", "https://api.openstreetmap.org/api/0.6")
# Overpass is free community infrastructure and rate-limits under load. A
# transient failure there must never be allowed to silently degrade a quote,
# so try the public mirrors in turn before giving up.
OVERPASS_APIS = [u for u in os.environ.get(
    "OVERPASS_APIS",
    "https://overpass-api.de/api/interpreter,"
    "https://overpass.kumi.systems/api/interpreter,"
    "https://overpass.osm.ch/api/interpreter").split(",") if u.strip()]

# EA composite vertical accuracy. Carried into every result so a caller can
# see the error bar rather than infer false precision.
EA_VERTICAL_RMSE_M = 0.15
EA_CELL_M = 1.0

HTTP_TIMEOUT = 60

# Overpass rejects requests with no User-Agent — live-confirmed HTTP 406,
# which is not an obvious failure mode from the status code alone. Identify
# properly on every outbound call; it is also the courteous thing to do
# against free community infrastructure.
USER_AGENT = os.environ.get(
    "BUILDING_USER_AGENT",
    "building-scan/1.0 (roof takeoff; +https://github.com/n29yf2kyfm-lab)")
HTTP_HEADERS = {"User-Agent": USER_AGENT}


def _requests():
    import requests
    return requests


# --- location --------------------------------------------------------------

def resolve_location(spec):
    """Get WGS84 lat/lon and National Grid easting/northing for the job.

    Accepts explicit gps, or a UK postcode/address resolved via postcodes.io
    (free, no key). A full street address needs a geocoder with address-level
    coverage; postcode centroid is enough to select a LIDAR tile but NOT to
    identify which building — the footprint lookup does that.
    """
    gps = spec.get("gps")
    if isinstance(gps, dict) and gps.get("lat") is not None:
        lat, lon = float(gps["lat"]), float(gps["lon"])
    else:
        address = (spec.get("address") or "").strip()
        if not address:
            raise ValueError("roof mode needs gps or address")
        lat, lon = _geocode_uk(address)

    easting, northing = osgb.latlon_to_easting_northing(lat, lon)
    return {
        "lat": lat, "lon": lon,
        "easting": round(easting, 2), "northing": round(northing, 2),
        "grid_ref": osgb.grid_ref(easting, northing),
        "lidar_tile": osgb.lidar_tile_name(easting, northing),
    }


def _geocode_uk(address):
    """Resolve a UK postcode (or the postcode inside an address) to lat/lon."""
    token = address.replace(",", " ").split()[-2:]
    candidates = [" ".join(token), address.split(",")[-1].strip(), address]
    for candidate in candidates:
        cleaned = candidate.replace(" ", "").upper()
        if not cleaned:
            continue
        try:
            # Imported inside the attempt rather than above the loop. If the
            # HTTP library is missing the geocoder is simply unreachable, and
            # that is the same outcome as the network being down — the caller
            # needs the actionable "supply a postcode or gps" below, not an
            # ImportError raised three frames deep.
            requests = _requests()
            r = requests.get(f"{POSTCODE_API}/postcodes/{cleaned}",
                             headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                res = r.json().get("result") or {}
                if res.get("latitude") is not None:
                    return float(res["latitude"]), float(res["longitude"])
        except Exception as e:
            print(f"geocode attempt failed: {e}", file=sys.stderr)
    raise ValueError(
        f"could not resolve {address!r} to coordinates. Supply a UK postcode, "
        f"or pass gps: {{\"lat\": ..., \"lon\": ...}} directly.")


# --- footprint -------------------------------------------------------------

FOOTPRINT_CACHE_DIR = paths.resolve(
    "FOOTPRINT_CACHE_DIR", "building-outputs/footprints",
    "building-footprints")


def _cache_path(lat, lon):
    # ~11m resolution — fine enough to key one building, coarse enough that
    # repeat scans of the same property hit the same entry.
    return os.path.join(FOOTPRINT_CACHE_DIR, f"{lat:.4f}_{lon:.4f}.json")


def _footprints_from_overpass(lat, lon, radius_m):
    """Building outlines near a point, via Overpass. [] if none, None if the
    service could not be reached at all — the caller needs that difference."""
    requests = _requests()
    query = (f"[out:json][timeout:{HTTP_TIMEOUT}];"
             f"way(around:{radius_m},{lat},{lon})[building];"
             f"out geom;")
    for endpoint in OVERPASS_APIS:
        try:
            r = requests.post(endpoint, data={"data": query},
                              headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return [el["geometry"] for el in (r.json().get("elements") or [])
                    if len(el.get("geometry") or []) >= 4]
        except Exception as e:
            print(f"footprint via {endpoint} failed: {e}", file=sys.stderr)
    return None


def _footprints_from_osm_api(lat, lon, radius_m):
    """The same outlines from the OSM Foundation's own map API.

    Deliberately a SEPARATE service, not another Overpass mirror. Overpass
    was live-confirmed to serve this exact query happily from one host while
    refusing it from a RunPod worker every time — the signature of a
    datacentre IP range being rate-limited, which no number of Overpass
    mirrors fixes because they share that policy. api.openstreetmap.org is
    different infrastructure with a different one.

    Returns geometry in the same shape as the Overpass path so the caller
    does not care which answered.
    """
    import xml.etree.ElementTree as ET

    # Degrees per metre: latitude is constant, longitude narrows with it.
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    bbox = f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"

    try:
        r = _requests().get(f"{OSM_API}/map", params={"bbox": bbox},
                            headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"footprint via {OSM_API} failed: {e}", file=sys.stderr)
        return None

    nodes = {n.get("id"): (float(n.get("lat")), float(n.get("lon")))
             for n in root.findall("node")}
    out = []
    for way in root.findall("way"):
        if not any(t.get("k") == "building" for t in way.findall("tag")):
            continue
        # The API returns node references rather than inline geometry, so the
        # ring has to be reassembled from the node table.
        ring = [nodes[nd.get("ref")] for nd in way.findall("nd")
                if nd.get("ref") in nodes]
        if len(ring) >= 4:
            out.append([{"lat": a, "lon": b} for a, b in ring])
    return out


# Tried in order. Each is a different operator, so one being unreachable or
# rate-limiting this worker does not take roof mode down with it.
FOOTPRINT_SOURCES = (
    ("openstreetmap-api", _footprints_from_osm_api),
    ("overpass", _footprints_from_overpass),
)


def fetch_footprint(lat, lon, radius_m=30):
    """Building footprint polygon around a point, from OpenStreetMap.

    Returns a list of (easting, northing) in National Grid, or None. The
    footprint is what separates the target roof from its neighbours — without
    it, a terrace becomes one continuous surface.

    TWO INDEPENDENT SOURCES, and that is the point. Overpass is free
    community infrastructure that rate-limits hard, and it was live-confirmed
    serving this query from one host while refusing it from a RunPod worker
    three times running. Adding mirrors does not help when the block is on the
    address range; adding a different operator does.

    Cached on disk. Building outlines effectively never change, so re-querying
    for a property already scanned is both fragile and rude — though the cache
    only survives the worker unless a network volume is attached.
    """
    cached = _cache_path(lat, lon)
    if os.path.exists(cached):
        try:
            with open(cached) as f:
                return [tuple(p) for p in json.load(f)]
        except Exception:
            pass

    geometries = None
    for name, fetch in FOOTPRINT_SOURCES:
        found = fetch(lat, lon, radius_m)
        if found:
            print(f"footprint from {name}: {len(found)} candidates",
                  file=sys.stderr)
            geometries = found
            break
        if found == []:
            # Reached the service; it genuinely has no building here. Trying
            # another copy of the same map will not invent one.
            print(f"{name}: no buildings mapped at this location",
                  file=sys.stderr)
            geometries = []
            break

    if not geometries:
        return None

    best, best_d = None, float("inf")
    for geom in geometries:
        cy = sum(g["lat"] for g in geom) / len(geom)
        cx = sum(g["lon"] for g in geom) / len(geom)
        d = (cy - lat) ** 2 + (cx - lon) ** 2
        if d < best_d:
            best, best_d = geom, d

    if not best:
        return None

    polygon = [osgb.latlon_to_easting_northing(g["lat"], g["lon"])
               for g in best]
    try:
        paths.ensure(FOOTPRINT_CACHE_DIR)
        with open(cached, "w") as f:
            json.dump(polygon, f)
    except Exception as e:
        print(f"footprint cache write skipped: {e}", file=sys.stderr)
    return polygon


def point_in_polygon(x, y, polygon):
    """Ray casting. Used to clip elevation samples to one building."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def polygon_perimeter(polygon):
    """Perimeter in metres — the eaves/guttering estimate for a simple roof."""
    total = 0.0
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def polygon_area(polygon):
    """Plan area in square metres, by the shoelace formula.

    Far better than counting raster cells: the polygon is a true outline,
    while a 1m grid quantises the edge and loses or gains up to half a metre
    all the way round.
    """
    total = 0.0
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def distance_to_boundary(x, y, polygon):
    """Shortest distance from a point to the polygon's edge."""
    best = float("inf")
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq == 0 else max(
            0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


# How far inside the footprint a sample must sit to be trusted for fitting.
#
# A 1m cell straddling the wall line averages roof and ground into one
# height. Live-confirmed on a Birmingham semi: samples within 1m of the
# boundary had a median height above ground of 2.9m against 5.8m for
# interior samples, dragging the apparent eaves down to 2.5m on a two-storey
# house and the fitted pitch down to 26 degrees. At a 1m inset the same roof
# fits at 31 degrees, against 34 from an independent finite-difference check
# of the same surface (itself biased high, because creases at hips and
# ridges inflate local gradients).
#
# 1m rather than the geometric minimum of half a cell: it covers the cell
# footprint AND typical OpenStreetMap positional error, which is itself
# around a metre. Testing 0.5 to 1.25m showed no further gain beyond 0.5m,
# only fewer samples, so this is the conservative end of a flat optimum.
BOUNDARY_INSET_M = 1.0

# Below this sampling density the roof is described by too few points for
# edge topology to be trustworthy, even though pitch and area still are.
MIN_SAMPLES_PER_M2 = 0.45


# --- elevation -------------------------------------------------------------

_COVERAGE_CACHE = {}


def coverage_id(wcs_url):
    """Discover the WCS coverage id for a dataset.

    EA coverage ids embed a dataset UUID, e.g.
    '<uuid>__Lidar_Composite_Elevation_LZ_DSM_1m', so they cannot be
    hard-coded safely — they change when the dataset is republished. Read
    them from GetCapabilities once per process and cache.

    Each service publishes both an Elevation and a Hillshade coverage.
    Hillshade is a shaded-relief PICTURE, not heights — selecting it by
    accident would yield a plausible-looking raster of meaningless values,
    so match on Elevation explicitly.
    """
    if wcs_url in _COVERAGE_CACHE:
        return _COVERAGE_CACHE[wcs_url]

    requests = _requests()
    try:
        r = requests.get(wcs_url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT,
                         params={"service": "WCS",
                                 "request": "GetCapabilities"})
        r.raise_for_status()
        import re
        ids = re.findall(r"<wcs:CoverageId>([^<]+)</wcs:CoverageId>", r.text)
    except Exception as e:
        print(f"WCS GetCapabilities failed: {e}", file=sys.stderr)
        return None

    chosen = next((i for i in ids if "Elevation" in i), ids[0] if ids else None)
    _COVERAGE_CACHE[wcs_url] = chosen
    return chosen


def fetch_surface(bbox, wcs_url, cell_m=EA_CELL_M):
    """Fetch an elevation grid for a bounding box via WCS.

    Returns [(easting, northing, z)] or None. Failure is returned, not
    raised: a caller can still work from a supplied raster, and a clear
    "could not reach the data" beats a traceback.

    The service publishes on EPSG:27700 with axis labels E and N, so the
    subset is given in National Grid metres directly — no reprojection.
    """
    requests = _requests()
    cid = coverage_id(wcs_url)
    if not cid:
        print(f"no coverage id for {wcs_url}", file=sys.stderr)
        return None

    minx, miny, maxx, maxy = bbox
    # Repeated 'subset' params, one per axis — a dict would collapse them.
    params = [
        ("service", "WCS"), ("version", "2.0.1"), ("request", "GetCoverage"),
        ("coverageId", cid), ("format", "image/tiff"),
        ("subset", f"E({minx},{maxx})"), ("subset", f"N({miny},{maxy})"),
    ]
    try:
        r = requests.get(wcs_url, params=params, headers=HTTP_HEADERS,
                         timeout=HTTP_TIMEOUT)
        if r.status_code != 200 or not r.content:
            print(f"WCS {wcs_url} returned {r.status_code}: "
                  f"{r.text[:200]}", file=sys.stderr)
            return None
        return _decode_geotiff(r.content, bbox, cell_m)
    except Exception as e:
        print(f"WCS fetch failed: {e}", file=sys.stderr)
        return None


def _decode_geotiff(data, bbox, cell_m):
    """GeoTIFF bytes -> elevation samples in National Grid coordinates."""
    try:
        import numpy as np
        from PIL import Image
        from io import BytesIO
    except ImportError:
        print("numpy/PIL unavailable — cannot decode raster", file=sys.stderr)
        return None

    try:
        img = Image.open(BytesIO(data))
        arr = np.array(img, dtype="float64")
    except Exception as e:
        print(f"raster decode failed: {e}", file=sys.stderr)
        return None

    if arr.ndim != 2 or arr.size == 0:
        return None
    minx, miny, maxx, maxy = bbox
    rows, cols = arr.shape
    xs = np.linspace(minx, maxx, cols)
    # Raster rows run north to south.
    ys = np.linspace(maxy, miny, rows)

    points = []
    for i in range(rows):
        for j in range(cols):
            z = arr[i, j]
            # EA rasters use large negative values for no-data.
            if not np.isfinite(z) or z < -100 or z > 1400:
                continue
            points.append((float(xs[j]), float(ys[i]), float(z)))
    return points


def load_points(path_or_points):
    """Accept supplied elevation data so the mode works without network.

    Understands a list of tuples, or a file of 'x y z' per line (the ASCII
    grid export the EA portal produces).
    """
    if isinstance(path_or_points, list):
        return [tuple(map(float, p[:3])) for p in path_or_points]
    points = []
    with open(path_or_points) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                points.append((float(parts[0]), float(parts[1]),
                               float(parts[2])))
            except ValueError:
                continue
    return points


def normalise(dsm_points, dtm_points, min_height_m=2.0):
    """Subtract ground from surface, keeping only what stands above it.

    DSM includes buildings and vegetation; DTM is ground only. The difference
    isolates the structure. 2m removes hedges, cars, walls and bins while
    keeping any roof worth pricing.
    """
    if not dtm_points:
        return dsm_points
    ground = {}
    for x, y, z in dtm_points:
        ground[(round(x, 1), round(y, 1))] = z

    out = []
    for x, y, z in dsm_points:
        g = ground.get((round(x, 1), round(y, 1)))
        if g is None:
            continue
        if z - g >= min_height_m:
            out.append((x, y, z))
    return out


# --- entry point -----------------------------------------------------------

def run(spec, prog, output_dir):
    """Roof Mode. Returns (artifacts, result_fields) for the handler."""
    prog.stage("fetching")

    location = resolve_location(spec)
    prog.note(f"{location['grid_ref']} (tile {location['lidar_tile']})",
              **location)

    source = spec.get("roof_source") or "lidar_open"
    notes = []

    # --- elevation -----------------------------------------------------
    supplied = spec.get("point_cloud_url")
    if supplied and os.path.exists(supplied):
        points = load_points(supplied)
        dtm = None
        notes.append("Elevation from supplied data, not open LIDAR.")
    else:
        bbox = osgb.bbox_around(location["easting"], location["northing"])
        points = fetch_surface(bbox, EA_WCS)
        dtm = fetch_surface(bbox, EA_DTM_WCS) if points else None

    if not points:
        raise RuntimeError(
            "No elevation data. The Environment Agency LIDAR service could "
            "not be reached or returned nothing for this location. Coverage "
            "is England only (~99% at 1m). Supply point_cloud_url with an "
            "exported grid, or set roof_source='drone' with drone_image_urls.")

    prog.stage("clipping_footprint", points=len(points))

    # --- footprint -----------------------------------------------------
    footprint = fetch_footprint(location["lat"], location["lon"])
    eaves_m = footprint_area = None
    if footprint:
        before = len(points)
        inside = [p for p in points
                  if point_in_polygon(p[0], p[1], footprint)]
        # Fit only on samples clear of the wall line, so mixed roof/ground
        # cells cannot flatten the pitch or drag the eaves down. Area still
        # comes from the full polygon below, so the inset costs accuracy
        # nowhere — it only removes contaminated samples.
        points = [p for p in inside
                  if distance_to_boundary(p[0], p[1], footprint)
                  >= BOUNDARY_INSET_M]
        if len(points) < rg.MIN_PLANE_POINTS and inside:
            points = inside
            notes.append(
                f"Building too small to inset {BOUNDARY_INSET_M}m from its "
                f"own walls, so edge samples are included. Pitch may be "
                f"understated where 1m cells straddle the wall line.")
        eaves_m = polygon_perimeter(footprint)
        footprint_area = polygon_area(footprint)
        prog.note(f"{before} -> {len(inside)} in footprint -> {len(points)} "
                  f"clear of the {BOUNDARY_INSET_M}m edge")
    elif not spec.get("allow_unclipped"):
        # Without a footprint the samples cover the whole neighbourhood, not
        # one building. Live-confirmed when Overpass rate-limited mid-test:
        # the same house returned 2,696 m2 and 29,669 tiles — the entire
        # street. A warning is not enough for a number that wrong, because a
        # quote carrying it is worse than no quote at all.
        raise RuntimeError(
            "No building footprint could be found for this location, so the "
            "roof cannot be separated from its neighbours. Refusing to "
            "produce quantities that would cover the whole street. "
            "OpenStreetMap may not have this building mapped, or the lookup "
            "may have been rate-limited — retry, or pass an explicit "
            "footprint. Set allow_unclipped=true only for an isolated "
            "building with nothing else within 60m.")
    else:
        notes.append(
            "UNCLIPPED: no footprint was used, so these figures may include "
            "neighbouring buildings. Areas and quantities are upper bounds, "
            "not a takeoff.")

    if dtm:
        points = normalise(points, dtm)
        prog.note(f"{len(points)} points above ground after normalising")

    if len(points) < rg.MIN_PLANE_POINTS:
        raise RuntimeError(
            f"Only {len(points)} usable elevation samples for this building — "
            f"too few to fit a roof. The building may be newer than the last "
            f"LIDAR flight, or outside coverage.")

    # --- geometry -------------------------------------------------------
    prog.stage("fitting_planes")
    planes = rg.segment_planes(points)
    if not planes:
        raise RuntimeError("No roof planes could be fitted to this surface.")

    prog.stage("extracting_edges", planes=len(planes))
    edges = rg.find_edges(planes, EA_CELL_M)

    prog.stage("quantities")
    if footprint_area:
        density = len(points) / footprint_area
        if density < MIN_SAMPLES_PER_M2:
            notes.append(
                f"Thin sampling: {len(points)} usable points over "
                f"{footprint_area:.0f} m2 ({density:.2f}/m2). Pitch and area "
                f"remain sound, but ridge, hip and valley lengths are "
                f"low-confidence — measure those on site before ordering "
                f"ridge tiles or valley trough.")
    cell_area = EA_CELL_M ** 2
    q = rg.quantities(planes, edges, cell_area, EA_CELL_M,
                      eaves_length_m=eaves_m,
                      materials=(spec.get("design_rules") or {}).get("roof"),
                      footprint_area_m2=footprint_area)

    # Pitch confidence from the source's own vertical error, over the
    # shortest plane run present. A pitch without an error bar invites
    # someone to order tiles against it.
    smallest = min((p.plan_area(cell_area) for p in planes), default=0.0)
    run_m = math.sqrt(max(smallest, 1.0))
    q["pitch_uncertainty_deg"] = rg.pitch_uncertainty_deg(
        EA_VERTICAL_RMSE_M, run_m)

    # --- cross-check against Google Solar, when a key is configured -----
    # Independent source, finer imagery. Used to validate rather than
    # replace: the free path must stay the default, since Solar is metered
    # and its coverage is not universal.
    solar_result = cross_check = None
    if solar.available():
        solar_result = solar.parse_segments(
            solar.fetch_building_insights(location["lat"], location["lon"]))
        cross_check = solar.compare(q, solar_result)
        if cross_check:
            notes.extend(cross_check.get("notes", []))
            prog.note("cross-checked against Google Solar",
                      **{k: v for k, v in cross_check.items() if k != "notes"})

    # The 1m LIDAR pitch under-read is a property of the source data, not a
    # bug — state it whenever quantities came from that path.
    notes.append(rg.PITCH_BIAS_NOTE)

    # --- export ---------------------------------------------------------
    prog.stage("exporting")
    payload = {
        "location": location,
        "source": source,
        "vertical_rmse_m": EA_VERTICAL_RMSE_M,
        "cell_size_m": EA_CELL_M,
        "planes": [p.as_dict(cell_area) for p in planes],
        "edges": [e.as_dict() for e in edges],
        "quantities": q,
        "solar": solar_result,
        "cross_check": cross_check,
        "notes": notes,
        "limits": [
            "1m sampling cannot resolve small dormers, porches or narrow "
            "roof planes.",
            f"+/-{EA_VERTICAL_RMSE_M}m vertical RMSE: pitch is uncertain to "
            f"about +/-{q['pitch_uncertainty_deg']} degrees on the smallest "
            f"plane here.",
            "The LIDAR composite merges surveys of different dates — recent "
            "extensions or re-roofs may not appear.",
            "This is a strong estimate, not a survey. Verify on site before "
            "ordering or cutting.",
        ],
    }

    output_dir = paths.ensure(output_dir)
    scan = spec.get("scan_id") or location["grid_ref"].replace(" ", "")
    json_path = os.path.join(output_dir, f"roof_{scan}.json")
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)

    artifacts = [(json_path, f"roof/{scan}.json", None)]
    return artifacts, {
        "roof": payload,
        "quantities": q,
        "warnings": notes,
    }
