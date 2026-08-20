#!/usr/bin/env python3
"""blender_live.py — a RESIDENT Blender session that takes repair commands.

Every other Blender stage in this repo is `blender -b --python x.py -- in.glb
out.glb`: boot, import, one fixed operation, export, exit. That shape makes an
iterative repair — nudge, render, judge, nudge again — cost a full cold cycle
per nudge, so nobody does it. This keeps ONE scene resident and feeds it
commands, so the import is paid once and every later command starts from a
loaded car.

MEASURED, so the justification is honest rather than assumed (Golf Mk8
golf_final.glb, 65MB, 592,715 verts / 983,512 faces, 2026-08-20):
  blender boot + factory reset + glTF import  ~5.0 s   paid ONCE here
  glTF import alone                            3.18 s
So the fixed cost this harness removes is ~5 s per command, NOT the ~60 s that
was assumed when the work was commissioned. On a CYCLES CPU render (~30-60 s at
1100px/40spp on 4 cores) that is a modest win; on the cheap commands — info,
select, snapshot, restore, apply, export — it is the difference between 5.2 s
and 0.2 s, i.e. the whole cost. State the numbers, not the hope.

TRANSPORT: a unix domain socket, one newline-terminated JSON request per
connection, one newline-terminated JSON reply, then close.
  * a FIFO was rejected: opening the reply FIFO BLOCKS until a reader appears,
    so a client that dies after sending wedges the session forever — the exact
    failure this harness must survive.
  * a watched command-file was rejected: it polls (latency, or a busy loop) and
    races on partial writes.
  * a socket gives framing for free, wakes instantly, and a dead client is a
    plain OSError on send which we swallow. The op has already run; the scene is
    unaffected. VERIFIED by test (see PROVEN below).

NOTHING an op raises may kill the session. Every dispatch is wrapped, including
SystemExit — bpy operators and stray `raise SystemExit` in helper code would
otherwise take the resident scene with them, and a harness that dies on a bad
argument is no better than the batch scripts it replaces.

SNAPSHOTS — this is the feature the harness exists for, and Blender's own undo
does NOT work here. MEASURED on the Golf, background mode, Blender 4.0.2:

    bpy.ops.ed.undo_push(message=...)   -> ok
    bpy.ops.ed.undo()                   -> RuntimeError: Operator
                                           bpy.ops.ed.undo.poll() failed,
                                           context is incorrect
    metric after the failed undo        -> UNCHANGED from the mutated value

so the mutation survives an "undo" that reports failure only via an exception.
Do not trust `ed.undo` in `-b` mode and do not reintroduce it. Two snapshot
modes are provided instead, both measured on that same car:

  mode="blend"  save_as_mainfile(copy=True) + open_mainfile
                0.44 s save / 0.63 s restore / 158 MB on disk
                FULL fidelity: geometry, topology, materials, object
                transforms, the render rig, everything.
  mode="verts"  numpy cache of every mesh's vertex coordinates
                0.06 s save / 0.03 s restore / ~7 MB in RAM
                GEOMETRY ONLY: restores vertex POSITIONS. It cannot restore
                topology, materials or object transforms, and it silently
                cannot restore a mesh whose vertex COUNT changed — so it
                reports those as `unrestorable` rather than pretending.

Disk is the reason blend snapshots are capped. This container has rolled back
four times in one day and the volume reaching 100% is what started it (see
CLAUDE.md); at 158 MB a snapshot an unbounded stack fills 6 GB in 40 commands.
So: a ring buffer (--max-snapshots, default 4, oldest evicted and SAID SO) and
a hard refusal below --min-free-gb.

RENDER: the rig is `eyeball_views.py`'s, which is the proven one — bbox-derived
camera (the catalogue azimuth convention has produced upside-down sheets twice),
80mm lens, key SUN plus a FILL from the other side (the production rig's
one-sided key made a majority of cars read as a 2-vs-2 brightness split and was
misread as a per-side wheel defect more than once). CYCLES, denoising OFF: this
build has no EGL so EEVEE cannot initialise, and no OIDN either.
View transform is forced to **Standard**. Blender 4's default AgX once clipped a
tyre to pure white and produced a FALSE defect verdict that cost a wrong ruling
being written down before a magenta control exposed it. `op_calibrate` proves
Standard is actually in force by rendering a 0.22 emission card and asserting it
lands at sRGB 129 +/- 3 — the same 0.22 -> ~130 calibration CLAUDE.md records.
A guard nobody tested is a guard that does not exist, so the guard renders.

LOG: every request is appended to a JSONL log with a timestamp, the op and its
arguments, the status and the wall time. `blender_cmd.py replay <log>` feeds it
back into a fresh session, so a live repair session is reproducible as a batch.
A live session whose work cannot be reproduced is a liability.

Run (normally via blender_cmd.py start, which handles the readiness race):
  blender -b --python blender_live.py -- --sock /tmp/bl.sock --log /tmp/bl.jsonl
"""
import datetime
import json
import math
import os
import shutil
import socket
import sys
import time
import traceback

