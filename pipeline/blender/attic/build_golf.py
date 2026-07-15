"""build_golf.py — parametric VW Golf Mk7.5 hatch, built from scratch in Blender.

Lessons applied vs the sourced mesh:
  • normals outward by construction (no flipped faces)
  • doors / bonnet / boot are SEPARATE objects from the start -> actually openable
  • clean quad surfaces + subdivision (no melted rear quarter)
  • real modelled floor (no pale procedural underbody tray)
  • one shared body-paint material (no patchy panels)

OUTCOME (recorded 2026-07-13): proven-negative experiment. Building a Golf from
primitives + subsurf produces a crude blob that does NOT read as a Golf and is
far worse than the sourced/hand-finished mesh. Conclusion: an accurate car is
manual artist modelling or a LICENSED base mesh run through this pipeline — it
cannot be procedurally generated. Kept as documentation of the limit; not used
in production.

It is a clean, recognisable hatch — NOT photoreal OEM. Run:
  blender -b -noaudio --python pipeline/blender/build_golf.py -- \
      --out pipeline/build/golf_scratch.glb
"""
import bpy, bmesh, sys, os, math, mathutils
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(f, d=None): return argv[argv.index(f) + 1] if f in argv else d
OUT = arg("--out", "golf_scratch.glb")
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)

# ------------------------------------------------------------------ materials
def mat(name, rgba, metal=0.0, rough=0.5, coat=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = rgba
    b.inputs["Metallic"].default_value = metal
    b.inputs["Roughness"].default_value = rough
    if "Coat Weight" in b.inputs: b.inputs["Coat Weight"].default_value = coat
    return m
PAINT = mat("Car_Paint", (0.055, 0.062, 0.075, 1), metal=0.85, rough=0.30, coat=1.0)
GLASS = mat("Glass", (0.02, 0.024, 0.03, 1), metal=0.0, rough=0.08); GLASS.blend_method = "BLEND"
GLASS.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 0.55
TYRE  = mat("Tyre", (0.02, 0.02, 0.022, 1), metal=0.0, rough=0.9)
ALLOY = mat("Alloy", (0.11, 0.12, 0.14, 1), metal=1.0, rough=0.35)
CHROME= mat("Chrome", (0.8, 0.82, 0.85, 1), metal=1.0, rough=0.12)
BLACK = mat("Trim_Black", (0.02, 0.02, 0.02, 1), metal=0.2, rough=0.5)
RED   = mat("Caliper_Red", (0.5, 0.02, 0.02, 1), metal=0.3, rough=0.4)
GTEBLU= mat("GTE_Blue", (0.02, 0.18, 0.75, 1), metal=0.4, rough=0.35)
LIGHT = mat("Light", (0.6, 0.6, 0.62, 1), metal=0.3, rough=0.15)
INTER = mat("Interior", (0.20, 0.20, 0.21, 1), metal=0.0, rough=0.85)

def add_mat(o, m): o.data.materials.append(m)

# ------------------------------------------------------------------ body shell
# Build the half-body from length stations; each station is a vertical section
# of the side (bottom sill -> waist -> roof). Mirror across X for symmetry.
# z = length (front +), x = half-width, y = height.
LEN = 4.26; WID = 1.80; HT = 1.46
# side silhouette: (z_frac 0=rear..1=front, sill_y, waist_y, roof_y, halfwidth_frac)
STATIONS = [
    (0.00, 0.34, 0.62, 0.62, 0.60),   # rear bumper
    (0.06, 0.30, 0.82, 1.02, 0.86),   # rear valance/hatch base
    (0.14, 0.30, 0.96, 1.34, 0.98),   # C-pillar base / haunch
    (0.30, 0.30, 0.98, 1.42, 1.00),   # rear door
    (0.46, 0.29, 0.99, 1.44, 1.00),   # B-pillar
    (0.62, 0.29, 0.99, 1.43, 1.00),   # front door
    (0.74, 0.30, 0.98, 1.30, 0.98),   # A-pillar base
    (0.84, 0.32, 0.86, 0.92, 0.92),   # bonnet
    (0.93, 0.34, 0.66, 0.66, 0.82),   # grille
    (1.00, 0.40, 0.56, 0.56, 0.60),   # front bumper
]
# roofline height (cabin greenhouse) separate from body-top so we get a cabin
ROOF = {0.14: 1.44, 0.30: 1.47, 0.46: 1.48, 0.62: 1.47, 0.74: 1.40}

bm = bmesh.new()
rings = []
SECT = [  # vertical section params: (t 0=sill..1=roof, xscale)
    (0.00, 0.55), (0.18, 0.92), (0.42, 1.00), (0.66, 0.98), (0.85, 0.80), (1.00, 0.42)]
for (zf, sill, waist, roof, wf) in STATIONS:
    z = (zf - 0.5) * LEN
    ring = []
    for (t, xs) in SECT:
        y = sill + (roof - sill) * t
        x = (WID / 2) * wf * xs
        ring.append(bm.verts.new((x, y, z)))
    rings.append(ring)
# bridge rings into a half-shell (quads)
for i in range(len(rings) - 1):
    a, b2 = rings[i], rings[i + 1]
    for j in range(len(a) - 1):
        bm.faces.new((a[j], a[j + 1], b2[j + 1], b2[j]))
# close top centreline with a roof strip (flat-ish across width already via x=0? )
bm.normal_update()
mesh = bpy.data.meshes.new("BodyHalf"); bm.to_mesh(mesh); bm.free()
body = bpy.data.objects.new("Body", mesh); bpy.context.collection.objects.link(body)
# mirror + subsurf + smooth
mir = body.modifiers.new("Mirror", "MIRROR"); mir.use_axis[0] = True; mir.use_clip = True
sub = body.modifiers.new("Subsurf", "SUBSURF"); sub.levels = 2; sub.render_levels = 2
for p in mesh.polygons: p.use_smooth = True
add_mat(body, PAINT)

# recompute outward normals
bpy.context.view_layer.objects.active = body; body.select_set(True)
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.normals_make_consistent(inside=False); bpy.ops.object.mode_set(mode="OBJECT")
body.select_set(False)

# ------------------------------------------------------------------ helpers
def cube(name, sx, sy, sz, x, y, z, m, rot=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z))
    o = bpy.context.active_object; o.name = name; o.scale = (sx, sy, sz)
    if rot: o.rotation_euler = rot
    bpy.ops.object.transform_apply(scale=True, rotation=bool(rot))
    for p in o.data.polygons: p.use_smooth = True
    add_mat(o, m); o.select_set(False); return o

