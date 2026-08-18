"""Put the measured building on the actual planet.

Everything else in this codebase works in the plan's own metres: the
model runs from (0, 0) to (9.4, 7.2) and knows nothing about where that
is. A builder needs it ON the plot — for the location and block plans a
planning application validates on, for the red line, and for checking the
footprint against what is actually there on satellite imagery.

This module is the bridge. Give it an ANCHOR — a latitude, a longitude
and the compass bearing of the plan's +y axis — and it maps the model's
local metres onto WGS84, emits GeoJSON, and (if geolibre is installed)
hands back a slippy map with the footprint drawn on a basemap.

TWO KINDS OF ACCURACY, and they are not the same:

  RELATIVE — the shape. A local tangent plane about the anchor is exact
  to well under a millimetre over a plot this size, so the footprint's
  dimensions, areas and angles survive the trip intact.

  ABSOLUTE — where that shape sits on the earth. Exactly as good as the
  anchor you supply, and no better. A phone GPS fix is 3-10 m; a corner
  digitised off OS MasterMap or a title plan is far better. This module
  cannot improve the anchor and does not pretend to; it records the
  anchor's stated source in the output so nobody downstream mistakes a
  GPS guess for a survey.

osgb.py converts WGS84 to the National Grid for finding LIDAR tiles, and
says plainly that its ~5 m Helmert transform is not good enough to place
a footprint. That is why the geometry here rides on the tangent plane
instead of going through the grid.
"""
import json
import math

# Metres per degree on the WGS84 ellipsoid — the standard series, good
# to a few millimetres per degree at UK latitudes.
def _m_per_deg(lat_deg):
    lat = math.radians(lat_deg)
    m_lat = (111132.92 - 559.82 * math.cos(2 * lat)
             + 1.175 * math.cos(4 * lat) - 0.0023 * math.cos(6 * lat))
    m_lon = (111412.84 * math.cos(lat) - 93.5 * math.cos(3 * lat)
             + 0.118 * math.cos(5 * lat))
    return m_lat, m_lon


class Anchor:
    """Where the plan's origin sits, and which way it faces.

    lat/lon locate the model's (0, 0) corner. bearing_deg is the compass
    bearing of the plan's +y axis — 0 when plan north IS true north,
    which is the assumption the floor plan's north point and Part O
    already carry, so a rotated plot must say so here.
    """

    def __init__(self, lat, lon, bearing_deg=0.0, source="unstated"):
        if not -90.0 <= lat <= 90.0:
            raise ValueError(f"latitude {lat} is not on the earth")
        if not -180.0 <= lon <= 180.0:
            raise ValueError(f"longitude {lon} is not on the earth")
        self.lat = float(lat)
        self.lon = float(lon)
        self.bearing_deg = float(bearing_deg) % 360.0
        self.source = source
        self._m_lat, self._m_lon = _m_per_deg(self.lat)

    def as_dict(self):
        return {"lat": self.lat, "lon": self.lon,
                "bearing_deg": self.bearing_deg, "source": self.source,
                "note": "absolute accuracy equals the anchor's; relative "
                        "geometry is exact on the local tangent plane"}


def local_to_wgs84(anchor, x, y):
    """Plan metres -> (lon, lat). GeoJSON order, which is lon first."""
    b = math.radians(anchor.bearing_deg)
    east = x * math.cos(b) + y * math.sin(b)
    north = -x * math.sin(b) + y * math.cos(b)
    return (anchor.lon + east / anchor._m_lon,
            anchor.lat + north / anchor._m_lat)


def wgs84_to_local(anchor, lon, lat):
    """(lon, lat) -> plan metres. The inverse, for checking."""
    east = (lon - anchor.lon) * anchor._m_lon
    north = (lat - anchor.lat) * anchor._m_lat
    b = math.radians(anchor.bearing_deg)
    return (east * math.cos(b) - north * math.sin(b),
            east * math.sin(b) + north * math.cos(b))


def _ring(points):
    """Close a ring and hand back GeoJSON coordinates."""
    ring = list(points)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return [list(p) for p in ring]


def footprint_local(model):
    """The building outline in plan metres, traced from the EXTERNAL
    WALLS rather than assumed rectangular — an L-shaped plan has an
    L-shaped footprint, and a location plan showing a rectangle over an
    L is a wrong drawing, not a simplified one.

    Falls back to the extent rectangle if the walls do not chain into a
    SINGLE closed ring, and says so in the returned flag. A detached
    annex or a courtyard plan produces two or more wall loops; tracing
    just the loop that happens to come first and calling it THE footprint
    would report a measured-looking area that quietly excludes a whole
    building, so a closure only counts when every external segment was
    consumed by it.
    """
    segs = []
    for w in model["walls"]:
        if not w.get("external"):
            continue
        if int(w.get("base_level") or 0) != 0:
            continue
        a = (round(w["start"][0], 4), round(w["start"][1], 4))
        b = (round(w["end"][0], 4), round(w["end"][1], 4))
        if a != b:
            segs.append((a, b))
    if segs:
        ring = [segs[0][0], segs[0][1]]
        used = {0}
        for _ in range(len(segs)):
            tail = ring[-1]
            for i, (a, b) in enumerate(segs):
                if i in used:
                    continue
                if a == tail:
                    ring.append(b); used.add(i); break
                if b == tail:
                    ring.append(a); used.add(i); break
            else:
                break
            if ring[-1] == ring[0] and len(used) > 2:
                if len(used) == len(segs):
                    return ring[:-1], True
                # The ring closed but external segments remain — a second
                # loop exists (detached annex, courtyard). A partial ring
                # must not travel labelled as traced.
                break
    ex, ey = model["extent_m"]["x"], model["extent_m"]["y"]
    return [(ex[0], ey[0]), (ex[1], ey[0]),
            (ex[1], ey[1]), (ex[0], ey[1])], False


