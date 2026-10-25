#!/usr/bin/env python3
"""rig.py — the rig step in pure Python: one car in, its parts named and
framed for finish.py. No Blender.

    node tools/decode.mjs SRC.glb PLAIN.glb       # Draco/meshopt -> plain (once)
    python3 pipeline/realcar/rig.py PLAIN.glb OUT_DIR

A port of the Strip Bay rigger (platform/trainer/blender_addon/
strip_bay_rigger/core.py 1.1.0), rule for rule, in numpy. Every rule there was
written against a car that broke the one before it, and the comments name
the cars; they are kept here where the rule is.

OUTPUT: OUT_DIR/src.glb with nodes SB_<part>__<n> in the rig frame (+Y up,
nose +Z, the car's left +X, ground Y = 0), OUT_DIR/src.report.json (every
decision) and OUT_DIR/result.json ({status, opens, missing, refused}),
the same files the Blender rig machine wrote, so finish.py and batch.py read
either.

CHECKED AGAINST BLENDER on the 21 UK top-seller catalogue cars: the same
parts open on 20, hinges within 5 mm. Blender's own quirks are kept where
its rules were tuned on them (it poses an animated file at frame 1; it welds
in each mesh's own units; its up/along tests carry the object's scale). One
is not: it ranked door pieces by area in each mesh's own units, so meshes at
different scales compared wrongly (the catalogue's mislabelled "Honda Jazz"
got two 8-vertex boxes as doors; here it gets its door skins).

A part is made of SEGMENTS: (primitive, triangle indices). Lifting faces off
a mesh is moving triangle indices from one segment list to another; nothing
is cut until the file is written.
"""
import json
import math
import os
import re
import sys
import time

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "template"))
from gltf import GLTF, row_ids  # noqa: E402

VERSION = "2.4.0-py"


class Refused(Exception):
    """The car cannot be rigged safely. The message says why."""


# ── what each mesh is, from its name chain (nearest name wins) ──────────
RULES = [
    ("steering", r"steer"),
    # not a digit before it: `Opel_Corsa_5door_2` is the ROOT node of a file
    # whose 76 meshes are all called `Object_N`
    ("door", r"(^|[^a-z0-9])door(?!_?(mirror|handle_int|light_int|seal_body|frame_body|jamb|sill|step|trim_body|opening))|doorf|doorr|door_?[lr][fr]"),
    # no word boundary before hood: variants are GLUED (`carbonhood`) (BMW M6)
    ("bonnet", r"(hood|bonnet)(?!_?(piston|strut|latch|ornament|release|prop|scoop_body|vent_body|ie))"),
    # not a LAMP on the lid: the 2026 308's `Trunk_Light`
    ("tailgate", r"(^|[^a-z])(trunk|tailgate|hatch|bootlid|boot)(?!_?(divider|floor|panel|carpet|cam|liner|light|lamp|lens|piston|strut|latch))"),
    # BEFORE wheel: a caliper stays bolted to the hub (the RS6's rear calipers)
    ("brakes", r"call?iper|brake_?disc|(^|[^a-z])rotor([^a-z]|$)"),
    ("wheel", r"(^|[^a-z])(wheel|tyre|tire|rim)(?!_?(arch|house|well|cover|liner|trim_body|lip_body))"
              r"|(^|[^a-z])(w[fr][lr]|whl)([^a-z]|$)"),
    # lamps BEFORE glazing, or `headlight_glass` becomes a window
    ("lamps_front", r"headl|foglight|extralight|(^|[^a-z])drl"),
    ("lamps_rear", r"taill|brakel|reversingl|rearlight"),
    ("glazing", r"windscreen|windshield|glass|window|vitre|(^|[^a-z])glaz"),
    # NOT `chassis`: a GTA-style car's `chassis` is its whole BODY SHELL
    ("cabin", r"interior|seat|dash|carpet|console|headlin|pedal|gauge|speedo"),
    ("engine", r"engine|engbay|intake|turbo|intercooler|radiator|airbox"),
]
RULES = [(k, re.compile(p, re.I)) for k, p in RULES]
DOOR_RX = dict(RULES)["door"]
SPARE = re.compile(r"spare_?(tire|tyre|wheel)|sparetire|reserverad|ersatzrad|stepney", re.I)
SHIFTER_BOOT = re.compile(r"shifter_?boot|gear_?boot|gaiter", re.I)
DROP = re.compile(r"(_dam\b|_dam[_.\d]|_vlo\b|_vlo[_.]|\blod[1-9]\b|_lod[1-9]|shadow|_l[12]_end|collision|\bcol_)", re.I)
# default primitives left in the export: the A6 carries an `Icosphere` below its tyres
PRIM = re.compile(r"^(icosphere|uv ?sphere|sphere|cube|plane|cylinder|cone|torus)(\.\d+)?$", re.I)
SLIDE_NAME = re.compile(r"slid", re.I)
FRONT_RX = re.compile(r"(^|[^a-z])front([^a-z]|$)", re.I)
REAR_RX = re.compile(r"(^|[^a-z])(rear|back)([^a-z]|$)", re.I)
# Turkish too (the 2018 G-Class): jant rim, lastik tyre (not plastik), teker wheel, frendisk brake disc
WHEEL_MAT = re.compile(r"tyre|tire|rubber|pneu|reifen|llanta|luntai|lungu|wheel|felge|rueda"
                       r"|(^|[^a-z])rim([^a-z]|$)|(^|_)rin(_|\d|$)|jant|teker|(^|[^p])lastik|frendis[ck]", re.I)
RED_NAME = re.compile(r"(?<![a-z])red|red(?![a-z])|tail|lanterna|brake.?light|stop.?light|rear.?light|rueckl|feu.?arr", re.I)
TWO_DOOR = re.compile(r"coupe|coupé|convertible|cabrio|roadster|spider|spyder|targa"
                      r"|\b[23][- ]?(?:door|dr)\b|\b(?:two|three)[- ]door", re.I)
GLASS_MAT = re.compile(r"glass|window|vitre|windscreen|windshield|lamp|light|lens|tyre|tire|rubber|chrome_?badge", re.I)
ANG = float(os.environ.get("SB_CUT_ANG", 40))


def pose_first_frame(g, t=1 / 24):
    """Blender's import leaves an animated file at scene FRAME 1 of its first
    animation (t = 1/24 s), not the rest pose: the 2023 BMW 3 Series' door
    animation has them 10 cm off by then. Do the same, so every measurement
    starts where Blender's proven rigger started (checked to 1e-5 on it)."""
    anims = g.j.get("animations") or []
    if not anims:
        return 0
    a, n = anims[0], 0
    for ch in a.get("channels", []):
        tg = ch.get("target", {})
        path, ni = tg.get("path"), tg.get("node")
        if ni is None or path not in ("translation", "rotation", "scale") or "matrix" in g.j["nodes"][ni]:
            continue
        smp = a["samplers"][ch["sampler"]]
        times = g.accessor(smp["input"]).ravel().astype(np.float64)
        vals = g.accessor(smp["output"]).astype(np.float64).reshape(-1, 4 if path == "rotation" else 3)
        how = smp.get("interpolation", "LINEAR")
        if how == "CUBICSPLINE":                    # in-tangent, value, out-tangent
            vals = vals[1::3]
        if how == "STEP":
            v = vals[max(0, int(np.searchsorted(times, t, side="right")) - 1)]
        else:
            v = np.array([np.interp(t, times, vals[:, c]) for c in range(vals.shape[1])])
        if path == "rotation":
            v = v / max(np.linalg.norm(v), 1e-12)
        g.j["nodes"][ni][path] = [float(x) for x in v]
        n += 1
    return n


# ═════════════════════════════════════════════════════════════════════════
class Car:
    """Every primitive of the file in world space, and the objects (one per
    mesh node, as Blender's import makes them) as segment lists."""

    def __init__(self, path):
        self.g = g = GLTF(path)
        j = g.j
        self.posed = pose_first_frame(g)
        W, parent = g.world_matrices()
        self.mats = j.get("materials", [])
        self.prims = []             # {P, I, mat, Nm, node, prim}
        self.objs = []              # {chain, kind, segs: [(pi, tris)]}
        names = {i: n.get("name", "") for i, n in enumerate(j["nodes"])}

        def chain(i):
            out = []
            while i is not None:
                out.append(names.get(i, ""))
                i = parent.get(i)
            return out
        skins = j.get("skins", [])
        self.baked = 0
        for ni, n in enumerate(j["nodes"]):
            if "mesh" not in n:
                continue
            segs, ch = [], chain(ni)
            for p in j["meshes"][n["mesh"]]["primitives"]:
                if p.get("mode", 4) != 4:
                    continue
                P = g.accessor(p["attributes"]["POSITION"]).astype(np.float64)
                if "skin" in n and "JOINTS_0" in p["attributes"]:
                    # BAKE a rigid skin (game rigs): each mesh follows ONE bone at
                    # weight 1.0, so the skin carries no deformation
                    sk = skins[n["skin"]]
                    jn = g.accessor(p["attributes"]["JOINTS_0"]).astype(int)
                    wt = g.accessor(p["attributes"]["WEIGHTS_0"])
                    used = set(jn[wt > 0].ravel().tolist())
                    if len(used) > 1:
                        raise Refused(f"{n.get('name')} is skinned to {len(used)} bones — a deforming rig, not a parts rig")
                    ji = used.pop() if used else 0
                    ibm = g.accessor(sk["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)[ji] \
                        if "inverseBindMatrices" in sk else np.eye(4)
                    M = W[sk["joints"][ji]] @ ibm
                    ch = [names.get(sk["joints"][ji], "")] + ch
                    self.baked += 1
                else:
                    M = W[ni]
                P = P @ M[:3, :3].T + M[:3, 3]
                I = g.accessor(p["indices"]).ravel().astype(np.int64) if "indices" in p else np.arange(len(P))
                I = I[:len(I) // 3 * 3].reshape(-1, 3)
                if not len(I):
                    continue
                Rm = M[:3, :3]
                self.prims.append({"P": P, "I": I, "mat": p.get("material"), "prim": p,
                                   "Nm": np.linalg.inv(Rm).T, "Tm": Rm.copy(), "flip": np.linalg.det(Rm) < 0,
                                   "unit": abs(np.linalg.det(Rm)) ** (1 / 3)})
                segs.append((len(self.prims) - 1, np.arange(len(I))))
            if segs:
                self.objs.append({"chain": "|".join(ch), "name": n.get("name", ""), "kind": None, "segs": segs})

    # ── geometry of one object ──
    def tris(self, o):
        """(T (n,3,3), material per triangle, (seg index, triangle) refs)."""
        Ts, ms, refs = [], [], []
        for si, (pi, t) in enumerate(o["segs"]):
            pr = self.prims[pi]
            Ts.append(pr["P"][pr["I"][t]])
            ms.append(np.full(len(t), -1 if pr["mat"] is None else pr["mat"]))
            refs.append(np.c_[np.full(len(t), si), t])
        if not Ts:
            return np.zeros((0, 3, 3)), np.zeros(0, int), np.zeros((0, 2), int)
        return np.vstack(Ts), np.concatenate(ms), np.vstack(refs)

    def verts(self, o):
        out = []
        for pi, t in o["segs"]:
            pr = self.prims[pi]
            out.append(pr["P"][np.unique(pr["I"][t].ravel())])
        return np.vstack(out) if out else np.zeros((0, 3))

    def nfaces(self, o):
        return sum(len(t) for _, t in o["segs"])

    def transform(self, M):
        """Apply a 4x4 to the whole car (every primitive)."""
        for pr in self.prims:
            pr["P"] = pr["P"] @ M[:3, :3].T + M[:3, 3]
            R = M[:3, :3]
            pr["Nm"] = np.linalg.inv(R).T @ pr["Nm"]
            pr["Tm"] = R @ pr["Tm"]
            if np.linalg.det(R) < 0:
                pr["flip"] = not pr["flip"]
            pr["unit"] *= abs(np.linalg.det(R)) ** (1 / 3)

    def unit(self, o):
        """World length of one of the object's own file units (Blender welds
        and measures in these)."""
        return self.prims[o["segs"][0][0]]["unit"] if o["segs"] else 1.0

    def mname(self, mi):
        return self.mats[mi].get("name", "") if 0 <= mi < len(self.mats) else ""

    def lift(self, o, groups):
        """Split triangle groups (lists of (seg index, tri) refs) off `o` into
        new objects, one per group. `o` keeps the rest."""
        out = []
        take = {}
        for gi, refs in enumerate(groups):
            new = {"chain": o["chain"], "name": o["name"], "kind": o["kind"], "segs": []}
            refs = np.asarray(refs).reshape(-1, 2)
            for si in np.unique(refs[:, 0]):
                pi, t = o["segs"][si]
                sel = np.unique(refs[refs[:, 0] == si, 1])
                new["segs"].append((pi, sel))
                take.setdefault(si, []).append(sel)
            out.append(new)
        segs = []
        for si, (pi, t) in enumerate(o["segs"]):
            if si in take:
                t = np.setdiff1d(t, np.concatenate(take[si]))
            if len(t):
                segs.append((pi, t))
        o["segs"] = segs
        return out


def bbox(V):
    return V.min(0), V.max(0)


def centre(car, objs):
    V = np.vstack([car.verts(o) for o in objs])
    return V.mean(0)


def tri_area_normal(T):
    c = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    a = np.linalg.norm(c, axis=1)
    return a / 2, c / np.maximum(a, 1e-12)[:, None]


def rot_y(deg):
    a = math.radians(deg)
    M = np.eye(4)
    M[0, 0], M[0, 2], M[2, 0], M[2, 2] = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
    return M


def drop(lst, o):
    """list.remove by identity: objects hold numpy arrays, so == is no test."""
    del lst[next(i for i, x in enumerate(lst) if x is o)]


def per_material(ms, test):
    """TEST of each triangle's material (MS: material index per triangle),
    asked once per material, not once per triangle."""
    if not len(ms):
        return np.zeros(0, bool)
    u, inv = np.unique(ms, return_inverse=True)
    return np.array([bool(test(int(m))) for m in u])[inv.reshape(-1)]


def weld_ids(T, scale):
    return row_ids(np.round(T.reshape(-1, 3) / max(scale, 1e-9)).astype(np.int64)).reshape(-1, 3)


def components(vid, mask=None):
    """Connected face groups through shared (welded) vertices."""
    nt = len(vid)
    idx = np.arange(nt) if mask is None else np.where(mask)[0]
    if not len(idx):
        return np.zeros(nt, int) - 1
    rows = np.repeat(np.arange(len(idx)), 3)
    _, cv = np.unique(vid[idx].ravel(), return_inverse=True)
    n = len(idx) + cv.max() + 1
    A = coo_matrix((np.ones(len(rows)), (rows, cv + len(idx))), shape=(n, n))
    _, lab = connected_components(A, directed=False)
    out = np.full(nt, -1)
    out[idx] = lab[:len(idx)]
    return out


def edge_components(vid):
    """Connected face groups through shared EDGES, as Blender's bmesh walk
    (e.link_faces) finds them: faces touching at one corner stay apart."""
    nt = len(vid)
    if not nt:
        return np.zeros(0, int)
    e = np.sort(np.vstack([vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 0]]]), 1)
    f = np.tile(np.arange(nt), 3)
    _, ek = np.unique(e[:, 0] * (vid.max() + 1) + e[:, 1], return_inverse=True)
    n = nt + ek.max() + 1
    A = coo_matrix((np.ones(len(f)), (f, ek + nt)), shape=(n, n))
    _, lab = connected_components(A, directed=False)
    _, lab = np.unique(lab[:nt], return_inverse=True)
    return lab


def edges_of(vid, nrm):
    """Welded edges: (a, b, faces...) with each edge's face count and, for
    two-face edges, the angle between the faces (degrees)."""
    e = np.vstack([vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 0]]])
    f = np.tile(np.arange(len(vid)), 3)
    e.sort(1)
    key = e[:, 0] * (vid.max() + 1) + e[:, 1]
    order = np.argsort(key, kind="stable")
    key, e, f = key[order], e[order], f[order]
    uk, start, cnt = np.unique(key, return_index=True, return_counts=True)
    two = cnt == 2
    fa = f[start[two]]
    fb = f[start[two] + 1]
    cosang = np.clip((nrm[fa] * nrm[fb]).sum(1), -1, 1)
    ang = np.degrees(np.arccos(cosang))
    return {"edge": e[start], "count": cnt, "fa": fa, "fb": fb, "ang": ang, "two": two,
            "face_of_single": f[start[cnt == 1]], "single": e[start[cnt == 1]]}


