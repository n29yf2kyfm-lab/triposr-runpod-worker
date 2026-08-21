"""Face-orientation render: BLUE = facing the camera, RED = facing away.
Cycles has no 'face orientation' overlay, so it is built from the Geometry
node's Backfacing output — the mechanism proven to work when
material.use_backface_culling was shown to do nothing in Cycles."""
import bpy, sys, os, math, mathutils
a=sys.argv[sys.argv.index("--")+1:]
GLB,OUT,AZ=a[0],a[1],float(a[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
sc=bpy.context.scene
bpy.ops.import_scene.gltf(filepath=GLB)
m=bpy.data.materials.new("FO"); m.use_nodes=True
nt=m.node_tree; nt.nodes.clear()
g=nt.nodes.new("ShaderNodeNewGeometry")
mx=nt.nodes.new("ShaderNodeMixShader")
front=nt.nodes.new("ShaderNodeEmission"); front.inputs[0].default_value=(0.10,0.28,0.85,1)
back =nt.nodes.new("ShaderNodeEmission"); back.inputs[0].default_value=(1.0,0.05,0.05,1)
ou=nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(g.outputs["Backfacing"], mx.inputs[0])
nt.links.new(front.outputs[0], mx.inputs[1])
nt.links.new(back.outputs[0],  mx.inputs[2])
nt.links.new(mx.outputs[0], ou.inputs[0])
objs=[o for o in sc.objects if o.type=="MESH"]
for o in objs:
    o.data.materials.clear(); o.data.materials.append(m)
lo=[1e18]*3; hi=[-1e18]*3
for o in objs:
    for c in o.bound_box:
        w=o.matrix_world@mathutils.Vector(c)
        for i in range(3): lo[i]=min(lo[i],w[i]); hi[i]=max(hi[i],w[i])
ctr=[(lo[i]+hi[i])/2 for i in range(3)]; span=max(hi[i]-lo[i] for i in range(3))
w=bpy.data.worlds.new("W"); sc.world=w; w.use_nodes=True
w.node_tree.nodes["Background"].inputs[0].default_value=(0.06,0.06,0.07,1)
cd=bpy.data.cameras.new("C"); cd.lens=62
cam=bpy.data.objects.new("C",cd); sc.collection.objects.link(cam); sc.camera=cam
r=span*1.6; az=math.radians(AZ); el=math.radians(14)
cam.location=(ctr[0]+r*math.cos(az)*math.cos(el), ctr[1]+r*math.sin(az)*math.cos(el), ctr[2]+r*math.sin(el))
cam.rotation_euler=(mathutils.Vector(ctr)-cam.location).to_track_quat("-Z","Y").to_euler()
sc.render.engine="CYCLES"; sc.cycles.device="CPU"; sc.cycles.samples=8
sc.render.resolution_x=1200; sc.render.resolution_y=800
sc.view_settings.view_transform="Standard"; sc.render.image_settings.file_format="PNG"
if os.path.exists(OUT): os.remove(OUT)
sc.render.filepath=OUT
bpy.ops.render.render(write_still=True)
print("FACEORIENT_DONE", OUT)
