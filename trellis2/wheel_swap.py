"""OEM wheel swap for GENERATED models.

TRELLIS.2 bakes wheels into the voxel grid, so at 1024-1536 resolution rims
come out melted (user-scored 4/10 — the single biggest quality gap). Fix:
detect the four wheel positions in the exported GLB and overlay clean
parametric wheels (tyre + spoked rim + brake disc) built as separate PBR
primitives. The original geometry/textures are untouched — the new wheels are
appended to the binary container the same way oem_paint appends textures, so
WebP-texture indirection and material order survive.

Detection assumptions (all true for our worker's output):
  - glTF Y-up, model normalized near the [-0.5, 0.5] aabb, identity node
    transforms (o_voxel.postprocess.to_glb exports a single unrotated node)
  - the car sits on its wheels (contact patches are the lowest geometry)
Orientation is NOT assumed: the ground-plane long axis comes from PCA, so a
3/4-view generation (car rotated around Y) is handled.

Input (handler): wheel_swap: true | {"style": "audi"} | false
"""
import json
import os
import struct
import sys

import numpy as np

# brand -> rim look, tuned toward each marque's signature alloy language.
# spokes = major arms; twin doubles each arm into a V pair; w_hub/w_rim are
# tangential arm widths (fractions of wheel radius) at hub and rim end.
WHEEL_STYLES = {
    "audi":       {"spokes": 5, "twin": False, "rim_hex": "#C9CDCF",
                   "w_hub": 0.17, "w_rim": 0.10},   # 5-arm star
    "bmw":        {"spokes": 5, "twin": True,  "rim_hex": "#BFC3C6",
                   "w_hub": 0.06, "w_rim": 0.045},  # M double-spoke
    "mercedes":   {"spokes": 5, "twin": False, "rim_hex": "#CDD1D3",
                   "w_hub": 0.18, "w_rim": 0.11},
    "land rover": {"spokes": 6, "twin": False, "rim_hex": "#9FA4A8",
                   "w_hub": 0.14, "w_rim": 0.11},   # 6-spoke utility
    "range rover": {"spokes": 6, "twin": False, "rim_hex": "#9FA4A8",
                    "w_hub": 0.14, "w_rim": 0.11},
    "volkswagen": {"spokes": 5, "twin": True,  "rim_hex": "#C5C9CB",
                   "w_hub": 0.075, "w_rim": 0.055},  # V-pair (GTE-ish)
    "porsche":    {"spokes": 5, "twin": False, "rim_hex": "#C9CDCF",
                   "w_hub": 0.16, "w_rim": 0.09},
    "black":      {"spokes": 5, "twin": True,  "rim_hex": "#26282B",
                   "w_hub": 0.075, "w_rim": 0.055},
    "default":    {"spokes": 5, "twin": False, "rim_hex": "#C5C9CB",
                   "w_hub": 0.15, "w_rim": 0.10},
}


# ---------------------------------------------------------------- GLB parsing
def _read_glb(path):
    data = open(path, "rb").read()
    if data[:4] != b"glTF":
        raise ValueError("not a GLB")
    jlen, jtype = struct.unpack("<II", data[12:20])
    j = json.loads(data[20:20 + jlen])
    rest = data[20 + jlen:]
    blen = struct.unpack("<I", rest[0:4])[0]
    return j, jtype, bytearray(rest[8:8 + blen])


def _write_glb(path, j, jtype, bin_data):
    while len(bin_data) % 4:
        bin_data.append(0)
    j["buffers"][0]["byteLength"] = len(bin_data)
    nj = json.dumps(j, separators=(",", ":")).encode()
    nj += b" " * ((4 - len(nj) % 4) % 4)
    out = (b"glTF" + struct.pack("<II", 2,
                                 12 + 8 + len(nj) + 8 + len(bin_data))
           + struct.pack("<II", len(nj), jtype) + nj
           + struct.pack("<I", len(bin_data)) + b"BIN\x00" + bytes(bin_data))
    # atomic: a hard kill mid-write must not leave a truncated GLB behind
    tmp = path + ".tmp"
    open(tmp, "wb").write(out)
    os.replace(tmp, path)


