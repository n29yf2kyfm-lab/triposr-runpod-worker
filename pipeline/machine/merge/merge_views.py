#!/usr/bin/env python3
"""merge_views.py — matched before/after renders for the merge operator.

A before/after pair is only evidence if the camera and the exposure are the
SAME in both frames. Gate 6 lost a comparison to exactly this ("the baseline's
hubs sat 100 mm higher and the pair would not have been comparable"), so the
camera boxes here are computed once, from a bbox handed in on the command
line, and reused for every file in the pair.

Conventions, all of them already paid for by this project:
  * ORTHOGRAPHIC. Every quantity in this gate is a distance in the car's own
    frame; a perspective camera photographs a symmetric car as asymmetric.
  * glTF (x, y, z) -> Blender (x, -z, y).
  * Standard view transform, never AgX. A clipped tyre has produced a false
    defect verdict for this project more than once. The world is flat 0.22
    grey and the reported background sRGB must land near 130; the number is
    printed for every frame so an exposure fault cannot be silent.
  * CYCLES with denoising OFF. This container has no OpenImageDenoiser and
    `use_denoising = True` raises AFTER "Blender quit" prints, which leaves
    STALE FRAMES behind that read as a successful render. Target frames are
    deleted before rendering and the script prints its own DONE marker; grep
    for that, never for Blender's exit.
  * A ground plane is drawn as real GEOMETRY at y = 0, so a tyre that floats
    or sinks is visible as such rather than being hidden by a shader trick.

Run:
    blender -b --python merge_views.py -- CAR.GLB OUTDIR [--paint R,G,B]
                                          [--bbox x0,y0,z0,x1,y1,z1]
                                          [--views top,front,side,hero]
"""
import json
import math
import os
import sys

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
VIEW_ALL = ("top", "front", "rear", "side", "hero")


def parse():
    a = dict(car=ARGS[0], out=ARGS[1], paint=None, bbox=None,
             views=os.environ.get("MV_VIEWS", "top,front,side,hero"),
             res=int(os.environ.get("MV_RES", "1400")),
             samples=int(os.environ.get("MV_SAMPLES", "32")))
    a["matid"] = "--matid" in ARGS
    i = 2
    while i < len(ARGS):
        if ARGS[i] == "--paint":
            a["paint"] = [float(x) for x in ARGS[i + 1].split(",")]
            i += 2
        elif ARGS[i] == "--bbox":
            a["bbox"] = [float(x) for x in ARGS[i + 1].split(",")]
            i += 2
        elif ARGS[i] == "--views":
            a["views"] = ARGS[i + 1]
            i += 2
        else:
            i += 1
    return a


