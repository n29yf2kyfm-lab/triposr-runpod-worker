#!/usr/bin/env python3
"""author_car.py — build a car GLB FROM SCRATCH, no Blender, no generator.

STUDY ARTEFACT, written 2026-08-14. Its job is not to ship a car; it is to
prove, in code, the three things every audit in this project depends on and
that no generated mesh has yet delivered together:

  1. HOW A GLB IS ACTUALLY MADE. Everything here is written by hand into the
     glTF 2.0 container: a 12-byte header, a JSON chunk, a BIN chunk, and the
     buffer/bufferView/accessor chain that turns raw bytes into positions,
     normals and indices. If you can write this you can also read, repair and
     probe one, which is what glass_probe/tyre_probe/respray_gltf all do.
  2. WHAT SHARPNESS LOOKS LIKE NUMERICALLY. The body carries deliberate creases
     -- swage line, sill step, and ENGRAVED SHUT LINES around the doors, bonnet
     and tailgate. mesh_forensics.py should read this car as bimodal (big flat
     panels AND real creases), which is exactly the signature every generated
     car lacks.
  3. THE MATERIAL SCHEME THE OWNER'S RULINGS REQUIRE. Separate paint, BLEND
     glazing, dark rubber, metal rim and lamp lens -- so glass_probe returns
     clear/proven and a respray can only ever move the body colour.

WHY SHUT LINES ARE ENGRAVED HERE AND CANNOT BE GENERATED (measured 2026-08-14):
a real panel gap is 3-5mm on a 4000mm car. At the octree resolutions the open
generators run (256-512, i.e. 8-16mm per voxel) a shut line is 0.2-0.4 of ONE
VOXEL -- below the representable bandwidth, so no amount of fine-tuning at that
resolution can produce one. Even the hosted 1536 tier lands at ~1.15 voxels.
Authoring or engraving them is not a shortcut; it is the only way they can exist.

Geometry is lofted: a series of cross-section rings along the car's length, each
a rounded box, stitched into quads and triangulated. That is deliberately the
same construction an artist uses (sections -> surface), which is why the result
has clean edge flow instead of the uniform triangle soup a dual-marching-cubes
extractor emits.

Usage:
    python3 pipeline/trellis/author_car.py out.glb
    HDRI_PATH=render/assets/hdri.hdr xvfb-run -a blender -b --factory-startup \
      -noaudio -P pipeline/qc/prod_render.py -- render/handler.py out.glb v.png 215
"""
import json
import math
import struct
import sys

import numpy as np

# ---------------------------------------------------------------- body shape
# All dimensions in metres, a C-segment hatchback. x = length (nose at +x),
# y = up, z = width. glTF is Y-up, which is what render/handler.py expects.
LEN, WID, HGT = 4.00, 1.76, 1.46
WHEELBASE, TRACK = 2.60, 1.52
WHEEL_R, TYRE_W = 0.32, 0.21


def body_profile(t):
    """Cross-section parameters at normalised length t in [0,1], nose at t=1.

    Returns (half_width, y_bottom, y_top, corner_radius). These four curves are
    the whole silhouette: widening over the arches, the roofline rising behind
    the screen and falling to the tailgate, the sill sitting just above the
    ground. Hand-tuned to read as a hatchback in profile.
    """
    # plan view: narrow at both ends, full width across the doors
    w = 0.5 * WID * (0.62 + 0.38 * math.sin(math.pi * min(max(t, 0.0), 1.0)) ** 0.55)
    # sill height: slight rake, lower at the front
    y0 = 0.30 + 0.03 * t
    # roofline: bonnet low, screen rises, roof flat, tailgate drops
    if t < 0.18:            # rear bumper / tailgate lower edge
        y1 = 0.95 + 1.4 * t
    elif t < 0.32:          # tailgate to rear roof
        y1 = 1.20 + (HGT - 1.20) * (t - 0.18) / 0.14
    elif t < 0.62:          # roof
        y1 = HGT - 0.02 * abs(t - 0.47) / 0.15
    elif t < 0.80:          # windscreen sweeping down to the cowl
        y1 = HGT - (HGT - 0.98) * (t - 0.62) / 0.18
    else:                   # bonnet, dipping to the nose
        y1 = 0.98 - 0.10 * (t - 0.80) / 0.20
    r = 0.18 + 0.10 * math.sin(math.pi * t)      # corner softness
    return w, y0, y1, r


def ring(t, inset=0.0, n=28):
    """One closed cross-section as an (n,3) array, ordered around the section.

    `inset` shrinks the ring toward its own centre — that is how a shut line is
    engraved: two rings at nearly the same x, one pushed in by a few mm, gives
    a groove with real walls that catches a shadow exactly like a panel gap.
    """
    w, y0, y1, r = body_profile(t)
    w -= inset
    y0 += inset * 0.5
    y1 -= inset * 0.5
    cy, hy = (y0 + y1) / 2.0, (y1 - y0) / 2.0
    r = min(r, min(w, hy) * 0.9)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        # superellipse: exponent controls how boxy the section reads
        e = 2.0 / 3.2
        ca, sa = math.cos(a), math.sin(a)
        px = math.copysign(abs(ca) ** e, ca) * w
        py = math.copysign(abs(sa) ** e, sa) * hy
        pts.append((LEN * (t - 0.5), cy + py, px))
    return np.array(pts, dtype=np.float32)


