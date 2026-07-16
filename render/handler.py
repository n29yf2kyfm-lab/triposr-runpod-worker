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
                           "dbg": {"alpha": alpha, "tw": tw, "emiss": emiss}}
                d = meta[n]
            d["area"] += p.area * ((cof @ p.normal).length if cof else 1.0)
    return meta


def _choose_body(meta):
    """Body-paint material names: paint-named candidates plus the largest opaque
    non-excluded material(s), so multi-panel bodies and generic-named ('Material_134',
    'Misc') bodies both get repainted while glass/lights/wheels/interior are spared."""
    cands = {n: d for n, d in meta.items() if not d["excl"]}
    if not cands:
        return set()
    big = max(d["area"] for d in cands.values())
    paint = set(n for n, d in cands.items() if d["paint"])
    # explicitly paint-named materials are authoritative: on models that ALSO
    # have a big generic-named material (trim atlas, underbody tray) the area
    # rule would flood colour onto the wrong parts (Golf 'Paint_Color' 17% vs
    # 'Index_0_1' 71%; A1 'bodyh'+'body1' vs 'under' 34%). Only fall back to
    # area when the paint-named materials are implausibly small (mirror-cap
    # sized) or absent.
    if paint and sum(cands[n]["area"] for n in paint) >= big * 0.15:
        return paint
    # No authoritative paint material: the body is spread across many generic or
    # colour-coded panel materials (e.g. Macan exports one 'wire_<rgb>' material
    # PER panel — bonnet, each door, roof...). The old 55%-of-biggest cutoff only
    # caught the two largest and left the doors unpainted (two-tone car). Instead
    # paint EVERY non-excluded, non-interior panel down to a small share of the
    # whole, so all body panels recolour together. Interior/glass/wheels/trim/
    # underbody are already excluded upstream.
    chosen = set(paint)
    total = sum(d["area"] for d in meta.values()) or 1.0
    for n, d in cands.items():
        if d["area"] >= 0.01 * total:
            chosen.add(n)
    return chosen


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


def _fetch_glb(job_input):
    """Materialise the GLB to a temp file from b64 / url / (base+path)."""
    path = os.path.join(tempfile.gettempdir(), "model.glb")
    if job_input.get("glb_b64"):
        with open(path, "wb") as f:
            f.write(base64.b64decode(job_input["glb_b64"]))
        return path
    url = job_input.get("glb_url")
    if not url and job_input.get("glb_path"):
        base = job_input.get("glb_base", "").rstrip("/")
        url = f"{base}/{job_input['glb_path'].lstrip('/')}"
    if not url:
        raise ValueError("provide glb_b64, glb_url, or glb_path(+glb_base)")
    headers = {}
    if job_input.get("glb_auth"):
        headers["Authorization"] = job_input["glb_auth"]
    r = requests.get(url, headers=headers, timeout=90)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    return path