def panel(name, w, h, thick, x, y, z, m, bevel=0.03):
    """A body panel (door/bonnet/boot) as a beveled slab, its own object."""
    o = cube(name, w, thick, h, x, y, z, m)
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    bev = o.modifiers.new("Bevel", "BEVEL"); bev.width = bevel; bev.segments = 2
    sub2 = o.modifiers.new("Subsurf", "SUBSURF"); sub2.levels = 1
    o.select_set(False); return o

# separate opening panels (sit flush on the flank / top)
xside = WID / 2 - 0.02
DoorFL = panel("Door_FL", 0.02, 0.66, 0.95,  xside, 0.66, 0.30, PAINT)
DoorRL = panel("Door_RL", 0.02, 0.62, 0.80,  xside, 0.66, -0.55, PAINT)
DoorFR = panel("Door_FR", 0.02, 0.66, 0.95, -xside, 0.66, 0.30, PAINT)
DoorRR = panel("Door_RR", 0.02, 0.62, 0.80, -xside, 0.66, -0.55, PAINT)
Bonnet = panel("Bonnet", 1.5, 0.04, 0.95, 0.0, 0.98, 1.34, PAINT)
Boot   = panel("Boot",   1.4, 0.55, 0.05, 0.0, 1.10, -1.75, PAINT)

# ------------------------------------------------------------------ glass
Wind = cube("Glass_Windscreen", 1.4, 0.6, 0.02, 0.0, 1.30, 0.86, GLASS, rot=(math.radians(58), 0, 0))
Rear = cube("Glass_Rear", 1.35, 0.5, 0.02, 0.0, 1.30, -1.30, GLASS, rot=(math.radians(-62), 0, 0))
Roof = cube("Glass_Roof", 1.15, 1.5, 0.02, 0.0, 1.485, 0.10, GLASS)
for zc in (0.30, -0.55):
    for xs in (xside + 0.005, -(xside + 0.005)):
        cube(f"Glass_Side_{zc}_{xs:.2f}", 0.01, 0.42, 0.62, xs, 1.20, zc, GLASS)