# ═════════════════════════════════════════════════════════════════════════
def kind_of(chain):
    for n in chain.split("|"):
        if SHIFTER_BOOT.search(n):
            return "cabin"
        for k, rx in RULES:
            if rx.search(n):
                return k
    return "body"


def own_name(car, objs, o):
    """The chain to read a part from. An exporter names each material's mesh
    `<object>_<material>_0`: a material several objects wear (`door_plastic`
    on the 2026 G-Class's gear lever, engine and cabin; `door_handles` on its
    tailgate) says nothing of which part this is, and is left out. The name
    keeps the material as the artist called it, which the file may since
    have renamed, so the names are compared, not the materials."""
    ch = o["chain"].split("|")

    def mat_part(c):
        if len(c) < 2 or not c[0].startswith(c[1] + "_"):
            return None
        return re.sub(r"_\d+(\.\d+)?$", "", c[0][len(c[1]) + 1:]).lower()
    if not hasattr(car, "_mat_users"):
        car._mat_users = {}
        for q in objs:
            c = q["chain"].split("|")
            if mat_part(c):
                car._mat_users.setdefault(mat_part(c), set()).add(c[1])
    m = mat_part(ch)
    if m and len(car._mat_users.get(m, ())) > 1:
        return "|".join(ch[1:])
    return o["chain"]


def islands(car, o, length):
    """Loose pieces of one object: bbox, mean up, refs, mean forward, area,
    share facing up, share facing along the car."""
    T, ms, refs = car.tris(o)
    if not len(T):
        return []
    vid = weld_ids(T, 1e-5 * car.unit(o))          # Blender: remove_doubles(dist=1e-5), mesh units
    lab = edge_components(vid)
    a, n = tri_area_normal(T)
    out = []
    order = np.argsort(lab, kind="stable")
    bounds = np.searchsorted(lab[order], np.arange(lab.max() + 2))
    for k in range(lab.max() + 1):
        ix = order[bounds[k]:bounds[k + 1]]
        if not len(ix):
            continue
        V = T[ix].reshape(-1, 3)
        A = a[ix].sum()
        up = float((n[ix, 1] * a[ix]).sum() / max(A, 1e-12))
        fwd = float((n[ix, 2] * a[ix]).sum() / max(A, 1e-12))
        upf = float(a[ix][np.abs(n[ix, 1]) > .55].sum() / max(A, 1e-12))
        endf = float(a[ix][np.abs(n[ix, 2]) > .55].sum() / max(A, 1e-12))
        out.append({"lo": V.min(0), "hi": V.max(0), "up": up, "refs": refs[ix], "fwd": fwd, "area": float(A),
                    "upf": upf, "endf": endf, "ix": ix})
    return out


