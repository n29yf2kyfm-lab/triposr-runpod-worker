#!/usr/bin/env python3
"""body_probe.py — find which material is actually the BODY, by painting it.

THE PROBLEM. `paintMaterialNames` is picked heuristically by the render worker,
and on a scraped GLB the material NAMED like paint is routinely not the body.
Measured on hyundai-tucson-2022 (2026-08-14): its `Carpaint_Simple_Onyx2` is the
B/C-pillar covers, roof rails and window surrounds; `Carpaint_Simple_Onyx3` is
the wheel spokes; the actual body skin is `Material_2125670220`, a junk name no
regex would ever pick. The eight colour variants baked off the wrong name were
byte-different and visually identical -- recolour_audit dist=0.038 -- which is
the same failure CLAUDE.md records for toyota-corolla-cross (dist=0.004) and for
Toyota #41 rendering pink under `--colour silver`.

WHY A NAME GATE CANNOT FIX IT, and why this does not repeat clay_geoclass. The
name carries no reliable signal here: the misleading material is the one that
says "Carpaint". Nor is this the GEOMETRIC classification that `clay_geoclass`
tried and failed -- that inferred class from bbox and area and got the Juke's
interior and body backwards, because a material's union bbox spans the whole car
when it is scattered across many pieces. This probe does not infer anything from
geometry. It PAINTS a candidate and LOOKS, which is the cross-check CLAUDE.md
already endorses for tyres ("rewrite the tyre material and re-render; if the
tyre changes, that material really is on the tyre"). The evidence is the render,
not a theory about the mesh.

METHOD. Rank plausible candidates (opaque, not glass/tyre/lamp/interior by name,
carrying real vertex share), then for each: respray it magenta, render one 3/4
view, and measure what fraction of the car's silhouette turned magenta. The body
is the candidate that moves the most pixels. Reports the whole ranking, not just
a winner, so a car whose paint is legitimately split across two panels' worth of
materials is visible as two strong candidates rather than silently halved.

Magenta is used rather than red because nothing on a car is magenta: red would
be indistinguishable from tail lamps and brake calipers.

NOT a replacement for `body_candidates.py`, which solves the OTHER half of this
problem: paint SPLIT across sibling materials of one colour (Paint2..Paint8),
found by clustering baseColorFactor. The two fail on opposite cars, so reach for
the right one. Clustering cannot resolve the Tucson -- measured, not assumed:
its real body material sits in a 13-strong cluster at [0.12,0.12,0.13] together
with `steel`, `Material_134` and the rest of the trim (clay_rebuild gives every
dark trim class the same value), so the cluster is the whole car minus the
paint-named decoys. Conversely this probe would report a split-paint car as one
weak candidate among several, which is exactly what its "paint appears SPLIT"
line is for -- take every material it lists above the threshold, not just the
winner.

Usage:
  body_probe.py --glb car.glb [--top 5] [--json out.json] [--keep-renders DIR]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "pipeline", "ingest"))
sys.path.insert(0, os.path.join(REPO, "pipeline", "publish"))

from pose_fix import (load_glb, world_points, read_accessor,   # noqa: E402
                      _node_matrix)
import respray_gltf                                 # noqa: E402

# Names that are never the body. Deliberately conservative: this only removes
# candidates, and a name it fails to exclude simply costs one extra render.
# COLOUR WORDS MUST SURVIVE THE LAMP RULE. Measured on the 2026 Clio: its body
# material is `M_0132_LightGray`, and `light` ate it -- the car then had NO body
# candidate at all and the probe reported "no confident body material" on a car
# whose body was sitting right there. This is the same class as CLAUDE.md's
# `backlight_glass` trap, reproduced here; the lamp rule now requires `light`
# NOT to be followed by a colour word.
SKIP_RE = (
    r"glass|window|windscreen|windshield|"
    r"tire|tyre|rubber|"
    r"lamp|light(?!\s*_?\s*(gray|grey|blue|green|red|brown|beige|silver))|"
    r"drl|blink|indicat|"
    r"interior|seat|dash|leather|fabric|carpet|"
    r"plate|badge|emblem|logo|"
    r"brake|caliper|rotor|disc"
)

MAGENTA = "ff00ff"

BLENDER = r'''
import bpy, sys, mathutils
from mathutils import Vector
argv = sys.argv[sys.argv.index("--")+1:]
src, out = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs=[o for o in bpy.context.scene.objects if o.type=="MESH"]
mn=Vector((1e18,)*3); mx=Vector((-1e18,)*3)
for o in objs:
    for c in o.bound_box:
        w=o.matrix_world @ Vector(c)
        for i in range(3):
            mn[i]=min(mn[i],w[i]); mx[i]=max(mx[i],w[i])
ctr=(mn+mx)/2; dim=mx-mn; radius=max(dim)/2
w=bpy.data.worlds.new("W"); bpy.context.scene.world=w; w.use_nodes=True
w.node_tree.nodes["Background"].inputs[0].default_value=(0.22,0.22,0.24,1)
def light(loc,e):
    d=bpy.data.lights.new("L",type="AREA"); d.energy=e; d.size=radius*2
    ob=bpy.data.objects.new("L",d); ob.location=loc
    bpy.context.collection.objects.link(ob)
    t=ob.constraints.new("TRACK_TO"); em=bpy.data.objects.new("T",None)
    em.location=ctr; bpy.context.collection.objects.link(em); t.target=em
p=radius*4
light((ctr.x+p,ctr.y-p,ctr.z+p),700*radius*radius)
light((ctr.x-p,ctr.y+p,ctr.z+p*0.6),380*radius*radius)
cd=bpy.data.cameras.new("C"); cd.type="ORTHO"
cam=bpy.data.objects.new("C",cd); bpy.context.collection.objects.link(cam)
bpy.context.scene.camera=cam
sc=bpy.context.scene
sc.render.engine="CYCLES"; sc.cycles.device="CPU"; sc.cycles.samples=12
sc.cycles.use_denoising=False
# film_transparent gives a clean alpha silhouette, so "share of the CAR" needs
# no background subtraction and no chroma key against the backdrop.
sc.render.film_transparent=True
sc.render.image_settings.file_format="PNG"
sc.render.image_settings.color_mode="RGBA"
sc.view_settings.view_transform="Standard"; sc.view_settings.look="None"
order=sorted(range(3), key=lambda i:-dim[i]); LONG,WIDE,UP=order
dist=radius*3.0
loc=[ctr.x,ctr.y,ctr.z]; loc[LONG]+=dist*0.75; loc[WIDE]-=dist*0.75; loc[UP]+=radius*0.45
loc=mathutils.Vector(loc)
fwd=(ctr-loc).normalized()
up=mathutils.Vector((0,0,0)); up[UP]=1.0
right=fwd.cross(up)
if right.length<1e-6:
    up=mathutils.Vector((0,0,0)); up[(UP+1)%3]=1.0; right=fwd.cross(up)
right.normalize(); tu=right.cross(fwd).normalized()
cam.matrix_world=mathutils.Matrix((
 (right.x,tu.x,-fwd.x,loc.x),(right.y,tu.y,-fwd.y,loc.y),
 (right.z,tu.z,-fwd.z,loc.z),(0,0,0,1)))
cd.clip_start=max(radius*0.001,1e-4); cd.clip_end=radius*50
cd.ortho_scale=max(dim)*1.12
sc.render.resolution_x=420; sc.render.resolution_y=420
sc.render.filepath=out
bpy.ops.render.render(write_still=True)
'''


def _tri_area(js, bin_, pr, W):
    """World-space surface area of one primitive, or None if unindexed."""
    pos = pr.get("attributes", {}).get("POSITION")
    if pos is None:
        return 0.0
    V = read_accessor(js, bin_, pos)
    Vw = (W[:3, :3] @ V.T).T + W[:3, 3]
    ia = pr.get("indices")
    I = (read_accessor(js, bin_, ia).astype(np.int64).ravel()
         if ia is not None else np.arange(len(Vw)))
    n = (len(I) // 3) * 3
    if n < 3:
        return 0.0
    T = Vw[I[:n].reshape(-1, 3)]
    return float(0.5 * np.linalg.norm(
        np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1).sum())


def material_area(glb):
    """{material name: world-space surface area}.

    RANK BY AREA, NOT VERTEX COUNT. Vertex share is a bad proxy for how much of
    the car a material covers, and it cost a real miss: on the 2026 Clio the
    body is 18.4% of AREA but only 4.8% of verts, while the tyres/arches/interior
    material is 66.1% of area at 39.5% of verts. A smooth body panel is
    vertex-CHEAP -- it is a few big quads -- whereas tyres, arch liners and
    interiors are vertex-dense. Ranking by verts pushed the body off the end of
    the candidate list entirely.
    """
    js, bin_ = load_glb(glb)
    nodes = js.get("nodes", [])
    mats = js.get("materials", [])
    roots = []
    for s in js.get("scenes", [{}]):
        roots += s.get("nodes", [])
    if not roots:
        roots = list(range(len(nodes)))
    area = {}

    def walk(i, M):
        nd = nodes[i]
        W = M @ _node_matrix(nd)
        if "mesh" in nd:
            for pr in js["meshes"][nd["mesh"]].get("primitives", []):
                mi = pr.get("material")
                nm = mats[mi].get("name", "") if mi is not None and mi < len(mats) else ""
                area[nm] = area.get(nm, 0.0) + _tri_area(js, bin_, pr, W)
        for c in nd.get("children", []):
            walk(c, W)

    for r in roots:
        walk(r, np.eye(4))
    return area


def candidates(glb, top):
    """Plausible body materials, largest surface area first."""
    import re
    js, bin_ = load_glb(glb)
    prims = world_points(js, bin_)
    area = material_area(glb)
    tot_area = sum(area.values()) or 1.0
    alpha = {}
    for m in js.get("materials", []):
        pbr = m.get("pbrMetallicRoughness", {})
        bc = pbr.get("baseColorFactor") or [1, 1, 1, 1]
        alpha[m.get("name", "")] = (bc[3] if len(bc) > 3 else 1.0,
                                    m.get("alphaMode", "OPAQUE"))
    agg = {}
    for nm, V in prims:
        a = agg.setdefault(nm, [0, None])
        a[0] += len(V)
        bb = np.vstack([V.min(0), V.max(0)])
        a[1] = bb if a[1] is None else np.vstack(
            [np.minimum(a[1][0], bb[0]), np.maximum(a[1][1], bb[1])])
    tot = sum(v[0] for v in agg.values()) or 1
    full = None
    for v in agg.values():
        e = v[1][1] - v[1][0]
        full = e if full is None else np.maximum(full, e)
    skip = re.compile(SKIP_RE, re.I)
    rows = []
    for nm, (n, bb) in agg.items():
        if not nm or skip.search(nm):
            continue
        al, mode = alpha.get(nm, (1.0, "OPAQUE"))
        if al < 0.99 or mode != "OPAQUE":
            continue                      # transparent things are not paint
        ext = bb[1] - bb[0]
        span = float(np.mean(ext / np.maximum(full, 1e-9)))
        rows.append({"name": nm, "verts": n, "vert_share": round(n / tot, 4),
                     "area_share": round(area.get(nm, 0.0) / tot_area, 4),
                     "bbox_span": round(span, 3)})
    # a body material must both cover ground and reach across the car
    rows.sort(key=lambda r: -(r["area_share"] * (0.25 + r["bbox_span"])))
    return rows[:top]


def render(glb, png):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(BLENDER); script = f.name
    try:
        subprocess.run(["xvfb-run", "-a", "blender", "-b", "--factory-startup",
                        "-noaudio", "-P", script, "--", glb, png],
                       capture_output=True, text=True, timeout=600)
    finally:
        os.unlink(script)
    return os.path.exists(png)


def magenta_share(png):
    """Fraction of the car's silhouette that reads magenta."""
    from PIL import Image
    im = np.asarray(Image.open(png).convert("RGBA"), dtype=np.float32) / 255.0
    a = im[..., 3]
    fg = a > 0.6
    if fg.sum() < 100:
        return 0.0, 0
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    mag = fg & (r > 0.22) & (b > 0.22) & (g < 0.55 * np.minimum(r, b))
    return float(mag.sum() / fg.sum()), int(fg.sum())


