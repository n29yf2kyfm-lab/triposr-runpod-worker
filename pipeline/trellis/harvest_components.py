#!/usr/bin/env python3
"""harvest_components.py — build a library of car PARTS from audited catalogue cars.

Generated cars (Hunyuan3D geometry + PartCrafter part labels) always melt the
small hard-surface details: wheels, mirrors, lamps. `wheel_swap.py` proved the
fix — graft a crisp wheel harvested from an audited catalogue car onto the
generated shell — but it only ever had ONE donor (the GR Supra's front-left).
This builds a proper LIBRARY so a supermini, a 4x4 and a supercar can each get a
wheel that suits it.

WHAT IT DOES, per donor assetId:
  1. resolves the assetId through the public catalogue.json to its desktopGlbUrl
  2. downloads it (public bucket — no credentials needed)
  3. DECOMPRESSES it if it is Draco.  Neither trimesh nor the local Blender can
     decode Draco: you get a mesh with the right vertex COUNT and extents of
     exactly zero, which reads like a broken donor rather than a codec problem.
     Detection parses the GLB JSON chunk for `extensionsUsed`/`Required` —
     grepping the first 4 KB of the file (the previously documented trick) does
     NOT work: in `toyota-gr-supra-v1.glb` the string "KHR_draco" first appears
     at byte 53,568, so a 4 KB grep calls the canonical donor uncompressed.
  4. finds a wheel: parts whose NODE or MESH name matches wheel/tyre/rim, with a
     geometric fall-back that scans every connected component in the file.
     Either way the candidate must PASS a shape test (see `wheelness`), so a
     name match alone can never ship a steering wheel or a wheel-arch liner.
  5. normalises it: bbox-centred on the origin, axle on +X pointing OUTBOARD,
     car-up on +Y, scaled to diameter 1.0.
  6. splits tyre from rim by radius and assigns OUR materials.

WHY OUR MATERIALS: donor material tables are not trustworthy.  The Supra ships
its entire wheel — tyre AND rim — as one pale material called `wheel_rim`, so a
straight material copy paints the rubber body-colour, which is a hard fail under
the owner's tyre ruling.  The donor contributes GEOMETRY ONLY.

ORIENTATION CONVENTION: +X = OUTBOARD, +Y = up, diameter = 1.0.  This matches
the raw orientation of the Supra donor `wheel_swap.py` already uses (its LF
wheel sits at x=+0.80 with the car centred at x=0), so the library is a drop-in
for the existing consumer.  NOTE, unverified-by-me but visible in the code:
`wheel_swap.py` rotates the donor by rotation_matrix(+pi/2, [0,1,0]) for the
+Z side, which maps donor +X to -Z, i.e. it points the OUTBOARD face INBOARD
on both sides.  That is a pre-existing sign bug in the placement stage, not in
this library; fix it there, not by flipping the convention here.

OUTPUT: one GLB per wheel holding two geometries, `tyre` and `rim`, plus an
INDEX.json manifest.  (`wheel_swap.load_donor` currently wants a SINGLE named
geometry, so it needs a small change to consume these — it should concatenate
`tyre`+`rim`, or simply keep them, since they are already split and materialled.)

Usage:
    python3 pipeline/trellis/harvest_components.py \\
        --assets toyota-gr-supra-v1,kia-ev9-v1,mg-3-2025-v1 \\
        --out-dir out/components/wheels

    python3 pipeline/trellis/harvest_components.py \\
        --assets-file donors.txt --out-dir out/components/wheels --workdir /tmp/hc
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import urllib.request

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

CATALOGUE_URL = ("https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/"
                 "public/car-renders/catalogue.json")
GLTF_TRANSFORM = os.environ.get("GLTF_TRANSFORM", "/opt/node22/bin/gltf-transform")

# Names that make a part a wheel candidate, and names that disqualify it.
# The shape test is the real gate; these only decide what we bother testing.
WHEEL_WORDS = ("wheel", "tyre", "tire", "rim", "alloy", "hubcap")
NOT_WHEEL_WORDS = ("steering", "spare", "arch", "wheelarch", "wheelwell", "well",
                   "liner", "guard", "flare", "cover", "nut", "bolt", "stud",
                   "caliper", "calliper", "brake", "disc", "disk", "rotor",
                   "suspension", "axle", "hub_carrier", "fender", "housing",
                   "handle", "gauge", "dial", "logo", "badge", "text")

TYRE_MAT = dict(name="Tyre_Rubber", baseColorFactor=[0.028, 0.028, 0.030, 1.0],
                metallicFactor=0.0, roughnessFactor=0.9)
RIM_MAT = dict(name="Rim_Alloy", baseColorFactor=[0.42, 0.43, 0.45, 1.0],
               metallicFactor=0.85, roughnessFactor=0.35)

TYRE_FRAC = 0.72        # faces beyond this fraction of R are tyre, as wheel_swap
MIN_VERTS = 300         # below this a "wheel" is a lug nut or a badge
MAX_SPLIT_VERTS = 400_000   # do not connected-component a mesh bigger than this


# ---------------------------------------------------------------- catalogue io

def load_catalogue(path_or_url: str) -> dict:
    """assetId -> catalogue entry, for approved and non-approved alike."""
    if path_or_url.startswith("http"):
        with urllib.request.urlopen(path_or_url, timeout=120) as f:
            data = json.load(f)
    else:
        data = json.load(open(path_or_url))
    return {e["assetId"]: e for e in data if e.get("assetId")}


def download(url: str, dest: str) -> str:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    return dest


# ------------------------------------------------------------------- draco

def glb_json(path: str) -> dict:
    """The JSON chunk of a .glb, or {} if the file is not a binary glTF."""
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"glTF":
            return {}
        clen, ctype = struct.unpack("<I4s", f.read(8))
        if ctype != b"JSON":
            return {}
        return json.loads(f.read(clen))


def is_draco(path: str) -> bool:
    j = glb_json(path)
    exts = set(j.get("extensionsUsed") or []) | set(j.get("extensionsRequired") or [])
    return "KHR_draco_mesh_compression" in exts


def decompress(path: str, out: str) -> str:
    """gltf-transform copy — the only Draco decoder available on this box."""
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    subprocess.run([GLTF_TRANSFORM, "copy", path, out], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out


# ------------------------------------------------------------- shape testing

def wheelness(v: np.ndarray) -> dict:
    """Is this vertex cloud a wheel?  Returns the measurements and a verdict.

    A wheel is a disc: one small extent (the axle) and two near-equal large
    ones, with geometry present at close to the outer radius all the way round.
    The angular-coverage term is what rejects blobs that merely have a squarish
    bounding box — a mirror housing or a door card can pass the ratio test, but
    not the 360-degree rim test.
    """
    ext = v.max(0) - v.min(0)
    a = int(np.argmin(ext))
    i, j = [k for k in range(3) if k != a]
    big, small = max(ext[i], ext[j]), min(ext[i], ext[j])
    if big <= 0:
        return dict(ok=False, reason="zero extent (undecoded Draco?)")
    ctr = (v.max(0) + v.min(0)) / 2
    p = v[:, [i, j]] - ctr[[i, j]]
    r = np.linalg.norm(p, axis=1)
    R = float(np.percentile(r, 99.5))
    nb = 36
    th = np.arctan2(p[:, 1], p[:, 0])
    idx = np.clip(((th + np.pi) / (2 * np.pi) * nb).astype(int), 0, nb - 1)
    maxr = np.zeros(nb)
    np.maximum.at(maxr, idx, r)
    cov = float((maxr >= 0.85 * R).mean())
    m = dict(axle_axis=a, diameter=float(big), width=float(ext[a]),
             roundness=float(small / big), aspect=float(ext[a] / big),
             coverage=cov, verts=int(len(v)))
    why = []
    if m["roundness"] < 0.82:
        why.append(f"not round in plane ({m['roundness']:.2f})")
    if not (0.10 <= m["aspect"] <= 0.85):
        why.append(f"bad width/dia aspect ({m['aspect']:.2f})")
    if cov < 0.92:
        why.append(f"rim not continuous ({cov:.2f} of 36 sectors)")
    if len(v) < MIN_VERTS:
        why.append(f"too few verts ({len(v)})")
    m["ok"] = not why
    m["reason"] = "; ".join(why)
    return m


def world_meshes(scene: trimesh.Scene):
    """(node_name, geom_name, mesh-in-world-coords) for every placed geometry."""
    out = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry.get(gname)
        if g is None or not hasattr(g, "vertices") or len(g.vertices) == 0:
            continue
        m = g.copy()
        m.apply_transform(T)
        out.append((node, gname, m))
    return out


def named_wheel(node: str, gname: str) -> bool:
    s = f"{node} {gname}".lower()
    if any(w in s for w in NOT_WHEEL_WORDS):
        return False
    return any(w in s for w in WHEEL_WORDS)


MAX_COMPONENTS = 3000   # pdist beyond this is not worth the memory


def components(cands):
    """[(idx, mesh)] connected components of the candidate meshes.

    Vertices are force-merged FIRST: many donors export split vertices for
    per-face UVs/normals, and on those `split()` would otherwise hand back one
    "component" per TRIANGLE.  The merged copies are used for ANALYSIS ONLY —
    the harvested geometry is rebuilt from the untouched originals at the end,
    so hard edges on the rim survive.
    """
    out = []
    for i, (_lab, m) in enumerate(cands):
        if len(m.vertices) > MAX_SPLIT_VERTS:
            out.append((i, m))
            continue
        mm = m.copy()
        try:
            mm.merge_vertices(merge_tex=True, merge_norm=True)
            parts = mm.split(only_watertight=False)
        except Exception:
            parts = []
        if len(parts) == 0 or len(parts) > 400:
            out.append((i, mm))
        else:
            out.extend((i, p) for p in parts)
    return [(i, p) for i, p in out if len(p.vertices) >= 16]


def _bbox(m):
    return m.vertices.min(0), m.vertices.max(0)


def grow(seed, pool, pad=0.06):
    """Absorb every component that sits INSIDE the seed's bounding box.

    A tyre on its own already passes the shape test, but it is a bare ring —
    the rim, spokes, hub and brake disc are separate components nested inside
    it.  Containment (not proximity) is the right rule: it pulls in everything
    the tyre encloses and can never pull in a wheel-arch liner or a body panel,
    which are always LARGER than the wheel they surround.

    This replaces centroid clustering, which was tried and does not work: on a
    dense car single-linkage chains the whole vehicle into one cluster (the
    Suzuki Jimny's 2,749 components collapsed to 1).
    """
    lo, hi = _bbox(seed)
    d = float((hi - lo).max())
    lo, hi = lo - pad * d, hi + pad * d
    idx, parts = set(), []
    for i, p in pool:
        plo, phi = _bbox(p)
        if (plo >= lo).all() and (phi <= hi).all():
            idx.add(i)
            parts.append(p)
    if not parts:
        return seed, idx
    return trimesh.util.concatenate(parts), idx


def rebuild(cands, idx, bbox, pad=0.08):
    """Re-cut the winning wheel from the ORIGINAL, unmerged donor meshes.

    Analysis runs on merged copies (needed for connectivity); merging welds the
    split vertices that carry a rim's hard edges, so shipping the merged copy
    would smooth-shade the spokes.  Here we go back to the source meshes that
    contributed and keep the faces inside the wheel's box.
    """
    lo, hi = bbox
    d = float((hi - lo).max())
    lo, hi = lo - pad * d, hi + pad * d
    keep = []
    for i in sorted(idx):
        m = cands[i][1]
        c = m.triangles_center
        sel = np.where(((c >= lo) & (c <= hi)).all(axis=1))[0]
        if len(sel):
            keep.append(m.submesh([sel], append=True))
    if not keep:
        return None
    return trimesh.util.concatenate(keep) if len(keep) > 1 else keep[0]


def find_wheel(scene: trimesh.Scene):
    """Best wheel in the scene, as (mesh, measurements, how_found, label).

    Named parts are tried first because they are cheap and unambiguous; the
    geometric sweep is the fall-back for donors that name nothing (the Jimny's
    parts are all `Object_NN`).  Both routes end at the same shape test, so a
    name match alone never decides anything.
    """
    wm = world_meshes(scene)
    if not wm:
        return None, {"reason": "no placed geometry"}, None, None
    allv = np.concatenate([m.vertices for _, _, m in wm])
    car_ext = allv.max(0) - allv.min(0)
    car_ctr = (allv.max(0) + allv.min(0)) / 2
    car_len = float(car_ext.max())

    def sweep(cands, how):
        pool = components(cands)
        if len(pool) > MAX_COMPONENTS:
            pool = sorted(pool, key=lambda ip: -len(ip[1].vertices))[:MAX_COMPONENTS]
        # seeds: any component, or any whole part, that is already wheel-shaped
        seeds = []
        for i, p in pool + [(k, c[1]) for k, c in enumerate(cands)]:
            mm = wheelness(p.vertices)
            # 0.11-0.20 of car length, not 0.06-0.40: measured on real picks
            # 2026-08-13 — genuine road wheels landed at 0.135-0.152 while a
            # STEERING WHEEL (complete with column stalks) passed the loose
            # band at 0.088 and shipped as the Golf mk8 "wheel". A road wheel
            # smaller than 11% or larger than 20% of car length is not one.
            if mm["ok"] and 0.11 * car_len <= mm["diameter"] <= 0.20 * car_len:
                seeds.append((i, p, mm))
        seeds.sort(key=lambda s: -s[2]["diameter"])
        seeds = seeds[:60]

        results = []
        for i, p, mm in seeds:
            g, idx = grow(p, pool)
            gm = wheelness(g.vertices)
            # growth must not break the disc shape or inflate the diameter
            if gm["ok"] and gm["diameter"] <= 1.05 * mm["diameter"]:
                src, box, base = idx | {i}, _bbox(g), gm
            else:
                src, box, base = {i}, _bbox(p), mm
            final = rebuild(cands, src, box)
            if final is None or len(final.vertices) < MIN_VERTS:
                continue
            fm = wheelness(final.vertices)
            if not fm["ok"] or fm["diameter"] > 1.10 * base["diameter"]:
                continue
            results.append((final, fm, cands[i][0]))
        if not results:
            return None

        # Drop nested hits: a brake disc is round, thin and continuous, so it
        # passes the shape test on its own — but it lives INSIDE the wheel that
        # also passed, so the enclosing hit is the one we want.
        results.sort(key=lambda r: -r[1]["diameter"])
        kept = []
        for r in results:
            lo, hi = _bbox(r[0])
            c = (lo + hi) / 2
            if any(((c >= _bbox(k[0])[0]).all() and (c <= _bbox(k[0])[1]).all())
                   for k in kept):
                continue
            kept.append(r)
        # most detailed wheel; on a staggered car the tie breaks to the
        # narrower (front) wheel, which is the more generally useful donor
        final, fm, lab = max(kept, key=lambda r: (r[1]["verts"], -r[1]["aspect"]))
        return final, fm, how, lab

    named = [(g, m) for n, g, m in wm if named_wheel(n, g)]
    best = sweep(named, "named") if named else None
    if best is None:
        best = sweep([(g, m) for _, g, m in wm], "geometric")

    if best is None:
        return None, {"reason": f"no component passed the wheel shape test "
                                f"({len(named)} name-matched parts examined)"}, None, None
    mesh, meas, how, lab = best
    meas["car_length"] = car_len
    meas["dia_over_car_length"] = meas["diameter"] / car_len
    meas["car_centre"] = car_ctr.tolist()
    meas["car_extents"] = car_ext.tolist()
    return mesh, meas, how, lab


# ------------------------------------------------------------- normalisation

def normalise(mesh: trimesh.Trimesh, meas: dict):
    """Origin-centred, axle on +X pointing outboard, car-up on +Y, diameter 1."""
    a = meas["axle_axis"]
    ctr = (mesh.vertices.max(0) + mesh.vertices.min(0)) / 2
    car_ctr = np.array(meas["car_centre"])
    car_ext = np.array(meas["car_extents"])

    # outboard = away from the car's centreline along the axle axis
    sgn = 1.0 if (ctr[a] - car_ctr[a]) >= 0 else -1.0
    # of the two non-axle car axes, the SHORTER is height: that is up
    rest = [k for k in range(3) if k != a]
    up = rest[int(np.argmin(car_ext[rest]))]
    lng = [k for k in rest if k != up][0]

    ex = np.zeros(3); ex[a] = sgn
    ey = np.zeros(3); ey[up] = 1.0
    ez = np.cross(ex, ey)                     # keep it right-handed
    R = np.eye(4)
    R[:3, 0], R[:3, 1], R[:3, 2] = ex, ey, ez
    R[:3, :3] = R[:3, :3].T                   # world -> library

    m = mesh.copy()
    m.vertices = m.vertices - ctr
    m.apply_transform(R)
    scale = 1.0 / meas["diameter"]
    m.apply_scale(scale)
    meas["up_axis"] = up
    meas["length_axis"] = lng
    meas["outboard_sign"] = sgn
    meas["scale_applied"] = scale
    return m


def split_materials(m: trimesh.Trimesh, tyre_frac: float = TYRE_FRAC):
    """Tyre/rim by radius from the axle, with OUR materials.  Donor materials
    are discarded on purpose (see the module docstring)."""
    R = float(np.abs(m.vertices[:, 1:3]).max())
    fr = np.linalg.norm(m.triangles_center[:, 1:3], axis=1)
    ti = np.where(fr > tyre_frac * R)[0]
    ri = np.where(fr <= tyre_frac * R)[0]
    out = {}
    if len(ti):
        t = m.submesh([ti], append=True)
        t.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(**TYRE_MAT))
        out["tyre"] = t
    if len(ri):
        r = m.submesh([ri], append=True)
        r.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(**RIM_MAT))
        out["rim"] = r
    return out


# ------------------------------------------------------------------ harvest

def harvest_one(asset_id, entry, workdir, out_dir):
    url = entry.get("desktopGlbUrl")
    if not url:
        return None, "no desktopGlbUrl in the catalogue entry"
    raw = os.path.join(workdir, f"{asset_id}.glb")
    try:
        download(url, raw)
    except Exception as e:
        return None, f"download failed: {e}"

    draco = is_draco(raw)
    src = raw
    if draco:
        try:
            src = decompress(raw, os.path.join(workdir, f"{asset_id}_uc.glb"))
        except Exception as e:
            return None, f"draco decompress failed: {e}"

    try:
        scene = trimesh.load(src)
    except Exception as e:
        return None, f"load failed: {e}"
    if not isinstance(scene, trimesh.Scene):
        scene = trimesh.Scene(scene)

    mesh, meas, how, lab = find_wheel(scene)
    if mesh is None:
        return None, meas.get("reason", "no wheel found")

    norm = normalise(mesh, meas)
    parts = split_materials(norm)
    if "tyre" not in parts or "rim" not in parts:
        return None, "tyre/rim radius split produced an empty half"

    out_name = f"wheel_{asset_id}.glb"
    out_path = os.path.join(out_dir, out_name)
    sc = trimesh.Scene()
    for nm, g in parts.items():
        sc.add_geometry(g, node_name=nm, geom_name=nm)
    os.makedirs(out_dir, exist_ok=True)
    sc.export(out_path)

    rec = dict(
        filename=out_name,
        assetId=asset_id,
        make=entry.get("make"), model=entry.get("model"),
        bodyStyle=entry.get("bodyStyle"), qualityGrade=entry.get("qualityGrade"),
        sourceTitle=entry.get("sourceTitle"),
        donorPart=lab, foundBy=how, dracoSource=bool(draco),
        vertices=int(len(norm.vertices)), faces=int(len(norm.faces)),
        tyreVertices=int(len(parts["tyre"].vertices)),
        rimVertices=int(len(parts["rim"].vertices)),
        diameterSourceUnits=round(meas["diameter"], 5),
        widthSourceUnits=round(meas["width"], 5),
        widthOverDiameter=round(meas["aspect"], 4),
        diameterOverCarLength=round(meas["dia_over_car_length"], 4),
        carLengthSourceUnits=round(meas["car_length"], 4),
        roundness=round(meas["roundness"], 4),
        rimCoverage=round(meas["coverage"], 3),
        normalisedDiameter=1.0,
        normalisedWidth=round(float(norm.vertices[:, 0].max() - norm.vertices[:, 0].min()), 4),
        orientation="axle +X outboard, up +Y, diameter 1.0",
        fileBytes=os.path.getsize(out_path),
    )
    return rec, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--assets", help="comma-separated assetIds")
    ap.add_argument("--assets-file", help="file with one assetId per line")
    ap.add_argument("--catalogue", default=CATALOGUE_URL)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workdir", default="/tmp/harvest_components")
    ap.add_argument("--manifest", default=None,
                    help="default: <out-dir>/INDEX.json")
    a = ap.parse_args()

    ids = []
    if a.assets:
        ids += [x.strip() for x in a.assets.split(",") if x.strip()]
    if a.assets_file:
        ids += [l.split("#")[0].strip() for l in open(a.assets_file)
                if l.split("#")[0].strip()]
    if not ids:
        ap.error("give --assets or --assets-file")

    cat = load_catalogue(a.catalogue)
    os.makedirs(a.workdir, exist_ok=True)
    os.makedirs(a.out_dir, exist_ok=True)

    ok, bad = [], []
    for i in ids:
        e = cat.get(i)
        if e is None:
            bad.append((i, "assetId not in catalogue"))
            print(f"FAIL {i}: not in catalogue", flush=True)
            continue
        try:
            rec, err = harvest_one(i, e, a.workdir, a.out_dir)
        except Exception as ex:                      # noqa: BLE001 - report, continue
            rec, err = None, f"{type(ex).__name__}: {ex}"
        if rec is None:
            bad.append((i, err))
            print(f"FAIL {i}: {err}", flush=True)
        else:
            ok.append(rec)
            print(f"OK   {i}: {rec['donorPart']} verts={rec['vertices']} "
                  f"dia={rec['diameterSourceUnits']:.3f} "
                  f"w/d={rec['widthOverDiameter']:.2f} "
                  f"dia/car={rec['diameterOverCarLength']:.3f} "
                  f"{'draco' if rec['dracoSource'] else 'plain'}", flush=True)

    man = dict(
        component="wheels",
        generatedBy="pipeline/trellis/harvest_components.py",
        orientation="axle +X outboard, up +Y, bbox-centred, diameter normalised to 1.0",
        materials={"tyre": TYRE_MAT["name"], "rim": RIM_MAT["name"]},
        tyreSplitFraction=TYRE_FRAC,
        note=("Donor materials are discarded; tyre/rim are split by radius and "
              "re-materialled. Geometry only."),
        count=len(ok), wheels=ok,
        failures=[dict(assetId=i, reason=r) for i, r in bad],
    )
    mpath = a.manifest or os.path.join(a.out_dir, "INDEX.json")
    with open(mpath, "w") as f:
        json.dump(man, f, indent=2)
    print(f"\n{len(ok)} harvested, {len(bad)} failed -> {mpath}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