# ═════════════════════════════════════════════════════════════════════════
def convert(car, rep, override=None, body_style=""):
    objs = car.objs
    rep["baked"] = car.baked
    # ── 1. DROP what must not render ──
    keep = []
    dropped = 0
    for o in objs:
        ch = o["chain"].split("|")[:3]
        if any(DROP.search(n) for n in ch) or PRIM.match(o["name"]):
            dropped += 1
            continue
        keep.append(o)
    rep["dropped"] = dropped
    objs = [o for o in keep if car.nfaces(o)]
    if not objs:
        raise Refused("no geometry")
    for o in objs:
        o["kind"] = kind_of(own_name(car, objs, o))

    def allv():
        return np.vstack([car.verts(o) for o in objs])

    # ── 2. FRAME: length along Z, nose +Z, up +Y, left +X, ground 0 ──
    lo, hi = bbox(allv())
    if (hi[0] - lo[0]) > (hi[2] - lo[2]):          # length lies on X: turn 90
        car.transform(rot_y(90))
        rep["turn90"] = True
    wheels = [o for o in objs if o["kind"] == "wheel"]
    if not wheels:
        # most "no wheels named" cars name the pieces after their MATERIAL
        material_wheels(car, objs, rep)
        wheels = [o for o in objs if o["kind"] == "wheel"]
    if not wheels:
        # names and materials found nothing (the 2011 Corsa): read the SHAPE
        geometry_wheels(car, objs, rep)
        wheels = [o for o in objs if o["kind"] == "wheel"]
    glass = [o for o in objs if o["kind"] == "glazing"]
    if not wheels:
        raise Refused("no wheels named")
    if glass and centre(car, wheels)[1] > centre(car, glass)[1]:
        raise Refused("wheels sit ABOVE the glass — upside down")
    cues = {}
    bon = [o for o in objs if o["kind"] == "bonnet"]
    tg = [o for o in objs if o["kind"] == "tailgate"]
    st = [o for o in objs if o["kind"] == "steering"]
    lo, hi = bbox(allv())
    mid = (lo + hi) / 2
    if bon and tg:
        cues["bonnet_vs_boot"] = 1 if centre(car, bon)[2] > centre(car, tg)[2] else -1
    if st:
        cues["steering"] = 1 if centre(car, st)[2] > mid[2] else -1
    hl = [o for o in objs if o["kind"] == "lamps_front"]
    tl = [o for o in objs if o["kind"] == "lamps_rear"]
    if hl and tl:
        cues["head_vs_tail_lamps"] = 1 if centre(car, hl)[2] > centre(car, tl)[2] else -1
    wf = [o for o in wheels if FRONT_RX.search(o["chain"]) and not REAR_RX.search(o["chain"])]
    wr = [o for o in wheels if REAR_RX.search(o["chain"]) and not FRONT_RX.search(o["chain"])]
    if wf and wr:
        cues["wheel_names"] = 1 if centre(car, wf)[2] > centre(car, wr)[2] else -1
    if not cues:
        rl = red_lamp_end(car, objs, lo, hi)
        if rl:
            cues["red_tail_lamps"] = -rl              # the red end is the BACK
            rep["red_tail_lamps"] = rl
    if not cues:
        ta = top_over_axles(car, objs, wheels)
        if ta:
            cues["top_over_axles"] = ta["nose"]
            rep["top_over_axles"] = ta
    if not cues:
        raise Refused("cannot decide the nose: no bonnet/boot pair, no lamps, no front/rear wheel names "
                      "and no steering wheel")
    # PRIORITY, not a vote: the steering wheel is the weakest cue (GR Supra)
    ends = [cues[k] for k in ("bonnet_vs_boot", "head_vs_tail_lamps", "wheel_names", "red_tail_lamps",
                              "top_over_axles") if k in cues]
    if len(set(ends)) > 1:
        raise Refused(f"the two end cues disagree: {cues}")
    nose = ends[0] if ends else cues["steering"]
    if len(set(cues.values())) > 1:
        rep["nose_overruled"] = cues
    if nose < 0:
        car.transform(rot_y(180))
    # SCALE: a car outside 2.5-7.5 long is set so its wheels are 0.68 m tall
    lo, hi = bbox(allv())
    if not 2.5 <= hi[2] - lo[2] <= 7.5:
        WV = np.vstack([car.verts(o) for o in wheels])
        wh = WV[:, 1].max() - WV[:, 1].min()
        if wh <= 0:
            raise Refused("cannot size the car: the wheels have no height")
        f = 0.68 / wh
        S = np.eye(4)
        S[:3, :3] *= f
        car.transform(S)
        rep["rescaled"] = {"factor": round(f, 4), "length_before": round(float(hi[2] - lo[2]), 4),
                           "why": "not metre scale; wheels set to 0.68 m tall (typical, not measured)"}
    WV = np.vstack([car.verts(o) for o in wheels])
    ground = WV[:, 1].min()
    # CENTRE ACROSS when off-centre by more than 2% of the width (Model Y,
    # Corolla): on the wheels, unless their middle is not the body's (wheels
    # read from one side, or something else among them: the Passat scan was
    # moved 0.8 m sideways so), then on the body itself
    dx = -(WV[:, 0].min() + WV[:, 0].max()) / 2
    lo0, hi0 = bbox(allv())
    dxb = -(lo0[0] + hi0[0]) / 2
    if abs(dx - dxb) > .05 * (hi0[0] - lo0[0]):
        rep["centred_on_body"] = {"wheels_said": round(float(dx), 4), "body_says": round(float(dxb), 4)}
        dx = dxb
    if abs(dx) <= .02 * (hi0[0] - lo0[0]):
        dx = 0.0
    else:
        rep["centred_across"] = round(float(dx), 4)
    Tm = np.eye(4)
    Tm[:3, 3] = [dx, -ground, 0]
    car.transform(Tm)
    lo, hi = bbox(allv())
    mid = (lo + hi) / 2
    rep["frame"] = {"nose_cues": cues, "yaw180": bool(nose < 0), "ground_shift": round(float(-ground), 4),
                    "extent": [round(float(hi[i] - lo[i]), 3) for i in range(3)]}
    if st:
        rep["frame"]["drive"] = "LHD" if centre(car, st)[0] > 0 else "RHD"

    # ── 2b. MIRRORED PAIRS saved as ONE mesh (the 2022 Tiguan) ──
    split = split_pairs(car, objs, hi[0] - lo[0])
    if split:
        rep["split_pairs"] = split
        wheels = [o for o in objs if o["kind"] == "wheel"]

    # ── 3. CORNERS by position ──
    parts = {}

    def put(pid, o):
        parts.setdefault(pid, []).append(o)

    if not any(o["kind"] == "door" for o in objs):
        for o in find_doors(car, objs, wheels, lo, hi, rep, body_style):
            objs.append(o)
            o["kind"] = "door"
    doorkey = {}
    for o in objs:
        if o["kind"] != "door":
            continue
        ch = own_name(car, objs, o).split("|")     # the door, not its material: `G-class_FL_door_AMG`
        root = next((n for n in ch if DOOR_RX.search(n)), ch[0])
        root = re.sub(r"(_ok|_dummy|__\d+|\.\d+|_\d+)$", "", root, flags=re.I)
        doorkey.setdefault(root, []).append(o)

    def size(t):                                   # Blender: len(o.data.vertices)
        return sum(len(car.verts(o)) for o in t[1])
    DOOR = {}
    L, Wd = hi[2] - lo[2], hi[0] - lo[0]
    for root in list(doorkey):                     # one name, both flanks: two doors (Tiguan)
        os_ = doorkey[root]
        if centre(car, os_)[2] < lo[2] + .15 * L:
            continue
        xs = [centre(car, [o])[0] for o in os_]
        if max(xs) > .15 * Wd and min(xs) < -.15 * Wd:
            del doorkey[root]
            for o, x in zip(os_, xs):
                doorkey.setdefault((root, "l" if x > 0 else "r"), []).append(o)
    for os_ in doorkey.values():
        c = centre(car, os_)
        b0, b1 = bbox(np.vstack([car.verts(o) for o in os_]))
        # a door across the BACK runs sideways (the Vito's barn doors)
        if c[2] < lo[2] + .15 * L and (b1[2] - b0[2]) < .5 * (b1[0] - b0[0]):
            if abs(c[0]) < .15 * Wd:
                for o in os_:
                    put("tailgate", o)
            else:
                for o in os_:
                    put("door_b" + ("l" if c[0] > 0 else "r"), o)
            continue
        DOOR.setdefault("l" if c[0] > 0 else "r", []).append((c[2], os_))
    # ONE named piece two doors long on a side of a five-door body (the 2017
    # Golf's `Doors`, both doors of each flank in one mesh): split at its
    # shut line, as a loose door piece is (find_doors). A two-door body asked
    # for changes nothing here: no door is 42% of the car, so a piece that
    # long is two, and the rear one is kept shut later ("Golf 2017 2 door")
    for side, lst in DOOR.items():
        if len(lst) != 1:
            continue
        os_ = lst[0][1]
        b0, b1 = bbox(np.vstack([car.verts(o) for o in os_]))
        if b1[2] - b0[2] <= .42 * L:
            continue
        big = max(os_, key=car.nfaces)
        cut, prof = shut_line(car, big, car.tris(big)[2], b0[2], b1[2], L)
        rep.setdefault("named_door_split", {})[side] = dict(prof, cut_z=None if cut is None else round(float(cut), 4))
        if cut is None:
            continue
        front, rear = [], []
        for o in os_:
            T, _, refs = car.tris(o)
            cz = T.mean(1)[:, 2]
            fr, rr = refs[cz > cut], refs[cz <= cut]
            if not len(fr) or not len(rr):
                (front if len(fr) else rear).append(o)
                continue
            f_new, r_new = car.lift(o, [fr, rr])
            objs.extend([f_new, r_new])
            front.append(f_new)
            rear.append(r_new)
        objs[:] = [o for o in objs if car.nfaces(o)]
        DOOR[side] = [(centre(car, g)[2], g) for g in (front, rear) if g]
    for side, lst in DOOR.items():
        lst.sort(key=lambda t: -t[0])
        biggest = max(size(t) for t in lst)
        # anchors are the two LARGEST clusters (BMW M6)
        bysize = sorted(lst, key=size, reverse=True)
        anchors = [bysize[0][0]]
        for t in bysize[1:]:
            if size(t) > 0.35 * biggest and abs(t[0] - anchors[0]) > 0.35:
                anchors.append(t[0])
                break
        anchors.sort(reverse=True)
        for z, os_ in lst:
            k = min(range(len(anchors)), key=lambda i: abs(anchors[i] - z))
            for o in os_:
                put(f"door_{'fr'[k]}{side}", o)
    nd = sum(1 for k in parts if k.startswith("door_") and k[5] in "fr")
    if nd < 2:
        for pid, os_ in cut_doors(car, objs, wheels, lo, hi, rep, body_style).items():
            for o in os_:
                objs.append(o)
                o["kind"] = "door"
                put(pid, o)
        nd = sum(1 for k in parts if k.startswith("door_") and k[5] in "fr")
    if nd < 2:
        raise Refused(f"only {nd} door part(s) found — the doors are not separate objects in this file")

    # A WHEEL MUST BE WHEEL-SHAPED (the Rolls-Royce Ghost)
    def shape_ok(o):
        b0, b1 = bbox(car.verts(o))
        h, l, w = b1[1] - b0[1], b1[2] - b0[2], b1[0] - b0[0]
        return .35 < h < 1.0 and .75 < l / max(h, 1e-6) < 1.3 and w < .65 * h
    prim = [o for o in wheels if shape_ok(o)]
    boxes = [bbox(car.verts(o)) for o in prim]
    rest = []
    for o in wheels:
        if any(o is p for p in prim):
            continue
        b0, b1 = bbox(car.verts(o))
        c = (b0 + b1) / 2
        inside = any(all(pb0[i] - .03 <= c[i] <= pb1[i] + .03 for i in range(3))
                     and np.linalg.norm(b1 - b0) < np.linalg.norm(pb1 - pb0) for pb0, pb1 in boxes)
        (prim if inside else rest).append(o)
    for o in prim:
        c = centre(car, [o])
        put("wheel_" + ("f" if c[2] > mid[2] else "r") + ("l" if c[0] > 0 else "r"), o)
    hubs = {}
    for k in [k for k in parts if k.startswith("wheel_")]:
        b0, b1 = bbox(np.vstack([car.verts(o) for o in parts[k]]))
        hubs[k] = ((b0 + b1) / 2, (b1[1] - b0[1]) / 2)
    joined = 0
    for o in list(rest):                           # a caliper or rim lip near a wheel is that wheel's (RS6)
        c = centre(car, [o])
        best = None
        for k, (hc, R) in hubs.items():
            d = ((c[1] - hc[1]) ** 2 + (c[2] - hc[2]) ** 2) ** .5
            if d < 1.15 * R and abs(c[0] - hc[0]) < R and (best is None or d < best[1]):
                best = (k, d)
        if best:
            put(best[0], o)
            drop(rest, o)
            joined += 1
    rep["wheel_pieces_joined"] = joined
    rep["wheel_rejects"] = [o["chain"][:50] for o in rest][:8]
    for o in rest:
        o["kind"] = "body"
    got = sorted(k for k in parts if k.startswith("wheel_"))
    if got != ["wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr"]:
        rep["wheel_shapes"] = []
        for o in wheels:
            b0, b1 = bbox(car.verts(o))
            rep["wheel_shapes"].append({"part": o["chain"][:40], "h": round(float(b1[1] - b0[1]), 3),
                                        "l": round(float(b1[2] - b0[2]), 3), "w": round(float(b1[0] - b0[0]), 3)})
        raise Refused(f"wheels do not fill four corners ({got}) — often ONE wheel the game copies at run time")
    placed = {id(o) for v in parts.values() for o in v}
    for o in objs:
        if o["kind"] in ("door", "wheel") or id(o) in placed:
            continue
        put({"bonnet": "panel_bonnet"}.get(o["kind"], o["kind"]), o)

    # glass and handles INSIDE a door's box travel with the door
    for pid in [k for k in parts if k.startswith("door_")]:
        b0, b1 = bbox(np.vstack([car.verts(o) for o in parts[pid]]))
        for other in ("glazing", "body"):
            keepl = []
            for o in parts.get(other, []):
                ov = car.verts(o)
                if not len(ov):
                    keepl.append(o)
                    continue
                ob0, ob1 = bbox(ov)
                inside = all(b0[i] - .02 <= ob0[i] and ob1[i] <= b1[i] + .02 for i in range(3))
                (parts[pid] if inside else keepl).append(o)
            if other in parts:
                parts[other] = keepl

    if rep.get("door_finder", {}).get("doors") or rep.get("door_cutter", {}).get("faces"):
        adopt_into_doors(car, parts, rep, L)

    # ── 4. TYRES READ AS BLACK RUBBER ──
    rep["tyre_faces_to_rubber"] = rubber_tyres(car, parts)
    # ── 5. PAINT ──
    paint = find_paint(car, parts, rep)
    # ── 6. BONNET / BOOT from the paint mesh if no part carries them ──
    lift_panels(car, parts, paint, lo, hi, rep)
    rep["missing"] = [p for p in wanted(parts) if not parts.get(p)]
    # ── 7. HINGES, and which doors SLIDE ──
    island = bool(rep.get("door_finder", {}).get("doors") or rep.get("door_cutter", {}).get("faces"))
    hinge = hinges(car, parts, island)
    dropped = implausible(car, parts, hinge)
    if dropped:
        rep["implausible"] = dropped
        # what was taken for the doors was not (the Polo's "doors" were its wings)
        if not any(k in parts for k in ("door_fl", "door_fr", "door_rl", "door_rr")) \
                and any(d.startswith("door_") and "kept" not in d for d in dropped) and "door_cutter" not in rep:
            two_asked = bool(TWO_DOOR.search(body_style or os.environ.get("SB_BODY", "")))
            for bs in ([body_style, ""] if two_asked else [body_style]):
                pool = parts.get("body", []) + parts.get("glazing", [])
                for o in pool:
                    o["kind"] = "glazing" if any(o is x for x in parts.get("glazing", [])) else "body"
                cut = cut_doors(car, pool, [o for k in parts if k.startswith("wheel_") for o in parts[k]], lo, hi, rep,
                                bs)
                for pid, os_ in cut.items():
                    parts[pid] = os_
                if not cut:
                    break
                adopt_into_doors(car, parts, rep, L)
                for pid, h in hinges(car, parts, True).items():
                    if pid in cut:
                        hinge[pid] = h
                again = implausible(car, parts, {k: v for k, v in hinge.items() if k in cut})
                for d in again:
                    if "kept" not in d:
                        hinge.pop(d.split(":")[0], None)
                rep["implausible"] += again
                if not any(d.startswith("door_") and "kept" not in d for d in again):
                    break
                # a two-door cut longer than any door: the model is a five-door;
                # cut four, and the rear pair is kept shut below
                rep["two_door_cut_as_four"] = again
        rep["missing"] = [p for p in wanted(parts) if not parts.get(p)]
        if not any(k in parts for k in ("door_fl", "door_fr", "door_rl", "door_rr", "door_bl", "door_br")):
            # the pieces taken for doors were not doors, and none were found
            # instead: a car whose doors do not open is not one to build (the A5)
            raise Refused("the door pieces found were not doors (" + "; ".join(dropped)[:160] + ")")
    # a two-door body has front doors only: a lone "rear" door left on a side
    # once the wing taken for its front door is dropped is that side's door
    # (the BMW 1 Series coupe)
    if TWO_DOOR.search(body_style or os.environ.get("SB_BODY", "")):
        for sd in "lr":
            if f"door_r{sd}" in parts and f"door_f{sd}" not in parts:
                parts[f"door_f{sd}"] = parts.pop(f"door_r{sd}")
                if f"door_r{sd}" in hinge:
                    hinge[f"door_f{sd}"] = hinge.pop(f"door_r{sd}")
                rep.setdefault("two_door", []).append(f"door_r{sd} is the front door")
            elif f"door_r{sd}" in parts:
                # a two-door body asked for ("Transit 2 door") from a model
                # with rear side doors: they stay shut, part of the body,
                # closed up so they do not read as doors (no handle, no seam)
                shut = parts.pop(f"door_r{sd}")
                closed = close_up(car, shut, [o for o in parts.get("body", []) if o["kind"] != "wheel"], L)
                parts.setdefault("body", []).extend(shut)
                hinge.pop(f"door_r{sd}", None)
                rep.setdefault("two_door", []).append(f"door_r{sd} kept shut: the body asked for has no rear side doors")
                rep.setdefault("closed_up", {})[f"door_r{sd}"] = closed
    # a spare wheel on the back door (the G-Class, a Jimny, an old RAV4) rides
    # on it, and a door that carries one is hinged at the side: the side away
    # from its handle
    spare = [o for o in parts.get("body", []) if SPARE.search(own_name(car, objs, o))]
    if spare and parts.get("tailgate") and "tailgate" in hinge:
        b0, b1 = bbox(np.vstack([car.verts(o) for o in parts["tailgate"]]))
        s0, s1 = bbox(np.vstack([car.verts(o) for o in spare]))
        sc = (s0 + s1) / 2
        if sc[2] < b0[2] + .02 and b0[0] - .05 <= sc[0] <= b1[0] + .05 and b0[1] <= sc[1] <= b1[1]:
            parts["body"] = [o for o in parts["body"] if not any(o is x for x in spare)]
            parts["tailgate"] += spare
            handle = [o for o in parts["tailgate"] if re.search(r"handle", o["chain"], re.I)]
            hx = centre(car, handle)[0] if handle else -sc[0]
            rep["hinges"] = {"tailgate": {"edge": "left" if hx < 0 else "right"}}
            rep["spare_on_tailgate"] = {"pieces": len(spare), "hinged": rep["hinges"]["tailgate"]["edge"],
                                        "why": "a spare wheel on the back door: the door is side-hinged"}
    rep["hinge"] = hinge
    rep["motion"] = motion(car, parts, hi[1] - lo[1], rep, override)
    # ── 8. GLASS: what the file claims ──
    gm = {}
    for o in parts.get("glazing", []) + [o for k in parts if k.startswith("door_") for o in parts[k]]:
        for pi, _ in o["segs"]:
            mi = car.prims[pi]["mat"]
            m = car.mats[mi] if mi is not None and mi < len(car.mats) else {}
            if re.search(r"glass|window|vitre|screen", m.get("name", ""), re.I):
                gm[m.get("name")] = m.get("alphaMode", "OPAQUE")
    rep["glass_materials"] = gm
    parts = {k: [o for o in v if car.nfaces(o)] for k, v in parts.items()}
    parts = {k: v for k, v in parts.items() if v}
    rep["parts"] = {k: len(v) for k, v in sorted(parts.items())}
    return parts, hinge


# ═════════════════════════════════════════════════════════════════════════
def light_untextured(m):
    pbr = m.get("pbrMetallicRoughness", {})
    if "baseColorTexture" in pbr:
        return False
    c = pbr.get("baseColorFactor", [1, 1, 1, 1])
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.18


def rubber_tyres(car, parts):
    """Tyres read as black rubber (owner ruling 2026-08-09): a light,
    untextured face reaching the tread band and not coming in to the rim."""
    rub = None
    split = 0
    for k in [k for k in parts if k.startswith("wheel_")]:
        b0, b1 = bbox(np.vstack([car.verts(o) for o in parts[k]]))
        cy, cz, R = (b0[1] + b1[1]) / 2, (b0[2] + b1[2]) / 2, (b1[1] - b0[1]) / 2
        for o in parts[k]:
            new = []
            for pi, t in o["segs"]:
                pr = car.prims[pi]
                mi = pr["mat"]
                if mi is None or mi >= len(car.mats) or not light_untextured(car.mats[mi]):
                    new.append((pi, t))
                    continue
                T = pr["P"][pr["I"][t]]
                rr = np.sqrt((T[:, :, 1] - cy) ** 2 + (T[:, :, 2] - cz) ** 2)
                hit = (rr.max(1) > .85 * R) & (rr.min(1) > .60 * R)
                if not hit.any():
                    new.append((pi, t))
                    continue
                if rub is None:
                    car.mats.append({"name": "SB_tyre_rubber", "pbrMetallicRoughness": {
                        "baseColorFactor": [0.022, 0.022, 0.024, 1], "roughnessFactor": 0.88, "metallicFactor": 0}})
                    rub = len(car.mats) - 1
                car.prims.append(dict(pr, mat=rub))
                new += [(pi, t[~hit]), (len(car.prims) - 1, t[hit])]
                split += int(hit.sum())
            o["segs"] = [(p, t) for p, t in new if len(t)]
    return split


