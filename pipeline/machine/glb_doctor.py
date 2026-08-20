#!/usr/bin/env python3
"""glb_doctor.py — baseline audit and size repair for a FINISHED car GLB.

Two jobs, one file, because they share the same measurements:

  audit  — everything a QA manifest needs about a shipped GLB, measured from
           the file rather than from the pipeline that claims to have made it.
  slim   — cut a finished car under the Supabase object cap without touching
           the silhouette, and say in numbers what was removed.

WHY THIS EXISTS AT ALL. CLAUDE.md's standing rule is that a gate nobody ran
against inputs it must catch AND must not is a gate that does not exist, and
that the render is the verdict while every number is a candidate finder. The
machine chain (canon -> seg_* -> surface_clean -> seg_assemble -> shut_lines)
reports what each STAGE did; nothing until now read the finished artefact back
and asked whether the claims survived export. Three defects found on the first
car it was pointed at were all invisible to the stages that made them:

  * THE FILE IS 57% TEXTURE, NOT GEOMETRY. golf_final.glb is 65.1 MB: 27.8 MB
    of geometry and 37.3 MB of two 4096x4096 PNGs. Every conversation about
    that car's size had been about its 985k triangles. Deleting the entire
    660k-face interior would still have left a 49 MB file, i.e. still over the
    ~25 MB bucket cap (measured: HTTP 400 wrapping 413 EntityTooLarge). Read
    the byte budget before optimising the thing you assume is big.

  * DRACO MADE IT WORSE, 65 -> 78 MB, rc=0. Not a fluke and not a bug in
    Draco: the file's two images are each referenced by TWO glTF `images`
    entries pointing at ONE bufferView, so the PNGs are stored once. A
    round-trip through gltf-transform gives each image its own bufferView and
    the 37.3 MB of texture becomes 74.7 MB, which swamps the ~24 MB Draco
    saves on geometry. `dedupe` before `draco`, and always re-measure: a
    compressor that returns rc=0 has not promised you a smaller file.

  * TWO MATERIALS SHARED ONE ATLAS. `carpaint` and `Rim_Alloy` both sample
    image 0/1 — the alloys are textured with the body's baked albedo. That is
    a real material defect and it is only visible in the JSON, because the
    rims render a plausible dark grey either way.

WHAT THE AUDIT DELIBERATELY WILL NOT DO. It reports non-manifold edges,
flipped windings, degenerate and duplicate faces, loose parts and unreferenced
materials as COUNTS with context, never as a pass/fail. A generated car is an
isosurface: it is normal for it to carry open boundaries where the shell was
cut into material parts, and "non-manifold edge count > 0" on such a mesh is
a property of the pipeline, not a defect. Numbers here exist to be looked at
next to a render.

Self-intersection is reported NOT TESTED. There is no honest cheap test for it
here and inventing one is worse than the gap: a metric that confidently says
"all clear" is worse than no metric (CLAUDE.md, on the tyre-darkness probe
that returned 0 suspects for every car because it was measuring the backdrop).

Run:
  python3 glb_doctor.py audit <car.glb> [--json qc_manifest.json]
  python3 glb_doctor.py slim  <car.glb> <out.glb> [--target-mb 25]
                              [--tex-size 2048] [--tex-quality 92]
                              [--keep-hidden] [--report slim.json]
"""
import argparse
import hashlib
import io
import json
import os
import struct
import sys

import numpy as np

# trimesh is imported lazily by the geometry pass: the JSON pass must work on a
# file trimesh cannot open (Draco), and reporting "not readable" is useful.

# Reuse the wave probe's rules rather than restating them. Two independent
# implementations of the glazing verdict drift, and then they disagree about
# the same car -- glass_probe.py's own docstring makes that point about the
# retro audit. Path juggling because this file lives in machine/ and the probe
# in ingest/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "ingest"))


# --------------------------------------------------------------------------
# glTF container level: what the FILE says, before any library normalises it.
# --------------------------------------------------------------------------

