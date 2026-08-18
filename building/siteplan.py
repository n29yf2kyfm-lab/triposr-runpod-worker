"""The site plan: our building on the map, with what a map cannot know.

Named siteplan and not site because `site` is a Python standard-library
module imported during interpreter startup — a file called site.py on the
path is the kind of landmine that breaks an endpoint at boot and not in
testing.

geo.py puts the measured model on the planet. This module makes that a
SITE — a complete GeoLibre project a builder opens in one file, carrying
the layers a planning conversation actually needs:

    red line           the application boundary
    building           the footprint, traced from the external walls
    services           mep.py's routed pipes and cables, on the map
    PD envelope        how far Class A permitted development would let a
                       rear extension go on this plot
    shadow             where the building throws shade at a chosen date
                       and hour, which is the neighbour-amenity argument

WHY A PROJECT AND NOT A SCREENSHOT. GeoLibre reads a project file: layers,
styles, view. Writing one means the builder gets something live — pan,
zoom, toggle, measure, switch to aerial — rather than a picture of a map.
The format is public and the licence is MIT, so this is the supported
seam, not a fork of somebody else's application.

WHAT IS OURS AND WHAT IS THEIRS. GeoLibre draws. The envelope and the
shadow are ours: they come from the GPDO limits and the solar geometry
this project already carries, and no GIS knows them. That division is the
point — we do not reimplement a map, and they do not know what a rear
extension may do.
"""
import math

import geo

# GPDO Schedule 2, Part 1, Class A — the householder limits learned in
# docs/UK_COMPLIANCE_KNOWLEDGE.md. These draw the ENVELOPE, they do not
# grant permission: Article 4 directions, conservation areas, listed
# buildings and previous extensions all bite, and the envelope says so.
PD_REAR_SINGLE_DETACHED_M = 4.0
PD_REAR_SINGLE_OTHER_M = 3.0
PD_REAR_SINGLE_LARGER_DETACHED_M = 8.0     # with prior approval
PD_REAR_SINGLE_LARGER_OTHER_M = 6.0
PD_REAR_TWO_STOREY_M = 3.0
PD_TWO_STOREY_BOUNDARY_M = 7.0             # min to the rear boundary
PD_CURTILAGE_COVER = 0.50

STYLE = {
    "red_line": {"fill_color": "#d1002a", "fill_opacity": 0.06,
                 "line_color": "#d1002a", "line_width": 3},
    "building": {"fill_color": "#2b3138", "fill_opacity": 0.85,
                 "line_color": "#11151a", "line_width": 1.5},
    "pd": {"fill_color": "#1f8a4c", "fill_opacity": 0.18,
           "line_color": "#1f8a4c", "line_width": 2},
    "shadow": {"fill_color": "#2a3550", "fill_opacity": 0.30,
               "line_color": "#2a3550", "line_width": 1},
    "rooms": {"fill_color": "#8d98a4", "fill_opacity": 0.35,
              "line_color": "#4a545e", "line_width": 1},
    "services": {"line_color": "#e0a020", "line_width": 2},
    "ridge": {"line_color": "#c8410d", "line_width": 2},
}

IMAGERY_XYZ = geo.IMAGERY_XYZ
IMAGERY_ATTR = geo.IMAGERY_ATTR


# --- solar geometry ---------------------------------------------------
# The same declination and hour-angle maths the 3D viewer uses, in Python,
# so a shadow on the map and a shadow in the walkthrough agree.

def sun_position(lat_deg, day_of_year, solar_hour):
    """(altitude, azimuth) in radians. Azimuth is from north, clockwise."""
    lat = math.radians(lat_deg)
    decl = math.radians(-23.44) * math.cos(
        2 * math.pi * (day_of_year + 10) / 365.25)
    H = math.radians((solar_hour - 12.0) * 15.0)
    alt = math.asin(math.sin(lat) * math.sin(decl)
                    + math.cos(lat) * math.cos(decl) * math.cos(H))
    az_south = math.atan2(
        math.sin(H),
        math.cos(H) * math.sin(lat) - math.tan(decl) * math.cos(lat))
    return alt, (az_south + math.pi) % (2 * math.pi)