# a modeller's untouched default, named by the tool: Blender's "Material",
# "Material.001" ... are DIFFERENT materials, one a new slot. A default with
# its own number ("Material_1467", Maya's "lambert2") is one material, and
# its ".001" copies are that one again.
DEFAULT_MAT = re.compile(r"^(material|mat|default|defaultmaterial|lambert|phong|blinn|standard|surface|no name|none)?[\s_#-]*$", re.I)


def find_paint(car, parts, rep):
    """The material on the OUTSIDE of the panel: faces facing out (up for a
    bonnet, away from the centreline for a door). Counting all area picked
    the Sharan's black door CARD."""
    def mat_area(os_, outward):
        A = {}
        for o in os_:
            T, ms, _ = car.tris(o)
            if not len(T):
                continue
            a, n = tri_area_normal(T)
            ok = (outward(n) >= 0.5) & (ms >= 0)
            for mi in np.unique(ms[ok]):
                A[mi] = A.get(mi, 0) + float(a[ok & (ms == mi)].sum())
        return A
    if parts.get("panel_bonnet"):
        A = mat_area(parts["panel_bonnet"], lambda n: n[:, 1])
    else:
        A = {}
        for k in [k for k in parts if k.startswith("door_") and k[5] in "fr"]:
            sx = 1 if k[-1] == "l" else -1
            for m, a in mat_area(parts[k], lambda n, sx=sx: n[:, 0] * sx).items():
                A[m] = A.get(m, 0) + a
    if not A:
        return None
    paint = max(A, key=A.get)
    name = car.mname(paint)
    rep["paint"] = {"material": name, "from": "bonnet" if parts.get("panel_bonnet") else "doors",
                    "share": round(A[paint] / sum(A.values()), 3)}
    # SIBLINGS ARE THE SAME PAINT (the Micra's `primary.001` and `primary`),
    # but not a modeller's untouched defaults (`Material.001` … `Material.019`
    # on the 1998 Micra are its tyres, glass and lamps)
    base = re.sub(r"\.\d+$", "", name)
    sib = [m for m in car.mats if re.sub(r"\.\d+$", "", m.get("name", "")) == base]
    if DEFAULT_MAT.match(base):
        sib = [car.mats[paint]]
    for m in sib:
        if "paint" not in m.get("name", "").lower():
            m["name"] = m.get("name", "") + "_paint"
    rep["paint"]["renamed"] = [m.get("name") for m in sib]
    return paint


def material_wheels(car, objs, rep):
    """The four wheels from MATERIAL names and position (`Object_21` carrying
    `Rubber_Rough`): tyre/rim faces in the lower 45% of the car, away from the
    centreline, on the wheel's circle, one object per corner."""
    V = np.vstack([car.verts(o) for o in objs])
    lo, hi = bbox(V)
    H, Wd = hi[1] - lo[1], hi[0] - lo[0]
    xm, zm = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    skip = ("wheel", "glazing", "lamps_front", "lamps_rear", "cabin", "steering")
    # an exporter splits one object per material, `Object003.004_frendisk_0`:
    # the rims and calipers of a wheel object whose tyres are named come too
    stems = set()
    for o in objs:
        if o["kind"] not in skip:
            for m in {int(m) for m in car.tris(o)[1] if m >= 0}:
                k = o["name"].rfind("_" + car.mname(m) + "_")
                if WHEEL_MAT.search(car.mname(m)) and k > 0:
                    stems.add(o["name"][:k])
    cand = {}
    for oi, o in enumerate(objs):
        if o["kind"] in skip:
            continue
        T, ms, refs = car.tris(o)
        if any(o["name"].startswith(st + "_") for st in stems) and len(T) and T[..., 1].max() <= lo[1] + .5 * H:
            hit = np.ones(len(ms), bool)          # all low: rims, not a body that shares the name
        else:
            hit = per_material(ms, lambda m: m >= 0 and bool(WHEEL_MAT.search(car.mname(m))))
        if not hit.any():
            continue
        c = T.mean(1)
        ok = hit & (c[:, 1] <= lo[1] + .45 * H) & (np.abs(c[:, 0] - xm) >= .12 * Wd)
        for q, sel in (("fl", (c[:, 2] > zm) & (c[:, 0] > xm)), ("fr", (c[:, 2] > zm) & (c[:, 0] <= xm)),
                       ("rl", (c[:, 2] <= zm) & (c[:, 0] > xm)), ("rr", (c[:, 2] <= zm) & (c[:, 0] <= xm))):
            s = ok & sel
            if s.any():
                cand.setdefault(q, []).append((oi, refs[s], c[s]))
    plan = {}
    for q, lst in cand.items():
        C = np.vstack([c for _, _, c in lst])
        y0, y1 = np.percentile(C[:, 1], 1), np.percentile(C[:, 1], 99)
        D = max(y1 - y0, 1e-6)
        yc = y0 + D / 2
        topz = C[C[:, 1] > y0 + .85 * D, 2]
        zc = np.median(topz) if len(topz) else np.median(C[:, 2])
        xout = np.percentile(np.abs(C[:, 0] - xm), 99)
        for oi, refs, c in lst:
            s = ((c[:, 2] - zc) ** 2 + (c[:, 1] - yc) ** 2 <= (.56 * D) ** 2) & (np.abs(c[:, 0] - xm) >= xout - .5 * D)
            if s.any():
                plan.setdefault(oi, {}).setdefault(q, []).append(refs[s])
    counts = {q: int(sum(sum(len(r) for r in g.get(q, [])) for g in plan.values())) for q in ("fl", "fr", "rl", "rr")}
    if min(counts.values()) < 24:
        rep["material_wheels"] = {"found": False, "faces_per_corner": counts}
        return
    byq = {}
    for oi, g in plan.items():
        o = objs[oi]
        qs = [q for q in ("fl", "fr", "rl", "rr") if g.get(q)]
        for q, piece in zip(qs, car.lift(o, [np.vstack(g[q]) for q in qs])):
            byq.setdefault(q, []).append(piece)
    for q, pieces in byq.items():
        w = pieces[0]
        for p in pieces[1:]:
            w["segs"] += p["segs"]
        w["chain"] = f"material_wheel_{q}|" + w["chain"]
        w["kind"] = "wheel"
        objs.append(w)
    objs[:] = [o for o in objs if car.nfaces(o)]
    used = sorted({car.mname(car.prims[pi]["mat"]) for o in objs if o["kind"] == "wheel" for pi, _ in o["segs"]
                   if car.prims[pi]["mat"] is not None and WHEEL_MAT.search(car.mname(car.prims[pi]["mat"]))})[:8]
    rep["material_wheels"] = {"found": True, "faces_per_corner": counts, "materials": used}


def round_corners(car, objs, up, rep):
    """Four round, narrow, grounded objects in four corners, with `up` taken
    as up. Returns (picked, diameters, candidates) or None."""
    P = {"y": np.eye(3), "z": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float),
         "x": np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)}[up]
    allv = np.vstack([car.verts(o) for o in objs]) @ P.T
    lo, hi = bbox(allv)
    Q = np.eye(3)
    if (hi[0] - lo[0]) > (hi[2] - lo[2]):          # look at it from the side
        Q = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]], float)
        allv = allv @ Q.T
        lo, hi = bbox(allv)
    H, Wd = hi[1] - lo[1], hi[0] - lo[0]
    xm, zm = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    cand = []
    for o in objs:
        if o["kind"] in ("glazing", "lamps_front", "lamps_rear", "cabin", "steering", "door", "bonnet", "tailgate", "engine"):
            continue
        if car.nfaces(o) < 24:
            continue
        a, b = bbox(car.verts(o) @ P.T @ Q.T)
        dx, dy, dz = b - a
        if not dy or not dz:
            continue
        c = (a + b) / 2
        if (.8 <= dy / dz <= 1.25 and dx <= .6 * dy and .12 * H <= dy <= .5 * H and a[1] <= lo[1] + .08 * H
                and abs(c[0] - xm) >= .2 * Wd):
            cand.append((o, c, dy))
    rep["geometry_wheels"] = {"found": False, "up_tried": up, "candidates": len(cand)}
    if len(cand) < 4:
        return None
    corners = {}
    for o, c, d in cand:
        q = ("f" if c[2] > zm else "r") + ("l" if c[0] > xm else "r")
        corners.setdefault(q, []).append((o, c, d))
    if set(corners) != {"fl", "fr", "rl", "rr"}:
        rep["geometry_wheels"]["corners"] = {q: len(v) for q, v in corners.items()}
        return None
    picked = {}
    for q, cs in corners.items():
        cs.sort(key=lambda t: -t[2])
        o0, c0, d0 = cs[0]
        picked[q] = [o for o, c, d in cs if np.linalg.norm(c - c0) <= .35 * d0]
    ds = sorted(max(d for o, c, d in corners[q] if any(o is p for p in picked[q])) for q in picked)
    if ds[0] < .75 * ds[-1]:
        rep["geometry_wheels"]["diameters"] = [round(float(d), 3) for d in ds]
        return None
    return picked, ds, len(cand), P


def axle_halves(car, objs, rep):
    """Wheel meshes holding BOTH wheels of one axle, left and right, with
    nothing named (the 1998 Micra: `Object_4..7`, `Material.007`): split
    where each half, alone, is round, narrow and grounded at one side.
    The file is upright here (length on Z, up Y). Returns how many split."""
    V = np.vstack([car.verts(o) for o in objs])
    lo, hi = bbox(V)
    H, Wd, xm = hi[1] - lo[1], hi[0] - lo[0], (lo[0] + hi[0]) / 2

    def wheel_like(P):
        a, b = P.min(0), P.max(0)
        dx, dy, dz = b - a
        return (dz > 0 and .8 <= dy / dz <= 1.25 and dx <= .6 * dy and .12 * H <= dy <= .5 * H
                and a[1] <= lo[1] + .08 * H and abs((a[0] + b[0]) / 2 - xm) >= .2 * Wd)
    done = []
    for o in list(objs):
        if o["kind"] in ("glazing", "lamps_front", "lamps_rear", "cabin", "steering", "door", "bonnet",
                         "tailgate", "engine") or car.nfaces(o) < 48:
            continue
        T, _, refs = car.tris(o)
        xs = T[:, :, 0] - xm
        cross = (xs.min(1) < 0) & (xs.max(1) > 0)
        left = ~cross & (xs.mean(1) > 0)
        right = ~cross & ~left
        n = len(T)
        if cross.sum() > .02 * n or not (.3 * n <= left.sum() <= .7 * n):
            continue
        if not (wheel_like(T[left].reshape(-1, 3)) and wheel_like(T[right].reshape(-1, 3))):
            continue
        objs.append(car.lift(o, [refs[left]])[0])
        done.append(o["name"][:40])
    if done:
        rep["axle_halves"] = done
    return len(done)


def geometry_wheels(car, objs, rep):
    """Wheels from SHAPE and POSITION alone (the 2011 Corsa: `Object_65..68`,
    material `material`, and a file standing on its nose). Each axis is tried
    as up; the one where four round grounded corner objects appear is up.
    Last, wheels kept in pairs, one mesh an axle, are split and tried again."""
    found = None
    for up in ("y", "z", "x"):
        found = round_corners(car, objs, up, rep)
        if found:
            break
    if not found and axle_halves(car, objs, rep):
        up = "y"
        found = round_corners(car, objs, up, rep)
    if not found:
        return
    if up != "y":
        M = np.eye(4)
        M[:3, :3] = found[3]
        car.transform(M)
        V = np.vstack([car.verts(o) for o in objs])
        lo, hi = bbox(V)
        if (hi[0] - lo[0]) > (hi[2] - lo[2]):
            car.transform(rot_y(90))
        rep["re_upright"] = {"file_up_axis": up, "why": "four round grounded corner objects only exist with this axis up"}
        found = round_corners(car, objs, "y", rep)
        if not found:
            return
    picked, ds, ncand, _ = found
    for q, pieces in picked.items():
        w = pieces[0]
        for p in pieces[1:]:
            w["segs"] += p["segs"]
            p["segs"] = []
        w["chain"] = f"geometry_wheel_{q}|" + w["chain"]
        w["kind"] = "wheel"
    objs[:] = [o for o in objs if car.nfaces(o)]
    rep["geometry_wheels"] = {"found": True, "candidates": ncand,
                              "pieces_per_corner": {q: len(v) for q, v in picked.items()},
                              "diameter": round(float(ds[-1]), 3)}


def top_over_axles(car, objs, wheels):
    """The nose from the height of the bodywork over each axle: the bonnet
    end is lower (the 2009 Fiesta, where nothing is named)."""
    V = np.vstack([car.verts(o) for o in objs])
    lo, hi = bbox(V)
    zm = (lo[2] + hi[2]) / 2
    wc = [centre(car, [o]) for o in wheels]
    front = [c for c in wc if c[2] > zm]
    rear = [c for c in wc if c[2] <= zm]
    if not front or not rear:
        return None
    za, zb = np.mean([c[2] for c in front]), np.mean([c[2] for c in rear])
    WV = np.vstack([car.verts(o) for o in wheels])
    D = WV[:, 1].max() - WV[:, 1].min()
    if D <= 0 or abs(za - zb) < 2 * D:
        return None
    BV = np.vstack([car.verts(o) for o in objs if o["kind"] in ("body", "bonnet", "tailgate", "glazing", "door", "brakes")])

    def top(z0):
        ys = BV[np.abs(BV[:, 2] - z0) <= .12 * D, 1]
        return np.percentile(ys, 95) if len(ys) >= 50 else None
    ta, tb = top(za), top(zb)
    if ta is None or tb is None:
        return None
    ha, hb = ta - lo[1], tb - lo[1]
    if ha <= 0 or hb <= 0 or max(ha, hb) < 1.12 * min(ha, hb):
        return None
    return {"nose": 1 if ha < hb else -1, "top_plus_z": round(float(ha), 4), "top_minus_z": round(float(hb), 4),
            "ratio": round(float(max(ha, hb) / min(ha, hb)), 3)}


