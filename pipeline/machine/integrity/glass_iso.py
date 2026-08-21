"""Glass-only isolation render: does the Glass_Rear debris actually disappear,
and does Glass_Backlight survive? Emission-flat so nothing can hide in shading."""
import bpy, sys, os, math, mathutils
a = sys.argv[sys.argv.index("--")+1:]
GLB, OUT, AZ = a[0], a[1], float(a[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=GLB)
keep, drop = [], []
for o in list(sc.objects):
    if o.type != "MESH": continue
    (keep if "glass" in o.name.lower() else drop).append(o)
for o in drop:
    bpy.data.objects.remove(o, do_unlink=True)
print("GLASS_NODES:", sorted(o.name for o in keep))
lo=[1e18]*3; hi=[-1e18]*3
for o in keep:
    for c in o.bound_box:
        w=o.matrix_world@mathutils.Vector(c)
        for i in range(3): lo[i]=min(lo[i],w[i]); hi[i]=max(hi[i],w[i])
ctr=[(lo[i]+hi[i])/2 for i in range(3)]; span=max(hi[i]-lo[i] for i in range(3))
# one flat emissive material on every glass node — a shading trick cannot hide a hole
m=bpy.data.materials.new("ISO"); m.use_nodes=True
nt=m.node_tree; nt.nodes.clear()
e=nt.nodes.new("ShaderNodeEmission"); e.inputs[0].default_value=(1,0.25,0.05,1)
ou=nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(e.outputs[0], ou.inputs[0])
for o in keep:
    o.data.materials.clear(); o.data.materials.append(m)
w=bpy.data.worlds.new("W"); sc.world=w; w.use_nodes=True
w.node_tree.nodes["Background"].inputs[0].default_value=(0.05,0.05,0.06,1)
cd=bpy.data.cameras.new("C"); cd.lens=70
cam=bpy.data.objects.new("C",cd); sc.collection.objects.link(cam); sc.camera=cam
r=span*2.2; az=math.radians(AZ); el=math.radians(12)
cam.location=(ctr[0]+r*math.cos(az)*math.cos(el), ctr[1]+r*math.sin(az)*math.cos(el), ctr[2]+r*math.sin(el))
cam.rotation_euler=(mathutils.Vector(ctr)-cam.location).to_track_quat("-Z","Y").to_euler()
sc.render.engine="CYCLES"; sc.cycles.device="CPU"; sc.cycles.samples=8
sc.render.resolution_x=1100; sc.render.resolution_y=800
sc.view_settings.view_transform="Standard"
sc.render.image_settings.file_format="PNG"
if os.path.exists(OUT): os.remove(OUT)
sc.render.filepath=OUT
bpy.ops.render.render(write_still=True)
print("GLASSISO_DONE", OUT)