import bpy
import bmesh
import mathutils
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


SOCK = _arg("--sock", "/tmp/blender_live.sock")
LOG = _arg("--log", SOCK + ".jsonl")
READY = SOCK + ".ready"
SNAPDIR = _arg("--snapdir", SOCK + ".snaps")
IDLE_TIMEOUT = float(_arg("--idle-timeout", "3600"))
MAX_SNAPS = int(_arg("--max-snapshots", "4"))
MIN_FREE_GB = float(_arg("--min-free-gb", "2.0"))

# Server-side state. Deliberately holds NO bpy pointers: a blend restore calls
# open_mainfile, which invalidates every previously held Python reference to
# Blender data. Anything cached across a restore would be a dangling pointer and
# would crash the process — which for a resident session means losing the scene
# we exist to keep. Everything is re-resolved BY NAME inside each op.
STATE = {"glb": None, "selection": [], "seq": 0, "t0": time.time()}
SNAPS = []          # [{"name","mode","path"|"data","t","bytes"}] oldest first


class _Quit(Exception):
    """the only exception allowed to end the loop"""


# --------------------------------------------------------------- utilities

def _meshes():
    return [o for o in bpy.data.objects if o.type == "MESH"]


def _world_bbox(objs=None):
    """world-space bbox over mesh objects; None if there is no geometry"""
    lo = [1e30] * 3
    hi = [-1e30] * 3
    for o in (objs if objs is not None else _meshes()):
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    if lo[0] > hi[0]:
        return None
    return lo, hi


def _counts():
    ms = _meshes()
    return {"objects": len(bpy.data.objects), "meshes": len(ms),
            "materials": len(bpy.data.materials),
            "verts": sum(len(o.data.vertices) for o in ms),
            "faces": sum(len(o.data.polygons) for o in ms)}


def _resolve(names):
    """names -> live objects, dropping any that vanished (rename, restore)"""
    out = []
    for n in names:
        o = bpy.data.objects.get(n)
        if o is not None:
            out.append(o)
    return out


def _sel_objects():
    """the current selection, or every mesh when nothing is selected"""
    if not STATE["selection"]:
        return _meshes()
    return [o for o in _resolve(STATE["selection"]) if o.type == "MESH"]


def _free_gb(path):
    return shutil.disk_usage(os.path.dirname(path) or "/").free / 1e9


# ------------------------------------------------------------------ render rig

RIG = {"cam": "LIVE_CAM", "key": "LIVE_KEY", "fill": "LIVE_FILL"}


