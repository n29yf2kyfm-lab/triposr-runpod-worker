"""normalize_shell.py — orient a raw AI/scan car shell into the library
convention that cabin_assembly / clean_export expect: length along +Y,
width along X, up along +Z, centred on origin.

AI exporters (Meshy, TRELLIS) emit Y-up with arbitrary length axis; the
finisher assumes Z-up length-along-Y. Feed the shell through here first.

Detect: longest span = length -> Y, smallest span = up -> Z, middle = width -> X.
Keeps a proper rotation (no mirroring); flips length dir if needed so det>0.
Up sign chosen so the heavier half (floor/wheels) sits low.

Run: blender -b -noaudio --python normalize_shell.py -- in.glb out.glb
"""
import bpy, sys, numpy as np, mathutils
argv = sys.argv[sys.argv.index("--")+1:]
SRC, DST = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
obj=[o for o in bpy.context.scene.objects if o.type=="MESH"][0]
bpy.context.view_layer.objects.active=obj
vs=np.array([(obj.matrix_world@v.co)[:] for v in obj.data.vertices])
lo,hi=vs.min(0),vs.max(0); span=hi-lo; cen=(lo+hi)/2; cent=vs.mean(0)
L=int(np.argmax(span)); U=int(np.argmin(span)); W=3-L-U
# columns map source axis -> target: X<-W, Y<-L, Z<-U
R=np.zeros((3,3)); R[0,W]=1; R[1,L]=1; R[2,U]=1
if np.linalg.det(R)<0: R[1,:]*=-1          # flip length dir to stay a proper rotation
if cent[U]>cen[U]: R[2,:]*=-1; 
if np.linalg.det(R)<0: R[1,:]*=-1          # keep det +1 after up flip
M=mathutils.Matrix([list(R[i])+[0] for i in range(3)]+[[0,0,0,1]])
obj.matrix_world = M @ obj.matrix_world
bpy.context.view_layer.update()
# recentre on origin, floor at z=0
vs2=np.array([(obj.matrix_world@v.co)[:] for v in obj.data.vertices])
lo2,hi2=vs2.min(0),vs2.max(0); c2=(lo2+hi2)/2
obj.location = (obj.location[0]-c2[0], obj.location[1]-c2[1], obj.location[2]-lo2[2])
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB")
d=hi2-lo2
print(f"NORMALIZE_OK L(y)={d[max(L,0)]:.2f} orig-span={span.round(2).tolist()} -> Y-length,Z-up")