def probe(glb, top=5, keep=None):
    cands = candidates(glb, top)
    tmp = tempfile.mkdtemp(prefix="bodyprobe_")
    out = []
    for c in cands:
        gp = os.path.join(tmp, "p.glb")
        pn = os.path.join(keep or tmp, f"probe_{c['name'][:24].replace('/','_')}.png")
        try:
            respray_gltf.respray(glb, gp, [c["name"]], MAGENTA)
        except Exception as e:
            c.update(share=None, note=f"respray failed: {type(e).__name__}")
            out.append(c); continue
        if not render(gp, pn):
            c.update(share=None, note="render failed")
            out.append(c); continue
        share, fgpx = magenta_share(pn)
        c.update(share=round(share, 4), fg_px=fgpx)
        out.append(c)
    out.sort(key=lambda r: -(r.get("share") or -1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--top", type=int, default=5,
                    help="how many candidates to paint and render (default 5)")
    ap.add_argument("--json", help="write the full ranking here")
    ap.add_argument("--keep-renders", help="directory to keep the probe renders in")
    a = ap.parse_args()
    if a.keep_renders:
        os.makedirs(a.keep_renders, exist_ok=True)
    rows = probe(a.glb, a.top, a.keep_renders)
    print(f"{'material':38s} {'area%':>7s} {'vert%':>7s} {'span':>6s} {'PAINTED':>8s}")
    for r in rows:
        sh = "  n/a" if r.get("share") is None else f"{100*r['share']:6.1f}%"
        print(f"  {r['name'][:36]:36s} {100*r['area_share']:6.1f}% "
              f"{100*r['vert_share']:6.1f}% {r['bbox_span']:6.2f} {sh}"
              + (f"   {r['note']}" if r.get("note") else ""))
    best = rows[0] if rows and rows[0].get("share") else None
    if best and best["share"] >= 0.15:
        print(f"\nBODY: {best['name']}  ({100*best['share']:.1f}% of the silhouette)")
        rest = [r for r in rows[1:] if (r.get("share") or 0) >= 0.15]
        if rest:
            # ADVISORY, not an instruction to add them. Measured on the Juke:
            # `black_matt` moves 17% and is the car's genuine unpainted body
            # cladding, which must NOT be resprayed. A second strong candidate
            # means "look at these two renders", not "paint both".
            print("  also moves a real share (CHECK BY EYE — may be genuine "
                  "unpainted cladding, not split paint): "
                  + ", ".join(f"{r['name']} ({100*r['share']:.0f}%)" for r in rest))
    else:
        print("\nNO CONFIDENT BODY MATERIAL — highest candidate moves "
              f"{0 if not best else round(100*best['share'],1)}% of the silhouette. "
              "Route to the eye; do not bake colours off a guess.")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)
        print(f"wrote {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