def red_lamp_end(car, objs, lo, hi):
    """Which end carries the red tail lamps, by material name or base colour,
    never the body paint (a red car); three times the other end's area."""
    L, H = hi[2] - lo[2], hi[1] - lo[1]
    area = {}
    data = []
    for o in objs:
        T, ms, _ = car.tris(o)
        if not len(T):
            continue
        a, _ = tri_area_normal(T)
        for mi in np.unique(ms):
            area[mi] = area.get(mi, 0) + float(a[ms == mi].sum())
        data.append((T, ms, a))
    paint = max(area, key=area.get) if area else None

    def red(mi):
        if mi < 0 or mi == paint:
            return False
        m = car.mats[mi] if mi < len(car.mats) else {}
        if RED_NAME.search(m.get("name", "")):
            return True
        pbr = m.get("pbrMetallicRoughness", {})
        if "baseColorTexture" in pbr:
            return False
        r, g, b = pbr.get("baseColorFactor", [1, 1, 1, 1])[:3]
        return r > .45 and g < .2 and b < .2
    end = {1: 0.0, -1: 0.0}
    for T, ms, a in data:
        reds = per_material(ms, red)
        if not reds.any():
            continue
        c = T.mean(1)
        ok = reds & (c[:, 1] > lo[1] + .25 * H) & (c[:, 1] < lo[1] + .85 * H)
        end[1] += float(a[ok & (c[:, 2] > hi[2] - .15 * L)].sum())
        end[-1] += float(a[ok & (c[:, 2] < lo[2] + .15 * L)].sum())
    a, b = end[1], end[-1]
    if a > 3 * b and a > 0:
        return 1
    if b > 3 * a and b > 0:
        return -1
    return None


def split_pairs(car, objs, width):
    """A door, wheel or brake mesh holding BOTH sides of the car is split left
    and right (the 2022 Tiguan); a wheel mesh holding both axles front and
    rear (the 2023 Sportage). Narrow on purpose."""
    done = []
    for o in [o for o in objs if o["kind"] in ("door", "wheel", "brakes")]:
        V = car.verts(o)
        b0, b1 = bbox(V)
        if not (b0[0] < -.25 * width and b1[0] > .25 * width):
            continue
        T, _, refs = car.tris(o)
        xs = T[:, :, 0]
        cross = (xs.min(1) < -.02 * width) & (xs.max(1) > .02 * width)
        left = ~cross & (xs.sum(1) > 0)
        n = len(T)
        if not n or cross.sum() > .02 * n or not (.2 * n <= left.sum() <= .8 * n):
            continue
        new = car.lift(o, [refs[left]])[0]
        objs.append(new)
        done.append(f"{o['name'][:40]} ({o['kind']})")
    V = np.vstack([car.verts(o) for o in objs])
    lo, hi = bbox(V)
    L, zm = hi[2] - lo[2], (lo[2] + hi[2]) / 2
    for o in [o for o in objs if o["kind"] == "wheel"]:
        b0, b1 = bbox(car.verts(o))
        if not (b0[2] < zm - .2 * L and b1[2] > zm + .2 * L):
            continue
        T, _, refs = car.tris(o)
        zs = T[:, :, 2]
        cross = (zs.min(1) < zm) & (zs.max(1) > zm)
        front = ~cross & (zs.mean(1) > zm)
        n = len(T)
        if not n or cross.sum() > .02 * n or not (.2 * n <= front.sum() <= .8 * n):
            continue
        objs.append(car.lift(o, [refs[front]])[0])
        done.append(f"{o['name'][:40]} (wheel, front/rear)")
    return done


