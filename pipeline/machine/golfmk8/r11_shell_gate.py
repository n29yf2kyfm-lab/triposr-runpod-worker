#!/usr/bin/env python3
"""r11_shell_gate.py — REJECTED. Two metrics for "is the bodywork there", both
measured, both useless. Kept so the next attempt starts from the results.

THE DEFECT IT WAS WRITTEN FOR, which is real and is still undetected.
skoda-octavia-w7-v1 probes verdict=clear certainty=proven after reglazing and
HAS NO FRONT BODYWORK. A material-ID render head-on (unique flat colour per
material, 1 sample) shows seats, headrests, centre console and floor pan where
the bonnet, grille and bumper should be; 73.5% of the head-on silhouette is
cabin. In an ordinary render that region is solid black, because an interior in
shadow renders black -- which is how it first got described as "a solid black
mass", a symptom with no cause attached. It is present in the UNTOUCHED source
file, so no repair in this pipeline caused it.

IT DEFEATS EVERY EXISTING CHECK, each for its own reason:
  * glass_probe reads MATERIALS. Missing geometry has no material, so a car with
    no front end probes exactly as clear as one with a front end.
  * the wave sheet's two PROFILE tiles show a whole car -- flank, doors, roof
    and quarter panels are all present. It only appears head-on and in
    three-quarter views.
  * the flat-shell test reads baseColorFactors, which are unremarkable here.
  * recalculating normals does nothing: 13.5% of this car's 1,647,599 faces do
    flip under recalc, and fixing every one moved the black region from 73.5%
    of the head-on view to 74.4%. The inverted-normal theory was wrong.

WHAT THIS FILE TRIED, AND THE NUMBERS THAT KILLED EACH ONE.

1. RAY DEPTH -- fire rays from all round with glazing blocking, and ask how far
   into the car's bounding box each ray gets before it hits something, on the
   theory that an intact skin stops rays near the surface and a hole lets them
   fly on to a seat.
       skoda (no front end)   76.3% of rays land "deep"
       aston (intact)         74.7%
       focus (intact)         73.5%
   It does not separate them at all, and the reason is geometric rather than
   fixable: at the silhouette a car's surface is TANGENT to the view direction,
   so a perfectly intact panel is struck at every depth from front to back. The
   metric is measuring the shape of a car, not the presence of its panels.

2. BACKFACE FIRST HIT -- count rays whose first hit is the INSIDE of a surface,
   on the theory that a hole exposes the back of whatever is behind it.
       skoda (no front end)   0.8%
       aston (intact)         1.6%
       focus (intact)         2.2%
   Backwards: the gutted car scores LOWEST. A missing panel does not expose the
   back of anything -- the ray simply carries on and strikes the FRONT face of a
   seat, which is a perfectly ordinary front hit. What this actually measures is
   how much loose inward-facing trim a model carries, which the well-built cars
   have more of.

WHAT WOULD PROBABLY WORK, for whoever picks this up. The signal that is
unambiguous in the material-ID render is SEMANTIC -- cabin parts appearing in
the exterior silhouette -- and the reason a name test cannot read it here is
that this particular car is a merged re-export whose material names were
reassigned wholesale (its outer SKIN is called `Int_gauges_rs_A_4`). So either:
  * classify interior-vs-exterior GEOMETRICALLY first -- a part enclosed by the
    hull is cabin regardless of its name -- then run the silhouette test; or
  * compare the silhouette against the CONVEX HULL: an intact car's first hits
    hug its own hull, and a missing panel leaves a large region where the
    nearest surface sits far inside it. This is the promising one and it is not
    the same as metric 1, which measured depth into the BOUNDING BOX rather
    than distance from the HULL.
Do not retry either of the two above without new evidence; they are measured.

Run: blender -b --python r11_shell_gate.py -- car.glb [report.json]
Env: R11_GRID (40) rays per axis per direction · R11_DEEP (0.22) depth
     fraction counted as "inside the car" · R11_FAIL (0.10) share of rays
     allowed to land deep before the car fails
"""
import json
import math
import os
import sys

import bpy
import mathutils
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
GLB = argv[0]
REPORT = argv[1] if len(argv) > 1 else None
GRID = int(os.environ.get("R11_GRID", "40"))
DEEP = float(os.environ.get("R11_DEEP", "0.22"))
FAIL = float(os.environ.get("R11_FAIL", "0.10"))

GLASSY = ("glass", "window", "windscreen", "windshield", "screen", "glas",
          "scheibe", "fenster", "vidro", "backlight", "quarter")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)

