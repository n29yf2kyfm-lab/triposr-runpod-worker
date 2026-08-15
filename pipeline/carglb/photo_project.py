#!/usr/bin/env python3
"""photo_project.py — bake the capture photos onto the finished car's body.

THE IDENTITY FIX. The assembled car has correct panel forms but reads generic:
no grille graphic, no lamp shapes, no badges. Those details are sub-pixel at
the viewer's 5mm/px (measured, STUDY_3D.md) — they belong in TEXTURE, sampled
from the very photos the car was generated from. The earlier photo_skin
attempt failed on a featureless parametric blob; here the mesh has real
apertures and panel forms, so the photo's grille lands ON the modelled grille.

METHOD — box-projection atlas, no unwrap:
  * split body faces into 6 groups by dominant normal (left/right/front/
    back/top/bottom in the car frame: X length, Y up, Z width);
  * each group gets one cell of a 3x2 texture atlas; UVs are the planar
    projection of the face's vertices in that cell — for the four principal
    groups this matches the ORTHOGRAPHIC capture photos exactly, so the bake
    is a direct resample of the photo into the cell;
  * vertices are split per group (a vertex shared by a side face and a roof
    face needs different UVs — same mechanics as the crease split);
  * top/bottom cells carry flat paint (no orthographic top photo in the
    contract; the roof is featureless anyway).

RESPRAY TRADE, stated plainly: the photo bakes the CAPTURE car's colour into
baseColorTexture. factor x texture still tints, but over silver paint a blue
respray reads muted. Ship the textured build as the HERO/identity variant and
keep the flat-paint build for the 8-colour swatches — same policy as the
authored cars' skin.

Usage:
    python3 pipeline/carglb/photo_project.py car.glb photos_dir out.glb
photos_dir must hold front.png rear.png left.png right.png (RGBA cutouts).
"""
import io
import os
import sys

import numpy as np
import trimesh
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "authoring"))
from glb import GLB                                            # noqa: E402

ATLAS = 2048
CELL_W, CELL_H = ATLAS // 3, ATLAS // 2
# group -> (atlas cell col,row), photo, plane axes (u_axis, v_axis), flips
GROUPS = {
    "left":  ((0, 0), "left.png",  (0, 1)),
    "right": ((1, 0), "right.png", (0, 1)),
    "front": ((2, 0), "front.png", (2, 1)),
    "back":  ((0, 1), "rear.png",  (2, 1)),
    "top":   ((1, 1), None,        (0, 2)),
    "bottom": ((2, 1), None,       (0, 2)),
}


def alpha_bbox(im):
    a = np.asarray(im.convert("RGBA"))[:, :, 3]
    ys, xs = np.where(a > 24)
    return xs.min(), ys.min(), xs.max(), ys.max()


def paint_colour(photos_dir):
    """Median RGB of the DOOR-SKIN band of a side photo.

    The first render (tex_az125, 2026-08-15) proved why this matters: the
    top/bottom cells carried neutral grey and the whole bonnet+roof rendered
    silver on a dark-red car — a jarring two-tone. The roof is body colour,
    so sample the body: opaque pixels between 45%% and 62%% of the car's
    height (below the glass, above the sill shadow).
    """
    for cand in ("left.png", "right.png", "front.png", "rear.png"):
        path = os.path.join(photos_dir, cand)
        if not os.path.exists(path):
            continue
        im = np.asarray(Image.open(path).convert("RGBA"))
        x0, y0, x1, y1 = alpha_bbox(Image.open(path))
        band0 = y0 + int(0.45 * (y1 - y0))
        band1 = y0 + int(0.62 * (y1 - y0))
        cut = im[band0:band1, x0:x1]
        px = cut[cut[:, :, 3] > 200][:, :3]
        if len(px) > 500:
            col = tuple(int(c) for c in np.median(px, axis=0))
            print(f"  paint colour from {cand} door band: {col}")
            return col
    return (184, 186, 190)


def group_of(n):
    ax = int(np.argmax(np.abs(n)))
    if ax == 2:
        return "left" if n[2] > 0 else "right"
    if ax == 0:
        return "front" if n[0] > 0 else "back"
    return "top" if n[1] > 0 else "bottom"


