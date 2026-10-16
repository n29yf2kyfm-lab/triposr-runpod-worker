#!/usr/bin/env python3
"""morph.py — reshape a master car into another car, and give it that car's face.

    python3 pipeline/template/morph.py MASTER.glb SPEC.json OUT.glb

A master is a properly built car: separate doors, bonnet and tailgate, clear
glass, a full cabin. Every car made from it inherits all of that, so the
output always opens and always shows a cabin behind clear glass — by
construction, not by repair.

SPEC.json (published figures in mm, photographs as background-removed PNGs):
    {"name": "Ford Fiesta Mk7", "length": 4040, "width": 1735, "height": 1483,
     "wheelbase": 2493, "wheel_d": 621,                  # track optional
     "front_photo": "fiesta_front.png", "rear_photo": "fiesta_rear.png",
     "side_profile": "polo_side.png",                    # optional, true side
     "paint": "auto" | [r, g, b] (linear 0-1),
     "engine_pack": "engine_pack.glb"}                   # optional
Relative paths are taken from the spec file's folder.

1. SHAPE. A smooth warp in the master's frame (y up, nose +z, the car's
   left +x): along the car through the tail, both arches and the nose (the
   target's overhangs and wheelbase, each arch kept at the wheel's scale so it
   stays round); up the car, the wheel's scale below the arch tops and the
   target's roofline above (its side photograph if given, else its height);
   across, the published width. Wheels, tyres, discs and calipers move rigidly
   to the new axles and track. Normals and tangents go through the warp's
   Jacobian.
2. IDENTITY. The master's own wheels, light signatures and model badges are
   taken off (plain five-spoke alloys from kit.py go on). Each photograph's
   camera is found by fitting the car's outline to it (photoproj.py); every
   outside triangle that faces a camera, is not hidden behind another part
   and lands on the car in that photograph takes its colour from it, and the
   far side takes the mirror image. The paint is the photographs' own colour.
3. ENGINE. An engine pack in the master's frame (the petrol bay exported
   from the workshop) is merged and warped with the car.
4. RIG. Doors, bonnet and tailgate hang from pivot nodes on their hinge edges
   and the file carries glTF animation clips (door_FL_open … tailgate_open,
   doors_open, all_open) that any viewer can play.
"""
import io
import json
import math
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import gaussian_filter1d

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gltf import GLTF  # noqa: E402
import kit  # noqa: E402
import photoproj as pp  # noqa: E402

GROUPS = [  # first match wins, on the node name
    ("bay", r"^bay:"),
    ("wheel_FL", r"(Tire|Rim)_FL|Brake_FL"),
    ("wheel_FR", r"(Tire|Rim)_FR|Brake_FR"),
    ("wheel_RL", r"(Tire|Rim)_RL"),
    ("wheel_RR", r"(Tire|Rim)_RR"),
    ("wheel_rear", r"Brake_Rear"),
    ("door_FL", r"Door_FL|Mirror_FL"),
    ("door_FR", r"Door_FR"),
    ("door_RL", r"Door_RL"),
    ("door_RR", r"Door_RR"),
    ("tailgate", r"Trunk_Lid(?!_Hyd)"),
    ("bonnet", r"Panel_Bonnet"),
]
HINGED = {"door_FL": -65, "door_FR": 65, "door_RL": -65, "door_RR": 65, "bonnet": -55, "tailgate": 75}
# the master's identity, taken off every car made from it
HIDE = re.compile(r"^Rim_|Glow_|GTI_Badge")
NEUTRAL = {"leather_Red": [0.045, 0.045, 0.05], "Red_ST": [0.12, 0.12, 0.12], "fabric": [0.06, 0.06, 0.065]}
# outside surfaces a photograph may paint
OUTSIDE = re.compile(r"^(Ext|ExtBody|Panel_|Asm_)(?!.*(Brake|Limiter|Glass|Window|Windows|Glow|Hyd))")


def group_of(name):
    for g, rx in GROUPS:
        if re.search(rx, name):
            return g
    return "body"