def _hull(points):
    """Convex hull, monotone chain. A shadow envelope is a hull, not a
    silhouette — it is the area that MIGHT be shaded, which is the
    conservative direction for a neighbour-amenity argument."""
    pts = sorted(set((round(x, 6), round(y, 6)) for x, y in points))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2:
                (x1, y1), (x2, y2) = out[-2], out[-1]
                if ((x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1)) <= 0:
                    out.pop()
                else:
                    break
            out.append(p)
        return out

    return half(pts)[:-1] + half(reversed(pts))[:-1]


def shadow_local(model, anchor, day_of_year=355, solar_hour=12.0):
    """The shadow the building throws, in plan metres.

    21 December at noon by default: the worst case a planning officer
    asks about. Returns (ring, info) — and an empty ring when the sun is
    below the horizon or so low the shadow runs to the horizon, because
    a shadow 400 m long is not a drawing, it is a warning.
    """
    alt, az = sun_position(anchor.lat, day_of_year, solar_hour)
    info = {"day_of_year": day_of_year, "solar_hour": solar_hour,
            "altitude_deg": round(math.degrees(alt), 2),
            "azimuth_deg": round(math.degrees(az), 2)}
    if alt <= math.radians(3.0):
        info["note"] = ("sun at or below 3 degrees — no usable shadow "
                        "outline at this hour")
        return [], info

    ring, _ = geo.footprint_local(model)
    t = model.get("totals") or {}
    height = float(t.get("ridge_height_m") or t.get("eaves_height_m") or 5.0)
    reach = height / math.tan(alt)
    # away from the sun, in the PLAN's frame: the plan's +y is north
    # rotated by the anchor's bearing
    theta = az - math.radians(anchor.bearing_deg)
    dx = -reach * math.sin(theta)
    dy = -reach * math.cos(theta)
    info["reach_m"] = round(reach, 2)
    info["height_m"] = height
    return _hull(list(ring) + [(x + dx, y + dy) for x, y in ring]), info


def permitted_development_local(model, detached=True, larger=False,
                                two_storey=False):
    """The Class A envelope for a REAR extension, in plan metres.

    Drawn off the rear elevation of the existing building — which is the
    face at the largest y in this project's convention — because that is
    where a householder extension goes.
    """
    ex, ey = model["extent_m"]["x"], model["extent_m"]["y"]
    if two_storey:
        depth = PD_REAR_TWO_STOREY_M
        note = ("two-storey rear: 3 m beyond the original rear wall, and "
                "it must stay 7 m clear of the rear boundary")
    elif larger:
        depth = (PD_REAR_SINGLE_LARGER_DETACHED_M if detached
                 else PD_REAR_SINGLE_LARGER_OTHER_M)
        note = ("larger single-storey rear under the prior-approval "
                "procedure — not available on designated land")
    else:
        depth = (PD_REAR_SINGLE_DETACHED_M if detached
                 else PD_REAR_SINGLE_OTHER_M)
        note = "single-storey rear within Class A without prior approval"
    ring = [(ex[0], ey[1]), (ex[1], ey[1]),
            (ex[1], ey[1] + depth), (ex[0], ey[1] + depth)]
    return ring, {
        "depth_m": depth, "detached": bool(detached),
        "larger": bool(larger), "two_storey": bool(two_storey),
        "note": note,
        "warning": ("ENVELOPE, NOT PERMISSION. Class A is removed by "
                    "Article 4 directions and does not apply to flats or "
                    "listed buildings; conservation areas, previous "
                    "extensions and the 50% curtilage cap all bite. "
                    "Check with the LPA before relying on it."),
    }


