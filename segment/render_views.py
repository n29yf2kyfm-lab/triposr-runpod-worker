"""Step A of the multi-view back-projection segmenter.

Blender does ALL the 3D work here so the masker stays a pure-2D drop-in:
  1. import raw TRELLIS GLB, clean geometry (Merge/Loose/Normals),
     export the CLEANED mesh (both later steps use THIS, so face indices match),
  2. render N ring views of the neutral textured mesh (for the segmenter to see),
  3. for every face, dump (pixel_x, pixel_y, visible) in each view, using
     world_to_camera_view + a BVH occlusion ray + back-face cull.

Outputs into <work>/:  cleaned.glb, view_XX.png, proj.npz (px,py,vis,Wpx,Hpx),
                       geom.npz (zc, lc per face — used as a prior by the masker).

Usage: blender -b -P seg_stepA_render.py -- raw.glb <work_dir> [n_views]
"""
import bpy, sys, os, math, numpy as np, mathutils
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index("--")+1:]
RAW, WORK = argv[0], argv[1]
NV = int(argv[2]) if len(argv) > 2 else 15
os.makedirs(WORK, exist_ok=True)
Wpx, Hpx = 640, 448

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=RAW)
obj = next(o for o in bpy.data.objects if o.type == "MESH")

# ---- geometry cleanup ----
bpy.context.view_layer.objects.active = obj; obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.0002)
bpy.ops.mesh.delete_loose()
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.export_scene.gltf(filepath=f"{WORK}/cleaned.glb", export_format='GLB',
    export_apply=True, use_selection=False, export_yup=True,
    export_draco_mesh_compression_enable=False)

me = obj.data
polys = me.polygons
N = len(polys)
cent = np.array([p.center[:] for p in polys])           # world (object at origin)
nrm = np.array([p.normal[:] for p in polys])

# geometry priors (height + length position) for the masker to disambiguate
co = np.array([v.co[:] for v in me.vertices])
zmin, zr = co[:, 2].min(), max(co[:, 2].ptp(), 1e-6)
dims = [co[:, i].ptp() for i in range(3)]; L = int(np.argmax(dims))
lmin, lr = co[:, L].min(), max(dims[L], 1e-6)
zc = (cent[:, 2]-zmin)/zr
lc = (cent[:, L]-lmin)/lr
nup = np.abs(nrm[:, 2])                    # 0 vertical (side glass) .. 1 flat (roof)
np.savez(f"{WORK}/geom.npz", zc=zc, lc=lc, nup=nup)

# ---- scene: camera + soft even light so the segmenter sees clean parts ----
sc = bpy.context.scene
sc.render.engine = 'CYCLES'; sc.cycles.samples = 20; sc.cycles.device = 'CPU'
sc.cycles.use_denoising = False
sc.render.resolution_x = Wpx; sc.render.resolution_y = Hpx
try: sc.view_settings.view_transform = 'Standard'
except Exception: pass
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[1].default_value = 1.1

ctr = mathutils.Vector(cent.mean(0))
rad = float(np.linalg.norm(co - co.mean(0), axis=1).max())
cam = bpy.data.cameras.new("c"); co_ = bpy.data.objects.new("c", cam)
sc.collection.objects.link(co_); sc.camera = co_
sun = bpy.data.lights.new("s", 'SUN'); sun.energy = 3.0
so = bpy.data.objects.new("s", sun); sc.collection.objects.link(so)

# BVH for occlusion
bvh = mathutils.bvhtree.BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())

# view ring: NV azimuths cycling three elevations. (Near-overhead views were
# tried and dropped: Grounding DINO does not recognise car glass from directly
# above — top-down is out of distribution — so those views returned 0 glass. The
# ring's elev=48 tier is where SAM masks the windshield.)
views = []
els = [8.0, 26.0, 48.0]
for i in range(NV):
    az = (360.0/NV)*i
    views.append((az, els[i % 3]))

PX = np.full((NV, N), -1, np.int16); PY = np.full((NV, N), -1, np.int16)
VIS = np.zeros((NV, N), bool)
centV = [mathutils.Vector(c) for c in cent]

for vi, (az, el) in enumerate(views):
    a, e = math.radians(az), math.radians(el); D = rad*3.2
    loc = ctr + mathutils.Vector((D*math.cos(e)*math.sin(a), -D*math.cos(e)*math.cos(a), D*math.sin(e)))
    co_.location = loc
    co_.rotation_euler = (ctr-loc).to_track_quat('-Z', 'Y').to_euler()
    so.location = loc + mathutils.Vector((0, 0, rad)); so.rotation_euler = co_.rotation_euler
    sc.render.filepath = f"{WORK}/view_{vi:02d}.png"
    bpy.ops.render.render(write_still=True)
    bpy.context.view_layer.update()
    cd = np.array([(ctr-loc).normalized().x, (ctr-loc).normalized().y, (ctr-loc).normalized().z])
    facing = nrm @ cd                       # <0 = front face (normal toward camera)
    for fi in range(N):
        if facing[fi] > 0.55:               # cull only strongly back-facing faces
            continue                        # (0.15 culled the raked windshield —
                                            #  SAM masks it in 2D but the faces were
                                            #  dropped before sampling -> speckle)
        p = world_to_camera_view(sc, co_, centV[fi])
        if p.z <= 0 or not (0.0 <= p.x <= 1.0 and 0.0 <= p.y <= 1.0):
            continue
        # occlusion: cast from camera to the face centroid
        d = (centV[fi]-loc); dist = d.length
        hit, _, _, _ = bvh.ray_cast(loc, d.normalized(), dist*0.999)
        if hit is not None:
            continue
        PX[vi, fi] = int(p.x*Wpx); PY[vi, fi] = int((1.0-p.y)*Hpx); VIS[vi, fi] = True

np.savez(f"{WORK}/proj.npz", px=PX, py=PY, vis=VIS, W=Wpx, H=Hpx, nviews=NV)
print("STEPA_DONE faces=%d views=%d visfrac=%.2f -> %s" % (N, NV, VIS.mean(), WORK))
