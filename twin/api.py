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


def _load_env(path=None):
    """Read keys from a file OUTSIDE the repository.

    Keys are not in git and never will be. They live in one file with
    mode 600 whose path can be overridden, so a deployment can point at
    a secrets mount instead. Anything already set in the real
    environment WINS — a container's injected secret must not be
    silently overwritten by a stale developer file.
    """
    path = path or os.environ.get("TWIN_ENV_FILE", "/root/.banana/env")
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError:
        return 0
    n = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip()
            n += 1
    return n


_load_env()

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
    # Project state is LIVE state. A cached /sheets.pdf is a superseded
    # drawing set re-shown after an edit with nothing on it saying so —
    # and a stale drawing is the one artefact this project must never
    # serve. The tile proxy sets its own longer-lived policy after this.
    if request.path.startswith("/api/project/"):
        resp.headers["Cache-Control"] = "no-store"
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


# -- projects: the editable twin ---------------------------------------
# In-process for now. A real deployment puts these in PostGIS with the
# owner and permissions on them; the Project object is already the unit
# that would be persisted, so that is a storage change, not a redesign.
_projects = {}


def _project(pid):
    pj = _projects.get(pid)
    if pj is None:
        raise ValueError(f"no project {pid!r} — it may have expired")
    return pj


def _state(pj, include=("plan", "massing")):
    from . import design as design_mod
    bld = pj.current()
    out = {"available": True, "project_id": pj.id,
           "building": bld.as_dict(), "history": pj.history()}
    if "plan" in include:
        out["plan"] = design_mod.floor_plan(bld)
    if "massing" in include:
        out["massing"] = design_mod.massing(bld)
    return out


@app.post("/api/project")
def create_project():
    """Start a twin from a real selected building."""
    from . import commands as cmd_mod
    from . import model as model_mod
    body = request.get_json(silent=True) or {}
    lat, lon = body.get("lat"), body.get("lon")
    if lat is None or lon is None:
        raise ValueError("lat and lon are required")
    sel = property_mod.select_building(float(lat), float(lon), _registry)
    if not sel:
        return _out(sel)
    addr = _registry.reverse(float(lat), float(lon))
    lidar = _registry.elevation(float(lat), float(lon), country="GB")
    bld = model_mod.from_footprint(
        sel.value,
        lidar=(lidar.value if lidar else None),
        address=(addr.value.get("label") if addr else None))
    pj = cmd_mod.Project(bld)
    _projects[pj.id] = pj
    return jsonify(_state(pj))


@app.get("/api/project/<pid>")
def get_project(pid):
    return jsonify(_state(_project(pid)))


@app.post("/api/project/<pid>/command")
def project_command(pid):
    """Apply ONE validated edit. Refusals carry a reason, not a stack."""
    from . import commands as cmd_mod
    pj = _project(pid)
    body = request.get_json(silent=True) or {}
    try:
        if body.get("text"):
            cmd = cmd_mod.parse_instruction(body["text"], pj.current())
        else:
            kind = body.get("kind")
            if not kind:
                raise ValueError("send {kind, ...} or {text}")
            cmd = cmd_mod.make(kind, **{k: v for k, v in body.items()
                                        if k != "kind"})  # kind is positional
        pj.apply(cmd)
    except cmd_mod.CommandError as e:
        return Response(json.dumps({"available": False,
                                    "status": "REFUSED", "reason": str(e)}),
                        status=422, mimetype="application/json")
    except KeyError as e:
        # A command body missing a required field is a malformed REQUEST,
        # not a server fault: without this, {"kind":"set_storeys"} with no
        # storeys was a 500 and a stack trace — on the endpoint whose
        # docstring promises refusals carry a reason.
        return Response(json.dumps({
            "available": False, "status": "REFUSED",
            "reason": f"the {body.get('kind', 'command')} command needs a "
                      f"value for {e.args[0]!r}"}),
            status=422, mimetype="application/json")
    except (TypeError, AttributeError):
        return Response(json.dumps({
            "available": False, "status": "REFUSED",
            "reason": f"a field in that {body.get('kind', 'command')} "
                      f"command has the wrong type — numbers must be "
                      f"numbers and text must be text"}),
            status=422, mimetype="application/json")
    return jsonify(dict(_state(pj), applied=cmd.as_dict()))


