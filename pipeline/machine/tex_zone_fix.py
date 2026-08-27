"""tex_zone_fix.py — remove bright baked-texture artefacts inside world-space
zones of a generated car GLB, and optionally flip the nose 180 deg about Y.

Built 2026-08-27 for the RF67 Golf (Hunyuan 2.1, front-conditioned). The
reviewer's "two white loop/question-mark shapes on the hatch" are a GHOSTED
BADGE baked into the texture — the clay pass is smooth there, so the fix is
texture surgery, not geometry. Same pass removes the garbled registration
plate (review: "use a plain demonstration plate or REMOVE it" — removed).

METHOD, and the traps it is built around:
  * The GLB is edited as JSON + BIN SPLICE. No trimesh round-trip: trimesh
    export silently drops KHR material extensions and re-binds materials
    (recorded 2026-08-21). Only the image bufferView's bytes change; every
    following bufferView's byteOffset is shifted, the buffer length updated,
    4-byte alignment preserved.
  * Zones are WORLD-SPACE boxes; faces whose centroid falls in a zone have
    their UV triangles rasterised into a texel mask. Only BRIGHT texels
    (min(R,G,B) above a floor) inside that mask are touched — the artefacts
    are white-on-dark-paint, so brightness is the discriminator.
  * Inpaint is iterative neighbourhood-median growth from surrounding paint,
    then a feather blur INSIDE the repaired region only. A flat fill is the
    recorded backfire (2026-08-26: plate repair created NEW hard edges and
    raised the artefact count); median-feather is what avoids it.
  * The nose flip is a ROOT-NODE quaternion (0,1,0,0) — the pose_fix
    pattern: determinant +1, geometry bytes untouched, winding valid.
    canon.py states it does not resolve nose direction; this is where that
    gets fixed when a mesh comes out tail-first.

A GHOST CAN LIVE IN THE METALLICROUGHNESS MAP, NOT THE BASECOLOR. Measured
on the RF67 Golf 2026-08-27: after the baseColor inpaint the zone's darkest
channel maxed at 114 (dark paint everywhere) and the white loops still
rendered — the badge ghost is loop-shaped MIRROR GLOSS (roughness p5=3) in
image1, catching the strip lights. --mr-floor N repairs it: texels in the
zone mask whose roughness (G channel) is below N are inpainted from the
surrounding >=N texels, same median-grow method. Both images then change,
so the BIN is REBUILT view-by-view rather than spliced once.

Run: python3 tex_zone_fix.py in.glb out.glb --zones zones.json [--flip-nose] [--mr-floor N]
zones.json: [{"x":[x0,x1],"y":[y0,y1],"z":[z0,z1],"bright_floor":110}, ...]
"""
import json
import struct
import sys
from io import BytesIO

import numpy as np
from PIL import Image, ImageFilter

INP, OUT = sys.argv[1], sys.argv[2]
ZONES = json.load(open(sys.argv[sys.argv.index("--zones") + 1]))
FLIP = "--flip-nose" in sys.argv
MR_FLOOR = int(sys.argv[sys.argv.index("--mr-floor") + 1]) if "--mr-floor" in sys.argv else None

raw = open(INP, "rb").read()
assert raw[:4] == b"glTF"
jlen, jtype = struct.unpack("<II", raw[12:20])
assert jtype == 0x4E4F534A
gltf = json.loads(raw[20:20 + jlen])
boff = 20 + jlen
blen, btype = struct.unpack("<II", raw[boff:boff + 8])
assert btype == 0x004E4942
bin_ = bytearray(raw[boff + 8: boff + 8 + blen])


