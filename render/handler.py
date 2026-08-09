"""RunPod serverless GPU render worker for Expert Car Check Pro.

Takes a car GLB + a DVLA colour + an optional UK plate and returns a cinematic
hero PNG (dark studio, three-point lighting, clearcoat gloss, reflective floor,
AgX). Renders on the GPU via Cycles (OPTIX/CUDA), scale-to-zero when idle.

Input (job["input"]):
  glb_b64 | glb_url | glb_path(+glb_base)  - the model (one is required)
  colour        - DVLA colour name to repaint the body material (optional)
  finish        - OEM paint FINISH (Solid|Metallic|Pearl|Mica|Multi-coat|
                  Tri-coat|Crystal|Matte, from platform/paint/oem_paint_db.csv);
                  optional — omitted keeps the legacy semi-metallic look
  recolour      - "auto" (default) | "flat" | "tint" | "off".
                  auto: paint-named body materials get a clean flat respray;
                  anything else (fused/generated shells, generic-named bodies)
                  gets a MULTIPLY tint so baked shading/detail survives —
                  flat repaint is never flooded onto a shell without a real
                  paint material (the quarantine-sweep rule, now in code).
  plate         - UK reg text, e.g. "LV24 TGN" (optional; drawn on front bumper)
  plate_end     - "auto" (default: end nearest the camera) | "hi" | "lo"
                  (explicit end on the length axis). Turntable sweeps must pass
                  the value reported as plate_end_used by frame 0, or the plate
                  jumps ends mid-sweep.
  az, elev      - camera azimuth (deg) / elevation fraction (default 40 / 0.15)
  zfrac         - plate height as a fraction of car height (default 0.32)
  samples       - Cycles samples (default 160)
  width, height - output resolution (default 1600x900)
  studio        - clean dark backdrop + bright reflections (default TRUE:
                  one consistent catalogue look; pass false for the legacy
                  colour-dependent backdrop)
  glass_tint    - window glass base colour: "r,g,b", [r,g,b] or a single float
                  for neutral grey. Default 0.18,0.20,0.22 (env GLASS_TINT).
                  The worker overrides the GLB's own glass material, so this is
                  the ONLY lever on how dark the windows read.
  fill_strength - emission strength of the invisible flank reflector cards.
                  Default 1.6 (env FILL_STRENGTH). Lowering it calms both the
                  highlight streak on the paint and the haze seen through glass.

Output: { "status": "success", "png_b64": "...", "device": "OPTIX|CUDA|CPU",
          "seconds": <float>, "recolour": {mode, paint_named, coverage,
          materials}, "plate_end_used": "hi|lo|null" }
"""
import os
import sys
import time
import math
import base64
import tempfile

import runpod
import requests
import ipaddress
import socket
import urllib.parse