def read_glb(path):
    """Return (gltf_json, bin_chunk_bytes). Raises on a non-GLB."""
    with open(path, "rb") as f:
        hdr = f.read(12)
        if hdr[:4] != b"glTF":
            raise SystemExit(f"REFUSED: {path} is not a binary glTF")
        jlen = struct.unpack("<I", f.read(4)[:4])[0]
        ctype = f.read(4)
        if ctype != b"JSON":
            raise SystemExit("REFUSED: first chunk is not JSON")
        g = json.loads(f.read(jlen).decode("utf-8", "replace"))
        binc = b""
        tail = f.read(8)
        if len(tail) == 8:
            blen = struct.unpack("<I", tail[:4])[0]
            binc = f.read(blen)
    return g, binc


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def byte_budget(g, binc):
    """Where the bytes actually are, counting SHARED bufferViews once.

    The naive sum over images double-counts a shared view and reports more
    bytes than the file contains -- that discrepancy is exactly what exposed
    the shared-atlas defect, so it is reported rather than silently fixed.
    """
    bv = g.get("bufferViews") or []
    acc = g.get("accessors") or []
    charged = set()          # bufferView indices already counted
    out = {"images": {}, "meshes": {}, "image_bytes_unique": 0,
           "image_bytes_naive": 0, "geometry_bytes": 0}

    for i, im in enumerate(g.get("images") or []):
        idx = im.get("bufferView")
        n = bv[idx]["byteLength"] if idx is not None else 0
        out["images"][i] = {"bufferView": idx, "bytes": n,
                            "mimeType": im.get("mimeType"),
                            "uri": im.get("uri")}
        out["image_bytes_naive"] += n
        if idx is not None and idx not in charged:
            charged.add(idx)
            out["image_bytes_unique"] += n

    for i, m in enumerate(g.get("meshes") or []):
        tot = 0
        for pr in m["primitives"]:
            refs = list(pr.get("attributes", {}).values())
            if "indices" in pr:
                refs.append(pr["indices"])
            for a in refs:
                idx = acc[a].get("bufferView")
                if idx is None:
                    continue
                n = bv[idx]["byteLength"]
                tot += n                       # per-mesh charge, may overlap
                if idx not in charged:
                    charged.add(idx)
                    out["geometry_bytes"] += n
        out["meshes"][m.get("name") or f"mesh{i}"] = tot

    out["shared_image_bufferviews"] = (
        out["image_bytes_naive"] != out["image_bytes_unique"])
    return out


def texture_inventory(g, binc):
    """Decode every image header. Records DUPLICATES by bufferView identity."""
    from PIL import Image
    bv = g.get("bufferViews") or []
    inv, by_view = [], {}
    for i, im in enumerate(g.get("images") or []):
        rec = {"index": i, "name": im.get("name"),
               "mimeType": im.get("mimeType"), "bufferView": im.get("bufferView")}
        idx = im.get("bufferView")
        if idx is None:
            rec["note"] = "external uri, not embedded"
            inv.append(rec)
            continue
        v = bv[idx]
        o = v.get("byteOffset", 0)
        data = binc[o:o + v["byteLength"]]
        rec["bytes"] = len(data)
        try:
            img = Image.open(io.BytesIO(data))
            rec["size"] = list(img.size)
            rec["mode"] = img.mode
            rec["format"] = img.format
        except Exception as exc:                       # noqa: BLE001
            rec["decode_error"] = str(exc)
        rec["duplicate_of"] = by_view.get(idx)
        by_view.setdefault(idx, i)
        inv.append(rec)
    return inv


def material_report(g):
    """Materials as the FILE states them, plus which meshes actually use each.

    An unreferenced material is dead weight in a validator report and a sign
    the assemble stage wrote a name it then never bound to geometry.
    """
    mats = g.get("materials") or []
    used = {}
    for m in g.get("meshes") or []:
        for pr in m["primitives"]:
            if "material" in pr:
                used.setdefault(pr["material"], []).append(m.get("name"))
    out = []
    for i, m in enumerate(mats):
        pbr = m.get("pbrMetallicRoughness") or {}
        ext = m.get("extensions") or {}
        sg = ext.get("KHR_materials_pbrSpecularGlossiness") or {}
        bcf = pbr.get("baseColorFactor") or sg.get("diffuseFactor") or [1, 1, 1, 1]
        out.append({
            "index": i, "name": m.get("name"),
            "alphaMode": m.get("alphaMode", "OPAQUE"),
            "doubleSided": bool(m.get("doubleSided")),
            "baseColorFactor": [round(x, 4) for x in bcf],
            "metallicFactor": pbr.get("metallicFactor", 1.0),
            "roughnessFactor": pbr.get("roughnessFactor", 1.0),
            "baseColorTexture": (pbr.get("baseColorTexture") or {}).get("index"),
            "metallicRoughnessTexture":
                (pbr.get("metallicRoughnessTexture") or {}).get("index"),
            "extensions": sorted(ext.keys()),
            "used_by": used.get(i, []),
            "unreferenced": i not in used,
        })
    return out