def close_up(car, door, body, length):
    """A rear door kept shut (a 3-door asked for, a 5-door model: the 1998
    Micra) closed up so it reads as body: its outside handle goes; the
    skin's OUTER edge (not its window opening, not the edge against the
    front door, which opens) grows over the gap to the body, 1.5 times the
    gap measured (at most 0.4% of the car's length); the lining behind the
    skin, whose edges showed as a dark outline, steps inboard. Returns what
    was done."""
    from scipy.spatial import cKDTree
    isl = [(o, c) for o in door for c in islands(car, o, length)]
    if not isl:
        return {}
    skin_o, skin = max(isl, key=lambda t: t[1]["area"])
    s0, s1 = skin["lo"], skin["hi"]
    side = 1 if s0[0] + s1[0] > 0 else -1
    outer = max(abs(s0[0]), abs(s1[0]))
    out = {"handles_removed": 0, "linings_inboard": 0}
    step = max(.0025 * length, .003)

    handles = []
    for o, c in isl:
        if c is skin:
            continue
        b0, b1 = c["lo"], c["hi"]
        x_out = max(abs(b0[0]), abs(b1[0])) if np.sign(b0[0] + b1[0]) == side else 0.0
        if np.linalg.norm(b1 - b0) <= .06 * length and c["area"] <= .08 * skin["area"]:
            if x_out >= .9 * outer:
                handles.append((o, c))              # the handle (and its lock)
            continue
        mi = int(car.tris(o)[1][c["ix"][0]])
        glass = 0 <= mi < len(car.mats) and car.mats[mi].get("alphaMode") == "BLEND"
        if x_out >= .97 * outer and not glass:
            for pi, vs in _island_verts(car, o, c).items():
                car.prims[pi]["P"][vs, 0] -= side * step
            out["linings_inboard"] += 1
    # the skin's boundary: its outer loop is the widest
    T = car.tris(skin_o)[0][skin["ix"]]
    V = T.reshape(-1, 3)
    q = 1e-5 * car.unit(skin_o)
    vid = weld_ids(T, q).ravel()
    E = np.sort(vid.reshape(-1, 3)[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
    ue, cnt = np.unique(E, axis=0, return_counts=True)
    bnd = ue[cnt == 1]
    if not len(bnd):
        out["handles_removed"] = _lift_out(car, handles)
        return out
    nv = int(vid.max()) + 1
    _, lab = connected_components(coo_matrix((np.ones(len(bnd)), (bnd[:, 0], bnd[:, 1])), shape=(nv, nv)),
                                  directed=False)
    first = np.full(nv, -1)
    first[vid[::-1]] = np.arange(len(vid))[::-1]
    on = np.unique(bnd.ravel())
    loops = {l: on[lab[on] == l] for l in np.unique(lab[on])}
    widest = max(loops.values(), key=lambda lp: np.ptp(V[first[lp], 2]) * np.ptp(V[first[lp], 1]))
    rim = V[first[widest]]
    BT = [car.tris(o)[0] for o in body if car.nfaces(o)]
    if not BT:
        out["handles_removed"] = _lift_out(car, handles)
        return out
    BT = np.vstack(BT)
    BT = BT[(np.abs(BT[:, :, 0]).mean(1) >= .7 * outer) & (np.sign(BT[:, :, 0].mean(1)) == side)]
    if not len(BT):
        out["handles_removed"] = _lift_out(car, handles)
        return out
    from cabin_pack import dense_points
    zf_edge = s1[2] - .15 * (s1[2] - s0[2])
    rim = rim[rim[:, 2] < zf_edge]              # not the edge against the front door
    if not len(rim):
        out["handles_removed"] = _lift_out(car, handles)
        return out
    gap = float(np.median(cKDTree(dense_points(BT, .002 * length)).query(rim)[0]))
    grow = min(1.5 * gap, .004 * length)
    c = (s0 + s1) / 2
    keys = {tuple(k) for k in np.round(rim / q).astype(np.int64)}
    moved = 0
    for pi, vs in _island_verts(car, skin_o, skin).items():
        P = car.prims[pi]["P"]
        hit = np.array([tuple(k) in keys for k in np.round(P[vs] / q).astype(np.int64)], bool)
        if not hit.any():
            continue
        d = P[vs[hit], 1:] - c[1:]
        P[vs[hit], 1:] += d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12) * grow
        moved += int(hit.sum())
    out.update({"gap": round(gap, 4), "rim_grown": round(grow, 4), "rim_vertices": moved,
                "handles_removed": _lift_out(car, handles)})
    return out


def _lift_out(car, pieces):
    """Lift islands out of their objects and keep them nowhere (last: a lift
    renumbers what is left of the object)."""
    by = {}
    for o, c in pieces:
        by.setdefault(id(o), (o, []))[1].append(c["refs"])
    for o, refs in by.values():
        car.lift(o, [np.vstack(refs)])
    return len(pieces)


def _island_verts(car, o, c):
    """{prim index: vertex indices} of one island of `o`."""
    vs = {}
    for si, t in c["refs"]:
        pi = o["segs"][si][0]
        vs.setdefault(pi, set()).update(car.prims[pi]["I"][t].tolist())
    return {pi: np.array(sorted(v)) for pi, v in vs.items()}



def wanted(parts):
    """A van closed by BARN doors has no tailgate (the Vito)."""
    barn = "door_bl" in parts or "door_br" in parts
    return [p for p in ("panel_bonnet", "tailgate") if not (p == "tailgate" and barn)]


def shut_line(car, o, refs, z0, z1, length):
    """Where a piece holding BOTH doors of one side splits: a GROOVE leaves
    sharp (>30 deg), near-vertical edges; the peak in the middle 25-75% of
    the piece, when it stands out 3x (the RS6)."""
    sub = {"segs": []}
    for si in np.unique(refs[:, 0]):
        pi, _ = o["segs"][si]
        sub["segs"].append((pi, refs[refs[:, 0] == si, 1]))
    T, _, _ = car.tris(sub)
    vid = weld_ids(T, 1e-6 * car.unit(o))          # Blender: remove_doubles(dist=1e-6), mesh units
    _, n = tri_area_normal(T)
    E = edges_of(vid, n)
    NB = 60
    hist = np.zeros(NB)
    flat = T.reshape(-1, 3)
    first = {}
    for k, v in enumerate(vid.ravel()):
        first.setdefault(v, k)
    vpos = np.array([flat[first[v]] for v in range(vid.max() + 1)])
    sel = np.zeros(len(E["two"]), bool)
    sel[E["two"]] = E["ang"] >= 30
    e = E["edge"][sel]
    a, b = vpos[e[:, 0]], vpos[e[:, 1]]
    d = b - a
    dl = np.linalg.norm(d, axis=1)
    ok = (dl > 0) & (np.abs(d[:, 1]) / np.maximum(dl, 1e-12) >= .8)
    k = np.clip(((a[ok, 2] + b[ok, 2]) / 2 - z0) / (z1 - z0) * NB, 0, NB - 1).astype(int)
    np.add.at(hist, k, dl[ok])
    lo_k, hi_k = int(.25 * NB), int(.75 * NB)
    kk = lo_k + int(np.argmax(hist[lo_k:hi_k]))
    rest = [hist[i] for i in range(lo_k, hi_k) if abs(i - kk) > 3]
    ref = max(rest) if rest else 0
    prof = {"peak": round(float(hist[kk]), 3), "at_frac": round((kk + .5) / NB, 3), "next_best": round(float(ref), 3)}
    if hist[kk] > 0 and hist[kk] >= 3 * ref:
        return z0 + (kk + .5) / NB * (z1 - z0), prof
    return None, prof


def surface_points(T, step):
    """Points over each triangle no further apart than about `step`: its
    corners, its centre and, on a big triangle, a grid across it."""
    e = np.linalg.norm(T[:, [1, 2, 0]] - T, axis=2).max(1)
    k = np.clip(np.ceil(e / step).astype(int), 1, 40)
    out = [T.reshape(-1, 3), T.mean(1)]
    for kk in np.unique(k[k > 1]):
        t = T[k == kk]
        i, j = np.meshgrid(np.arange(kk + 1), np.arange(kk + 1), indexing="ij")
        ok = i + j <= kk
        u, v = (i[ok] / kk)[None, :, None], (j[ok] / kk)[None, :, None]
        out.append((t[:, None, 0] * (1 - u - v) + t[:, None, 1] * u + t[:, None, 2] * v).reshape(-1, 3))
    return np.vstack(out)


def flank_skin(car, objs, lo, hi, cx, cell=.05):
    """The outer skin seen from each side: for every 5 cm cell along and up
    the car, how far out from the centreline the body or its glass reaches."""
    nz, ny = int((hi[2] - lo[2]) / cell) + 2, int((hi[1] - lo[1]) / cell) + 2
    m = {"l": np.full((nz, ny), -np.inf), "r": np.full((nz, ny), -np.inf)}
    for q in objs:
        if q["kind"] not in ("body", "glazing") or not car.nfaces(q):
            continue
        P = surface_points(car.tris(q)[0], cell)
        iz = np.clip(((P[:, 2] - lo[2]) / cell).astype(int), 0, nz - 1)
        iy = np.clip(((P[:, 1] - lo[1]) / cell).astype(int), 0, ny - 1)
        for sd, sg in (("l", 1), ("r", -1)):
            np.maximum.at(m[sd], (iz, iy), sg * (P[:, 0] - cx))
    return m, cell


def inside_skin(car, o, c, side, skin, lo, cx):
    """Share of an island's side-facing area (either way: a lining faces the
    cabin, a modeller's flipped skin faces in) lying where the body reaches
    more than 3 cm further out than the island itself does (flank_skin). A
    door's own card, behind its skin, does not count against it."""
    m, cell = skin
    T = car.tris(o)[0][c["ix"]]
    a, n = tri_area_normal(T)
    sd = np.abs(n[:, 0]) > .5
    if a[sd].sum() <= 0:
        return 0.0
    sg = 1 if side == "l" else -1
    nz, ny = m[side].shape

    def cells(P):
        return (np.clip(((P[:, 2] - lo[2]) / cell).astype(int), 0, nz - 1),
                np.clip(((P[:, 1] - lo[1]) / cell).astype(int), 0, ny - 1))
    own = np.full((nz, ny), -np.inf)
    P = surface_points(T[sd], cell)
    np.maximum.at(own, cells(P), sg * (P[:, 0] - cx))
    iz, iy = cells(T[sd].mean(1))
    cov = m[side][iz, iy] > own[iz, iy] + .03
    return float(a[sd][cov].sum() / a[sd].sum())


def find_doors(car, objs, wheels, lo, hi, rep, body_style=""):
    """Doors that are LOOSE PIECES inside a body mesh (the RS6): wholly on one
    flank, 45% of the car's height from low down, 15-60% of its length,
    between the axles, mirrored on the other side. A piece two doors long is
    split at its shut line."""
    L, Wd, H = hi[2] - lo[2], hi[0] - lo[0], hi[1] - lo[1]
    cx = (lo[0] + hi[0]) / 2
    wz = [centre(car, [o])[2] for o in wheels]
    zf, zr = max(wz), min(wz)
    found = {"l": [], "r": []}
    info = rep.setdefault("door_finder", {})
    skin = None
    for o in objs:
        if o["kind"] != "body" or car.nfaces(o) < 50:
            continue
        for c in islands(car, o, L):
            b0, b1 = c["lo"], c["hi"]
            side = "l" if b0[0] - cx > .25 * Wd else "r" if cx - b1[0] > .25 * Wd else None
            if not side or not (b1[1] - b0[1] > .45 * H and b0[1] < lo[1] + .35 * H):
                continue
            if not (.15 * L < b1[2] - b0[2] < .6 * L and zr < (b0[2] + b1[2]) / 2 < zf):
                continue
            # a piece the body's own skin covers from outside is a cabin
            # lining or a door card, not a door: the 2022 Caddy's, whose door
            # skins are each two strips too short to be found, and the
            # Sprinter's, a sliding door long, behind its sliding door
            skin = skin if skin is not None else flank_skin(car, objs, lo, hi, cx)
            cov = inside_skin(car, o, c, side, skin, lo, cx)
            if cov > .5:
                info.setdefault("inside_skin", []).append(
                    {"side": side, "z": [round(float(b0[2]), 2), round(float(b1[2]), 2)], "covered": round(cov, 2)})
                continue
            found[side].append((c["area"], o, c["refs"], b0, b1))
    if not found["l"] or not found["r"]:
        info["result"] = f"no door-shaped piece on {'both sides' if not (found['l'] or found['r']) else 'one side'}"
        return []
    for side in found:
        # the door's own skin, not the trim inside it: the outermost pieces of
        # the flank (within 10 cm), whose lining joins them later (the Mazda 3:
        # its biggest door-shaped piece is the cabin's trim, both doors long)
        out_x = (lambda t: t[4][0]) if side == "l" else (lambda t: -t[3][0])
        edge = max(out_x(t) for t in found[side])
        found[side] = [t for t in found[side] if out_x(t) >= edge - .1]
        found[side].sort(key=lambda t: -t[0])
        big = found[side][0][0]
        found[side] = [t for t in found[side] if t[0] > .3 * big][:4]
    # every door kept has its twin on the other flank, at the same place along
    # the car (within 5% of the length), matched pair by pair, biggest first:
    # a modeller's left and right doors are seldom the same size to the
    # square centimetre, so the biggest piece of one side may be the front
    # door and of the other the rear (the Kamiq)
    pairs, used = [], set()
    for tl in found["l"]:
        l0, l1 = tl[3], tl[4]
        # the same door again (its frame, its skin), or a piece holding most of
        # a kept door along its length: the Sprinter's cargo-bay lining runs
        # from its sliding door to the back, and is no door at all
        if any(min(l1[2], p[0][4][2]) - max(l0[2], p[0][3][2])
               > .5 * min(l1[2] - l0[2], p[0][4][2] - p[0][3][2]) for p in pairs):
            continue
        j = next((j for j, tr in enumerate(found["r"]) if j not in used
                  and abs(l0[2] - tr[3][2]) <= .05 * L and abs(l1[2] - tr[4][2]) <= .05 * L), None)
        if j is not None:
            used.add(j)
            pairs.append((tl, found["r"][j]))
        if len(pairs) == 2:
            break
    if not pairs:
        info["result"] = "left and right door pieces do not mirror each other — not guessing"
        return []
    if len(pairs) < min(len(found["l"]), len(found["r"]), 2):
        info["unpaired"] = "a door piece on one flank has no twin on the other: left out"
    pairs.sort(key=lambda p: -p[0][3][2])            # front first
    found = {"l": [p[0] for p in pairs], "r": [p[1] for p in pairs]}
    groups = []                                     # (obj, name, refs)
    for side in ("l", "r"):
        lst = found[side]
        # one long piece is two doors on a five-door side; on a two-door body
        # (a coupe, a three-door hatch: the GR Yaris) it is the door, unless
        # it is longer than any door (42% of the car: a five-door model asked
        # for as a two-door), when it is two and the rear one is kept shut
        two = bool(TWO_DOOR.search(body_style or os.environ.get("SB_BODY", "")))
        if len(lst) == 1 and lst[0][4][2] - lst[0][3][2] > (.42 if two else .3) * L:
            area, o, refs, b0, b1 = lst[0]
            cut, prof = shut_line(car, o, refs, b0[2], b1[2], L)
            info[f"shut_line_{side}"] = prof
            if cut is not None:
                sub = {"segs": o["segs"]}
                T, _, _ = car.tris(sub)
                # centre z of each ref's triangle
                cz = np.array([car.prims[o["segs"][s][0]]["P"][car.prims[o["segs"][s][0]]["I"][t]].mean(0)[2]
                               for s, t in refs])
                fr, rr = refs[cz > cut], refs[cz <= cut]
                info[f"split_{side}"] = {"cut_z": round(float(cut), 4), "cut_frac": round(float((cut - lo[2]) / L), 3),
                                         "front": len(fr), "rear": len(rr)}
                groups += [(o, f"door_island_{side}f", fr), (o, f"door_island_{side}r", rr)]
                continue
        for k, (area, o, refs, b0, b1) in enumerate(lst):
            groups.append((o, f"door_island_{side}{k}", refs))
    out = []
    byobj = {}
    for o, name, refs in groups:
        byobj.setdefault(id(o), (o, []))[1].append((name, refs))
    for o, gl in byobj.values():
        for (name, _), new in zip(gl, car.lift(o, [r for _, r in gl])):
            new["name"] = new["chain"] = name
            out.append(new)
    info["doors"] = [o["name"] for o in out]
    info["result"] = f"{len(out)} door piece(s) lifted from body islands"
    return out


def cut_doors(car, objs, wheels, lo, hi, rep, body_style=""):
    """WELDED DOORS: cut the door skins out of the body shell.
    Where: SHUT LINES (sharp near-vertical edges, or open panel edges, on the
    flanks; the Focus peaks exactly at the door's leading edge and the
    B-pillar), else PROPORTIONS (front door 33-63% of the wheelbase behind the
    front axle; calibrated on the Focus). Each door skin is GROWN from a seed
    across smooth edges only, so it stops at the panel's own creases. A door
    that cannot be cut cleanly stays shut, with its twin."""
    info = rep.setdefault("door_cutter", {})
    L, Wd, H = hi[2] - lo[2], hi[0] - lo[0], hi[1] - lo[1]
    cx = (lo[0] + hi[0]) / 2
    wz = [centre(car, [o])[2] for o in wheels]
    zf, zr = max(wz), min(wz)
    wb = zf - zr
    r = np.vstack([car.verts(o) for o in wheels])[:, 1].max() / 2
    if wb < .3 * L or r <= 0:
        info["result"] = "cannot place the axles"
        return {}
    src = [o for o in objs if o["kind"] == "body" and car.nfaces(o) >= 50]
    gls = [o for o in objs if o["kind"] == "glazing" and car.nfaces(o)]
    ysill, ytop = .7 * r, hi[1] - .12 * H
    NB, NY = 80, 6
    hist = np.zeros(NB)
    hits = [[set(), set()] for _ in range(NB)]
    cache = {}
    for o in [o for o in objs if o["kind"] == "body"]:
        T, ms, refs = car.tris(o)
        if not len(T):
            continue
        vid = weld_ids(T, 1e-6 * car.unit(o))      # shut lines: Blender welds at 1e-6 mesh units
        a_, n_ = tri_area_normal(T)
        E = edges_of(vid, n_)
        Eg = edges_of(weld_ids(T, 1e-5 * car.unit(o)), n_)   # growth: at 1e-5
        flat = T.reshape(-1, 3)
        vpos = np.zeros((vid.max() + 1, 3))
        vpos[vid.ravel()] = flat
        cache[id(o)] = (T, ms, refs, vid, a_, n_, Eg)
        e = E["edge"]
        cnt = E["count"]
        ang = np.zeros(len(e))
        ang[E["two"]] = E["ang"]
        sel = (cnt == 1) | ((cnt == 2) & (ang >= 30))
        A, B = vpos[e[sel, 0]], vpos[e[sel, 1]]
        d = B - A
        dl = np.linalg.norm(d, axis=1)
        mx = (A[:, 0] + B[:, 0]) / 2
        ok = (dl > 0) & (np.abs(d[:, 1]) / np.maximum(dl, 1e-12) >= .8) & (np.abs(mx - cx) >= .3 * Wd)
        zc, yc = (A[:, 2] + B[:, 2]) / 2, (A[:, 1] + B[:, 1]) / 2
        ok &= (zr < zc) & (zc < zf) & (1.0 * r < yc) & (yc < 2.4 * r)
        for z in (zf, zr):
            ok &= (yc - r) ** 2 + (zc - z) ** 2 > (1.3 * r) ** 2
        k = np.minimum(NB - 1, ((zc - zr) / wb * NB).astype(int))
        for i in np.where(ok)[0]:
            hist[k[i]] += dl[i]
            fl = 0 if mx[i] > cx else 1
            for yy in (A[i, 1], B[i, 1], yc[i]):
                hits[k[i]][fl].add(int(min(NY - 1, max(0, int((yy - r) / (1.4 * r) * NY)))))
    cover = [max(len(set().union(*(hits[j][s] for j in range(max(0, k - 1), min(NB, k + 2))))) for s in (0, 1))
             for k in range(NB)]
    mean = hist.sum() / NB
    need = max(.1 * H, 1.5 * mean)

    def zat(k):
        return zr + (k + .5) / NB * wb

    def line(a, b, front):
        cand = [i for i in range(max(0, a), min(NB, b)) if cover[i] >= 5 and hist[i] >= need]
        if not cand:
            return None
        top_ = max(hist[i] for i in cand)
        cand = [i for i in cand if hist[i] >= .6 * top_]
        return max(cand) if front else min(cand)
    kf = line(int(.50 * NB), int(.85 * NB), True)
    two = bool(TWO_DOOR.search(body_style or os.environ.get("SB_BODY", "")))
    info["doors_expected"] = 2 if two else 4
    if two:
        kb = line(int(.12 * NB), (kf if kf is not None else int(.70 * NB)) - int(.30 * NB), False)
    else:
        kb = line(int(.20 * NB), (kf if kf is not None else int(.70 * NB)) - int(.22 * NB), False)
    F = zat(kf) if kf is not None else zf - .33 * wb
    Bp = zat(kb) if kb is not None else zf - (.70 if two else .63) * wb
    Rr = zr + .045 * wb
    ev = {"front_edge": "shut line" if kf is not None else "proportion",
          "b_pillar": "shut line" if kb is not None else "proportion", "rear_edge": "proportion"}
    info["profile"] = [round(float(h), 2) for h in hist]
    info["cover"] = cover
    info.update(evidence=ev, front_edge_z=round(float(F), 3), b_pillar_z=round(float(Bp), 3),
                rear_edge_z=round(float(Rr), 3), peak_need=round(float(need), 3))
    if not (zr < Rr < Bp < F < zf) or F - Bp < .15 * wb or Bp - Rr < .15 * wb:
        info["result"] = "door edges out of order — not cutting"
        return {}

    def near_arch(c):
        return np.any([(c[:, 1] - r) ** 2 + (c[:, 2] - z) ** 2 < (1.35 * r) ** 2 for z in (zf, zr)], axis=0)

    def in_arch(c):
        return np.any([(c[:, 1] - r) ** 2 + (c[:, 2] - z) ** 2 < (1.03 * r) ** 2 for z in (zf, zr)], axis=0)
    pad = .04 * wb
    nom = {"f": (Bp, F)} if two else {"f": (Bp, F), "r": (Rr, Bp)}
    grow = {"f": (Bp - pad, zf - .9 * r), "r": (Rr - pad, F)}
    seed_z = {"f": zf - .48 * wb, "r": zf - .80 * wb}
    if not Bp < seed_z["f"] < F:
        seed_z["f"] = (Bp + F) / 2
    if not Rr < seed_z["r"] < Bp:
        seed_z["r"] = (Rr + Bp) / 2
    # the car's outer skin at each seed, over every mesh (the Polo's seat bolsters)
    skin_x = {}
    for o in src:
        T, ms, refs, vid, a_, n_, E = cache[id(o)]
        c = T.mean(1)
        mn = per_material(ms, lambda m: GLASS_MAT.search(car.mname(m)))
        for sd in (1, -1):
            ok = ~mn & (sd * n_[:, 0] > .7) & (ysill < c[:, 1]) & (c[:, 1] < ytop) & (np.sign(c[:, 0] - cx) == sd)
            for d in ("f", "r"):
                s = ok & (np.abs(c[:, 2] - seed_z[d]) < .06 * wb) & (np.abs(c[:, 1] - 1.45 * r) < .35 * r)
                if s.any():
                    skin_x[(sd, d)] = max(skin_x.get((sd, d), -1e9), float((sd * c[s, 0]).max()))
    groups, area, clamped, top = {}, {}, [], {}
    for o in src:
        T, ms, refs, vid, a_, n_, E = cache[id(o)]
        c = T.mean(1)
        u, inv = np.unique(ms, return_inverse=True) if len(ms) else (np.zeros(0, int), np.zeros(0, int))
        un = [car.mname(int(m)) for m in u]           # each material's name, looked up once
        mname = np.array(un or [""])[inv.reshape(-1)]
        isg = np.array([bool(GLASS_MAT.search(m)) for m in un] or [False])[inv.reshape(-1)]
        smooth = E["two"].copy()
        smooth[E["two"]] = E["ang"] <= ANG
        sa, sb = E["fa"][E["ang"] <= ANG], E["fb"][E["ang"] <= ANG]
        for sd in (1, -1):
            side = "l" if sd > 0 else "r"
            for d, (z0, z1) in nom.items():
                pid = f"door_{d}{side}"
                g0, g1 = grow[d]
                base = (~isg & (sd * (c[:, 0] - cx) > .25 * Wd) & (sd * n_[:, 0] > .25) & (ysill < c[:, 1])
                        & (c[:, 1] < ytop) & (g0 < c[:, 2]) & (c[:, 2] < g1) & ~in_arch(c)
                        & ((sd * n_[:, 0] > .8) | ~near_arch(c)))
                seeds = base & (sd * n_[:, 0] > .7) & (np.abs(c[:, 2] - seed_z[d]) < .06 * wb) \
                    & (np.abs(c[:, 1] - 1.45 * r) < .35 * r)
                seeds &= sd * c[:, 0] > skin_x.get((sd, d), 1e9) - .03 * Wd
                if not seeds.any():
                    continue
                ms_ = {}
                for i in np.where(seeds)[0]:
                    ms_[mname[i]] = ms_.get(mname[i], 0) + a_[i]
                paint = max(ms_, key=ms_.get)
                fits = base & (mname == paint)
                seeds &= mname == paint
                # growth: faces that fit, joined across smooth edges, reached from a seed
                ok_e = fits[sa] & fits[sb]
                nt = len(T)
                Agr = coo_matrix((np.ones(ok_e.sum()), (sa[ok_e], sb[ok_e])), shape=(nt, nt))
                _, lab = connected_components(Agr, directed=False)
                seen = np.isin(lab, np.unique(lab[seeds])) & fits
                zs = c[seen, 2]
                if not len(zs):
                    continue
                lo_c = zs.min() < (z0 - .5 * pad if d == "f" else g0 + .25 * pad)
                hi_c = zs.max() > (g1 - .25 * pad if d == "f" else z1 + .5 * pad)
                if lo_c or hi_c:
                    clamped.append(f"{pid}{' rear' if lo_c else ''}{' front' if hi_c else ''}")
                keep = seen & ((~lo_c) | (c[:, 2] >= z0)) & ((~hi_c) | (c[:, 2] < z1))
                if d == "r" and lo_c:
                    keep &= (c[:, 1] - r) ** 2 + (c[:, 2] - zr) ** 2 > (1.25 * r) ** 2
                groups.setdefault(id(o), (o, {}))[1].setdefault(pid, set()).update(np.where(keep)[0].tolist())
                area[pid] = area.get(pid, 0) + float(a_[keep].sum())
                if keep.any():
                    top[pid] = max(top.get(pid, -1e9), float(c[keep, 1].max()))
    # a face both doors grew into goes by the line
    for o, g in groups.values():
        cz = cache[id(o)][0].mean(1)[:, 2]
        for side in "lr":
            f_, r_ = g.get("door_f" + side), g.get("door_r" + side)
            if f_ and r_ and f_ & r_:
                both = f_ & r_
                f_ -= {i for i in both if cz[i] < Bp}
                r_ -= {i for i in both if cz[i] >= Bp}
    info["clamped_at_line"] = clamped
    info["skin_top"] = {p: round(y, 4) for p, y in top.items()}
    want = {"f": (F - Bp) * 1.6 * r, "r": (Bp - Rr) * 1.6 * r}
    info["skin_area_share"] = {p: round(area.get(p, 0) / want[p[5]], 2)
                               for p in (("door_fl", "door_fr") if two else ("door_fl", "door_rl", "door_fr", "door_rr"))}
    bad = {}
    for p_, sh in info["skin_area_share"].items():
        if sh < .4:
            bad[p_] = f"too little skin ({sh})"
        elif sh > 1.8:
            bad[p_] = f"too much skin ({sh}) — grew past the door"
        elif top.get(p_, 0) > lo[1] + .78 * H:
            bad[p_] = "reaches above the glass line"
        elif sh > 1.3 and sum(1 for c_ in clamped if c_.startswith(p_ + " ") and "rear" in c_ and "front" in c_):
            bad[p_] = f"no panel edge at either end and oversized ({sh}) — not a door"
    for p_ in list(bad):
        twin = p_[:-1] + ("r" if p_[-1] == "l" else "l")
        bad.setdefault(twin, f"its twin {p_} was refused")
    info["refused_doors"] = bad
    ok = [p_ for p_ in info["skin_area_share"] if p_ not in bad]
    if not {"door_fl", "door_fr"} <= set(ok):
        info["result"] = "no clean door cut: " + "; ".join(f"{k} {v}" for k, v in bad.items()
                                                         if not v.startswith("its twin"))[:300]
        return {}
    # each side window above a kept door goes with it, as a whole pane
    gl_groups = []
    for o in gls:
        for cmp in islands(car, o, L):
            b0, b1 = cmp["lo"], cmp["hi"]
            midp = (b0 + b1) / 2
            sd = 1 if midp[0] > cx else -1
            if sd * (midp[0] - cx) < .25 * Wd or b1[1] < 1.6 * r or b1[2] - b0[2] > .6 * wb:
                continue
            d = "f" if Bp <= midp[2] < F + .03 * wb else "r" if Rr <= midp[2] < Bp else None
            pid = d and f"door_{d}{'l' if sd > 0 else 'r'}"
            if pid in ok:
                gl_groups.append((o, pid, cmp["refs"]))
    out = {}
    for o, g in groups.values():
        refs = cache[id(o)][2]
        todo = [(p, refs[sorted(f)]) for p, f in g.items() if p in ok and f]
        if not todo:
            continue
        for (pid, _), new in zip(todo, car.lift(o, [r_ for _, r_ in todo])):
            new["name"] = new["chain"] = "door_cut_" + pid[5:]
            new["card"] = (1 if pid[-1] == "l" else -1, .025 * Wd)     # a dark inner panel, written on export
            out.setdefault(pid, []).append(new)
    for o, pid, refs in gl_groups:
        new = car.lift(o, [refs])[0]
        out.setdefault(pid, []).append(new)
    info["result"] = f"cut {len([p for p in out])} door(s) from the body: {sorted(out)}"
    info["faces"] = {p: sum(car.nfaces(x) for x in os_) for p, os_ in out.items()}
    return out


def adopt_into_doors(car, parts, rep, length):
    """Loose pieces of OTHER meshes that belong to an island or cut door
    (glass, handles, trim, the window frame) go with it (the RS6's one Window
    mesh; the Polo's frame bar left floating)."""
    info = rep.setdefault("door_finder", {})
    moved = 0
    for side in ("l", "r"):
        dps = [p for p in ("door_f" + side, "door_r" + side) if p in parts]
        if not dps:
            continue
        boxes = {p: bbox(np.vstack([car.verts(o) for o in parts[p]])) for p in dps}
        b0 = np.min([boxes[p][0] for p in dps], axis=0)
        b1 = np.max([boxes[p][1] for p in dps], axis=0)
        cutter = bool(rep.get("door_cutter", {}).get("faces"))
        hubs = []
        for k in ("wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr"):
            if parts.get(k):
                w0, w1 = bbox(np.vstack([car.verts(o) for o in parts[k]]))
                hubs.append(((w0[2] + w1[2]) / 2, (w1[1] - w0[1]) / 2))
        cut = info.get(f"split_{side}", {}).get("cut_z")
        m = .02
        if cutter:
            AV = np.vstack([car.verts(o) for os_ in parts.values() for o in os_ if car.nfaces(o)])
            c0, c1 = bbox(AV)
            Wc, roof = c1[0] - c0[0], c1[1] - .02 * (c1[1] - c0[1])
            sx = 1 if side == "l" else -1
            outer = {q: float(np.abs(np.vstack([car.verts(o) for o in parts[q]])[:, 0]).max()) for q in dps}
            tops = rep["door_cutter"].get("skin_top", {})
        for other in ("glazing", "body", "cabin"):
            for o in list(parts.get(other, [])):
                if car.nfaces(o) < 2:
                    continue
                grp = {p: [] for p in dps}
                comps = islands(car, o, length)
                T, _, refs = car.tris(o)
                for cmp in comps:
                    cb0, cb1 = cmp["lo"], cmp["hi"]
                    if cutter:
                        midp = (cb0 + cb1) / 2
                        p = None
                        for q in dps:
                            q0, q1 = boxes[q]
                            ln = q1[2] - q0[2]
                            if not (q0[2] - m <= midp[2] <= q1[2] + m and cb0[2] >= q0[2] - .12 * ln
                                    and cb1[2] <= q1[2] + .12 * ln and cb0[1] >= q0[1] - m and cb1[1] <= roof):
                                continue
                            inb = min(abs(cb0[0]), abs(cb1[0]))
                            if sx * cb0[0] < 0 or inb < outer[q] - .2 * Wc:
                                continue
                            if (other != "glazing" and cb0[1] >= tops.get(q, 1e9) - m and cb1[2] - cb0[2] < .4 * ln
                                    and max(abs(cb0[0]), abs(cb1[0])) <= outer[q] + .03 * Wc):
                                continue
                            if inb < outer[q] - .08 * Wc and cb0[1] < tops.get(q, 1e9) - m:
                                _, nn = tri_area_normal(T[cmp["ix"]])
                                aa, _ = tri_area_normal(T[cmp["ix"]])
                                fac = float((sx * nn[:, 0] * aa).sum() / max(aa.sum(), 1e-12))
                                if cb1[0] - cb0[0] > .12 * Wc or fac > -.1:
                                    continue
                            p = q
                            break
                        if p and not any((midp[1] - wr_) ** 2 + (midp[2] - wz_) ** 2 < (1.35 * wr_) ** 2
                                         for wz_, wr_ in hubs):
                            grp[p].append(cmp["refs"])
                        continue
                    if not all(b0[i] - m <= cb0[i] and cb1[i] <= b1[i] + m for i in range(3)):
                        continue
                    shut = cut
                    if shut is None and len(dps) == 2:
                        # a lining both doors long (the 1998 Micra's door cards,
                        # one piece a side) splits where the doors meet
                        zf, zr = boxes["door_f" + side][0][2], boxes["door_r" + side][1][2]
                        z_ = (zf + zr) / 2
                        lf = boxes["door_f" + side][1][2] - zf
                        lr = zr - boxes["door_r" + side][0][2]
                        if cb0[2] < z_ - .25 * lr and cb1[2] > z_ + .25 * lf:
                            shut = z_
                    if shut is not None and len(dps) == 2:
                        cz = T[cmp["ix"]].mean(1)[:, 2]
                        grp["door_f" + side].append(cmp["refs"][cz > shut])
                        grp["door_r" + side].append(cmp["refs"][cz <= shut])
                    else:
                        cz = (cb0[2] + cb1[2]) / 2
                        p = min(dps, key=lambda q: abs((boxes[q][0][2] + boxes[q][1][2]) / 2 - cz))
                        grp[p].append(cmp["refs"])
                todo = [(p, np.vstack(g)) for p, g in grp.items() if g and sum(len(x) for x in g)]
                if not todo:
                    continue
                if len(todo) == 1 and len(todo[0][1]) >= car.nfaces(o):
                    drop(parts[other], o)
                    parts[todo[0][0]].append(o)
                    moved += len(todo[0][1])
                    continue
                if sum(len(g) for _, g in todo) >= car.nfaces(o) and not cutter:
                    continue
                for (p, g), new in zip(todo, car.lift(o, [g for _, g in todo])):
                    parts[p].append(new)
                    moved += len(g)
    info["adopted_faces"] = moved


def lift_panels(car, parts, paint, lo, hi, rep):
    """A bonnet or boot lid kept as one loose piece of the paint mesh, lifted
    when it is the only piece in its place (one candidate, never a guess)."""
    need = [p for p in wanted(parts) if not parts.get(p)]
    if not (need and paint is not None):
        return
    L, Wd, H = hi[2] - lo[2], hi[0] - lo[0], hi[1] - lo[1]
    for o in list(parts.get("body", [])):
        if not any(car.prims[pi]["mat"] == paint for pi, _ in o["segs"]):
            continue
        # The up / along-the-car tests are kept exactly as calibrated in
        # Blender, whose world normals carried the object's scale: a mean of
        # 0.51 read 0.70 at scale 1.375 (the BMW 1 Series boot lid), so a lid
        # and a lip both qualified and nothing was guessed.
        u = car.unit(o)
        progress = True
        while need and progress:
            progress = False
            comps = islands(car, o, L)
            for c in comps:
                c["up"], c["fwd"] = c["up"] * u, c["fwd"] * u
            for pid in list(need):
                def where(c):
                    return ((c["hi"][0] - c["lo"][0]) > .6 * Wd and c["lo"][1] > lo[1] + .25 * H
                            and (c["hi"][2] > hi[2] - .15 * L if pid == "panel_bonnet" else c["lo"][2] < lo[2] + .15 * L))
                cand = [c for c in comps if where(c)
                        and (abs(c["up"]) > .55 if pid == "panel_bonnet" else (abs(c["up"]) > .55 or c["fwd"] < -.55))]
                if not cand:                          # a closed shell's normals cancel (RS6 bonnet)
                    cand = [c for c in comps if where(c)
                            and (c["upf"] > .6 if pid == "panel_bonnet" else c["upf"] + c["endf"] > .9)]
                rep.setdefault("island_candidates", {})[pid] = len(cand)
                if len(cand) == 1:
                    parts.setdefault(pid, []).append(car.lift(o, [cand[0]["refs"]])[0])
                    need.remove(pid)
                    rep.setdefault("lifted", {})[pid] = len(cand[0]["refs"])
                    progress = True
                    break
        if not need:
            break


def hinges(car, parts, island_doors=False):
    hinge = {}
    for pid in [k for k in parts if k.startswith("door_b")]:
        vs = np.vstack([car.verts(o) for o in parts[pid]])
        b0, b1 = bbox(vs)
        x = np.percentile(np.abs(vs[:, 0]), 98)
        edge = vs[np.abs(vs[:, 0]) > x - .06]
        hinge[pid] = {"x": round(float(x if pid[-1] == "l" else -x), 4), "y": round(float((b0[1] + b1[1]) / 2), 4),
                      "z": round(float(edge[:, 2].mean()), 4)}
    for pid in [k for k in parts if k.startswith("door_") and k[5] in "fr"]:
        vs = np.vstack([car.verts(o) for o in parts[pid]])
        b0, b1 = bbox(vs)
        edge = vs[vs[:, 2] > b1[2] - .06]
        if island_doors:                            # the RS6's rear door: its last 6 cm all inner trim
            edge = vs[vs[:, 2] > b1[2] - .15 * (b1[2] - b0[2])]
        x = np.percentile(np.abs(edge[:, 0]), 95 if island_doors else 90)
        hinge[pid] = {"x": round(float(x if pid[-1] == "l" else -x), 4), "y": round(float((b0[1] + b1[1]) / 2), 4),
                      "z": round(float(b1[2]), 4)}
    if parts.get("panel_bonnet"):
        vs = np.vstack([car.verts(o) for o in parts["panel_bonnet"]])
        b0, b1 = bbox(vs)
        hinge["panel_bonnet"] = {"x": 0, "y": round(float(vs[vs[:, 2] < b0[2] + .06, 1].max()), 4), "z": round(float(b0[2]), 4)}
    if parts.get("tailgate"):
        vs = np.vstack([car.verts(o) for o in parts["tailgate"]])
        b0, b1 = bbox(vs)
        hinge["tailgate"] = {"x": 0, "y": round(float(vs[vs[:, 2] > b1[2] - .06, 1].max()), 4), "z": round(float(b1[2]), 4)}
    return hinge


def implausible(car, parts, hinge):
    """Opening parts that cannot be what they claim go back to the body: the
    2023 Sportage's 'doors' hinged ahead of the front wheels, the 2023 Polo's
    'bonnet' carrying the wings and bumper."""
    wc = {k: centre(car, parts[k]) for k in ("wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr") if parts.get(k)}
    if len(wc) < 4 or os.environ.get("SB_NO_IMPLAUSIBLE"):
        return []
    AV = np.vstack([car.verts(o) for os_ in parts.values() for o in os_ if car.nfaces(o)])
    lo, hi = bbox(AV)
    L = hi[2] - lo[2]
    wtop = max(np.vstack([car.verts(o) for o in parts[k]])[:, 1].max() for k in wc)
    zf = (wc["wheel_fl"][2] + wc["wheel_fr"][2]) / 2
    zr = (wc["wheel_rl"][2] + wc["wheel_rr"][2]) / 2
    out = []
    for pid in list(hinge):
        objs_ = [o for o in parts.get(pid, []) if car.nfaces(o)]
        if not objs_:
            continue
        b0, b1 = bbox(np.vstack([car.verts(o) for o in objs_]))
        lim = .42 * L if pid.startswith("door_") else .35 * L if pid == "tailgate" else None
        if lim and b1[2] - b0[2] > lim and len(objs_) > 1:
            main = max(objs_, key=lambda o: len(car.verts(o)))
            m0, m1 = bbox(car.verts(main))

            def within(o):
                o0, o1 = bbox(car.verts(o))
                return m0[2] - .08 * L <= o0[2] and o1[2] <= m1[2] + .08 * L
            stray = [o for o in objs_ if o is not main and not within(o)]
            rest = [o for o in objs_ if not any(o is s for s in stray)]
            if stray and rest:
                r0, r1 = bbox(np.vstack([car.verts(o) for o in rest]))
                if r1[2] - r0[2] <= lim:
                    parts[pid] = rest
                    twin = None
                    if pid.startswith("door_") and pid[5] in "fr":
                        twin = "door_" + ("r" if pid[5] == "f" else "f") + pid[6]
                    for o in stray:
                        if twin in parts and twin in hinge:
                            t0, t1 = bbox(np.vstack([car.verts(x) for x in parts[twin]]))
                            o0, o1 = bbox(car.verts(o))
                            if t0[2] - .05 * L <= o0[2] and o1[2] <= t1[2] + .05 * L:
                                parts[twin].append(o)
                                continue
                        parts.setdefault("body", []).append(o)
                    hinge[pid] = hinges(car, {pid: rest}, False)[pid]
                    out.append(f"{pid}: kept; {len(stray)} stray piece(s) sent back to the body")
                    objs_, b0, b1 = rest, r0, r1
        h, why = hinge[pid], None
        wb = zf - zr
        cz = (b0[2] + b1[2]) / 2
        if pid.startswith("door_") and pid[5] in "fr":
            if b1[2] - b0[2] > .42 * L:
                why = f"{b1[2] - b0[2]:.2f} long, more than 42% of the car"
            elif not zr - .05 * L <= h["z"] <= zf + .04 * L:
                why = "hinged outside the wheelbase (a wing, not a door)"
            elif pid[5] == "f" and h["z"] < zf - .45 * wb:
                why = "a front door hinged in the rear half of the wheelbase"
            elif pid[5] == "r" and h["z"] > zf - .2 * wb:
                why = "a rear door hinged at the front axle"
        elif pid == "panel_bonnet":
            if b0[1] < .6 * wtop:
                why = f"reaches down to {b0[1]:.2f}, bumper height — not a bonnet"
            elif cz < zf - .15 * L:
                why = "not over the front of the car"
        elif pid == "tailgate":
            if b1[2] - b0[2] > .35 * L:
                why = f"{b1[2] - b0[2]:.2f} long, more than 35% of the car"
            elif cz > zr + .15 * L:
                why = "not at the back of the car"
        if why:
            parts.setdefault("body", []).extend(parts.pop(pid))
            del hinge[pid]
            out.append(f"{pid}: {why}")
    return out


def motion(car, parts, height, rep, override=None):
    """Which doors SLIDE: an override, a name, or the van signature (rear
    doors >= 1.04x the front doors' height, vehicle >= 2.6 wheels tall:
    catches the Vito, none of 23 hinged cars). An MPV (Sharan) needs an
    override; never judge in metres (the catalogue's scale spread)."""
    override = override or {}
    mo = {}
    for pid in ("door_bl", "door_br"):
        if pid in parts:
            mo[pid] = {"type": "barn", "why": "door across the back of the vehicle"}
    wd = []
    for k in ("wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr"):
        if k in parts:
            b0, b1 = bbox(np.vstack([car.verts(o) for o in parts[k]]))
            wd.append(b1[1] - b0[1])
    wd = sum(wd) / len(wd) if wd else 0

    def dh(k):
        b0, b1 = bbox(np.vstack([car.verts(o) for o in parts[k]]))
        return b1[1] - b0[1], b1[2] - b0[2]
    fh = [dh(k)[0] for k in ("door_fl", "door_fr") if k in parts]
    fh = sum(fh) / len(fh) if fh else 0
    # the rear pair is judged together, as the front height is the pair's:
    # the Sprinter's left slider is modelled 30 cm taller than its right
    rh = [dh(k)[0] for k in ("door_rl", "door_rr") if k in parts]
    pair = sum(rh) / len(rh) / fh if rh and fh else 0
    sig = {}
    for pid in ("door_rl", "door_rr"):
        if pid not in parts:
            continue
        h, l = dh(pid)
        ratio = h / fh if fh else 0
        sig[pid] = {"rear_over_front": round(float(ratio), 3), "height_in_wheels": round(float(height / wd), 3) if wd else 0}
        forced = override.get(pid)
        if forced:
            if forced == "slide":
                mo[pid] = {"type": "slide", "out": 0.07, "back": round(float(0.82 * l), 3), "why": "override"}
            continue
        named = any(SLIDE_NAME.search(o["chain"]) for o in parts[pid])
        van = wd and fh and pair >= 1.04 and height / wd >= 2.6
        if named or van:
            mo[pid] = {"type": "slide", "out": 0.07, "back": round(float(0.82 * l), 3),
                       "why": "named sliding" if named else
                       f"van signature: rear doors {pair:.2f}x the front doors, vehicle {height / wd:.2f} wheels tall"}
    rep["door_signature"] = sig
    return mo


# ═════════════════════════════════════════════════════════════════════════
def export(car, parts, dst):
    """Write the parts as SB_<part>__<n> nodes, positions baked in the rig
    frame, every attribute carried; a cut door gets its dark inner card."""
    g = car.g
    j = g.j
    j["materials"] = car.mats
    inner = None
    meshes, nodes = [], [{"name": "car", "children": []}]
    for pid, os_ in parts.items():
        for k, o in enumerate(os_):
            prims = []
            for pi, t in o["segs"]:
                pr = car.prims[pi]
                I = pr["I"][t]
                uniq, inv = np.unique(I.ravel(), return_inverse=True)
                inv = inv.reshape(-1, 3)
                if pr["flip"]:
                    inv = inv[:, [0, 2, 1]]
                attrs = {}
                for an, ai in pr["prim"]["attributes"].items():
                    if an.startswith(("JOINTS", "WEIGHTS")):
                        continue
                    if an == "POSITION":
                        attrs[an] = g.add_accessor(pr["P"][uniq], minmax=True, target=34962)
                        continue
                    A = g.accessor(ai)[uniq].astype(np.float64)
                    if an == "NORMAL":
                        A = A @ pr["Nm"].T
                        A /= np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-12)
                    elif an == "TANGENT":
                        t3 = A[:, :3] @ pr["Tm"].T
                        t3 /= np.maximum(np.linalg.norm(t3, axis=1, keepdims=True), 1e-12)
                        A = np.c_[t3, A[:, 3:4] * (-1 if pr["flip"] else 1)]
                    attrs[an] = g.add_accessor(A, target=34962)
                prim = {"attributes": attrs, "mode": 4,
                        "indices": g.add_accessor(inv.ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)}
                if pr["mat"] is not None:
                    prim["material"] = pr["mat"]
                prims.append(prim)
                if o.get("card"):
                    # the door card: the skin offset inboard, wound the other way
                    sd, th = o["card"]
                    if inner is None:
                        car.mats.append({"name": "SB_door_inner", "pbrMetallicRoughness": {
                            "baseColorFactor": [0.045, 0.045, 0.05, 1], "roughnessFactor": 0.7, "metallicFactor": 0}})
                        inner = len(car.mats) - 1
                    Pc = pr["P"][uniq] - np.array([sd * th, 0, 0])
                    T3 = Pc[inv]
                    _, nn = tri_area_normal(T3[:, [0, 2, 1]])
                    Nv = np.zeros_like(Pc)
                    np.add.at(Nv, inv[:, [0, 2, 1]].ravel(), np.repeat(nn, 3, axis=0))
                    Nv /= np.maximum(np.linalg.norm(Nv, axis=1, keepdims=True), 1e-12)
                    prims.append({"attributes": {"POSITION": g.add_accessor(Pc, minmax=True, target=34962),
                                                 "NORMAL": g.add_accessor(Nv, target=34962)},
                                  "indices": g.add_accessor(inv[:, [0, 2, 1]].ravel().astype(np.uint32), ctype=5125,
                                                            atype="SCALAR", target=34963),
                                  "material": inner, "mode": 4})
            if not prims:
                continue
            meshes.append({"name": f"SB_{pid}__{k}", "primitives": prims})
            nodes.append({"name": f"SB_{pid}__{k}", "mesh": len(meshes) - 1})
            nodes[0]["children"].append(len(nodes) - 1)
    j["meshes"] = meshes
    j["nodes"] = nodes
    j["scenes"] = [{"name": "car", "nodes": [0]}]
    j["scene"] = 0
    for k in ("skins", "animations", "cameras"):
        j.pop(k, None)
    return g.save(dst)


