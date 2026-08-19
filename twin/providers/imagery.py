"""Something to look at the property ON, obtained legitimately.

THE PROBLEM, STATED HONESTLY. Free, worldwide, house-scale photographic
imagery does not exist. Every provider that has it — Esri, Google, Bing,
Mapbox — pays aircraft and satellite operators for it and licenses it
accordingly. A product that ships their tiles without a licence is not
clever, it is a breach that renders correctly until somebody notices.

So this module does three things instead:

1. RENDERS OUR OWN for the UK, from Environment Agency LIDAR. Open
   Government Licence, no key, no account, 1 m cells. It is not a photo:
   it is a shaded relief of the SURFACE, which for the work this product
   does is arguably better — roof planes, ridges, hips, dormers, garden
   levels and boundary walls all read clearly, and unlike a photo it is
   a MEASUREMENT with a height behind every pixel.

2. CARRIES OPEN PHOTOGRAPHIC SOURCES where a country publishes them.
   USGS covers the United States at sub-metre in the public domain.
   Sentinel-2 covers the world but at ~10 m, which is a street, not a
   house — declared as such rather than offered as if it were aerial.

3. TAKES YOUR OWN KEY for the commercial providers. Esri, Mapbox,
   MapTiler and Ordnance Survey all sell exactly the imagery wanted here,
   most with a free developer tier that permits commercial use. Putting
   a key in the environment is the licensed door, and it is the same
   imagery. The key stays server-side and is never sent to a browser.

Sources declare their own licence key and the registry refuses one whose
terms do not permit the use — the check is not skippable.
"""
from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass
from typing import Optional

from .. import licences


@dataclass(frozen=True)
class ImagerySource:
    key: str
    name: str
    kind: str                 # "xyz" | "rendered"
    licence: str
    countries: tuple          # ("*",) or ISO codes
    resolution_m: float       # ground sample distance, honestly stated
    url: Optional[str] = None
    api_key_env: Optional[str] = None
    attribution: str = ""
    note: str = ""
    max_zoom: int = 19

    @property
    def needs_key(self) -> bool:
        return bool(self.api_key_env)

    @property
    def key_present(self) -> bool:
        return bool(self.api_key_env and os.environ.get(self.api_key_env))

    def usable(self, commercial=True):
        """(bool, [reasons]) — licence first, then key, then coverage."""
        bad = licences.check(self.licence, licences.USE_RENDER,
                             *( [licences.USE_COMMERCIAL] if commercial else []),
                             raises=False)
        if self.needs_key and not self.key_present:
            bad.append(f"needs an API key in ${self.api_key_env} — free "
                       f"developer tiers exist for this provider")
        return (not bad), bad

    def as_dict(self):
        ok, why = self.usable()
        return {"key": self.key, "name": self.name, "kind": self.kind,
                "licence": self.licence, "countries": list(self.countries),
                "resolution_m": self.resolution_m, "usable": ok,
                "blocked_because": why, "attribution": self.attribution,
                "note": self.note, "needs_key": self.needs_key,
                "key_present": self.key_present, "max_zoom": self.max_zoom}


