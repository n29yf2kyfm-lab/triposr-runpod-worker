#!/usr/bin/env python3
"""p3sam_materials.py — P3-SAM part segmentation -> shippable material-separated car.

Third sibling of assign_materials.py (fused TRELLIS) and partcrafter_materials.py
(part-native PartCrafter). This one takes a mesh we already like — a Hunyuan3D
shell, the best surfacing measured to date — plus a P3-SAM face-level part
segmentation of it, and paints the proven golf 4+1 material scheme onto it.

Why this route exists (CLAUDE.md 2026-08-12): Hunyuan3D-2 output is ONE fused
component (measured 100.0% of verts), which is an automatic scrap under the
owner's ruling — opaque glazing, painted tyres. hybrid_transfer.py solves that by
borrowing PartCrafter's parts, but its label boundaries are only as good as
PartCrafter's own melt geometry (ragged windscreen edge, dashboard junk landing on
the front wing). P3-SAM segments the ACTUAL mesh we ship, per face, so there is no
cross-mesh alignment step and no boundary to smear.

INPUT, verified by reading Tencent-Hunyuan/Hunyuan3D-Part P3-SAM/demo/auto_mask.py
(save_mesh, ~line 387; mesh_sam ~line 757):
  * `<name>_face_ids.npy` — ONE integer part id PER FACE. Ids -1 and -2 mean
    "no part" and DO occur (save_mesh skips them when colouring).
  * `<name>.glb` / `.ply` — the same mesh, face-coloured per part.
  * `<name>_aabb.npy`, `<name>_aabb.glb` — per-part bounding boxes.
  With the default `--save_mid_res 1` the interesting file is
  `auto_mask_mesh_final_face_ids.npy` beside `auto_mask_mesh_final.glb`.

THE ALIGNMENT RISK, handled: auto_mask.py runs `clean_mesh` by DEFAULT
(`--clean_mesh 1`), which calls `mesh.merge_vertices()` then `mesh.process(True)`
— duplicate/degenerate faces are dropped, so the segmented mesh can have a
DIFFERENT face count and order from the file we handed it. Index alignment is
therefore an assumption, not a fact. This loader checks the face count and, on a
mismatch, transfers ids by nearest face-centroid lookup (cKDTree) against the
colour-coded GLB P3-SAM saved alongside — which is the cleaned mesh, so it always
matches the id array. Which path ran is printed and recorded in the report.

WHAT IT DOES
  1. load our mesh + face ids (aligned, or nearest-centroid transferred),
  2. fill unlabelled (-1/-2) faces from the nearest labelled face,
  3. classify every part with partcrafter_materials.classify — same rules, same
     thresholds, imported not copied,
  4. delete debris faces,
  5. physical priors + island absorption + hybrid_transfer.refine (graph cut on
     creases, interior visibility ray test, wheel cylinders, lamp mirroring),
  6. split canopy per-face into roof (body paint) vs glazing, by |n_up| AND
     HEIGHT — a raked windscreen centre is up-facing too (n_up ~0.86 at 31 deg
     from horizontal) and must stay glass; only up-facing faces near the TOP of
     the car are roof. Painting a windscreen with the body was caught on a
     head-on render, hence the second term,
  7. export one GLB with Material_0 / Glass_Tint / Wheel_Dark / Interior_Dark /
     Lamp_Lens — identical values to the other two stages so glass_probe,
     colour_variants and recolour_audit find what they expect,
  8. REFUSES to write when glazing lands on <2% of faces. Real cars are 4-12%.
     A file that names Glass_Tint without putting it on the windows PASSES
     glass_probe while the actual windows respray with the body — worse than no
     output. Do not relax this threshold.

Usage:
    python3 pipeline/trellis/p3sam_materials.py \
        --mesh hy_shape_raw.glb \
        --face-ids results/auto_mask_mesh_final_face_ids.npy \
        [--seg-mesh results/auto_mask_mesh_final.glb] \
        --out car_mat.glb [--report r.json]
    python3 pipeline/trellis/p3sam_materials.py --selftest
"""
import argparse
import json
import os
import sys
from collections import Counter

import numpy as np
import trimesh
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from partcrafter_materials import classify, ROOF_NORMAL_UP          # noqa: E402
from hybrid_transfer import (LABS, MATS, _norm_frame, _patches,     # noqa: E402
                             clamp_spikes, refine)

