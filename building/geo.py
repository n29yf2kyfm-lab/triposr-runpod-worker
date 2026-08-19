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
import os

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


# --- a map you can actually put in a document ------------------------------
# site_map() hands back a LIVE geolibre widget, which is the right thing in
# a notebook and useless everywhere else: geolibre.Map.to_html() writes an
# <iframe> pointing at the hosted app (web.geolibre.app), so on a worker,
# in CI, or in any headless browser sandbox the page renders EMPTY — the
# app refuses to frame from file://, and the frame lands on an error page.
# A location plan is a deliverable, not a widget, so the tiles are fetched
# and composited here and the drawing is done on top of them. Same imagery
# layer, same attribution, no hosted application in the path.
TILE_PX = 256


def _tile_xy(lat_deg, lon_deg, zoom):
    """(lon, lat) -> fractional slippy-map tile coordinates (Web Mercator)."""
    n = 2.0 ** zoom
    x = (lon_deg + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat_deg))) / math.pi) / 2.0 * n
    return x, y


def static_map(model, anchor, path, zoom=19, span=1, red_line_margin_m=6.0,
               rooms=False, imagery=True, timeout=40):
    """Write a PNG location plan: aerial tiles with the building drawn on.

    span is tiles either side of centre, so the image is
    (2*span+1) * 256 px square. Returns (path, info) where info records the
    zoom actually used, how many tiles arrived and the metres per pixel —
    a plan whose scale is unstated is not a plan.

    Missing tiles are left dark rather than faked, and the count is
    reported: imagery coverage runs out at high zoom in places (Esri has
    no level 20 over parts of Birmingham), and a map that quietly drew
    nothing would be worse than one that says so.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:                          # pragma: no cover - optional
        raise RuntimeError("static_map needs Pillow (pip install pillow)")
    import requests

    cx, cy = _tile_xy(anchor.lat, anchor.lon, zoom)
    x0, y0 = int(cx) - span, int(cy) - span
    n = 2 * span + 1
    img = Image.new("RGB", (n * TILE_PX, n * TILE_PX), (36, 36, 36))
    got = 0
    if imagery:
        for i in range(n):
            for j in range(n):
                url = IMAGERY_XYZ.format(z=zoom, x=x0 + i, y=y0 + j)
                try:
                    r = requests.get(url, timeout=timeout)
                    if r.status_code == 200 and r.content:
                        import io
                        img.paste(Image.open(io.BytesIO(r.content))
                                  .convert("RGB"), (i * TILE_PX, j * TILE_PX))
                        got += 1
                except Exception:                # a missing tile is not fatal
                    pass

    def to_px(lon_, lat_):
        px, py = _tile_xy(lat_, lon_, zoom)
        return ((px - x0) * TILE_PX, (py - y0) * TILE_PX)

    dr = ImageDraw.Draw(img, "RGBA")
    data = geojson(model, anchor, red_line_margin_m=red_line_margin_m,
                   rooms=rooms)
    STYLE = {"red line": ((255, 40, 40, 255), 3),
             "building": ((255, 214, 0, 255), 3),
             "ridge":    ((255, 255, 255, 200), 2),
             "room":     ((120, 210, 255, 180), 1)}
    for f in data["features"]:
        colour, width = STYLE.get(f["properties"]["layer"],
                                  ((255, 255, 255, 200), 2))
        g = f["geometry"]
        if g["type"] == "Polygon":
            pts = [to_px(p[0], p[1]) for p in g["coordinates"][0]]
        else:
            pts = [to_px(p[0], p[1]) for p in g["coordinates"]]
        if len(pts) > 1:
            dr.line(pts, fill=colour, width=width)

    m_per_px = (156543.03392 * math.cos(math.radians(anchor.lat))
                / (2.0 ** zoom))
    # The caption carries the scale AND the anchor's provenance, so it is
    # laid out in lines that fit the image: running it as one string ran
    # the accuracy warning off the right edge, which is the one part of a
    # location plan that must never be the bit that gets cut.
    lines = [f"{model.get('name') or 'Proposed dwelling'}",
             f"{m_per_px:.2f} m/px at zoom {zoom} — "
             f"imagery: {IMAGERY_ATTR}",
             f"position is only as good as the anchor: {anchor.source}"]
    lh = 13
    bar = lh * len(lines) + 9
    dr.rectangle([0, img.size[1] - bar, img.size[0], img.size[1]],
                 fill=(0, 0, 0, 200))
    for i, line in enumerate(lines):
        while len(line) * 6 > img.size[0] - 14 and len(line) > 12:
            line = line[:-4] + "…"
        dr.text((7, img.size[1] - bar + 5 + i * lh), line,
                fill=(255, 255, 255, 255))
    img.save(path)
    return path, {"zoom": zoom, "tiles": got, "tiles_expected": n * n,
                  "m_per_px": round(m_per_px, 3),
                  "size_px": list(img.size),
                  "note": ("imagery incomplete at this zoom — "
                           "try a lower zoom" if imagery and got < n * n
                           else "")}


# --- the map you can actually move around ----------------------------------
# static_map answers "put it in a document". This answers the other half:
# pan it, zoom it, measure off it — on site, on a phone, with no signal.
#
# WHY NOT A MAP LIBRARY. MapLibre, Leaflet and geolibre all do this better
# in a browser with a network. None of them survives the job this is for:
# geolibre's export is a 6 KB iframe pointing at a website, so with no
# signal it is a grey box; MapLibre needs bundling and still fetches its
# tiles live. The whole value here is a file that works with the network
# unplugged, which means the tiles ship INSIDE it and nothing may be
# fetched at view time. That rules out every library, so the viewer is
# ~200 lines of canvas: pan, zoom, layers, a live scale bar and a tape
# measure. No dependency, no bundler, no CDN, no hosted app.
JPEG_QUALITY = 78


def _fetch_tiles(anchor, zooms, span, timeout):
    """{"z/x/y": jpeg-bytes} around the anchor, plus what went missing."""
    import io
    import requests
    from PIL import Image

    tiles, missing = {}, []
    for z in zooms:
        cx, cy = _tile_xy(anchor.lat, anchor.lon, z)
        x0, y0 = int(cx) - span, int(cy) - span
        for i in range(2 * span + 1):
            for j in range(2 * span + 1):
                x, y = x0 + i, y0 + j
                try:
                    r = requests.get(IMAGERY_XYZ.format(z=z, x=x, y=y),
                                     timeout=timeout)
                    if r.status_code != 200 or not r.content:
                        missing.append(f"{z}/{x}/{y}")
                        continue
                    buf = io.BytesIO()
                    (Image.open(io.BytesIO(r.content)).convert("RGB")
                     .save(buf, "JPEG", quality=JPEG_QUALITY))
                    tiles[f"{z}/{x}/{y}"] = buf.getvalue()
                except Exception:
                    missing.append(f"{z}/{x}/{y}")
    return tiles, missing


def interactive_map(model, anchor, path, zooms=(17, 18, 19), span=1,
                    red_line_margin_m=6.0, rooms=True, timeout=40):
    """Write a self-contained pannable map. Returns (path, info).

    Every tile is embedded, so the page opens offline and keeps working
    when the phone has no signal — which is the state a phone is in
    inside most houses being surveyed.
    """
    import base64
    import json as _json

    tiles, missing = _fetch_tiles(anchor, zooms, span, timeout)
    if not tiles:
        raise RuntimeError(
            "no imagery tiles could be fetched, so the map would be a "
            "blank page. Check network access to "
            + IMAGERY_XYZ.split("/ArcGIS")[0])
    encoded = {k: "data:image/jpeg;base64," + base64.b64encode(v).decode()
               for k, v in tiles.items()}
    data = geojson(model, anchor, red_line_margin_m=red_line_margin_m,
                   rooms=rooms)
    payload = {
        "tiles": encoded,
        "zooms": sorted(zooms),
        "geojson": data,
        "centre": [anchor.lon, anchor.lat],
        "zoom": max(zooms),
        "name": model.get("name") or "Proposed dwelling",
        "attribution": IMAGERY_ATTR,
        "anchor_source": anchor.source,
        "bearing_deg": anchor.bearing_deg,
    }
    html = _VIEWER_HTML % {"title": payload["name"].replace("<", ""),
                           "data": _json.dumps(payload)}
    with open(path, "w") as fh:
        fh.write(html)
    size = os.path.getsize(path)
    return path, {
        "tiles": len(tiles),
        "tiles_expected": len(zooms) * (2 * span + 1) ** 2,
        "missing": missing[:12],
        "zooms": sorted(zooms),
        "bytes": size,
        "offline": True,
        "note": ("some imagery tiles are missing and will show as dark "
                 "squares" if missing else ""),
    }


_VIEWER_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,
 maximum-scale=1,user-scalable=no">
<title>%(title)s</title>
<style>
 html,body{margin:0;height:100%%;background:#0b0b0d;overflow:hidden;
  font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  color:#f2f1ec;-webkit-text-size-adjust:100%%}
 canvas{display:block;touch-action:none;cursor:grab}
 canvas.drag{cursor:grabbing}
 .panel{position:fixed;background:rgba(14,14,16,.9);border-radius:10px;
  padding:10px 12px;backdrop-filter:blur(6px);
  box-shadow:0 2px 14px rgba(0,0,0,.5)}
 #hud{left:12px;top:12px;max-width:min(340px,calc(100vw - 24px))}
 #hud b{color:#ffd600;font-size:15px}
 #hud .sub{color:#9c9a92;font-size:12px;margin-top:3px}
 #tools{right:12px;top:12px;display:flex;flex-direction:column;gap:7px}
 label{display:flex;gap:8px;align-items:center;font-size:13px;cursor:pointer}
 button{background:#26262c;color:#f2f1ec;border:1px solid #3a3a44;
  border-radius:7px;padding:7px 11px;font-size:13px;cursor:pointer;
  font-family:inherit}
 button:hover{background:#33333c}
 button.on{background:#ffd600;color:#111;border-color:#ffd600}
 #scale{left:12px;bottom:12px;padding:7px 11px}
 #bar{height:5px;background:#f2f1ec;border:1px solid #111;
  border-top:none;margin-top:4px}
 #readout{right:12px;bottom:12px;font-variant-numeric:tabular-nums;
  max-width:min(300px,calc(100vw - 24px))}
 .k{color:#9c9a92}
 #north{position:fixed;right:16px;top:50%%;transform:translateY(-50%%);
  opacity:.85;pointer-events:none}
</style></head><body>
<canvas id="c"></canvas>
<div class="panel" id="hud"><b id="ttl"></b>
 <div class="sub" id="src"></div></div>
<div class="panel" id="tools">
 <label><input type="checkbox" id="lAerial" checked> Aerial</label>
 <label><input type="checkbox" id="lBuild" checked> Building</label>
 <label><input type="checkbox" id="lRed" checked> Red line</label>
 <label><input type="checkbox" id="lRoom" checked> Rooms</label>
 <button id="measure">Measure</button>
 <button id="reset">Recentre</button>
</div>
<svg id="north" width="34" height="46" viewBox="0 0 34 46">
 <polygon points="17,3 24,26 17,21 10,26" fill="#f2f1ec"/>
 <text x="17" y="42" font-size="13" fill="#f2f1ec" text-anchor="middle"
  font-family="system-ui">N</text></svg>
<div class="panel" id="scale"><span id="scaleTxt"></span><div id="bar"></div>
</div>
<div class="panel" id="readout"></div>
<script>
const D = %(data)s;
const TS = 256, R = 6378137.0;
const cv = document.getElementById('c'), cx = cv.getContext('2d');
const imgs = {};                       // "z/x/y" -> HTMLImageElement
for (const k in D.tiles) { const i = new Image(); i.src = D.tiles[k];
  i.onload = draw; imgs[k] = i; }

// --- projection. Web Mercator world pixels at a given (fractional) zoom.
function proj(lon, lat, z) {
  const n = TS * Math.pow(2, z);
  return [(lon + 180) / 360 * n,
          (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n];
}
function unproj(px, py, z) {
  const n = TS * Math.pow(2, z);
  const lon = px / n * 360 - 180;
  const lat = Math.atan(Math.sinh(Math.PI * (1 - 2 * py / n))) * 180 / Math.PI;
  return [lon, lat];
}
let zoom = D.zoom, centre = D.centre.slice();
const ZMIN = D.zooms[0] - 0.6, ZMAX = D.zooms[D.zooms.length - 1] + 2.2;
// Metres per SCREEN pixel — the number the scale bar and the tape both
// need, and the one a slippy map usually refuses to tell you.
function mpp() {
  return 156543.03392 * Math.cos(centre[1] * Math.PI / 180)
         / Math.pow(2, zoom) / dpr();
}
function dpr() { return Math.min(2, window.devicePixelRatio || 1); }

function resize() {
  const r = dpr();
  cv.width = Math.floor(innerWidth * r);
  cv.height = Math.floor(innerHeight * r);
  cv.style.width = innerWidth + 'px'; cv.style.height = innerHeight + 'px';
  draw();
}
// Screen (device px) position of a lon/lat.
function toScreen(lon, lat) {
  const c = proj(centre[0], centre[1], zoom), p = proj(lon, lat, zoom);
  const s = dpr();
  return [(p[0] - c[0]) * s + cv.width / 2, (p[1] - c[1]) * s + cv.height / 2];
}
function toLonLat(sx, sy) {
  const c = proj(centre[0], centre[1], zoom), s = dpr();
  return unproj(c[0] + (sx - cv.width / 2) / s,
                c[1] + (sy - cv.height / 2) / s, zoom);
}

const on = (id) => document.getElementById(id).checked;
const LAYER = {'red line': ['lRed', '#ff2828', 3],
               'building': ['lBuild', '#ffd600', 3],
               'ridge':    ['lBuild', '#ffffff', 2],
               'room':     ['lRoom', '#78d2ff', 1.4]};

function draw() {
  cx.setTransform(1, 0, 0, 1, 0, 0);
  cx.fillStyle = '#16161a'; cx.fillRect(0, 0, cv.width, cv.height);
  const s = dpr();
  if (on('lAerial')) {
    // Nearest available tile zoom, then scale it to the current view.
    let tz = D.zooms[0];
    for (const z of D.zooms) if (z <= Math.round(zoom)) tz = z;
    const scale = Math.pow(2, zoom - tz) * s, tp = TS * scale;
    const c = proj(centre[0], centre[1], tz);
    const originX = cv.width / 2 - c[0] * scale;
    const originY = cv.height / 2 - c[1] * scale;
    const i0 = Math.floor(-originX / tp), i1 = Math.ceil((cv.width - originX) / tp);
    const j0 = Math.floor(-originY / tp), j1 = Math.ceil((cv.height - originY) / tp);
    cx.imageSmoothingEnabled = true;
    for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) {
      // +1 closes the hairline seam sub-pixel placement leaves between tiles.
      const dx = originX + i * tp, dy = originY + j * tp, dw = tp + 1;
      const im = imgs[tz + '/' + i + '/' + j];
      if (im && im.complete && im.naturalWidth) {
        cx.drawImage(im, dx, dy, dw, dw);
        continue;
      }
      // NO TILE HERE. Only a few tiles ship, so at high zoom the edges of
      // the screen fall outside them and the map ended in a black band.
      // Fall back to the covering tile from a lower zoom and draw the
      // sub-square of it that belongs here — blurrier, but a map that
      // keeps going, which is what panning about on site needs.
      for (let k = 1; tz - k >= D.zooms[0]; k++) {
        const px = Math.floor(i / Math.pow(2, k));
        const py = Math.floor(j / Math.pow(2, k));
        const par = imgs[(tz - k) + '/' + px + '/' + py];
        if (!par || !par.complete || !par.naturalWidth) continue;
        const f = Math.pow(2, k), sub = TS / f;
        cx.drawImage(par, (i - px * f) * sub, (j - py * f) * sub, sub, sub,
                     dx, dy, dw, dw);
        break;
      }
    }
  }
  for (const f of D.geojson.features) {
    const spec = LAYER[f.properties.layer] || ['lBuild', '#ffffff', 2];
    if (!on(spec[0])) continue;
    const g = f.geometry;
    const ring = g.type === 'Polygon' ? g.coordinates[0] : g.coordinates;
    if (!ring || ring.length < 2) continue;
    cx.beginPath();
    ring.forEach((p, i) => { const q = toScreen(p[0], p[1]);
      i ? cx.lineTo(q[0], q[1]) : cx.moveTo(q[0], q[1]); });
    cx.lineWidth = spec[2] * s; cx.strokeStyle = spec[1];
    cx.lineJoin = 'round'; cx.stroke();
  }
  drawTape();
  scaleBar();
}

// --- the tape measure. Two taps, a distance in metres, on the ground.
let measuring = false, pts = [];
function haversine(a, b) {
  const [lo1, la1] = a, [lo2, la2] = b, r = Math.PI / 180;
  const dla = (la2 - la1) * r, dlo = (lo2 - lo1) * r;
  const h = Math.sin(dla / 2) ** 2
    + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dlo / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function drawTape() {
  if (!pts.length) return;
  const s = dpr();
  cx.save(); cx.strokeStyle = '#39ff88'; cx.fillStyle = '#39ff88';
  cx.lineWidth = 2 * s; cx.setLineDash([7 * s, 5 * s]);
  cx.beginPath();
  pts.forEach((p, i) => { const q = toScreen(p[0], p[1]);
    i ? cx.lineTo(q[0], q[1]) : cx.moveTo(q[0], q[1]); });
  cx.stroke(); cx.setLineDash([]);
  for (const p of pts) { const q = toScreen(p[0], p[1]);
    cx.beginPath(); cx.arc(q[0], q[1], 4.5 * s, 0, 7); cx.fill(); }
  cx.restore();
}
function tapeText() {
  if (pts.length < 2) return '';
  let t = 0;
  for (let i = 1; i < pts.length; i++) t += haversine(pts[i - 1], pts[i]);
  return t < 10 ? t.toFixed(2) + ' m' : t.toFixed(1) + ' m';
}

function scaleBar() {
  const m = mpp();
  let target = 120 * m;                              // aim for ~120 CSS px
  const pow = Math.pow(10, Math.floor(Math.log10(target)));
  const nice = [1, 2, 5, 10].map(v => v * pow)
                 .reduce((a, b) => Math.abs(b - target) < Math.abs(a - target)
                                   ? b : a);
  document.getElementById('bar').style.width = (nice / m) + 'px';
  document.getElementById('scaleTxt').textContent =
    (nice >= 1000 ? (nice / 1000) + ' km' : nice + ' m')
    + '  ·  ' + m.toFixed(3) + ' m/px';
  const tape = tapeText();
  document.getElementById('readout').innerHTML =
    (tape ? '<b style="color:#39ff88">' + tape + '</b><br>' : '')
    + '<span class="k">centre</span> ' + centre[1].toFixed(6) + ', '
    + centre[0].toFixed(6) + '<br><span class="k">zoom</span> '
    + zoom.toFixed(1)
    + (measuring ? '<br><span class="k">tap two points</span>' : '');
}

// --- input ------------------------------------------------------------
let drag = null;
cv.addEventListener('pointerdown', (e) => {
  cv.setPointerCapture(e.pointerId);
  drag = {x: e.clientX, y: e.clientY, moved: 0};
  cv.classList.add('drag');
});
cv.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const s = dpr();
  drag.moved += Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y);
  const c = proj(centre[0], centre[1], zoom);
  centre = unproj(c[0] - (e.clientX - drag.x) * s / s,
                  c[1] - (e.clientY - drag.y) * s / s, zoom);
  drag.x = e.clientX; drag.y = e.clientY;
  draw();
});
cv.addEventListener('pointerup', (e) => {
  cv.classList.remove('drag');
  const wasTap = drag && drag.moved < 6;
  drag = null;
  if (wasTap && measuring) {
    const s = dpr();
    if (pts.length >= 2) pts = [];
    pts.push(toLonLat(e.clientX * s, e.clientY * s));
    draw();
  }
});
cv.addEventListener('wheel', (e) => {
  e.preventDefault();
  zoomAt(e.clientX, e.clientY, -e.deltaY / 450);
}, {passive: false});
function zoomAt(clientX, clientY, dz) {
  const s = dpr(), before = toLonLat(clientX * s, clientY * s);
  zoom = Math.max(ZMIN, Math.min(ZMAX, zoom + dz));
  const after = toLonLat(clientX * s, clientY * s);
  centre = [centre[0] + before[0] - after[0], centre[1] + before[1] - after[1]];
  draw();
}
// Pinch, for the phone this is really for.
let pinch = null;
cv.addEventListener('touchmove', (e) => {
  if (e.touches.length !== 2) { pinch = null; return; }
  e.preventDefault();
  const [a, b] = e.touches;
  const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
  const mx = (a.clientX + b.clientX) / 2, my = (a.clientY + b.clientY) / 2;
  if (pinch) zoomAt(mx, my, Math.log2(d / pinch));
  pinch = d;
}, {passive: false});
cv.addEventListener('touchend', () => { pinch = null; });

['lAerial', 'lBuild', 'lRed', 'lRoom'].forEach((id) =>
  document.getElementById(id).addEventListener('change', draw));
document.getElementById('measure').addEventListener('click', (e) => {
  measuring = !measuring;
  e.target.classList.toggle('on', measuring);
  if (!measuring) pts = [];
  draw();
});
document.getElementById('reset').addEventListener('click', () => {
  centre = D.centre.slice(); zoom = D.zoom; draw();
});
document.getElementById('ttl').textContent = D.name;
document.getElementById('src').textContent =
  D.attribution + ' · position is only as good as the anchor: '
  + D.anchor_source;
addEventListener('resize', resize);
resize();
window.READY = () => Object.keys(imgs).length;
</script></body></html>"""


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