def collect(g):
    W, parent = g.world_matrices()
    out = []
    for i, n in enumerate(g.j["nodes"]):
        if "mesh" not in n:
            continue
        name = n.get("name") or ""
        if i in parent and g.j["nodes"][parent[i]].get("name", "").startswith("G:"):
            name = g.j["nodes"][parent[i]]["name"]
        name = re.sub(r"^G:", "", name)
        name = re.sub(r"_DefaultOBJ.*$", "", name)
        M = W[i]
        prims = []
        for p in g.j["meshes"][n["mesh"]]["primitives"]:
            v = g.accessor(p["attributes"]["POSITION"])
            prims.append((p, (np.c_[v, np.ones(len(v))] @ M.T)[:, :3]))
        out.append({"node": i, "mesh": n["mesh"], "name": name, "group": group_of(name), "M": M, "prims": prims})
    return out


def measure(parts):
    def verts(pred):
        vs = [v for pt in parts if pred(pt) for _, v in pt["prims"]]
        return np.vstack(vs) if vs else np.zeros((0, 3))
    car = verts(lambda pt: pt["group"] != "bay")
    tyres = {c: verts(lambda pt, c=c: pt["group"] == "wheel_" + c and "Tire" in pt["name"]) for c in ("FL", "FR", "RL", "RR")}
    gy = min(t[:, 1].min() for t in tyres.values())
    R = np.mean([(t[:, 1].max() - t[:, 1].min()) / 2 for t in tyres.values()])
    centre = {c: np.array([(t[:, 0].min() + t[:, 0].max()) / 2, gy + R, (t[:, 2].min() + t[:, 2].max()) / 2])
              for c, t in tyres.items()}
    t = tyres["FL"]
    rad = np.hypot(t[:, 1] - centre["FL"][1], t[:, 2] - centre["FL"][2])
    body = verts(lambda pt: pt["group"] == "body" and "Car_Paint" in pt["name"])
    zf = (centre["FL"][2] + centre["FR"][2]) / 2
    zr = (centre["RL"][2] + centre["RR"][2]) / 2
    ext = verts(lambda pt: pt["name"].startswith("Ext") or pt["group"] in ("bonnet", "tailgate"))
    z0, z1 = car[:, 2].min(), car[:, 2].max()
    bins = np.arange(z0, z1 + 0.01, 0.01)
    idx = np.clip(((ext[:, 2] - z0) / 0.01).astype(int), 0, len(bins) - 1)
    top = np.full(len(bins), -np.inf)
    np.maximum.at(top, idx, ext[:, 1] - gy)
    ok = np.isfinite(top)
    top = gaussian_filter1d(np.interp(bins, bins[ok], top[ok]), 2)
    return {"ground": float(gy), "R": float(R), "zf": float(zf), "zr": float(zr), "zmin": float(z0), "zmax": float(z1),
            "W": float(body[:, 0].max() - body[:, 0].min()), "H": float(car[:, 1].max() - gy),
            "track": float(abs(centre["FL"][0] - centre["FR"][0])), "centre": centre,
            "tyre_inner": float(np.percentile(rad, 2)), "tyre_width": float(np.ptp(t[:, 0])),
            "roof_z": bins, "roof": top}


def side_profile(path, spec):
    sys.path.insert(0, os.path.join(HERE, "..", "forge"))
    from trace import load_cutout, trace_side
    rgb, mask = load_cutout(path)
    d = {k: spec[k] for k in ("length", "width", "height", "wheelbase")}
    d["wheel_d"] = spec.get("wheel_d", 620)
    s = trace_side(rgb, mask, d)
    return s["u"], s["roof"], s["u_front"], s["u_rear"]


