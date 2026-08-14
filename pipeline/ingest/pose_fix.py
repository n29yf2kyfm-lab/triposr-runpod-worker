#!/usr/bin/env python3
"""pose_fix.py — put a wheels-up / on-side source GLB back on its wheels.

WHY THIS EXISTS. `gpu_wave.pose_gate` correctly hard-rejects cars whose pose is
wrong, and CLAUDE.md records a steady stream of them: three upside-down Toyotas,
an upside-down M-Class, an on-side ML and A-Class, a CL standing on end, the
wheels-up J100. Every one of those was SCRAPPED. But a wrong pose is not a
defect in the mesh — it is a rigid transform, and several of those cars are
otherwise good (the Hyundai Tucson 2022 that prompted this has real wheel
spokes, grille slats and lamp internals, and its materials are already sound).
Scrapping a good car for a 180-degree rotation is throwing away supply we are
short of.

WHAT IT DOES. Enumerates the axis-aligned 90-degree rotations, measures each in
WORLD coordinates with glTF's +Y as up, and picks the one that stands the car on
its wheels. The fix is written as a ROOT NODE quaternion — `scenes[].nodes` is
reparented under one new node carrying `rotation`. The BIN chunk is copied
verbatim, so like clay_rebuild this cannot damage geometry by construction, and
because a rotation has determinant +1 the triangle winding and the shipped
normals stay valid (a REFLECTION would not, which is why mirroring is not in the
candidate set).

HOW IT DECIDES, and why it is not the pose gate's own signal. geom_audit's
`top_over_bot` is a shape PROXY, and it is the thing that was already wrong-way
round on these cars, so verifying a flip with it alone would be circular. The
primary test here is PHYSICAL and world-referenced: the tyre material's vertices
must sit in the bottom of the car's height, and the glazing above them. Tyre and
glass names are the two most reliably-named materials in a scraped GLB, and a
car that is upside down puts its rubber in the sky — a fact no proxy is needed
to read. `top_over_bot` is kept as a SECONDARY check that must also improve.

  tyre_y  normalised height (0=lowest vert, 1=highest) of the tyre material's
          area-ish centroid. Upright cars measure ~0.10-0.25. Must be < 0.35.
  glass_y same for glazing, EXCLUDING lamp lenses (CLAUDE.md's `backlight` /
          `lights_glass` trap: a lamp lens is mid-height and would muddy this).
          Must be above tyre_y by a clear margin when measurable.

REFUSES rather than guesses. If no candidate satisfies the physical test, or the
best candidate is the identity, nothing is written and the exit code is 1. A
car whose tyres are unnamed degrades to `--allow-proxy`, which falls back to
top_over_bot and says so in its output — it is not silently trusted.

Usage:
  pose_fix.py --in car.glb --out car_upright.glb [--allow-proxy] [--report]
"""
import argparse
import json
import math
import os
import re
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TYRE_RE = re.compile(r"tire|tyre|rubber", re.I)
# glazing, minus the lamp senses that CLAUDE.md records outvoting real glass
GLASS_RE = re.compile(r"glass|window|windscreen|windshield", re.I)
LAMP_RE = re.compile(r"lamp|light|drl|blink|indicat|fog|rear_?l|head_?l", re.I)

TYRE_MAX = 0.35        # upright cars measure 0.10-0.25
GLASS_MIN_GAP = 0.15   # glazing must sit clearly above the rubber

_CT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(path):
    raw = open(path, "rb").read()
    if raw[:4] != b"glTF":
        raise ValueError("not a GLB")
    off, js, bin_ = 12, None, b""
    while off + 8 <= len(raw):
        ln, ty = struct.unpack("<II", raw[off:off + 8])
        chunk = raw[off + 8:off + 8 + ln]
        if ty == 0x4E4F534A:
            js = json.loads(chunk)
        elif ty == 0x004E4942:
            bin_ = chunk
        off += 8 + ln + ((4 - ln % 4) % 4 if ln % 4 else 0)
    if js is None:
        raise ValueError("no JSON chunk")
    return js, bin_


