"""Generalized proportion corrector: auto-detects the length axis, stretches
body to target L/W (wheels rigid-translated), compresses above wheel-top to
target H/W. Args: src dst target_LW target_HW"""
import bpy, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from car_common import detect_axes, body_width, wheel_arches

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, T_LW, T_HW = argv[0], argv[1], float(argv[2]), float(argv[3])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
mesh_objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if len(mesh_objs) != 1:
    # designed for fused AI shells; silently "fixing" one object of many
    # produced wrong geometry before — refuse loudly instead
    print(f"FIX_ERROR expected 1 mesh object, got {len(mesh_objs)}")
    sys.exit(1)
obj = mesh_objs[0]
me = obj.data
vs = np.array([v.co[:] for v in me.vertices])
lo, hi = vs.min(0), vs.max(0)
d = hi - lo
LA, WA = detect_axes(vs)
L, H = d[LA], d[2]
# mirror-safe width: same measure as asset_audit (lower-body percentiles)
W = body_width(vs, WA)
k_len = T_LW / (L / W)
k_h = T_HW / (H / W)
print(f"axes L={'xy'[LA]} L/W={L/W:.2f}->{T_LW} k_len={k_len:.3f} H/W={H/W:.2f}->{T_HW} k_h={k_h:.3f}")
cl = (lo[LA] + hi[LA]) / 2
arch = wheel_arches(vs, LA)
front, rear, R, czw = arch["front"], arch["rear"], arch["R"], arch["czw"]
wheel_top = lo[2] + 2.1 * R
new = vs.copy()
for i, co in enumerate(vs):
    y, z = co[LA], co[2]
    inwheel = z < wheel_top and any((y - ay) ** 2 + (z - czw) ** 2 < (R * 1.35) ** 2
                                    for ay in (front, rear))
    if inwheel:
        ay = front if abs(y - front) < abs(y - rear) else rear
        new[i, LA] = y + (cl + (ay - cl) * k_len - ay)
    else:
        new[i, LA] = cl + (y - cl) * k_len
    if z > wheel_top and not inwheel:
        new[i, 2] = wheel_top + (z - wheel_top) * k_h
for v, c in zip(me.vertices, new):
    v.co = c
nd = new.max(0) - new.min(0)
print(f"corrected L/W={nd[LA]/nd[WA]:.2f} H/W={nd[2]/nd[WA]:.2f}")
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_apply=True,
                          export_yup=True, export_normals=True, export_materials="EXPORT")
print("FIX_OK")