# Face fraction, matching hybrid_transfer's guard (partcrafter_materials guards
# the same 2% on verts). Do NOT relax — see the module docstring.
GLASS_MIN_FACE_FRAC = 0.02
# Up-facing AND this high in the car frame = roof skin. The height term is the
# 2026-08-12 fix: |n_up| alone paints a raked windscreen with the body.
ROOF_MIN_HEIGHT = 0.90
# Fit warning for the nearest-centroid path, in unit-car-frame units. The two
# meshes are the SAME object (clean_mesh only merges/drops, it never moves a
# vertex), so a healthy transfer is ~1e-3. Anything above this means the npy
# does not belong to this mesh.
MAX_TRANSFER_NN = 0.01

OUT_LABELS = ("body", "glass", "wheel", "interior", "lamp")


class Refused(Exception):
    """Guard tripped — nothing was written. Carries the report dict."""

    def __init__(self, msg, report=None):
        super().__init__(msg)
        self.report = report or {}


# ------------------------------------------------------------------ loading ---

def _guess_seg_mesh(ids_path):
    """P3-SAM writes <name>_face_ids.npy beside <name>.glb / <name>.ply."""
    if ids_path.endswith("_face_ids.npy"):
        stem = ids_path[: -len("_face_ids.npy")]
        for ext in (".glb", ".ply"):
            if os.path.exists(stem + ext):
                return stem + ext
    return None


def load_face_ids(mesh, ids_path, seg_mesh_path=None):
    """-> (ids aligned to mesh.faces, info dict).

    Index alignment is CHECKED, never assumed: auto_mask.py's default
    clean_mesh can change the face count and order. On a mismatch the ids are
    carried over by nearest face centroid, both meshes normalised into their own
    (length, width, up) unit frames so a rescale between them cannot break it.
    """
    raw = np.asarray(np.load(ids_path)).reshape(-1).astype(np.int64)
    info = {"ids_file": ids_path, "ids_len": int(len(raw)),
            "mesh_faces": int(len(mesh.faces)),
            "n_parts_raw": int(len(np.unique(raw[raw >= 0])))}

    if len(raw) == len(mesh.faces):
        info["mode"] = "aligned"
        print(f"face ids: ALIGNED ({len(raw)} faces, "
              f"{info['n_parts_raw']} parts)")
        return raw.copy(), info

    seg_path = seg_mesh_path or _guess_seg_mesh(ids_path)
    if not seg_path:
        raise SystemExit(
            f"face-id count {len(raw)} != mesh face count {len(mesh.faces)} "
            "(P3-SAM ran with clean_mesh=1 and re-meshed the input), and the "
            "segmented mesh it saved alongside was not found. Pass it with "
            "--seg-mesh <auto_mask_mesh_final.glb> so the ids can be "
            "transferred by nearest face centroid.")

    seg = trimesh.load(seg_path, force="mesh")
    if len(seg.faces) != len(raw):
        raise SystemExit(
            f"--seg-mesh {seg_path} has {len(seg.faces)} faces but the id array "
            f"has {len(raw)} — they are not from the same P3-SAM run.")

    def unit(m):
        axes, lo, ext = _norm_frame(m.vertices)
        return (m.vertices[:, axes] - lo) / ext

    src = unit(seg)[seg.faces].mean(axis=1)
    dst = unit(mesh)[mesh.faces].mean(axis=1)
    d, nn = cKDTree(src).query(dst, workers=4)
    ids = raw[nn]
    info.update(mode="nearest-centroid", seg_mesh=seg_path,
                transfer_nn_mean=float(d.mean()),
                transfer_nn_p99=float(np.percentile(d, 99)))
    print(f"face ids: FACE-COUNT MISMATCH ({len(raw)} seg vs "
          f"{len(mesh.faces)} ours) -> nearest-centroid transfer from "
          f"{os.path.basename(seg_path)}; mean NN {d.mean():.5f}, "
          f"p99 {np.percentile(d, 99):.5f}")
    if d.mean() > MAX_TRANSFER_NN:
        print(f"  WARNING: mean NN {d.mean():.4f} > {MAX_TRANSFER_NN} — these "
              "two meshes may not be the same object; labels will be wrong.")
    return ids, info