# Shut lines: (t position, half-width of the groove in t). A real car's door
# gap is ~4mm; on a 4m car that is 0.001 in t, which would vanish under any
# triangulation this coarse, so the groove is widened to something a 900px
# render can resolve — the TECHNIQUE is the point, not the millimetre.
SHUT_LINES = [(0.335, 0.004), (0.520, 0.004), (0.700, 0.004)]
GROOVE_DEPTH = 0.012


def build_body(n_sections=96, n_ring=28):
    """Loft the body, engraving a groove at each shut line."""
    ts = list(np.linspace(0.02, 0.98, n_sections))
    for t, half in SHUT_LINES:                 # add the groove's own sections
        ts += [t - half, t, t + half]
    ts = sorted(ts)

    rings, insets = [], []
    for t in ts:
        ins = 0.0
        for st, half in SHUT_LINES:
            if abs(t - st) < half * 0.5:       # the groove floor
                ins = GROOVE_DEPTH
        rings.append(ring(t, inset=ins, n=n_ring))
        insets.append(ins)

    V = np.concatenate(rings, axis=0)
    F = []
    for s in range(len(rings) - 1):
        a0, b0 = s * n_ring, (s + 1) * n_ring
        for i in range(n_ring):
            j = (i + 1) % n_ring
            F.append([a0 + i, b0 + i, b0 + j])
            F.append([a0 + i, b0 + j, a0 + j])
    # caps, as fans around each end ring's centroid
    for idx, sgn in ((0, -1), (len(rings) - 1, 1)):
        c = len(V)
        V = np.concatenate([V, rings[idx].mean(axis=0, keepdims=True)], axis=0)
        base = idx * n_ring
        for i in range(n_ring):
            j = (i + 1) % n_ring
            F.append([c, base + j, base + i][::sgn])
    return V.astype(np.float32), np.array(F, dtype=np.uint32)