@app.post("/api/project/<pid>/undo")
def project_undo(pid):
    from . import commands as cmd_mod
    try:
        _project(pid).undo()
    except cmd_mod.CommandError as e:
        return Response(json.dumps({"available": False, "status": "REFUSED",
                                    "reason": str(e)}), status=422,
                        mimetype="application/json")
    return jsonify(_state(_project(pid)))


@app.post("/api/project/<pid>/redo")
def project_redo(pid):
    from . import commands as cmd_mod
    try:
        _project(pid).redo()
    except cmd_mod.CommandError as e:
        return Response(json.dumps({"available": False, "status": "REFUSED",
                                    "reason": str(e)}), status=422,
                        mimetype="application/json")
    return jsonify(_state(_project(pid)))


@app.post("/api/project/<pid>/restore")
def project_restore(pid):
    from . import commands as cmd_mod
    body = request.get_json(silent=True) or {}
    try:
        _project(pid).restore(int(body.get("version", 0)))
    except (cmd_mod.CommandError, TypeError) as e:
        return Response(json.dumps({"available": False, "status": "REFUSED",
                                    "reason": str(e)}), status=422,
                        mimetype="application/json")
    return jsonify(_state(_project(pid)))


@app.get("/api/project/<pid>/assess")
def project_assess(pid):
    """Regulations gate, bill of quantities and a priced estimate."""
    from . import design as design_mod
    per_m2 = request.args.get("calibrate_per_m2")
    return jsonify(design_mod.assess(
        _project(pid).current(),
        region=request.args.get("region"),
        vat=request.args.get("vat", "standard"),
        calibrate_per_m2=float(per_m2) if per_m2 else None))


@app.get("/api/project/<pid>/sheets")
def project_sheets_manifest(pid):
    """What the drawing set would contain, before anybody downloads it."""
    from . import design as design_mod
    from . import sheets as sheets_mod
    pj = _project(pid)
    paper = request.args.get("paper", "A3")
    scale = request.args.get("scale")
    try:
        built = sheets_mod.sheet_set(
            pj.current(), paper=paper,
            scale=int(scale) if scale else None,
            date=time.strftime("%Y-%m-%d"),
            assessment=design_mod.assess(pj.current()))
    except sheets_mod.SheetError as e:
        return Response(json.dumps({"available": False, "reason": str(e)}),
                        status=422, mimetype="application/json")
    return jsonify({"available": True, "paper": paper,
                    "manifest": built["manifest"],
                    "problems": built["problems"]})


@app.get("/api/project/<pid>/sheets.pdf")
def project_sheets_pdf(pid):
    """The drawing set itself: one true-scale PDF, ready to issue."""
    from . import design as design_mod
    from . import sheets as sheets_mod
    pj = _project(pid)
    scale = request.args.get("scale")
    try:
        out = sheets_mod.drawing_set(
            pj.current(), paper=request.args.get("paper", "A3"),
            scale=int(scale) if scale else None,
            date=time.strftime("%Y-%m-%d"),
            status=request.args.get("status") or None,
            assessment=design_mod.assess(pj.current()))
    except sheets_mod.SheetError as e:
        return Response(json.dumps({"available": False, "reason": str(e)}),
                        status=422, mimetype="application/json")
    return Response(out["pdf"], mimetype="application/pdf", headers={
        "Content-Disposition": 'inline; filename="drawing-set.pdf"',
        # So the client can show what could NOT be drawn without parsing
        # the PDF to find out.
        "X-Sheet-Manifest": json.dumps(out["manifest"]),
        "X-Sheet-Problems": json.dumps(out["problems"]),
    })


