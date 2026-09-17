#!/usr/bin/env python3
"""panel_cut.py — cut a removable PANEL out of a one-piece body shell.

WHY THIS EXISTS. The owner asked for a teardown trainer where you take the
bonnet, a wing, the bumper and the mirror off with the correct fasteners in
the correct places. Measured against `volkswagen-golf-2021-w12-v1`, across
all 163 named meshes:

    doors          separate  (4)      bumper      ABSENT
    wheels         separate  (8)      bonnet      ABSENT
    front discs    separate  (2)      wing        ABSENT
    calipers       separate  (3)      mirror      ABSENT
    check straps   separate  (4)      door lock   ABSENT

The absent ones are not missing meshes — they are *inside* the 88,201-face
body shell, which is one welded visual object. No app logic can take a wing
off a wing that is not an object, so the panel has to be CUT.

THE SPLIT IS INDEX-ONLY, AND THAT IS THE WHOLE SAFETY ARGUMENT.
Vertex data is never touched: POSITION, NORMAL, TEXCOORD and TANGENT
accessors are shared byte-for-byte between the panel and the remaining
shell. Only new INDEX buffers are appended. So this tool cannot:
  * drop NORMAL accessors (the recorded crumpled-foil class),
  * drop TANGENT (the recorded Tripo validator class),
  * drop a KHR material extension (the recorded trimesh round-trip class),
  * move a vertex (the recorded vertex-pull panel-denting class).
It is the pose_fix / clay_rebuild discipline applied to topology: edit the
glTF, leave the geometry alone.

HOW THE BONNET BOUNDARY WAS FOUND — measured, not styled. Up-facing panel
faces were profiled across |X| at four Z stations. At every station the face
count spikes and the up-ness drops at the same place:

    Z +1.40   |X| 0.00-0.70   n=12-44    ny 0.95-0.99    <- bonnet, smooth
              |X| 0.70-0.80   n=144      ny 0.789        <- SHUT LINE
              |X| 0.80-0.90   n=120      ny 0.646        <- wing, turning down

THE TESSELLATION DENSITY IS THE CREASE. A sourced car spends triangles where
the panel edge is, so a density spike beside an up-ness drop locates a shut
line without any need to guess a styling dimension. The bonnet half-width
measured 0.67 m at the scuttle tapering to 0.58 m at the nose, which is why
HALF_W below is a taper and not a constant.

REFUSES rather than guesses. A selection that is empty, or that grabs more
than a stated share of the shell, or whose area is implausible for the panel,
aborts without writing — because a panel that silently takes half the car
with it looks fine until a trainee removes it.

Run:
  python3 panel_cut.py in.glb out.glb --panel bonnet
  python3 panel_cut.py in.glb out.glb --panel bonnet --report-only
"""
import argparse
import json
import struct

import numpy as np

CT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
      5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

# Shell parts a panel may be cut from. The chrome strips, reflectors and
# plate lights are separate meshes already and are deliberately NOT cut.
SHELL = ("Ext_Body_Car_Paint", "Ext_Body_Material_Atlas", "ExtBody_Material_Atlas")


def read(p):
    d = open(p, "rb").read()
    if d[:4] != b"glTF":
        raise SystemExit(f"REFUSED: {p} is not a binary glTF")
    n = struct.unpack("<I", d[12:16])[0]
    j = json.loads(d[20:20 + n])
    rest = d[20 + n:]
    blen = struct.unpack("<I", rest[:4])[0]
    return j, bytearray(rest[8:8 + blen])


def write(p, j, bin_):
    while len(bin_) % 4:
        bin_.append(0)
    j["buffers"][0]["byteLength"] = len(bin_)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_)
    with open(p, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<I", len(js)) + b"JSON" + js)
        f.write(struct.pack("<I", len(bin_)) + b"BIN\x00" + bytes(bin_))


def node_matrix(nd):
    if "matrix" in nd:
        return np.array(nd["matrix"], dtype=float).reshape(4, 4).T
    m = np.eye(4)
    if "scale" in nd:
        m[:3, :3] = np.diag(nd["scale"]) @ m[:3, :3]
    if "rotation" in nd:
        x, y, z, w = nd["rotation"]
        m[:3, :3] = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]
        ]) @ m[:3, :3]
    if "translation" in nd:
        m[:3, 3] = nd["translation"]
    return m