def compact_glb(glb_path):
    """Drop orphaned bufferView bytes. Every texture-writing stage appends a
    re-encoded blob and repoints the image, stranding the old bytes — ~10MB
    of dead weight per model after the full chain (review #8). Rebuilds the
    BIN chunk keeping only views referenced by accessors/images and remaps
    indices. Returns bytes saved, or None on any surprise (file untouched)."""
    try:
        j, jtype, bin_data = _read_glb(glb_path)
        used = set()
        for acc in j.get("accessors", []):
            if "bufferView" in acc:
                used.add(acc["bufferView"])
        for img in j.get("images", []):
            if "bufferView" in img:
                used.add(img["bufferView"])
        views = j.get("bufferViews", [])
        if len(used) == len(views):
            return 0
        new_bin = bytearray()
        remap = {}
        new_views = []
        for i, bv in enumerate(views):
            if i not in used:
                continue
            while len(new_bin) % 4:
                new_bin.append(0)
            off, ln = bv.get("byteOffset", 0), bv["byteLength"]
            nv = dict(bv)
            nv["byteOffset"] = len(new_bin)
            new_bin.extend(bin_data[off:off + ln])
            remap[i] = len(new_views)
            new_views.append(nv)
        j["bufferViews"] = new_views
        for acc in j.get("accessors", []):
            if "bufferView" in acc:
                acc["bufferView"] = remap[acc["bufferView"]]
        for img in j.get("images", []):
            if "bufferView" in img:
                img["bufferView"] = remap[img["bufferView"]]
        saved = len(bin_data) - len(new_bin)
        _write_glb(glb_path, j, jtype, new_bin)
        print(f"compact_glb: dropped {saved} orphaned bytes "
              f"({len(views) - len(new_views)} views)", file=sys.stderr)
        return saved
    except Exception as e:
        print(f"compact_glb skipped: {e}", file=sys.stderr)
        return None


def _positions(j, bin_data):
    """All POSITION vertices across all primitives (identity transforms)."""
    chunks = []
    for mesh in j.get("meshes", []):
        for prim in mesh.get("primitives", []):
            ai = (prim.get("attributes") or {}).get("POSITION")
            if ai is None:
                continue
            acc = j["accessors"][ai]
            if acc.get("componentType") != 5126 or acc.get("type") != "VEC3":
                continue
            bv = j["bufferViews"][acc["bufferView"]]
            off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            n = acc["count"]
            stride = bv.get("byteStride") or 12
            raw = np.frombuffer(bytes(bin_data[off:off + stride * n]),
                                dtype=np.uint8)
            raw = raw.reshape(n, stride)[:, :12].copy()
            chunks.append(raw.view(np.float32).reshape(n, 3))
    if not chunks:
        raise ValueError("no POSITION data")
    return np.concatenate(chunks, axis=0)