def fill_unlabelled(mesh, ids):
    """P3-SAM leaves -1/-2 on faces it could not assign. Give them the nearest
    labelled face's part rather than inventing a part or dropping geometry."""
    bad = ids < 0
    n = int(bad.sum())
    if n == 0 or bad.all():
        return ids, n
    fc = mesh.triangles_center
    tree = cKDTree(fc[~bad])
    ids = ids.copy()
    ids[bad] = ids[~bad][tree.query(fc[bad], workers=4)[1]]
    print(f"filled {n} unlabelled faces ({100*n/len(ids):.2f}%) from nearest "
          "labelled face")
    return ids, n


# -------------------------------------------------------------- classifying ---

def part_kinds(mesh, ids):
    """-> (dict part id -> kind, list of report rows).

    Features are exactly what partcrafter_materials.classify expects: vertex
    fraction, normalised (length, width, up) bbox, and the part's extents in
    WORLD units in the same axis order (aspect tests must not use the
    normalised frame — it scales each axis differently).
    """
    axes, lo, ext = _norm_frame(mesh.vertices)
    vn = (mesh.vertices[:, axes] - lo) / ext
    vw = mesh.vertices[:, axes]
    nv = len(mesh.vertices)

    kinds, rows = {}, []
    for pid in np.unique(ids):
        fm = ids == pid
        vidx = np.unique(mesh.faces[fm])
        p, w = vn[vidx], vw[vidx]
        feat = {"frac": len(vidx) / nv,
                "lo": p.min(axis=0).tolist(), "hi": p.max(axis=0).tolist(),
                "wspan": (w.max(axis=0) - w.min(axis=0)).tolist()}
        kind = classify(feat, None)
        kinds[int(pid)] = kind
        rows.append({"part": int(pid), "kind": kind,
                     "faces": int(fm.sum()), "verts": int(len(vidx)),
                     "frac": round(feat["frac"], 5),
                     "lo": [round(x, 3) for x in feat["lo"]],
                     "hi": [round(x, 3) for x in feat["hi"]]})
    return kinds, rows


def absorb_islands(mesh, flab, max_faces=4000):
    """Small patches whose every neighbour carries ONE other label are that
    label — same rule as hybrid_transfer.transfer, vectorised over components
    because a P3-SAM mesh is 600k faces, not a decimated PartCrafter part."""
    adj = mesh.face_adjacency
    n = len(mesh.faces)
    for target in range(len(LABS)):
        comp, cnt = _patches(flab, adj, n, target)
        small = {cid for cid, c in cnt.items() if c <= max_faces}
        if not small:
            continue
        ca, cb = comp[adj[:, 0]], comp[adj[:, 1]]
        sel = (ca >= 0) & (cb < 0)
        pairs = np.stack([ca[sel], flab[adj[sel, 1]]], axis=1)
        sel = (cb >= 0) & (ca < 0)
        pairs = np.concatenate(
            [pairs, np.stack([cb[sel], flab[adj[sel, 0]]], axis=1)])
        if not len(pairs):
            continue
        uniq = np.unique(pairs, axis=0)
        seen = {}
        for cid, lab in uniq:
            seen.setdefault(int(cid), []).append(int(lab))
        for cid, labs in seen.items():
            if cid in small and len(labs) == 1:
                flab[comp == cid] = labs[0]
    return flab


# ------------------------------------------------------------------- driver ---