def run(src, out, override=None, body_style=""):
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    rep = {"src": os.path.basename(src), "rigger": VERSION}
    res = {"car": "src", "src": os.path.basename(src), "rigger": VERSION, "body_style": body_style or ""}
    try:
        car = Car(src)
        parts, hinge = convert(car, rep, override, body_style)
        res["rig_seconds"] = round(time.time() - t0, 1)
        export(car, parts, os.path.join(out, "src.glb"))
        opens = [k for k in parts if k.startswith("door_")] + \
            [k.replace("panel_", "") for k in ("panel_bonnet", "tailgate") if k in hinge and k in parts]
        res.update(status="partial" if rep.get("missing") else "ok", opens=opens,
                   wheels=sorted(k for k in parts if k.startswith("wheel_")), missing=rep.get("missing", []),
                   motion=rep.get("motion", {}), rescaled=rep.get("rescaled"))
        if rep.get("hinges"):
            res["hinges"] = rep["hinges"]
    except Refused as e:
        rep["refused"] = res["refused"] = str(e)
        res["status"] = "refused"
    res["seconds"] = round(time.time() - t0, 1)
    json.dump(rep, open(os.path.join(out, "src.report.json"), "w"), indent=1, default=float)
    json.dump(res, open(os.path.join(out, "result.json"), "w"), indent=1, default=float)
    return res


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    body = next((x.split("=", 1)[1] for x in sys.argv if x.startswith("--body=")), "")
    r = run(a[0], a[1], body_style=body)
    print(json.dumps({k: r.get(k) for k in ("car", "status", "opens", "missing", "refused", "seconds", "body_style")}))
