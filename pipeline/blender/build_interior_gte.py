"""build_interior_gte.py — a reusable Golf Mk8 GTE-style interior asset,
modelled from reference photos (digital cockpit + touchscreen, houndstooth
seats with blue bolsters, GTE steering wheel, stubby e-shifter, blue ambient
strip). Generic/representative — NOT a photoreal copy of one specific car.

Drops into process_candidate.py as pipeline/components/interior.glb: it sits
inside a body shell whose greenhouse glass is transparent, so the cabin is
visible through the windows.

Run:
  blender -b -noaudio --python pipeline/blender/build_interior_gte.py -- \
      --out pipeline/components/interior.glb
Fits a ~4.26 x 1.79 x 1.45 m Golf; origin at floor centre, Y up, +Z front.
"""
import bpy, sys, os, math
argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
OUT = argv[argv.index("--out")+1] if "--out" in argv else "interior.glb"
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)

def mat(n, rgb, metal=0.0, rough=0.7, emit=None):
    m = bpy.data.materials.new(n); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Metallic"].default_value = metal; b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = 1.4
    return m
DARK   = mat("int_dark",   (0.028, 0.030, 0.035), rough=0.85)   # dash/console plastic
CLOTH  = mat("int_cloth",  (0.34, 0.35, 0.37),    rough=0.95)   # houndstooth seat centre (grey)
BOLST  = mat("int_bolster",(0.05, 0.05, 0.06),    rough=0.8)    # dark seat bolsters
BLUE   = mat("int_gte_blue",(0.02, 0.20, 0.85),   rough=0.5, emit=(0.01,0.08,0.45))  # GTE blue accent
SCREEN = mat("int_screen", (0.02, 0.03, 0.05),    rough=0.15, emit=(0.05,0.09,0.16)) # glass screens (faint glow)
WHEEL  = mat("int_wheel",  (0.02, 0.02, 0.025),   rough=0.6)

def box(name, sx, sy, sz, x, y, z, m, rot=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z))
    o = bpy.context.active_object; o.name = name; o.scale = (sx/2, sy/2, sz/2)
    if rot: o.rotation_euler = rot
    bpy.ops.object.transform_apply(scale=True, rotation=bool(rot))
    o.data.materials.append(m)
    for p in o.data.polygons: p.use_smooth = True
    return o

F = 0.62   # cabin floor height above ground
# ---- dashboard (full width) + faces the seats
box("dash", 1.70, 0.22, 0.34, 0.0, F+0.34, 1.05, DARK)
box("dash_top", 1.70, 0.06, 0.30, 0.0, F+0.46, 1.02, DARK)
# central touchscreen (portrait-ish landscape, faint glow) + driver cluster
box("touchscreen", 0.34, 0.22, 0.03, 0.0, F+0.40, 1.20, SCREEN, rot=(math.radians(-8),0,0))
box("cluster", 0.36, 0.20, 0.03, 0.44, F+0.42, 1.18, SCREEN, rot=(math.radians(-6),0,0))
# GTE blue ambient strip across the dash
box("ambient", 1.66, 0.015, 0.02, 0.0, F+0.30, 1.19, BLUE)
# ---- centre console + stubby e-shifter
box("console", 0.26, 0.22, 1.0, 0.0, F+0.14, 0.55, DARK)
box("shifter", 0.05, 0.08, 0.10, 0.0, F+0.28, 0.78, DARK)
box("shifter_blue", 0.052, 0.02, 0.10, 0.0, F+0.33, 0.78, BLUE)
# ---- steering wheel on the RIGHT (UK RHD): rim torus + GTE blue base
bpy.ops.mesh.primitive_torus_add(location=(0.46, F+0.36, 0.86), major_radius=0.17, minor_radius=0.022)
w = bpy.context.active_object; w.name = "wheel"; w.rotation_euler = (math.radians(64),0,0)
bpy.ops.object.transform_apply(rotation=True); w.data.materials.append(WHEEL)
for p in w.data.polygons: p.use_smooth = True
box("wheel_blue", 0.12, 0.02, 0.03, 0.46, F+0.24, 0.90, BLUE)

# ---- seats: squab + backrest + headrest + houndstooth centre + blue top bolster
def seat(px, zc):
    box(f"squab{px}",   0.48, 0.10, 0.52, px, F+0.10, zc, BOLST)
    box(f"squab_c{px}", 0.30, 0.11, 0.50, px, F+0.11, zc, CLOTH)      # cloth centre
    box(f"back{px}",    0.48, 0.55, 0.12, px, F+0.42, zc-0.28, BOLST)
    box(f"back_c{px}",  0.30, 0.50, 0.13, px, F+0.42, zc-0.27, CLOTH)
    box(f"headrest{px}",0.20, 0.16, 0.10, px, F+0.72, zc-0.30, BOLST)
    box(f"bolster{px}", 0.50, 0.06, 0.04, px, F+0.70, zc-0.30, BLUE)  # GTE blue top
for px in (0.44, -0.44):
    seat(px, 0.35)
# rear bench
box("rear_squab", 1.30, 0.10, 0.50, 0.0, F+0.10, -0.55, BOLST)
box("rear_squab_c", 1.10, 0.11, 0.46, 0.0, F+0.11, -0.55, CLOTH)
box("rear_back", 1.30, 0.50, 0.12, 0.0, F+0.40, -0.82, BOLST)
box("rear_back_c", 1.10, 0.46, 0.13, 0.0, F+0.40, -0.81, CLOTH)
# floor + door-card hints
box("floor", 1.55, 0.03, 2.4, 0.0, F+0.02, -0.1, DARK)
for px in (0.86, -0.86):
    box(f"doorcard{px}", 0.04, 0.5, 1.6, px, F+0.34, 0.2, DARK)
    box(f"doorcard_c{px}", 0.03, 0.16, 0.7, px, F+0.34, 0.2, CLOTH)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_materials="EXPORT")
print("INTERIOR_OK", OUT, len([o for o in bpy.context.scene.objects if o.type=="MESH"]), "parts")