def run(mesh_path, ids_path, out_path, seg_mesh=None, report_path=None,
        clamp=True):
    """Whole stage. Returns the report dict; raises Refused if the glazing
    guard trips (nothing is written in that case)."""
    m = trimesh.load(mesh_path, force="mesh")
    print(f"mesh: {len(m.vertices)} verts, {len(m.faces)} faces, "
          f"{len(m.split(only_watertight=False))} components")

    axes, lo, ext = _norm_frame(m.vertices)
    if axes[2] != 1:
        print("  WARNING: up axis is not glTF Y — refine() assumes Y-up")
    if ext[2] > min(ext[0], ext[1]):
        print(f"  WARNING: height {ext[2]:.3f} is not the smallest extent "
              f"(len {ext[0]:.3f}, wid {ext[1]:.3f}) — is this mesh Y-up?")

    ids, info = load_face_ids(m, ids_path, seg_mesh)
    ids, n_unlab = fill_unlabelled(m, ids)
    info["unlabelled_faces"] = n_unlab

    kinds, rows = part_kinds(m, ids)
    kc = Counter(kinds.values())
    print("parts: " + " ".join(f"{k}={kc.get(k, 0)}" for k in
                               ("body", "canopy", "wheel", "interior",
                                "lamp", "debris")))

    # DEBRIS out first — floating junk renders as artefacts on the audit sheet
    # and would otherwise get body paint. Face order is preserved by
    # update_faces, so the label array stays aligned.
    keep = np.array([kinds[int(p)] != "debris" for p in ids])
    n_debris = int((~keep).sum())
    kept_ids = ids[keep]
    flab = np.array([LABS.index(kinds[int(p)]) for p in kept_ids])
    if n_debris:
        m.update_faces(keep)
        m.remove_unreferenced_vertices()
        print(f"deleted {n_debris} debris faces "
              f"({100*n_debris/len(keep):.2f}%)")
    info["debris_faces"] = n_debris

    # normalised coords AFTER the debris cull (debris stretches the frame)
    axes, lo, ext = _norm_frame(m.vertices)
    hy = (m.vertices[:, axes] - lo) / ext
    fc = hy[m.faces].mean(axis=1)
    B, C, W, I, L = (LABS.index(k) for k in
                     ("body", "canopy", "wheel", "interior", "lamp"))

    # PHYSICAL PRIORS — same five rules, same thresholds, as
    # hybrid_transfer.transfer (they are inline there, not a function).
    flab[(flab == C) & (fc[:, 2] < 0.40)] = B          # no glazing below belt
    flab[(flab == W) & (fc[:, 2] > 0.55)] = B          # no tyres up high
    flab[(flab == L) & ~((fc[:, 0] > 0.78) | (fc[:, 0] < 0.22))] = B
    flab[(flab == I) & (fc[:, 2] > 0.80)] = B          # no interior in the roof
    flab[(flab == I) & (np.abs(fc[:, 1] - 0.5) > 0.38)] = B

    flab = absorb_islands(m, flab)

    # refine() wants the label source as a point cloud; ours is the mesh itself,
    # so its own face centroids ARE the labelled cloud (no cross-mesh distance
    # to decay against — the seeds sit exactly on the geometry they label).
    pc_lab_names = np.array(LABS)[flab]
    flab = refine(m, flab, hy, fc, pc_lab_names)

    if clamp:
        n_spike = int((hy[:, 2] > 1.015).sum())
        if n_spike:
            print(f"clamping {n_spike} antenna-spike verts above the roofline")
        m = clamp_spikes(m, hy)
        info["clamped_verts"] = n_spike

    # CANOPY -> roof vs glazing. |n_up| alone is not enough: a windscreen raked
    # 31 deg from horizontal has n_up ~0.86, above ROOF_NORMAL_UP, and was
    # measured painting body colour. Roof is up-facing AND near the top.
    n_up = np.abs(m.face_normals[:, 1])
    fcu = hy[m.faces].mean(axis=1)[:, 2]
    roofish = (n_up > ROOF_NORMAL_UP) & (fcu > ROOF_MIN_HEIGHT)
    out_lab = np.array(OUT_LABELS)[flab]
    out_lab[(flab == C) & roofish] = "body"
    out_lab[(flab == C) & ~roofish] = "glass"

    share = {k: round(100 * float(np.mean(out_lab == k)), 2) for k in OUT_LABELS}
    print("face share:", share)
    # Per-part OUTCOME: which material each P3-SAM part actually ended up
    # wearing after the priors and refine(). This is the diagnostic that says
    # whether a bad verdict came from classify() or from a later rule — the
    # distinction that "test the function, not the integration" keeps costing.
    for r in rows:
        if r["kind"] == "debris":
            r["final"] = {"deleted": r["faces"]}
            continue
        sel = kept_ids == r["part"]
        r["final"] = {k: int(v) for k, v in
                      Counter(out_lab[sel]).most_common()}
    rep = {"mesh": mesh_path, "out": out_path, "share": share,
           "counts": dict(kc), "load": info, "parts": rows,
           "faces": int(len(m.faces))}

    if share["glass"] < 100 * GLASS_MIN_FACE_FRAC:
        rep["refused"] = True
        rep["out"] = None
        if report_path:
            json.dump(rep, open(report_path, "w"), indent=1)
        raise Refused(
            f"REFUSING TO WRITE: glazing is {share['glass']:.2f}% of faces, "
            f"need >={100*GLASS_MIN_FACE_FRAC:.0f}% (real cars are 4-12%). "
            "P3-SAM did not give a greenhouse part, or the priors killed it. "
            "Writing anyway would ship a file that PASSES glass_probe with "
            "Glass_Tint on the wrong polygons while the real windows respray "
            "with the body. Do NOT relax this threshold — re-segment instead.",
            rep)

    scene = trimesh.Scene()
    for lab in OUT_LABELS:
        mask = out_lab == lab
        if not mask.any():
            print(f"  note: no {lab} faces — {MATS[lab].name} will be absent "
                  "from the file")
            continue
        sub = m.submesh([np.where(mask)[0]], append=True)
        sub.visual = trimesh.visual.TextureVisuals(material=MATS[lab])
        scene.add_geometry(sub, node_name=lab, geom_name=lab)
    scene.export(out_path)
    print(f"WROTE {out_path}")
    if report_path:
        json.dump(rep, open(report_path, "w"), indent=1)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", required=True, help="our GLB (Hunyuan shape)")
    ap.add_argument("--face-ids", required=True,
                    help="P3-SAM <name>_face_ids.npy")
    ap.add_argument("--seg-mesh", help="P3-SAM <name>.glb — only needed when "
                                       "the face count does not match")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    ap.add_argument("--no-clamp-spikes", action="store_true")
    a = ap.parse_args(argv)
    try:
        run(a.mesh, a.face_ids, a.out, a.seg_mesh, a.report,
            clamp=not a.no_clamp_spikes)
    except Refused as e:
        print(str(e))
        return 3
    return 0