def _ensure_rig(res, samples, engine="CYCLES"):
    """(re)build the eyeball_views rig if it is absent.

    Absent is the NORMAL case after `load` (which factory-resets) and after a
    blend restore of a snapshot taken before the first render — so this is
    idempotent and cheap, not a one-time init.
    """
    sc = bpy.context.scene
    cam = bpy.data.objects.get(RIG["cam"])
    if cam is None:
        cam = bpy.data.objects.new(RIG["cam"], bpy.data.cameras.new(RIG["cam"]))
        sc.collection.objects.link(cam)
        cam.data.lens = 80                  # long lens: minimal perspective distortion
    sc.camera = cam

    if bpy.data.objects.get(RIG["key"]) is None:
        key = bpy.data.objects.new(RIG["key"],
                                   bpy.data.lights.new(RIG["key"], "SUN"))
        key.data.energy = 4.0
        key.data.angle = math.radians(12)
        sc.collection.objects.link(key)
        key.rotation_euler = (math.radians(50), 0, math.radians(35))
    if bpy.data.objects.get(RIG["fill"]) is None:
        # FILL FROM THE OTHER SIDE — the production rig's single-sided key makes
        # a majority of cars read as a 2-vs-2 brightness split by side, which has
        # been misdiagnosed as a per-side wheel defect more than once.
        fill = bpy.data.objects.new(RIG["fill"],
                                    bpy.data.lights.new(RIG["fill"], "SUN"))
        fill.data.energy = 1.6
        sc.collection.objects.link(fill)
        fill.rotation_euler = (math.radians(60), 0, math.radians(210))

    sc.render.engine = engine
    if engine == "CYCLES":
        sc.cycles.device = "CPU"
        sc.cycles.samples = samples
        sc.cycles.use_denoising = False     # no OIDN in this build
        sc.view_layers[0].cycles.use_denoising = False
    # THE AgX TRAP: Blender 4 defaults to AgX, which once clipped a tyre to pure
    # white and produced a false defect verdict. Standard, always, and
    # op_calibrate proves it numerically.
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.exposure = 0.0
    sc.view_settings.look = "None"
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    return cam


def _png_stats(path):
    """mean/clip statistics of a rendered PNG, read as RAW FILE VALUES.

    colorspace 'Non-Color' matters: with the default sRGB colorspace Blender
    converts the file's bytes to scene-linear on read, and the numbers would not
    be the sRGB values the file actually holds — which is precisely what a
    view-transform check has to measure.
    """
    img = bpy.data.images.load(path, check_existing=False)
    try:
        img.colorspace_settings.name = "Non-Color"
        img.reload()
        buf = np.empty(len(img.pixels), dtype=np.float32)
        img.pixels.foreach_get(buf)
        px = buf.reshape(-1, 4)
        a = px[:, 3]
        fg = px[a > 0.5, :3]                # the car; background is transparent
        st = {"pixels": int(px.shape[0]),
              "coverage": round(float((a > 0.5).mean()), 4)}
        if fg.size:
            st["mean_srgb"] = round(float(fg.mean()) * 255, 1)
            st["clipped_frac"] = round(float((fg.max(axis=1) >= 254 / 255).mean()), 4)
        else:
            st["mean_srgb"] = None
            st["clipped_frac"] = None
        st["mean_srgb_all"] = round(float(px[:, :3].mean()) * 255, 1)
        return st
    finally:
        bpy.data.images.remove(img)


# ----------------------------------------------------------------------- ops

def op_ping(a):
    return {"uptime_s": round(time.time() - STATE["t0"], 1),
            "glb": STATE["glb"], "commands": STATE["seq"],
            "selection": len(STATE["selection"]), "snapshots": len(SNAPS),
            "blender": bpy.app.version_string}


def op_load(a):
    """import a GLB. clear=True (default) factory-resets first, which also
    removes the render rig — _ensure_rig rebuilds it on the next render."""
    path = a["path"]
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    t = time.time()
    if a.get("clear", True):
        bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    STATE["glb"] = path
    STATE["selection"] = []
    bb = _world_bbox()
    r = _counts()
    r["import_s"] = round(time.time() - t, 2)
    r["size_mb"] = round(os.path.getsize(path) / 1e6, 1)
    if bb:
        r["dimensions"] = [round(bb[1][i] - bb[0][i], 4) for i in range(3)]
    return r


def op_info(a):
    r = _counts()
    bb = _world_bbox()
    if bb:
        r["bbox_min"] = [round(v, 4) for v in bb[0]]
        r["bbox_max"] = [round(v, 4) for v in bb[1]]
        r["dimensions"] = [round(bb[1][i] - bb[0][i], 4) for i in range(3)]
    r["glb"] = STATE["glb"]
    r["selection"] = list(STATE["selection"])
    objs = []
    for o in _meshes():
        ob = _world_bbox([o])
        objs.append({"name": o.name, "verts": len(o.data.vertices),
                     "faces": len(o.data.polygons),
                     "materials": [m.name for m in o.data.materials if m],
                     "location": [round(v, 4) for v in o.location],
                     "dimensions": ([round(ob[1][i] - ob[0][i], 4)
                                     for i in range(3)] if ob else None)})
    r["object_list"] = sorted(objs, key=lambda d: -d["verts"])
    if a.get("materials"):
        r["material_list"] = [m.name for m in bpy.data.materials]
    return r