# ------------------------------------------------------------------ detection
def detect_wheels(verts):
    """Find 4 wheel centers. Returns dict or None if the geometry doesn't
    read as a wheels-on-ground car (gates below) — caller skips the swap."""
    y = verts[:, 1]
    y0 = np.percentile(y, 0.5)
    height = np.percentile(y, 99.5) - y0
    if height <= 0:
        return None

    # ground-plane frame: long axis u via PCA of XZ
    xz = verts[:, [0, 2]]
    c = xz.mean(axis=0)
    d = xz - c
    cov = d.T @ d / len(d)
    evals, evecs = np.linalg.eigh(cov)
    u_dir, v_dir = evecs[:, 1], evecs[:, 0]     # major, minor
    u = d @ u_dir
    v = d @ v_dir
    length = np.percentile(u, 99.5) - np.percentile(u, 0.5)
    if length <= 0:
        return None

    # contact patches: the very lowest geometry is tyre bottom
    patch = y < y0 + 0.06 * height
    if patch.sum() < 40:
        return None
    pu, pv = u[patch], v[patch]

    py = y[patch]
    centers, outer, grounds = [], [], []
    for su in (-1, 1):          # rear/front (sign along u)
        for sv in (-1, 1):      # left/right
            m = (np.sign(pu - np.median(u)) == su) & (np.sign(pv) == sv)
            if m.sum() < 10:
                return None
            centers.append((np.median(pu[m]), np.median(pv[m])))
            outer.append(np.percentile(np.abs(pv[m]), 95))
            grounds.append(np.percentile(py[m], 5))
    centers = np.array(centers)
    # each wheel sits on ITS OWN measured ground: the global percentile floor
    # sat ~15% of a wheel radius above the true tyre bottoms on the live
    # Golf, floating the overlays and letting the old tyre poke out beneath
    # (read as "crooked wheels" in review)
    gmed = float(np.median(grounds))
    grounds = [float(np.clip(g, gmed - 0.02 * length, gmed + 0.02 * length))
               for g in grounds]

    # sanity gates: plausible wheelbase, track symmetry, axle alignment
    wheelbase = abs((centers[0, 0] + centers[1, 0]) / 2
                    - (centers[2, 0] + centers[3, 0]) / 2)
    if not (0.40 * length < wheelbase < 0.85 * length):
        return None
    track = np.abs(centers[:, 1])
    if track.max() > 1.6 * max(track.min(), 1e-6):
        return None
    if abs(centers[0, 0] - centers[1, 0]) > 0.10 * length:
        return None
    if abs(centers[2, 0] - centers[3, 0]) > 0.10 * length:
        return None

    # radius: real-car heuristic (tyre radius ~= 0.115 * wheelbase), refined
    # by measuring the arch-opening height above each contact patch. The
    # wheel must FIT INSIDE the arch (user-confirmed oversize when the column
    # reached fender/door height): cap the column just above arch level and
    # size the tyre to sit inside the opening with a visible gap.
    r_h = 0.115 * wheelbase
    measured = []
    for (cu, cv), out_v in zip(centers, outer):
        col = ((np.abs(u - cu) < 0.75 * r_h)
               & (np.sign(v) == np.sign(cv))
               & (np.abs(v) > abs(cv) - 0.35 * r_h)
               & (y < y0 + 2.6 * r_h))
        if col.sum() > 30:
            measured.append((np.percentile(y[col], 97) - y0) / 2 * 0.92)
    if measured:
        r_h = float(np.clip(np.median(measured), 0.85 * r_h, 1.15 * r_h))
    radius = float(np.clip(r_h, 0.045 * length, 0.10 * length))
    # wheel axis = the MEASURED axle line (left->right pair centers), not the
    # PCA minor axis — kills any residual toe on skewed generations
    ax_uv = ((centers[1] - centers[0]) + (centers[3] - centers[2])) / 2
    ax_xz = ax_uv[0] * u_dir + ax_uv[1] * v_dir
    ax_xz /= max(np.linalg.norm(ax_xz), 1e-12)
    # Y-rotation mapping local +X to the axle direction: rotation about +Y
    # takes +X to (cos a, 0, -sin a), so a = atan2(-z, x)
    yaw = float(np.arctan2(-ax_xz[1], ax_xz[0]))
    # body half-width at fender height: tyre outer face should sit flush with
    # the body side, not proud of it (live Golf test: patch-based placement
    # pushed wheels visibly out of the arches)
    band = (y > y0 + 0.25 * height) & (y < y0 + 0.55 * height)
    body_half = float(np.percentile(np.abs(v[band]), 99)) if band.sum() > 100 \
        else float(np.median(track))
    world = []
    for (cu, cv), out_v, g in zip(centers, outer, grounds):
        target = abs(cv)
        if body_half > 0.7 * radius:
            target = min(max(abs(cv), out_v - 0.31 * radius),
                         body_half - 0.32 * radius)
        cv = np.sign(cv) * max(target, 0.35 * radius)
        p = c + u_dir * cu + v_dir * cv
        world.append([float(p[0]), float(g + radius), float(p[1])])
    return {"centers": world, "sides": [-1, 1, -1, 1], "radius": radius,
            "yaw": yaw, "wheelbase": float(wheelbase), "length": float(length),
            "ground": float(gmed)}


# ----------------------------------------------------------- wheel mesh build
def _orient(V, F):
    """Flip faces if the signed volume is negative — guarantees outward
    normals regardless of profile traversal direction (a hand-checked winding
    rendered inside-out in Cycles; measuring beats re-deriving)."""
    cr = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    if float(np.einsum("ij,ij->", V[F[:, 0]].astype(np.float64),
                       cr.astype(np.float64))) < 0:
        F = F[:, [0, 2, 1]]
    return V, F


def _lathe(profile, nseg=48):
    """Surface of revolution around local X. profile: [(radial, axial), ...]"""
    ang = np.linspace(0, 2 * np.pi, nseg, endpoint=False)
    rings = []
    for rr, aa in profile:
        rings.append(np.stack([np.full(nseg, aa),
                               rr * np.cos(ang), rr * np.sin(ang)], axis=1))
    V = np.concatenate(rings, axis=0)
    F = []
    for i in range(len(profile) - 1):
        a, b = i * nseg, (i + 1) * nseg
        for k in range(nseg):
            k2 = (k + 1) % nseg
            F += [[a + k, b + k2, b + k], [a + k, a + k2, b + k2]]
    return _orient(V, np.array(F, dtype=np.int64))


