"""qc_audit.py — Blender headless geometry QC audit for a car GLB.

Read-only. Imports a GLB and reports the automotive quality problems that
matter: loose/disconnected geometry, non-manifold edges, flipped normals,
duplicate vertices, n-gons, degenerate faces, watertightness, object
hierarchy (are doors/bonnet/boot separated?), material split, and overall
tri budget. Writes a JSON report and prints a human summary. It NEVER edits
or saves the model — it only inspects, so it is always safe to run first.

Run (a real Blender must execute this):
    blender -b -noaudio --python pipeline/blender/qc_audit.py -- \
        --in pipeline/masters/golf_master.glb \
        --out pipeline/reports/golf_qc.json

Exit code is 0 always (audit is advisory); read the JSON 'blockers' list to
gate a release in CI.
"""
import bpy, bmesh, json, sys, os, math
from collections import defaultdict

# ---- arg parsing (everything after "--") -----------------------------------
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default
IN  = arg("--in")
OUT = arg("--out", "qc_report.json")
if not IN or not os.path.exists(IN):
    print("QC_ERROR missing --in GLB"); sys.exit(0)

# ---- clean scene + import ---------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    bpy.ops.import_scene.gltf(filepath=IN)
except Exception as e:
    json.dump({"status": "import_failed", "error": str(e)}, open(OUT, "w"))
    print("QC_ERROR import_failed", e); sys.exit(0)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]

# ---- door / bonnet / boot hierarchy check ----------------------------------
OPEN_PARTS = {"door": ["door", "puerta", "tuer", "tür"],
              "bonnet": ["bonnet", "hood", "capot", "motorhaube"],
              "boot": ["boot", "trunk", "tailgate", "hatch", "heckklappe"],
              "wheel": ["wheel", "rim", "alloy"]}
def part_of(name):
    n = name.lower()
    for part, keys in OPEN_PARTS.items():
        if any(k in n for k in keys):
            return part
    return None
hierarchy = defaultdict(list)
for o in meshes:
    p = part_of(o.name)
    if p: hierarchy[p].append(o.name)

# ---- per-object geometry inspection ----------------------------------------
report_objs = []
tot = dict(verts=0, faces=0, tris=0, loose_verts=0, nonmanifold=0,
           flipped=0, ngons=0, degenerate=0, doubles_est=0)
for o in meshes:
    bm = bmesh.new(); bm.from_mesh(o.data)
    bm.normal_update()
    loose = sum(1 for v in bm.verts if not v.link_edges)
    nonman = sum(1 for e in bm.edges if not e.is_manifold)
    ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
    degen = sum(1 for f in bm.faces if f.calc_area() < 1e-9)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    # duplicate-vertex estimate: verts sharing a location within epsilon
    seen = set(); dbl = 0
    for v in bm.verts:
        key = (round(v.co.x, 5), round(v.co.y, 5), round(v.co.z, 5))
        if key in seen: dbl += 1
        else: seen.add(key)
    # flipped-normal detection by per-shell signed volume. A closed (manifold)
    # shell with inverted normals has NEGATIVE signed volume. This does NOT
    # false-positive on interior concavity the way an object-centroid test does
    # — open shells (no volume defined) are skipped, not flagged.
    flipped = 0
    shells = 0
    visited = set()
    face_list = list(bm.faces)
    for seed in face_list:
        if seed.index in visited:
            continue
        stack = [seed]; comp = []
        while stack:
            f = stack.pop()
            if f.index in visited:
                continue
            visited.add(f.index); comp.append(f)
            for e in f.edges:
                for lf in e.link_faces:
                    if lf.index not in visited:
                        stack.append(lf)
        # closed only if every edge in the component is shared by 2 comp faces
        cset = {f.index for f in comp}
        closed = all(sum(1 for lf in e.link_faces if lf.index in cset) == 2
                     for f in comp for e in f.edges)
        if not closed or len(comp) < 8:
            continue
        shells += 1
        vol = 0.0
        for f in comp:
            vs = f.verts
            if len(vs) < 3:
                continue
            a = vs[0].co
            for i in range(1, len(vs) - 1):
                vol += a.dot((vs[i].co).cross(vs[i + 1].co)) / 6.0
        if vol < 0:            # inverted closed shell
            flipped += len(comp)
    watertight = (nonman == 0 and loose == 0)
    report_objs.append(dict(
        name=o.name, part=part_of(o.name), verts=len(bm.verts), faces=len(bm.faces),
        tris=tris, loose_verts=loose, nonmanifold_edges=nonman, flipped_faces=flipped,
        ngons=ngons, degenerate_faces=degen, dup_verts_est=dbl,
        watertight=watertight, materials=[m.name for m in o.data.materials if m]))
    for k, val in dict(verts=len(bm.verts), faces=len(bm.faces), tris=tris,
                       loose_verts=loose, nonmanifold=nonman, flipped=flipped,
                       ngons=ngons, degenerate=degen, doubles_est=dbl).items():
        tot[k] += val
    bm.free()

# ---- blockers (release-gating) ---------------------------------------------
blockers, warnings = [], []
if tot["nonmanifold"] > 0:
    warnings.append(f"{tot['nonmanifold']} non-manifold edges (expected on open-panel car models; block only if watertight parts required)")
if tot["degenerate"] > 0:
    blockers.append(f"{tot['degenerate']} degenerate (zero-area) faces — clean before release")
if tot["flipped"] > 0:
    blockers.append(f"{tot['flipped']} faces in inverted closed shells — recalculate normals outside")
if tot["loose_verts"] > 0:
    warnings.append(f"{tot['loose_verts']} loose vertices — delete")
if tot["doubles_est"] > tot["verts"] * 0.10:
    warnings.append(f"~{tot['doubles_est']} duplicate vertices — merge by distance")
if not hierarchy.get("door"):
    warnings.append("no separated door objects found — door-open interaction not possible until doors are split")
if tot["tris"] > 350_000:
    warnings.append(f"{tot['tris']:,} triangles — heavy for mobile; consider LOD/decimation on smooth panels")

report = dict(
    status="ok", source=os.path.basename(IN),
    blender=bpy.app.version_string,
    objects=len(meshes), totals=tot,
    hierarchy={k: v for k, v in hierarchy.items()},
    blockers=blockers, warnings=warnings, per_object=report_objs)
json.dump(report, open(OUT, "w"), indent=1)

# ---- human summary ----------------------------------------------------------
print("\n===== QC AUDIT:", os.path.basename(IN), "=====")
print(f"objects={len(meshes)}  tris={tot['tris']:,}  materials(union)={len({m for o in report_objs for m in o['materials']})}")
print(f"nonmanifold_edges={tot['nonmanifold']}  flipped={tot['flipped']}  degenerate={tot['degenerate']}  loose={tot['loose_verts']}  dup_verts~{tot['doubles_est']}")
print(f"hierarchy: doors={len(hierarchy.get('door',[]))} bonnet={len(hierarchy.get('bonnet',[]))} boot={len(hierarchy.get('boot',[]))} wheels={len(hierarchy.get('wheel',[]))}")
print(f"BLOCKERS ({len(blockers)}):")
for b in blockers: print("  ✗", b)
print(f"WARNINGS ({len(warnings)}):")
for w in warnings: print("  !", w)
print("report ->", OUT)