def op_select(a):
    """name / regex / material / geometric predicate -> named selection.

    The predicate is `eval`'d against per-object metrics. This is a LOCAL
    developer tool talking over a unix socket owned by the user; it is not a
    network service and the expression is not sanitised. Do not expose the
    socket to anything you would not hand a python prompt.
    """
    import re
    hits = []
    for o in _meshes():
        bb = _world_bbox([o])
        if bb is None:
            continue
        env = {"name": o.name, "verts": len(o.data.vertices),
               "faces": len(o.data.polygons),
               "mats": [m.name for m in o.data.materials if m],
               "minx": bb[0][0], "miny": bb[0][1], "minz": bb[0][2],
               "maxx": bb[1][0], "maxy": bb[1][1], "maxz": bb[1][2],
               "cx": (bb[0][0] + bb[1][0]) / 2, "cy": (bb[0][1] + bb[1][1]) / 2,
               "cz": (bb[0][2] + bb[1][2]) / 2}
        ok = True
        if "name" in a:
            ok = ok and a["name"].lower() in o.name.lower()
        if "regex" in a:
            ok = ok and re.search(a["regex"], o.name, re.I) is not None
        if "material" in a:
            ok = ok and any(a["material"].lower() in m.lower()
                            for m in env["mats"])
        if "predicate" in a:
            ok = ok and bool(eval(a["predicate"], {"__builtins__": {}}, env))  # noqa: S307
        if ok:
            hits.append(o.name)
    if a.get("add"):
        hits = sorted(set(STATE["selection"]) | set(hits))
    STATE["selection"] = hits
    ms = _resolve(hits)
    return {"selected": hits, "count": len(hits),
            "verts": sum(len(o.data.vertices) for o in ms),
            "faces": sum(len(o.data.polygons) for o in ms)}


def op_render(a):
    """render one view. az/el follow eyeball_views; camera framing is derived
    from the CURRENT bbox so a repair that moves geometry stays framed."""
    out = a["out"]
    res = int(a.get("res", 900))
    samples = int(a.get("samples", 24))
    cam = _ensure_rig(res, samples, a.get("engine", "CYCLES"))
    bb = _world_bbox()
    if bb is None:
        raise RuntimeError("no mesh geometry in the scene — load a GLB first")
    lo, hi = bb
    ctr = mathutils.Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
    diag = max(hi[i] - lo[i] for i in range(3))
    if a.get("camera"):
        c = bpy.data.objects[a["camera"]]
        cam.location, cam.rotation_euler = c.location, c.rotation_euler
    else:
        az = math.radians(float(a.get("az", 45)))
        el = float(a.get("el", 0.30))
        dist = float(a.get("dist", 2.3))
        cam.location = ctr + mathutils.Vector((dist * diag * math.cos(az),
                                               dist * diag * math.sin(az),
                                               el * diag * 3))
        d = (ctr - cam.location).normalized()
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    bpy.context.scene.render.filepath = out
    t = time.time()
    bpy.ops.render.render(write_still=True)
    r = {"out": out, "render_s": round(time.time() - t, 2), "res": res,
         "samples": samples,
         "view_transform": bpy.context.scene.view_settings.view_transform}
    if os.path.exists(out):
        r["bytes"] = os.path.getsize(out)
        if a.get("stats", True):
            r.update(_png_stats(out))
    return r