# ------------------------------------------------------------------ interior (visible through glass)
cube("Interior_Floor", 1.5, 0.05, 2.6, 0.0, 0.55, -0.1, INTER)
cube("Interior_Dash", 1.5, 0.28, 0.16, 0.0, 1.02, 0.80, INTER)
for zc, xs in [(0.28, 0.42), (0.28, -0.42)]:                       # front seats
    cube(f"Seat_{zc}_{xs}", 0.42, 0.5, 0.12, xs, 0.86, zc, INTER)
    cube(f"SeatBack_{zc}_{xs}", 0.42, 0.12, 0.5, xs, 1.05, zc + 0.28, INTER)
# steering wheel on the RIGHT (UK RHD)
bpy.ops.mesh.primitive_torus_add(location=(0.42, 1.02, 0.62), major_radius=0.16, minor_radius=0.02)
sw = bpy.context.active_object; sw.name = "Steering"; sw.rotation_euler = (math.radians(62), 0, 0)
bpy.ops.object.transform_apply(rotation=True); add_mat(sw, BLACK); sw.select_set(False)

# ------------------------------------------------------------------ wheels
def wheel(name, x, z):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.34, depth=0.24,
        location=(x, 0.34, z), rotation=(0, math.radians(90), 0))
    t = bpy.context.active_object; t.name = name + "_tyre"; bpy.ops.object.transform_apply(rotation=True)
    for p in t.data.polygons: p.use_smooth = True
    add_mat(t, TYRE)
    bpy.ops.mesh.primitive_cylinder_add(vertices=5, radius=0.22, depth=0.26,
        location=(x, 0.34, z), rotation=(0, math.radians(90), 0))
    r = bpy.context.active_object; r.name = name + "_alloy"; bpy.ops.object.transform_apply(rotation=True)
    add_mat(r, ALLOY)
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.14, depth=0.20,
        location=(x, 0.34, z), rotation=(0, math.radians(90), 0))
    c = bpy.context.active_object; c.name = name + "_caliper"; bpy.ops.object.transform_apply(rotation=True)
    add_mat(c, RED)
    for o in (t, r, c): o.select_set(False)
wb_x = WID / 2 - 0.02
for nm, x, z in [("Wheel_FL", wb_x, 1.28), ("Wheel_FR", -wb_x, 1.28),
                 ("Wheel_RL", wb_x, -1.32), ("Wheel_RR", -wb_x, -1.32)]:
    wheel(nm, x, z)

# ------------------------------------------------------------------ front/rear details
cube("Grille", 1.15, 0.18, 0.02, 0.0, 0.66, 2.06, BLACK)
cube("GTE_Stripe", 1.15, 0.03, 0.03, 0.0, 0.80, 2.05, GTEBLU)       # blue GTE grille line
for xs in (0.62, -0.62):
    cube(f"Headlight_{xs}", 0.34, 0.16, 0.06, xs, 0.82, 2.02, LIGHT)
    cube(f"Taillight_{xs}", 0.34, 0.20, 0.05, xs, 0.86, -2.10, RED)
cube("Splitter", 1.5, 0.06, 0.3, 0.0, 0.30, 2.08, BLACK)
cube("Diffuser", 1.5, 0.10, 0.3, 0.0, 0.30, -2.08, BLACK)
# UK plates
cube("Plate_Front", 0.52, 0.11, 0.02, 0.0, 0.42, 2.10, mat("Plate_F", (0.9,0.91,0.93,1)))
cube("Plate_Rear", 0.52, 0.11, 0.02, 0.0, 0.5, -2.12, mat("Plate_R", (0.95,0.76,0.06,1)))

# ------------------------------------------------------------------ ground + export
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=False, export_normals=True, export_tangents=False,
    export_materials="EXPORT", export_extras=True)
n = len([o for o in bpy.context.scene.objects if o.type == "MESH"])
print(f"BUILD_OK wrote {OUT} — {n} objects ({os.path.getsize(OUT)//1024} KB)")