def _pose_audit(bpy):
    """Hardened structure/orientation gate — the checks the paint QC never ran,
    so upside-down cars, wheels-off race shells, doors-open poses and wrecked
    floorpans get auto-rejected instead of reaching a human. Runs AFTER
    auto-upright, so a fail means upright could not save it. Scale-invariant:
    everything is a fraction of the model's own bounding box.

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

    reject, warn = [], []
    # HARD rejects — strong, unambiguous, no normal car trips these
    if wheel_af < 0.002:
        reject.append("wheels-missing")
    if glass_zf is not None and glass_zf < 0.42:
        reject.append(f"upside-down(glass_zf={glass_zf})")
    if wheel_zf is not None and wheel_zf > 0.55:
        reject.append(f"upside-down(wheel_zf={wheel_zf})")
    # WARN — flag for the human, do not auto-kill (vans/odd glass names live here)
    if glass_af < 0.006:
        warn.append(f"no-greenhouse(glass_af={glass_af})")
    if h_over_l > 0.55:
        warn.append(f"too-tall(h/l={h_over_l})")
    if glass_zf is not None and 0.42 <= glass_zf < 0.50:
        warn.append(f"glass-low(glass_zf={glass_zf})")
    verdict = "reject" if reject else ("warn" if warn else "ok")
    return {"verdict": verdict, "reject": reject, "warn": warn,
            "glass_zf": glass_zf, "wheel_zf": wheel_zf,
            "glass_af": glass_af, "wheel_af": wheel_af, "h_over_l": h_over_l}


def _render(bpy, glb, out, colour, plate_reg, az_deg, elev, zfrac,
            samples, resx, resy, bright=False, studio=True,
            finish=None, recolour_mode="auto", plate_end="auto",
            plates_both=False, audit=False):
    import mathutils
    import bmesh
    import re

    az = math.radians(az_deg)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)

    def meshes():
        return [o for o in bpy.context.scene.objects if o.type == "MESH"]

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

        if gd["glass"]:
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
                bc.default_value = (0.74, 0.80, 0.84, 1.0)   # faint cool tint
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

    # auto-upright: a correctly-oriented car has its SMALLEST bbox extent vertical
    # (height < width < length). Some GLBs are authored tipped (length/width along
    # world-up) and render lying on their side or standing on the nose. If the
    # vertical (Blender Z) extent isn't clearly the smallest, rotate the whole
    # scene 90deg so the smallest extent becomes vertical.
    ulo = [1e9] * 3
    uhi = [-1e9] * 3
    for o in meshes():
        for cnr in o.bound_box:
            wv = o.matrix_world @ mathutils.Vector(cnr)
            for i in range(3):
                ulo[i] = min(ulo[i], wv[i]); uhi[i] = max(uhi[i], wv[i])
    uext = [uhi[i] - ulo[i] for i in range(3)]
    min_axis = min(range(3), key=lambda i: uext[i])
    if min_axis != 2 and uext[min_axis] < 0.85 * uext[2]:
        import math as _math

        def _apply(Rm):
            for o in list(bpy.context.scene.objects):
                if o.parent is None:
                    o.matrix_world = Rm @ o.matrix_world
            bpy.context.view_layer.update()

        if min_axis == 0:      # X smallest -> rotate about Y so X becomes up
            _apply(mathutils.Matrix.Rotation(_math.radians(90), 4, 'Y'))
        else:                  # Y smallest -> rotate about X so Y becomes up
            _apply(mathutils.Matrix.Rotation(_math.radians(90), 4, 'X'))

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
    zmin_true = 1e9
    for o in meshes():
        mw = o.matrix_world
        for v in o.data.vertices:
            w = mw @ v.co
            axs[0].append(w[0]); axs[1].append(w[1]); axs[2].append(w[2])
            if w[2] < zmin_true:
                zmin_true = w[2]
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
        em.inputs["Strength"].default_value = 1.6
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
    # hardened pose/structure audit (post-upright geometry, pre-render is fine —
    # recolour/glass polish never move geometry). Only when asked, so the 8-colour
    # store renders skip the extra geometry pass.
    pose_info = _pose_audit(bpy) if audit else None
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
            glb = _fetch_glb(ji)
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
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc()}
    try:
        bpy = _load_bpy()
        glb = _fetch_glb(ji)
        out = os.path.join(tempfile.gettempdir(), "render.png")
        t0 = time.time()
        device, recolour_info, plate_end_used, pose_info = _render(
            bpy, glb, out,
            colour=ji.get("colour") or ji.get("color"),
            plate_reg=ji.get("plate"),
            az_deg=float(ji.get("az", 40)),
            elev=float(ji.get("elev", 0.15)),
            zfrac=float(ji.get("zfrac", 0.32)),
            samples=int(ji.get("samples", 160)),
            resx=int(ji.get("width", 1600)),
            resy=int(ji.get("height", 900)),
            bright=bool(ji.get("bright", False)),
            studio=bool(ji.get("studio", True)),
            finish=ji.get("finish"),
            recolour_mode=str(ji.get("recolour", "auto")).lower(),
            plate_end=str(ji.get("plate_end", "auto")).lower(),
            plates_both=bool(ji.get("plates_both", False)),
            audit=bool(ji.get("audit") or ji.get("debug_materials")),
        )
        dt = round(time.time() - t0, 1)
        with open(out, "rb") as f:
            png_b64 = base64.b64encode(f.read()).decode("utf-8")
        resp = {"status": "success", "png_b64": png_b64,
                "device": device, "seconds": dt,
                "recolour": recolour_info, "plate_end_used": plate_end_used}
        if pose_info is not None:
            resp["audit"] = pose_info
        return resp
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


runpod.serverless.start({"handler": handler})