def op_calibrate(a):
    """PROVE the view transform is Standard, numerically, by rendering.

    An emission shader of value v renders to linear v exactly — no lighting, no
    sampling noise, no dependence on the scene. Under Standard, v=0.22 lands at
    sRGB 129.2; under AgX the same card lands far lower. This is the executable
    form of the lesson that cost a false white-tyre verdict.
    """
    v = float(a.get("value", 0.22))
    sc = bpy.context.scene
    keep_engine, keep_res = sc.render.engine, (sc.render.resolution_x,
                                               sc.render.resolution_y)
    _ensure_rig(int(a.get("res", 64)), 1)
    mesh = bpy.data.meshes.new("_CAL")
    obj = bpy.data.objects.new("_CAL", mesh)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    sc.collection.objects.link(obj)
    mat = bpy.data.materials.new("_CALMAT")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (v, v, v, 1.0)
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(em.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs[0])
    mesh.materials.append(mat)
    cam = bpy.data.objects[RIG["cam"]]
    keep_loc, keep_rot = tuple(cam.location), tuple(cam.rotation_euler)
    cam.location = (0, 0, 3)                 # card fills frame, dead-on
    cam.rotation_euler = (0, 0, 0)
    cam.data.lens = 80
    out = a.get("out", os.path.join(SNAPDIR, "_calibrate.png"))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sc.render.film_transparent = False
    sc.render.filepath = out
    try:
        bpy.ops.render.render(write_still=True)
        st = _png_stats(out)
    finally:                                  # never leave the scene dirtied
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.materials.remove(mat)
        cam.location, cam.rotation_euler = keep_loc, keep_rot
        sc.render.film_transparent = True
        sc.render.engine = keep_engine
        sc.render.resolution_x, sc.render.resolution_y = keep_res
    expect = round((1.055 * v ** (1 / 2.4) - 0.055) * 255, 1)
    got = st["mean_srgb_all"]
    tol = float(a.get("tol", 3.0))
    return {"value": v, "expected_srgb": expect, "measured_srgb": got,
            "delta": round(got - expect, 2), "tolerance": tol,
            "view_transform": sc.view_settings.view_transform,
            "standard_confirmed": abs(got - expect) <= tol, "out": out}


# --- repair operators -------------------------------------------------------
# DELIBERATELY MINIMAL. Real repair operators belong to the repair mission, not
# to the harness; these two exist to demonstrate the apply/snapshot/restore loop
# and to make the two snapshot modes' different coverage concrete.

def _rep_translate(sel, a):
    """move geometry. space='mesh' edits VERTEX COORDINATES, so both snapshot
    modes can restore it; space='object' edits the object transform, which ONLY
    a blend snapshot captures — the vertex cache stores coordinates, not
    matrices, and would silently "restore" nothing. Stated because a snapshot
    that quietly does not cover an operation is worse than no snapshot."""
    d = np.array([float(a.get("dx", 0)), float(a.get("dy", 0)),
                  float(a.get("dz", 0))], dtype=np.float32)
    space = a.get("space", "mesh")
    n = 0
    for o in sel:
        if space == "object":
            o.location = [o.location[i] + float(d[i]) for i in range(3)]
            n += 1
            continue
        cnt = len(o.data.vertices)
        buf = np.empty(cnt * 3, dtype=np.float32)
        o.data.vertices.foreach_get("co", buf)
        buf.reshape(-1, 3)[:] += d
        o.data.vertices.foreach_set("co", buf)
        o.data.update()
        n += cnt
    return {"space": space, "delta": [float(x) for x in d],
            "objects": len(sel), "moved": n}


def _rep_recalc_normals(sel, a):
    """recalculate outward face normals. Topology-adjacent: a VERTS snapshot
    does NOT capture this (it stores coordinates only) — use mode='blend' if you
    intend to revert it."""
    n = 0
    for o in sel:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(o.data)
        bm.free()
        o.data.update()
        n += len(o.data.polygons)
    return {"objects": len(sel), "faces": n}


REPAIRS = {"translate": _rep_translate, "recalc_normals": _rep_recalc_normals}


def op_apply(a):
    op = a.get("op")
    if op not in REPAIRS:
        raise KeyError(f"unknown repair op {op!r}; have {sorted(REPAIRS)}")
    sel = _sel_objects()
    if not sel:
        raise RuntimeError("nothing selected and no meshes in the scene")
    t = time.time()
    r = REPAIRS[op](sel, a)
    r["op"] = op
    r["apply_s"] = round(time.time() - t, 2)
    return r


