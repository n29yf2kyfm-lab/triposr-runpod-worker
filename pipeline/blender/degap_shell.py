"""degap_shell.py — kill the 'gaps in the doors' on generated (fused) shells.

Forensic findings this encodes (Alam 3D Golf, 2026-07-15):
  1. glTF import splits the shell at every UV-island border — 343,856 open
     edges on a 494k-vert mesh (99.6% of them UV splits, not holes). Every
     split edge is a shading discontinuity and bleeds the atlas' dark gutter
     colour: that IS the ragged dark line along doors/panels.
     -> weld by tiny distance (loops keep their UVs; texture unaffected),
        then smooth-shade: seams disappear, panels read continuous.
  2. The remaining real holes (~1.3k open edges) show the dark interior
     through the shell. -> fill small boundary loops.
  3. Baked-in shutlines are wide, dark, ragged texture lines.
     -> thin-dark-line inpaint: a dark pixel whose LOCAL median is bright is
        a line crossing a bright panel — replace it with that local median.
        Big dark regions (windows, grille) keep a dark local median, so real
        features survive. Only base-colour atlases of body materials touched.
  4. WIDE dark smears on the doors (source-photo window reflections baked
     below the beltline) survive thin-line inpaint.
     -> geometry-aware band repair: faces that are physically side panels
        (side-facing normal, beltline band, outside the wheel cylinders) must
        be paint. Their UV triangles are rasterized into a texel mask; dark
        texels inside it are pulled to the band's own bright median colour.

NOT for library/multi-part models: their panel gaps are real and wanted.

Run: blender -b -noaudio --python degap_shell.py -- in.glb out.glb
     (or: python3 degap_shell.py -- in.glb out.glb   with a pip bpy wheel)
"""
import os
import sys

import bpy
import bmesh
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from car_common import detect_axes, wheel_arches, in_wheel

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = argv[0], argv[1]
WELD = float(argv[argv.index("--weld") + 1]) if "--weld" in argv else 1e-5
MAX_HOLE = int(argv[argv.index("--maxhole") + 1]) if "--maxhole" in argv else 64

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
shell = max((o for o in bpy.context.scene.objects if o.type == "MESH"),
            key=lambda o: len(o.data.vertices))

# ---- 1+2: weld UV-split seams, fill small real holes -----------------------
bm = bmesh.new()
bm.from_mesh(shell.data)
nb0 = sum(1 for e in bm.edges if len(e.link_faces) == 1)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=WELD)
open_edges = [e for e in bm.edges if len(e.link_faces) == 1]
nb1 = len(open_edges)
bmesh.ops.holes_fill(bm, edges=open_edges, sides=MAX_HOLE)
nb2 = sum(1 for e in bm.edges if len(e.link_faces) == 1)
for f in bm.faces:
    f.smooth = True
bm.to_mesh(shell.data)
bm.free()
print(f"DEGAP mesh: open edges {nb0:,} -> weld {nb1:,} -> holes filled {nb2:,}")

# ---- 3+4: texture repair on BASE COLOUR atlases of body materials -----------
from PIL import Image, ImageDraw, ImageFilter