def _disk(rr_in, rr_out, aa, nseg=48):
    # flat annulus: signed volume = aa * area, so _orient in _lathe faces it
    # away from the origin — correct for the outboard (+X) lip
    return _lathe([(rr_in, aa), (rr_out, aa)], nseg)


def _box(hx, hy, hz):
    s = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1)
                  for sz in (-1, 1)], dtype=np.float64)
    V = s * [hx, hy, hz]
    F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5],
                  [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                  [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]], dtype=np.int64)
    return _orient(V, F)


def _spoke(t, y0, y1, w0, w1, c0, c1, xc):
    """Tapered prism arm: radial span y0->y1, tangential width w0->w1,
    tangential center offset c0->c1 (V-pairs), axial thickness t at xc."""
    V = np.zeros((8, 3))
    i = 0
    for ix in (-1, 1):
        for (yy, ww, cc) in ((y0, w0, c0), (y1, w1, c1)):
            for iz in (-1, 1):
                V[i] = [xc + ix * t / 2, yy, cc + iz * ww / 2]
                i += 1
    F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5],
                  [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                  [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]], dtype=np.int64)
    return _orient(V, F)


def _rot_x(V, angle):
    ca, sa = np.cos(angle), np.sin(angle)
    R = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])
    return V @ R.T


def _merge(parts):
    V, F, off = [], [], 0
    for v, f in parts:
        V.append(v)
        F.append(f + off)
        off += len(v)
    return np.concatenate(V), np.concatenate(F)


def _normals(V, F):
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    N = np.zeros_like(V)
    for i in range(3):
        np.add.at(N, F[:, i], fn)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.maximum(ln, 1e-12)


def build_wheel(radius, style):
    """Wheel meshes in local coords: axis = +X (outboard face at +X).
    Returns [(V, F, material_key), ...]."""
    r = radius
    w = 0.62 * r                      # tyre width (~235/700 automotive ratio)
    rim_r = 0.74 * r                  # modern low-profile rim
    # tyre: near-vertical sidewalls + flat tread, sized exactly to the
    # detected radius — the arch fit matters more than covering every last
    # sliver of the original wheel (user-confirmed)
    tyre_prof = [(rim_r * 0.97, -w / 2), (0.96 * r, -w * 0.44),
                 (1.00 * r, -w * 0.34), (1.00 * r, w * 0.34),
                 (0.96 * r, w * 0.44), (rim_r * 0.97, w / 2)]
    tyre = _lathe(tyre_prof)
    barrel = _lathe([(rim_r * 0.94, -w * 0.40), (rim_r * 0.94, w * 0.42),
                     (rim_r, w * 0.44)])
    lip = _disk(rim_r * 0.86, rim_r * 0.99, w * 0.42)
    hub = _lathe([(0.0, w * 0.28), (0.20 * r, w * 0.28),
                  (0.20 * r, w * 0.40), (0.0, w * 0.41)])

    n = style.get("spokes", 5)
    twin = style.get("twin", False)
    w0 = style.get("w_hub", 0.15) * r
    w1 = style.get("w_rim", 0.10) * r
    y0s, y1s = 0.16 * r, rim_r * 0.92
    spokes = []
    for k in range(n):
        base = 2 * np.pi * k / n
        for sgn in ((-1, 1) if twin else (0,)):
            # twin: V pair joined at the hub, opening toward the rim
            sv, sf = _spoke(0.05 * r, y0s, y1s, w0, w1,
                            sgn * 0.020 * r, sgn * 0.105 * r, w * 0.35)
            spokes.append((_rot_x(sv, base), sf))
    rim = _merge([barrel, lip, hub] + spokes)

    # brake sits just behind the spokes so it reads through the gaps
    disc = _lathe([(0.10 * r, w * 0.28), (0.62 * rim_r, w * 0.28),
                   (0.62 * rim_r, w * 0.20), (0.10 * r, w * 0.20)])
    cal_v, cal_f = _box(0.10 * r, 0.16 * r, 0.09 * r)
    cal = (_rot_x(cal_v + [w * 0.24, 0.54 * rim_r, 0], 0.35), cal_f)
    brake = _merge([disc, cal])

    return [(tyre[0], tyre[1], "tyre"), (rim[0], rim[1], "rim"),
            (brake[0], brake[1], "brake")]


# ------------------------------------------------------------------ GLB merge
def _hex_rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)] + [1.0]


