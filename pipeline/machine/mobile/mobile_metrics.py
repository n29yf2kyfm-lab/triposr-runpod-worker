#!/usr/bin/env python3
"""
mobile_metrics.py -- everything about a GLB that decides whether a phone can
serve it, measured from the file. No browser, no GPU, no network.

    python3 pipeline/machine/mobile/mobile_metrics.py car.glb --json m.json

WHY A SEPARATE MODULE FROM mobile_export.describe()
---------------------------------------------------
`mobile_export.describe()` answers "what does this file weigh". That was the
right question for the Golf MASTER it was written against, which is
TEXTURE-MAJORITY (37.35 MB of PNG against 27.77 MB of geometry). Its whole
strategy -- resize, WebP, dedup image bufferViews -- follows from that one fact.

`car_rebound.glb` is the opposite file. Measured: 28,674,996 payload bytes,
**0 images, 0 textures, 100.0% geometry**. Gate 7+8 deliberately dropped the
baked-lighting atlas. So every texture stage in mobile_export is a NO-OP here,
the +12.70 MB Draco image-duplication trap CANNOT fire (there are no images to
un-share), and the only levers left are triangles, index width and codec.

That inversion is exactly why this had to be measured rather than assumed, and
it is why this module reports the payload split FIRST: it is the fact that
selects the strategy, and it flips between cars.

WHAT IS MEASURED, AND WHY EACH ONE IS A MOBILE CONSTRAINT
---------------------------------------------------------
  sizeBytes ......... bytes over a mobile link. The dominant term in
                      time-to-first-frame on anything slower than wifi.
  drawCalls ......... one per primitive. Per-frame CPU cost in the browser's
                      renderer. NOTE: on this programme it is ALSO a floor, not
                      just a ceiling -- the viewer toggles components by node,
                      so primitives may not be merged away.
  triangles ......... per-frame vertex cost, and the thing decimation moves.
  vertices .......... post-transform vertex cache pressure; also the real driver
                      of the vertex-buffer bytes below.
  gpuBufferBytes .... EXACT bytes the driver must hold resident, computed from
                      the decoded accessors (positions + normals + UVs +
                      indices). Compression changes the DOWNLOAD, not this.
                      A 3.65 MB Draco file still uploads ~28 MB to the GPU.
                      Reporting only the compressed size hides that entirely.
  textureTexels ..... width*height summed over unique images. Zero here.
  normalCoverage .... primitives carrying a NORMAL accessor / total. CLAUDE.md
                      2026-08-16 v7: trimesh submesh exports DROP normals and
                      the studio clearcoat renders that as crumpled foil, and
                      THREE eye audits blamed the generator for a shading bug.
                      Anything below 1.0 is a hard defect.
  imageViewSharing .. images / unique image bufferViews. <1.0 means images share
                      views and a buffer-rewriting stage can un-share them --
                      the measured +12.70 MB Draco inflation. Guard, not a stat.
  perMaterial ....... triangles, vertices and SURFACE AREA per material.
                      Area, not face count: CLAUDE.md 2026-08-19 measured glass
                      faces 1.58x smaller than body faces on a generated mesh,
                      so counting faces mis-states a "share of the car". This
                      census is the input to the geometry-retention check that
                      catches a decimator quietly welding a glass pane shut --
                      a defect `glass_probe` is structurally blind to, because
                      it reads the MATERIAL TABLE and the material table does
                      not change when the geometry under it disappears.
  groundContact ..... per-tyre-node world-space minimum Y. A whole-model bbox
                      min-Y is NOT this: it passes as long as ANY single vertex
                      touches the floor, so three wheels can be in the air and
                      the model still reads "grounded".

RAW vs WORLD EXTENTS -- read this before quoting a dimension
------------------------------------------------------------
Node transforms matter. On car_rebound.glb the four wheel nodes carry
translations, so the union of RAW (untransformed) vertex bounds gives
4.2825 x 1.7798 x 1.7887 while the true WORLD bounds are
4.2825 x 1.4554 x 1.7887. The raw height is 22% too tall and is not a dimension
of anything -- it unions the wheels' local boxes with the body's world box.
Both are reported, and `extents` (the one to quote) is the WORLD one.
"""

import argparse
import json
import os
import re
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # pipeline/machine