def _base_colour_images(mat):
    """Only the image(s) actually feeding Base Color — never the
    metallicRoughness / normal atlases."""
    out = []
    b = next((x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
    if not b:
        return out
    stack = [l.from_node for l in b.inputs["Base Color"].links]
    seen = set()
    while stack:
        n = stack.pop()
        if n.name in seen:
            continue
        seen.add(n.name)
        if n.type == "TEX_IMAGE" and n.image:
            out.append(n.image)
        stack.extend(l.from_node for i in n.inputs for l in i.links)
    return out


body_mats = [
    (i, m) for i, m in enumerate(shell.data.materials)
    if m and m.use_nodes
    and not any(k in (m.name or "") for k in ("Glass", "Wheel", "Interior"))]
body_idx = {i for i, _ in body_mats}

# ---- 4a: glass-belt correction ----------------------------------------------
# cabin_assembly tints everything above its 0.60 H beltline as glass, but a
# Golf's real side-glass bottom is ~0.65 H — the strip in between is painted
# door metal wearing a near-black glass tint: the biggest part of the "gap".
# Reassign glass faces below the real belt back to the dominant body material.
BELT = float(argv[argv.index("--belt") + 1]) if "--belt" in argv else 0.645
_vs0 = np.array([v.co[:] for v in shell.data.vertices])
_lo0, _hi0 = _vs0.min(0), _vs0.max(0)
_H0 = _hi0[2] - _lo0[2]
glass_idx = {i for i, m in enumerate(shell.data.materials)
             if m and "Glass" in (m.name or "")}
from collections import Counter
_body_faces = Counter(p.material_index for p in shell.data.polygons
                      if p.material_index in body_idx)
main_body = _body_faces.most_common(1)[0][0]
relabelled = 0
for p in shell.data.polygons:
    if p.material_index in glass_idx and \
            p.center[2] < _lo0[2] + BELT * _H0:
        p.material_index = main_body
        relabelled += 1
print(f"DEGAP belt: {relabelled:,} glass faces below {BELT}H -> body")

# geometry-aware door-band UV mask (finding 4)
vs = np.array([v.co[:] for v in shell.data.vertices])
lo, hi = vs.min(0), vs.max(0)
Hh = hi[2] - lo[2]
LA, WA = detect_axes(vs)
arch = wheel_arches(vs, LA)
uvl = shell.data.uv_layers.active.data
band_tris = []       # UV triangles of physical side-panel faces
# band reaches the corrected glass beltline: the worst smears are the baked
# window reflections directly below the windows (including the strip the
# belt correction just handed back to the body). Glass faces keep their own
# material so body_idx keeps them out of the mask.
z0, z1 = lo[2] + 0.26 * Hh, lo[2] + BELT * Hh
for p in shell.data.polygons:
    if p.material_index not in body_idx:
        continue
    c = p.center
    if not (z0 < c[2] < z1):
        continue
    if abs(p.normal[WA]) < 0.45:
        continue
    if in_wheel(c[LA], c[2], arch, radius_factor=1.30):
        continue
    band_tris.append([tuple(uvl[li].uv) for li in p.loop_indices])
print(f"DEGAP band: {len(band_tris):,} side-panel faces in beltline band")

for _, m in body_mats:
    for img in _base_colour_images(m):
        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
        rgb = (np.clip(px[..., :3], 0, 1) * 255).astype(np.uint8)
        med = np.asarray(Image.fromarray(rgb).filter(ImageFilter.MedianFilter(9)),
                         dtype=np.float32) / 255.0
        luma = px[..., :3].mean(2)
        mluma = med.mean(2)
        # 3: thin dark line inside a locally-bright neighbourhood
        thin = (luma < 0.55 * mluma) & (mluma > 0.12)
        px[thin, :3] = med[thin]
        # 4: wide dark smears inside the door band
        mimg = Image.new("L", (w, h), 0)
        dr = ImageDraw.Draw(mimg)
        for tri in band_tris:
            dr.polygon([((u % 1.0) * (w - 1), (v % 1.0) * (h - 1))
                        for u, v in tri], fill=255)
        band = np.asarray(mimg) > 0
        bl = luma[band]
        if bl.size:
            bright_ref = np.percentile(bl, 70)
            panel = px[band & (luma > 0.8 * bright_ref)][:, :3]
            panel_med = np.median(panel, axis=0) if panel.size else None
            wide = band & (luma < 0.55 * bright_ref)
            if panel_med is not None and wide.any():
                # keep 15% of the original so the repair isn't a flat decal
                px[wide, :3] = 0.85 * panel_med + 0.15 * px[wide, :3]
        img.pixels[:] = px.reshape(-1).tolist()
        img.pack()
        print(f"DEGAP texture {img.name}: thin {int(thin.sum()):,} px, "
              f"band-smear {int(wide.sum()) if bl.size else 0:,} px repaired")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_apply=True,
                          export_yup=True, export_normals=True,
                          export_materials="EXPORT")
print("DEGAP_OK", DST)