# ================================================================= selftest ===
# Everything below builds a synthetic P3-SAM output and exercises the stage on
# it. There is no real P3-SAM run to test against yet, so the fixture is a
# procedural car: body box, raked-screen canopy, four wheel discs, four lamps,
# a hidden seat block, a VISIBLE underbody block (must be demoted to body), and
# a floating speck (must be culled as debris). Boxes/cylinders are subdivided to
# a uniform edge length so FACE fraction tracks AREA fraction — the glazing
# guard counts faces.

def _tri_box(x, y, z, sub=0.10):
    """Axis-aligned box from (lo, hi) pairs, subdivided to ~uniform density."""
    b = trimesh.creation.box(bounds=[[x[0], y[0], z[0]], [x[1], y[1], z[1]]])
    return b.subdivide_to_size(sub)


def _canopy(sub=0.10):
    """Open-bottomed greenhouse with a RAKED windscreen and backlight.

    The rake is deliberate: front face runs from (x=3.00, y=1.00) to
    (x=2.30, y=1.42) — 31 deg from horizontal, so its normal has n_up = 0.857,
    ABOVE ROOF_NORMAL_UP. If the roof/glass split used |n_up| alone this face
    would be painted body colour. It must come out GLASS.
    """
    v = np.array([
        [3.00, 1.00, 0.05], [1.00, 1.00, 0.05],      # 0,1 bottom right side
        [1.00, 1.00, 1.75], [3.00, 1.00, 1.75],      # 2,3 bottom left side
        [2.30, 1.42, 0.15], [1.60, 1.42, 0.15],      # 4,5 top
        [1.60, 1.42, 1.65], [2.30, 1.42, 1.65],      # 6,7
    ])
    f = np.array([
        [0, 4, 5], [0, 5, 1],        # windscreen (raked)
        [3, 2, 6], [3, 6, 7],        # backlight (raked)
        [0, 3, 7], [0, 7, 4],        # right side glass
        [1, 5, 6], [1, 6, 2],        # left side glass
        [4, 7, 6], [4, 6, 5],        # roof
    ])
    return trimesh.Trimesh(vertices=v, faces=f).subdivide_to_size(sub)


def _wheel(cx, cz, sub=0.10):
    """Disc lying in the length/height plane. trimesh's cylinder axis is +Z,
    which IS the width axis in this fixture, so it needs no rotation — an
    earlier version rotated it onto the up axis and produced a pancake that
    classify() correctly refused to call a wheel."""
    c = trimesh.creation.cylinder(radius=0.33, height=0.22, sections=24)
    c.apply_translation([cx, 0.33, cz])
    return c.subdivide_to_size(sub)


