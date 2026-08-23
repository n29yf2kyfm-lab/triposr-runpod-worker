#!/usr/bin/env python3
"""glass_pass.py — give a fused generated shell real glazing.

OWNER-AUTHORED. The detection and the material below are the owner's code with
their locked thresholds (height 0.60, |normal.z| 0.45) unchanged. What is added
here is the harness -- import, join, export -- and the measured evidence, so the
pass survives a container rollback and so nobody re-tunes it from scratch.

THE PROBLEM IT SOLVES. Image-to-3D generators emit ONE fused shell.
Hunyuan3D-2's Golf is 632,402 faces with no separate glazing geometry and no
glazing material, so glass_probe reads it opaque and the owner's standing rule
scraps it. Nothing in the salvage chain helps: r8_reglaze rewrites glazing
materials that already exist, and here none does.

MEASURED, ON THAT MESH:

  version                      faces      share   result
  height 0.40, |nz| 0.58     120,260      19.0%   whole upper body transparent
  height 0.60, |nz| 0.45      43,988       7.0%   correct: windows only
  real-car band                    -    4 - 12%   (CLAUDE.md, measured)

The v1 failure was not the thresholds alone. `is_dark` was initialised True and
only overwritten when a base-colour texture was found; a generated mesh has no
texture, so every vertical face above 40% height became glass. The fallback now
decides for itself instead of defaulting to yes.

TWO THINGS TO KNOW BEFORE TOUCHING THE NUMBERS:

  * THE FALLBACK'S SIDE-FACING TEST IS A NO-OP AT THESE VALUES. Measured: of the
    43,988 faces that pass height and |nz|, `abs(nx)>0.55 or abs(ny)>0.55`
    rejects ZERO. It cannot reject any -- once |nz| <= 0.45, nx^2+ny^2 >= 0.798,
    and the worst case is a face pointing exactly diagonally, where each
    component is 0.893/sqrt(2) = 0.631, still above 0.55. So the whole
    improvement from v1 to v2 came from the two thresholds. Do NOT loosen |nz|
    back toward 0.58 believing this line is a safety net: at 0.58 the diagonal
    worst case is 0.577, which only just clears 0.55, and above that the test
    starts silently passing everything anyway.
  * |nz| <= 0.45 ACCEPTS ONLY FACES WITHIN ~27 DEGREES OF VERTICAL. A real
    hatchback windscreen is raked about 25-30 degrees from HORIZONTAL, which
    puts its |nz| near 0.87 -- far outside this filter. It does not bite on
    Hunyuan output because that model renders the screen as part of a rounded
    shell rather than a sharply raked plane. On a sharper mesh the windscreen
    would be excluded and only the side glass would convert. Check the render,
    not the count, when moving to a different generator.

THE TEXTURE PATH IS THE FRAGILE ONE, and it is fragile in a way this project has
already measured: glazing selection by albedo darkness FAILS on dark cars. On a
VW Golf R base colour, glass, dark paint and dark trim all sit at the same
near-black value, with 58% of texels under luminance 40. `lum < 0.28 and
sat < 0.20` will take dark paint with the glass on any dark car. It works when
the body contrasts with the glazing.

Run: blender -b --python glass_pass.py -- in.glb out.glb [report.json]
Env: GLASS_ALPHA (0.25) · GLASS_HEIGHT (0.60) · GLASS_MAX_NZ (0.45)
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = argv[0], argv[1]
REPORT = argv[2] if len(argv) > 2 else None

ALPHA = float(os.environ.get("GLASS_ALPHA", "0.25"))
HEIGHT = float(os.environ.get("GLASS_HEIGHT", "0.60"))
MAX_NZ = float(os.environ.get("GLASS_MAX_NZ", "0.45"))


def log(m):
    print("GLASS:", m, flush=True)


def create_glass_material():
    """Clear but realistic thin glass."""
    mat = bpy.data.materials.new("WindowGlass")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.75, 0.80, 0.85, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.06
    bsdf.inputs["IOR"].default_value = 1.45
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = 0.95
    elif "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = 0.95
    bsdf.inputs["Alpha"].default_value = ALPHA
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    # shadow_method was REMOVED in Blender 4.2+. The hasattr guard keeps this
    # harmless rather than raising, but on 4.2 and later it simply never runs.
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "HASHED"
    log("created WindowGlass material")
    return mat


def detect_and_assign_glass(obj, basecolor_img=None):
    if obj is None or obj.type != "MESH":
        return 0
    glass_mat = create_glass_material()
    if not obj.data.materials:
        obj.data.materials.append(bpy.data.materials.new("Body"))
    obj.data.materials.append(glass_mat)
    glass_idx = len(obj.data.materials) - 1
    bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not bbox:
        return 0
    zs = [v.z for v in bbox]
    z_min, z_max = min(zs), max(zs)
    z_range = max(z_max - z_min, 1e-5)
    upper_threshold = z_min + HEIGHT * z_range
    use_color = False
    pixels = None
    w = h = 0
    if basecolor_img is not None and getattr(basecolor_img, "size", [0])[0] > 0:
        try:
            w, h = basecolor_img.size[0], basecolor_img.size[1]
            # list(image.pixels) materialises w*h*4 Python floats -- 16.7 million
            # for a 2048 square. foreach_get into a numpy array is far faster if
            # this ever runs on textured meshes in bulk.
            pixels = list(basecolor_img.pixels)
            use_color = True
        except Exception:
            use_color = False
    mesh = obj.data
    uv_layer = mesh.uv_layers.active.data if mesh.uv_layers.active else None
    assigned = 0
    for poly in mesh.polygons:
        center = obj.matrix_world @ poly.center
        if center.z < upper_threshold:
            continue
        normal = (obj.matrix_world.to_3x3() @ poly.normal).normalized()
        if abs(normal.z) > MAX_NZ:
            continue
        is_window = False
        if use_color and uv_layer is not None:
            uvs = [uv_layer[li].uv for li in poly.loop_indices]
            if uvs:
                # averaging UVs across a polygon that straddles a seam samples a
                # point that belongs to neither island; harmless on a generated
                # mesh with one atlas, worth knowing on a seamed one
                u = sum(uv.x for uv in uvs) / len(uvs)
                v = sum(uv.y for uv in uvs) / len(uvs)
                px = min(max(int(u * (w - 1)), 0), w - 1)
                py = min(max(int(v * (h - 1)), 0), h - 1)
                idx = (py * w + px) * 4
                r, g, b = pixels[idx], pixels[idx + 1], pixels[idx + 2]
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                sat = max(r, g, b) - min(r, g, b)
                if lum < 0.28 and sat < 0.20:
                    is_window = True
        else:
            if abs(normal.x) > 0.55 or abs(normal.y) > 0.55:
                is_window = True
        if is_window:
            poly.material_index = glass_idx
            assigned += 1
    log(f"glass faces assigned: {assigned}")
    return assigned


# --- harness ---------------------------------------------------------------
if not os.path.exists(SRC):
    raise SystemExit(f"REFUSED: no such file: {SRC}")
with open(SRC, "rb") as f:
    if f.read(4) != b"glTF":
        raise SystemExit(f"REFUSED: {SRC} is not a GLB (bad magic)")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
obs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not obs:
    raise SystemExit(f"REFUSED: no mesh geometry in {SRC}")
for o in obs:
    o.select_set(True)
bpy.context.view_layer.objects.active = obs[0]
if len(obs) > 1:
    bpy.ops.object.join()
tgt = bpy.context.view_layer.objects.active

basecolor_img = next((i for i in bpy.data.images if "BakedBaseColor" in i.name), None)
total = len(tgt.data.polygons)
n = detect_and_assign_glass(tgt, basecolor_img)
share = n / max(total, 1)
log(f"total faces {total}  glass {n}  share {share:.1%}")
# The count is the cheap check, not the verdict -- 4-12% is the real-car band,
# and anything outside it means the selector took bodywork or missed the glass.
if not 0.04 <= share <= 0.12:
    log(f"WARNING share {share:.1%} is OUTSIDE the 4-12% real-car band -- LOOK at "
        f"the render before shipping this")
bpy.ops.object.shade_smooth()
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
log(f"exported {DST}")
if REPORT:
    json.dump({"in": SRC, "out": DST, "faces_total": total, "faces_glass": n,
               "share": round(share, 4), "alpha": ALPHA, "height": HEIGHT,
               "max_nz": MAX_NZ, "textured": basecolor_img is not None},
              open(REPORT, "w"), indent=2)
log("DONE")