SOURCES = {
    # -- rendered by us, from open measurement -------------------------
    "lidar-hillshade": ImagerySource(
        key="lidar-hillshade",
        name="LIDAR shaded relief (Environment Agency, 1 m)",
        kind="rendered", licence="ogl-3.0", countries=("GB",),
        resolution_m=1.0,
        attribution="Environment Agency National LIDAR Programme "
                    "(Open Government Licence v3.0)",
        note="Not a photograph — a shaded surface model. Every pixel has "
             "a height behind it, so roof planes, ridges, dormers and "
             "garden levels read directly. England only; Wales and "
             "Scotland run separate programmes.",
        max_zoom=21),

    # -- open photographic, where a country publishes it ---------------
    "usgs-imagery": ImagerySource(
        key="usgs-imagery", name="USGS Imagery (United States)",
        kind="xyz", licence="us-public-domain", countries=("US",),
        resolution_m=0.6,
        url="https://basemap.nationalmap.gov/arcgis/rest/services/"
            "USGSImageryOnly/MapServer/tile/{z}/{y}/{x}",
        attribution="USGS The National Map",
        note="Public domain aerial imagery, sub-metre in most of the "
             "conterminous US.", max_zoom=19),

    "s2cloudless": ImagerySource(
        key="s2cloudless", name="Sentinel-2 cloudless (EOX)",
        kind="xyz", licence="cc-by-nc-sa-4.0", countries=("*",),
        resolution_m=10.0,
        url="https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/"
            "default/g/{z}/{y}/{x}.jpg",
        attribution="Sentinel-2 cloudless by EOX IT Services GmbH "
                    "(contains modified Copernicus Sentinel data 2020)",
        note="WORLDWIDE BUT 10 m PER PIXEL — a street, not a house. Good "
             "for context and useless for a roof. NON-COMMERCIAL licence, "
             "so it is refused for a paid product.", max_zoom=14),

    # -- commercial, unlocked by YOUR key ------------------------------
    "esri-keyed": ImagerySource(
        key="esri-keyed", name="Esri World Imagery (ArcGIS Location Platform)",
        kind="xyz", licence="esri-keyed", countries=("*",),
        resolution_m=0.3,
        url="https://ibasemaps-api.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}?token={key}",
        api_key_env="ARCGIS_API_KEY",
        attribution="Esri, Maxar, Earthstar Geographics",
        note="The SAME imagery the unlicensed tile endpoint serves, "
             "obtained the licensed way. ArcGIS Location Platform has a "
             "free tier that permits commercial use; the key goes in "
             "$ARCGIS_API_KEY on the server and never reaches a browser.",
        max_zoom=21),

    "mapbox-satellite": ImagerySource(
        key="mapbox-satellite", name="Mapbox Satellite",
        kind="xyz", licence="mapbox-keyed", countries=("*",),
        resolution_m=0.3,
        url="https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.jpg90"
            "?access_token={key}",
        api_key_env="MAPBOX_TOKEN",
        attribution="© Mapbox © Maxar",
        note="Free tier covers substantial monthly usage; commercial use "
             "permitted under the Mapbox terms.", max_zoom=21),

    "maptiler-satellite": ImagerySource(
        key="maptiler-satellite", name="MapTiler Satellite",
        kind="xyz", licence="maptiler-keyed", countries=("*",),
        resolution_m=0.5,
        url="https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg"
            "?key={key}",
        api_key_env="MAPTILER_KEY",
        attribution="© MapTiler © Planet",
        note="Free tier available; commercial use under MapTiler terms.",
        max_zoom=20),

    "os-premium": ImagerySource(
        key="os-premium", name="Ordnance Survey Maps API (Great Britain)",
        kind="xyz", licence="os-keyed", countries=("GB",),
        resolution_m=0.25,
        url="https://api.os.uk/maps/raster/v1/zxy/Outdoor_3857/{z}/{x}/{y}.png"
            "?key={key}",
        api_key_env="OS_DATA_HUB_KEY",
        attribution="© Crown copyright and database rights Ordnance Survey",
        note="OS Data Hub has a free OS OpenData tier and a paid Premium "
             "tier. Best cartography available for Great Britain.",
        max_zoom=20),
}


def for_country(country=None, commercial=True):
    """Every source, best first, each saying plainly if it is usable."""
    out = []
    for s in SOURCES.values():
        if country and "*" not in s.countries and country.upper() not in s.countries:
            continue
        out.append(s.as_dict())
    # Usable first, then finest resolution.
    out.sort(key=lambda d: (not d["usable"], d["resolution_m"]))
    return out


def get(key: str) -> ImagerySource:
    try:
        return SOURCES[key]
    except KeyError:
        raise ValueError(f"unknown imagery source {key!r}")


def tile_url(source: ImagerySource, z, x, y) -> str:
    """The upstream URL, with the key substituted SERVER-SIDE only."""
    if source.kind != "xyz" or not source.url:
        raise ValueError(f"{source.key} is not an XYZ source")
    key = os.environ.get(source.api_key_env or "", "")
    return source.url.format(z=z, x=x, y=y, key=key)


# ---------------------------------------------------------------- render
def _hillshade(grid, cell_m, azimuth_deg=315.0, altitude_deg=45.0,
               vertical_exaggeration=1.6):
    """Classic Horn shaded relief. Returns 0-255 float array.

    Light from the north-west at 45 degrees is the cartographic
    convention, and it matters: light from below reverses the perceived
    relief and every roof reads as a valley.
    """
    import numpy as np
    z = grid * vertical_exaggeration
    dzdx = np.zeros_like(z)
    dzdy = np.zeros_like(z)
    dzdx[1:-1, 1:-1] = ((z[:-2, 2:] + 2 * z[1:-1, 2:] + z[2:, 2:])
                        - (z[:-2, :-2] + 2 * z[1:-1, :-2] + z[2:, :-2])
                        ) / (8 * cell_m)
    dzdy[1:-1, 1:-1] = ((z[2:, :-2] + 2 * z[2:, 1:-1] + z[2:, 2:])
                        - (z[:-2, :-2] + 2 * z[:-2, 1:-1] + z[:-2, 2:])
                        ) / (8 * cell_m)
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(dzdy, -dzdx)
    az = math.radians(360.0 - azimuth_deg + 90.0)
    alt = math.radians(altitude_deg)
    shade = (math.sin(alt) * np.cos(slope)
             + math.cos(alt) * np.sin(slope) * np.cos(az - aspect))
    return np.clip(shade, 0, 1) * 255.0