def bake(car_glb, photos_dir, out_glb, nose_positive_x=True):
    scene = trimesh.load(car_glb)
    body = scene.geometry.get("body")
    if body is None:
        raise SystemExit("no 'body' geometry in the car GLB")
    V = np.asarray(body.vertices)
    F = np.asarray(body.faces)
    N = body.face_normals
    lo, hi = V.min(0), V.max(0)
    ext = hi - lo

    # ---- build the atlas ---------------------------------------------------
    paint = paint_colour(photos_dir)
    atlas = Image.new("RGB", (ATLAS, ATLAS), paint)
    for gname, ((cc, cr), photo, (ua, va)) in GROUPS.items():
        if photo is None:
            continue
        path = os.path.join(photos_dir, photo)
        if not os.path.exists(path):
            print(f"  photo missing for {gname}: {photo} — flat paint")
            continue
        im = Image.open(path).convert("RGBA")
        x0, y0, x1, y1 = alpha_bbox(im)
        crop = im.crop((x0, y0, x1 + 1, y1 + 1))
        # composite over the sampled paint so transparent pixels match the car
        bg = Image.new("RGBA", crop.size, paint + (255,))
        crop = Image.alpha_composite(bg, crop).convert("RGB")
        cell = crop.resize((CELL_W, CELL_H), Image.LANCZOS)
        atlas.paste(cell, (cc * CELL_W, cr * CELL_H))
    buf = io.BytesIO()
    atlas.save(buf, "PNG", optimize=True)
    atlas_png = buf.getvalue()

    # ---- per-group vertex split + UVs -------------------------------------
    # nose direction decides which photo is 'front'. If the badge ends up on
    # the wrong end, flip nose_positive_x — one boolean, checked by render.
    newV, newUV, newF = [], [], []
    index = {}
    for fi, face in enumerate(F):
        g = group_of(N[fi])
        (cc, cr), photo, (ua, va) = GROUPS[g]
        tri = []
        for vi in face:
            key = (vi, g)
            if key not in index:
                p = V[vi]
                u = (p[ua] - lo[ua]) / max(ext[ua], 1e-9)
                v = (p[va] - lo[va]) / max(ext[va], 1e-9)
                # orient each cell to match its photo's orientation
                if g in ("left", "front"):
                    u = u if nose_positive_x else 1 - u
                if g in ("right", "back"):
                    u = 1 - u if nose_positive_x else u
                v = 1 - v                      # image y grows downward
                cu = (cc * CELL_W + u * (CELL_W - 2) + 1) / ATLAS
                cv = (cr * CELL_H + v * (CELL_H - 2) + 1) / ATLAS
                index[key] = len(newV)
                newV.append(p)
                newUV.append([cu, cv])
            tri.append(index[key])
        newF.append(tri)
    newV = np.array(newV)
    newUV = np.array(newUV)
    newF = np.array(newF, dtype=np.uint32)
    print(f"body: {len(F)} faces, split to {len(newV)} verts across groups")

    # ---- reassemble the whole car through the writer ----------------------
    g = GLB(generator="carglb/photo_project")
    tex = g.texture(atlas_png)
    mats = {
        "carpaint": g.material("carpaint", [1.0, 1.0, 1.0, 1.0], 0.10, 0.35,
                               base_tex=tex),
        "Glass_Tint": g.material("Glass_Tint", [0.03, 0.04, 0.05, 0.26],
                                 0.0, 0.05, blend=True),
        "Tyre_Rubber": g.material("Tyre_Rubber", [0.026, 0.026, 0.030, 1.0],
                                  0.0, 0.92),
        "Rim_Alloy": g.material("Rim_Alloy", [0.52, 0.53, 0.55, 1.0],
                                0.92, 0.28),
        "Arch_Cavity": g.material("Arch_Cavity", [0.016, 0.016, 0.016, 1.0],
                                  0.0, 0.9),
        "flat": g.material("carpaint_flat",
                           [(paint[0] / 255) ** 2.2, (paint[1] / 255) ** 2.2,
                            (paint[2] / 255) ** 2.2, 1.0], 0.10, 0.28),
    }
    root = g.group("car")
    g.mesh("body", newV, newF, mats["carpaint"], parent=root, uvs=newUV)

    def mat_for(name, geom):
        # match by the material name trimesh carried through, else by geometry
        # name conventions from fit_panes/wheel_swap
        mname = getattr(getattr(geom, "visual", None), "material", None)
        mname = getattr(mname, "name", "") or ""
        for k in ("Glass_Tint", "Tyre_Rubber", "Rim_Alloy", "Arch_Cavity"):
            if k.lower() in mname.lower():
                return mats[k]
        if name.startswith("glass"):
            return mats["Glass_Tint"]
        if "tyre" in name.lower() or name == "wheel":
            return mats["Tyre_Rubber"]
        if "rim" in name.lower():
            return mats["Rim_Alloy"]
        return mats["flat"]

    for name, geom in scene.geometry.items():
        if name == "body":
            continue
        g.mesh(name, np.asarray(geom.vertices), np.asarray(geom.faces),
               mat_for(name, geom), parent=root)
    size = g.save(out_glb)
    print(f"wrote {out_glb} ({size/1e6:.1f}MB), atlas {ATLAS}px")
    return out_glb


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    bake(sys.argv[1], sys.argv[2], sys.argv[3],
         nose_positive_x=(len(sys.argv) < 5 or sys.argv[4] != "flip"))
