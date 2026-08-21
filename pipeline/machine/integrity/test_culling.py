#!/usr/bin/env python3
"""test_culling.py — does backface culling ACTUALLY cull in Cycles?

Run: blender -b --python test_culling.py -- OUT.json

Stage 2's acceptance criterion is "no wheel disappears with backface culling
ON", so the culling switch is load-bearing: if it does not cull, that criterion
is unfalsifiable and any PASS from it is worthless. This project has found nine
such checks; this one gets a control before it is used, not after.

The control is a single plane whose normal points AWAY from the camera. Under
working culling it must VANISH (the frame goes to background); under no culling
it must stay visible. Two materials are compared:

  A) `material.use_backface_culling = True`   -- the EEVEE/viewport flag
  B) a Geometry->Backfacing node driving a Transparent BSDF mix -- shader-level

Whichever of the two actually vanishes is the one the gate is allowed to use.
"""
import json
import math
import os
import sys

import bpy
import numpy as np


def argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def scene(res=300, samples=8):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.view_settings.view_transform = "Standard"
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.0, 0.0, 0.0, 1)
    return sc


def plane(flip):
    """A 2x2 plane in the XZ world plane. Camera sits at +Y looking at -Y.
    flip=True -> normal points at the camera (+Y); flip=False -> away (-Y)."""
    me = bpy.data.meshes.new("p")
    # winding VERIFIED by cross product, not assumed: (v1-v0)x(v2-v1) for the
    # order below is (0,-4,0), i.e. the normal points -Y, AWAY from a camera at
    # +Y. So this base order is BACKfacing and `flip` makes it FRONTfacing.
    v = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)]
    f = [(0, 1, 2, 3)] if flip else [(3, 2, 1, 0)]
    me.from_pydata(v, [], f)
    me.update()
    ob = bpy.data.objects.new("p", me)
    bpy.context.collection.objects.link(ob)
    return ob


def mat_flag(cull):
    m = bpy.data.materials.new("flag")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    ou = nt.nodes.new("ShaderNodeOutputMaterial")
    em.inputs["Color"].default_value = (1, 1, 1, 1)
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(em.outputs["Emission"], ou.inputs["Surface"])
    m.use_backface_culling = cull
    return m


def mat_shader(cull):
    """Shader-level culling: backfacing -> Transparent, frontfacing -> Emission."""
    m = bpy.data.materials.new("shader")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    ou = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1, 1, 1, 1)
    if not cull:
        nt.links.new(em.outputs["Emission"], ou.inputs["Surface"])
        return m
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    nt.links.new(em.outputs["Emission"], mix.inputs[1])
    nt.links.new(tr.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], ou.inputs["Surface"])
    return m


def cam():
    cd = bpy.data.cameras.new("c")
    cd.type = "ORTHO"
    cd.ortho_scale = 3.0
    c = bpy.data.objects.new("c", cd)
    bpy.context.collection.objects.link(c)
    c.location = (0, 6, 0)
    c.rotation_mode = "QUATERNION"
    from mathutils import Vector
    c.rotation_quaternion = Vector((0, -1, 0)).to_track_quat("-Z", "Y")
    bpy.context.scene.camera = c


def shoot(path):
    bpy.context.scene.render.filepath = path
    bpy.context.scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)[:, :3]
    bpy.data.images.remove(img)
    return round(float(px.mean()), 5)


def main():
    out = argv()[0]
    tmp = os.path.join(os.path.dirname(out), "_cull")
    os.makedirs(tmp, exist_ok=True)
    res = {}
    for kind, maker in (("use_backface_culling_flag", mat_flag),
                        ("shader_backfacing_node", mat_shader)):
        row = {}
        for flip in (True, False):
            for cull in (False, True):
                scene()
                cam()
                ob = plane(flip)
                ob.data.materials.append(maker(cull))
                # LABEL FROM THE MEASURED NORMAL, never from the winding I
                # believe I wrote. Reasoning about vertex order got this
                # backwards once already, and flipping both the order and the
                # label cancelled out and hid it.
                ob.data.calc_loop_triangles()
                n = ob.data.polygons[0].normal          # object == world here
                facing = "FRONT" if n.y > 0 else "BACK"   # camera sits at +Y
                k = f"{facing}facing_cull{'ON' if cull else 'OFF'}"
                row[k] = shoot(os.path.join(tmp, f"{kind}_{k}.png"))
        # A working culler: BACKfacing+cullON goes dark, the other three stay
        # lit. THRESHOLD CALIBRATED, NOT GUESSED: a white plane filling this
        # frame measures 0.447, so an absolute ">0.5 = lit" test can never pass
        # (it did not, and briefly read as "culling is broken"). Compare each
        # cell against the MEASURED lit level instead.
        lit = row["FRONTfacing_cullOFF"]
        row["lit_reference"] = lit
        row["CULLS"] = bool(row["BACKfacing_cullON"] < 0.05 * lit
                            and row["BACKfacing_cullOFF"] > 0.8 * lit
                            and row["FRONTfacing_cullON"] > 0.8 * lit
                            and lit > 0.05)
        res[kind] = row
        print(kind, json.dumps(row))
    res["VERDICT"] = ("shader_backfacing_node"
                      if res["shader_backfacing_node"]["CULLS"] else
                      ("use_backface_culling_flag"
                       if res["use_backface_culling_flag"]["CULLS"] else "NEITHER"))
    json.dump(res, open(out, "w"), indent=1)
    print("CULL_TEST_VERDICT", res["VERDICT"])


if __name__ == "__main__":
    main()