def main():
    import bpy
    import mathutils
    a = parse()
    os.makedirs(a["out"], exist_ok=True)
    views = [v for v in a["views"].split(",") if v in VIEW_ALL]
    for v in views:                      # delete stale frames FIRST
        p = os.path.join(a["out"], v + ".png")
        if os.path.exists(p):
            os.remove(p)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a["car"])

    if a["matid"]:
        # Flat unique emission per material, no lights, no world: one label
        # colour per pixel, deterministic. A point-sampled shaded render cannot
        # be used to build material masks (CLAUDE.md, label_bench).
        import colorsys
        names = sorted(m.name for m in bpy.data.materials)
        for i, nm in enumerate(names):
            m = bpy.data.materials[nm]
            h = (i * 0.6180339887) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, 0.95, 1.0)
            m.use_nodes = True
            nt = m.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs[0].default_value = (r, g, b, 1)
            op = nt.nodes.new("ShaderNodeOutputMaterial")
            nt.links.new(em.outputs[0], op.inputs[0])
            m.blend_method = "OPAQUE"
        json.dump({nm: [round(c, 6) for c in colorsys.hsv_to_rgb(
            (i * 0.6180339887) % 1.0, 0.95, 1.0)]
            for i, nm in enumerate(names)},
            open(os.path.join(a["out"], "matid_colors.json"), "w"), indent=1)

    if a["paint"]:
        r, g, b = a["paint"]
        for m in bpy.data.materials:
            if m.name.lower().startswith("carpaint"):
                for n in m.node_tree.nodes:
                    if n.type == "BSDF_PRINCIPLED":
                        n.inputs["Base Color"].default_value = (r, g, b, 1.0)

    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 1 if a["matid"] else a["samples"]
    sc.cycles.use_denoising = False       # no OIDN in this container
    if os.environ.get("MV_NOGI") == "1":
        # Direct light only. The respray control needs to separate "this
        # material took the paint" from "this material is near-black and is
        # lit by bounce off a body that just changed colour". With diffuse
        # bounces off, a dark trim stops following the body hue; a genuinely
        # painted surface does not.
        sc.cycles.diffuse_bounces = 0
        sc.cycles.glossy_bounces = 0
        sc.cycles.max_bounces = 1
    sc.render.resolution_x = sc.render.resolution_y = a["res"]
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0

    world = bpy.data.worlds.new("w")
    sc.world = world
    world.use_nodes = True
    bgv = (0, 0, 0, 1) if a["matid"] else (.22, .22, .22, 1)
    world.node_tree.nodes["Background"].inputs[0].default_value = bgv
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

    # three keys, deliberately soft and symmetric so neither flank is favoured
    sc.render.filter_size = 0.01 if a["matid"] else 1.5
    for pos, e in (() if a["matid"] else
                   (((4, -6, 5), 900), ((-5, -5, 4), 700), ((0, 7, 4), 500))):
        lt = bpy.data.lights.new("k", "AREA")
        lt.energy = e
        lt.size = 5.0
        ob = bpy.data.objects.new("k", lt)
        sc.collection.objects.link(ob)
        ob.location = pos
        ob.rotation_euler = (mathutils.Vector((0, 0, 0)) - mathutils.Vector(pos)
                             ).to_track_quat("-Z", "Y").to_euler()

    # ground plane at y=0 (glTF) -> z=0 (Blender)
    if a["matid"]:
        bpy.ops.mesh.primitive_plane_add(size=0.001, location=(0, 0, -50))
    else:
        bpy.ops.mesh.primitive_plane_add(size=14, location=(0, 0, -0.0005))
    gm = bpy.data.materials.new("ground")
    gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (.30, .30, .32, 1)
    gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
    bpy.context.object.data.materials.append(gm)

    if a["bbox"]:
        x0, y0, z0, x1, y1, z1 = a["bbox"]
    else:
        lo = [1e9] * 3
        hi = [-1e9] * 3
        for ob in sc.objects:
            if ob.type != "MESH" or ob.name.startswith(("Plane", "k")):
                continue
            for c in ob.bound_box:
                w = ob.matrix_world @ mathutils.Vector(c)
                for i in range(3):
                    lo[i] = min(lo[i], w[i])
                    hi[i] = max(hi[i], w[i])
        # Blender (x, -z, y) <- glTF (x, y, z)
        x0, x1 = lo[0], hi[0]
        y0, y1 = lo[2], hi[2]
        z0, z1 = -hi[1], -lo[1]
    cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2   # glTF centre
    L, H, Wd = x1 - x0, y1 - y0, z1 - z0
    # camera target in BLENDER coords
    Cb = (cx, -cz, cy)

    cam_data = bpy.data.cameras.new("c")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("c", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam

    SPEC = dict(
        top=((0, 0, 9), max(L, Wd) * 1.10),
        front=((-9, 0, y0 + 0.35 * H), max(Wd, H) * 1.25),
        rear=((9, 0, y0 + 0.35 * H), max(Wd, H) * 1.25),
        side=((0, -9, y0 + 0.42 * H), max(L, H) * 1.10),
        hero=((-6.4, -6.4, y0 + 0.55 * H + 2.2), max(L, Wd) * 1.20),
    )
    out = {}
    for v in views:
        rel, scale = SPEC[v]
        loc = (Cb[0] + rel[0], Cb[1] + rel[1], rel[2] if v != "top" else rel[2])
        if v == "top":
            loc = (Cb[0], Cb[1], rel[2])
        cam.location = loc
        d = mathutils.Vector(Cb) - mathutils.Vector(loc)
        if v == "top":
            cam.rotation_euler = (0, 0, 0)
        else:
            cam.rotation_euler = d.to_track_quat("-Z", "Z").to_euler()
        cam_data.ortho_scale = scale
        sc.render.filepath = os.path.join(a["out"], v + ".png")
        bpy.ops.render.render(write_still=True)
        out[v] = dict(loc=list(loc), ortho_scale=scale,
                      rot=[math.degrees(x) for x in cam.rotation_euler])
    json.dump(dict(cameras=out, bbox=[x0, y0, z0, x1, y1, z1],
                   car=a["car"], paint=a["paint"]),
              open(os.path.join(a["out"], "cameras.json"), "w"), indent=1)
    print("MERGE_VIEWS_DONE", a["out"])


main()
