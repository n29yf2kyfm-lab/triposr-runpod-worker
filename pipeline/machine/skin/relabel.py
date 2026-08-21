#!/usr/bin/env python3
"""relabel.py -- absorb speckled label islands into the material that surrounds
them, by editing ONLY the glTF index data.

WHY THIS AND NOT A DELETION.  The brief called this a double skin and asked for
one sheet of each pair to be deleted.  Measured on car_rebound.glb, that is not
what is there:
  * exactly 1 Interior face is a duplicate triangle of a Body_Shell face;
  * 23,232 Interior faces have all three vertices EXACTLY coincident with
    Body_Shell vertices, and 92.4% of them share an edge with a Body_Shell
    BOUNDARY edge -- they sit IN Body_Shell's holes, on its rim;
  * a clay render (one grey diffuse, real geometry, real normals) is CLEAN --
    so the geometry under the speckle is sound and there is nothing to delete.
Deleting these faces would punch 30,000 real holes in the bonnet and roof.
The exterior is ONE triangulated surface partitioned between materials, and the
partition is speckled.  The repair is to move the speckle faces to the material
that surrounds them.

That is a MATERIAL BINDING change, not paint applied over a geometry defect: the
clay render is the evidence that the geometry is already correct.  Vertex data
is copied byte for byte; face count, positions, normals, area and silhouette are
unchanged by construction.

SELECTION, from measurement not from taste:  same-material connected components
on the WELDED surface (adjacency crosses mesh boundaries because the meshes
share exact vertex positions).  Dark components split cleanly into ~12.6k islands
of <= 0.03 m2 and a handful of real parts of >= 0.26 m2 -- a 9x gap.  An island
is absorbed when its area is under --amax AND at least --frac of its boundary
neighbour area is the absorbing material.

NEVER TOUCHED: glass (the 2026-08-11 opaque-glazing ruling -- no glazing binding
is altered in either direction), Tyre_Rubber, Rim_Alloy, Brake_Disc and both
Lamp_Lens materials (the tyre and rim rulings).  Only the shell family moves.

Run: relabel.py <in.glb> <out.glb> [--amax 0.002] [--frac 0.90] [--report r.json]
"""
import json
import struct
import sys
from collections import defaultdict

import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph as csg
import trimesh

SRC, OUT = sys.argv[1], sys.argv[2]


def opt(f, d, c=float):
    return c(sys.argv[sys.argv.index(f) + 1]) if f in sys.argv else d


AMAX = opt("--amax", 0.002)
FRAC = opt("--frac", 0.90)
PASSES = opt("--passes", 1, int)
REPORT = opt("--report", "relabel_report.json", str)
Q = 1e-7
SHELL = {"carpaint", "Interior_Plastic", "Arch_Liner", "Underbody", "Trim_Black"}
FROZEN = {"glass", "Tyre_Rubber", "Rim_Alloy", "Brake_Disc", "Lamp_Lens", "Lamp_Lens_Rear"}

# ------------------------------------------------------------------ geometry
sc = trimesh.load(SRC, process=False, force="scene")
names = list(sc.geometry.keys())
mats, Vl, Fl, Gl = [], [], [], []
off = 0
counts = []
for gi, n in enumerate(names):
    m = sc.geometry[n]
    T, _ = sc.graph.get(n)
    v = trimesh.transformations.transform_points(np.asarray(m.vertices, np.float64), T)
    f = np.asarray(m.faces, np.int64)
    Vl.append(v); Fl.append(f + off); Gl.append(np.full(len(f), gi, np.int32))
    off += len(v); counts.append(len(f))
    mats.append(getattr(m.visual.material, "name", f"mat{gi}"))
V = np.vstack(Vl); F = np.vstack(Fl); G = np.concatenate(Gl)
MATN = sorted(set(mats))
MI = np.array([MATN.index(mats[g]) for g in G])
tri = V[F]
A = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
NF = len(F)