def render_lidar_surface(west, south, east, north, max_px=1400):
    """A shaded-relief PNG of the LIDAR surface over a lon/lat box.

    Returns (png_bytes, info) or (None, reason). Rendered from the DSM,
    so what you see is the top of everything — roofs, walls, trees — at
    1 m. Height is also returned per pixel band so the client can show
    the actual elevation under the cursor rather than guessing at it.
    """
    import numpy as np
    from PIL import Image

    import sys
    b = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "building")
    if b not in sys.path:
        sys.path.insert(0, b)
    import osgb
    import roof as roofmod

    # The National Grid box that covers the requested lon/lat box.
    try:
        corners = [osgb.latlon_to_easting_northing(la, lo)
                   for lo, la in ((west, south), (east, south),
                                  (west, north), (east, north))]
    except Exception as e:
        return None, f"not on the British National Grid: {e}"
    es = [c[0] for c in corners]
    ns = [c[1] for c in corners]
    e0, e1, n0, n1 = min(es), max(es), min(ns), max(ns)
    span = max(e1 - e0, n1 - n0)
    if span > 600:
        return None, ("area too large for a 1 m surface render — zoom in "
                      "to about 600 m across")
    try:
        pts = roofmod.fetch_surface((e0, n0, e1, n1), roofmod.EA_WCS)
    except Exception as e:
        return None, f"LIDAR service unreachable: {type(e).__name__}: {e}"
    if not pts:
        return None, ("no LIDAR coverage here — the National LIDAR "
                      "Programme covers ~99% of England only")

    xs = sorted({round(p[0], 1) for p in pts})
    ys = sorted({round(p[1], 1) for p in pts})
    if len(xs) < 4 or len(ys) < 4:
        return None, "too few LIDAR cells here to shade"
    xi = {v: i for i, v in enumerate(xs)}
    yi = {v: i for i, v in enumerate(ys)}
    grid = np.full((len(ys), len(xs)), np.nan)
    for e, n, z in pts:
        # Rows run north to south, as an image does.
        grid[len(ys) - 1 - yi[round(n, 1)], xi[round(e, 1)]] = z
    # Fill gaps so the shading does not tear; nan would blank whole cells.
    if np.isnan(grid).any():
        med = float(np.nanmedian(grid))
        grid = np.where(np.isnan(grid), med, grid)

    cell = (xs[1] - xs[0]) or 1.0
    shade = _hillshade(grid, cell)

    # Tint by height so form AND level read at once: low ground cool,
    # roofs warm. Purely a visual encoding of the same measurement.
    lo, hi = float(np.percentile(grid, 2)), float(np.percentile(grid, 98))
    t = np.clip((grid - lo) / max(0.5, hi - lo), 0, 1)
    r = shade * (0.62 + 0.38 * t)
    g = shade * (0.66 + 0.26 * t)
    bl = shade * (0.78 - 0.18 * t)
    rgb = np.dstack([r, g, bl]).astype(np.uint8)

    img = Image.fromarray(rgb, "RGB")
    if max(img.size) > max_px:
        s = max_px / max(img.size)
        img = img.resize((max(1, int(img.width * s)),
                          max(1, int(img.height * s))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)

    # The bounds the image ACTUALLY covers, back in lon/lat, so the
    # client can place it exactly rather than assuming it matches the
    # request. Grid and lon/lat boxes are not the same rectangle.
    sw = osgb.easting_northing_to_latlon(xs[0], ys[0])
    ne = osgb.easting_northing_to_latlon(xs[-1], ys[-1])
    return buf.getvalue(), {
        "bounds": [sw[1], sw[0], ne[1], ne[0]],     # W,S,E,N
        "cell_m": round(cell, 2),
        "size_px": list(img.size),
        "min_m_aod": round(float(np.min(grid)), 2),
        "max_m_aod": round(float(np.max(grid)), 2),
        "licence": "ogl-3.0",
        "attribution": SOURCES["lidar-hillshade"].attribution,
        "method": "Horn shaded relief, light from 315 deg at 45 deg, "
                  "1.6x vertical exaggeration, tinted by height",
    }