HDRI = os.environ.get("HDRI_PATH", "/app/assets/hdri.hdr")
FONT = os.environ.get(
    "PLATE_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

_RGB = {
    "grey": (0.30, 0.31, 0.33), "gray": (0.30, 0.31, 0.33),
    "silver": (0.58, 0.59, 0.62), "black": (0.02, 0.02, 0.024),
    "white": (0.82, 0.83, 0.85), "blue": (0.03, 0.11, 0.45),
    "navy": (0.02, 0.05, 0.20), "red": (0.48, 0.02, 0.02),
    "green": (0.04, 0.24, 0.11), "orange": (0.72, 0.20, 0.02),
    "yellow": (0.80, 0.62, 0.02), "bronze": (0.28, 0.18, 0.06),
    "gold": (0.60, 0.45, 0.08), "beige": (0.62, 0.56, 0.42),
    "purple": (0.20, 0.04, 0.30), "maroon": (0.28, 0.03, 0.05),
    "pink": (0.75, 0.20, 0.42), "turquoise": (0.05, 0.42, 0.42),
    # premium/nuanced metallic shades
    "gunmetal": (0.14, 0.16, 0.18), "gunmetal grey": (0.14, 0.16, 0.18),
    "gunmetal-grey": (0.14, 0.16, 0.18), "gunmetal gray": (0.14, 0.16, 0.18),
    "dark silver": (0.34, 0.36, 0.39), "dark-silver": (0.34, 0.36, 0.39),
    "light silver": (0.70, 0.72, 0.76), "light-silver": (0.70, 0.72, 0.76),
    "dark green": (0.02, 0.13, 0.07), "dark-green": (0.02, 0.13, 0.07),
    # COLOUR_FAMILY values from platform/paint/oem_paint_db.csv — every family
    # in the OEM paint database must resolve to a paint here (hyphen/space
    # variants handled by _paint_rgb normalisation)
    "pearl white": (0.85, 0.85, 0.87), "cream white": (0.80, 0.77, 0.68),
    "dark blue": (0.02, 0.06, 0.24), "racing blue": (0.02, 0.16, 0.55),
    "light blue": (0.35, 0.55, 0.75), "bright blue": (0.05, 0.25, 0.75),
    "petrol blue": (0.02, 0.15, 0.20), "turquoise blue": (0.05, 0.42, 0.42),
    "blue black": (0.02, 0.03, 0.08),
    "dark grey": (0.16, 0.17, 0.19), "light grey": (0.55, 0.56, 0.58),
    "cement grey": (0.45, 0.46, 0.45), "graphite grey": (0.11, 0.12, 0.13),
    "dark gunmetal": (0.09, 0.10, 0.12),
    "dark red": (0.30, 0.02, 0.03), "bright red": (0.60, 0.03, 0.03),
    "burgundy": (0.24, 0.03, 0.07),
    "bright green": (0.10, 0.55, 0.15), "emerald green": (0.02, 0.30, 0.16),
    "olive green": (0.18, 0.20, 0.08), "khaki green": (0.25, 0.26, 0.14),
    "sand": (0.60, 0.52, 0.38), "taupe": (0.35, 0.30, 0.26),
}


def _paint_rgb(colour):
    """Palette lookup tolerant of slug form: 'Racing-Blue' == 'racing blue'."""
    if not colour:
        return None
    k = str(colour).strip().lower()
    return _RGB.get(k) or _RGB.get(k.replace("-", " "))


# FINISH column of platform/paint/oem_paint_db.csv -> shader params. Base
# roughness sits UNDER the clearcoat, so metallic paint keeps flake depth while
# the coat provides the gloss. Legacy (finish omitted) preserves the exact look
# shipped before finish awareness.
_FIN_LEGACY = dict(metal=0.6, rough=0.11, coat=1.0, coat_r=0.03)
_FIN_PEARL = dict(metal=0.40, rough=0.18, coat=1.0, coat_r=0.02)
_FINISH = {
    "solid": dict(metal=0.05, rough=0.32, coat=1.0, coat_r=0.03),
    "metallic": dict(metal=0.85, rough=0.30, coat=1.0, coat_r=0.03),
    "mica": dict(metal=0.85, rough=0.30, coat=1.0, coat_r=0.03),
    "pearl": _FIN_PEARL, "multi-coat": _FIN_PEARL, "tri-coat": _FIN_PEARL,
    "crystal": _FIN_PEARL,
    "matte": dict(metal=0.20, rough=0.48, coat=0.0, coat_r=0.10),
}


def _finish_params(finish):
    if not finish:
        return _FIN_LEGACY
    k = str(finish).strip().lower().replace("_", "-").replace(" ", "-")
    return _FINISH.get(k, _FIN_LEGACY)

_gpu_device = None  # cached across warm invocations

# Glass tint + flank-reflector brightness, tunable without a rebuild.
#
# These two numbers together decide how much white haze fills the windows. The
# worker OVERRIDES whatever glass material the GLB ships with, so the GLB has no
# say: it forces transmission 1.0 and stamps this base colour on. At the old
# hardcoded 0.74/0.80/0.84 the "tint" was near-white, so transmitted light came
# through almost unattenuated — and what it transmits is not the dark backdrop
# the camera sees but the flank reflector cards (emission, visible_camera=False)
# plus the HDRI, which non-camera rays see at strength 1.5. Near-white glass in
# front of a bright emitter reads as fog inside the cabin. Real automotive glass
# is a much darker tint; drop this and the windows read as glass again.
#
# Measured on the Tiguan R-Line at az90, sampling the greenhouse (19,181 px) and
# the red bodywork separately:
#
#   tint                 window mean   body mean   windows vs paint
#   0.74,0.80,0.84 (old)     119.1        68.3       1.74x BRIGHTER
#   0.30,0.33,0.36            75.5        68.2       1.11x
#   0.18,0.20,0.22 (now)      58.4        68.2       0.86x
#   0.10,0.11,0.13            46.6        61.9       0.75x
#
# Glass reading 74% brighter than the paint is what "white mist" was. 0.18 puts
# the windows just under the bodywork, which is how tinted automotive glass
# actually reads, and leaves the paint untouched (68.2 vs 68.3) so the approved
# highlight is unchanged. Dimming the reflector cards also fixes the haze but
# costs 9% of body brightness, so it is left at 1.6 and offered as a knob.
_GLASS_TINT_DEFAULT = (0.18, 0.20, 0.22)
_FILL_STRENGTH_DEFAULT = 1.6


def _f3(v, fallback):
    """Accept (r,g,b), [r,g,b], "r,g,b" or a single float meaning neutral grey."""
    if v is None:
        return fallback
    if isinstance(v, (int, float)):
        return (float(v),) * 3
    if isinstance(v, str):
        v = [p for p in v.replace(" ", "").split(",") if p]
    try:
        t = tuple(float(x) for x in v)
    except (TypeError, ValueError):
        return fallback
    if len(t) == 1:
        return (t[0],) * 3
    return t[:3] if len(t) >= 3 else fallback


def _glass_tint(override=None):
    return _f3(override if override is not None
               else os.environ.get("GLASS_TINT"), _GLASS_TINT_DEFAULT)


def _fill_strength(override=None):
    v = override if override is not None else os.environ.get("FILL_STRENGTH")
    try:
        return float(v)
    except (TypeError, ValueError):
        return _FILL_STRENGTH_DEFAULT


import re as _re
# Role classifiers for body detection. Names come from wildly inconsistent
# third-party GLBs (multilingual), so we combine name hints with material
# properties (blend mode / transmission / emission) inside Blender.
_GLASS = _re.compile(r"(glass|window|windscreen|windshield|screen|vidro|glas|scheibe|fenster)", _re.I)
_LIGHT = _re.compile(r"(light|lamp|head[\s_-]?l|tail[\s_-]?l|indicator|reflector|\bled\b|drl|blinker|\blens\b|faro|phare)", _re.I)
_TYRE = _re.compile(r"(tyre|tire|rubber|reifen|pneu|gomma|llanta)", _re.I)
_WHEEL = _re.compile(r"(wheel|\brim\b|alloy|\bhub\b|jante|felge|cerchi|caliper|\bbrake)", _re.I)
_TRIM = _re.compile(r"(chrome|trim|grill|grille|badge|logo|emblem|number[\s_-]?plate|plate[\s_-]|licen|mirror|molding|moulding|\bseal\b|wiper|antenna|handle)", _re.I)
_INNER = _re.compile(r"(interior|seat|dash|leather|fabric|carpet|steering|cabin|\binner\b|interno|innen|cockpit|door[\s_-]?card|belt|pedal|\bint(?:erior|plastic|carpet|leather|trim|panel|console|floor|cloth|roof)|headliner|sunvisor|armrest|gauge|speedo)", _re.I)
_DARKP = _re.compile(r"(lower[\s_-]?clad|cladding|\bunder\b|under[\s_-]?body|undercarriag|arch[\s_-]?liner|wheel[\s_-]?arch|sill[\s_-]?trim|mud[\s_-]?flap)", _re.I)
_PAINT = _re.compile(r"(car[\s_-]?paint|body[\s_-]?paint|\bbody\w*|\bpaint\w*|pintura|\black\b|lackier|karosser|carrosser|carrocer|verniz|vernice|\bcoat\b|exterior|\bshell\b|chassis|metal[\s_-]?car|paintwork|lacca)", _re.I)


def _norm_name(n):
    """Material names use underscores/digits as separators ('Paint_Color',
    'bodyh', 'body1'), which break \\b word boundaries — normalise before any
    role-regex match."""
    return _re.sub(r"[_\-.]+", " ", (n or "").lower())


def _classify_materials(bpy):
    """Per-material metadata as Blender sees it: summed face area + role flags.

    Areas are WORLD-space: p.area is local mesh space, and objects arrive with
    node scales (e.g. unit-cube parts scaled down) — summing local areas made a
    scaled-down interior box outweigh the whole car shell and skewed the
    body-choice area rule on every multi-object GLB. For a planar face under a
    linear map M, world_area = local_area * |cofactor(M) @ n_local|."""
    meta = {}
    for o in [x for x in bpy.context.scene.objects if x.type == "MESH"]:
        m3 = o.matrix_world.to_3x3()
        try:
            cof = m3.inverted().transposed() * m3.determinant()
        except ValueError:
            cof = None  # degenerate transform: fall back to local area
        for p in o.data.polygons:
            mi = p.material_index
            if mi >= len(o.material_slots):
                continue
            mm = o.material_slots[mi].material
            if not mm:
                continue
            n = mm.name
            nn = _norm_name(n)
            d = meta.get(n)
            if d is None:
                # Glass/light by name first, then only STRONG material signals
                # (blend_method is unreliable across Blender versions, so it's
                # not used). Default is opaque body-eligible.
                glass = bool(_GLASS.search(nn))
                emiss = False
                alpha = tw = None
                b = mm.node_tree.nodes.get("Principled BSDF") if (mm.use_nodes and mm.node_tree) else None
                if b:
                    try:
                        t = b.inputs.get("Transmission Weight") or b.inputs.get("Transmission")
                        if t is not None:
                            tw = float(t.default_value)
                            if tw > 0.5:
                                glass = True
                    except Exception:
                        pass
                    try:
                        a = b.inputs.get("Alpha")
                        if a is not None:
                            alpha = float(a.default_value)
                            # 0.9 matches the QC gate (asset_audit G2) and
                            # cabin_assembly's 0.72 tint — anything that
                            # renders see-through must never be repainted.
                            if alpha < 0.9:
                                glass = True
                    except Exception:
                        pass
                    try:
                        es = b.inputs.get("Emission Strength")
                        ec = b.inputs.get("Emission Color") or b.inputs.get("Emission")
                        if es and ec and float(es.default_value) > 0.01 and max(ec.default_value[:3]) > 0.05:
                            emiss = True
                    except Exception:
                        pass
                light = emiss or bool(_LIGHT.search(nn))
                excl = bool(glass or light or _TYRE.search(nn) or _WHEEL.search(nn)
                            or _TRIM.search(nn) or _INNER.search(nn) or _DARKP.search(nn))
                meta[n] = {"area": 0.0, "glass": glass, "light": light,
                           "excl": excl, "paint": bool(_PAINT.search(nn)), "mat": mm,
                           "z0": 1e18, "z1": -1e18,  # world-space vertical span of this material
                           "dbg": {"alpha": alpha, "tw": tw, "emiss": emiss}}
                d = meta[n]
            d["area"] += p.area * ((cof @ p.normal).length if cof else 1.0)
            cz = (o.matrix_world @ p.center).z
            if cz < d["z0"]:
                d["z0"] = cz
            if cz > d["z1"]:
                d["z1"] = cz
    return meta


def _choose_body(meta):
    """Body-paint material names: paint-named candidates plus the largest opaque
    non-excluded material(s), so multi-panel bodies and generic-named ('Material_134',
    'Misc') bodies both get repainted while glass/lights/wheels/interior are spared."""
    cands = {n: d for n, d in meta.items() if not d["excl"]}
    if not cands:
        return set()
    # Geometric wheel/low-part guard. Scraped GLBs often name wheels generically
    # ('Material_25') so the name rules miss them, and flat paint then bleeds onto
    # the alloys. A wheel/tyre/underbody/low-trim material's HIGHEST point sits in
    # the bottom of the car; a real body panel (door, wing, bumper, roof) reaches
    # up to the beltline/roof. Exclude any candidate whose top is under ~42% of the
    # car's height — this catches unnamed wheels without touching upright panels.
    zs = [d for d in meta.values() if d.get("z1", -1e18) > -1e17]
    car_z0 = min(d["z0"] for d in zs) if zs else 0.0
    car_z1 = max(d["z1"] for d in zs) if zs else 1.0
    car_h = (car_z1 - car_z0) or 1.0

    def low_part(d):
        # Wheels/tyres/underbody, spared from body paint even when generically
        # named. Two signatures: (a) the whole material sits low — its TOP is under
        # ~42% of car height (alloy centres, sills, undertray); (b) it TOUCHES THE
        # GROUND and stays low — a tyre reaches ~46% (above (a)) but its bottom is
        # the car's lowest point, unlike a bumper/valance whose lip clears the road.
        top = d.get("z1", -1e18) - car_z0
        bot = d.get("z0", 1e18) - car_z0
        return (top < 0.42 * car_h) or (bot < 0.05 * car_h and top < 0.52 * car_h)

    big = max(d["area"] for d in cands.values())
    paint = set(n for n, d in cands.items() if d["paint"])
    # explicitly paint-named materials are authoritative: on models that ALSO
    # have a big generic-named material (trim atlas, underbody tray) the area
    # rule would flood colour onto the wrong parts (Golf 'Paint_Color' 17% vs
    # 'Index_0_1' 71%; A1 'bodyh'+'body1' vs 'under' 34%). Only fall back to
    # area when the paint-named materials are implausibly small (mirror-cap
    # sized) or absent.
    if paint and sum(cands[n]["area"] for n in paint) >= big * 0.15:
        return {n for n in paint if not low_part(cands[n])}
    # No authoritative paint material: the body is spread across many generic or
    # colour-coded panel materials (e.g. Macan exports one 'wire_<rgb>' material
    # PER panel — bonnet, each door, roof...). The old 55%-of-biggest cutoff only
    # caught the two largest and left the doors unpainted (two-tone car). Instead
    # paint EVERY non-excluded, non-interior panel down to a small share of the
    # whole, so all body panels recolour together. Interior/glass/wheels/trim/
    # underbody are already excluded upstream; low_part() drops unnamed wheels.
    chosen = set(paint)
    total = sum(d["area"] for d in meta.values()) or 1.0
    for n, d in cands.items():
        if d["area"] >= 0.01 * total and not low_part(d):
            chosen.add(n)
    return {n for n in chosen if not low_part(cands[n])}


def _load_bpy():
    import bpy  # imported lazily so import errors surface in the handler
    # The entire serving catalogue is draco-compressed. bpy wheels >=4.4 bundle
    # libextern_draco.so inside the glTF addon, but the addon's default lookup
    # expects a full Blender install layout and misses it — point the official
    # env override at the bundled lib so draco GLBs import.
    if not os.environ.get("BLENDER_EXTERN_DRACO_LIBRARY_PATH"):
        import glob as _glob
        try:
            scripts = bpy.utils.system_resource("SCRIPTS")
        except Exception:
            # scripts/modules/bpy/__init__.py -> up 2 = the scripts dir
            scripts = os.path.dirname(os.path.dirname(
                os.path.dirname(bpy.__file__)))
        hits = _glob.glob(os.path.join(scripts, "**", "libextern_draco*.so"),
                          recursive=True)
        if hits:
            os.environ["BLENDER_EXTERN_DRACO_LIBRARY_PATH"] = hits[0]
            print("draco decoder:", hits[0])
    return bpy


def _enable_gpu(bpy):
    """Turn on Cycles GPU (OPTIX preferred, then CUDA). Returns the type used."""
    global _gpu_device
    if _gpu_device is not None:
        return _gpu_device
    try:
        bpy.ops.preferences.addon_enable(module="cycles")
    except Exception:
        pass
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except Exception:
        _gpu_device = "CPU"
        return _gpu_device
    for dt in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = dt
            prefs.get_devices()
            on = False
            for d in prefs.devices:
                d.use = (d.type == dt)
                on = on or d.use
            if on:
                _gpu_device = dt
                return dt
        except Exception:
            continue
    _gpu_device = "CPU"
    return _gpu_device


def _make_plate(reg, rear=False):
    """Render a UK plate PNG (blue GB band, black chars). Front = white,
    rear = yellow. Returns path."""
    from PIL import Image, ImageDraw, ImageFont
    reg = reg.upper().strip()
    W, H = 1040, 220
    bg = (255, 205, 0) if rear else (250, 250, 248)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    band = 78
    d.rectangle([0, 0, band, H], fill=(0, 51, 153))
    try:
        fb = ImageFont.truetype(FONT, 44)
        fp = ImageFont.truetype(FONT, 150)
    except Exception:
        fb = fp = ImageFont.load_default()
    d.text((band / 2 - 14, H / 2 - 30), "UK", font=fb, fill=(255, 255, 255))
    tw = d.textlength(reg, font=fp)
    d.text(((W + band - tw) / 2, H / 2 - 92), reg, font=fp, fill=(15, 15, 15))
    d.rectangle([1, 1, W - 2, H - 2], outline=(120, 120, 120), width=2)
    path = os.path.join(tempfile.gettempdir(), "plate_rear.png" if rear else "plate.png")
    img.save(path)
    return path


# ---------------------------------------------------------------- input safety
# Added 2026-08-09 after an external review. The previous _fetch_glb would GET
# ANY url, forward a caller-supplied Authorization header, follow redirects to
# anywhere, and buffer the whole body with no size cap -- server-side request
# forgery plus trivial memory exhaustion. It also wrote fixed temp filenames,
# so two jobs in one container would clobber each other.

# Hosts this worker may fetch a GLB from. Override with RENDER_GLB_ALLOWLIST
# (comma-separated). Defaults to the project's own Supabase storage.
_DEFAULT_ALLOWLIST = "tfkvthprsntexrcuqpyd.supabase.co"
MAX_GLB_BYTES = int(os.environ.get("RENDER_MAX_GLB_BYTES", 256 * 1024 * 1024))
MAX_PNG_B64_BYTES = int(os.environ.get("RENDER_MAX_PNG_B64", 9 * 1024 * 1024))


def _allowed_hosts():
    raw = os.environ.get("RENDER_GLB_ALLOWLIST", _DEFAULT_ALLOWLIST)
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _assert_public_host(url):
    """https + allowlisted host + every resolved A/AAAA record is public.

    Resolving and checking EVERY address matters: a permitted hostname whose DNS
    points at 169.254.169.254 or 10.x would otherwise reach cloud metadata or
    internal services."""
    u = urllib.parse.urlparse(url)
    if u.scheme != "https":
        raise ValueError(f"glb_url must be https, got {u.scheme!r}")
    host = (u.hostname or "").lower()
    allow = _allowed_hosts()
    if host not in allow:
        raise ValueError(f"host {host!r} is not in the GLB allowlist")
    try:
        infos = socket.getaddrinfo(host, u.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {host!r}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            raise ValueError(f"host {host!r} resolves to non-public {ip}")
    return host


def _clamp(v, lo, hi, name):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric, got {v!r}")
    if n != n or n in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite, got {v!r}")
    return max(lo, min(hi, n))


def _fetch_glb(job_input, workdir=None):
    """Materialise the GLB to a temp file from b64 / url / (base+path).

    Streams with a hard byte cap, allowlists the host, refuses redirects that
    leave the allowlist, and validates the glTF magic before handing the file on.
    """
    workdir = workdir or tempfile.gettempdir()
    path = os.path.join(workdir, "model.glb")

    if job_input.get("glb_b64"):
        blob = base64.b64decode(job_input["glb_b64"])
        if len(blob) > MAX_GLB_BYTES:
            raise ValueError(f"glb_b64 is {len(blob)}B, over the "
                             f"{MAX_GLB_BYTES}B limit")
        if blob[:4] != b"glTF":
            raise ValueError("glb_b64 is not a binary glTF (bad magic)")
        with open(path, "wb") as f:
            f.write(blob)
        return path

    url = job_input.get("glb_url")
    if not url and job_input.get("glb_path"):
        base = job_input.get("glb_base", "").rstrip("/")
        url = f"{base}/{job_input['glb_path'].lstrip('/')}"
    if not url:
        raise ValueError("provide glb_b64, glb_url, or glb_path(+glb_base)")

    _assert_public_host(url)
    headers = {}
    if job_input.get("glb_auth"):
        # Only ever sent to an allowlisted host -- _assert_public_host has run.
        headers["Authorization"] = job_input["glb_auth"]

    # allow_redirects=False: a 30x to an unvetted host would bypass the checks.
    r = requests.get(url, headers=headers, timeout=90, stream=True,
                     allow_redirects=False)
    if r.is_redirect or r.is_permanent_redirect:
        nxt = r.headers.get("Location", "")
        _assert_public_host(urllib.parse.urljoin(url, nxt))
        r = requests.get(urllib.parse.urljoin(url, nxt), headers=headers,
                         timeout=90, stream=True, allow_redirects=False)
    r.raise_for_status()

    declared = int(r.headers.get("Content-Length") or 0)
    if declared and declared > MAX_GLB_BYTES:
        raise ValueError(f"GLB declares {declared}B, over the {MAX_GLB_BYTES}B limit")

    got = 0
    with open(path, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            got += len(chunk)
            if got > MAX_GLB_BYTES:
                raise ValueError(f"GLB exceeded the {MAX_GLB_BYTES}B limit mid-stream")
            f.write(chunk)
    if declared and got != declared:
        raise ValueError(f"GLB truncated: {got}B of {declared}B")
    with open(path, "rb") as f:
        if f.read(4) != b"glTF":
            raise ValueError("downloaded file is not a binary glTF (bad magic)")
    return path


def _pose_audit(bpy):
    """Structure/orientation METRICS the paint QC never measured — feeds the
    real gate in pipeline/ingest/geom_audit.py (which adds name-independent
    vertex geometry). Returns raw numbers only, no verdict: name-based glass/
    wheel detection is too unreliable on scraped GLBs to judge on alone. Runs
    AFTER auto-upright. Scale-invariant: everything is a fraction of the model's
    own bounding box.

    Signals (world space, Z is vertical after upright):
      glass_zf  area-weighted glass centroid height, 0=floor .. 1=roof
      wheel_zf  area-weighted wheel centroid height
      glass_af  glass share of total surface area (a real car has windows)
      wheel_af  wheel/tyre share (a sellable car has its wheels on)
      h_over_l  height / longest-horizontal (doors-up & on-side balloon this)
    """
    import mathutils
    glo = [1e9] * 3; ghi = [-1e9] * 3
    acc = {"glass": [0.0, 0.0], "wheel": [0.0, 0.0], "all": [0.0, 0.0]}  # [sum(area*z), sum(area)]
    for o in [x for x in bpy.context.scene.objects if x.type == "MESH"]:
        mw = o.matrix_world
        m3 = mw.to_3x3()
        try:
            cof = m3.inverted().transposed() * m3.determinant()
        except ValueError:
            cof = None
        for cnr in o.bound_box:
            wv = mw @ mathutils.Vector(cnr)
            for i in range(3):
                glo[i] = min(glo[i], wv[i]); ghi[i] = max(ghi[i], wv[i])
        for p in o.data.polygons:
            mi = p.material_index
            mm = o.material_slots[mi].material if mi < len(o.material_slots) else None
            nn = _norm_name(mm.name) if mm else ""
            a = p.area * ((cof @ p.normal).length if cof else 1.0)
            cz = (mw @ p.center).z
            acc["all"][0] += a * cz; acc["all"][1] += a
            if _GLASS.search(nn):
                acc["glass"][0] += a * cz; acc["glass"][1] += a
            if _WHEEL.search(nn) or _TYRE.search(nn):
                acc["wheel"][0] += a * cz; acc["wheel"][1] += a
    ext = [ghi[i] - glo[i] for i in range(3)]
    zmin = glo[2]; zspan = ext[2] or 1.0
    tot = acc["all"][1] or 1.0

    def zf(k):
        s = acc[k]
        return None if s[1] <= 0 else round((s[0] / s[1] - zmin) / zspan, 3)

    glass_zf = zf("glass"); wheel_zf = zf("wheel")
    glass_af = round(acc["glass"][1] / tot, 4); wheel_af = round(acc["wheel"][1] / tot, 4)
    length = max(ext[0], ext[1]) or 1.0
    h_over_l = round(ext[2] / length, 3)

    # Raw metrics only — deliberately NO verdict here. Name-based wheel/glass
    # detection is unreliable on scraped GLBs (most don't name those materials),
    # so a verdict computed from these alone false-rejects good cars. The real
    # gate is pipeline/ingest/geom_audit.py, which combines these glass metrics
    # with name-independent vertex geometry. Consumers must call that, not judge
    # off this dict.
    return {"glass_zf": glass_zf, "wheel_zf": wheel_zf,
            "glass_af": glass_af, "wheel_af": wheel_af, "h_over_l": h_over_l}


_RIG_MAX_FACES = 200     # a sphere/box rig; car parts are far denser
_RIG_ISOTROPY = 1.30     # max/min extent — a ball or box, not a car part
_RIG_MIN_SPAN = 0.35     # of car length: big enough to move the bbox

# Thresholds for stepping over a stray that sits below the wheels. Both must
# hold before a mesh is skipped, and the floor may never climb past _STRAY_MAX
# of the model's vertical spread, so a bad call can only sink a car slightly --
# never lift it back into the air, which is the failure being fixed.
_STRAY_GAP = 0.05        # of the zmin spread: a clear void under the car
_STRAY_MASS = 0.01       # of total faces: negligible geometry, never a wheel
_STRAY_MAX = 0.30        # of the zmin spread: hard ceiling on the correction


def _ground_z(meshes):
    """Height of the ground the car stands on.

    Takes the bottom of the CAR, not the bottom of the scene. Scraped GLBs
    routinely carry a stray -- a shadow plane, an aerial, a leftover locator --
    whose bounding box reaches below the tyres, and a blind minimum lays the
    studio floor under that instead, leaving the car hanging in mid-air.

    Walks the per-mesh bbox minima upward and steps over a mesh only when it
    sits alone in a gap beneath everything else AND holds under _STRAY_MASS of
    the faces. A wheel fails both tests: it carries real geometry, and it sits
    level with the other three, so there is no gap above it to step across.
    Where no such gap exists this returns the plain minimum, so models that
    were already correct are untouched.

    KNOWN LIMIT, measured -- this handles ONE stray, not a scatter. The Touran
    Mk1 (Sketchfab 539194f and 518767f) carries a spray of loose VW badge
    meshes at many different heights below the body. No single gap between
    consecutive minima clears _STRAY_GAP, so the walk stops at the first badge
    and the car still floats. Widening the thresholds to catch that would risk
    stepping over real wheels, and it would not help those files anyway: the
    badges are IN the model and render as debris on the floor at any floor
    height. Such assets are a sourcing problem, not a render problem, and the
    audit scraps them.
    """
    import mathutils as _mu
    ms = []
    for o in meshes():
        zs = [(o.matrix_world @ _mu.Vector(c))[2] for c in o.bound_box]
        ms.append((min(zs), len(o.data.polygons)))
    if not ms:
        return 0.0
    ms.sort(key=lambda t: t[0])
    spread = ms[-1][0] - ms[0][0]
    total = sum(f for _, f in ms)
    if spread <= 0 or total <= 0:
        return ms[0][0]

    floor, cum = ms[0][0], 0
    for i in range(len(ms) - 1):
        cum += ms[i][1]
        if (ms[i + 1][0] - ms[i][0]) > _STRAY_GAP * spread \
                and cum <= _STRAY_MASS * total \
                and (ms[i + 1][0] - ms[0][0]) <= _STRAY_MAX * spread:
            floor = ms[i + 1][0]
            continue
        break
    return floor


def _drop_rigs(bpy, mathutils, meshes):
    """Remove enclosing environment rigs before anything measures the scene.

    Sourced GLBs ship studio props baked in. The VW Sharan carries an
    `Icosphere`, 80 faces, 1.9 x 2.0 x 2.0, spanning Z -1.000..+1.000 while the
    car itself occupies Z 0.000..1.767. Nothing removed it at render time, so
    the scene bbox came out 2.767 tall instead of 1.767, and since the floor is
    built at the scene's zmin the studio floor was laid ONE METRE BENEATH THE
    WHEELS. Every hero rendered with the car hanging in mid-air.

    `strip_env.py` exists to catch exactly this, but it only runs in the
    sourcing wave, and it uploads its cleaned copy only when its self-check
    passes -- the Sharan's returned ok=False, so no clean GLB was ever stored
    and the render worker got the raw file. Serving cannot depend on an offline
    step having succeeded, so the guard belongs here too.

    A rig is low-poly AND roughly isotropic AND large next to the car:

      faces <= 200          an 80-face icosphere or a 12-face cube
      max/min extent < 1.30 a ball or box, not a car part
      max extent >= 35%     of car length, so small props are left alone

    Thresholds set by measurement, not taste. The Sharan's Icosphere is 80
    faces, isotropy 1.05, span 42%. The nearest false positive found was the
    Touran's `EngineMesh_wiper.4_0` at 183 faces, isotropy 1.52, span 26% --
    a real car part that an earlier, looser cut (300 / 1.6 / 25%) deleted.
    Every threshold now sits between the two.

    All three must hold. Verified on the Sharan (drops the Icosphere, bbox
    2.767 -> 1.767, car sits on the floor) and against Golf 2000, Golf 2021,
    Passat 2001, Touran 2004, Touran 2010 and Tiguan 2021, which lose nothing.

    An earlier attempt at this used a body-envelope test built on measurements
    from a helper that disagreed with Blender; it would have deleted the four
    real wheels. Everything here is measured through Blender itself.
    """
    ms = meshes()
    if len(ms) < 3:
        return []

    def world_box(o):
        lo = [1e30] * 3
        hi = [-1e30] * 3
        for cnr in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(cnr)
            for i in range(3):
                lo[i] = min(lo[i], w[i]); hi[i] = max(hi[i], w[i])
        return lo, hi, [hi[i] - lo[i] for i in range(3)]

    boxes = {o.name: world_box(o) for o in ms}
    car_len = max(max(boxes[o.name][2]) for o in ms)

    drop = []
    for o in ms:
        ext = sorted(boxes[o.name][2], reverse=True)
        if ext[2] <= 1e-9:
            continue
        if (len(o.data.polygons) <= _RIG_MAX_FACES
                and ext[0] / ext[2] < _RIG_ISOTROPY
                and ext[0] >= _RIG_MIN_SPAN * car_len):
            drop.append(o)

    # Refuse to gut the car: if this ever selects a large share of the scene the
    # test is wrong, and rendering the raw model beats rendering a hollow one.
    if not drop or len(drop) > 0.25 * len(ms):
        return []

    names = [o.name for o in drop]
    # bpy.ops.object.delete() silently did nothing here -- the operator depends
    # on a context this worker does not have, and the scene bbox came back
    # unchanged with the rig still in it. Remove from bpy.data directly, then
    # confirm the objects are actually gone before reporting success.
    for o in drop:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    left = {o.name for o in meshes()}
    return [n for n in names if n not in left]


def _render(bpy, glb, out, colour, plate_reg, az_deg, elev, zfrac,
            samples, resx, resy, bright=False, studio=True,
            finish=None, recolour_mode="auto", plate_end="auto",
            plates_both=False, audit=False,
            glass_tint=None, fill_strength=None):
    import mathutils
    import bmesh
    import re

    az = math.radians(az_deg)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)

    def meshes():
        return [o for o in bpy.context.scene.objects if o.type == "MESH"]

    _dropped_rigs = _drop_rigs(bpy, mathutils, meshes)

    ms = meshes()
    bpy.ops.object.select_all(action="DESELECT")
    for o in ms:
        o.select_set(True)
    bpy.context.view_layer.objects.active = ms[0]
    try:
        bpy.ops.object.shade_auto_smooth(angle=math.radians(40))
    except Exception:
        pass

    # premium clearcoat (+ optional recolour) on the DETECTED body materials.
    # Detection is by role flags + area in Blender (not just material name).
    # Recolour has two methods and the choice is now a machine rule:
    #   flat — unlink Base Color inputs, set the colour (clean OEM respray;
    #          destroys baked detail, so ONLY safe on paint-named materials)
    #   tint — MULTIPLY the existing Base Color chain by the colour, so baked
    #          shading, shutlines and trim survive (the method that shipped the
    #          Golf colour variants). Used whenever the body is not paint-named
    #          — fused/generated shells, generic atlases — which also encodes
    #          the "never flood-paint a fused shell" quarantine rule.
    meta = _classify_materials(bpy)
    chosen = _choose_body(meta)
    _rgb = _paint_rgb(colour)
    fin = _finish_params(finish)
    paint_named = any(meta[n]["paint"] for n in chosen)
    tot_area = sum(d["area"] for d in meta.values()) or 1.0
    mode = recolour_mode if recolour_mode in ("flat", "tint", "off") \
        else ("flat" if paint_named else "tint")
    recolour_info = {
        "mode": mode if (_rgb is not None and mode != "off") else "none",
        "paint_named": paint_named,
        "coverage": round(sum(meta[n]["area"] for n in chosen) / tot_area, 3),
        "materials": sorted(chosen)}
    for bn in chosen:
        m = meta[bn]["mat"]
        if not m or not m.use_nodes or not m.node_tree:
            continue
        b = m.node_tree.nodes.get("Principled BSDF")
        if not b:
            continue
        if _rgb is not None and mode != "off":
            links = list(b.inputs["Base Color"].links)
            if mode == "flat" or not links:
                for lnk in links:
                    m.node_tree.links.remove(lnk)
                b.inputs["Base Color"].default_value = (*_rgb, 1)
            else:
                src = links[0].from_socket
                m.node_tree.links.remove(links[0])
                mix = m.node_tree.nodes.new("ShaderNodeMix")
                mix.data_type = "RGBA"
                mix.blend_type = "MULTIPLY"
                mix.inputs["Factor"].default_value = 1.0
                m.node_tree.links.new(src, mix.inputs[6])
                # 1.25 lift compensates multiply darkening on mid-tone bakes
                # (same constant the offline tint pipeline shipped with)
                mix.inputs[7].default_value = \
                    (*[min(1.0, cc * 1.25) for cc in _rgb], 1.0)
                # multiply CRUSHES dark targets (petrol blue on the Tiguan
                # rendered black, hue gone): restore hue by blending a
                # fraction of the flat target on top, scaled by target
                # darkness — dark paints get up to ~45% flat colour, light
                # paints keep nearly all baked detail. A texture-luma mask
                # was tried and rejected: on palette models whose SOURCE car
                # was dark, body texels are as dark as trim texels, so the
                # mask kills the restore exactly where it's needed. Uniform
                # restore slightly tints dark trim — acceptable; wrong paint
                # colour is not.
                luma = 0.2126 * _rgb[0] + 0.7152 * _rgb[1] + 0.0722 * _rgb[2]
                restore = max(0.12, min(0.45, 0.12 + (0.35 - luma)))
                fix = m.node_tree.nodes.new("ShaderNodeMix")
                fix.data_type = "RGBA"
                fix.blend_type = "MIX"
                fix.inputs["Factor"].default_value = restore
                m.node_tree.links.new(mix.outputs[2], fix.inputs[6])
                fix.inputs[7].default_value = (*_rgb, 1.0)
                m.node_tree.links.new(fix.outputs[2], b.inputs["Base Color"])

        def _force(name, val):
            # setting default_value on a LINKED input is silently ignored —
            # generated assets drive Metallic/Roughness from a baked
            # metallicRoughness texture (implicit factor 1.0 = chrome car),
            # so the link must be cut before the value can land.
            inp = b.inputs.get(name)
            if inp is None:
                return
            for lnk in list(inp.links):
                m.node_tree.links.remove(lnk)
            inp.default_value = val
        if mode == "flat":
            _force("Metallic", fin["metal"])
            _force("Roughness", fin["rough"])
        elif mode == "tint" and _rgb is not None:
            # tinted (generated/fused) bodies render as DIELECTRIC paint:
            # the baked metallicRoughness atlas is photo noise, not paint
            # data — it's what made the Alam Golf liquid-silver. Colour
            # detail still comes from the multiplied base texture; gloss
            # comes from the clearcoat.
            _force("Metallic", 0.15)
            _force("Roughness", 0.30)
        if "Coat Weight" in b.inputs:
            b.inputs["Coat Weight"].default_value = fin["coat"]
            b.inputs["Coat Roughness"].default_value = fin["coat_r"]

    # --- glass + light polish -------------------------------------------------
    # Raw sourced GLBs ship glass as dark/opaque slabs and light lenses as dull,
    # un-emissive plastic, so windscreens render BLACK and headlights render as
    # grey blobs. This polish used to live only in the offline finish step, so
    # GPU/live renders never got it. Apply it to every render: glass -> real
    # transmissive clear glass (Cycles refraction shows the interior); light
    # lenses -> glossy clearcoat + modest emission so coloured lenses read vivid.
    _gtot = sum(d["area"] for d in meta.values()) or 1.0
    for gn, gd in meta.items():
        gm = gd["mat"]
        if not gm or not gm.use_nodes or not gm.node_tree or gn in chosen:
            continue
        gb = gm.node_tree.nodes.get("Principled BSDF")
        if not gb:
            continue

        def _gcut(name):
            inp = gb.inputs.get(name)
            if inp is not None:
                for lnk in list(inp.links):
                    gm.node_tree.links.remove(lnk)
            return inp

        # A car has TWO kinds of glass and they must not share a branch. Window
        # glass is near-colourless and transmissive; a lamp lens is coloured and
        # must stay saturated. _GLASS matched first, so any material named like
        # BOTH - 'HeadLightsGlass', 'BrakeLightsGlass', 'Tailights_Glass',
        # 'wrxM_LightGlassNormal_Clear' - was being made fully transmissive and
        # stamped with the window tint, i.e. rendered as a grey window where the
        # car has a red tail light. 53 such materials across 38 catalogue cars.
        # Requiring "glass AND NOT light" sends them to the lamp branch below,
        # which is what they always should have hit.
        if gd["glass"] and not gd["light"]:
            # Safety net: a single 'glass' material covering an implausibly large
            # share of the car is almost certainly mislabeled bodywork (the Golf's
            # finished GLB had roof_glass 27% + privacy_glass 24%). Full trans-
            # mission on that renders a see-through glass shell, so keep oversized
            # 'glass' opaque and lightly tinted instead of fully clear.
            oversized = gd["area"] > 0.22 * _gtot
            trans = 0.0 if oversized else 1.0
            for nm, val in (("Transmission Weight", trans), ("Transmission", trans),
                            ("Roughness", 0.10 if oversized else 0.03), ("Metallic", 0.0),
                            ("Alpha", 1.0), ("IOR", 1.45)):
                inp = _gcut(nm)
                if inp is not None:
                    inp.default_value = val
            bc = _gcut("Base Color")
            if bc is not None:
                bc.default_value = tuple(_glass_tint(glass_tint)) + (1.0,)
            try:
                gm.use_screen_refraction = True
                gm.blend_method = "OPAQUE"
            except Exception:
                pass
        elif gd["light"]:
            # crisp glossy CLEAR lens (glass-like), NOT an emissive glow —
            # emission washed chrome-ringed lamps (classic Fiat 500) to a milky
            # foggy haze. Gloss + light transmission + clearcoat reads as a real
            # lamp cover; coloured lenses (red tails) stay deep and glossy.
            for nm, val in (("Roughness", 0.04), ("Metallic", 0.0),
                            ("Transmission Weight", 0.35), ("Transmission", 0.35),
                            ("IOR", 1.45)):
                inp = _gcut(nm)
                if inp is not None:
                    inp.default_value = val
            if "Coat Weight" in gb.inputs:
                gb.inputs["Coat Weight"].default_value = 0.7
                gb.inputs["Coat Roughness"].default_value = 0.03
            # kill any residual emissive glow that reads as fog
            es = gb.inputs.get("Emission Strength")
            if es is not None:
                for lnk in list(es.links):
                    gm.node_tree.links.remove(lnk)
                es.default_value = 0.0
        else:
            # Untextured 'clay' trim. On fully-generic models (every material named
            # Material_xx, no textures) the lights/grille/mirrors — and the wheels
            # the geometric guard spared from body paint — render as matte WHITE fog
            # and read unfinished. If a non-body material has no base-colour texture
            # and reads bright + neutral (white/grey clay), retreat it as glossy dark
            # trim: smoked lens / gloss-black grille / dark alloy — a cohesive premium
            # accent. Textured parts and saturated colours (red tail-lenses) are left
            # untouched so nothing real is destroyed.
            bc = gb.inputs.get("Base Color")
            if bc is not None and not bc.links:
                v = bc.default_value
                bright = min(v[0], v[1], v[2]) > 0.45
                neutral = (max(v[0], v[1], v[2]) - min(v[0], v[1], v[2])) < 0.12
                if bright and neutral:
                    bc.default_value = (0.035, 0.035, 0.038, 1.0)
                    for nm, val in (("Metallic", 0.0), ("Roughness", 0.22)):
                        inp = gb.inputs.get(nm)
                        if inp is not None and not inp.links:
                            inp.default_value = val
                    if "Coat Weight" in gb.inputs:
                        gb.inputs["Coat Weight"].default_value = 0.6
                        gb.inputs["Coat Roughness"].default_value = 0.06

    # auto-upright, conservative: only rescue the UNAMBIGUOUS wreck — the
    # vertical extent is clearly the LARGEST, i.e. the car stands on its
    # nose/tail with its length pointing up. The old rule ("smallest extent
    # must be vertical") mis-rotated vehicles whose height rightly exceeds
    # their width — Sprinter-class vans, and cars whose roof aerial inflates
    # the height — and ingest now uprights staged GLBs, so an already-
    # horizontal model is trusted as authored.
    ulo = [1e9] * 3
    uhi = [-1e9] * 3
    for o in meshes():
        for cnr in o.bound_box:
            wv = o.matrix_world @ mathutils.Vector(cnr)
            for i in range(3):
                ulo[i] = min(ulo[i], wv[i]); uhi[i] = max(uhi[i], wv[i])
    uext = [uhi[i] - ulo[i] for i in range(3)]
    if uext[2] > 1.25 * max(uext[0], uext[1]):
        import math as _math

        def _apply(Rm):
            for o in list(bpy.context.scene.objects):
                if o.parent is None:
                    o.matrix_world = Rm @ o.matrix_world
            bpy.context.view_layer.update()

        # lay the length down (Z -> Y), then if the car landed on its side
        # (height ended up horizontal on X) roll it upright
        _apply(mathutils.Matrix.Rotation(_math.radians(90), 4, 'X'))
        lo2 = [1e9] * 3
        hi2 = [-1e9] * 3
        for o in meshes():
            for cnr in o.bound_box:
                wv = o.matrix_world @ mathutils.Vector(cnr)
                for i in range(3):
                    lo2[i] = min(lo2[i], wv[i]); hi2[i] = max(hi2[i], wv[i])
        ext2 = [hi2[i] - lo2[i] for i in range(3)]
        if min(range(3), key=lambda i: ext2[i]) != 2:
            _apply(mathutils.Matrix.Rotation(_math.radians(90), 4, 'Y'))
        uext = ext2  # keep the 180-flip's length-axis pick consistent

        # 180deg ambiguity: a car is WIDER at the bottom (body/wheels) than the
        # top (cabin). Sample the widest horizontal span in the top third vs the
        # bottom third; if the top is wider the car is upside down -> flip 180.
        zs = []
        pts = []
        for o in meshes():
            m = o.matrix_world
            for v in o.data.vertices:
                w = m @ v.co
                pts.append((w.x, w.y, w.z)); zs.append(w.z)
            if len(pts) > 40000:
                break
        if zs:
            zlo, zhi = min(zs), max(zs); span = (zhi - zlo) or 1.0
            def _wid(frac_lo, frac_hi):
                sel = [(x, y) for (x, y, z) in pts
                       if zlo + frac_lo * span <= z <= zlo + frac_hi * span]
                if not sel:
                    return 0.0
                xs = [p[0] for p in sel]; ys = [p[1] for p in sel]
                return max(max(xs) - min(xs), max(ys) - min(ys))
            if _wid(0.66, 1.0) > 1.15 * _wid(0.0, 0.34):
                # centre on length axis, flip about it
                cax = 0 if uext[0] >= uext[1] else 1  # longest horizontal = length
                axis = 'X' if cax == 0 else 'Y'
                _apply(mathutils.Matrix.Rotation(_math.radians(180), 4, axis))

    # normalize scale: GLBs arrive at wildly different scales (some cars are
    # ~0.05 units); scale the scene so the car is ~4.5 units so camera/DOF/light
    # math all operate in a sane range.
    rlo = [1e9] * 3
    rhi = [-1e9] * 3
    for o in meshes():
        for cnr in o.bound_box:
            wv = o.matrix_world @ mathutils.Vector(cnr)
            for i in range(3):
                rlo[i] = min(rlo[i], wv[i])
                rhi[i] = max(rhi[i], wv[i])
    rsize = max(rhi[i] - rlo[i] for i in range(3))
    if rsize > 1e-6 and not (2.0 < rsize < 8.0):
        f = 4.5 / rsize
        for o in list(bpy.context.scene.objects):
            if o.parent is None:
                o.scale = [s * f for s in o.scale]
                o.location = [l * f for l in o.location]
        bpy.context.view_layer.update()

    # robust bounds via vertex percentiles (stray verts can't blow up framing)
    axs = [[], [], []]
    for o in meshes():
        mw = o.matrix_world
        for v in o.data.vertices:
            w = mw @ v.co
            axs[0].append(w[0]); axs[1].append(w[1]); axs[2].append(w[2])

    # Ground height comes from the object bounding boxes, NOT from raw
    # o.data.vertices.
    #
    # The two disagree. Measured on the VW Sharan at the moment the floor is
    # built: bound_box puts the car at Z 0.000..1.767 (correct -- 1.767 m is a
    # Sharan's height, and this number tracked the Icosphere rig removal
    # exactly, 2.767 -> 1.767). The vertex scan returns -2.170. `o.data.vertices`
    # is the raw stored mesh, unevaluated: it does not reflect the depsgraph
    # state Blender actually renders, so for rigged/parented meshes -- this
    # model's wheels are `wheel_lf.child.001/.002/.003` -- it reports positions
    # the renderer never uses.
    #
    # The floor is laid at this value, so a -2.170 reading put the studio floor
    # 2.17 units BENEATH the wheels and every hero rendered with the car hanging
    # in mid-air. Four earlier diagnoses of that symptom (strip_env damage, a
    # stray mesh below, spare wheels above, the Icosphere) were all wrong; this
    # is the measured cause.
    #
    # A blind minimum over every mesh is still wrong, and that was measured too.
    # The 2017 Golf (Sketchfab 0fcad851) carries `Object_177`, a 1,008-face
    # stray spanning the whole scene vertically: the body sits at -28.352 and
    # that one object reaches -40.236, so the floor went 11.9 units under the
    # tyres and the car floated exactly as before. So take the bottom of the
    # CAR, not the bottom of the scene: walk the per-mesh bbox minima upward and
    # step over anything that sits alone in a gap below everything else while
    # holding a negligible share of the faces. A wheel never qualifies -- it
    # carries real geometry and sits level with the other wheels. Nothing is
    # deleted here, only excluded from the floor height, so the worst case of a
    # misjudgement is a car sunk slightly into the floor rather than one
    # missing its wheels.
    zmin_true = _ground_z(meshes)
    for a in axs:
        a.sort()

    def _pct(a, p):
        return a[min(len(a) - 1, max(0, int(p * (len(a) - 1))))]
    lo = [_pct(axs[i], 0.01) for i in range(3)]
    hi = [_pct(axs[i], 0.99) for i in range(3)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    size = max(hi[i] - lo[i] for i in range(3))
    zmin = zmin_true
    height = hi[2] - lo[2]

    # camera
    cam_d = bpy.data.cameras.new("C")
    cam_d.lens = float(os.environ.get("LENS", "62"))
    cam = bpy.data.objects.new("C", cam_d)
    bpy.context.collection.objects.link(cam)
    dist = size * float(os.environ.get("DIST", "2.1"))
    fx, fy = math.sin(az), -math.cos(az)
    loc = (c[0] + dist * fx, c[1] + dist * fy, c[2] + size * elev)
    cam.location = loc
    cam.rotation_euler = (mathutils.Vector(c) - mathutils.Vector(loc)) \
        .to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    cam_d.dof.use_dof = True
    cam_d.dof.focus_distance = (mathutils.Vector(loc) - mathutils.Vector(c)).length
    cam_d.dof.aperture_fstop = 11.0

    # world: HDRI lights the car, camera sees a dark graded backdrop
    w = bpy.data.worlds.new("W")
    bpy.context.scene.world = w
    w.use_nodes = True
    wn = w.node_tree
    for n in list(wn.nodes):
        wn.nodes.remove(n)
    outw = wn.nodes.new("ShaderNodeOutputWorld")
    mix = wn.nodes.new("ShaderNodeMixShader")
    lp = wn.nodes.new("ShaderNodeLightPath")
    env = wn.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(os.path.abspath(HDRI))
    tc = wn.nodes.new("ShaderNodeTexCoord")
    mp = wn.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value[2] = math.radians(110)
    wn.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    wn.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    bg_light = wn.nodes.new("ShaderNodeBackground")
    wn.links.new(env.outputs["Color"], bg_light.inputs["Color"])
    bg_light.inputs["Strength"].default_value = 0.8
    grad = wn.nodes.new("ShaderNodeTexGradient")
    gtc = wn.nodes.new("ShaderNodeTexCoord")
    gmap = wn.nodes.new("ShaderNodeMapping")
    wn.links.new(gtc.outputs["Window"], gmap.inputs["Vector"])
    wn.links.new(gmap.outputs["Vector"], grad.inputs["Vector"])
    ramp = wn.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.006, 0.007, 0.010, 1)
    ramp.color_ramp.elements[1].color = (0.020, 0.022, 0.028, 1)
    wn.links.new(grad.outputs["Color"], ramp.inputs["Fac"])
    bg_dark = wn.nodes.new("ShaderNodeBackground")
    wn.links.new(ramp.outputs["Color"], bg_dark.inputs["Color"])
    _dark = {"black", "navy", "grey", "gray", "gunmetal", "maroon",
             "purple", "bronze"}
    # studio mode wins: keep the clean dark backdrop for the camera while a
    # bright HDRI still lights + reflects on the car, so even black reads
    # premium on a clean studio ground (no visible room).
    _ckey = (colour or "").lower().replace("-", " ")
    _is_dark = any(w in _dark for w in _ckey.split()) or _ckey.startswith("dark")
    use_bright = (bright or (colour and _is_dark)) and not studio
    if studio:
        # boost reflection/lighting so dark paint still pops against the clean
        # backdrop, but the camera only ever sees the dark graded ground.
        bg_light.inputs["Strength"].default_value = 1.5
        wn.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
        wn.links.new(bg_light.outputs["Background"], mix.inputs[1])
        wn.links.new(bg_dark.outputs["Background"], mix.inputs[2])
        wn.links.new(mix.outputs["Shader"], outw.inputs["Surface"])
    elif use_bright:
        # dark paint needs a bright environment to reflect, or it vanishes on a
        # dark backdrop. Show the HDRI studio everywhere.
        bg_light.inputs["Strength"].default_value = 1.5
        wn.links.new(bg_light.outputs["Background"], outw.inputs["Surface"])
    else:
        wn.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
        wn.links.new(bg_light.outputs["Background"], mix.inputs[1])
        wn.links.new(bg_dark.outputs["Background"], mix.inputs[2])
        wn.links.new(mix.outputs["Shader"], outw.inputs["Surface"])

    S = size
    S2 = size * size

    def area_light(name, x, y, z, power, sizem, color):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = power
        ld.size = sizem
        ld.color = color
        ob = bpy.data.objects.new(name, ld)
        bpy.context.collection.objects.link(ob)
        ob.location = (c[0] + x, c[1] + y, c[2] + z)
        dv = mathutils.Vector((c[0], c[1], c[2] + height * 0.2)) \
            - mathutils.Vector(ob.location)
        ob.rotation_euler = dv.to_track_quat("-Z", "Y").to_euler()

    area_light("key", -1.1 * S, -0.9 * S, 1.3 * S, 55 * S2, 0.9 * S, (1.0, 0.95, 0.88))
    area_light("rim", 1.0 * S, 1.2 * S, 1.0 * S, 42 * S2, 0.7 * S, (0.80, 0.89, 1.0))
    area_light("fill", 1.2 * S, -0.8 * S, 0.5 * S, 16 * S2, 1.1 * S, (0.95, 0.97, 1.0))
    area_light("wheelkick", -0.3 * S, -1.15 * S, 0.10 * S, 10 * S2, 0.45 * S, (0.92, 0.95, 1.0))

    # side fill cards: automotive-studio reflectors along both flanks,
    # invisible to camera. The tumblehome band under the windows reflects the
    # BACKDROP (not the lights) — with a dark studio that reads as a black
    # "gap" stripe across the doors on side views. A long soft bright card is
    # what real car studios use to put the premium highlight streak there.
    L_axis = 0 if (hi[0] - lo[0]) >= (hi[1] - lo[1]) else 1
    W_axis = 1 - L_axis
    car_len = hi[L_axis] - lo[L_axis]
    for sgn in (-1.0, 1.0):
        cm = bpy.data.meshes.new(f"fillcard{sgn}")
        bmc = bmesh.new()
        half_l = car_len * 0.75
        z_lo, z_hi = c[2], c[2] + height * 1.1
        for dl, dz in ((-half_l, z_lo), (half_l, z_lo),
                       (half_l, z_hi), (-half_l, z_hi)):
            p = [0.0, 0.0, dz]
            p[L_axis] = c[L_axis] + dl
            p[W_axis] = c[W_axis] + sgn * size * 1.05
            bmc.verts.new(p)
        bmc.faces.new(bmc.verts)
        bmc.to_mesh(cm)
        bmc.free()
        card = bpy.data.objects.new(f"fillcard{sgn}", cm)
        bpy.context.collection.objects.link(card)
        cmat = bpy.data.materials.new(f"fillcard{sgn}")
        cmat.use_nodes = True
        nt = cmat.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (1.0, 0.99, 0.97, 1)
        em.inputs["Strength"].default_value = _fill_strength(fill_strength)
        outn = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs["Emission"], outn.inputs["Surface"])
        cm.materials.append(cmat)
        card.visible_camera = False

    # glossy dark floor. Sized as a STAGE (2.5x car) not an infinite plane:
    # a huge sharp floor mirror-reflects the bright HDRI room at grazing
    # angles and smears it across the frame edges; a stage keeps the premium
    # under-car reflection while grazing rays fall off into the dark backdrop.
    # Slightly rougher so the room reads as a soft sheen, not a mirror image.
    fm = bpy.data.meshes.new("floor")
    bm = bmesh.new()
    s2 = size * 2.5
    for dx, dy in [(-s2, -s2), (s2, -s2), (s2, s2), (-s2, s2)]:
        bm.verts.new((c[0] + dx, c[1] + dy, zmin))
    bm.faces.new(bm.verts)
    bm.to_mesh(fm)
    bm.free()
    floor = bpy.data.objects.new("floor", fm)
    bpy.context.collection.objects.link(floor)
    fmat = bpy.data.materials.new("floor")
    fmat.use_nodes = True
    fb = fmat.node_tree.nodes.get("Principled BSDF")
    fb.inputs["Base Color"].default_value = (0.010, 0.010, 0.013, 1)
    fb.inputs["Roughness"].default_value = 0.12
    fm.materials.append(fmat)

    # optional plate. plate_end "hi"/"lo" pins the end on the length axis so
    # turntable sweeps don't re-decide per frame (the plate used to teleport
    # from nose to tail as the camera crossed the side); "auto" keeps the
    # camera-facing choice for single hero frames.
    plate_end_used = None
    if plate_reg:
        L = 0 if (hi[0] - lo[0]) >= (hi[1] - lo[1]) else 1
        Wd = 1 - L
        scale = (hi[L] - lo[L]) / 4.5
        pw = 0.52 * scale / 2
        ph = 0.11 * scale / 2
        Wc = c[Wd]
        Zc = zmin + zfrac * height

        def _place_plate(name, end, png):
            outward = 1.0 if end == hi[L] else -1.0
            Lc = end + outward * size * 0.006
            pm = bpy.data.meshes.new(name)
            bm = bmesh.new()

            def V(dw, dz):
                p = [0, 0, 0]
                p[L] = Lc
                p[Wd] = Wc + dw
                p[2] = Zc + dz
                return bm.verts.new(p)
            vs = [V(-pw, -ph), V(-pw, ph), V(pw, ph), V(pw, -ph)]
            f = bm.faces.new(vs)
            uvl = bm.loops.layers.uv.new("UVMap")
            uvs = [(1, 0), (1, 1), (0, 1), (0, 0)] if outward > 0 \
                else [(0, 0), (0, 1), (1, 1), (1, 0)]
            for lp2, uv in zip(f.loops, uvs):
                lp2[uvl].uv = uv
            bm.to_mesh(pm)
            bm.free()
            pobj = bpy.data.objects.new(name, pm)
            bpy.context.collection.objects.link(pobj)
            pmat = bpy.data.materials.new(name)
            pmat.use_nodes = True
            nt = pmat.node_tree
            pb = nt.nodes.get("Principled BSDF")
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = bpy.data.images.load(png)
            nt.links.new(tex.outputs["Color"], pb.inputs["Base Color"])
            pb.inputs["Roughness"].default_value = 0.3
            if "Emission Color" in pb.inputs:
                nt.links.new(tex.outputs["Color"], pb.inputs["Emission Color"])
                pb.inputs["Emission Strength"].default_value = 0.6
            pm.materials.append(pmat)

        if plates_both:
            # front = end the camera faces (hero shots frame the front); rear =
            # the opposite end. Front white, rear yellow.
            front_end = hi[L] if abs(loc[L] - hi[L]) < abs(loc[L] - lo[L]) else lo[L]
            rear_end = lo[L] if front_end == hi[L] else hi[L]
            _place_plate("plate_front", front_end, _make_plate(plate_reg, rear=False))
            _place_plate("plate_rear", rear_end, _make_plate(plate_reg, rear=True))
            plate_end_used = "both"
        else:
            if plate_end == "hi":
                end = hi[L]
            elif plate_end == "lo":
                end = lo[L]
            else:
                end = hi[L] if abs(loc[L] - hi[L]) < abs(loc[L] - lo[L]) else lo[L]
            plate_end_used = "hi" if end == hi[L] else "lo"
            _place_plate("plate", end, _make_plate(plate_reg, rear=False))

    # render
    device = _enable_gpu(bpy)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "GPU" if device in ("OPTIX", "CUDA") else "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.render.resolution_x = resx
    sc.render.resolution_y = resy
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - High Contrast", "AgX - Medium High Contrast",
                 "High Contrast", "None"):
        try:
            sc.view_settings.look = look
            break
        except Exception:
            continue
    sc.view_settings.exposure = -0.15
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = out
    # hardened pose/structure metrics (post-upright geometry, pre-render is fine —
    # recolour/glass polish never move geometry). Only when asked, so the 8-colour
    # store renders skip the extra geometry pass. Never let an audit error abort a
    # render — a malformed mesh should still produce a picture.
    pose_info = None
    if audit:
        try:
            pose_info = _pose_audit(bpy)
        except Exception as _e:
            pose_info = {"error": str(_e)[:120]}
    bpy.ops.render.render(write_still=True)
    return device, recolour_info, plate_end_used, pose_info


