"""RunPod serverless GPU render worker for Expert Car Check Pro.

Takes a car GLB + a DVLA colour + an optional UK plate and returns a cinematic
hero PNG (dark studio, three-point lighting, clearcoat gloss, reflective floor,
AgX). Renders on the GPU via Cycles (OPTIX/CUDA), scale-to-zero when idle.

Input (job["input"]):
  glb_b64 | glb_url | glb_path(+glb_base)  - the model (one is required)
  colour        - DVLA colour name to repaint the body material (optional)
  plate         - UK reg text, e.g. "LV24 TGN" (optional; drawn on front bumper)
  az, elev      - camera azimuth (deg) / elevation fraction (default 40 / 0.15)
  zfrac         - plate height as a fraction of car height (default 0.32)
  samples       - Cycles samples (default 160)
  width, height - output resolution (default 1600x900)

Output: { "status": "success", "png_b64": "...", "device": "OPTIX|CUDA|CPU",
          "seconds": <float> }
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
}

_gpu_device = None  # cached across warm invocations

import re as _re
# Role classifiers for body detection. Names come from wildly inconsistent
# third-party GLBs (multilingual), so we combine name hints with material
# properties (blend mode / transmission / emission) inside Blender.
_GLASS = _re.compile(r"(glass|window|windscreen|windshield|screen|vidro|glas|scheibe|fenster)", _re.I)
_LIGHT = _re.compile(r"(light|lamp|head[\s_-]?l|tail[\s_-]?l|indicator|reflector|\bled\b|drl|blinker|\blens\b|faro|phare)", _re.I)
_TYRE = _re.compile(r"(tyre|tire|rubber|reifen|pneu|gomma|llanta)", _re.I)
_WHEEL = _re.compile(r"(wheel|\brim\b|alloy|\bhub\b|jante|felge|cerchi|caliper|\bbrake)", _re.I)
_TRIM = _re.compile(r"(chrome|trim|grill|grille|badge|logo|emblem|number[\s_-]?plate|licen|mirror|molding|moulding|\bseal\b|wiper|antenna|handle)", _re.I)
_INNER = _re.compile(r"(interior|seat|dash|leather|fabric|carpet|steering|cabin|\binner\b|interno|innen|cockpit|door[\s_-]?card|belt|pedal)", _re.I)
_DARKP = _re.compile(r"(lower[\s_-]?clad|cladding|under[\s_-]?body|arch[\s_-]?liner|wheel[\s_-]?arch|sill[\s_-]?trim|mud[\s_-]?flap)", _re.I)
_PAINT = _re.compile(r"(car[\s_-]?paint|body[\s_-]?paint|\bbody\b|\bpaint\b|pintura|\black\b|lackier|karosser|carrosser|carrocer|verniz|vernice|\bcoat\b|exterior|\bshell\b|chassis|metal[\s_-]?car|bodywork|paintwork|lacca)", _re.I)


def _classify_materials(bpy):
    """Per-material metadata as Blender sees it: summed face area + role flags."""
    meta = {}
    for o in [x for x in bpy.context.scene.objects if x.type == "MESH"]:
        for p in o.data.polygons:
            mi = p.material_index
            if mi >= len(o.material_slots):
                continue
            mm = o.material_slots[mi].material
            if not mm:
                continue
            n = mm.name
            d = meta.get(n)
            if d is None:
                # Glass/light by name first, then only STRONG material signals
                # (blend_method is unreliable across Blender versions, so it's
                # not used). Default is opaque body-eligible.
                glass = bool(_GLASS.search(n))
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
                            if alpha < 0.55:
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
                light = emiss or bool(_LIGHT.search(n))
                excl = bool(glass or light or _TYRE.search(n) or _WHEEL.search(n)
                            or _TRIM.search(n) or _INNER.search(n) or _DARKP.search(n))
                meta[n] = {"area": 0.0, "glass": glass, "light": light,
                           "excl": excl, "paint": bool(_PAINT.search(n)), "mat": mm,
                           "dbg": {"alpha": alpha, "tw": tw, "emiss": emiss}}
                d = meta[n]
            d["area"] += p.area
    return meta


def _choose_body(meta):
    """Body-paint material names: paint-named candidates plus the largest opaque
    non-excluded material(s), so multi-panel bodies and generic-named ('Material_134',
    'Misc') bodies both get repainted while glass/lights/wheels/interior are spared."""
    cands = {n: d for n, d in meta.items() if not d["excl"]}
    chosen = set(n for n, d in cands.items() if d["paint"])
    if cands:
        big = max(d["area"] for d in cands.values())
        thresh = big * 0.55
        for n, d in cands.items():
            if d["area"] >= thresh:
                chosen.add(n)
    return chosen


def _load_bpy():
    import bpy  # imported lazily so import errors surface in the handler
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


def _make_plate(reg):
    """Render a UK plate PNG (white, blue UK band, black chars). Returns path."""
    from PIL import Image, ImageDraw, ImageFont
    reg = reg.upper().strip()
    W, H = 1040, 220
    img = Image.new("RGB", (W, H), (250, 250, 248))
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
    path = os.path.join(tempfile.gettempdir(), "plate.png")
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


def _render(bpy, glb, out, colour, plate_reg, az_deg, elev, zfrac,
            samples, resx, resy, bright=False, studio=False):
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
    # Detection is by role flags + area in Blender (not just material name), so
    # generic-named / non-English bodies still repaint and glass/lights/wheels
    # are spared. Any baked texture or vertex-colour feeding Base Color is
    # unlinked so the DVLA colour always wins (fixes camo-wrap models).
    meta = _classify_materials(bpy)
    chosen = _choose_body(meta)
    for bn in chosen:
        m = meta[bn]["mat"]
        if not m or not m.use_nodes or not m.node_tree:
            continue
        b = m.node_tree.nodes.get("Principled BSDF")
        if not b:
            continue
        if colour and colour.lower() in _RGB:
            for lnk in list(b.inputs["Base Color"].links):
                m.node_tree.links.remove(lnk)
            b.inputs["Base Color"].default_value = (*_RGB[colour.lower()], 1)
            b.inputs["Metallic"].default_value = 0.6
        b.inputs["Roughness"].default_value = 0.11
        if "Coat Weight" in b.inputs:
            b.inputs["Coat Weight"].default_value = 1.0
            b.inputs["Coat Roughness"].default_value = 0.03

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
    use_bright = (bright or (colour and colour.lower() in _dark)) and not studio
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

    # glossy dark floor
    fm = bpy.data.meshes.new("floor")
    bm = bmesh.new()
    s2 = size * 5
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
    fb.inputs["Roughness"].default_value = 0.06
    fm.materials.append(fmat)

    # optional plate on the camera-facing end
    if plate_reg:
        plate_png = _make_plate(plate_reg)
        L = 0 if (hi[0] - lo[0]) >= (hi[1] - lo[1]) else 1
        Wd = 1 - L
        scale = (hi[L] - lo[L]) / 4.5
        pw = 0.52 * scale / 2
        ph = 0.11 * scale / 2
        end = hi[L] if abs(loc[L] - hi[L]) < abs(loc[L] - lo[L]) else lo[L]
        outward = 1.0 if end == hi[L] else -1.0
        Lc = end + outward * size * 0.006
        Wc = c[Wd]
        Zc = zmin + zfrac * height
        pm = bpy.data.meshes.new("plate")
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
        pobj = bpy.data.objects.new("plate", pm)
        bpy.context.collection.objects.link(pobj)
        pmat = bpy.data.materials.new("plate")
        pmat.use_nodes = True
        nt = pmat.node_tree
        pb = nt.nodes.get("Principled BSDF")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(plate_png)
        nt.links.new(tex.outputs["Color"], pb.inputs["Base Color"])
        pb.inputs["Roughness"].default_value = 0.3
        if "Emission Color" in pb.inputs:
            nt.links.new(tex.outputs["Color"], pb.inputs["Emission Color"])
            pb.inputs["Emission Strength"].default_value = 0.6
        pm.materials.append(pmat)

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
    bpy.ops.render.render(write_still=True)
    return device


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
        device = _render(
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
            studio=bool(ji.get("studio", False)),
        )
        dt = round(time.time() - t0, 1)
        with open(out, "rb") as f:
            png_b64 = base64.b64encode(f.read()).decode("utf-8")
        return {"status": "success", "png_b64": png_b64,
                "device": device, "seconds": dt}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


runpod.serverless.start({"handler": handler})