def _feature(anchor, ring, layer, props, closed=True):
    coords = [list(geo.local_to_wgs84(anchor, x, y)) for x, y in ring]
    if closed:
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        geom = {"type": "Polygon", "coordinates": [coords]}
    else:
        geom = {"type": "LineString", "coordinates": coords}
    return {"type": "Feature", "geometry": geom,
            "properties": dict(props, layer=layer)}


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def layers(model, anchor, red_line_margin_m=6.0, rooms=False,
           services=False, pd=None, shadow=None):
    """Every layer of the site, as (name, FeatureCollection, style).

    Returned before any GeoLibre call so the same set can be written as
    plain GeoJSON, tested, or handed to another GIS entirely.
    """
    out = []
    base = geo.geojson(model, anchor, red_line_margin_m=red_line_margin_m,
                       rooms=rooms)
    by_layer = {}
    for f in base["features"]:
        by_layer.setdefault(f["properties"]["layer"], []).append(f)

    if "red line" in by_layer:
        out.append(("Red line", _fc(by_layer["red line"]), STYLE["red_line"]))
    if pd is not None:
        ring, info = permitted_development_local(model, **pd)
        out.append(("Permitted development envelope",
                    _fc([_feature(anchor, ring, "pd envelope", info)]),
                    STYLE["pd"]))
    if shadow is not None:
        ring, info = shadow_local(model, anchor, **shadow)
        if ring:
            out.append((f"Shadow {info['solar_hour']:.0f}h "
                        f"day {info['day_of_year']}",
                        _fc([_feature(anchor, ring, "shadow", info)]),
                        STYLE["shadow"]))
    if rooms and "room" in by_layer:
        out.append(("Rooms", _fc(by_layer["room"]), STYLE["rooms"]))
    if services and model.get("mep"):
        feats = []
        for r in model["mep"].get("runs", []):
            pts = [(p[0], p[1]) for p in r["points"]]
            if len(pts) < 2:
                continue
            feats.append(_feature(anchor, pts, "service",
                                  {"system": r["system"],
                                   "service": r["service"],
                                   "size": r["size"],
                                   "length_m": r["length_m"]},
                                  closed=False))
        if feats:
            out.append(("Services", _fc(feats), STYLE["services"]))
    if "ridge" in by_layer:
        out.append(("Ridge", _fc(by_layer["ridge"]), STYLE["ridge"]))
    if "building" in by_layer:
        out.append(("Building", _fc(by_layer["building"]), STYLE["building"]))
    return out


def project(model, anchor, name=None, zoom=19, imagery=True,
            basemap="positron", **kwargs):
    """A complete GeoLibre project: layers, styles and view."""
    try:
        from geolibre import project as glp
        from geolibre import authoring as gla
    except ImportError:                          # pragma: no cover
        raise RuntimeError(
            "geolibre is not installed (pip install geolibre); "
            "geo.write_geojson works without it")

    proj = glp.build_empty_project(
        name or (model.get("name") or "Proposed dwelling"),
        center=[anchor.lon, anchor.lat], zoom=zoom,
        basemap_url=basemap)
    if imagery:
        gla.add_layer(proj, glp.tile_layer(
            "Aerial imagery", IMAGERY_XYZ, attribution=IMAGERY_ATTR))
    for layer_name, data, style in layers(model, anchor, **kwargs):
        gla.add_layer(proj, glp.geojson_layer(layer_name, data, **style))
    gla.set_view(proj, center=[anchor.lon, anchor.lat], zoom=zoom)
    return proj


def write_project(model, anchor, path, **kwargs):
    """Write the project GeoLibre opens. Returns (path, summary)."""
    from geolibre import authoring as gla
    proj = project(model, anchor, **kwargs)
    gla.save_project(path, proj)
    return path, gla.describe_project(proj)


def describe(model, anchor, **kwargs):
    lines = [geo.describe(anchor, model)]
    for layer_name, data, _ in layers(model, anchor, **kwargs):
        n = len(data["features"])
        lines.append(f"  {layer_name:<34} {n} feature(s)")
    return "\n".join(lines)
