import bpy, sys, math, mathutils
argv = sys.argv[sys.argv.index("--")+1:]
GLB, OUT, DROP = argv[0], argv[1], argv[2]   # DROP: csv of object keywords to delete
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
drops = [d for d in DROP.split(",") if d]
for o in list(bpy.data.objects):
    if o.type == 'MESH' and any(k.lower() in o.name.lower() for k in drops):
        bpy.data.objects.remove(o, do_unlink=True)
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
# worker-style glass: force transmission on the glass material
for m in bpy.data.materials:
    if "glass" in m.name.lower():
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Transmission Weight"].default_value = 1.0
            bsdf.inputs["Base Color"].default_value = (0.18, 0.20, 0.22, 1)
            bsdf.inputs["Roughness"].default_value = 0.0
            bsdf.inputs["IOR"].default_value = 1.45
            bsdf.inputs["Alpha"].default_value = 1.0
        m.blend_method = 'OPAQUE'
mn = mathutils.Vector((1e9,)*3); mx = mathutils.Vector((-1e9,)*3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        mn = mathutils.Vector(map(min, mn, w)); mx = mathutils.Vector(map(max, mx, w))
ctr = (mn+mx)/2; size = max(mx-mn)
scn = bpy.context.scene
scn.render.engine='CYCLES'; scn.cycles.device='CPU'; scn.cycles.samples=64
scn.cycles.use_denoising=False
scn.view_settings.view_transform='Standard'
scn.render.resolution_x=1100; scn.render.resolution_y=650
w = bpy.data.worlds.new("w"); w.use_nodes=True
w.node_tree.nodes["Background"].inputs[0].default_value=(0.9,0.9,0.92,1)  # BRIGHT, like the studio
w.node_tree.nodes["Background"].inputs[1].default_value=1.5
scn.world = w
sun=bpy.data.objects.new("s",bpy.data.lights.new("s","SUN")); scn.collection.objects.link(sun)
sun.data.energy=4; sun.rotation_euler=(math.radians(55),0,math.radians(35))
cam=bpy.data.objects.new("c",bpy.data.cameras.new("c")); scn.collection.objects.link(cam); scn.camera=cam
a=math.radians(125); e=math.radians(10); d=size*1.75
cam.location=(ctr.x+d*math.cos(e)*math.sin(a), ctr.y-d*math.cos(e)*math.cos(a), ctr.z+d*math.sin(e))
cam.rotation_euler=(mathutils.Vector(ctr)-cam.location).to_track_quat('-Z','Y').to_euler()
scn.render.filepath=OUT
bpy.ops.render.render(write_still=True)
print("BISECT_DONE", OUT)
