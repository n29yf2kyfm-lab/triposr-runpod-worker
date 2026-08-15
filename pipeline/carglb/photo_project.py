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
  * the top cell carries the PAINT colour sampled from a side photo's door
    band (neutral grey rendered a silver-roofed two-tone car — measured);
    the bottom cell is CABIN dark for the underbody and roof lining;
  * front/back faces are DEPTH-SPLIT: Hi3DGen wraps one skin through the
    apertures, so those groups contain both the scuttle and the passage
    behind the windscreen. Exterior = within a margin of the cell's
    outermost surface; passage faces go to the dark cell (paint there would
    read as body-coloured windows). Exterior faces above CLAMP height get
    paint — the photo shows glass at that height, and baking it painted a
    white marble patch on the bonnet (measured, tex_az125).

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
    # review finding 10: falling back to an END photo samples the grille/
    # lamp strip as "door skin" and paints the car grille-black. Sides only.
    for cand in ("left.png", "right.png"):
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
    print("WARNING: no SIDE photo for paint sampling — using neutral grey "
          "(door-skin colour needs left.png or right.png)")
    return (184, 186, 190)


def group_of(n, nose_pos=True):
    """Review finding 1: with nose +X and Y up (right-handed),
    right = forward x up = X x Y = ... -Z?? No: X x Y = +Z is UP-relative —
    the CAR's right side is -Z when facing +X? Work it as a driver: facing
    +X with up +Y, the LEFT hand points along +Z (Y x X = +Z... ). The
    reviewer's evaluated table is the authority: +Z faces were being fed
    left.png and every cell came out mirrored. +Z is the car's RIGHT when
    the nose is +X. nose_pos flips both ends AND handedness together.
    """
    ax = int(np.argmax(np.abs(n)))
    if ax == 2:
        if nose_pos:
            return "right" if n[2] > 0 else "left"
        return "left" if n[2] > 0 else "right"
    if ax == 0:
        if nose_pos:
            return "front" if n[0] > 0 else "back"
        return "back" if n[0] > 0 else "front"
    return "top" if n[1] > 0 else "bottom"


# Above this height fraction the photos show GLASS, not body — baking those
# pixels put a white marble patch on the bonnet (front photo's windscreen at
# scuttle height, measured tex_az125) and white streaks along the cant rails
# (side photos' DLO reflections, measured tex4_az125). Exterior faces above
# the line get paint instead.
CLAMP = {"front": 0.53, "back": 0.58, "left": 0.58, "right": 0.58}
CABIN = (36, 36, 40)          # what interior passage skin + underbody get

# outward axis and sign per photo group (authoring frame: X length, Y up,
# Z width)
# Signs must FOLLOW group_of's naming (they did not, and after the
# handedness fix every exterior side face tested as interior -> the whole
# flank baked cabin-dark; caught in the mirror-check render). With nose +X:
# right = +Z, left = -Z. out_axis() flips all four when the nose is -X,
# exactly as group_of swaps its labels.
def out_axis(nose_pos=True):
    s = 1 if nose_pos else -1
    return {"front": (0, +s), "back": (0, -s),
            "right": (2, +s), "left": (2, -s)}


OUT_AXIS = out_axis(True)          # legacy import surface


def depth_map(C, groups, gname, lo, ext, res=96, oax=None):
    """Per cell, the outermost surface offset of this group's faces.

    Splits EXTERIOR skin from the CABIN PASSAGE skin behind the glass panes:
    Hi3DGen wraps one continuous surface through the window apertures, so
    'front'-group faces include both the scuttle AND the surface behind the
    windscreen — and the passage baked the photo's glass pixels as white
    marble. A face is exterior iff it sits within a margin of the outermost
    surface in its cell.
    """
    sel = np.array([g == gname for g in groups])
    dm = np.full((res, res), -np.inf)
    if not sel.any():
        return sel, dm
    ax, sgn = (oax or OUT_AXIS)[gname]
    ua = 2 if ax == 0 else 0            # cell plane = (other horizontal, up)
    u = np.clip(((C[sel, ua] - lo[ua]) / max(ext[ua], 1e-9) * (res - 1)), 0,
                res - 1).astype(int)
    v = np.clip(((C[sel, 1] - lo[1]) / max(ext[1], 1e-9) * (res - 1)), 0,
                res - 1).astype(int)
    np.maximum.at(dm, (v, u), C[sel, ax] * sgn)
    # 3x3 max-filter so a cell boundary can't strand an exterior face
    out = dm.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out[max(0, dy):res + min(0, dy), max(0, dx):res + min(0, dx)] = \
                np.maximum(out[max(0, dy):res + min(0, dy),
                               max(0, dx):res + min(0, dx)],
                           dm[max(0, -dy):res - max(0, dy),
                              max(0, -dx):res - max(0, dx)])
    return sel, out