key = np.round(V / Q).astype(np.int64)
_, inv = np.unique(key, axis=0, return_inverse=True)
W = inv[F]
e = np.sort(np.concatenate([W[:, [0, 1]], W[:, [1, 2]], W[:, [0, 2]]]), axis=1)
fid = np.tile(np.arange(NF), 3)
o = np.lexsort((e[:, 1], e[:, 0]))
e, fid = e[o], fid[o]
brk = np.nonzero(~np.all(e[1:] == e[:-1], axis=1))[0]
bounds = np.concatenate([[0], brk + 1, [len(e)]])
pl = []
for a, b in zip(bounds[:-1], bounds[1:]):
    if b - a >= 2:
        g = fid[a:b]
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                pl.append((g[i], g[j]))
pairs = np.array(pl, np.int64)

MI0 = MI.copy()
newmat = np.full(NF, -1, np.int64)
moved = defaultdict(lambda: [0, 0.0])
FROZEN_I = {MATN.index(x) for x in FROZEN if x in MATN}
SHELL_I = {MATN.index(x) for x in SHELL if x in MATN}
FROZEN_FACE = np.zeros(NF, bool)   # a face may be absorbed ONCE.  Without this
# the rule oscillates: a component absorbed into carpaint merges with its
# neighbours, the merged component can then qualify to move back, and the pass
# count changes the answer.  One move per face makes the result a fixed point.

for pss in range(PASSES):
    same = MI[pairs[:, 0]] == MI[pairs[:, 1]]
    p = pairs[same]
    ncomp, lab = csg.connected_components(
        sp.coo_matrix((np.ones(len(p)), (p[:, 0], p[:, 1])), shape=(NF, NF)),
        directed=False)
    carea = np.bincount(lab, weights=A, minlength=ncomp)
    cmat = np.zeros(ncomp, np.int64); cmat[lab] = MI
    xb = pairs[~same]
    nb = defaultdict(lambda: defaultdict(float))
    for a, b in xb:
        nb[lab[a]][MI[b]] += A[b]
        nb[lab[b]][MI[a]] += A[a]
    hits = 0
    for ci in range(ncomp):
        if carea[ci] <= 0 or carea[ci] >= AMAX or cmat[ci] not in SHELL_I:
            continue
        d = nb.get(ci)
        if not d:
            continue
        tot = sum(d.values())
        dst_i = max(d, key=d.get)
        if dst_i in FROZEN_I or dst_i not in SHELL_I or dst_i == cmat[ci]:
            continue
        if d[dst_i] / tot < FRAC:
            continue
        m = lab == ci
        if FROZEN_FACE[m].any():
            continue
        MI[m] = dst_i
        FROZEN_FACE[m] = True
        hits += int(m.sum())
    print(f"   pass {pss+1}: {hits} faces absorbed")
    if hits == 0:
        break

ch = MI != MI0
newmat = np.where(ch, MI, -1)
for a, b in zip(MI0[ch], MI[ch]):
    pass
import collections as _c
cc = _c.Counter(zip(MI0[ch].tolist(), MI[ch].tolist()))
ar = _c.defaultdict(float)
for i in np.nonzero(ch)[0]:
    ar[(MI0[i], MI[i])] += A[i]
for (a, b), n in cc.items():
    moved[f"{MATN[a]}->{MATN[b]}"] = [n, float(ar[(a, b)])]

print(f"[relabel] amax {AMAX} m2, frac {FRAC}, passes {PASSES}")
print(f"[relabel] components {ncomp}; faces rebound {int((newmat>=0).sum())} "
      f"({100*(newmat>=0).mean():.3f}%), area {A[newmat>=0].sum():.4f} m2")
for k, v in sorted(moved.items(), key=lambda x: -x[1][1]):
    print(f"    {k:38s} {v[0]:7d} faces  {v[1]:.5f} m2")
assert not set(np.unique(newmat[newmat >= 0]).tolist()) & FROZEN_I, \
    "refusing: a frozen material was chosen as a destination"
assert not (np.isin(MI0, list(FROZEN_I)) & ch).any(), \
    "refusing: a frozen material was moved"
assert A[ch].sum() < 0.25 * A.sum(), "refusing: absorbed area is implausibly large"

# ------------------------------------------------------------- write the glTF
raw = open(SRC, "rb").read()
pp = 12
jlen, _ = struct.unpack("<II", raw[pp:pp + 8]); pp += 8
gl = json.loads(raw[pp:pp + jlen]); pp += jlen
blen, _ = struct.unpack("<II", raw[pp:pp + 8]); pp += 8
BIN = raw[pp:pp + blen]
assert [m["name"] for m in gl["meshes"]] == names, "mesh order mismatch"
CT = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}
matidx = {m["name"]: i for i, m in enumerate(gl["materials"])}