def _fixture(sub=0.10, with_canopy=True):
    """-> (mesh, face ids, expected kind per part id, part names).

    Frame: X = length 0..4.3, Y = up 0..1.42, Z = width 0..1.8 (glTF Y-up).
    Dimensions are a real saloon's, and the parts sit where a real car's do —
    lamps high on the nose (centre at 54% of body height, not down at wheel
    level), sills clear of the ground, wheels 0.66 m across.
    """
    parts = []                                     # (name, mesh, expect)
    parts.append(("body", _tri_box((0.0, 4.3), (0.40, 1.05), (0.0, 1.8), sub),
                  "body"))
    if with_canopy:
        parts.append(("canopy", _canopy(sub), "canopy"))
    for i, (cx, cz) in enumerate([(1.0, 0.05), (1.0, 1.75),
                                  (3.3, 0.05), (3.3, 1.75)]):
        parts.append((f"wheel{i}", _wheel(cx, cz, sub), "wheel"))
    for i, (x, z) in enumerate([((4.18, 4.30), (0.15, 0.57)),
                                ((4.18, 4.30), (1.23, 1.65)),
                                ((0.00, 0.12), (0.15, 0.57)),
                                ((0.00, 0.12), (1.23, 1.65))]):
        parts.append((f"lamp{i}", _tri_box(x, (0.68, 0.90), z, sub), "lamp"))
    # hidden seat block: fully inside the closed body box -> must STAY interior
    parts.append(("seats", _tri_box((1.4, 2.4), (0.60, 1.00), (0.4, 1.4), sub),
                  "interior"))
    # underfloor tray: classify() calls it interior (inset, mid band) but it is
    # VISIBLE from below, so refine()'s ray test must demote it to body. The
    # pair tests the visibility rule in BOTH directions.
    parts.append(("tray", _tri_box((1.4, 2.4), (0.28, 0.40), (0.4, 1.4), sub),
                  "interior"))
    # floating speck above the roofline -> debris, must be deleted
    parts.append(("speck", _tri_box((2.0, 2.06), (1.60, 1.66), (0.9, 0.96),
                                    sub), "debris"))

    meshes = [p[1] for p in parts]
    ids = np.concatenate([np.full(len(mm.faces), i)
                          for i, mm in enumerate(meshes)])
    car = trimesh.util.concatenate(meshes)
    expect = {i: p[2] for i, p in enumerate(parts)}
    names = {i: p[0] for i, p in enumerate(parts)}
    return car, ids, expect, names