verts = []
polys = []
owner = []
for ob in bpy.data.objects:
    if ob.type != "MESH" or not ob.data.polygons:
        continue
    mw = ob.matrix_world
    base = len(verts)
    verts.extend([mw @ v.co for v in ob.data.vertices])
    mats = list(ob.data.materials)
    for poly in ob.data.polygons:
        idx = [base + i for i in poly.vertices]
        mat = mats[min(poly.material_index, len(mats) - 1)] if mats else None
        for k in range(1, len(idx) - 1):
            polys.append((idx[0], idx[k], idx[k + 1]))
            owner.append(mat.name if mat else None)

if not polys:
    raise SystemExit(f"R11_REFUSED: no geometry in {GLB}")

lo = [min(v[i] for v in verts) for i in range(3)]
hi = [max(v[i] for v in verts) for i in range(3)]
span = [hi[i] - lo[i] for i in range(3)]
ctr = mathutils.Vector([(lo[i] + hi[i]) / 2.0 for i in range(3)])
diag = max(span)
tree = BVHTree.FromPolygons(verts, polys, all_triangles=True)

dirs = []
for az in range(0, 360, 24):
    for el in (-15.0, 5.0, 25.0, 50.0):
        a, e = math.radians(az), math.radians(el)
        dirs.append(mathutils.Vector((math.cos(a) * math.cos(e),
                                      math.sin(a) * math.cos(e),
                                      math.sin(e))))
up = mathutils.Vector((0, 0, 1))
# Per-direction bbox extent, precomputed: the eight corners projected onto each
# ray direction give the near and far faces the depth fraction is measured
# between.
corners = [mathutils.Vector((x, y, z))
           for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
lo_proj = []
hi_proj = []
for d in dirs:
    dv = -d.normalized()
    ps = [c.dot(dv) for c in corners]
    lo_proj.append(min(ps))
    hi_proj.append(max(ps))

hits = 0
deep = 0
deep_owner = {}
for k_dir, d in enumerate(dirs):
    d = d.normalized()
    u = d.cross(up)
    u = (u.normalized() if u.length > 1e-6
         else d.cross(mathutils.Vector((1, 0, 0))).normalized())
    v = d.cross(u).normalized()
    for i in range(GRID):
        for j in range(GRID):
            start = (ctr + d * diag
                     + u * ((i / (GRID - 1) - 0.5) * diag * 1.05)
                     + v * ((j / (GRID - 1) - 0.5) * diag * 1.05))
            o = start
            dirv = -d
            for _ in range(8):
                hit = tree.ray_cast(o, dirv)
                if hit[0] is None:
                    break
                nm = owner[hit[2]] or ""
                if any(g in nm.lower() for g in GLASSY):
                    # glazing is see-through by construction: a ray that passes
                    # through a windscreen and lands on a seat has found a
                    # WINDOW, not a hole, and must not be counted as one
                    o = hit[0] + dirv * (diag * 1e-4)
                    continue
                hits += 1
                # DEPTH = how far along its own direction the ray got before it
                # struck something, expressed as a fraction of the car's extent
                # along that same direction. 0.0 is the leading face of the
                # bounding box, 1.0 the trailing face. Projecting onto the ray
                # direction rather than measuring travelled distance is what
                # makes this independent of where the ray started and of the
                # file's units.
                p = hit[0].dot(dirv)
                depth = (p - lo_proj[k_dir]) / max(hi_proj[k_dir] - lo_proj[k_dir], 1e-12)
                if depth >= DEEP:
                    deep += 1
                    deep_owner[nm] = deep_owner.get(nm, 0) + 1
                break

frac = deep / max(hits, 1)
verdict = "gutted" if frac >= FAIL else "intact"
print(f"R11_RAYS hits={hits} deep={deep} ({frac:.1%}) threshold={FAIL:.0%}")
print(f"R11_VERDICT {verdict}")
if deep_owner:
    print("R11_DEEP_OWNERS (what the rays are landing on inside the car)")
    for nm, c in sorted(deep_owner.items(), key=lambda x: -x[1])[:8]:
        print(f"   {c / max(deep,1):6.1%}  {nm or '(no material)'}")
if REPORT:
    json.dump({"file": GLB, "verdict": verdict, "deep_fraction": round(frac, 4),
               "rays": hits, "deep": deep,
               "deep_owners": dict(sorted(deep_owner.items(),
                                          key=lambda x: -x[1])[:12])},
              open(REPORT, "w"), indent=2)
print("R11_DONE")
