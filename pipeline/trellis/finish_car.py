#!/usr/bin/env python3
"""finish_car.py — Blender finishing pass for a generated car GLB.

Runs INSIDE Blender (it needs bpy):

    xvfb-run -a blender -b --factory-startup -noaudio \
        -P pipeline/trellis/finish_car.py -- in.glb out.glb [angle] [--no-liner]

Two defects, both MEASURED on golf_v12.glb (2026-08-13) and both invisible in
a flat-lit preview — they only show under the production studio rig, which is
why they survived every audit until the car was rendered through
render/handler.py locally.

1. NO VERTEX NORMALS AT ALL. golf_v12.glb carried NORMAL on 0 of 13
   primitives; the Hi3DGen source has none either, because trimesh's submesh
   export writes positions and indices only. With no normals a renderer falls
   back to flat per-face normals, so under clearcoat paint plus the rig's
   flank reflector cards every facet catches its own highlight and the car
   renders like crumpled foil. Fixed with angle-based auto smooth (hard edges
   above the angle survive, so shut lines and arch lips are not melted) plus
   a face-area weighted-normal modifier. Geometry is untouched.

2. HOLLOW CABIN. The generated shell has no interior (interior label 0.0% of
   faces), and the render worker forces transmission=1.0 onto any material
   whose NAME matches its glass regex — which "Glass_Tint" does. So the
   windows become genuinely clear and you see straight through to the
   brightly lit far side of the body shell: the windows read as body colour.
   PROVEN, not inferred: rendering the same GLB with a white body gives white
   windows and with a black body gives dark windows — greenhouse brightness
   tracks body colour, which only happens if you are seeing the shell through
   the glass.
   Fixed with a dark cabin liner: a box sized from the glazing's own bounding
   box, inset so it cannot poke through the doors or roof, carrying the
   Interior_Dark material the scheme already defines. This is a light blocker
   standing in for a modelled interior, not an interior — say so when
   reporting it.
"""
import math
import os
import sys

import bpy
import mathutils

INTERIOR_RGBA = (0.045, 0.045, 0.050, 1.0)
INTERIOR_ROUGHNESS = 0.9
GLASS_MAT = "Glass_Tint"
LINER_MAT = "Interior_Dark"
# Inset fractions for the liner, per axis of the glazing bbox. Width is the
# tightest because the doors are the nearest surface; the roof needs only a
# little, and the ends must clear the raked screens.
INSET = {"len": 0.06, "wid": 0.14, "up": 0.04}


def _mesh_objects():
    return [o for o in bpy.data.objects if o.type == "MESH"]


def smooth_normals(angle_deg):
    objs = _mesh_objects()
    for o in objs:
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
        bpy.ops.object.shade_smooth()
        me = o.data
        if hasattr(me, "use_auto_smooth"):        # Blender 4.0 and earlier
            me.use_auto_smooth = True
            me.auto_smooth_angle = math.radians(angle_deg)
        if not any(m.type == "WEIGHTED_NORMAL" for m in o.modifiers):
            wn = o.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
            wn.keep_sharp = True
            wn.mode = "FACE_AREA"
        o.select_set(False)
    print(f"finish_car: smoothed {len(objs)} mesh objects at {angle_deg} deg")
    return len(objs)


def _glass_objects():
    out = []
    for o in _mesh_objects():
        for s in o.material_slots:
            if s.material and s.material.name.startswith(GLASS_MAT):
                out.append(o)
                break
    return out


def add_cabin_liner(delta=None):
    """Dark backing sheet just inside the glazing.

    NOT a box. A box was tried first and fails on measurement: the Golf's
    greenhouse tapers (glass spans z 0.045-0.159 with the roof at 0.176, and
    the body narrows toward the tail), so any rectangular prism big enough to
    block the cabin punches through the rear roof — it rendered as a grey slab
    hanging out of the car. Instead the liner is the GLAZING ITSELF,
    duplicated and pushed inward along its own vertex normals, so it follows
    the greenhouse shape exactly and cannot leave the silhouette by
    construction.
    """
    glass = _glass_objects()
    if not glass:
        print("finish_car: NO GLASS MATERIAL — liner skipped")
        return False
    import bmesh

    span = max((o.dimensions.x for o in bpy.data.objects
                if o.type == "MESH"), default=1.0)
    frac = float(os.environ.get("LINER_INSET", "0.012"))
    d = delta if delta is not None else span * frac

    # REUSE the scheme's existing Interior_Dark if the transfer already wrote
    # one. Creating a second material lets Blender mint "Interior_Dark.001",
    # which is the exact `.NNN` sibling trap CLAUDE.md records against
    # paintMaterialNames — keep the name space clean rather than rely on a
    # downstream resolver.
    mat = bpy.data.materials.get(LINER_MAT)
    if mat is None:
        mat = bpy.data.materials.new(LINER_MAT)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = INTERIOR_RGBA
    bsdf.inputs["Roughness"].default_value = INTERIOR_ROUGHNESS

    # CONVEX HULL of the glazing, not an offset copy of it. Offsetting the
    # glass sheet inward along its own normals was tried and corrugates: the
    # label boundary is ragged, so every step in it becomes a ridge and the
    # windscreen rendered as slats — and a deeper offset made it worse, which
    # is what ruled out z-fighting. The hull is smooth by construction, follows
    # the greenhouse taper (unlike the box), and is a closed volume, so it
    # blocks the cabin from every angle.
    bm = bmesh.new()
    for src in glass:
        mw = src.matrix_world
        me = src.to_mesh()
        for v in me.vertices:
            bm.verts.new(mw @ v.co)
        src.to_mesh_clear()
    bm.verts.ensure_lookup_table()
    bmesh.ops.convex_hull(bm, input=bm.verts)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces],
                     context="VERTS")

    zs = [v.co.z for v in bm.verts]
    ztop, zbot = max(zs), min(zs)
    cx = sum(v.co.x for v in bm.verts) / len(bm.verts)
    cy = sum(v.co.y for v in bm.verts) / len(bm.verts)
    shrink = 1.0 - float(os.environ.get("LINER_SHRINK", "0.06"))
    drop = float(os.environ.get("LINER_DROP", "1.35"))
    for v in bm.verts:
        v.co.x = cx + (v.co.x - cx) * shrink
        v.co.y = cy + (v.co.y - cy) * shrink
        # grow DOWNWARD only: the top stays under the roof panel while the
        # bottom reaches below the beltline, so no sliver of lit far-side
        # shell shows through the bottom of a window at a low camera angle.
        v.co.z = ztop - (ztop - v.co.z) * drop

    liner = bpy.data.objects.new("cabin_liner",
                                 bpy.data.meshes.new("cabin_liner"))
    bpy.context.collection.objects.link(liner)
    bm.to_mesh(liner.data)
    bm.free()
    liner.data.materials.append(mat)
    liner.data.shade_smooth() if hasattr(liner.data, "shade_smooth") else None
    print(f"finish_car: cabin liner = convex hull of {len(glass)} glazing "
          f"object(s), shrink {shrink:.2f}, drop {drop:.2f}, "
          f"z {ztop - (ztop - zbot) * drop:.3f}..{ztop:.3f}")
    return True


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    src, dst = argv[0], argv[1]
    angle = 30.0
    for a in argv[2:]:
        if a != "--no-liner":
            angle = float(a)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    smooth_normals(angle)
    if "--no-liner" not in argv:
        add_cabin_liner()
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB",
                              export_apply=True, export_normals=True,
                              export_materials="EXPORT", export_yup=True)
    print("FINISH_OK ->", dst)


if __name__ == "__main__":
    main()