@app.get("/api/project/<pid>/ground")
def project_ground(pid):
    """Real imagery for the ground under THIS building, already placed.

    The 3D view drew the house on a flat coloured plane, which is why a
    correct model still read as CGI: a building with no context looks
    like a render of nothing. This drapes real imagery under it.

    The corners come back in BUILDING-FRAME METRES, not lon/lat. The
    projection maths lives in one place — here — so the browser cannot
    drift from the server about where the ground is, and a rotated
    house lands on rotated imagery rather than an axis-aligned smear.
    """
    from .providers import imagery as img
    pj = _project(pid)
    bld = pj.current()
    margin = _float("margin_m", required=False, lo=0, hi=200)
    # 45 m of street either side: enough that the neighbours, the road
    # and the back gardens are in shot, which is what makes the model
    # read as standing somewhere rather than floating.
    margin = max(6.0, min(120.0, 45.0 if margin is None else margin))
    want = request.args.get("source")

    xs, ys = [], []
    for b in bld.blocks:
        xs += [b.x - margin, b.x + b.width + margin]
        ys += [b.y - margin, b.y + b.depth + margin]
    if not xs:
        return _out({"available": False, "status": "DATA NOT AVAILABLE",
                     "reason": "there is no building to stand on",
                     "asked": []})
    # Corners of the local box -> lon/lat, then the lon/lat box that
    # contains them. The building frame is rotated, so the imagery box
    # must cover the rotated rectangle, not just its own diagonal.
    corners = [bld.to_lonlat(x, y)
               for x in (min(xs), max(xs)) for y in (min(ys), max(ys))]
    west = min(c[0] for c in corners)
    east = max(c[0] for c in corners)
    south = min(c[1] for c in corners)
    north = max(c[1] for c in corners)

    country = "GB"
    order = ([want] if want else
             [s["key"] for s in img.for_country(country) if s["usable"]])
    # CACHED ON THE BOX, NOT THE PROJECT. The LIDAR fetch takes seconds,
    # and the same ground serves every edit of the same house — and the
    # neighbour's twin too. Keyed on the rounded box so a nudge of the
    # extension does not re-fetch a picture of the same street.
    ckey = cache_mod.Cache.key("ground", want or "auto",
                               *(round(v, 4) for v in
                                 (west, south, east, north)))
    hit = _cache.get(ckey)
    if hit is not None:
        png = base64.b64decode(hit["png"])
        info, tried = hit["info"], hit["asked"]
    else:
        tried, png, info = [], None, None
        for key in order:
            tried.append(key)
            try:
                src = img.get(key)
            except (KeyError, ValueError):
                continue
            if key == "lidar-hillshade":
                png, info = img.render_lidar_surface(west, south, east, north)
            else:
                png, info = img.mosaic(src, west, south, east, north)
            if png:
                break
            png = None
        if png:
            # The cache refuses a licence that forbids keeping a copy,
            # so a source we may only stream is simply never stored.
            try:
                _cache.put(ckey, info.get("source", "lidar-hillshade"),
                           info.get("licence", "ogl-3.0"),
                           {"png": base64.b64encode(png).decode(),
                            "info": info, "asked": tried},
                           ttl=90 * 86400)
            except Exception:
                pass
    if not png:
        return _out({"available": False, "status": "DATA NOT AVAILABLE",
                     "reason": (info if isinstance(info, str) else
                                "no usable imagery source here"),
                     "asked": tried,
                     "note": "Sub-metre aerial worldwide needs a key of "
                             "your own — Esri, Mapbox, MapTiler and OS "
                             "all have free tiers that permit commercial "
                             "use. The key goes on the server."})

    # Back to building-frame metres, so the viewer just draws a quad.
    w2, s2, e2, n2 = info["bounds"]
    quad = [bld.from_lonlat(w2, s2), bld.from_lonlat(e2, s2),
            bld.from_lonlat(e2, n2), bld.from_lonlat(w2, n2)]
    mime = info.get("format", "image/png")
    return jsonify({
        "available": True,
        "image": f"data:{mime};base64," + base64.b64encode(png).decode(),
        "corners_m": [[round(x, 3), round(y, 3)] for x, y in quad],
        "bounds": info["bounds"],
        "source": info.get("source", "lidar-hillshade"),
        "licence": info.get("licence"),
        "attribution": info.get("attribution"),
        "resolution_m": info.get("resolution_m") or info.get("cell_m"),
        "method": info.get("method"),
        "asked": tried,
    })