def build_warp(m, spec, log):
    L_t, W_t, H_t, WB_t = (spec[k] / 1000.0 for k in ("length", "width", "height", "wheelbase"))
    R_t = spec.get("wheel_d", m["R"] * 2000 * (L_t / (m["zmax"] - m["zmin"]))) / 2000.0
    s_r = R_t / m["R"]
    track_t = spec.get("track", m["track"] * 1000 * W_t / m["W"]) / 1000.0
    sx = W_t / m["W"]
    OF_m, OR_m = m["zmax"] - m["zf"], m["zr"] - m["zmin"]
    prof = None
    OF_t = (L_t - WB_t) * OF_m / (OF_m + OR_m)
    log["overhangs"] = "master ratio (no side photo)"
    if spec.get("side_profile") and os.path.exists(spec["side_profile"]):
        u, roof, uf, ur = side_profile(spec["side_profile"], spec)
        mid = (uf + ur) / 2
        of = (1 - (mid + WB_t / L_t / 2)) * L_t
        if 0.4 * (L_t - WB_t) / 2 < of < 1.6 * (L_t - WB_t) / 2:
            OF_t, prof = of, (u, roof)
            log["overhangs"] = "side photo"
        else:
            log["overhangs"] = "side photo's split implausible; master ratio used"
    OR_t = L_t - WB_t - OF_t
    zmid = (m["zf"] + m["zr"]) / 2
    zf_t, zr_t = zmid + WB_t / 2, zmid - WB_t / 2
    a = 1.25 * m["R"]
    src = [m["zmin"], m["zr"] - a, m["zr"] + a, m["zf"] - a, m["zf"] + a, m["zmax"]]
    dst = [zr_t - OR_t, zr_t - a * s_r, zr_t + a * s_r, zf_t - a * s_r, zf_t + a * s_r, zf_t + OF_t]
    Z = PchipInterpolator(src, dst, extrapolate=True)
    hb, bw = 2.2 * m["R"], 0.06
    a_, c_ = hb - bw, hb + bw
    H_m = m["H"]
    k_glob = s_r + (H_t - s_r * H_m) / (bw + H_m - c_)
    zs, roof_m = m["roof_z"], m["roof"]
    if prof is not None:
        u, roof = prof
        ut = (Z(zs) - (zr_t - OR_t)) / L_t
        R_tgt = np.interp(ut, u, roof)
        k = s_r + (R_tgt - s_r * roof_m) / np.maximum(bw + roof_m - c_, 1e-6)
        w = np.clip((roof_m - c_ - 0.08) / 0.12, 0, 1)
        k = gaussian_filter1d(np.clip(w * k + (1 - w) * k_glob, 0.6, 1.5), 6)
    else:
        k = np.full(len(zs), k_glob)
    gy = m["ground"]

    def I(u_):
        return u_ ** 3 - u_ ** 4 / 2

    def f(P):
        x, y, z = P[:, 0], P[:, 1], P[:, 2]
        h = y - gy
        kz = np.interp(z, zs, k)
        t = np.clip((h - a_) / (2 * bw), 0, 1)
        extra = np.where(h <= a_, 0.0, np.where(h < c_, 2 * bw * I(t), bw + (h - c_)))
        return np.c_[x * sx, gy + s_r * h + (kz - s_r) * extra, Z(z)]

    wheels = {}
    for c, cm in m["centre"].items():
        sign = 1 if cm[0] > 0 else -1
        wheels[c] = (cm, np.array([sign * track_t / 2, gy + R_t, zf_t if c[0] == "F" else zr_t]))
    log.update({"s_wheel": round(s_r, 4), "sx": round(sx, 4), "k_roof_global": round(float(k_glob), 4),
                "overhang_front_m": round(OF_t, 3), "overhang_rear_m": round(OR_t, 3),
                "track_m": round(track_t, 3), "wheel_d_m": round(2 * R_t, 3)})
    return f, wheels, s_r


def jac_normals(f, P, N, T=None, h=1e-3):
    J = np.empty((len(P), 3, 3))
    for i in range(3):
        d = np.zeros(3)
        d[i] = h
        J[:, :, i] = (f(P + d) - f(P - d)) / (2 * h)
    out_n = out_t = None
    if N is not None:
        n = np.einsum("nij,nj->ni", np.linalg.inv(J).transpose(0, 2, 1), N)
        out_n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    if T is not None:
        t = np.einsum("nij,nj->ni", J, T[:, :3])
        out_t = np.c_[t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12), T[:, 3:4]]
    return out_n, out_t


def quat(axis, deg):
    a = np.array(axis, float) / np.linalg.norm(axis)
    s = math.sin(math.radians(deg) / 2)
    return [float(a[0] * s), float(a[1] * s), float(a[2] * s), float(math.cos(math.radians(deg) / 2))]