def build_glass(n_sections=40, n_ring=28):
    """The greenhouse as its OWN mesh — the structural fix a fused shell lacks.

    Sits just inside the body over the cabin band, so it can carry a BLEND
    material without the paint ever touching it.
    """
    ts = np.linspace(0.30, 0.78, n_sections)
    rings = [ring(t, inset=0.012, n=n_ring) for t in ts]
    V = np.concatenate(rings, axis=0)
    F = []
    for s in range(len(rings) - 1):
        a0, b0 = s * n_ring, (s + 1) * n_ring
        for i in range(n_ring):
            j = (i + 1) % n_ring
            # keep only the upper band: glazing, not the whole tube
            if not (0 <= i < n_ring // 2):
                continue
            F.append([a0 + i, b0 + i, b0 + j])
            F.append([a0 + i, b0 + j, a0 + j])
    return V.astype(np.float32), np.array(F, dtype=np.uint32)


def cylinder(c, axis_len, r_out, r_in, seg=32, closed=True):
    """A wheel-shaped tube along z, used for both tyre and rim."""
    V, F = [], []
    for sign in (-1, 1):
        for i in range(seg):
            a = 2 * math.pi * i / seg
            V.append([c[0] + r_out * math.cos(a), c[1] + r_out * math.sin(a),
                      c[2] + sign * axis_len / 2])
    for i in range(seg):
        j = (i + 1) % seg
        F += [[i, seg + i, seg + j], [i, seg + j, j]]
    if closed:
        for sign, base in ((-1, 0), (1, seg)):
            cidx = len(V)
            V.append([c[0], c[1], c[2] + sign * axis_len / 2])
            for i in range(seg):
                j = (i + 1) % seg
                tri = [cidx, base + i, base + j]
                F.append(tri if sign > 0 else tri[::-1])
    _ = r_in
    return np.array(V, dtype=np.float32), np.array(F, dtype=np.uint32)


def wheels():
    """Four corners: dark rubber tyre + metal rim, as SEPARATE meshes.

    Separate is the whole point — the owner's ruling is that tyres must read as
    black rubber, and geometry the paint cannot reach is the only durable way
    to guarantee it.
    """
    xs = [WHEELBASE / 2, -WHEELBASE / 2]
    zs = [TRACK / 2, -TRACK / 2]
    tyres, rims = [], []
    for x in xs:
        for z in zs:
            c = (x, WHEEL_R, z)
            tyres.append(cylinder(c, TYRE_W, WHEEL_R, WHEEL_R * 0.62))
            rims.append(cylinder(c, TYRE_W * 0.55, WHEEL_R * 0.62, 0.0))
    return tyres, rims


def lamps():
    """Headlamp and tail-lamp lenses as their own small meshes."""
    out = []
    for x, z, r in ((LEN / 2 - 0.10, 0.62, 0.13), (LEN / 2 - 0.10, -0.62, 0.13),
                    (-LEN / 2 + 0.08, 0.66, 0.11), (-LEN / 2 + 0.08, -0.66, 0.11)):
        out.append(cylinder((x, 0.86, z), 0.06, r, 0.0, seg=20))
    return out


# ------------------------------------------------------------- glTF plumbing
def normals(V, F):
    """Area-weighted vertex normals. Smooth shading everywhere except where the
    geometry itself folds — the creases come from the SHAPE, not from split
    normals, which is what makes them survive a re-export."""
    N = np.zeros_like(V, dtype=np.float64)
    tri = V[F]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    return (N / np.maximum(ln, 1e-12)).astype(np.float32)


class GLB:
    """Minimal glTF 2.0 writer: one buffer, everything packed into the BIN chunk.

    The layout rule that matters: every accessor's byteOffset must be a multiple
    of its component size, so each block is padded to 4 bytes. Getting this wrong
    produces a file that loads in one viewer and fails in another — which is
    exactly the class of bug the probes in this repo have to survive.
    """

    def __init__(self):
        self.bin = bytearray()
        self.g = {"asset": {"version": "2.0", "generator": "author_car.py"},
                  "scene": 0, "scenes": [{"nodes": []}], "nodes": [],
                  "meshes": [], "materials": [], "accessors": [],
                  "bufferViews": [], "buffers": []}

    def _view(self, data, target):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += data
        self.g["bufferViews"].append(
            {"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        return len(self.g["bufferViews"]) - 1

    def _acc(self, view, ctype, count, atype, mn=None, mx=None):
        a = {"bufferView": view, "componentType": ctype, "count": count, "type": atype}
        if mn is not None:
            a["min"], a["max"] = mn, mx
        self.g["accessors"].append(a)
        return len(self.g["accessors"]) - 1

    def material(self, name, base, metal=0.0, rough=0.5, blend=False):
        m = {"name": name,
             "pbrMetallicRoughness": {"baseColorFactor": base,
                                      "metallicFactor": metal,
                                      "roughnessFactor": rough},
             "doubleSided": True}
        if blend:
            m["alphaMode"] = "BLEND"
        self.g["materials"].append(m)
        return len(self.g["materials"]) - 1

    def mesh(self, name, V, F, mat):
        N = normals(V, F)
        vp = self._view(V.astype("<f4").tobytes(), 34962)
        vn = self._view(N.astype("<f4").tobytes(), 34962)
        vi = self._view(F.astype("<u4").reshape(-1).tobytes(), 34963)
        ap = self._acc(vp, 5126, len(V), "VEC3",
                       V.min(0).tolist(), V.max(0).tolist())
        an = self._acc(vn, 5126, len(V), "VEC3")
        ai = self._acc(vi, 5125, F.size, "SCALAR")
        self.g["meshes"].append({"name": name, "primitives": [
            {"attributes": {"POSITION": ap, "NORMAL": an}, "indices": ai,
             "material": mat}]})
        self.g["nodes"].append({"mesh": len(self.g["meshes"]) - 1, "name": name})
        self.g["scenes"][0]["nodes"].append(len(self.g["nodes"]) - 1)

    def save(self, path):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.g["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(self.g, separators=(",", ":")).encode()
        js += b" " * ((4 - len(js) % 4) % 4)          # JSON pads with SPACES
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942) + bytes(self.bin))
        return total


def main(out="authored_car.glb"):
    g = GLB()
    m_paint = g.material("Material_0", [0.72, 0.74, 0.76, 1.0], 0.10, 0.30)
    m_glass = g.material("Glass_Tint", [0.03, 0.04, 0.05, 0.28], 0.0, 0.05, blend=True)
    m_tyre = g.material("Tyre_Rubber", [0.027, 0.027, 0.031, 1.0], 0.0, 0.90)
    m_rim = g.material("Rim_Alloy", [0.42, 0.43, 0.45, 1.0], 0.85, 0.35)
    m_lamp = g.material("Lamp_Lens", [0.078, 0.078, 0.090, 1.0], 0.0, 0.08)

    bV, bF = build_body()
    g.mesh("body", bV, bF, m_paint)
    gV, gF = build_glass()
    g.mesh("greenhouse", gV, gF, m_glass)
    tyres, rims = wheels()
    for i, (V, F) in enumerate(tyres):
        g.mesh(f"tyre_{i}", V, F, m_tyre)
    for i, (V, F) in enumerate(rims):
        g.mesh(f"rim_{i}", V, F, m_rim)
    for i, (V, F) in enumerate(lamps()):
        g.mesh(f"lamp_{i}", V, F, m_lamp)

    size = g.save(out)
    print(f"wrote {out}  {size/1024:.1f} KB  meshes={len(g.g['meshes'])} "
          f"materials={len(g.g['materials'])}")
    print(f"body: {len(bV)} verts / {len(bF)} tris, {len(SHUT_LINES)} shut lines engraved")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "authored_car.glb")