def node_report(g):
    """Hierarchy + unapplied transforms.

    A non-identity node matrix on an exported car is not automatically wrong,
    but it decides whether a consumer that ignores the scene graph (several do
    for single-mesh imports) shows the car in the right place, so it is a
    baseline fact worth recording rather than discovering later.
    """
    nodes = g.get("nodes") or []
    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    out = []
    for i, n in enumerate(nodes):
        trs = {k: n[k] for k in ("translation", "rotation", "scale") if k in n}
        mat = n.get("matrix")
        nonid = bool(trs) or (mat is not None and
                              any(abs(a - b) > 1e-9 for a, b in zip(mat, ident)))
        out.append({"index": i, "name": n.get("name"), "mesh": n.get("mesh"),
                    "children": n.get("children", []), "trs": trs,
                    "matrix": mat, "non_identity_transform": nonid})
    return out


# --------------------------------------------------------------------------
# Geometry level: topology facts, measured with process=False.
# --------------------------------------------------------------------------

def topo(mesh):
    """Topology counts for one part.

    process=False at load time is mandatory for this to mean anything: trimesh
    merges coincident vertices on load by default, which silently repairs the
    exact duplicate-vertex and non-manifold defects the audit is asked to
    count. An audit that runs after an implicit repair reports the repair.
    """
    V, F = mesh.vertices, mesh.faces
    rec = {"vertices": int(len(V)), "faces": int(len(F))}

    # degenerate: a face naming the same vertex twice, or with ~zero area.
    same = (F[:, 0] == F[:, 1]) | (F[:, 1] == F[:, 2]) | (F[:, 0] == F[:, 2])
    area = mesh.area_faces
    rec["faces_degenerate_index"] = int(same.sum())
    rec["faces_zero_area"] = int((area <= 1e-14).sum())
    rec["area_m2"] = float(area.sum())

    # duplicate faces: identical vertex TRIPLE regardless of winding.
    key = np.sort(F, axis=1)
    _, first, counts = np.unique(key, axis=0, return_index=True,
                                 return_counts=True)
    rec["faces_duplicate"] = int((counts - 1).sum())

    # edge manifoldness: count undirected edges by how many faces use them.
    e = np.sort(F[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
    _, ecounts = np.unique(e, axis=0, return_counts=True)
    rec["edges_total"] = int(len(ecounts))
    rec["edges_boundary"] = int((ecounts == 1).sum())      # open border
    rec["edges_manifold"] = int((ecounts == 2).sum())
    rec["edges_nonmanifold"] = int((ecounts > 2).sum())    # 3+ faces on one edge

    # winding consistency: on a consistently wound surface every interior edge
    # is traversed once in each direction. A DIRECTED edge seen twice means the
    # two faces sharing it disagree -- that is a flipped normal, and it is the
    # only test here that does not depend on a normal vector actually being
    # stored in the file.
    d = F[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    _, dcounts = np.unique(d, axis=0, return_counts=True)
    rec["edges_winding_conflict"] = int((dcounts > 1).sum())

    # coincident vertices that were never welded.
    try:
        from scipy.spatial import cKDTree
        pairs = cKDTree(V).query_pairs(1e-6, output_type="ndarray")
        rec["vertices_coincident_pairs"] = int(len(pairs))
    except Exception:                                       # noqa: BLE001
        rec["vertices_coincident_pairs"] = None

    rec["bounds"] = [[float(x) for x in mesh.bounds[0]],
                     [float(x) for x in mesh.bounds[1]]]
    rec["volume_m3"] = float(mesh.volume)
    rec["watertight"] = bool(mesh.is_watertight)
    rec["has_normals"] = bool(getattr(mesh, "vertex_normals", None) is not None
                              and len(mesh.vertex_normals) == len(V))
    uv = getattr(mesh.visual, "uv", None)
    rec["has_uv"] = uv is not None and len(uv) == len(V)
    if rec["has_uv"]:
        u = np.asarray(uv)
        rec["uv_range"] = [float(u.min()), float(u.max())]
        rec["uv_outside_01"] = int(((u < -1e-6) | (u > 1 + 1e-6)).any(axis=1).sum())
    return rec


def loose_parts(mesh, cap=16):
    """Connected-component sizes, largest first.

    Uses face-adjacency LABELS, never mesh.split(). split() materialises one
    Trimesh per component and this car's `carpaint` part has 12,302 of them --
    the first version of this function was OOM-killed (rc 137) on a 12 GB box
    for exactly that reason. The label form costs 0.3 s and no memory, and the
    thing being reported is a count, not a set of meshes.

    Capped list because a noisy generated part carries thousands of specks and
    the list is for the eye. The COUNT is always exact.
    """
    try:
        from trimesh.graph import connected_components
        cc = connected_components(mesh.face_adjacency,
                                  nodes=np.arange(len(mesh.faces)))
    except Exception:                                       # noqa: BLE001
        return {"count": None, "sizes": []}
    sizes = sorted((int(len(c)) for c in cc), reverse=True)
    return {"count": len(sizes), "sizes": sizes[:cap],
            "faces_outside_largest": int(sum(sizes[1:])),
            "components_under_10_faces": int(sum(1 for s in sizes if s < 10))}


def wheel_geometry(scene, tyre_key="tyre"):
    """Wheelbase and track measured from the TYRE mesh's own components.

    Derived from geometry, never from a spec sheet: CLAUDE.md's accuracy rule
    forbids asserting a dimension the asset does not state. If the tyre mesh
    does not split into four components this returns what it found and says so,
    rather than guessing which blob is which corner.
    """
    import trimesh
    name = next((n for n in scene.geometry if tyre_key in n.lower()), None)
    if name is None:
        return {"status": "no tyre mesh found"}
    comps = scene.geometry[name].split(only_watertight=False)
    comps = [c for c in comps if len(c.faces) > 200]
    out = {"tyre_mesh": name, "components": len(comps), "wheels": []}
    if not comps:
        return out
    # Length is on X and width on Z after canon.py; up is Y. Assert that from
    # the scene bbox rather than assuming, because a Y-up assumption once
    # rendered a Y-down glb upside down (CLAUDE.md, evidence rule).
    lo, hi = scene.bounds
    ext = hi - lo
    out["axis_note"] = (f"extents X={ext[0]:.3f} Y={ext[1]:.3f} Z={ext[2]:.3f}; "
                        "length assumed = longest, up = shortest-of-remaining")
    for c in comps:
        ctr = c.bounds.mean(axis=0)
        e = c.extents
        out["wheels"].append({
            "centre": [round(float(x), 4) for x in ctr],
            "extents": [round(float(x), 4) for x in e],
            "diameter_m": round(float(max(e[0], e[1])), 4),
            "width_m": round(float(e[2]), 4),
            "faces": int(len(c.faces))})
    if len(comps) == 4:
        cs = np.array([w["centre"] for w in out["wheels"]])
        front = cs[cs[:, 0] > cs[:, 0].mean()]
        rear = cs[cs[:, 0] <= cs[:, 0].mean()]
        out["wheelbase_m"] = round(float(abs(front[:, 0].mean()
                                             - rear[:, 0].mean())), 4)
        out["track_front_m"] = round(float(abs(np.diff(np.sort(front[:, 2]))[0])), 4)
        out["track_rear_m"] = round(float(abs(np.diff(np.sort(rear[:, 2]))[0])), 4)
        out["hub_symmetry_mm"] = round(float(
            abs(abs(front[:, 2]).max() - abs(front[:, 2]).min()) * 1000), 2)
        gy = float(min(w["centre"][1] - w["extents"][1] / 2
                       for w in out["wheels"]))
        out["lowest_tyre_point_m"] = round(gy, 5)
        out["ground_error_mm"] = round(gy * 1000, 2)
    return out


# --------------------------------------------------------------------------
# Glazing / flat-shell verdict, from the local file.
# --------------------------------------------------------------------------

def glazing_verdict(g):
    """Run glass_probe's classifier against an in-memory glTF dict.

    glass_probe.probe() fetches by URL because it was written for the wave. Its
    RULES are the asset here, so they are called through a shim that hands it
    the JSON we already have rather than re-implementing the bands.
    """
    try:
        import glass_probe as gp
    except Exception as exc:                                # noqa: BLE001
        return {"status": f"glass_probe unavailable: {exc}"}
    orig = gp.gltf_json
    gp.gltf_json = lambda url: g
    try:
        return gp.probe("local", url="local://audit")
    finally:
        gp.gltf_json = orig


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------

def audit(path, out_json=None):
    g, binc = read_glb(path)
    man = {
        "file": os.path.abspath(path),
        "bytes": os.path.getsize(path),
        "sha256": sha256(path),
        "asset": g.get("asset"),
        "extensionsUsed": g.get("extensionsUsed", []),
        "extensionsRequired": g.get("extensionsRequired", []),
        "counts": {
            "nodes": len(g.get("nodes") or []),
            "meshes": len(g.get("meshes") or []),
            "materials": len(g.get("materials") or []),
            "textures": len(g.get("textures") or []),
            "images": len(g.get("images") or []),
            "animations": len(g.get("animations") or []),
            "skins": len(g.get("skins") or []),
            "cameras": len(g.get("cameras") or []),
        },
        "byte_budget": byte_budget(g, binc),
        "textures": texture_inventory(g, binc),
        "materials": material_report(g),
        "nodes": node_report(g),
        "glazing": glazing_verdict(g),
        "self_intersection": "NOT TESTED — no honest cheap test available here",
    }

    import trimesh
    # process=False: see topo()'s note. This is load-bearing, not a speed knob.
    sc = trimesh.load(path, force="scene", process=False)
    man["scene_bounds"] = [[float(x) for x in sc.bounds[0]],
                           [float(x) for x in sc.bounds[1]]]
    man["dimensions_m"] = {"x": round(float(sc.extents[0]), 4),
                           "y": round(float(sc.extents[1]), 4),
                           "z": round(float(sc.extents[2]), 4)}
    parts, tot_f = {}, 0
    for name, gm in sc.geometry.items():
        rec = topo(gm)
        rec["loose_parts"] = loose_parts(gm)
        parts[name] = rec
        tot_f += rec["faces"]
    man["parts"] = parts
    man["faces_total"] = tot_f
    man["material_share_pct"] = {n: round(100.0 * p["faces"] / tot_f, 2)
                                 for n, p in parts.items()}
    man["wheels"] = wheel_geometry(sc)

    if out_json:
        with open(out_json, "w") as f:
            json.dump(man, f, indent=1)
    return man


def print_audit(man):
    bb = man["byte_budget"]
    print(f"FILE {man['file']}")
    print(f"  {man['bytes']/1e6:.2f} MB   sha256 {man['sha256'][:16]}…")
    print(f"  generator: {(man['asset'] or {}).get('generator')}")
    print(f"  extensionsUsed: {man['extensionsUsed'] or 'none'}")
    print(f"  counts: {man['counts']}")
    print(f"  dimensions (m): {man['dimensions_m']}")
    print("BYTE BUDGET")
    print(f"  geometry      {bb['geometry_bytes']/1e6:8.2f} MB")
    print(f"  images unique {bb['image_bytes_unique']/1e6:8.2f} MB"
          f"   (naive sum {bb['image_bytes_naive']/1e6:.2f} MB"
          f"{'  <-- SHARED bufferViews' if bb['shared_image_bufferviews'] else ''})")
    print("TEXTURES")
    for t in man["textures"]:
        dup = f"  DUPLICATE of image {t['duplicate_of']}" if t.get("duplicate_of") is not None else ""
        print(f"  [{t['index']}] {t.get('size')} {t.get('mode')} "
              f"{t.get('format')} {t.get('bytes', 0)/1e6:.2f} MB{dup}")
    print("MATERIALS")
    for m in man["materials"]:
        flag = "  UNREFERENCED" if m["unreferenced"] else ""
        print(f"  [{m['index']}] {m['name']:14s} {m['alphaMode']:7s} "
              f"a={m['baseColorFactor'][3]:.3f} metal={m['metallicFactor']} "
              f"rough={m['roughnessFactor']} tex={m['baseColorTexture']}"
              f"/{m['metallicRoughnessTexture']} used_by={m['used_by']}{flag}")
    print("PARTS")
    hdr = ("name", "verts", "faces", "share%", "nonmanif", "wind", "bound",
           "dupF", "degen", "loose", "uv")
    print("  " + "".join(f"{h:>10s}" for h in hdr))
    for n, p in man["parts"].items():
        print("  " + "".join(f"{v:>10}" for v in (
            n[:10], p["vertices"], p["faces"],
            man["material_share_pct"][n], p["edges_nonmanifold"],
            p["edges_winding_conflict"], p["edges_boundary"],
            p["faces_duplicate"], p["faces_degenerate_index"] + p["faces_zero_area"],
            p["loose_parts"]["count"], "y" if p["has_uv"] else "-")))
    print(f"  TOTAL faces {man['faces_total']}")
    print("WHEELS")
    print("  " + json.dumps(man["wheels"])[:900])
    print("GLAZING")
    gl = man["glazing"]
    print("  " + json.dumps({k: gl[k] for k in
                             ("verdict", "certainty", "reason", "flat_shell",
                              "alpha_shell")
                             if k in gl})[:700])
    print("SELF-INTERSECTION: " + man["self_intersection"])


# --------------------------------------------------------------------------
# slim
# --------------------------------------------------------------------------

def hidden_faces(scene, target_name, samples=64, seed=0, glass_key="glass"):
    """Boolean mask over target_name's faces: True where the face can NEVER be
    seen from outside the car.

    THE DEFINITION MATTERS MORE THAN THE CODE. "Unseen" is not "inside the
    bounding box" and it is not "facing away from the camera" -- a generated
    car is a closed shell with thickness, so its inner skin faces the cabin
    void, and part of that void IS visible: through the windscreen you see the
    inner roof, the floor and the parcel shelf, and the owner's rulings make
    glazing a hard-fail item precisely because a customer looks through it.

    So: a face is SEEN if a ray leaving its front side escapes to infinity
    passing through nothing solid. GLASS IS NOT AN OCCLUDER — it is excluded
    from the occluder set, which is what makes the cabin lining survive. A face
    is HIDDEN only if all `samples` directions are blocked, which errs towards
    keeping geometry: over-keeping costs bytes, over-deleting costs a hole in
    something a customer can see, and those are not symmetric.

    Rays start at the face centroid pushed 0.5 mm along the face normal, which
    is the standard self-hit guard; without it every ray hits its own face.
    """
    import trimesh
    tgt = scene.geometry[target_name]
    occ = trimesh.util.concatenate(
        [gm for n, gm in scene.geometry.items() if glass_key not in n.lower()])

    tri = tgt.triangles
    ctr = tri.mean(axis=1)
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, np.maximum(ln, 1e-20))

    # Stratified hemisphere directions (cosine-ish via a Fibonacci sphere,
    # rejected to the face's own hemisphere per-face). One shared direction set
    # keeps this deterministic, which matters because the result decides what
    # gets deleted and a run-to-run difference would be untraceable.
    rng = np.random.default_rng(seed)
    i = np.arange(samples) + 0.5
    phi = np.arccos(1 - 2 * i / samples)
    theta = np.pi * (1 + 5 ** 0.5) * i
    D = np.stack([np.cos(theta) * np.sin(phi),
                  np.sin(theta) * np.sin(phi),
                  np.cos(phi)], axis=1)
    D = (D + rng.normal(0, 0.02, D.shape))
    D /= np.linalg.norm(D, axis=1, keepdims=True)

    n = len(ctr)
    escaped = np.zeros(n, dtype=bool)
    origins = ctr + nrm * 5e-4
    for d in D:
        todo = ~escaped
        if not todo.any():
            break
        # Only cast in the face's own hemisphere; the opposite hemisphere is
        # behind the surface and a hit there says nothing about visibility.
        front = (nrm[todo] @ d) > 0.05
        idx = np.flatnonzero(todo)[front]
        if not len(idx):
            continue
        hit = occ.ray.intersects_any(
            ray_origins=origins[idx],
            ray_directions=np.tile(d, (len(idx), 1)))
        escaped[idx[~hit]] = True
    return ~escaped


def grow_mask(mesh, mask, rings=2):
    """Dilate a face mask by `rings` face-adjacency steps.

    The visibility test is a point sample at each centroid, so its boundary is
    ragged at exactly the places that matter -- the edge of a window aperture.
    Growing the KEEP set by two rings buys a margin at negligible cost. This is
    the same instinct as seg_boundary's stencil dilation and is here for the
    same reason: a ragged label boundary is visible and a slightly generous one
    is not.
    """
    keep = mask.copy()
    F = mesh.faces
    for _ in range(rings):
        vk = np.zeros(len(mesh.vertices), dtype=bool)
        vk[F[keep].ravel()] = True
        keep |= vk[F].any(axis=1)
    return keep


def recompress_images(g, binc, max_size, quality):
    """Re-encode embedded PNGs as JPEG, downscaling to max_size.

    Returns a NEW bin chunk and rewritten bufferViews. Deliberately keeps the
    shared-bufferView structure intact: two `images` entries may point at one
    view, and splitting them here would reintroduce the exact duplication that
    made Draco inflate this file.

    ALPHA IS CHECKED, NOT ASSUMED. JPEG cannot carry alpha, so an image whose
    alpha channel is actually used must not be converted. On the Golf the
    baseColor atlas is RGBA with 98 distinct alpha values -- and every material
    that samples it is alphaMode=OPAQUE, so glTF ignores that channel entirely
    and dropping it is free. Any file where a BLEND/MASK material samples the
    image keeps its PNG.
    """
    from PIL import Image
    bv = g["bufferViews"]
    alpha_needed = set()
    for m in g.get("materials") or []:
        if m.get("alphaMode", "OPAQUE") in ("BLEND", "MASK"):
            t = (m.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
            if t:
                src = (g["textures"][t["index"]].get("source"))
                if src is not None:
                    alpha_needed.add(g["images"][src]["bufferView"])

    replace, notes = {}, []
    for i, im in enumerate(g.get("images") or []):
        idx = im.get("bufferView")
        if idx is None or idx in replace:
            continue
        v = bv[idx]
        o = v.get("byteOffset", 0)
        data = binc[o:o + v["byteLength"]]
        try:
            img = Image.open(io.BytesIO(data))
        except Exception as exc:                            # noqa: BLE001
            notes.append(f"image {i}: undecodable, left alone ({exc})")
            continue
        w, h = img.size
        if max(w, h) > max_size:
            s = max_size / max(w, h)
            img = img.resize((max(1, int(w * s)), max(1, int(h * s))),
                             Image.LANCZOS)
        buf = io.BytesIO()
        if idx in alpha_needed:
            img.save(buf, "PNG", optimize=True)
            mime = "image/png"
            notes.append(f"image {i}: alpha is USED by a BLEND/MASK material,"
                         " kept as PNG")
        else:
            img.convert("RGB").save(buf, "JPEG", quality=quality,
                                    subsampling=0, optimize=True)
            mime = "image/jpeg"
        replace[idx] = (buf.getvalue(), mime)
        notes.append(f"image {i}: {w}x{h} -> {img.size[0]}x{img.size[1]}  "
                     f"{len(data)/1e6:.2f} -> {len(buf.getvalue())/1e6:.2f} MB")
    for im in g.get("images") or []:
        if im.get("bufferView") in replace:
            im["mimeType"] = replace[im["bufferView"]][1]
    return replace, notes


def rebuild_glb(g, binc, replace, out_path):
    """Write a GLB, repacking the bin chunk so replaced views take their new
    size. Every bufferView offset is recomputed; nothing is patched in place.
    """
    bv = g["bufferViews"]
    order = sorted(range(len(bv)), key=lambda i: bv[i].get("byteOffset", 0))
    newbin = bytearray()
    for i in order:
        v = bv[i]
        o = v.get("byteOffset", 0)
        data = (replace[i][0] if i in replace
                else binc[o:o + v["byteLength"]])
        while len(newbin) % 4:                     # glTF: 4-byte alignment
            newbin.append(0)
        v["byteOffset"] = len(newbin)
        v["byteLength"] = len(data)
        newbin += data
    g["buffers"] = [{"byteLength": len(newbin)}]
    js = json.dumps(g, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    while len(newbin) % 4:
        newbin.append(0)
    with open(out_path, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(newbin)))
        f.write(struct.pack("<I", len(js)) + b"JSON" + js)
        f.write(struct.pack("<I", len(newbin)) + b"BIN\x00" + bytes(newbin))


def slim(path, out_path, target_mb=25.0, tex_size=2048, tex_quality=92,
         keep_hidden=False, cull_part="interior", samples=64, report=None):
    """Cut a finished car under an object-size cap without changing what a
    customer can see. Order is deliberate: geometry first, then texture, then
    measure -- because the byte budget decides which of the two was worth doing
    and on this car the answer was the opposite of everyone's assumption.
    """
    import trimesh
    rep = {"input": path, "input_bytes": os.path.getsize(path), "steps": []}
    sc = trimesh.load(path, force="scene", process=False)

    if not keep_hidden and cull_part in sc.geometry:
        gm = sc.geometry[cull_part]
        n0 = len(gm.faces)
        hid = hidden_faces(sc, cull_part, samples=samples)
        keep = grow_mask(gm, ~hid, rings=2)
        gm.update_faces(keep)
        gm.remove_unreferenced_vertices()
        rep["steps"].append({
            "step": "occlusion cull", "part": cull_part,
            "faces_before": n0, "faces_after": int(len(gm.faces)),
            "hidden_by_raycast": int(hid.sum()),
            "kept_after_2ring_grow": int(keep.sum()),
            "definition": "a face is hidden only if all %d hemisphere rays are "
                          "blocked by non-glass geometry" % samples})

    # Export the trimmed scene, then re-open at the JSON level for textures.
    # include_normals is NOT optional: a scene export drops NORMAL otherwise
    # and the car renders faceted (paid for on an earlier submesh export).
    tmp = out_path + ".geom.glb"
    with open(tmp, "wb") as f:
        f.write(trimesh.exchange.gltf.export_glb(sc, include_normals=True))
    rep["steps"].append({"step": "geometry export", "bytes": os.path.getsize(tmp)})

    g, binc = read_glb(tmp)
    replace, notes = recompress_images(g, binc, tex_size, tex_quality)
    rep["steps"].append({"step": "texture recompress", "notes": notes})
    rebuild_glb(g, binc, replace, out_path)
    os.remove(tmp)

    rep["output"] = out_path
    rep["output_bytes"] = os.path.getsize(out_path)
    rep["target_bytes"] = int(target_mb * 1e6)
    rep["under_target"] = rep["output_bytes"] <= rep["target_bytes"]
    rep["ratio"] = round(rep["output_bytes"] / rep["input_bytes"], 4)
    if report:
        with open(report, "w") as f:
            json.dump(rep, f, indent=1)
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("glb")
    a.add_argument("--json")
    s = sub.add_parser("slim")
    s.add_argument("glb")
    s.add_argument("out")
    s.add_argument("--target-mb", type=float, default=25.0)
    s.add_argument("--tex-size", type=int, default=2048)
    s.add_argument("--tex-quality", type=int, default=92)
    s.add_argument("--samples", type=int, default=64)
    s.add_argument("--cull-part", default="interior")
    s.add_argument("--keep-hidden", action="store_true")
    s.add_argument("--report")
    ns = ap.parse_args()

    if ns.cmd == "audit":
        print_audit(audit(ns.glb, ns.json))
    else:
        rep = slim(ns.glb, ns.out, ns.target_mb, ns.tex_size, ns.tex_quality,
                   ns.keep_hidden, ns.cull_part, ns.samples, ns.report)
        print(json.dumps(rep, indent=1))
        print(f"{rep['input_bytes']/1e6:.2f} MB -> {rep['output_bytes']/1e6:.2f} MB"
              f"   under {ns.target_mb} MB: {rep['under_target']}")


if __name__ == "__main__":
    main()