def apply_wheel_swap(glb_path, spec=True):
    """Overlay parametric OEM-style wheels on a generated car GLB.
    Returns report dict, or None if detection failed (GLB left untouched)."""
    try:
        style_key = "default"
        if isinstance(spec, dict):
            style_key = (spec.get("style") or "default").lower().strip()
        style = None
        for k, v in WHEEL_STYLES.items():
            if k != "default" and k in style_key:
                style = v
                break
        style = style or WHEEL_STYLES.get(style_key, WHEEL_STYLES["default"])

        j, jtype, bin_data = _read_glb(glb_path)
        det = detect_wheels(_positions(j, bin_data))
        if det is None:
            print("wheel_swap: no confident 4-wheel detection, skipped",
                  file=sys.stderr)
            return None

        parts = build_wheel(det["radius"], style)

        mat_pbr = {
            "tyre": {"baseColorFactor": [0.055, 0.055, 0.06, 1.0],
                     "metallicFactor": 0.0, "roughnessFactor": 0.92},
            "rim": {"baseColorFactor": _hex_rgb(style["rim_hex"]),
                    "metallicFactor": 0.9, "roughnessFactor": 0.28},
            "brake": {"baseColorFactor": [0.36, 0.37, 0.38, 1.0],
                      "metallicFactor": 0.85, "roughnessFactor": 0.45},
        }

        def append_view(blob, target=None):
            while len(bin_data) % 4:
                bin_data.append(0)
            start = len(bin_data)
            bin_data.extend(blob)
            view = {"buffer": 0, "byteOffset": start, "byteLength": len(blob)}
            if target:
                view["target"] = target
            j.setdefault("bufferViews", []).append(view)
            return len(j["bufferViews"]) - 1

        prims = []
        for V, F, key in parts:
            V = V.astype(np.float32)
            N = _normals(V, F).astype(np.float32)
            F = F.astype(np.uint32)
            acc = j.setdefault("accessors", [])
            mats = j.setdefault("materials", [])
            # doubleSided: renderers flip normals on backfaces, so any lathe
            # patch with inverted winding still lights correctly
            mats.append({"name": f"wheel_{key}", "doubleSided": True,
                         "pbrMetallicRoughness": mat_pbr[key]})
            pos_bv = append_view(V.tobytes(), 34962)
            acc.append({"bufferView": pos_bv, "componentType": 5126,
                        "count": len(V), "type": "VEC3",
                        "min": V.min(0).tolist(), "max": V.max(0).tolist()})
            pos_a = len(acc) - 1
            nrm_bv = append_view(N.tobytes(), 34962)
            acc.append({"bufferView": nrm_bv, "componentType": 5126,
                        "count": len(N), "type": "VEC3"})
            nrm_a = len(acc) - 1
            idx_bv = append_view(F.tobytes(), 34963)
            acc.append({"bufferView": idx_bv, "componentType": 5125,
                        "count": int(F.size), "type": "SCALAR"})
            prims.append({"attributes": {"POSITION": pos_a, "NORMAL": nrm_a},
                          "indices": len(acc) - 1,
                          "material": len(mats) - 1})

        j.setdefault("meshes", []).append({"name": "oem_wheel",
                                           "primitives": prims})
        wheel_mesh = len(j["meshes"]) - 1

        nodes = j.setdefault("nodes", [])
        scene = j.setdefault("scenes", [{"nodes": []}])[j.get("scene", 0)]
        yaw = det["yaw"]
        for center, side in zip(det["centers"], det["sides"]):
            # local +X (wheel axis) -> world lateral dir, flipped per side
            a = yaw + (0.0 if side > 0 else np.pi)
            q = [0.0, float(np.sin(a / 2)), 0.0, float(np.cos(a / 2))]
            nodes.append({"mesh": wheel_mesh, "translation": center,
                          "rotation": q, "name": "oem_wheel_node"})
            scene.setdefault("nodes", []).append(len(nodes) - 1)

        _write_glb(glb_path, j, jtype, bin_data)
        print(f"wheel_swap: 4 wheels r={det['radius']:.3f} "
              f"wheelbase={det['wheelbase']:.3f} style={style_key}",
              file=sys.stderr)
        return {"applied": True, "radius": round(det["radius"], 4),
                "wheelbase": round(det["wheelbase"], 4), "style": style_key}
    except Exception as e:
        print(f"wheel_swap skipped: {e}", file=sys.stderr)
        return None