class Gltf:
    def __init__(self, path):
        self.j, self.bin = read(path)

    def acc(self, i):
        a = self.j["accessors"][i]
        bv = self.j["bufferViews"][a["bufferView"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        n = NC[a["type"]]
        fmt, isz = CT[a["componentType"]]
        stride = bv.get("byteStride") or isz * n
        buf = np.frombuffer(bytes(self.bin), dtype=np.uint8)
        idx = off + np.arange(a["count"])[:, None] * stride + np.arange(n * isz)[None, :]
        return np.frombuffer(buf[idx].tobytes(),
                             dtype=np.dtype("<" + fmt)).reshape(a["count"], n)

    def leaves(self):
        nodes = self.j["nodes"]
        sc = self.j["scenes"][self.j.get("scene", 0)]
        out = []

        def walk(i, P):
            nd = nodes[i]
            M = P @ node_matrix(nd)
            nm = nd.get("name", "")
            if nm.startswith("G:"):
                nm = nm[2:]
            if nd.get("mesh") is not None:
                out.append((i, nm, nd["mesh"], M))
            for c in nd.get("children", []):
                walk(c, M)
        for r in sc["nodes"]:
            walk(r, np.eye(4))
        return out

    def append_indices(self, arr):
        """Append an index array; return a new accessor index.

        Promotes to uint32 unconditionally. A uint16 buffer would be smaller,
        but the panel's indices point into the SHARED vertex array, whose
        count can exceed 65535 even when the panel itself is small — and a
        silent overflow there would scramble the panel rather than fail.
        """
        arr = np.asarray(arr, dtype="<u4")
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin.extend(arr.tobytes())
        self.j["bufferViews"].append(
            {"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes,
             "target": 34963})
        self.j["accessors"].append(
            {"bufferView": len(self.j["bufferViews"]) - 1, "byteOffset": 0,
             "componentType": 5125, "count": int(arr.size), "type": "SCALAR"})
        return len(self.j["accessors"]) - 1


def _adjacency(tri, vw):
    """Face pairs sharing a welded edge, plus their dihedral angle."""
    q = np.round(vw * 1e5).astype(np.int64)
    _, vid = np.unique(q, axis=0, return_inverse=True)
    wf = vid[tri]
    e = np.sort(np.concatenate([wf[:, [0, 1]], wf[:, [1, 2]], wf[:, [2, 0]]]), axis=1)
    fid = np.tile(np.arange(len(wf)), 3)
    o = np.lexsort((e[:, 1], e[:, 0]))
    e, fid = e[o], fid[o]
    same = np.all(e[1:] == e[:-1], axis=1)
    pa, pb = fid[:-1][same], fid[1:][same]
    P = vw[tri]
    nr = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    L = np.linalg.norm(nr, axis=1)
    g = L > 1e-12
    nr[g] /= L[g, None]
    cos = np.clip(np.einsum("ij,ij->i", nr[pa], nr[pb]), -1.0, 1.0)
    return pa, pb, np.degrees(np.arccos(cos))


def explain_frontier(tri, vw, cur, env, nr, c, crease_deg, spec):
    """Say WHY the grown panel stopped where it did, edge by edge.

    A ragged or short panel edge has exactly two possible causes — a crease
    the fill correctly refused to cross, or an envelope limit somebody typed.
    Guessing between them is a tuning loop; counting them is one run.
    """
    pa, pb, ang = _adjacency(tri, vw)
    onein = cur[pa] ^ cur[pb]
    fa, fb, fang = pa[onein], pb[onein], ang[onein]
    out = np.where(cur[fa], fb, fa)
    bc = fang >= crease_deg
    be = ~env[out]
    print(f"    why: {onein.sum()} frontier edges — "
          f"crease {int((bc & ~be).sum())}, envelope {int((be & ~bc).sum())}, "
          f"both {int((bc & be).sum())}, neither {int((~bc & ~be).sum())}")
    if (be & ~bc).any():
        co, no = c[out[be & ~bc]], nr[out[be & ~bc]]
        print(f"         envelope-blocked extent: "
              f"X {co[:,0].min():+.3f}..{co[:,0].max():+.3f} "
              f"Y {co[:,1].min():+.3f}..{co[:,1].max():+.3f} "
              f"Z {co[:,2].min():+.3f}..{co[:,2].max():+.3f}")
    if (~bc & ~be).any():
        print(f"         WARNING {int((~bc & ~be).sum())} edges blocked by "
              f"NEITHER — the fill stopped for an unexplained reason")


def panel_topology(tri):
    """(components, boundary_loops) of a face set, on a welded topology.

    THIS IS THE REAL GATE, and it replaced an area band that could not catch
    anything. A correct panel is ONE connected component with ONE boundary
    loop — the shut line all the way round. A flood-fill leak across a smooth
    surface, or a fragmented selection, shows up here immediately and cannot
    show up in a total area:

        cut at 1.23 m2 (short at the front)  comps 1  loops 1  holes 0
        cut at 1.54 m2 (grown to the crease) comps 1  loops 1  holes 0

    Both clean, so the wider one is the real panel rather than a leak — which
    is the question an area band was being asked to answer and could not. It
    is `glass_topo`'s components/loops/holes measurement pointed at a cut
    instead of at glazing.
    """
    tri = np.asarray(tri)
    par = np.arange(int(tri.max()) + 1)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for f in tri:
        for u, v in ((f[0], f[1]), (f[1], f[2])):
            ru, rv = find(u), find(v)
            if ru != rv:
                par[ru] = rv
    comps = len({find(v) for v in np.unique(tri)})
    e = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    uniq, cnt = np.unique(e, axis=0, return_counts=True)
    bnd = uniq[cnt == 1]
    adj = {}
    for u, v in bnd:
        adj.setdefault(u, []).append(v)
        adj.setdefault(v, []).append(u)
    seen, loops = set(), 0
    for s0 in adj:
        if s0 in seen:
            continue
        loops += 1
        stack = [s0]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(adj[x])
    return comps, loops, len(bnd)


def grow_to_crease(tri, vw, seed, envelope, crease_deg=26.0, max_iter=400):
    """Grow a seed face set outward, stopping at CREASES.

    The region predicate alone gives a sawtooth boundary, because it tests
    triangle CENTROIDS and a triangle straddling the edge is either wholly
    in or wholly out. Measured on the Golf bonnet: the selection landed
    inside the real panel on all four sides and its border zigzagged.

    A panel edge on a SOURCED car is a real dihedral discontinuity — the
    face-density spike that located the shut line is that crease being
    tessellated. So flood-fill across face adjacency and refuse to cross an
    edge sharper than `crease_deg`; the boundary then snaps to the panel
    edge and the sawtooth disappears.

    This is `glass_relabel`'s crease-bounded fill, and the recorded reason
    that stage misbehaved does NOT apply here: it walked onto roof and doors
    on a 40k generated mesh that had no crease at the A-pillar to stop
    against. This is an 88k sourced shell whose creases were measured before
    the fill was written. `envelope` is still enforced every step, so even a
    total crease failure cannot take the roof.

    Adjacency is built on a COORDINATE-QUANTISED weld, not on raw indices: a
    GLB stores split vertices wherever normals or UVs differ, so index-based
    adjacency breaks at arbitrary places (and at the crease itself).
    """
    q = np.round(vw * 1e5).astype(np.int64)
    _, vid = np.unique(q, axis=0, return_inverse=True)
    wf = vid[tri]                                     # welded face corners
    # edge -> faces
    e = np.concatenate([wf[:, [0, 1]], wf[:, [1, 2]], wf[:, [2, 0]]])
    e = np.sort(e, axis=1)
    fid = np.tile(np.arange(len(wf)), 3)
    order = np.lexsort((e[:, 1], e[:, 0]))
    e, fid = e[order], fid[order]
    same = np.all(e[1:] == e[:-1], axis=1)
    pa, pb = fid[:-1][same], fid[1:][same]            # face pairs sharing an edge

    P = vw[tri]
    nr = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    L = np.linalg.norm(nr, axis=1)
    good = L > 1e-12
    nr[good] /= L[good, None]
    cosang = np.clip(np.einsum("ij,ij->i", nr[pa], nr[pb]), -1.0, 1.0)
    smooth = np.degrees(np.arccos(cosang)) < crease_deg
    pa, pb = pa[smooth], pb[smooth]                   # crossable edges only

    # CSR-ish neighbour lists over the crossable edges
    src = np.concatenate([pa, pb])
    dst = np.concatenate([pb, pa])
    o = np.argsort(src, kind="stable")
    src, dst = src[o], dst[o]
    start = np.searchsorted(src, np.arange(len(wf) + 1))

    cur = seed.copy()
    for _ in range(max_iter):
        frontier = np.flatnonzero(cur)
        cand = np.concatenate([dst[start[f]:start[f + 1]] for f in frontier]) \
            if len(frontier) else np.empty(0, dtype=np.int64)
        if not len(cand):
            break
        cand = np.unique(cand)
        new = cand[~cur[cand] & envelope[cand]]
        if not len(new):
            break
        cur[new] = True
    return cur


# ── panel definitions ────────────────────────────────────────────────────
# Every constant here was measured on volkswagen-golf-2021-w12-v1 after
# scale_normalise (metres, +X left, +Y up, +Z nose, ground Y=0). They are
# NOT styling numbers and they are NOT transferable to another car without
# re-running the profile that produced them.

def bonnet_mask(c, nrm):
    """SEED: comfortably inside the bonnet, so growth does the boundary.

    The half-width taper 0.67 -> 0.58 is the measured position of the
    density spike. The seed is pulled IN from it so the fill, not the
    predicate, decides the edge."""
    z = c[:, 2]
    t = np.clip((z - 1.115) / (1.920 - 1.115), 0.0, 1.0)
    half_w = 0.670 - 0.090 * t
    return ((z >= 1.19) & (z <= 1.85) &
            (c[:, 1] > 0.60) &
            (np.abs(c[:, 0]) <= half_w - 0.07) &
            (nrm[:, 1] > 0.70))


def bonnet_envelope(c, nrm):
    """HARD CEILING on the fill. Even with every crease missing, the panel
    cannot escape the bonnet aperture: behind the scuttle, past the nose,
    below the wing crown, or onto a downward-facing surface.

    Z WAS WIDENED AFTER MEASURING, not after guessing. `--why` on the first
    grown cut classified all 134 frontier edges: 78 stopped at a real crease
    (the wing shut lines and the scuttle — correct, and visible as clean
    straight edges in the matID render), and all 54 envelope-blocked ones
    were the Z limits (18 rear, 36 front) with ZERO blocked by Y, |X| or
    normal. So the sides were crease-limited and only the front and rear
    were being cut short by arbitrary numbers. Widened to let the crease
    decide there too; `ny > 0.18` still stops the fill walking down the nose
    onto the grille, which is the real risk of opening Z up.""" 
    return ((c[:, 2] >= 1.00) & (c[:, 2] <= 2.12) &
            (c[:, 1] > 0.55) &
            (np.abs(c[:, 0]) <= 0.80) &
            (nrm[:, 1] > 0.18))


PANELS = {
    "bonnet": dict(
        fn=bonnet_mask,
        env=bonnet_envelope,
        crease_deg=26.0,
        label="Panel_Bonnet",
        # Advisory only, and deliberately wide: a bonnet's SKIN area exceeds
        # its plan area because the panel is crowned and wraps down over the
        # wing tops, so a remembered "1.25 x 0.85 m" figure under-predicts it
        # and nearly had me reject a correct cut. The topology gate is what
        # decides; this only catches an order-of-magnitude mistake.
        area_m2=(0.60, 2.20),
        max_share=0.25,
        hinge=dict(y=0.975, z=1.115),   # rear edge at the scuttle, axis on X
        open_deg=52.0),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--panel", required=True, choices=sorted(PANELS))
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--why", action="store_true",
                    help="classify every frontier edge as crease-blocked or "
                         "envelope-blocked, and say which envelope limit bit. "
                         "This is the difference between one measured fix and "
                         "a blind tuning loop — run it before touching a constant.")
    a = ap.parse_args()
    if not a.report_only and not a.out:
        raise SystemExit("REFUSED: give an output path, or --report-only")

    spec = PANELS[a.panel]
    g = Gltf(a.inp)

    # Gather the shell primitives and find the panel faces in each.
    hits, total_faces = [], 0
    for node_i, nm, mesh_i, M in g.leaves():
        if not nm.startswith(SHELL):
            continue
        mesh = g.j["meshes"][mesh_i]
        for pi, prim in enumerate(mesh.get("primitives", [])):
            if prim.get("indices") is None:
                continue
            v = g.acc(prim["attributes"]["POSITION"]).astype(float)
            vw = (np.c_[v, np.ones(len(v))] @ M.T)[:, :3]
            idx = g.acc(prim["indices"]).astype(np.int64).ravel()
            tri = idx.reshape(-1, 3)
            total_faces += len(tri)
            P = vw[tri]
            c = P.mean(axis=1)
            nr = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
            L = np.linalg.norm(nr, axis=1)
            good = L > 1e-12
            nr[good] /= L[good, None]
            area = 0.5 * L
            m = spec["fn"](c, nr) & good
            if m.any() and spec.get("env") is not None:
                env = spec["env"](c, nr) & good
                before = int(m.sum())
                m = grow_to_crease(tri, vw, m, env,
                                   crease_deg=spec.get("crease_deg", 26.0))
                print(f"    grow: {before:,} seed -> {int(m.sum()):,} faces "
                      f"(envelope allowed {int(env.sum()):,})")
                if a.why:
                    explain_frontier(tri, vw, m, env, nr, c,
                                     spec.get("crease_deg", 26.0), spec)
            if m.any():
                hits.append(dict(node=node_i, name=nm, mesh=mesh_i, prim=pi,
                                 tri=tri, mask=m, area=area[m].sum(),
                                 cen=c[m], vw=vw, mat=prim.get("material")))

    if not hits:
        raise SystemExit(f"REFUSED: no faces selected for '{a.panel}'. The "
                         f"region predicate found nothing — measure the shell "
                         f"before changing the constants.")

    sel = sum(int(h["mask"].sum()) for h in hits)
    area = sum(h["area"] for h in hits)
    cen = np.vstack([h["cen"] for h in hits])
    share = sel / max(total_faces, 1)
    print(f"panel '{a.panel}': {sel:,} of {total_faces:,} shell faces "
          f"({share*100:.2f}%), area {area:.4f} m2")
    print(f"  extent  X {cen[:,0].min():+.3f}..{cen[:,0].max():+.3f}  "
          f"Y {cen[:,1].min():+.3f}..{cen[:,1].max():+.3f}  "
          f"Z {cen[:,2].min():+.3f}..{cen[:,2].max():+.3f}")
    print(f"  across {len(hits)} primitive(s)")

    lo, hi = spec["area_m2"]
    if not (lo <= area <= hi):
        raise SystemExit(f"REFUSED: area {area:.3f} m2 outside the plausible "
                         f"{lo}-{hi} m2 for a {a.panel}. Either the predicate "
                         f"is wrong or this is not the car it was measured on.")
    if share > spec["max_share"]:
        raise SystemExit(f"REFUSED: selection is {share*100:.1f}% of the shell, "
                         f"over the {spec['max_share']*100:.0f}% ceiling. A "
                         f"runaway region would take half the car off with it.")

    # topology gate — the one that can actually catch a leak
    wtri = []
    for h in hits:
        v = h["vw"]
        q = np.round(v * 1e5).astype(np.int64)
        _, vid = np.unique(q, axis=0, return_inverse=True)
        wtri.append(vid[h["tri"][h["mask"]]])
    off, parts = 0, []
    for w in wtri:
        parts.append(w + off)
        off += int(w.max()) + 1
    comps, loops, bnd = panel_topology(np.vstack(parts))
    print(f"  topology: {comps} component(s), {loops} boundary loop(s), "
          f"{bnd} boundary edges -> holes {loops - comps}")
    if comps != 1 or loops != 1:
        raise SystemExit(
            f"REFUSED: a panel must be ONE component with ONE boundary loop; "
            f"got {comps} component(s) and {loops} loop(s). More than one "
            f"component is a fragmented selection; more than one loop is a "
            f"hole or a fill that leaked around the end of a crease.")
    if a.report_only:
        print("report-only: nothing written")
        return

    # ── the cut: index-only, vertex data shared and untouched ────────────
    panel_prims = []
    for h in hits:
        keep = h["tri"][~h["mask"]].ravel()
        take = h["tri"][h["mask"]].ravel()
        src = g.j["meshes"][h["mesh"]]["primitives"][h["prim"]]
        src["indices"] = g.append_indices(keep)          # shell minus panel
        p = dict(attributes=dict(src["attributes"]),      # SAME accessors
                 indices=g.append_indices(take),
                 mode=src.get("mode", 4))
        if h["mat"] is not None:
            p["material"] = h["mat"]
        panel_prims.append(p)

    g.j["meshes"].append({"name": spec["label"], "primitives": panel_prims})
    hinge = spec["hinge"]
    g.j["nodes"].append({"name": spec["label"],
                         "mesh": len(g.j["meshes"]) - 1})
    g.j["scenes"][g.j.get("scene", 0)]["nodes"].append(len(g.j["nodes"]) - 1)
    write(a.out, g.j, g.bin)

    # ── verify the WRITTEN file, never the intent ────────────────────────
    g2 = Gltf(a.out)
    names = {n.get("name") for n in g2.j["nodes"]}
    assert spec["label"] in names, "panel node missing from the written file"
    pmesh = next(m for m in g2.j["meshes"] if m.get("name") == spec["label"])
    got = sum(g2.j["accessors"][p["indices"]]["count"] // 3
              for p in pmesh["primitives"])
    assert got == sel, f"panel holds {got} faces, expected {sel}"
    # the shell must have lost exactly what the panel gained, and the vertex
    # accessors must be the same objects — that is the no-geometry-touched proof
    shell_after = 0
    for node_i, nm, mesh_i, M in g2.leaves():
        if not nm.startswith(SHELL):
            continue
        for prim in g2.j["meshes"][mesh_i].get("primitives", []):
            if prim.get("indices") is not None:
                shell_after += g2.j["accessors"][prim["indices"]]["count"] // 3
    assert shell_after == total_faces - sel, (
        f"shell has {shell_after} faces, expected {total_faces - sel}")
    for p, h in zip(pmesh["primitives"], hits):
        orig = g.j["meshes"][h["mesh"]]["primitives"][h["prim"]]["attributes"]
        assert p["attributes"] == orig, "panel does not share the vertex accessors"
    print(f"verified in {a.out}: {spec['label']} carries {got:,} faces, "
          f"shell {total_faces:,} -> {shell_after:,}, vertex accessors shared")
    print(f"  hinge for the app: y={hinge['y']} z={hinge['z']} axis=X "
          f"open={spec['open_deg']} deg")


if __name__ == "__main__":
    main()