def write_glb(path, js, bin_):
    jb = json.dumps(js, separators=(",", ":")).encode()
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bb = bin_ + b"\0" * ((4 - len(bin_) % 4) % 4)
    total = 12 + 8 + len(jb) + (8 + len(bb) if bb else 0)
    with open(path, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<II", len(jb), 0x4E4F534A) + jb)
        if bb:
            f.write(struct.pack("<II", len(bb), 0x004E4942) + bb)


class Unreadable(Exception):
    """Geometry cannot be measured, so no pose verdict may be given."""


def read_accessor(js, bin_, idx):
    """Decode a POSITION accessor to (N,3) float32. Handles byteStride."""
    acc = js["accessors"][idx]
    if "bufferView" not in acc:
        # A Draco primitive keeps its positions inside the compressed blob and
        # omits bufferView. Falling back to trimesh here would be WORSE than
        # failing: it has no Draco handler in this container and returns
        # placeholder ZEROS (measured 100% zero on bmw-m3-e30), which would let
        # this tool confidently roll a car that was never measured.
        raise Unreadable("Draco-compressed positions — decompress first: "
                         "gltf-transform copy in.glb out.glb")
    n = acc["count"]
    nc = _NC[acc["type"]]
    fmt = _CT[acc["componentType"]]
    isz = np.dtype(fmt).itemsize
    bv = js["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or nc * isz
    if stride == nc * isz:
        buf = np.frombuffer(bin_, dtype=fmt, count=n * nc, offset=base)
        return buf.reshape(n, nc).astype(np.float64)
    out = np.empty((n, nc), dtype=np.float64)
    for i in range(n):
        o = base + i * stride
        out[i] = np.frombuffer(bin_, dtype=fmt, count=nc, offset=o)
    return out


def _node_matrix(nd):
    if "matrix" in nd:
        return np.array(nd["matrix"], dtype=np.float64).reshape(4, 4).T
    M = np.eye(4)
    if "scale" in nd:
        M = np.diag(list(nd["scale"]) + [1.0]) @ M
    if "rotation" in nd:
        x, y, z, w = nd["rotation"]
        R = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
            [0, 0, 0, 1]])
        M = R @ M
    if "translation" in nd:
        T = np.eye(4); T[:3, 3] = nd["translation"]
        M = T @ M
    return M


def world_points(js, bin_):
    """[(material_name, (N,3) world verts)] for every primitive with POSITION."""
    nodes = js.get("nodes", [])
    mats = js.get("materials", [])
    roots = []
    for s in js.get("scenes", [{}]):
        roots += s.get("nodes", [])
    if not roots:
        roots = list(range(len(nodes)))
    out = []
    seen = set()

    def walk(i, M):
        if i in seen and len(seen) > len(nodes):
            return
        nd = nodes[i]
        W = M @ _node_matrix(nd)
        if "mesh" in nd:
            for pr in js["meshes"][nd["mesh"]].get("primitives", []):
                pos = pr.get("attributes", {}).get("POSITION")
                if pos is None:
                    continue
                V = read_accessor(js, bin_, pos)
                Vw = (W[:3, :3] @ V.T).T + W[:3, 3]
                mi = pr.get("material")
                nm = mats[mi].get("name", "") if mi is not None and mi < len(mats) else ""
                out.append((nm, Vw))
        for c in nd.get("children", []):
            walk(c, W)

    for r in roots:
        walk(r, np.eye(4))
    return out


# candidate rotations: identity + all 90-degree turns about X and about Z.
# A rotation about the world-Y (yaw) can never change which way is up, so it is
# excluded — this tool fixes POSE, it does not choose which way the car faces.
_S = math.sqrt(0.5)
CANDIDATES = [
    ("identity", [0.0, 0.0, 0.0, 1.0]),
    ("roll+90",  [_S, 0.0, 0.0, _S]),
    ("roll180",  [1.0, 0.0, 0.0, 0.0]),
    ("roll-90",  [-_S, 0.0, 0.0, _S]),
    ("pitch+90", [0.0, 0.0, _S, _S]),
    ("pitch180", [0.0, 0.0, 1.0, 0.0]),
    ("pitch-90", [0.0, 0.0, -_S, _S]),
]