def bake(car_glb, photos_dir, out_glb, nose_positive_x=None):
    if nose_positive_x is None:
        # measure, don't assume (finding 11): fit_panes writes the sidecar
        import json as _json
        sc = car_glb + ".pose.json"
        if os.path.exists(sc):
            nose_positive_x = bool(_json.load(open(sc))["nose_positive_L"])
            print(f"nose from sidecar: {'+X' if nose_positive_x else '-X'}")
        else:
            nose_positive_x = True
            print("WARNING: no pose sidecar — ASSUMING nose +X (unverified)")
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
    groups_cfg = dict(GROUPS)
    if not nose_positive_x:
        # the +X end is the TAIL: swap which photo lands on which end (the
        # UV flip alone would bake the front photo onto the back of the car)
        (c1, _, a1), (c2, _, a2) = groups_cfg["front"], groups_cfg["back"]
        groups_cfg["front"] = (c1, "rear.png", a1)
        groups_cfg["back"] = (c2, "front.png", a2)
    for gname, ((cc, cr), photo, (ua, va)) in groups_cfg.items():
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
    # bottom cell = CABIN dark, not paint: it textures the underbody, the
    # roof lining and (via reassignment below) the passage skin behind the
    # glass panes — paint red behind a windscreen reads as body-coloured
    # windows, the exact defect the owner ruling scraps cars for
    (bc, br), _, _ = GROUPS["bottom"]
    atlas.paste(Image.new("RGB", (CELL_W, CELL_H), CABIN),
                (bc * CELL_W, br * CELL_H))
    buf = io.BytesIO()
    atlas.save(buf, "PNG", optimize=True)
    atlas_png = buf.getvalue()

    # ---- per-group vertex split + UVs -------------------------------------
    # nose direction decides which photo is 'front'. If the badge ends up on
    # the wrong end, flip nose_positive_x — one boolean, checked by render.
    C = V[F].mean(axis=1)
    groups = [group_of(N[i], nose_positive_x) for i in range(len(F))]
    oax = out_axis(nose_positive_x)
    dmaps = {gn: depth_map(C, groups, gn, lo, ext, oax=oax)
             for gn in ("front", "back", "left", "right")}
    newV, newUV, newF = [], [], []
    index = {}
    for fi, face in enumerate(F):
        g = groups[fi]
        if g in oax:
            _, dm = dmaps[g]
            ax, sgn = oax[g]
            ua2 = 2 if ax == 0 else 0
            margin = 0.05 * ext[ax]
            res_d = dm.shape[0]
            du = int(np.clip((C[fi, ua2] - lo[ua2]) / max(ext[ua2], 1e-9)
                             * (res_d - 1), 0, res_d - 1))
            dv = int(np.clip((C[fi, 1] - lo[1]) / max(ext[1], 1e-9)
                             * (res_d - 1), 0, res_d - 1))
            if C[fi, ax] * sgn < dm[dv, du] - margin:
                g = "bottom"                       # cabin passage -> dark
            elif ((C[fi, 1] - lo[1]) / ext[1] > CLAMP[groups[fi]]
                  and (groups[fi] not in ("front", "back")
                       or 0.25 < (C[fi, 2] - lo[2]) / max(ext[2], 1e-9) < 0.75)):
                # review finding 2: the height clamp alone painted over the
                # HEADLAMPS (a lamp tops out above 0.53 of car height). The
                # glass this clamp masks is the central windscreen zone, so
                # on end groups restrict it to the middle half of the width —
                # lamp faces in the outer quarters keep the photo.
                g = "top"                          # photo shows glass -> paint
        (cc, cr), photo, (ua, va) = GROUPS[g]
        tri = []
        for vi in face:
            key = (vi, g)
            if key not in index:
                p = V[vi]
                u = (p[ua] - lo[ua]) / max(ext[ua], 1e-9)
                v = (p[va] - lo[va]) / max(ext[va], 1e-9)
                # orient each cell to match its photo (reviewer-evaluated
                # truth table, finding 1). u is the WORLD fraction along the
                # cell axis (L for sides, W=+Z for ends), nose already +X via
                # group_of(nose_pos): left.png has the nose at image-LEFT so
                # world +X(u=1) must map to image-right -> u stays; right.png
                # mirrors it; front.png is shot FACING the nose so the car's
                # +Z lands at image-LEFT -> flip; rear.png keeps +Z at right.
                # left.png: nose at image-LEFT, u=1 is the nose, and u=1
                # maps to cell-right -> FLIP. right.png: nose at image-RIGHT
                # -> no flip. front.png: shot facing the nose, car's +Z lands
                # image-LEFT, u=1 is +Z -> FLIP. rear.png: +Z at image-RIGHT
                # -> no flip. (First cut had the sides inverted; caught by
                # re-deriving before render.)
                if g in ("left", "front"):
                    u = 1 - u
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
        if name.startswith("inner") or name.startswith("trim"):
            return mats["flat"]
        # review finding 12: paint as the fallback ships painted tyres the
        # moment an upstream name changes — the owner's hard fail. Dark
        # cavity is the safe direction for anything unrecognised.
        print(f"  WARNING: unrecognised geometry '{name}' -> Arch_Cavity "
              "(never paint by default)")
        return mats["Arch_Cavity"]

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
    # default None -> measure from the sidecar; 'flip'/'noflip' force it
    _nose = None
    if len(sys.argv) > 4:
        _nose = (sys.argv[4] != "flip")
    bake(sys.argv[1], sys.argv[2], sys.argv[3], nose_positive_x=_nose)