def op_measure(a):
    """a cheap scalar over the scene, so a test can PROVE a mutation happened
    and PROVE a restore undid it. Mean vertex coordinate per axis plus the
    world bbox — both move when geometry moves."""
    tot = np.zeros(3, dtype=np.float64)
    n = 0
    for o in _sel_objects():
        cnt = len(o.data.vertices)
        if not cnt:
            continue
        buf = np.empty(cnt * 3, dtype=np.float32)
        o.data.vertices.foreach_get("co", buf)
        tot += buf.reshape(-1, 3).sum(axis=0)
        n += cnt
    bb = _world_bbox()
    return {"verts": n,
            "mean_co": [round(float(x), 6) for x in (tot / max(n, 1))],
            "bbox_min": [round(v, 6) for v in bb[0]] if bb else None,
            "bbox_max": [round(v, 6) for v in bb[1]] if bb else None}


# --- snapshots --------------------------------------------------------------

def _evict_if_needed():
    """ring buffer over BLEND snapshots only (verts snapshots are RAM and
    cheap). The volume filling to 100% is what began four container rollbacks
    in one day, so this cap is not cosmetic."""
    dropped = []
    blends = [s for s in SNAPS if s["mode"] == "blend"]
    while len(blends) > MAX_SNAPS:
        old = blends.pop(0)
        SNAPS.remove(old)
        try:
            os.unlink(old["path"])
        except OSError:
            pass
        dropped.append(old["name"])
    return dropped


def op_snapshot(a):
    mode = a.get("mode", "blend")
    name = a.get("name") or f"auto{len(SNAPS):03d}"
    SNAPS[:] = [s for s in SNAPS if s["name"] != name]     # replace by name
    os.makedirs(SNAPDIR, exist_ok=True)
    t = time.time()
    if mode == "blend":
        free = _free_gb(SNAPDIR)
        if free < MIN_FREE_GB:
            raise RuntimeError(
                f"REFUSED: {free:.1f} GB free < --min-free-gb {MIN_FREE_GB}; "
                "a full volume is what started four rollbacks in one day. "
                "Use mode='verts', or free space, or lower the floor.")
        path = os.path.join(SNAPDIR, f"{name}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True,
                                    compress=bool(a.get("compress", False)))
        rec = {"name": name, "mode": mode, "path": path, "t": time.time(),
               "bytes": os.path.getsize(path)}
    elif mode == "verts":
        data = {}
        for o in _meshes():
            cnt = len(o.data.vertices)
            buf = np.empty(cnt * 3, dtype=np.float32)
            o.data.vertices.foreach_get("co", buf)
            data[o.name] = buf
        rec = {"name": name, "mode": mode, "data": data, "t": time.time(),
               "bytes": int(sum(b.nbytes for b in data.values()))}
    else:
        raise ValueError(f"mode must be 'blend' or 'verts', got {mode!r}")
    SNAPS.append(rec)
    dropped = _evict_if_needed()
    return {"name": name, "mode": mode, "snapshot_s": round(time.time() - t, 2),
            "bytes": rec["bytes"], "stack": [s["name"] for s in SNAPS],
            "evicted": dropped, "free_gb": round(_free_gb(SNAPDIR), 1)}


