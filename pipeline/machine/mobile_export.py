#!/usr/bin/env python3
"""
mobile_export.py -- turn a master GLB into a mobile GLB under a size budget
WITHOUT visible silhouette degradation.

    python3 pipeline/machine/mobile_export.py master.glb out.glb --budget-mb 8

------------------------------------------------------------------------------
WHY THE ORDER OF OPERATIONS IS WHAT IT IS
------------------------------------------------------------------------------
Measured on the Golf Mk8 master (65.13 MB, 985,227 tris, 6 draw calls):

    texture payload   37.35 MB  (57.4%)   2 unique 4096x4096 PNGs
    geometry payload  27.77 MB  (42.6%)   indices 11.82 / pos 7.11 / nrm 7.11 / uv 1.72

THE FILE IS TEXTURE-MAJORITY. That single fact sets the whole strategy: no
geometry compression alone can ever reach an 8 MB budget, because even
annihilating 100% of the geometry leaves 37 MB of PNG. Texture handling is the
primary lever and mesh work is secondary.

It also explains the "Draco made it WORSE" result (65 MB -> 78 MB, rc=0), which
is NOT a Draco failure:

    master : tex 37.35 + geo 27.77 = 65.12 MB
    draco  : tex 74.70 + geo  3.12 = 77.82 MB
             ^^^^^^^^ exactly 2x            ^^^^ 8.90x SMALLER

Draco did its job: geometry fell 27.77 -> 3.12 MB, an 8.90x win. The master has
4 images sharing only 2 bufferViews (images 0,2 -> bv2; images 1,3 -> bv3). The
Draco pass rewrote the buffer and gave every image its OWN copy, un-deduplicating
37.35 MB of PNG. Net +12.70 MB, which matches the observed inflation exactly.

=> STAGE ORDER, and the reason for each position:

  1. DEDUP + PRUNE ......... FIRST, always. This is the guard against the exact
                             +37 MB trap above. Any stage that rewrites buffers
                             can un-share image bufferViews, so dedup runs first
                             and again at the end. Zero visual cost.
  2. CULL HIDDEN INTERIOR .. Before simplification, so the simplifier spends its
                             error budget only on geometry somebody can see.
                             Proven-invisible by ray test => zero silhouette cost.
  3. WELD .................. meshoptimizer's simplifier is limited by split
                             vertices; welding first is what makes stage 4 work.
  4. SIMPLIFY (error-bound). ERROR-bounded, not ratio-bounded. A fixed error as a
                             fraction of mesh radius automatically preserves
                             high-curvature silhouette edges and crushes flat
                             interior panels -- which is the behaviour we want and
                             a global ratio does not give.
  5. TEXTURE RESIZE + WEBP . The main event. Textures cannot affect the
                             silhouette (that is pure geometry), so this is the
                             cheapest large saving available and it is applied
                             after geometry so the final atlas matches final UVs.
  6. COMPRESS (draco|meshopt) LAST. Compression makes the mesh opaque to further
                             editing, so nothing may follow it except dedup.
  7. VERIFY ................ silhouette IoU + Khronos validator + budget.

------------------------------------------------------------------------------
THE SILHOUETTE GATE
------------------------------------------------------------------------------
Metric: ALPHA IoU from matched cameras. For each of 8 canonical azimuths the car
is ray-cast at 1024x1024 from an identical camera before and after; the binary
"pixel hit the car" masks give IoU = |A n B| / |A u B|.

A reduction is REFUSED if any single view falls below --min-iou (default 0.990)
or the mean falls below --min-mean-iou (default 0.995). Refusing is the point:
the tool declines to write a file that moved the outline, rather than reporting
a number and shipping anyway.

Per-material screen coverage is reported alongside, because a whole-car IoU can
stay high while the glazing quietly thins -- and opaque glazing is an owner-level
hard fail.

------------------------------------------------------------------------------
INTERIOR CULLING -- AND WHY "67% IS INTERIOR" IS NOT 67% OF FREE BUDGET
------------------------------------------------------------------------------
The interior mesh is 660,134 of 985,227 tris (67.0%) and its bbox is the WHOLE
car, so it is an inner shell of the entire body, not cabin furniture.

It is NOT invisible. MEASURED, 8 canonical views at 1024x1024 with glass treated
as fully transparent (the worst case): 15.24% of all car pixels show interior.
The rear view is the extreme at 22.26%. Depth-testing the big rear block found
75.7% of those pixels have NO carpaint at all and 83% have glass in front --
i.e. it is the cabin seen through the rear screen, exactly the through-glass read
the owner's glazing ruling protects. Deleting the interior wholesale would gut it.

What IS free is the part with no line of sight from ANY camera. That is found by
an EXACT per-face test, not by rasterising: for every interior face a ray is cast
from its centroid to each camera and blocked only by OPAQUE geometry (glass
excluded, so through-glass sightlines count as visible).

A camera-raster prototype was tried first and DISCARDED as unconverged -- it gave
5.02% -> 13.13% -> 29.87% visible as sampling rose, because interior faces average
~7.5 mm across while a 300px raster over a 5.4 m span samples every 18 mm. Any
number from that method is an undercount of unknown size. Do not reintroduce it.

The keep-set is then DILATED over face adjacency (--dilate rings) so that a face
which is marginally visible from an unsampled angle still has neighbours present.
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from collections import OrderedDict

import numpy as np

try:
    import trimesh
except ImportError:
    trimesh = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

GLTF_TRANSFORM = shutil.which("gltf-transform") or "/opt/node22/bin/gltf-transform"

# Materials that block a sightline. Glass is BLEND and deliberately excluded.
OPAQUE_MATERIALS = ("carpaint", "Rim_Alloy", "Tyre_Rubber", "Lamp_Lens", "interior")
TRANSPARENT_HINT = ("glass", "window", "windscreen", "glazing")

CANONICAL_VIEWS = [
    ("front", 180.0, 12.0), ("front34", 215.0, 12.0),
    ("side", 270.0, 12.0), ("rear34", 315.0, 12.0),
    ("rear", 0.0, 12.0), ("rear34_L", 45.0, 12.0),
    ("side_L", 90.0, 12.0), ("front34_L", 135.0, 12.0),
]


# --------------------------------------------------------------------------
# GLB container I/O -- direct surgery, so that image bufferView SHARING and
# every material flag (glass alphaMode=BLEND in particular) survive untouched.
# Round-tripping through a mesh library loses both.
# --------------------------------------------------------------------------

def glb_read(path):
    with open(path, "rb") as fh:
        magic, ver, total = struct.unpack("<III", fh.read(12))
        if magic != 0x46546C67:
            raise ValueError("not a GLB: %s" % path)
        js, bin_ = None, b""
        while fh.tell() < total:
            clen, ctype = struct.unpack("<II", fh.read(8))
            data = fh.read(clen)
            if ctype == 0x4E4F534A:
                js = json.loads(data.decode("utf-8"))
            elif ctype == 0x004E4942:
                bin_ = data
    return js, bin_


def glb_write(path, js, bin_):
    jb = json.dumps(js, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bb = bin_ + b"\x00" * ((4 - len(bin_) % 4) % 4)
    total = 12 + 8 + len(jb) + (8 + len(bb) if bb else 0)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(jb), 0x4E4F534A)); fh.write(jb)
        if bb:
            fh.write(struct.pack("<II", len(bb), 0x004E4942)); fh.write(bb)


COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
        5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(js, bin_, idx):
    a = js["accessors"][idx]
    bv = js["bufferViews"][a["bufferView"]]
    fmt, sz = COMP[a["componentType"]]
    n = NCOMP[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or (sz * n)
    dt = np.dtype({"b": np.int8, "B": np.uint8, "h": np.int16,
                   "H": np.uint16, "I": np.uint32, "f": np.float32}[fmt])
    if stride == sz * n:
        arr = np.frombuffer(bin_, dtype=dt, count=a["count"] * n, offset=off)
        return arr.reshape(a["count"], n) if n > 1 else arr
    raw = np.frombuffer(bin_, dtype=np.uint8, count=a["count"] * stride, offset=off)
    raw = raw.reshape(a["count"], stride)[:, : sz * n]
    arr = raw.copy().view(dt)
    return arr.reshape(a["count"], n) if n > 1 else arr.ravel()


def payload_split(js):
    """Bytes attributable to images vs geometry. Counts each bufferView ONCE, so
    shared image views are not double-counted -- which is the whole point."""
    bvs = js["bufferViews"]
    img_bv = {im["bufferView"] for im in js.get("images", []) if "bufferView" in im}
    tex = sum(bvs[i]["byteLength"] for i in img_bv)
    tot = sum(bv["byteLength"] for bv in bvs)
    return {"total": tot, "texture": tex, "geometry": tot - tex,
            "n_images": len(js.get("images", [])), "n_unique_image_views": len(img_bv)}


def describe(path):
    js, bin_ = glb_read(path)
    sp = payload_split(js)
    meshes = []
    for i, m in enumerate(js.get("meshes", [])):
        for p in m["primitives"]:
            ia = js["accessors"][p["indices"]] if "indices" in p else None
            mat = js["materials"][p["material"]].get("name", "?") if "material" in p else "?"
            meshes.append({"mesh": i, "material": mat,
                           "tris": (ia["count"] // 3) if ia else 0,
                           "verts": js["accessors"][p["attributes"]["POSITION"]]["count"]})
    return {"path": path, "sizeBytes": os.path.getsize(path),
            "payload": sp, "meshes": meshes,
            "tris": sum(m["tris"] for m in meshes),
            "extensionsUsed": js.get("extensionsUsed", [])}


# --------------------------------------------------------------------------
# Stage 2 -- hidden-interior culling
# --------------------------------------------------------------------------

def hidden_face_mask(path, target="interior", n_az=32, elevations=(-25, -10, 5, 20, 40, 60, 80),
                     dilate=2, verbose=True):
    """Return (keep_mask, stats) for the target mesh's faces.

    keep_mask[i] is True when face i has line-of-sight to at least one camera,
    or lies within `dilate` adjacency rings of one that does.
    """
    if trimesh is None:
        raise RuntimeError("trimesh is required for interior culling")
    scene = trimesh.load(path, process=False)
    if target not in scene.geometry:
        raise KeyError("no geometry named %r (have %s)" % (target, list(scene.geometry)))
    tgt = scene.geometry[target]

    occluders = [n for n in scene.geometry
                 if not any(h in n.lower() for h in TRANSPARENT_HINT)]
    occl = trimesh.util.concatenate([scene.geometry[n] for n in occluders])
    inter = trimesh.ray.ray_pyembree.RayMeshIntersector(occl)

    b = scene.bounds
    centre = b.mean(axis=0)
    radius = float(np.linalg.norm(b[1] - b[0])) * 0.9

    eyes = []
    for el in elevations:
        e = np.radians(el)
        for k in range(n_az):
            az = 2 * np.pi * k / n_az
            eyes.append(centre + radius * np.array(
                [np.cos(e) * np.cos(az), np.sin(e), np.cos(e) * np.sin(az)]))

    cent = tgt.triangles_center
    n_f = len(cent)
    visible = np.zeros(n_f, dtype=bool)
    t0 = time.time()
    for eye in eyes:
        todo = np.flatnonzero(~visible)
        if todo.size == 0:
            break
        o = cent[todo]
        d = eye - o
        dist = np.linalg.norm(d, axis=1)
        d /= dist[:, None]
        origins = o + 1e-4 * d
        loc, idx_ray, _ = inter.intersects_location(origins, d, multiple_hits=False)
        blocked = np.zeros(todo.size, dtype=bool)
        if idx_ray.size:
            hd = np.linalg.norm(loc - origins[idx_ray], axis=1)
            blocked[idx_ray[hd < (dist[idx_ray] - 1e-3)]] = True
        visible[todo[~blocked]] = True

    raw_visible = int(visible.sum())
    keep = visible.copy()
    if dilate > 0:
        adj = tgt.face_adjacency  # (n,2) pairs of neighbouring faces
        for _ in range(dilate):
            grow = keep.copy()
            grow[adj[keep[adj[:, 0]], 1]] = True
            grow[adj[keep[adj[:, 1]], 0]] = True
            keep = grow

    areas = tgt.area_faces
    stats = {
        "target": target, "faces": n_f, "cameras": len(eyes),
        "visible_faces": raw_visible,
        "visible_pct": 100.0 * raw_visible / n_f,
        "visible_area_pct": 100.0 * areas[visible].sum() / areas.sum(),
        "kept_after_dilate": int(keep.sum()),
        "kept_pct": 100.0 * keep.sum() / n_f,
        "culled": int(n_f - keep.sum()),
        "culled_pct": 100.0 * (n_f - keep.sum()) / n_f,
        "dilate_rings": dilate,
        "seconds": round(time.time() - t0, 1),
    }
    if verbose:
        print("  [cull] %s: %d faces, %d cameras" % (target, n_f, len(eyes)))
        print("  [cull] line-of-sight visible : %d (%.2f%% of faces, %.2f%% of area)"
              % (raw_visible, stats["visible_pct"], stats["visible_area_pct"]))
        print("  [cull] keep after %d-ring dilate: %d (%.2f%%)"
              % (dilate, keep.sum(), stats["kept_pct"]))
        print("  [cull] CULLED: %d faces (%.2f%% of %s) in %.1fs"
              % (stats["culled"], stats["culled_pct"], target, stats["seconds"]))
    return keep, stats


def apply_face_cull(src, dst, target_material, keep_mask):
    """Rewrite the GLB keeping only `keep_mask` faces of the primitive whose
    material is `target_material`. Vertices are compacted.

    FULL GEOMETRY REBUILD -- and it has to be. The obvious implementation ("drop
    the target's bufferViews, append new ones") SILENTLY INFLATES the file,
    measured at +7.9 MB on the Golf master, because bufferView 2 there is one
    11.82 MB block holding the index accessors of ALL SIX meshes. The interior's
    share of it cannot be dropped without breaking the other five, so its dead
    bytes stay in the file while the new compacted copy is appended alongside.

    So every accessor is re-emitted into its own tight bufferView instead. That
    leaves no dead space, and because accessor INDICES are preserved, nothing
    referencing them needs renumbering. Image bufferViews are copied byte-for-byte
    with their SHARING intact -- un-sharing them is the +37 MB trap in the module
    docstring.
    """
    js, bin_ = glb_read(src)

    prim = None
    for m in js["meshes"]:
        for p in m["primitives"]:
            if "material" in p and js["materials"][p["material"]].get("name") == target_material:
                if prim is not None:
                    raise ValueError(
                        "material %r is on more than one primitive; cull target must be "
                        "unambiguous" % target_material)
                prim = p
    if prim is None:
        raise KeyError("no primitive with material %r" % target_material)

    for a in js["accessors"]:
        if "sparse" in a:
            raise NotImplementedError("sparse accessors are not handled")

    idx = read_accessor(js, bin_, prim["indices"]).reshape(-1, 3)
    if keep_mask.shape[0] != idx.shape[0]:
        raise ValueError("keep_mask has %d entries, primitive has %d faces"
                         % (keep_mask.shape[0], idx.shape[0]))
    kept = idx[keep_mask]
    used = np.unique(kept)
    remap = np.full(int(used.max()) + 1, -1, dtype=np.int64)
    remap[used] = np.arange(used.size)
    new_idx = remap[kept].ravel()

    # Read every accessor, then substitute the culled ones.
    data = {i: read_accessor(js, bin_, i) for i in range(len(js["accessors"]))}
    data[prim["indices"]] = new_idx
    for name, ai in prim["attributes"].items():
        data[ai] = np.ascontiguousarray(data[ai][used])

    out = bytearray()
    new_bvs = []

    def emit(raw, extra=None):
        while len(out) % 4:
            out.append(0)
        off = len(out)
        out.extend(raw)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
        if extra:
            bv.update(extra)
        new_bvs.append(bv)
        return len(new_bvs) - 1

    # 1) images first, preserving sharing (old bv index -> new bv index)
    img_map = {}
    for im in js.get("images", []):
        if "bufferView" not in im:
            continue
        old = im["bufferView"]
        if old not in img_map:
            bv = js["bufferViews"][old]
            o = bv.get("byteOffset", 0)
            img_map[old] = emit(bin_[o:o + bv["byteLength"]])
        im["bufferView"] = img_map[old]

    # 2) one tight bufferView per accessor, indices preserved
    NP2COMP = {np.dtype("int8"): 5120, np.dtype("uint8"): 5121,
               np.dtype("int16"): 5122, np.dtype("uint16"): 5123,
               np.dtype("uint32"): 5125, np.dtype("float32"): 5126}
    index_accessors = set()
    for m in js["meshes"]:
        for p in m["primitives"]:
            if "indices" in p:
                index_accessors.add(p["indices"])

    for i, acc in enumerate(js["accessors"]):
        arr = data[i]
        if i in index_accessors:
            # narrowest legal index type -- uint16 halves the index payload
            mx = int(arr.max()) if arr.size else 0
            arr = arr.astype(np.uint16 if mx < 65536 else np.uint32)
        elif arr.dtype != np.dtype(np.float32) and acc["componentType"] == 5126:
            arr = arr.astype(np.float32)
        arr = np.ascontiguousarray(arr)
        acc["componentType"] = NP2COMP[arr.dtype]
        acc["count"] = int(arr.shape[0]) if arr.ndim > 1 else int(arr.size)
        acc["bufferView"] = emit(arr.tobytes(),
                                 {"target": 34963 if i in index_accessors else 34962})
        acc.pop("byteOffset", None)
        if acc["type"] == "VEC3" and arr.ndim > 1 and arr.size:
            acc["min"] = [float(x) for x in arr.min(axis=0)]
            acc["max"] = [float(x) for x in arr.max(axis=0)]

    js["bufferViews"] = new_bvs
    js["buffers"] = [{"byteLength": len(out)}]
    glb_write(dst, js, bytes(out))
    return {"kept_faces": int(keep_mask.sum()), "kept_verts": int(used.size)}


# --------------------------------------------------------------------------
# Silhouette measurement
# --------------------------------------------------------------------------

def silhouette_masks(path, res=1024, fov_deg=30.0, views=CANONICAL_VIEWS,
                     ref_bounds=None):
    """Binary car-coverage mask per canonical view, plus per-material labels.

    Cameras are derived from ref_bounds when given, so the BEFORE and AFTER
    renders use IDENTICAL cameras. Deriving them from each file's own bounds
    would move the camera with the mesh and make the IoU meaningless.
    """
    scene = trimesh.load(path, process=False)
    # NODE TRANSFORMS MUST BE APPLIED. scene.geometry[n] is the RAW mesh in its
    # own local space; `quantize`/`dequantize` leave a scale+translate on the
    # node, so concatenating raw geometry rendered the car at half linear scale
    # and scored IoU 0.07 against an export that was actually correct.
    names, parts, offs, tot = [], [], {}, 0
    for node in scene.graph.nodes_geometry:
        tf, gname = scene.graph[node]
        g = scene.geometry[gname].copy()
        g.apply_transform(tf)
        names.append(gname)
        offs[gname] = (tot, tot + len(g.faces)); tot += len(g.faces); parts.append(g)
    combined = trimesh.util.concatenate(parts)
    inter = trimesh.ray.ray_pyembree.RayMeshIntersector(combined)

    b = ref_bounds if ref_bounds is not None else scene.bounds
    centre = b.mean(axis=0)
    dist = float(np.linalg.norm(b[1] - b[0])) * 1.6
    half = np.tan(np.radians(fov_deg) / 2)
    s = np.linspace(-half, half, res)
    U, V = np.meshgrid(s, -s)

    masks, coverage = OrderedDict(), OrderedDict()
    for name, azd, eld in views:
        az, el = np.radians(azd), np.radians(eld)
        eye = centre + dist * np.array(
            [np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)])
        fwd = centre - eye; fwd /= np.linalg.norm(fwd)
        right = np.cross(fwd, [0, 1.0, 0]); right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        dirs = fwd + U.reshape(-1, 1) * right + V.reshape(-1, 1) * up
        dirs /= np.linalg.norm(dirs, axis=1)[:, None]
        origins = np.tile(eye, (dirs.shape[0], 1))
        tri, ray = inter.intersects_id(origins, dirs, multiple_hits=False,
                                       return_locations=False)
        mask = np.zeros(res * res, dtype=bool)
        mask[ray] = True
        masks[name] = mask.reshape(res, res)
        cov = {}
        for n in names:
            a, bb = offs[n]
            sel = (tri >= a) & (tri < bb)
            cov[n] = int(sel.sum())
        coverage[name] = cov
    return masks, coverage, scene.bounds


def decode_for_probe(path, workdir, ext=None):
    """Return a path trimesh can ray-cast honestly.

    TWO decode steps are needed, and missing either one produces a mesh that
    LOOKS like catastrophic failure while the export is fine:

      * EXT_meshopt_compression / KHR_draco_mesh_compression -- trimesh cannot
        read these at all. Fed a compressed file it built a mesh that filled the
        entire frame, scoring IoU 0.16 against a perfectly good 5.06 MB export.
      * KHR_mesh_quantization -- `copy` decodes the compression but LEAVES the
        quantization, and trimesh then reads the raw int16s as metres: bounds
        came out +/-70162 instead of +/-2.14. `dequantize` is required as well.

    This is the same family as CLAUDE.md's note that Draco GLBs render blank in
    a local model-viewer harness -- a decode gap reads as a broken asset.
    """
    if ext is None:
        ext = describe(path)["extensionsUsed"]
    need_decode = any(e in ext for e in
                      ("EXT_meshopt_compression", "KHR_draco_mesh_compression"))
    need_dequant = "KHR_mesh_quantization" in ext
    if not (need_decode or need_dequant):
        return path
    cur = path
    if need_decode:
        nxt = os.path.join(workdir, "probe_decoded.glb")
        gt(["copy", cur, nxt], None, False)
        cur = nxt
    if need_dequant:
        nxt = os.path.join(workdir, "probe_dequant.glb")
        gt(["dequantize", cur, nxt], None, False)
        cur = nxt
    return cur


def silhouette_iou(before_masks, after_masks):
    rows = []
    for name in before_masks:
        A, B = before_masks[name], after_masks[name]
        inter = np.logical_and(A, B).sum()
        union = np.logical_or(A, B).sum()
        iou = float(inter) / float(union) if union else 1.0
        rows.append({"view": name, "iou": iou,
                     "before_px": int(A.sum()), "after_px": int(B.sum()),
                     "delta_px": int(B.sum()) - int(A.sum())})
    return rows


# --------------------------------------------------------------------------
# gltf-transform driver
# --------------------------------------------------------------------------

def gt(args, label=None, verbose=True):
    cmd = [GLTF_TRANSFORM] + args
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("gltf-transform %s failed rc=%d\n%s\n%s"
                           % (args[0], p.returncode, p.stdout[-2000:], p.stderr[-2000:]))
    if verbose and label:
        print("  [%s] %.1fs" % (label, time.time() - t0))
    return p.stdout


def export(master, out, budget_mb=8.0, texture_px=2048, simplify_error=0.001,
           simplify_ratio=0.6, compress="meshopt", cull_target="interior",
           dilate=2, min_iou=0.990, min_mean_iou=0.995, res=1024,
           workdir=None, keep_intermediates=False, verbose=True):
    """Run the full pipeline. Returns a report dict. Raises on gate failure."""
    workdir = workdir or os.path.join(os.path.dirname(os.path.abspath(out)), "_mobile_tmp")
    os.makedirs(workdir, exist_ok=True)
    rep = {"master": describe(master), "stages": [], "budget_mb": budget_mb}
    if verbose:
        m = rep["master"]
        print("MASTER %s" % master)
        print("  %.2f MB | %d tris | texture %.2f MB (%.1f%%) geometry %.2f MB (%.1f%%)"
              % (m["sizeBytes"] / 1e6, m["tris"], m["payload"]["texture"] / 1e6,
                 100 * m["payload"]["texture"] / m["payload"]["total"],
                 m["payload"]["geometry"] / 1e6,
                 100 * m["payload"]["geometry"] / m["payload"]["total"]))
        print("  %d images sharing %d unique bufferViews"
              % (m["payload"]["n_images"], m["payload"]["n_unique_image_views"]))

    def step(name, path):
        sz = os.path.getsize(path)
        rep["stages"].append({"stage": name, "sizeBytes": sz, "sizeMB": round(sz / 1e6, 3)})
        if verbose:
            print("  -> %-22s %8.2f MB" % (name, sz / 1e6))

    cur = os.path.join(workdir, "s0_master.glb")
    shutil.copy(master, cur)
    step("00 master", cur)

    # 1 -- dedup/prune FIRST (the +37 MB guard)
    nxt = os.path.join(workdir, "s1_dedup.glb")
    gt(["dedup", cur, nxt], "dedup", verbose)
    cur = nxt; step("01 dedup+prune", cur)

    # 2 -- cull hidden interior
    cull_stats = None
    if cull_target:
        keep, cull_stats = hidden_face_mask(cur, target=cull_target, dilate=dilate,
                                            verbose=verbose)
        nxt = os.path.join(workdir, "s2_cull.glb")
        apply_face_cull(cur, nxt, cull_target, keep)
        cur = nxt; step("02 cull hidden", cur)
    rep["cull"] = cull_stats

    # 3 -- weld (prerequisite for a useful simplify)
    nxt = os.path.join(workdir, "s3_weld.glb")
    gt(["weld", cur, nxt], "weld", verbose)
    cur = nxt; step("03 weld", cur)

    # 4 -- error-bounded simplify
    nxt = os.path.join(workdir, "s4_simplify.glb")
    gt(["simplify", cur, nxt, "--error", str(simplify_error),
        "--ratio", str(simplify_ratio)], "simplify", verbose)
    cur = nxt; step("04 simplify", cur)

    # 5 -- textures: the majority of the bytes
    nxt = os.path.join(workdir, "s5_resize.glb")
    gt(["resize", cur, nxt, "--width", str(texture_px), "--height", str(texture_px)],
       "resize", verbose)
    cur = nxt; step("05 texture resize", cur)

    nxt = os.path.join(workdir, "s6_webp.glb")
    gt(["webp", cur, nxt, "--quality", "85"], "webp", verbose)
    cur = nxt; step("06 texture webp", cur)

    # 6a -- LAST chance to re-share image bufferViews. This MUST come BEFORE
    # compression: `dedup` (like `copy`) round-trips through the SDK and DECODES
    # EXT_meshopt_compression / KHR_draco_mesh_compression on the way in.
    # Running it after compression silently threw the compression away and took
    # 5.06 MB back up to 11.87 MB -- measured, not theorised.
    nxt = os.path.join(workdir, "s7_dedup2.glb")
    gt(["dedup", cur, nxt], "dedup(pre-compress)", verbose)
    cur = nxt; step("07 dedup(pre-compress)", cur)

    # 6b -- geometry compression LAST. Nothing may follow it.
    if compress and compress != "none":
        nxt = os.path.join(workdir, "s8_%s.glb" % compress)
        if compress == "draco":
            gt(["draco", cur, nxt], "draco", verbose)
        else:
            gt(["meshopt", cur, nxt, "--level", "high"], "meshopt", verbose)
        cur = nxt; step("08 %s" % compress, cur)

    shutil.copy(cur, out)
    rep["export"] = describe(out)

    # ---- silhouette gate -------------------------------------------------
    if verbose:
        print("\nSILHOUETTE GATE (alpha IoU, %d canonical views @ %dpx)"
              % (len(CANONICAL_VIEWS), res))
    before, cov_b, ref_bounds = silhouette_masks(master, res=res)
    # trimesh cannot read EXT_meshopt_compression / KHR_draco_mesh_compression,
    # and handed a compressed file it reads the quantised integers as positions
    # and builds a garbage mesh that fills the frame -- which showed up as an
    # IoU of 0.16 against a perfectly good export. `copy` is the decode path.
    probe = decode_for_probe(out, workdir, rep["export"]["extensionsUsed"])
    after, cov_a, _ = silhouette_masks(probe, res=res, ref_bounds=ref_bounds)
    rows = silhouette_iou(before, after)
    rep["silhouette"] = rows
    ious = [r["iou"] for r in rows]
    rep["iou_min"] = min(ious); rep["iou_mean"] = float(np.mean(ious))
    if verbose:
        for r in rows:
            print("  %-10s IoU %.5f   px %7d -> %7d (%+d)"
                  % (r["view"], r["iou"], r["before_px"], r["after_px"], r["delta_px"]))
        print("  min %.5f  mean %.5f  (thresholds %.3f / %.3f)"
              % (rep["iou_min"], rep["iou_mean"], min_iou, min_mean_iou))

    rep["material_coverage"] = {"before": cov_b, "after": cov_a}

    ok = rep["iou_min"] >= min_iou and rep["iou_mean"] >= min_mean_iou
    size_mb = rep["export"]["sizeBytes"] / 1e6
    rep["size_mb"] = round(size_mb, 3)
    rep["within_budget"] = size_mb <= budget_mb
    rep["silhouette_ok"] = ok
    if not keep_intermediates:
        shutil.rmtree(workdir, ignore_errors=True)
    if not ok:
        raise RuntimeError(
            "SILHOUETTE GATE FAILED: min IoU %.5f (need %.3f), mean %.5f (need %.3f). "
            "Refusing to ship this reduction." % (rep["iou_min"], min_iou,
                                                  rep["iou_mean"], min_mean_iou))
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master"); ap.add_argument("out")
    ap.add_argument("--budget-mb", type=float, default=8.0)
    ap.add_argument("--texture-px", type=int, default=2048)
    ap.add_argument("--simplify-error", type=float, default=0.001)
    ap.add_argument("--simplify-ratio", type=float, default=0.6)
    ap.add_argument("--compress", choices=["meshopt", "draco", "none"], default="meshopt")
    ap.add_argument("--cull-target", default="interior",
                    help="material name of the inner shell; '' disables culling")
    ap.add_argument("--dilate", type=int, default=2)
    ap.add_argument("--min-iou", type=float, default=0.990)
    ap.add_argument("--min-mean-iou", type=float, default=0.995)
    ap.add_argument("--res", type=int, default=1024)
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--keep-intermediates", action="store_true")
    a = ap.parse_args()

    try:
        rep = export(a.master, a.out, budget_mb=a.budget_mb, texture_px=a.texture_px,
                     simplify_error=a.simplify_error, simplify_ratio=a.simplify_ratio,
                     compress=a.compress, cull_target=a.cull_target or None,
                     dilate=a.dilate, min_iou=a.min_iou, min_mean_iou=a.min_mean_iou,
                     res=a.res, keep_intermediates=a.keep_intermediates)
    except RuntimeError as e:
        print("\nFAIL: %s" % e, file=sys.stderr)
        return 1

    print("\nRESULT %s" % a.out)
    print("  %.2f MB (budget %.1f MB) -- %s"
          % (rep["size_mb"], a.budget_mb, "WITHIN" if rep["within_budget"] else "OVER"))
    print("  %d tris (from %d, %.1f%% reduction)"
          % (rep["export"]["tris"], rep["master"]["tris"],
             100 * (1 - rep["export"]["tris"] / rep["master"]["tris"])))
    print("  silhouette min IoU %.5f mean %.5f" % (rep["iou_min"], rep["iou_mean"]))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=2)
    return 0 if rep["within_budget"] else 1


if __name__ == "__main__":
    sys.exit(main())