def selftest():
    import subprocess
    import tempfile

    ok = [0]
    bad = []

    def check(name, cond, detail=""):
        if cond:
            ok[0] += 1
            print(f"ok   {name}")
        else:
            bad.append(name)
            print(f"BAD  {name} {detail}")

    tmp = tempfile.mkdtemp(prefix="p3sam_selftest_")
    car, ids, expect, names = _fixture()
    mesh_p = os.path.join(tmp, "car.glb")
    car.export(mesh_p)
    ids_p = os.path.join(tmp, "auto_mask_mesh_final_face_ids.npy")
    np.save(ids_p, ids)
    print(f"\nfixture: {len(car.faces)} faces, {len(np.unique(ids))} parts "
          f"-> {tmp}\n")

    # 1. classification of every fixture part (before any refinement)
    reloaded = trimesh.load(mesh_p, force="mesh")
    kinds, _ = part_kinds(reloaded, ids)
    for pid, want in expect.items():
        check(f"classify part {pid} ({names[pid]}) -> {want}",
              kinds[pid] == want, f"got {kinds[pid]}")

    # 2. happy path
    out_p = os.path.join(tmp, "out.glb")
    rep_p = os.path.join(tmp, "out.json")
    rep = run(mesh_p, ids_p, out_p, report_path=rep_p)
    check("aligned path taken", rep["load"]["mode"] == "aligned",
          rep["load"]["mode"])
    check("debris deleted", rep["load"]["debris_faces"] > 0)
    check("wrote a GLB", os.path.exists(out_p))

    s = trimesh.load(out_p)
    mats = sorted(g.visual.material.name for g in s.geometry.values())
    want = sorted(["Material_0", "Glass_Tint", "Wheel_Dark", "Interior_Dark",
                   "Lamp_Lens"])
    check("all 5 materials present", mats == want, str(mats))
    gl = [g for g in s.geometry.values()
          if g.visual.material.name == "Glass_Tint"][0]
    check("Glass_Tint alpha 0.72 + BLEND",
          abs(float(gl.visual.material.baseColorFactor[3]) / 255.0 - 0.72) < 0.01
          or abs(float(gl.visual.material.baseColorFactor[3]) - 0.72) < 0.01,
          str(gl.visual.material.baseColorFactor))
    check("glazing in the 4-12% band",
          4.0 <= rep["share"]["glass"] <= 12.0, f"{rep['share']['glass']}%")
    check("wheels painted", rep["share"]["wheel"] > 1.0,
          f"{rep['share']['wheel']}%")
    check("lamps painted", rep["share"]["lamp"] > 0.05,
          f"{rep['share']['lamp']}%")
    check("hidden seat block kept as interior", rep["share"]["interior"] > 0.5,
          f"{rep['share']['interior']}%")

    # per-part outcomes — these say whether a verdict came from classify() or
    # from a later rule, which a face-share number cannot
    byname = {names[r["part"]]: r for r in rep["parts"]}

    def dominant(part):
        f = byname[part]["final"]
        return max(f, key=f.get), sum(f.values())

    for w in ("wheel0", "wheel1", "wheel2", "wheel3"):
        d, _ = dominant(w)
        check(f"{w} ends up Wheel_Dark", d == "wheel", d)
    for lp in ("lamp0", "lamp1", "lamp2", "lamp3"):
        d, _ = dominant(lp)
        check(f"{lp} ends up Lamp_Lens", d == "lamp", d)
    d, _ = dominant("seats")
    check("hidden seats survive the visibility test", d == "interior", d)
    d, n = dominant("tray")
    check("VISIBLE tray demoted from interior to body by the ray test",
          d == "body" and byname["tray"]["final"].get("interior", 0) == 0,
          str(byname["tray"]["final"]))
    cf = byname["canopy"]["final"]
    check("canopy splits into BOTH glass and roof-body",
          cf.get("glass", 0) > 0 and cf.get("body", 0) > 0, str(cf))
    check("canopy is mostly glass, not mostly roof",
          cf.get("glass", 0) > cf.get("body", 0), str(cf))
    check("body shell stays body", dominant("body")[0] == "body")
    check("speck deleted as debris",
          byname["speck"]["final"] == {"deleted": byname["speck"]["faces"]},
          str(byname["speck"]["final"]))

    # 3. the raked windscreen must be GLASS, not roof. Its faces are the ones
    # whose normal is strongly up-facing but which sit BELOW the roofline.
    axes, lo, ext = _norm_frame(gl.vertices)
    fcu = ((gl.vertices[:, axes] - lo) / ext)[gl.faces].mean(axis=1)[:, 2]
    nup = np.abs(gl.face_normals[:, 1])
    raked = (nup > ROOF_NORMAL_UP) & (fcu < ROOF_MIN_HEIGHT)
    check("raked windscreen (n_up>0.85, below roofline) stays glass",
          raked.sum() > 0, f"{raked.sum()} such faces in Glass_Tint")
    body = [g for g in s.geometry.values()
            if g.visual.material.name == "Material_0"][0]
    axes, lo, ext = _norm_frame(body.vertices)
    bfcu = ((body.vertices[:, axes] - lo) / ext)[body.faces].mean(axis=1)[:, 2]
    check("roof skin is body paint",
          ((np.abs(body.face_normals[:, 1]) > ROOF_NORMAL_UP)
           & (bfcu > ROOF_MIN_HEIGHT)).sum() > 0)

    # 4. REFUSAL — same fixture with the canopy merged into the body, i.e. a
    # segmentation that never found a greenhouse. A gate only tested passing is
    # an untested gate.
    car2, ids2, _, _ = _fixture(with_canopy=False)
    mesh2 = os.path.join(tmp, "car_noglass.glb")
    car2.export(mesh2)
    ids2_p = os.path.join(tmp, "noglass_face_ids.npy")
    np.save(ids2_p, ids2)
    refused = False
    try:
        run(mesh2, ids2_p, os.path.join(tmp, "never.glb"))
    except Refused as e:
        refused = True
        msg = str(e)
    check("refuses when no greenhouse part exists", refused)
    check("refusal wrote nothing",
          not os.path.exists(os.path.join(tmp, "never.glb")))
    if refused:
        check("refusal names the threshold", "2%" in msg, msg[:80])
    r = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--mesh", mesh2, "--face-ids", ids2_p,
                        "--out", os.path.join(tmp, "never2.glb")],
                       capture_output=True, text=True)
    check("CLI exits non-zero (3) on refusal", r.returncode == 3,
          f"rc={r.returncode}")

    # 5. FACE-COUNT MISMATCH -> nearest-centroid path. Simulate auto_mask.py's
    # clean_mesh (merge_vertices + process) plus a few dropped faces and a
    # shuffled order, then segment THAT and feed it against our original mesh.
    seg = car.copy()
    seg.merge_vertices()
    seg.process(validate=True)
    rng = np.random.RandomState(0)
    order = rng.permutation(len(seg.faces))
    drop = order[:37]
    keep = np.ones(len(seg.faces), bool)
    keep[drop] = False
    seg.update_faces(keep)
    seg.remove_unreferenced_vertices()
    check("fixture seg mesh really has a different face count",
          len(seg.faces) != len(car.faces),
          f"{len(seg.faces)} vs {len(car.faces)}")
    # ids for the seg mesh, derived by its own nearest original face
    src_ids = ids[cKDTree(car.triangles_center).query(
        seg.triangles_center, workers=4)[1]]
    seg_p = os.path.join(tmp, "auto_mask_mesh_final.glb")
    seg.export(seg_p)
    seg_ids_p = os.path.join(tmp, "auto_mask_mesh_final_face_ids.npy")
    np.save(seg_ids_p, src_ids)
    out2 = os.path.join(tmp, "out_mismatch.glb")
    rep2 = run(mesh_p, seg_ids_p, out2)
    check("mismatch triggers nearest-centroid transfer",
          rep2["load"]["mode"] == "nearest-centroid", rep2["load"]["mode"])
    check("transfer auto-found the seg mesh beside the npy",
          rep2["load"].get("seg_mesh") == seg_p)
    check("transfer NN distance is tiny",
          rep2["load"]["transfer_nn_mean"] < 0.005,
          str(rep2["load"].get("transfer_nn_mean")))
    check("mismatch path still lands glazing in band",
          4.0 <= rep2["share"]["glass"] <= 12.0, f"{rep2['share']['glass']}%")
    same = all(abs(rep["share"][k] - rep2["share"][k]) < 1.0
               for k in OUT_LABELS)
    check("mismatch path agrees with aligned path (<1pp per class)", same,
          f"{rep['share']} vs {rep2['share']}")

    # 6. unlabelled (-1/-2) faces are filled, not dropped
    ids3 = ids.copy()
    ids3[rng.choice(len(ids3), 200, replace=False)] = -1
    ids3[rng.choice(len(ids3), 50, replace=False)] = -2
    ids3_p = os.path.join(tmp, "unlab_face_ids.npy")
    np.save(ids3_p, ids3)
    rep3 = run(mesh_p, ids3_p, os.path.join(tmp, "out_unlab.glb"))
    check("unlabelled faces reported and filled",
          rep3["load"]["unlabelled_faces"] >= 200,
          str(rep3["load"]["unlabelled_faces"]))
    check("unlabelled fill does not move the glazing share",
          abs(rep3["share"]["glass"] - rep["share"]["glass"]) < 1.0,
          f"{rep3['share']['glass']} vs {rep['share']['glass']}")

    # 7. a mismatched npy with NO seg mesh beside it must fail loudly, not
    # silently assume alignment
    lone = os.path.join(tmp, "lonely_face_ids.npy")
    np.save(lone, ids[:-5])
    try:
        run(mesh_p, lone, os.path.join(tmp, "never3.glb"))
        check("mismatch without a seg mesh raises", False, "no exception")
    except SystemExit as e:
        check("mismatch without a seg mesh raises", "--seg-mesh" in str(e))

    print(f"\n{ok[0]}/{ok[0] + len(bad)} assertions pass")
    for b in bad:
        print(f"  FAILED: {b}")
    return not bad


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    sys.exit(main())