def read_idx(ai):
    a = gl["accessors"][ai]
    bv = gl["bufferViews"][a["bufferView"]]
    return np.frombuffer(BIN, dtype=CT[a["componentType"]], count=a["count"],
                         offset=bv.get("byteOffset", 0) + a.get("byteOffset", 0))


new_arrays = {}          # accessor idx -> array   (existing, rewritten)
extra = []               # (mesh_idx, material_idx, array, componentType)
cur = 0
for mi_, me in enumerate(gl["meshes"]):
    ai = me["primitives"][0]["indices"]
    idx = read_idx(ai)
    nf = len(idx) // 3
    seg = newmat[cur:cur + nf]
    cur += nf
    if (seg < 0).all():
        continue
    t = idx.reshape(-1, 3)
    new_arrays[ai] = t[seg < 0].reshape(-1)
    for dst in np.unique(seg[seg >= 0]):
        extra.append((mi_, matidx[MATN[dst]], t[seg == dst].reshape(-1),
                      gl["accessors"][ai]["componentType"]))
assert cur == NF

order = sorted(range(len(gl["bufferViews"])),
               key=lambda i: gl["bufferViews"][i].get("byteOffset", 0))
acc_by_bv = defaultdict(list)
for i, a in enumerate(gl["accessors"]):
    acc_by_bv[a["bufferView"]].append(i)

out = bytearray()


def emit(arr, ct):
    global out
    while len(out) % 4:
        out.append(0)
    st = len(out)
    out += arr.astype(CT[ct]).tobytes()
    return st


for bvi in order:
    bv = gl["bufferViews"][bvi]
    accs = acc_by_bv[bvi]
    if len(accs) == 1 and accs[0] in new_arrays:
        a = gl["accessors"][accs[0]]
        arr = new_arrays[accs[0]]
        st = emit(arr, a["componentType"])
        a["count"] = int(len(arr)); a["max"] = [int(arr.max())]; a["min"] = [int(arr.min())]
        a.pop("byteOffset", None)
        bv["byteOffset"] = st; bv["byteLength"] = len(arr) * np.dtype(CT[a["componentType"]]).itemsize
    else:
        while len(out) % 4:
            out.append(0)
        st = len(out)
        o0 = bv.get("byteOffset", 0)
        out += BIN[o0:o0 + bv["byteLength"]]
        bv["byteOffset"] = st

for mi_, mat_i, arr, ct in extra:
    st = emit(arr, ct)
    gl["bufferViews"].append({"buffer": 0, "byteOffset": st,
                              "byteLength": len(arr) * np.dtype(CT[ct]).itemsize})
    gl["accessors"].append({"bufferView": len(gl["bufferViews"]) - 1, "componentType": ct,
                            "count": int(len(arr)), "type": "SCALAR",
                            "max": [int(arr.max())], "min": [int(arr.min())]})
    src_prim = gl["meshes"][mi_]["primitives"][0]
    gl["meshes"][mi_]["primitives"].append({
        "attributes": dict(src_prim["attributes"]),
        "indices": len(gl["accessors"]) - 1, "material": mat_i,
        "mode": src_prim.get("mode", 4)})

gl["buffers"][0]["byteLength"] = len(out)
jb = json.dumps(gl, separators=(",", ":")).encode()
while len(jb) % 4:
    jb += b" "
while len(out) % 4:
    out.append(0)
glb = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(out))
       + struct.pack("<II", len(jb), 0x4E4F534A) + jb
       + struct.pack("<II", len(out), 0x004E4942) + bytes(out))
open(OUT, "wb").write(glb)
np.save(OUT + ".newmat.npy", newmat)
json.dump({"input": SRC, "output": OUT, "amax": AMAX, "frac": FRAC,
           "faces_total": int(NF), "faces_rebound": int((newmat >= 0).sum()),
           "area_rebound": round(float(A[newmat >= 0].sum()), 6),
           "moves": {k: {"faces": v[0], "area": round(v[1], 6)} for k, v in moved.items()},
           "frozen_materials": sorted(FROZEN)}, open(REPORT, "w"), indent=1)
print(f"[relabel] wrote {OUT} ({len(glb)} bytes) and {REPORT}")