def _diag():
    """Import bpy, enumerate Cycles devices, and report — no rendering."""
    info = {"stage": "start"}
    try:
        bpy = _load_bpy()
        info["bpy"] = bpy.app.version_string
        info["stage"] = "bpy_imported"
        dev = _enable_gpu(bpy)
        info["device"] = dev
        info["stage"] = "gpu_enabled"
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            info["compute_device_type"] = prefs.compute_device_type
            info["devices"] = [
                {"name": d.name, "type": d.type, "use": bool(d.use)}
                for d in prefs.devices
            ]
        except Exception as e:
            info["devices_error"] = str(e)
    except Exception as e:
        import traceback
        info["error"] = str(e)
        info["traceback"] = traceback.format_exc()
    return {"status": "diag", **info}


def handler(job):
    ji = job.get("input", {})
    if ji.get("diag"):
        return _diag()
    if ji.get("mat_audit"):
        # Fast, render-free: import the GLB and report which materials the body
        # detector picks, so we can measure recolour coverage across the library.
        try:
            bpy = _load_bpy()
            glb = _fetch_glb(ji, tempfile.mkdtemp(prefix="matadt_"))
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath=glb)
            meta = _classify_materials(bpy)
            chosen = _choose_body(meta)
            tot = sum(d["area"] for d in meta.values()) or 1.0
            table = sorted(
                [{"name": n, "pct": round(100 * d["area"] / tot, 1),
                  "glass": d["glass"], "light": d["light"], "excl": d["excl"],
                  "paint": d["paint"], "body": n in chosen, "dbg": d.get("dbg")}
                 for n, d in meta.items()], key=lambda r: -r["pct"])[:20]
            return {"status": "success", "n_materials": len(meta),
                    "chosen_body": sorted(chosen),
                    "body_pct": round(sum(100 * meta[n]["area"] / tot for n in chosen), 1),
                    "materials": table}
        except Exception as e:
            resp = {"error": str(e)[:400], "error_type": type(e).__name__}
            if os.environ.get("RENDER_DEBUG_TRACEBACK"):
                import traceback
                resp["traceback"] = traceback.format_exc()
            return resp
    # Per-job scratch dir: the fixed names model.glb / render.png / plate.png
    # would collide the moment two jobs share a container. RunPod concurrency is
    # opt-in and this worker runs one at a time, but the isolation is cheap and
    # removes the landmine before someone enables it.
    workdir = tempfile.mkdtemp(prefix=f"job_{str(job.get('id','x'))[:24]}_")
    try:
        bpy = _load_bpy()
        glb = _fetch_glb(ji, workdir)
        out = os.path.join(workdir, "render.png")
        t0 = time.time()
        device, recolour_info, plate_end_used, pose_info = _render(
            bpy, glb, out,
            colour=ji.get("colour") or ji.get("color"),
            plate_reg=ji.get("plate"),
            az_deg=_clamp(ji.get("az", 40), -3600, 3600, "az"),
            elev=_clamp(ji.get("elev", 0.15), -1.0, 1.0, "elev"),
            zfrac=_clamp(ji.get("zfrac", 0.32), 0.01, 1.0, "zfrac"),
            # Bounded so a job cannot burn GPU-hours and then fail delivery on
            # RunPod's 10MB /run payload limit.
            samples=int(_clamp(ji.get("samples", 160), 1, 512, "samples")),
            resx=int(_clamp(ji.get("width", 1600), 64, 2560, "width")),
            resy=int(_clamp(ji.get("height", 900), 64, 2560, "height")),
            bright=bool(ji.get("bright", False)),
            studio=bool(ji.get("studio", True)),
            finish=ji.get("finish"),
            recolour_mode=str(ji.get("recolour", "auto")).lower(),
            plate_end=str(ji.get("plate_end", "auto")).lower(),
            plates_both=bool(ji.get("plates_both", False)),
            audit=bool(ji.get("audit") or ji.get("debug_materials")),
            glass_tint=ji.get("glass_tint"),
            fill_strength=ji.get("fill_strength"),
        )
        dt = round(time.time() - t0, 1)
        with open(out, "rb") as f:
            png_b64 = base64.b64encode(f.read()).decode("utf-8")
        # Fail loudly and cheaply rather than returning a payload RunPod will
        # reject at the transport layer (10MB /run, 20MB /runsync).
        if len(png_b64) > MAX_PNG_B64_BYTES:
            return {"error": "rendered PNG exceeds the response payload limit",
                    "error_type": "PayloadTooLarge",
                    "png_b64_bytes": len(png_b64),
                    "limit": MAX_PNG_B64_BYTES,
                    "hint": "lower width/height, or fetch via object storage"}
        resp = {"status": "success", "png_b64": png_b64,
                "device": device, "seconds": dt,
                "recolour": recolour_info, "plate_end_used": plate_end_used}
        if pose_info is not None:
            resp["audit"] = pose_info
        return resp
    except Exception as e:
        # Raw tracebacks leak absolute paths and internals to any caller. Keep
        # them behind RENDER_DEBUG_TRACEBACK for our own debugging only.
        resp = {"error": str(e)[:400], "error_type": type(e).__name__}
        if os.environ.get("RENDER_DEBUG_TRACEBACK"):
            import traceback
            resp["traceback"] = traceback.format_exc()
        return resp
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


runpod.serverless.start({"handler": handler})