def acc_array(idx):
    a = gltf["accessors"][idx]
    bv = gltf["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}[a["componentType"]]
    n = a["count"] * ncomp
    return np.frombuffer(bin_, dt, n, off).reshape(a["count"], ncomp)


prim = gltf["meshes"][0]["primitives"][0]
pos = acc_array(prim["attributes"]["POSITION"]).astype(np.float64)
uv = acc_array(prim["attributes"]["TEXCOORD_0"]).astype(np.float64)
tri = acc_array(prim["indices"]).reshape(-1, 3).astype(np.int64)
print(f"mesh: {len(pos)} verts {len(tri)} faces  "
      f"x[{pos[:,0].min():.2f},{pos[:,0].max():.2f}] "
      f"y[{pos[:,1].min():.2f},{pos[:,1].max():.2f}] "
      f"z[{pos[:,2].min():.2f},{pos[:,2].max():.2f}]")

# ---- decode baseColor image ----------------------------------------------
mat = gltf["materials"][0]
tex_i = mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]
img_i = gltf["textures"][tex_i]["source"]
img_bv_i = gltf["images"][img_i]["bufferView"]
bv = gltf["bufferViews"][img_bv_i]
i0, ilen = bv.get("byteOffset", 0), bv["byteLength"]
im = Image.open(BytesIO(bytes(bin_[i0:i0 + ilen]))).convert("RGB")
W, H = im.size
px = np.asarray(im).copy()
print(f"baseColor: {gltf['images'][img_i].get('mimeType')} {W}x{H}")

# ---- rasterise zone faces' UV triangles into a texel mask ----------------
cent = pos[tri].mean(axis=1)
mask = np.zeros((H, W), bool)
total_faces = 0
for z in ZONES:
    inz = np.ones(len(cent), bool)
    for ax, key in ((0, "x"), (1, "y"), (2, "z")):
        if key in z:
            inz &= (cent[:, ax] >= z[key][0]) & (cent[:, ax] <= z[key][1])
    faces = tri[inz]
    total_faces += len(faces)
    for f in faces:
        u = uv[f]                                   # 3x2 in [0,1]
        xs = u[:, 0] * (W - 1)
        ys = u[:, 1] * (H - 1)
        x0, x1 = int(xs.min()), int(np.ceil(xs.max()))
        y0, y1 = int(ys.min()), int(np.ceil(ys.max()))
        if x1 - x0 > W // 4 or y1 - y0 > H // 4:    # UV seam wrap: skip
            continue
        gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        # barycentric inside-test
        d = ((ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2]))
        if abs(d) < 1e-9:
            continue
        a = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / d
        b = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / d
        c = 1 - a - b
        ins = (a >= -0.02) & (b >= -0.02) & (c >= -0.02)
        mask[gy[ins], gx[ins]] = True
print(f"zone faces: {total_faces}  zone texels: {mask.sum()}")

# ---- bright-artefact selection -------------------------------------------
floor = min(z.get("bright_floor", 110) for z in ZONES)
bright = mask & (px.min(axis=2) > floor)
n_bright = int(bright.sum())
print(f"bright texels in zones (min channel > {floor}): {n_bright}")
if n_bright == 0:
    print("NOTHING TO FIX in zones — writing flip only" if FLIP
          else "NOTHING TO FIX — refusing to write a byte-identical file")
    if not FLIP:
        sys.exit(1)

# dilate 2px so halo rims go too
for _ in range(2):
    d = bright.copy()
    d[1:] |= bright[:-1]; d[:-1] |= bright[1:]
    d[:, 1:] |= bright[:, :-1]; d[:, :-1] |= bright[:, 1:]
    bright = d

