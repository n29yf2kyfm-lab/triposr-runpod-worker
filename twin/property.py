"""Assemble everything known about one real property, and admit the rest.

This is the object the UI binds to. It pulls from the registry, measures
what it got, and returns a structure in which EVERY layer is either a
Sourced value or an explicit Missing. There is no partially-filled
dictionary where absent means zero.

THE SELECTION RULE. A click gives a point; a property is a polygon. The
building chosen is the one whose footprint CONTAINS the point, not the
nearest — nearest silently picks the neighbour when a user taps a garden,
and a neighbour's house presented as yours is the single worst failure
this product can have. A tap that lands in no footprint returns Missing
with the reason, and the UI offers "trace it yourself".
"""
from __future__ import annotations

import math

from . import geodesy
from .provenance import CLASS_DERIVED, Missing, Sourced
from .providers import registry as registry_mod


# A tap is a fingertip, not a survey point. Buildings are searched inside
# a small box around it so the query is cheap; 60 m comfortably contains
# any dwelling plus its neighbours.
SEARCH_RADIUS_M = 60.0


def _box(lat, lon, radius_m=SEARCH_RADIUS_M):
    """A search box SNAPPED TO A GRID, so nearby taps share a cache entry.

    The unsnapped version recomputed a box centred on the exact tap, so
    every tap produced a unique cache key and every tap paid for a live
    Overpass query — 63 seconds, measured, on a selection that should
    feel instant. Snapping to a ~120 m grid means the second tap on the
    same street is served from cache, and the box is grown to a full
    cell either side so a building near a cell edge is still wholly
    inside the queried area.
    """
    # The cell must NOT be derived from the query point: doing that gave
    # every tap a slightly different cell size, so no two taps ever
    # landed in the same cell and the snap bought nothing. Latitude uses
    # a fixed degree cell; longitude scales by the cosine of the SNAPPED
    # latitude, so the cell is stable within a band.
    cell_lat = (2 * radius_m) / 111320.0
    clat = math.floor(lat / cell_lat) * cell_lat
    cell_lon = cell_lat / max(0.05, math.cos(math.radians(clat)))
    clon = math.floor(lon / cell_lon) * cell_lon
    return (clon - cell_lon, clat - cell_lat,
            clon + 2 * cell_lon, clat + 2 * cell_lat)


def select_building(lat, lon, reg=None):
    """The footprint under this point, measured. Missing if none."""
    reg = reg or registry_mod.default()
    west, south, east, north = _box(lat, lon)
    fc = reg.buildings(west, south, east, north)
    if not fc:
        return fc                      # Missing, with its reason intact
    hits = [f for f in fc.value["features"]
            if geodesy.point_in_polygon(lon, lat, f["geometry"])]
    if not hits:
        return Missing(
            "no mapped building at this point",
            asked=(fc.provenance.source_provider,),
            detail=f"{len(fc.value['features'])} buildings were found within "
                   f"{SEARCH_RADIUS_M:.0f} m but none contains the point. "
                   f"Tap the roof itself, or trace the outline to create it "
                   f"as user geometry.")
    # Smallest containing polygon: a building inside a courtyard block, or
    # a house within a terrace outline, is the more specific answer.
    hits.sort(key=lambda f: geodesy.polygon_area(f["geometry"]))
    return Sourced(value=hits[0], provenance=fc.provenance,
                   classification=fc.classification)


def measure(feature) -> dict:
    """Areas and lengths of a footprint, in metres, geodesically."""
    g = feature["geometry"]
    ring = (g["coordinates"][0] if g["type"] == "Polygon"
            else g["coordinates"][0][0])
    c = geodesy.centroid(g)
    return {
        "footprint_area_m2": round(geodesy.polygon_area(g), 2),
        "perimeter_m": round(geodesy.perimeter(g), 2),
        "vertices": len(ring) - 1,
        "centroid": c,
        "bbox": geodesy.bbox_of(g),
        "method": "geodesic (spherical excess) on WGS84 — NOT planar "
                  "shoelace, which over-measures by 1/cos(latitude)",
    }


def _levels_from_tags(props):
    """OSM's own storey/height tags, or Missing. Never a default.

    A house with no `building:levels` is a house whose storey count we do
    not know. Substituting 2 here is how a bungalow becomes a two-storey
    on somebody's elevation drawing.
    """
    lv, h = props.get("levels"), props.get("height_m")
    out = {}
    for key, raw in (("levels", lv), ("height_m", h)):
        if raw in (None, ""):
            continue
        try:
            out[key] = float(str(raw).split()[0].replace("m", ""))
        except (ValueError, IndexError):
            continue
    return out or None


def property_at(lat, lon, reg=None, include_slow=False) -> dict:
    """Everything the platform can verify about the property at a point.

    TWO SPEEDS, ON PURPOSE. Footprint and address answer in about a
    second and are what the panel needs to exist at all. Elevation means
    pulling a LIDAR raster over WCS and can take tens of seconds — long
    enough that bundling it made the whole endpoint hang, which is how
    it was found. So the slow layers are opt-in (`include_slow`) and the
    UI fetches them separately and fills them in when they land. A panel
    that appears in one second and gains a height in twenty beats a
    blank screen for twenty-one.
    """
    reg = reg or registry_mod.default()
    building = select_building(lat, lon, reg)
    address = reg.reverse(lat, lon)
    country = None
    if address:
        country = address.value.get("country_code")
    if include_slow:
        elevation = reg.elevation(lat, lon, country=country)
    else:
        elevation = Missing(
            "not requested with this call",
            asked=(),
            detail="Elevation is fetched separately because it reads a "
                   "LIDAR raster; the panel requests it on its own.")
    parcel = reg.parcel(lat, lon, country=country)

    out = {
        "query": {"lat": lat, "lon": lon},
        "country": country,
        "capabilities": reg.capabilities(country),
        "address": address.as_dict(),
        "parcel": parcel.as_dict(),
        "elevation": elevation.as_dict(),
        "building": building.as_dict(),
    }

    if building:
        f = building.value
        m = measure(f)
        out["measurements"] = {
            "value": m,
            "classification": CLASS_DERIVED,
            "provenance": building.provenance.derive(
                "geodesic measurement of the published footprint",
                confidence=0.75).as_dict(),
            "available": True,
        }
        tags = _levels_from_tags(f["properties"])
        out["storeys"] = ({
            "available": True, "value": tags, "classification": "verified",
            "provenance": building.provenance.as_dict(),
        } if tags else Missing(
            "OpenStreetMap holds no storey count or height for this building",
            asked=("overpass",),
            detail="Height can be derived from LIDAR where covered, or "
                   "stated by the owner.").as_dict())

        # Cross-check the two independent height sources when both exist.
        # Agreement is worth showing; disagreement is worth showing MORE.
        if elevation and tags and tags.get("height_m"):
            lidar_h = elevation.value["height_above_ground_m"]
            osm_h = tags["height_m"]
            out["height_cross_check"] = {
                "lidar_m": lidar_h, "osm_tag_m": osm_h,
                "difference_m": round(abs(lidar_h - osm_h), 2),
                "agree": abs(lidar_h - osm_h) < 1.5,
                "note": "Two independent measurements. Where they disagree "
                        "by more than 1.5 m, treat both as unconfirmed.",
            }
    else:
        out["measurements"] = building.as_dict()
        out["storeys"] = building.as_dict()
    return out
