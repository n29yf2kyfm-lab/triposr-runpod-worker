"""The HTTP layer. Thin on purpose.

Everything real happens in the providers, the registry and the property
engine; this file maps them onto URLs, validates input, and serves the
front end. Keeping it thin is what lets the same engine drive a CLI, a
batch job or a native app later without a rewrite.

WHY THE BROWSER NEVER TALKS TO A DATA SOURCE DIRECTLY. Three reasons,
all of them load-bearing: provider API keys must never reach a client;
the rate limits and caching in cache.py can only be honoured at one
chokepoint; and the licence checks are worthless if the front end can
route around them. So the browser talks to this, and this talks to the
world.
"""
from __future__ import annotations

import base64
import json
import os
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from . import cache as cache_mod
from . import geodesy, licences, property as property_mod
from .provenance import Missing
from .providers import registry as registry_mod

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

app = Flask(__name__, static_folder=None)
_registry = registry_mod.default()
_cache = cache_mod.default()


def _out(result):
    """One shape for every answer: available true/false, never a bare null.

    STATUS CODES MEAN WHAT HTTP SAYS THEY MEAN. "There is no building
    here" is a successful query with a negative answer — 200 with
    available:false — not a 404, which says the ENDPOINT is missing and
    makes every browser log an error for a normal result. Only a failure
    to reach the upstream is a server-side error, and that gets 502 so
    monitoring can tell a dead provider from an empty field.
    """
    body = result.as_dict() if hasattr(result, "as_dict") else result
    code = 200
    if isinstance(body, dict) and body.get("available") is False:
        if "failed to reach" in (body.get("reason") or ""):
            code = 502
    return Response(json.dumps(body, default=str), status=code,
                    mimetype="application/json")


def _float(name, required=True, lo=None, hi=None):
    raw = request.args.get(name)
    if raw in (None, ""):
        if required:
            raise ValueError(f"{name} is required")
        return None
    try:
        v = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}")
    if lo is not None and v < lo or hi is not None and v > hi:
        raise ValueError(f"{name} must be between {lo} and {hi}, got {v}")
    return v


@app.errorhandler(ValueError)
def _bad_request(e):
    return jsonify({"available": False, "status": "BAD REQUEST",
                    "reason": str(e)}), 400


@app.after_request
def _headers(resp):
    # No third-party anything: the front end is served from here and pulls
    # nothing off a CDN, which is both a licence and a privacy property.
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# -- the API -----------------------------------------------------------
@app.get("/api/health")
def health():
    return jsonify({"ok": True, "time": time.time(),
                    "providers": [p.name for p in _registry.providers]})


@app.get("/api/capabilities")
def capabilities():
    """What this platform can and cannot answer in a given country."""
    return jsonify(_registry.capabilities(request.args.get("country")))


@app.get("/api/licences")
def licence_registry():
    return jsonify({k: {
        "name": v.name, "url": v.url, "commercial": v.commercial,
        "attribution": v.attribution, "share_alike": v.share_alike,
        "redistribute": v.redistribute, "cache": v.cache, "notes": v.notes,
    } for k, v in licences.LICENCES.items()})


@app.get("/api/search")
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        raise ValueError("q is required — a postcode, address or place name")
    if len(q) > 300:
        raise ValueError("q is too long")
    return _out(_registry.geocode(q, country=request.args.get("country"),
                                  limit=int(request.args.get("limit", 6))))


@app.get("/api/reverse")
def reverse():
    return _out(_registry.reverse(_float("lat", lo=-90, hi=90),
                                 _float("lon", lo=-180, hi=180)))


@app.get("/api/buildings")
def buildings():
    w = _float("west", lo=-180, hi=180)
    s = _float("south", lo=-90, hi=90)
    e = _float("east", lo=-180, hi=180)
    n = _float("north", lo=-90, hi=90)
    if not (w < e and s < n):
        raise ValueError("bbox must be west<east and south<north")
    return _out(_registry.buildings(w, s, e, n))


@app.get("/api/property")
def property_at():
    """Fast essentials by default; ?include=slow adds the LIDAR layers.

    The default must stay quick enough to feel instant, because this is
    the call that fires on every tap.
    """
    lat = _float("lat", lo=-90, hi=90)
    lon = _float("lon", lo=-180, hi=180)
    slow = request.args.get("include") == "slow"
    return jsonify(property_mod.property_at(lat, lon, _registry,
                                            include_slow=slow))


@app.get("/api/elevation")
def elevation():
    return _out(_registry.elevation(_float("lat", lo=-90, hi=90),
                                   _float("lon", lo=-180, hi=180)))


@app.post("/api/measure")
def measure():
    """Measure any GeoJSON the client holds — including user-drawn.

    Server-side so that one implementation of the geodesic maths exists.
    A second copy in JavaScript would drift, and the number a builder
    orders from must not depend on which surface computed it.
    """
    body = request.get_json(silent=True) or {}
    geom = body.get("geometry")
    if not isinstance(geom, dict) or "type" not in geom:
        raise ValueError("body must be {\"geometry\": <GeoJSON geometry>}")
    if geom["type"] in ("Polygon", "MultiPolygon"):
        return jsonify({
            "available": True,
            "area_m2": round(geodesy.polygon_area(geom), 2),
            "perimeter_m": round(geodesy.perimeter(geom), 2),
            "centroid": geodesy.centroid(geom),
            "bbox": geodesy.bbox_of(geom),
            "method": "geodesic on WGS84",
        })
    if geom["type"] == "LineString":
        cs = geom["coordinates"]
        d = sum(geodesy.haversine(cs[i][1], cs[i][0], cs[i+1][1], cs[i+1][0])
                for i in range(len(cs) - 1))
        return jsonify({"available": True, "length_m": round(d, 2),
                        "method": "haversine on WGS84"})
    raise ValueError(f"cannot measure a {geom['type']}")