def quat_matrix(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def measure(prims, R):
    """World-referenced pose signals after applying rotation R (+Y is up)."""
    allv = np.vstack([(R @ V.T).T for _, V in prims])
    lo, hi = allv.min(0), allv.max(0)
    ext = hi - lo
    ylo, yspan = lo[1], (ext[1] or 1.0)

    def yfrac(mask_re, exclude=None):
        acc, n = 0.0, 0
        for nm, V in prims:
            if not mask_re.search(nm or ""):
                continue
            if exclude is not None and exclude.search(nm or ""):
                continue
            W = (R @ V.T).T
            acc += float(((W[:, 1] - ylo) / yspan).sum()); n += len(W)
        return (acc / n) if n else None, n

    tyre_y, tyre_n = yfrac(TYRE_RE)
    glass_y, glass_n = yfrac(GLASS_RE, exclude=LAMP_RE)

    # top_over_bot on the WORLD up axis, same construction as geom_audit
    yf = (allv[:, 1] - ylo) / yspan
    hz = allv[:, [0, 2]]

    def band(a, b):
        m = (yf >= a) & (yf <= b)
        if m.sum() < 20:
            return 0.0
        P = hz[m]
        return float(max(np.ptp(P[:, 0]), np.ptp(P[:, 1])))

    bot, top = band(0.0, 0.33), band(0.67, 1.0)
    tob = round(top / bot, 3) if bot > 1e-6 else 9.99
    length = max(ext[0], ext[2]) or 1.0
    return {"tyre_y": tyre_y, "tyre_n": tyre_n, "glass_y": glass_y,
            "glass_n": glass_n, "top_over_bot": tob,
            "h_over_l": round(float(ext[1] / length), 3),
            "y_is_smallest": bool(np.argmin(ext) == 1)}


def score(m, allow_proxy):
    """Higher is better; None means this candidate is not admissible."""
    if not m["y_is_smallest"]:
        return None                      # car is standing on its nose or side
    if m["tyre_y"] is not None:
        if m["tyre_y"] >= TYRE_MAX:
            return None
        if m["glass_y"] is not None and m["glass_y"] - m["tyre_y"] < GLASS_MIN_GAP:
            return None
        # tyres as low as possible, glazing as far above them as possible
        s = (1.0 - m["tyre_y"]) * 2.0
        if m["glass_y"] is not None:
            s += (m["glass_y"] - m["tyre_y"])
        return s
    if not allow_proxy:
        return None
    tob = m["top_over_bot"]
    if tob == 9.99 or not (0.40 <= tob <= 1.20):
        return None
    return 1.0 - abs(tob - 0.72)


def plan(path, allow_proxy=False):
    js, bin_ = load_glb(path)
    prims = world_points(js, bin_)
    if not prims:
        raise ValueError("no POSITION data")
    rows = []
    for name, q in CANDIDATES:
        m = measure(prims, quat_matrix(q))
        rows.append((name, q, m, score(m, allow_proxy)))
    named = any(TYRE_RE.search(nm or "") for nm, _ in prims)
    ok = [r for r in rows if r[3] is not None]
    best = max(ok, key=lambda r: r[3]) if ok else None
    return rows, best, named


def apply_rotation(src, dst, quat):
    """Reparent every scene root under one new node carrying `rotation`."""
    js, bin_ = load_glb(src)
    nodes = js.setdefault("nodes", [])
    new_i = len(nodes)
    for s in js.get("scenes", []):
        kids = s.get("nodes", [])
        if not kids:
            continue
        nodes.append({"name": "pose_fix", "rotation": [float(v) for v in quat],
                      "children": list(kids)})
        s["nodes"] = [new_i]
        new_i = len(nodes)
    write_glb(dst, js, bin_)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst")
    ap.add_argument("--allow-proxy", action="store_true",
                    help="permit a decision from top_over_bot alone when no "
                         "tyre material is named. Weaker evidence; it is "
                         "reported as PROXY so a caller can route it to the eye.")
    ap.add_argument("--report", action="store_true",
                    help="print every candidate's signals and exit")
    a = ap.parse_args()

    try:
        rows, best, named = plan(a.src, a.allow_proxy)
    except Unreadable as e:
        print(f"UNREADABLE: {e}")
        return 3
    basis = "TYRE" if named else ("PROXY" if a.allow_proxy else "NONE")
    if a.report or not a.dst:
        print(f"evidence basis: {basis}")
        for name, q, m, s in rows:
            ty = "  n/a" if m["tyre_y"] is None else f"{m['tyre_y']:.3f}"
            gl = "  n/a" if m["glass_y"] is None else f"{m['glass_y']:.3f}"
            print(f"  {name:9s} tyre_y={ty} glass_y={gl} tob={m['top_over_bot']:6.3f} "
                  f"h/l={m['h_over_l']:.3f} upright_axis={int(m['y_is_smallest'])} "
                  f"score={'-' if s is None else round(s, 4)}")
    if best is None:
        print("REFUSED: no candidate stands this car on its wheels "
              f"(basis {basis}) — not a pose fault, or not measurable")
        return 1
    name, q, m, s = best
    if name == "identity":
        print(f"ALREADY UPRIGHT (basis {basis}, tyre_y="
              f"{'n/a' if m['tyre_y'] is None else round(m['tyre_y'], 3)}, "
              f"tob={m['top_over_bot']}) — nothing written")
        return 1
    if not a.dst:
        print(f"WOULD APPLY {name} {q}")
        return 0
    apply_rotation(a.src, a.dst, q)
    # Re-measure the WRITTEN FILE, not the plan. CLAUDE.md's standing lesson is
    # that testing the function and never the integration is how a gate ends up
    # not existing; this reads the identity row of the output, so it proves the
    # root node was actually written and is actually being applied.
    ver_rows, _, _ = plan(a.dst, a.allow_proxy)
    vm = ver_rows[0][2]
    print(f"APPLIED {name} (basis {basis}) -> {a.dst}")
    print(f"  verify: tyre_y={'n/a' if vm['tyre_y'] is None else round(vm['tyre_y'],3)} "
          f"glass_y={'n/a' if vm['glass_y'] is None else round(vm['glass_y'],3)} "
          f"tob={vm['top_over_bot']} h/l={vm['h_over_l']}")
    if score(vm, a.allow_proxy) is None:
        print("  VERIFY FAILED — the written file is not upright; do not ship it")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