def _restore(rec):
    t = time.time()
    if rec["mode"] == "blend":
        if not os.path.exists(rec["path"]):
            raise FileNotFoundError(f"snapshot file gone: {rec['path']}")
        bpy.ops.wm.open_mainfile(filepath=rec["path"])
        # every bpy pointer anywhere is now dangling; STATE holds names only,
        # which is why it holds names only.
        return {"restored_s": round(time.time() - t, 2), "unrestorable": []}
    bad = []
    for name, buf in rec["data"].items():
        o = bpy.data.objects.get(name)
        if o is None or o.type != "MESH":
            bad.append({"object": name, "why": "missing"})
            continue
        if len(o.data.vertices) * 3 != buf.size:
            # SAY SO. A vertex cache cannot restore a mesh whose topology moved,
            # and silently restoring nothing is the failure mode that makes a
            # guard worthless.
            bad.append({"object": name, "why": "vertex count changed",
                        "was": int(buf.size // 3),
                        "now": len(o.data.vertices)})
            continue
        o.data.vertices.foreach_set("co", buf)
        o.data.update()
    return {"restored_s": round(time.time() - t, 2), "unrestorable": bad}


def op_restore(a):
    name = a.get("name")
    if name:
        rec = next((s for s in SNAPS if s["name"] == name), None)
        if rec is None:
            raise KeyError(f"no snapshot {name!r}; have "
                           f"{[s['name'] for s in SNAPS]}")
    else:
        if not SNAPS:
            raise RuntimeError("no snapshots to restore")
        rec = SNAPS[-1]
    r = _restore(rec)
    r.update({"name": rec["name"], "mode": rec["mode"]})
    if a.get("pop"):
        SNAPS.remove(rec)
        if rec["mode"] == "blend":
            try:
                os.unlink(rec["path"])
            except OSError:
                pass
    r["stack"] = [s["name"] for s in SNAPS]
    return r


def op_undo(a):
    """restore the newest snapshot and DROP it — a stack pop, which is what a
    caller means by undo. Blender's own ed.undo does not work in background mode
    (measured; see the module docstring)."""
    return op_restore({"pop": True})


def op_snapshots(a):
    return {"stack": [{"name": s["name"], "mode": s["mode"],
                       "bytes": s["bytes"],
                       "age_s": round(time.time() - s["t"], 1)} for s in SNAPS],
            "max_blend": MAX_SNAPS, "dir": SNAPDIR,
            "free_gb": round(_free_gb(SNAPDIR), 1)}


def op_drop(a):
    """delete snapshots and reclaim their disk"""
    names = a.get("names") or ([a["name"]] if "name" in a else
                               [s["name"] for s in SNAPS])
    freed = 0
    for n in list(names):
        rec = next((s for s in SNAPS if s["name"] == n), None)
        if rec is None:
            continue
        freed += rec["bytes"]
        SNAPS.remove(rec)
        if rec["mode"] == "blend":
            try:
                os.unlink(rec["path"])
            except OSError:
                pass
    return {"dropped": names, "freed_mb": round(freed / 1e6, 1),
            "stack": [s["name"] for s in SNAPS]}


# --- export -----------------------------------------------------------------

def op_export(a):
    out = a["out"]
    inc = bool(a.get("include_normals", True))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    t = time.time()
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", export_normals=inc,
        export_materials="EXPORT", use_selection=False,
        export_apply=bool(a.get("apply_modifiers", False)))
    r = {"out": out, "export_s": round(time.time() - t, 2),
         "bytes": os.path.getsize(out), "include_normals": inc}
    if inc:
        # VERIFY the exporter actually wrote them. normals_fix.py exists because
        # a missing NORMAL accessor renders a car as crumpled foil and nothing
        # upstream complains — a fix that does not fire is the documented
        # failure class here.
        import struct
        b = open(out, "rb").read(1 << 22)
        jlen = struct.unpack("<I", b[12:16])[0]
        g = json.loads(b[20:20 + jlen])
        missing = [m.get("name") for m in g.get("meshes", [])
                   for p in m["primitives"] if "NORMAL" not in p["attributes"]]
        r["normal_accessors_missing"] = missing
        r["normals_verified"] = not missing
    return r


def op_log(a):
    n = int(a.get("tail", 20))
    if not os.path.exists(LOG):
        return {"log": LOG, "entries": []}
    lines = open(LOG).read().splitlines()[-n:]
    return {"log": LOG, "entries": [json.loads(x) for x in lines if x.strip()]}


def op_quit(a):
    raise _Quit()


OPS = {"ping": op_ping, "load": op_load, "info": op_info, "select": op_select,
       "render": op_render, "calibrate": op_calibrate, "apply": op_apply,
       "measure": op_measure, "snapshot": op_snapshot, "restore": op_restore,
       "undo": op_undo, "snapshots": op_snapshots, "drop": op_drop,
       "export": op_export, "log": op_log, "quit": op_quit}


# ------------------------------------------------------------------ dispatch