def _area(points):
    """Shoelace area in square metres of a local-coordinate ring."""
    n = len(points)
    s = 0.0
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def geojson(model, anchor, red_line_margin_m=None, rooms=False):
    """A FeatureCollection a planner, a GIS or a solicitor can read.

    Carries the building footprint, the ridge line, and the red line —
    the site boundary a householder application is validated against.
    """
    feats = []
    ring, traced = footprint_local(model)
    t = model.get("totals") or {}
    feats.append({
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [_ring(
            [local_to_wgs84(anchor, x, y) for x, y in ring])]},
        "properties": {
            "layer": "building",
            "name": model.get("name") or "Proposed dwelling",
            "footprint_m2": round(_area(ring), 2),
            "floor_area_m2": t.get("floor_area_m2"),
            "storeys": model.get("storeys"),
            "eaves_m": t.get("eaves_height_m"),
            "ridge_m": t.get("ridge_height_m"),
            "outline": "traced from external walls" if traced
                       else "extent rectangle (external walls did not "
                            "chain into a single closed ring)",
        },
    })

    roof = model.get("roof") or {}
    if roof.get("ridge"):
        (rx0, ry0), (rx1, ry1) = roof["ridge"]
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [
                list(local_to_wgs84(anchor, rx0, ry0)),
                list(local_to_wgs84(anchor, rx1, ry1))]},
            "properties": {"layer": "ridge",
                           "ridge_height_m": roof.get("ridge_z_m")},
        })

    if red_line_margin_m:
        ex, ey = model["extent_m"]["x"], model["extent_m"]["y"]
        m = float(red_line_margin_m)
        box = [(ex[0] - m, ey[0] - m), (ex[1] + m, ey[0] - m),
               (ex[1] + m, ey[1] + m), (ex[0] - m, ey[1] + m)]
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [_ring(
                [local_to_wgs84(anchor, x, y) for x, y in box])]},
            "properties": {
                "layer": "red line",
                "site_area_m2": round(_area(box), 2),
                "note": "application site boundary — CHECK against the "
                        "title plan before submitting; this is a margin "
                        "around the building, not a legal boundary",
            },
        })

    if rooms:
        for r in model["rooms"]:
            box = [(r["x"], r["y"]), (r["x"] + r["width_m"], r["y"]),
                   (r["x"] + r["width_m"], r["y"] + r["depth_m"]),
                   (r["x"], r["y"] + r["depth_m"])]
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [_ring(
                    [local_to_wgs84(anchor, x, y) for x, y in box])]},
                "properties": {"layer": "room", "name": r["name"],
                               "level": r.get("base_level", 0),
                               "area_m2": r["area_m2"],
                               "kind": r.get("kind")},
            })

    return {"type": "FeatureCollection",
            "features": feats,
            "properties": {"anchor": anchor.as_dict(),
                           "crs": "EPSG:4326 (WGS84)"}}


def write_geojson(model, anchor, path, **kwargs):
    data = geojson(model, anchor, **kwargs)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=1)
    return path


# GeoLibre ships five vector styles and no imagery. 'positron' is the
# right default here: a location plan is drawn over clean street mapping,
# not a photograph. Imagery is opt-in, as an XYZ layer, for the different
# job of checking what is actually standing on the plot today.
BASEMAPS = ("positron", "bright", "liberty", "dark", "fiord")
IMAGERY_XYZ = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
               "World_Imagery/MapServer/tile/{z}/{y}/{x}")
IMAGERY_ATTR = "Esri World Imagery"


def site_map(model, anchor, basemap="positron", zoom=19,
             red_line_margin_m=6.0, imagery=False, **kwargs):
    """A GeoLibre map of the site with the footprint drawn on it.

    geolibre is optional: the GeoJSON above is the deliverable and needs
    nothing installed. This is the look-at-it layer.
    """
    try:
        import geolibre
    except ImportError:                          # pragma: no cover
        raise RuntimeError(
            "geolibre is not installed (pip install geolibre); "
            "write_geojson works without it")
    if basemap not in BASEMAPS and "://" not in str(basemap):
        raise ValueError(
            f"basemap {basemap!r} is not one of {BASEMAPS} and is not a "
            "style URL — GeoLibre carries no imagery basemap; pass "
            "imagery=True for an aerial tile layer instead")
    data = geojson(model, anchor, red_line_margin_m=red_line_margin_m,
                   **kwargs)
    m = geolibre.Map(center=[anchor.lon, anchor.lat], zoom=zoom,
                     basemap=basemap)
    if imagery:
        m.add_tile_layer(IMAGERY_XYZ, name="Aerial imagery",
                         attribution=IMAGERY_ATTR)
    m.add_geojson(data, name="Proposed dwelling")
    return m


def describe(anchor, model=None):
    ring, traced = footprint_local(model) if model else ([], False)
    lines = [f"Anchored at {anchor.lat:.6f}, {anchor.lon:.6f} "
             f"(bearing of plan north {anchor.bearing_deg:.1f} deg, "
             f"source: {anchor.source})"]
    if model:
        lines.append(f"  footprint {_area(ring):.1f} m2, "
                     + ("traced from external walls" if traced
                        else "extent rectangle"))
    lines.append("  relative geometry exact; absolute position is only as "
                 "good as the anchor")
    return "\n".join(lines)