COMP = {5120: (np.int8, 1), 5121: (np.uint8, 1), 5122: (np.int16, 2),
        5123: (np.uint16, 2), 5125: (np.uint32, 4), 5126: (np.float32, 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

TYRE_NODE = re.compile(r"tyre|tire", re.I)
COMPRESSED_EXT = ("KHR_draco_mesh_compression", "EXT_meshopt_compression")


def glb_read(path):
    with open(path, "rb") as fh:
        magic, _ver, total = struct.unpack("<III", fh.read(12))
        if magic != 0x46546C67:
            raise ValueError("not a GLB: %s" % path)
        js, bin_ = None, b""
        while fh.tell() < total:
            clen, ctype = struct.unpack("<II", fh.read(8))
            data = fh.read(clen)
            if ctype == 0x4E4F534A:
                js = json.loads(data.decode("utf-8"))
            elif ctype == 0x004E4942:
                bin_ = data
    return js, bin_


def glb_write(path, js, bin_):
    jb = json.dumps(js, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bb = bin_ + b"\x00" * ((4 - len(bin_) % 4) % 4)
    total = 12 + 8 + len(jb) + (8 + len(bb) if bb else 0)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(jb), 0x4E4F534A)); fh.write(jb)
        if bb:
            fh.write(struct.pack("<II", len(bb), 0x004E4942)); fh.write(bb)


def read_accessor(js, bin_, idx):
    a = js["accessors"][idx]
    if "bufferView" not in a:
        raise KeyError("accessor %d has no bufferView (compressed or sparse)" % idx)
    bv = js["bufferViews"][a["bufferView"]]
    dt, sz = COMP[a["componentType"]]
    n = NCOMP[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or (sz * n)
    if stride == sz * n:
        arr = np.frombuffer(bin_, dtype=dt, count=a["count"] * n, offset=off)
    else:
        raw = np.frombuffer(bin_, dtype=np.uint8, count=a["count"] * stride, offset=off)
        arr = raw.reshape(a["count"], stride)[:, :sz * n].copy().view(dt).ravel()
    return arr.reshape(a["count"], n) if n > 1 else arr


def is_compressed(js):
    return [e for e in js.get("extensionsUsed", []) if e in COMPRESSED_EXT]


def node_world_translations(js):
    """name -> world translation, walking the scene graph.

    Rotation and scale are handled too; this project's own stages BAKE instance
    transforms (CLAUDE.md 2026-08-19: "measure from TRANSFORMED VERTICES, never
    the graph"), so most files carry identity here -- but a file that does not
    must still be measured correctly rather than measured as if it did.
    """
    out = {}

    def mat(n):
        if "matrix" in n:
            return np.array(n["matrix"], dtype=float).reshape(4, 4).T
        M = np.eye(4)
        if "scale" in n:
            M[:3, :3] = M[:3, :3] @ np.diag(n["scale"])
        if "rotation" in n:
            x, y, z, w = n["rotation"]
            R = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            M[:3, :3] = R @ M[:3, :3]
        if "translation" in n:
            M[:3, 3] = n["translation"]
        return M

    scene = js.get("scenes", [{}])[js.get("scene", 0)]

    def walk(i, parent):
        n = js["nodes"][i]
        M = parent @ mat(n)
        out[i] = M
        for c in n.get("children", []):
            walk(c, M)

    for r in scene.get("nodes", []):
        walk(r, np.eye(4))
    return out


def measure(path, geometry=True):
    """Full metric block for one GLB.

    `geometry=False` skips the per-material area census, which needs decoded
    accessors and is therefore impossible on a Draco/meshopt file without a
    decode pass. That is not a silent degradation: `geometryDecoded` records
    whether the census ran, so a caller cannot mistake "not measured" for zero.
    """
    js, bin_ = glb_read(path)
    m = {"path": os.path.abspath(path), "sizeBytes": os.path.getsize(path)}
    m["generator"] = (js.get("asset") or {}).get("generator")
    m["extensionsUsed"] = js.get("extensionsUsed", [])
    m["extensionsRequired"] = js.get("extensionsRequired", [])
    m["compression"] = is_compressed(js)

    mats = js.get("materials", [])
    m["materialNames"] = [x.get("name") for x in mats]
    m["materials"] = len(mats)
    m["nodes"] = len(js.get("nodes", []))
    m["nodeNames"] = [n.get("name") for n in js.get("nodes", [])]

    # ---- draw calls, triangles, vertices, attribute set -------------------
    prims, tris, verts, with_normal, with_uv = 0, 0, 0, 0, 0
    idx_widths, prim_rows = {}, []
    for mi, mesh in enumerate(js.get("meshes", [])):
        for p in mesh["primitives"]:
            prims += 1
            attrs = p["attributes"]
            nv = js["accessors"][attrs["POSITION"]]["count"]
            verts += nv
            if "indices" in p:
                ia = js["accessors"][p["indices"]]
                nt = ia["count"] // 3
                w = {5121: 8, 5123: 16, 5125: 32}.get(ia["componentType"], 0)
                idx_widths[w] = idx_widths.get(w, 0) + ia["count"]
            else:
                nt, w = nv // 3, 0
            tris += nt
            if "NORMAL" in attrs:
                with_normal += 1
            if "TEXCOORD_0" in attrs:
                with_uv += 1
            prim_rows.append({
                "mesh": mi, "meshName": mesh.get("name"),
                "material": mats[p["material"]].get("name") if "material" in p else None,
                "triangles": nt, "vertices": nv,
                "attributes": sorted(attrs), "mode": p.get("mode", 4)})
    m["drawCalls"] = prims
    m["triangles"] = tris
    m["vertices"] = verts
    m["primitives"] = prim_rows
    m["normalCoverage"] = round(with_normal / prims, 4) if prims else 0.0
    m["normalPrimitives"] = "%d/%d" % (with_normal, prims)
    m["uvPrimitives"] = "%d/%d" % (with_uv, prims)
    m["indexBitsHistogram"] = {str(k): v for k, v in sorted(idx_widths.items())}

    # ---- payload split ----------------------------------------------------
    bvs = js.get("bufferViews", [])
    img_bv = {im["bufferView"] for im in js.get("images", []) if "bufferView" in im}
    tex_bytes = sum(bvs[i]["byteLength"] for i in img_bv)
    total_bv = sum(b["byteLength"] for b in bvs)
    m["payload"] = {
        "totalBytes": total_bv, "textureBytes": tex_bytes,
        "geometryBytes": total_bv - tex_bytes,
        "geometryPct": round(100.0 * (total_bv - tex_bytes) / total_bv, 2) if total_bv else 0.0,
        "images": len(js.get("images", [])), "uniqueImageBufferViews": len(img_bv),
    }
    # <1.0 means images SHARE bufferViews; a buffer-rewriting stage can un-share
    # them and inflate the file. See the module docstring.
    m["imageViewSharing"] = (round(len(img_bv) / len(js["images"]), 3)
                             if js.get("images") else None)

    # ---- textures + texel budget -----------------------------------------
    m["textures"] = len(js.get("textures", []))
    texels, tex_rows = 0, []
    for i, im in enumerate(js.get("images", [])):
        wh = _png_or_webp_size(bin_, bvs, im)
        if wh:
            texels += wh[0] * wh[1]
            tex_rows.append({"image": i, "name": im.get("name"),
                             "mime": im.get("mimeType"), "width": wh[0], "height": wh[1]})
        else:
            tex_rows.append({"image": i, "name": im.get("name"),
                             "mime": im.get("mimeType"), "width": None, "height": None})
    m["textureTexels"] = texels
    m["textureImages"] = tex_rows
    # Decompressed RGBA8 VRAM the textures alone would occupy, mips included.
    m["textureVramBytesRGBA8"] = int(texels * 4 * 4 / 3)

    # ---- GPU-resident buffer bytes ---------------------------------------
    # The number the DOWNLOAD SIZE hides. Codec choice does not change it.
    gpu = 0
    for a in js.get("accessors", []):
        _dt, sz = COMP[a["componentType"]]
        gpu += a["count"] * NCOMP[a["type"]] * sz
    m["gpuBufferBytes"] = gpu

    # ---- geometry census --------------------------------------------------
    m["geometryDecoded"] = False
    if geometry and not m["compression"]:
        try:
            m.update(_geometry_census(js, bin_, mats))
            m["geometryDecoded"] = True
        except Exception as e:                      # never silently succeed
            m["geometryError"] = "%s: %s" % (type(e).__name__, e)
    return m


def _png_or_webp_size(bin_, bvs, im):
    if "bufferView" not in im:
        return None
    bv = bvs[im["bufferView"]]
    o = bv.get("byteOffset", 0)
    d = bin_[o:o + min(64, bv["byteLength"])]
    if d[:8] == b"\x89PNG\r\n\x1a\n" and len(d) >= 24:
        return struct.unpack(">II", d[16:24])
    if d[:4] == b"RIFF" and d[8:12] == b"WEBP":
        if d[12:16] == b"VP8X" and len(d) >= 30:
            w = int.from_bytes(d[24:27], "little") + 1
            h = int.from_bytes(d[27:30], "little") + 1
            return (w, h)
        if d[12:16] == b"VP8L" and len(d) >= 25:
            b = int.from_bytes(d[21:25], "little")
            return ((b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1)
    if d[:2] == b"\xff\xd8":                        # JPEG: needs a scan, skip
        return None
    return None


def _geometry_census(js, bin_, mats):
    """Per-material triangles / vertices / SURFACE AREA, plus world extents and
    per-tyre ground contact. All in WORLD space."""
    xf = node_world_translations(js)
    per, tyres = {}, {}
    wmin = np.array([np.inf] * 3); wmax = np.array([-np.inf] * 3)
    rmin = np.array([np.inf] * 3); rmax = np.array([-np.inf] * 3)
    for ni, n in enumerate(js.get("nodes", [])):
        if "mesh" not in n:
            continue
        M = xf.get(ni, np.eye(4))
        for p in js["meshes"][n["mesh"]]["primitives"]:
            pos = read_accessor(js, bin_, p["attributes"]["POSITION"]).astype(np.float64)
            rmin = np.minimum(rmin, pos.min(axis=0)); rmax = np.maximum(rmax, pos.max(axis=0))
            w = pos @ M[:3, :3].T + M[:3, 3]
            wmin = np.minimum(wmin, w.min(axis=0)); wmax = np.maximum(wmax, w.max(axis=0))
            if "indices" in p:
                idx = read_accessor(js, bin_, p["indices"]).reshape(-1, 3)
            else:
                idx = np.arange(len(w)).reshape(-1, 3)
            t = w[idx]
            area = 0.5 * np.linalg.norm(
                np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
            name = mats[p["material"]].get("name") if "material" in p else "<none>"
            d = per.setdefault(name, {"triangles": 0, "vertices": 0, "area": 0.0,
                                      "yMin": np.inf, "yMax": -np.inf, "nodes": []})
            d["triangles"] += len(idx); d["vertices"] += len(w)
            d["area"] += float(area.sum())
            d["yMin"] = min(d["yMin"], float(w[:, 1].min()))
            d["yMax"] = max(d["yMax"], float(w[:, 1].max()))
            d["nodes"].append(n.get("name"))
            if TYRE_NODE.search(n.get("name") or ""):
                tyres[n["name"]] = min(tyres.get(n["name"], np.inf), float(w[:, 1].min()))
    tot_a = sum(d["area"] for d in per.values()) or 1.0
    tot_t = sum(d["triangles"] for d in per.values()) or 1
    for d in per.values():
        d["areaPct"] = round(100.0 * d["area"] / tot_a, 3)
        d["trianglePct"] = round(100.0 * d["triangles"] / tot_t, 3)
        d["area"] = round(d["area"], 6)
        d["yMin"] = round(d["yMin"], 5); d["yMax"] = round(d["yMax"], 5)
    ground = min(tyres.values()) if tyres else None
    return {
        "extents": [round(float(v), 4) for v in (wmax - wmin)],
        "boundsWorld": [[round(float(v), 4) for v in wmin],
                        [round(float(v), 4) for v in wmax]],
        "extentsRawNoTransform": [round(float(v), 4) for v in (rmax - rmin)],
        "surfaceAreaM2": round(float(tot_a), 4),
        "perMaterial": per,
        "tyreNodeMinY": {k: round(v, 5) for k, v in sorted(tyres.items())},
        "tyreGroundGapMaxMM": (round(1000.0 * (max(tyres.values()) - ground), 1)
                               if tyres else None),
    }


# --------------------------------------------------------------------------
# BUDGET
# --------------------------------------------------------------------------
# Every number here is JUSTIFIED in mobile_gate.py's report and in
# pipeline/machine/mobile/README.md. They are defaults, not laws: override with
# --budget-json. What must NOT change without new evidence is the shape --
# bytes, triangles, GPU bytes and draw calls are four independent constraints
# and passing one says nothing about the others.
DEFAULT_BUDGET = {
    "sizeBytesMax": 5_000_000,
    "trianglesMax": 350_000,
    "drawCallsMax": 60,
    "gpuBufferBytesMax": 24_000_000,
    "textureVramBytesMax": 64_000_000,
    "normalCoverageMin": 1.0,
    "loadSecondsMax_typical4G": 4.0,
}


def budget_verdict(m, budget=None):
    b = dict(DEFAULT_BUDGET); b.update(budget or {})
    rows = [
        ("download bytes", m["sizeBytes"], b["sizeBytesMax"], "<=", "B"),
        ("triangles", m["triangles"], b["trianglesMax"], "<=", ""),
        ("draw calls", m["drawCalls"], b["drawCallsMax"], "<=", ""),
        ("GPU buffer bytes", m["gpuBufferBytes"], b["gpuBufferBytesMax"], "<=", "B"),
        ("texture VRAM bytes", m["textureVramBytesRGBA8"], b["textureVramBytesMax"], "<=", "B"),
        ("NORMAL coverage", m["normalCoverage"], b["normalCoverageMin"], ">=", ""),
    ]
    out = []
    for name, got, lim, op, unit in rows:
        ok = (got <= lim) if op == "<=" else (got >= lim)
        out.append({"axis": name, "value": got, "limit": lim, "op": op,
                    "unit": unit, "pass": bool(ok)})
    return {"budget": b, "axes": out, "pass": all(r["pass"] for r in out)}


def fmt(m, budget=None):
    L = []
    A = L.append
    A("=" * 78)
    A("MOBILE METRICS  %s" % os.path.basename(m["path"]))
    A("=" * 78)
    A("size            : %10s bytes  (%.3f MB)" % ("{:,}".format(m["sizeBytes"]),
                                                   m["sizeBytes"] / 1e6))
    A("compression     : %s" % (", ".join(m["compression"]) or "none"))
    p = m["payload"]
    A("payload split   : geometry %.3f MB (%.1f%%)  texture %.3f MB  [%d images / %d unique views]"
      % (p["geometryBytes"] / 1e6, p["geometryPct"], p["textureBytes"] / 1e6,
         p["images"], p["uniqueImageBufferViews"]))
    A("draw calls      : %d primitives" % m["drawCalls"])
    A("triangles       : %s" % "{:,}".format(m["triangles"]))
    A("vertices        : %s" % "{:,}".format(m["vertices"]))
    A("GPU buffers     : %.3f MB resident (unchanged by codec)" % (m["gpuBufferBytes"] / 1e6))
    A("materials       : %d  %s" % (m["materials"], m["materialNames"]))
    A("nodes           : %d" % m["nodes"])
    A("textures        : %d images, %s texels, %.2f MB RGBA8+mips VRAM"
      % (m["textures"], "{:,}".format(m["textureTexels"]),
         m["textureVramBytesRGBA8"] / 1e6))
    A("NORMAL accessors: %s primitives (%.0f%%)"
      % (m["normalPrimitives"], 100 * m["normalCoverage"]))
    A("index widths    : %s" % m["indexBitsHistogram"])
    if m.get("geometryDecoded"):
        A("extents (world) : %.4f x %.4f x %.4f m" % tuple(m["extents"]))
        A("extents (raw)   : %.4f x %.4f x %.4f m   <- node transforms IGNORED, do not quote"
          % tuple(m["extentsRawNoTransform"]))
        A("surface area    : %.4f m2" % m["surfaceAreaM2"])
        if m.get("tyreNodeMinY"):
            A("tyre ground     :")
            for k, v in m["tyreNodeMinY"].items():
                A("    %-18s world minY %8.4f m   (%+.1f mm off the lowest tyre)"
                  % (k, v, 1000 * (v - min(m["tyreNodeMinY"].values()))))
        A("")
        A("  %-20s %9s %6s %11s %6s   %8s %8s"
          % ("material", "tris", "%tri", "area m2", "%area", "yMin", "yMax"))
        for name, d in sorted(m["perMaterial"].items(), key=lambda kv: -kv[1]["triangles"]):
            A("  %-20s %9s %5.1f%% %11.4f %5.1f%%   %8.4f %8.4f"
              % (name, "{:,}".format(d["triangles"]), d["trianglePct"], d["area"],
                 d["areaPct"], d["yMin"], d["yMax"]))
    elif m["compression"]:
        A("geometry census : NOT DECODED (%s). Run `gltf-transform copy` first."
          % ", ".join(m["compression"]))
    bv = budget_verdict(m, budget)
    A("")
    A("BUDGET")
    for r in bv["axes"]:
        v = ("{:,}".format(r["value"]) if isinstance(r["value"], int) else r["value"])
        l = ("{:,}".format(r["limit"]) if isinstance(r["limit"], int) else r["limit"])
        A("  [%s] %-20s %14s  %s %-14s" % ("PASS" if r["pass"] else "FAIL",
                                           r["axis"], v, r["op"], l))
    A("  => %s" % ("WITHIN BUDGET" if bv["pass"] else "OVER BUDGET"))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--budget-json", help="JSON file overriding DEFAULT_BUDGET keys")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    budget = json.load(open(a.budget_json)) if a.budget_json else None
    out = []
    for g in a.glb:
        m = measure(g)
        m["budgetVerdict"] = budget_verdict(m, budget)
        out.append(m)
        if not a.quiet:
            print(fmt(m, budget))
            print()
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out if len(out) > 1 else out[0], fh, indent=2)
    return 0 if all(o["budgetVerdict"]["pass"] for o in out) else 1


if __name__ == "__main__":
    sys.exit(main())