def _logline(rec):
    try:
        with open(LOG, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass          # a full disk must not kill the session either


def dispatch(req):
    STATE["seq"] += 1
    op = req.get("op")
    args = {k: v for k, v in req.items() if k != "op"}
    t = time.time()
    rec = {"t": datetime.datetime.now().isoformat(timespec="seconds"),
           "seq": STATE["seq"], "op": op, "args": args}
    try:
        fn = OPS.get(op)
        if fn is None:
            raise KeyError(f"unknown op {op!r}; have {sorted(OPS)}")
        result = fn(args)
        reply = {"status": "ok", "op": op, "seq": STATE["seq"],
                 "ms": int((time.time() - t) * 1000), "result": result}
    except _Quit:
        raise
    except BaseException as e:              # noqa: BLE001 — including SystemExit:
        # an op may NEVER end the session. A bpy operator that raises, a bad
        # argument, a KeyError from a typo, or helper code with a stray
        # `raise SystemExit` all have to leave the scene loaded and the loop
        # running, or this is just the batch scripts again with extra steps.
        reply = {"status": "error", "op": op, "seq": STATE["seq"],
                 "ms": int((time.time() - t) * 1000),
                 "error": type(e).__name__, "message": str(e),
                 "traceback": traceback.format_exc().splitlines()[-6:]}
    rec["status"] = reply["status"]
    rec["ms"] = reply["ms"]
    if reply["status"] == "error":
        rec["error"] = f'{reply["error"]}: {reply["message"]}'
    _logline(rec)
    return reply


def serve():
    if os.path.exists(SOCK):
        os.unlink(SOCK)                     # stale socket from a killed session
    os.makedirs(SNAPDIR, exist_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    srv.listen(8)
    srv.settimeout(IDLE_TIMEOUT)
    # the ready file is written AFTER listen(), so a client that sees it can
    # always connect — polling for the socket file alone races the bind.
    with open(READY, "w") as fh:
        json.dump({"pid": os.getpid(), "sock": SOCK, "log": LOG,
                   "snapdir": SNAPDIR, "started": time.time()}, fh)
    print(f"BLENDER_LIVE_READY sock={SOCK} pid={os.getpid()} log={LOG}",
          flush=True)
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                print(f"BLENDER_LIVE_IDLE_EXIT after {IDLE_TIMEOUT}s", flush=True)
                return
            try:
                conn.settimeout(120)        # a client that connects and never
                buf = b""                   # speaks must not wedge the session
                while b"\n" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                if not buf.strip():
                    continue
                try:
                    req = json.loads(buf.split(b"\n", 1)[0].decode())
                except Exception as e:      # noqa: BLE001
                    reply = {"status": "error", "error": "BadJSON",
                             "message": str(e)}
                else:
                    reply = dispatch(req)
                try:
                    conn.sendall((json.dumps(reply) + "\n").encode())
                except OSError as e:
                    # the client died between sending and reading. The op has
                    # already run and the scene is intact; that is the whole
                    # point of doing the work before answering.
                    print(f"BLENDER_LIVE_REPLY_UNDELIVERED seq={STATE['seq']} "
                          f"{type(e).__name__}", flush=True)
            except socket.timeout:
                print("BLENDER_LIVE_CLIENT_TIMEOUT", flush=True)
            except _Quit:
                raise
            except OSError as e:
                print(f"BLENDER_LIVE_CONN_ERROR {type(e).__name__}: {e}",
                      flush=True)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
    except _Quit:
        print("BLENDER_LIVE_QUIT", flush=True)
    finally:
        srv.close()
        for p in (SOCK, READY):
            try:
                os.unlink(p)
            except OSError:
                pass
        # snapshot .blend files are NOT auto-removed on quit: a session that
        # died mid-repair is exactly when you want the last good state back.
        # blender_cmd.py stop --clean removes them deliberately.


if __name__ == "__main__":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if _arg("--glb"):
        try:
            print("BLENDER_LIVE_PRELOAD", json.dumps(op_load({"path": _arg("--glb")})),
                  flush=True)
        except Exception as e:              # noqa: BLE001
            print(f"BLENDER_LIVE_PRELOAD_FAILED {type(e).__name__}: {e}",
                  flush=True)
    serve()
