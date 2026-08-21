#!/usr/bin/env python3
"""glb_facecut.py -- delete faces from a GLB by rewriting ONLY the index data.

Every vertex attribute (POSITION, NORMAL) is copied BYTE-FOR-BYTE from the
source BIN, and the JSON's materials, extensions, nodes and transforms are kept
verbatim.  Nothing is welded, nothing is reprocessed, nothing is moved.

Why not export through trimesh: trimesh submesh export DROPS THE NORMAL
ACCESSORS -- the recorded crumpled-foil defect (CLAUDE.md v7, and again on the
Yaris hybrid, 0/5 primitives).  Recomputing them instead would also change the
shading everywhere and make a before/after render uncomparable.  Cutting
indices is the only edit that leaves the shading identical on every face that
survives, which is exactly what a before/after must guarantee.

Unreferenced vertices are deliberately LEFT IN PLACE: removing them would mean
rewriting POSITION and NORMAL, and the whole point is that those bytes are not
touched.  The mobile/Draco export drops them downstream.

Usage: glb_facecut.py <in.glb> <kill.npy> <out.glb>
  kill.npy is a bool array over faces in mesh order = the order of
  gltf['meshes'], each mesh's primitive[0] indices, concatenated.
"""
import json
import struct
import sys

import numpy as np

SRC, KILL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

raw = open(SRC, "rb").read()
magic, ver, total = struct.unpack("<III", raw[:12])
assert magic == 0x46546C67 and ver == 2, (magic, ver)
p = 12
jlen, jty = struct.unpack("<II", raw[p:p + 8]); p += 8
gl = json.loads(raw[p:p + jlen]); p += jlen
blen, bty = struct.unpack("<II", raw[p:p + 8]); p += 8
BIN = raw[p:p + blen]
assert jty == 0x4E4F534A and bty == 0x004E4942

CT = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}


def read_idx(ai):
    a = gl["accessors"][ai]
    bv = gl["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    dt = CT[a["componentType"]]
    return np.frombuffer(BIN, dtype=dt, count=a["count"], offset=off)


kill = np.load(KILL)
cursor = 0
new_idx = {}      # accessor index -> new index array
for mi, me in enumerate(gl["meshes"]):
    assert len(me["primitives"]) == 1, "multi-primitive mesh not handled"
    ai = me["primitives"][0]["indices"]
    idx = read_idx(ai)
    nf = len(idx) // 3
    k = kill[cursor:cursor + nf]
    cursor += nf
    tri = idx.reshape(-1, 3)[~k]
    if len(tri) == 0:
        raise SystemExit(f"refusing: mesh {me.get('name')} would be emptied")
    new_idx[ai] = tri.reshape(-1)
assert cursor == len(kill), (cursor, len(kill))

# ---- rebuild the BIN: every bufferView in its original order, index views
# replaced.  Contiguity and 4-byte alignment are re-established from scratch.
order = sorted(range(len(gl["bufferViews"])),
               key=lambda i: gl["bufferViews"][i].get("byteOffset", 0))
acc_by_bv = {}
for i, a in enumerate(gl["accessors"]):
    acc_by_bv.setdefault(a["bufferView"], []).append(i)

out = bytearray()
for bvi in order:
    bv = gl["bufferViews"][bvi]
    accs = acc_by_bv.get(bvi, [])
    while len(out) % 4:
        out.append(0)
    start = len(out)
    if len(accs) == 1 and accs[0] in new_idx:
        arr = new_idx[accs[0]]
        a = gl["accessors"][accs[0]]
        dt = CT[a["componentType"]]
        buf = arr.astype(dt).tobytes()
        out += buf
        a["count"] = int(len(arr))
        a["max"] = [int(arr.max())]
        a["min"] = [int(arr.min())]
        a.pop("byteOffset", None)
        bv["byteLength"] = len(buf)
    else:
        o = bv.get("byteOffset", 0)
        out += BIN[o:o + bv["byteLength"]]
    bv["byteOffset"] = start

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
print(f"[glb_facecut] {SRC} -> {OUT}")
print(f"   faces {len(kill)} -> {int((~kill).sum())}  (deleted {int(kill.sum())}, "
      f"{100*kill.mean():.3f}%)")
print(f"   bytes {len(raw)} -> {len(glb)}")
