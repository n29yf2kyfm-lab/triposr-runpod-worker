#!/usr/bin/env python3
"""skin.py — the TEXTURE detail layer for authored cars.

STUDY_3D.md, measured: in the viewer a 4m car gets ~800px, so 5mm per pixel — a
3mm shut line is 0.6px, a grille slat less. At that scale panel detail is a
SHADING phenomenon, not a shape phenomenon, which is why games and product viz
carry it in normal/AO maps. This module paints those maps procedurally, from
the SAME landmarks that placed the geometry's seams — so the painted line and
the engraved groove land on top of each other and reinforce, never disagree.

Texture space: x = u along the car (0 tail, 1 nose) — identical to the loft
parameter; y = j/nv around the half-section (0 floor centre, 1 roof centre).
Both body sides share the map (mirror symmetry, like real cars).

What gets painted:
  * seam lines at every shut position   (AO dark + normal groove)
  * the swage line along the flank      (normal crease + faint AO)
  * door handle recesses                (AO pocket + normal dish)
  * sill shadow band                    (AO gradient)
  * fuel filler ring on the rear quarter (AO + normal)

Returns (base_png_bytes, normal_png_bytes). Base is near-white and MULTIPLIES
with baseColorFactor, so resprays keep working untouched.
"""
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


TEX_W, TEX_H = 2048, 512


def _height_to_normal(h, strength=6.0):
    """Tangent-space normal map from a height field (OpenGL +Y, per glTF)."""
    gy, gx = np.gradient(h.astype(np.float64))
    nx = -gx * strength
    ny = gy * strength          # +Y up: image y grows downward, so no flip
    nz = np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx / ln, ny / ln, nz / ln], axis=-1)
    return ((rgb * 0.5 + 0.5) * 255).astype(np.uint8)


def paint_skin(car, v_marks):
    """Build the two maps for `car`.

    v_marks: dict of section-fraction landmarks measured from the REAL loft
    grid (not guessed): {'belt': j-fraction of the beltline, 'shoulder': ...,
    'sill': ...}. structured_car computes them from REG so the painted lines
    sit exactly where the geometry says those features are.
    """
    W, H = TEX_W, TEX_H
    ao = Image.new("L", (W, H), 255)
    hgt = np.zeros((H, W), dtype=np.float64)
    d = ImageDraw.Draw(ao)

    v_belt = v_marks.get("belt", 0.62)
    v_shoulder = v_marks.get("shoulder", 0.55)
    v_sill = v_marks.get("sill", 0.16)

    def u2x(u):
        return int(u * (W - 1))

    def v2y(v):
        return int(v * (H - 1))

    # --- seam lines at the shut positions (the same list the loft engraves).
    # Each seam's REGION SPAN bounds its v extent: a door seam runs sill to
    # belt like a real door edge; the bonnet/cowl seam stays on the upper body;
    # the tailgate seam stays on the hatch. v1 drew every seam floor-to-roof
    # and the bonnet shut ran down the wing to the rocker, which read wrong.
    seams = car.shut_positions()
    groove_px = max(2, int(0.004 * W))
    REGION_V = {0: 0.02, 1: v_sill, 2: (v_sill + v_shoulder) / 2,
                3: v_shoulder, 4: v_belt, 5: 0.985}
    for u, (r0, r1) in seams:
        x = u2x(u)
        va = REGION_V.get(r0, 0.06)
        vb = REGION_V.get(r1, 0.97)
        d.line([(x, v2y(va)), (x, v2y(vb))], fill=132, width=groove_px)
        hgt[v2y(va):v2y(vb), max(0, x - groove_px):x + groove_px] -= 1.0

    # --- swage line: a crease along the flank between belt and shoulder
    y_sw = v2y((v_belt + v_shoulder) / 2)
    u0, u1 = u2x(car.u_rear - 0.04), u2x(car.u_front + 0.06)
    d.line([(u0, y_sw), (u1, y_sw)], fill=205, width=3)
    hgt[y_sw - 2:y_sw + 2, u0:u1] += 1.0          # a ridge, not a groove

    # --- door handles: a recess just behind each door's leading seam, at belt
    door_seams = [u for u, _ in seams[1:-1]]      # the door edges
    hw, hh = int(0.020 * W), int(0.016 * H)
    for u in door_seams:
        x = u2x(u - 0.028)
        y = v2y(v_belt - 0.045)
        d.ellipse([x - hw, y - hh, x + hw, y + hh], fill=118)
        hgt[y - hh:y + hh, x - hw:x + hw] -= 0.9

    # --- sill shadow: AO falloff toward the rocker
    sill_band = np.linspace(1.0, 0.72, v2y(v_sill))
    ao_np = np.array(ao, dtype=np.float64)
    ao_np[:v2y(v_sill), :] *= sill_band[:, None]

    # --- fuel filler: rear quarter, above belt
    fx, fy = u2x(car.u_rear - 0.065), v2y(v_belt + 0.05)
    r = int(0.011 * W)
    d2 = ImageDraw.Draw(Image.new("L", (1, 1)))   # noqa: F841 (draw on ao below)
    dd = ImageDraw.Draw(ao)
    dd.ellipse([fx - r, fy - r, fx + r, fy + r], outline=150, width=2)
    yy, xx = np.ogrid[:H, :W]
    ring = np.abs(np.hypot(xx - fx, yy - fy) - r) < 2
    hgt[ring] -= 0.5

    # merge the numpy AO ops back, soften everything one step
    ao_np = np.minimum(ao_np, np.array(ao, dtype=np.float64))
    ao_img = Image.fromarray(ao_np.astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(1.0))

    # base colour = neutral near-white AO (multiplies with baseColorFactor)
    base = Image.merge("RGB", (ao_img, ao_img, ao_img))

    hgt_blur = np.array(Image.fromarray(
        ((hgt - hgt.min()) / max(np.ptp(hgt), 1e-9) * 255).astype(np.uint8)
    ).filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float64) / 255.0
    normal = Image.fromarray(_height_to_normal(hgt_blur, strength=8.0))

    bb, nb = io.BytesIO(), io.BytesIO()
    base.save(bb, "PNG", optimize=True)
    normal.save(nb, "PNG", optimize=True)
    return bb.getvalue(), nb.getvalue()