# -- imagery -----------------------------------------------------------
@app.get("/api/imagery")
def imagery_sources():
    """What can legitimately be shown here, and what each is blocked on."""
    from .providers import imagery as img
    return jsonify({"available": True,
                    "sources": img.for_country(request.args.get("country")),
                    "note": "Sources needing a key are unlocked by putting "
                            "one in the named environment variable on the "
                            "SERVER. Keys never reach the browser."})


@app.get("/api/surface")
def surface():
    """A shaded-relief PNG of the LIDAR surface over a lon/lat box.

    Rendered by us from Open Government Licence data, so there is no
    tile licence to breach and no key to hold. Returns the image plus
    the bounds it ACTUALLY covers, which is not the requested box —
    the National Grid and lon/lat are different rectangles.
    """
    from .providers import imagery as img
    w = _float("west", lo=-180, hi=180)
    s_ = _float("south", lo=-90, hi=90)
    e = _float("east", lo=-180, hi=180)
    n = _float("north", lo=-90, hi=90)
    if not (w < e and s_ < n):
        raise ValueError("bbox must be west<east and south<north")
    key = ("surface", round(w, 5), round(s_, 5), round(e, 5), round(n, 5))
    ck = cache_mod.Cache.key(*key)
    hit = _cache.get(ck)
    if hit is None:
        png, info = img.render_lidar_surface(w, s_, e, n)
        if png is None:
            return _out({"available": False, "status": "DATA NOT AVAILABLE",
                         "reason": info, "asked": ["uk-gov-open"]})
        hit = {"png": base64.b64encode(png).decode(), "info": info}
        _cache.put(ck, "uk-gov-open", "ogl-3.0", hit, ttl=180 * 86400)
    return jsonify({"available": True,
                    "image": "data:image/png;base64," + hit["png"],
                    **hit["info"]})


@app.get("/api/tiles/<source>/<int:z>/<int:x>/<int:y>")
def tiles(source, z, x, y):
    """Proxy a keyed XYZ source. THE KEY STAYS HERE.

    The browser asks this server for a tile; this server adds the key.
    A key in a front-end URL is a key on a pastebin within a week, and
    it is also how a licensed source becomes an unlicensed one when
    somebody copies the URL out of devtools.
    """
    from .providers import imagery as img
    try:
        src = img.get(source)
    except ValueError as e:
        raise ValueError(str(e))
    ok, why = src.usable()
    if not ok:
        return Response(json.dumps({"available": False,
                                    "status": "DATA NOT AVAILABLE",
                                    "reason": "; ".join(why)}),
                        status=403, mimetype="application/json")
    if not (0 <= z <= src.max_zoom and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise ValueError(f"tile {z}/{x}/{y} is outside this source")
    import requests as _rq
    try:
        r = _rq.get(img.tile_url(src, z, x, y), timeout=20,
                    headers={"User-Agent": "triposr-twin/0.1"})
    except Exception as ex:
        return Response(b"", status=502)
    if r.status_code != 200:
        return Response(b"", status=r.status_code)
    resp = Response(r.content,
                    mimetype=r.headers.get("Content-Type", "image/jpeg"))
    # Streamed, not stored: these licences permit display, not caching.
    resp.headers["Cache-Control"] = ("no-store" if not
                                     licences.get(src.licence).cache
                                     else "public, max-age=86400")
    return resp


# -- tiles: a licence gate, not a proxy --------------------------------
@app.get("/api/basemap")
def basemap():
    """Which basemaps this deployment is permitted to use, and why.

    The front end asks before it draws. A source whose terms forbid what
    we do with it is reported here as unavailable WITH the reason, so the
    restriction is visible in the product rather than buried in a file
    nobody reads. Stage 1 ships no raster basemap for exactly this
    reason — see KNOWN LIMITATIONS.
    """
    out = []
    for key in ("osm-tile-policy", "esri-world-imagery"):
        lic = licences.get(key)
        refusals = licences.check(key, licences.USE_EXPORT,
                                  licences.USE_COMMERCIAL, raises=False)
        out.append({"licence": key, "name": lic.name, "url": lic.url,
                    "usable_for_this_product": not refusals,
                    "refusals": refusals, "attribution": lic.attribution})
    return jsonify({
        "available": True,
        "sources": out,
        "note": "No raster basemap is bundled. Vector building footprints "
                "come from OpenStreetMap under ODbL and are drawn by our "
                "own renderer, which needs no tile licence.",
    })


# -- static front end --------------------------------------------------
@app.get("/favicon.ico")
def favicon():
    # A 404 per page load is noise that trains people to ignore the
    # console, which is where the real errors have to be visible.
    return Response(b"", status=204)


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/<path:name>")
def static_file(name):
    if ".." in name or name.startswith("/"):
        raise ValueError("bad path")
    return send_from_directory(WEB, name)


def main():
    port = int(os.environ.get("TWIN_PORT", "8000"))
    app.run(host="127.0.0.1", port=port, threaded=True)


if __name__ == "__main__":
    main()