@app.post("/api/project/<pid>/impression")
def project_impression(pid):
    """A photoreal impression of THIS building, from the massing render.

    The browser sends the canvas it is already showing, so the picture
    that comes back is the same building at the same camera — which is
    the only reason it can be trusted to be the same house at all.

    The FACTS come from the server, not from the body. The client may
    say which view it grabbed; it may not tell the server how big the
    house is, because that is measured and the whole point of the
    constraint in the prompt is that it is not up for negotiation.

    On failure this returns DATA NOT AVAILABLE with the reason, in the
    same shape as every other unavailable layer. It never returns a
    stand-in image.
    """
    from .providers import visual
    pj = _project(pid)
    bld = pj.current()
    body = request.get_json(silent=True) or {}

    data_url = body.get("massing_png") or ""
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        png = base64.b64decode(data_url, validate=True)
    except Exception:
        png = b""
    if not png:
        return _out({"available": False, "status": "DATA NOT AVAILABLE",
                     "reason": "the massing render did not arrive — the "
                               "impression is drawn FROM the model, not "
                               "from the address",
                     "asked": []})
    # 12 MB of PNG is already far more than a canvas grab; past that it
    # is either a mistake or somebody using the endpoint as an upload.
    if len(png) > 12 * 1024 * 1024:
        return _out({"available": False, "status": "REFUSED",
                     "reason": "that render is too large to send"})

    big = max(bld.blocks, key=lambda b: b.area()) if bld.blocks else None
    roof = (big.roof or {}) if big else {}
    facts = {
        "width_m": big.width if big else None,
        "depth_m": big.depth if big else None,
        "storeys": big.storeys if big else None,
        "eaves_m": bld.eaves_m(),
        "ridge_m": bld.ridge_m(),
        "roof_kind": roof.get("kind"),
        "address": bld.address or "",
        "place": _place_from(bld.address or ""),
    }
    try:
        imp = visual.impression(png, facts)
    except visual.NotAvailable as e:
        return _out({"available": False, "status": "DATA NOT AVAILABLE",
                     "reason": str(e), "asked": list(visual.MODELS),
                     "note": "The impression is a selling picture, not a "
                             "survey. Nothing downstream depends on it, "
                             "so the rest of the model is unaffected."})
    return jsonify({
        "available": True,
        "image": "data:image/png;base64," + base64.b64encode(imp.png).decode(),
        "model": imp.model,
        "classification": imp.classification,
        "licence": imp.licence,
        "attribution": imp.attribution,
        "caption": imp.caption,
        "asked": list(imp.notes),
    })


def _place_from(address: str) -> str:
    """The town out of a Nominatim label, for the prompt's sense of place.

    Nominatim puts the country last and the house number first; the
    middle is the useful part. Guessing wrong only costs a slightly
    generic picture, so this stays cheap and never raises.
    """
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) >= 4:
        return ", ".join(parts[-4:-1])
    return ", ".join(parts[1:]) or "England"


@app.get("/api/rates")
def rates():
    """The rate card, its regions, VAT bases and what they mean."""
    import sys as _sys
    import os as _os
    b = _os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))), "building")
    if b not in _sys.path:
        _sys.path.insert(0, b)
    import estimate as E
    return jsonify({
        "available": True,
        "basis": E.RATE_BASIS, "date": E.RATE_CARD_DATE,
        "regions": {k: {"factor": v[0], "name": v[1]}
                    for k, v in E.REGIONS.items()},
        "vat": {k: {"rate": v[0], "note": v[1]}
                for k, v in E.VAT_RATES.items()},
        "estimate_classes": {k: {"low": v[0], "high": v[1], "note": v[2]}
                             for k, v in E.CLASSES.items()},
        "typical_gross_per_m2": list(E.TYPICAL_GROSS_PER_M2),
        "packages": {k: v[1] for k, v in E.PACKAGES.items()},
    })


@app.get("/api/project/<pid>/baseline")
def project_baseline(pid):
    """The building AS FOUND — the left-hand side of before/after."""
    from . import design as design_mod
    base = _project(pid).baseline()
    return jsonify({"available": True, "building": base.as_dict(),
                    "massing": design_mod.massing(base),
                    "plan": design_mod.floor_plan(base)})


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