# ---- iterative median inpaint --------------------------------------------
def median_inpaint(px_arr, hole_mask):
    """Grow surrounding texels into hole_mask by neighbourhood median; feather."""
    Hh, Ww = hole_mask.shape
    hole = hole_mask.copy()
    work = px_arr.astype(np.float32)
    it = 0
    while hole.any() and it < 200:
        it += 1
        known = ~hole
        nb = np.zeros_like(hole, np.uint8)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                nb += np.roll(np.roll(known, dy, 0), dx, 1)
        front = hole & (nb > 0)
        ys, xs = np.nonzero(front)
        for y, x in zip(ys, xs):
            y0, y1 = max(0, y - 2), min(Hh, y + 3)
            x0, x1 = max(0, x - 2), min(Ww, x + 3)
            k = known[y0:y1, x0:x1]
            if k.any():
                work[y, x] = np.median(work[y0:y1, x0:x1][k], axis=0)
        hole[front] = False
    rim = hole_mask.copy()
    rim[1:] |= hole_mask[:-1]; rim[:-1] |= hole_mask[1:]
    rim[:, 1:] |= hole_mask[:, :-1]; rim[:, :-1] |= hole_mask[:, 1:]
    soft = np.asarray(Image.fromarray(work.clip(0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(1.6)), np.float32)
    work[rim] = soft[rim]
    print(f"  inpaint fronts: {it}, texels: {int(hole_mask.sum())}")
    return work.clip(0, 255).astype(np.uint8)


def encode_like(img_entry, px_arr):
    buf = BytesIO()
    if img_entry.get("mimeType") == "image/png":
        Image.fromarray(px_arr).save(buf, "PNG")
    else:
        Image.fromarray(px_arr).save(buf, "JPEG", quality=95)
    return buf.getvalue()


replaced = {}                                     # bufferView index -> bytes
out_px = median_inpaint(px, bright)
replaced[img_bv_i] = encode_like(gltf["images"][img_i], out_px)
print(f"baseColor: repaired {n_bright} bright texels")

if MR_FLOOR is not None:
    mrt = mat["pbrMetallicRoughness"].get("metallicRoughnessTexture")
    if mrt is None:
        raise SystemExit("REFUSED: --mr-floor given but no metallicRoughness texture")
    mr_img_i = gltf["textures"][mrt["index"]]["source"]
    mr_bv_i = gltf["images"][mr_img_i]["bufferView"]
    mbv = gltf["bufferViews"][mr_bv_i]
    mim = Image.open(BytesIO(bytes(bin_[mbv.get("byteOffset", 0):
                                        mbv.get("byteOffset", 0) + mbv["byteLength"]]))).convert("RGB")
    mpx = np.asarray(mim).copy()
    mH, mW = mpx.shape[:2]
    if (mH, mW) != (H, W):                        # same UVs, different res
        mmask = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255)
                           .resize((mW, mH), Image.NEAREST)) > 127
    else:
        mmask = mask
    ghost = mmask & (mpx[:, :, 1] < MR_FLOOR)     # G = roughness in glTF
    print(f"MR ghost texels (roughness < {MR_FLOOR}) in zones: {int(ghost.sum())}")
    if ghost.any():
        for _ in range(2):
            d = ghost.copy()
            d[1:] |= ghost[:-1]; d[:-1] |= ghost[1:]
            d[:, 1:] |= ghost[:, :-1]; d[:, :-1] |= ghost[:, 1:]
            ghost = d
        mout = median_inpaint(mpx, ghost)
        replaced[mr_bv_i] = encode_like(gltf["images"][mr_img_i], mout)

# ---- rebuild the BIN view by view ----------------------------------------
order = sorted(range(len(gltf["bufferViews"])),
               key=lambda i: gltf["bufferViews"][i].get("byteOffset", 0))
chunks = []
cursor = 0
for bi in order:
    v = gltf["bufferViews"][bi]
    data = replaced.get(bi) or bytes(
        bin_[v.get("byteOffset", 0): v.get("byteOffset", 0) + v["byteLength"]])
    v["byteOffset"] = cursor
    v["byteLength"] = len(data)
    pad = (4 - len(data) % 4) % 4
    chunks.append(data + b"\x00" * pad)
    cursor += len(data) + pad
new_bin = b"".join(chunks)
gltf["buffers"][0]["byteLength"] = len(new_bin)
print(f"BIN rebuilt: {len(bin_)} -> {len(new_bin)} bytes "
      f"({len(replaced)} image(s) replaced)")

if FLIP:
    for ni in gltf["scenes"][gltf.get("scene", 0)]["nodes"]:
        node = gltf["nodes"][ni]
        assert "rotation" not in node and "matrix" not in node, \
            "node already carries a transform — compose, don't overwrite"
        node["rotation"] = [0.0, 1.0, 0.0, 0.0]      # 180 deg about +Y
    print("nose flip: root rotation (0,1,0,0) applied")

jb = json.dumps(gltf, separators=(",", ":")).encode()
jb += b" " * ((4 - len(jb) % 4) % 4)
out = (b"glTF" + struct.pack("<II", 2, 12 + 8 + len(jb) + 8 + len(new_bin))
       + struct.pack("<II", len(jb), 0x4E4F534A) + jb
       + struct.pack("<II", len(new_bin), 0x004E4942) + new_bin)
open(OUT, "wb").write(out)
print(f"wrote {OUT} ({len(out)} bytes)")