def add_image_material(g, name, jpeg, base=None):
    j = g.j
    while (len(g.bin) + len(g.extra)) % 4:
        g.extra += b"\0"
    j["bufferViews"].append({"buffer": 0, "byteOffset": len(g.bin) + len(g.extra), "byteLength": len(jpeg)})
    g.extra += jpeg
    j.setdefault("images", []).append({"bufferView": len(j["bufferViews"]) - 1, "mimeType": "image/jpeg", "name": name})
    j.setdefault("samplers", []).append({"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071})
    j.setdefault("textures", []).append({"source": len(j["images"]) - 1, "sampler": len(j["samplers"]) - 1})
    mat = {"name": name, "pbrMetallicRoughness": {"baseColorTexture": {"index": len(j["textures"]) - 1},
                                                  "metallicFactor": 0.15, "roughnessFactor": 0.32},
           "extensions": {"KHR_materials_clearcoat": {"clearcoatFactor": 1.0, "clearcoatRoughnessFactor": 0.04}}}
    j["materials"].append(mat)
    used = set(j.get("extensionsUsed", []))
    used.add("KHR_materials_clearcoat")
    j["extensionsUsed"] = sorted(used)
    return len(j["materials"]) - 1


def depth_buffer(tris, cam, W, H):
    """Nearest depth per pixel, by drawing triangles far to near with their
    index as colour (a painter's z-buffer; PIL only)."""
    xy, z, _ = pp.project(tris.reshape(-1, 3), cam, W, H)
    xy, z = xy.reshape(-1, 3, 2), z.reshape(-1, 3).mean(1)
    order = np.argsort(-z)
    im = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    for i in order:
        if z[i] <= 0.1:
            continue
        dr.polygon([tuple(p) for p in xy[i]], fill=(int(i) & 255, (int(i) >> 8) & 255, (int(i) >> 16) & 255))
    a = np.asarray(im).astype(np.int64)
    ids = a[:, :, 0] | (a[:, :, 1] << 8) | (a[:, :, 2] << 16)
    dep = np.full((H, W), np.inf)
    hit = ids != 0xFFFFFF
    dep[hit] = z[ids[hit]]
    return dep


def morph(master, spec, out, base_dir="."):
    def path(k):
        v = spec.get(k)
        return os.path.join(base_dir, v) if v and not os.path.isabs(v) else v
    for k in ("front_photo", "rear_photo", "side_profile", "engine_pack"):
        if spec.get(k):
            spec[k] = path(k)
    g = GLTF(master)
    log = {"master": os.path.basename(master), "target": spec.get("name")}
    if spec.get("engine_pack"):
        g.append(GLTF(spec["engine_pack"]))
        log["engine_pack"] = os.path.basename(spec["engine_pack"])
    parts = collect(g)
    m = measure(parts)
    log["master_measured"] = {"length_m": round(m["zmax"] - m["zmin"], 3), "width_m": round(m["W"], 3),
                              "height_m": round(m["H"], 3), "wheelbase_m": round(m["zf"] - m["zr"], 3),
                              "track_m": round(m["track"], 3), "wheel_d_m": round(2 * m["R"], 3)}
    f, wheels, s_r = build_warp(m, spec, log)

    # ── pass 1: warp everything ──
    recs = []
    for pt in parts:
        hidden = bool(HIDE.search(pt["name"]))
        Mn = np.linalg.inv(pt["M"][:3, :3]).T
        for p, Pw in pt["prims"]:
            at = p["attributes"]
            N = g.accessor(at["NORMAL"]) @ Mn.T if "NORMAL" in at else None
            if N is not None:
                N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            T = g.accessor(at["TANGENT"]) if "TANGENT" in at else None
            if T is not None:
                T = np.c_[T[:, :3] @ pt["M"][:3, :3].T, T[:, 3:4]]
            if pt["group"].startswith("wheel"):
                cs = list(wheels.values())
                d = np.stack([np.linalg.norm(Pw[:, [0, 2]] - cm[[0, 2]], axis=1) for cm, _ in cs], 1)
                near = d.argmin(1)
                newP = np.empty_like(Pw)
                for wi, (cm, ct) in enumerate(cs):
                    sel = near == wi
                    newP[sel] = ct + s_r * (Pw[sel] - cm)
                newN, newT = N, T
            else:
                newP = f(Pw)
                newN, newT = jac_normals(f, Pw, N, T)
            recs.append({"pt": pt, "p": p, "P": newP, "N": newN, "T": newT, "hidden": hidden})

    # ── paint colour ──
    paint_srgb = None
    photos = {k: spec.get(k + "_photo") for k in ("front", "rear") if spec.get(k + "_photo")}
    if spec.get("paint") == "auto" and photos:
        paint_srgb = np.mean([pp.body_colour(v) for v in photos.values()], axis=0)
        spec["paint"] = [float(c) for c in pp.srgb_to_linear(paint_srgb)]
        log["paint_srgb"] = [int(round(c)) for c in paint_srgb]
    elif spec.get("paint"):
        lin = np.array(spec["paint"], float)
        paint_srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055) * 255

    # ── identity: cameras for the photographs ──
    cams = {}
    if photos:
        fit_tris, occ_tris = [], []
        for r in recs:
            if r["hidden"] or r["pt"]["group"] == "bay":
                continue
            if not r["pt"]["name"].startswith(("Ext", "ExtBody", "Panel_", "Asm_", "Tire")):
                continue
            idx = g.accessor(r["p"]["indices"]).reshape(-1, 3) if "indices" in r["p"] else np.arange(len(r["P"])).reshape(-1, 3)
            t = r["P"][idx]
            mat = g.j["materials"][r["p"]["material"]] if "material" in r["p"] else {}
            # the outline includes the glass (a photograph's cut-out does);
            # what can hide paint from the camera does not (paint behind glass
            # is not seen through it anyway)
            fit_tris.append(t)
            if mat.get("alphaMode") != "BLEND":
                occ_tris.append(t)
        fit = np.concatenate(fit_tris)
        occ = np.concatenate(occ_tris)
        for view, ph in photos.items():
            a = np.asarray(Image.open(ph).convert("RGBA"))
            mask = a[:, :, 3] > 128
            cam = pp.fit_camera(fit, mask, view, log)
            cam.pop("overlay").save(os.path.splitext(out)[0] + f".fit_{view}.png")
            jpeg, (TW, TH), tmask = pp.photo_texture(ph, paint_srgb if paint_srgb is not None else (180, 180, 180))
            DW = 900
            DH = int(round(TH * DW / TW))
            cams[view] = {"cam": cam, "jpeg": jpeg, "W": TW, "H": TH, "mask": tmask,
                          "depth": depth_buffer(occ, cam, DW, DH), "DW": DW, "DH": DH}
            cams[view]["material"] = add_image_material(g, "Photo_" + view, jpeg)
        log["photos"] = {k: os.path.basename(v) for k, v in photos.items()}

    def options(P, tri):
        """Per triangle: best (view, mirrored) by how squarely it faces a
        camera, among those where it is visible and lands on the car."""
        c = P[tri].mean(1)
        n = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        best = np.full(len(tri), -1)
        score = np.full(len(tri), 0.18)
        k = 0
        keys = []
        for view, cv in cams.items():
            for mir in (False, True):
                cc = c * ([-1, 1, 1] if mir else 1)
                nn = n * ([-1, 1, 1] if mir else 1)
                xy, z, C = pp.project(cc, cv["cam"], cv["W"], cv["H"])
                v = cc - C
                v /= np.linalg.norm(v, axis=1, keepdims=True)
                facing = -(nn * v).sum(1)
                ix = np.clip(xy[:, 0].astype(int), 0, cv["W"] - 1)
                iy = np.clip(xy[:, 1].astype(int), 0, cv["H"] - 1)
                inside = cv["mask"][iy, ix] & (xy[:, 0] >= 0) & (xy[:, 0] < cv["W"]) & (xy[:, 1] >= 0) & (xy[:, 1] < cv["H"])
                dx = np.clip((xy[:, 0] * cv["DW"] / cv["W"]).astype(int), 0, cv["DW"] - 1)
                dy = np.clip((xy[:, 1] * cv["DH"] / cv["H"]).astype(int), 0, cv["DH"] - 1)
                visible = cv["depth"][dy, dx] >= z - 0.05
                sc = facing + (0.06 if not mir else 0.0)
                ok = inside & visible & (facing > 0.18) & (sc > score)
                best[ok] = k
                score[ok] = sc[ok]
                keys.append((view, mir))
                k += 1
        return best, keys

    # ── pass 2: write ──
    for r in recs:
        p, at = r["p"], r["p"]["attributes"]
        at["POSITION"] = g.add_accessor(r["P"], minmax=True, target=34962)
        if r["N"] is not None:
            at["NORMAL"] = g.add_accessor(r["N"], target=34962)
        if r["T"] is not None:
            at["TANGENT"] = g.add_accessor(r["T"], target=34962)
        mat = g.j["materials"][p["material"]] if "material" in p else {}
        if not cams or r["hidden"] or mat.get("alphaMode") == "BLEND" or not OUTSIDE.search(r["pt"]["name"]) \
                or "indices" not in p or r["pt"]["group"].startswith("wheel"):
            continue
        tri = g.accessor(p["indices"]).reshape(-1, 3).astype(np.int64)
        best, keys = options(r["P"], tri)
        if (best < 0).all():
            continue
        new_prims = []
        for k, (view, mir) in enumerate(keys):
            sel = best == k
            if not sel.any():
                continue
            cv = cams[view]
            Pm = r["P"] * ([-1, 1, 1] if mir else 1)
            xy, _, _ = pp.project(Pm, cv["cam"], cv["W"], cv["H"])
            uv = np.c_[xy[:, 0] / cv["W"], xy[:, 1] / cv["H"]]
            np_ = {"attributes": {"POSITION": at["POSITION"], **({"NORMAL": at["NORMAL"]} if "NORMAL" in at else {}),
                                  "TEXCOORD_0": g.add_accessor(uv, target=34962)},
                   "indices": g.add_accessor(tri[sel].ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963),
                   "material": cv["material"], "mode": 4}
            new_prims.append(np_)
        rest = tri[best < 0]
        if len(rest):
            p["indices"] = g.add_accessor(rest.ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)
            g.j["meshes"][r["pt"]["mesh"]]["primitives"].extend(new_prims)
        else:
            prims = g.j["meshes"][r["pt"]["mesh"]]["primitives"]
            prims.remove(p)
            prims.extend(new_prims)

    # ── kit wheels in place of the master's ──
    j = g.j
    kit_meshes = {}
    mats = {}
    for nm, col, met, rough in (("Kit_Alloy", [0.62, 0.63, 0.65], 1.0, 0.26), ("Kit_Barrel", [0.18, 0.18, 0.19], 0.8, 0.45),
                                ("Kit_Cap", [0.30, 0.30, 0.32], 0.9, 0.35)):
        j["materials"].append({"name": nm, "pbrMetallicRoughness": {"baseColorFactor": col + [1.0], "metallicFactor": met,
                                                                     "roughnessFactor": rough}})
        mats[nm] = len(j["materials"]) - 1
    r_rim = m["tyre_inner"] * s_r * 1.01
    wdt = m["tyre_width"] * s_r * 0.86
    wk = kit.alloy_wheel(r_rim, wdt)
    for c, (cm, ct) in wheels.items():
        side = 1 if ct[0] > 0 else -1
        prims = []
        for part, mn in (("face", "Kit_Alloy"), ("barrel", "Kit_Barrel"), ("cap", "Kit_Cap")):
            V, N, F = kit.place(wk[part], ct, side)
            prims.append({"attributes": {"POSITION": g.add_accessor(V, minmax=True, target=34962),
                                         "NORMAL": g.add_accessor(N, target=34962)},
                          "indices": g.add_accessor(F.ravel(), ctype=5125, atype="SCALAR", target=34963),
                          "material": mats[mn], "mode": 4})
        j["meshes"].append({"name": "kit_wheel_" + c, "primitives": prims})
        kit_meshes[c] = len(j["meshes"]) - 1
    log["wheels"] = {"kit": "five-spoke alloy, plain cap", "rim_d_m": round(2 * r_rim, 3), "rim_w_m": round(wdt, 3)}

    # ── node tree: world space, hinged parts on pivots ──
    nodes = [{"name": spec.get("name") or "car", "children": []}]
    groups = {}
    verts_by_group = {}
    for r in recs:
        if not r["hidden"]:
            verts_by_group.setdefault(r["pt"]["group"], []).append(r["P"])
    for gname in sorted(verts_by_group):
        if gname in HINGED:
            V = np.vstack(verts_by_group[gname])
            lo, hi = V.min(0), V.max(0)
            if gname.startswith("door"):
                left = (lo[0] + hi[0]) / 2 > 0
                piv = [float(hi[0] - 0.02 if left else lo[0] + 0.02), float((lo[1] + hi[1]) / 2), float(hi[2] - 0.03)]
                axis = [0, 1, 0]
            elif gname == "tailgate":
                piv, axis = [0.0, float(hi[1] - 0.01), float(hi[2] - 0.01)], [1, 0, 0]
            else:
                piv, axis = [0.0, float(hi[1] - 0.01), float(lo[2] + 0.02)], [1, 0, 0]
            pivot = len(nodes)
            nodes.append({"name": gname + "_hinge", "translation": piv, "children": [pivot + 1],
                          "extras": {"axis": axis, "open_deg": HINGED[gname]}})
            nodes.append({"name": gname, "translation": [-c for c in piv], "children": []})
            nodes[0]["children"].append(pivot)
            groups[gname] = pivot + 1
            groups[gname + "_pivot"] = (pivot, axis, HINGED[gname])
        else:
            gi = len(nodes)
            nodes.append({"name": gname, "children": []})
            nodes[0]["children"].append(gi)
            groups[gname] = gi
    seen = set()
    for r in recs:
        pt = r["pt"]
        if r["hidden"] or pt["node"] in seen:
            continue
        seen.add(pt["node"])
        ni = len(nodes)
        nodes.append({"name": pt["name"], "mesh": pt["mesh"]})
        nodes[groups[pt["group"]]]["children"].append(ni)
    for c, mi in kit_meshes.items():
        gname = "wheel_" + c if "wheel_" + c in groups else "body"
        ni = len(nodes)
        nodes.append({"name": "kit_wheel_" + c, "mesh": mi})
        nodes[groups[gname]]["children"].append(ni)
    # meshes no node uses any more (the master's rims, glows, badges) go
    used = {n["mesh"] for n in nodes if "mesh" in n}
    remap, meshes = {}, []
    for i, me in enumerate(j["meshes"]):
        if i in used:
            remap[i] = len(meshes)
            meshes.append(me)
    j["meshes"] = meshes
    for n in nodes:
        if "mesh" in n:
            n["mesh"] = remap[n["mesh"]]
    j["nodes"] = nodes
    j["scenes"] = [{"name": spec.get("name") or "car", "nodes": [0]}]
    j["scene"] = 0

    # ── animation clips ──
    tin = g.add_accessor(np.array([0.0, 1.0]), minmax=True)
    clips = {}
    for gname, val in groups.items():
        if not gname.endswith("_pivot"):
            continue
        pivot, axis, deg = val
        part = gname[:-6]
        q = g.add_accessor(np.array([[0, 0, 0, 1], quat(axis, deg)]))
        clips.setdefault(part + "_open", []).append((pivot, q))
        if part.startswith("door"):
            clips.setdefault("doors_open", []).append((pivot, q))
        clips.setdefault("all_open", []).append((pivot, q))
    j["animations"] = [{"name": nm, "samplers": [{"input": tin, "output": q, "interpolation": "LINEAR"} for _, q in ch],
                        "channels": [{"sampler": i, "target": {"node": pv, "path": "rotation"}} for i, (pv, _) in enumerate(ch)]}
                       for nm, ch in clips.items()]

    # ── materials: paint and a neutral cabin ──
    for mat in j["materials"]:
        if mat.get("name") == "CarPaint" and spec.get("paint"):
            mat.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = list(spec["paint"]) + [1.0]
        if mat.get("name") in NEUTRAL:
            pbr = mat.setdefault("pbrMetallicRoughness", {})
            pbr.pop("baseColorTexture", None)
            pbr["baseColorFactor"] = NEUTRAL[mat["name"]] + [1.0]
    j.setdefault("asset", {}).setdefault("extras", {})["template_morph"] = log
    log["bytes"] = g.save(out)
    return log


if __name__ == "__main__":
    master, spec_p, out = sys.argv[1:4]
    spec = json.load(open(spec_p))
    print(json.dumps(morph(master, spec, out, os.path.dirname(os.path.abspath(spec_p))), indent=1, default=float))
