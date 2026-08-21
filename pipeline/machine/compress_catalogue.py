#!/usr/bin/env python3
"""
compress_catalogue.py -- re-runnable, resumable batch compressor for the LIVE
ExpertCarCheck catalogue, with per-asset quality gates.

    python3 pipeline/machine/compress_catalogue.py --sample 20
    python3 pipeline/machine/compress_catalogue.py --ids jeep-grand-cherokee-jpw1-v1
    python3 pipeline/machine/compress_catalogue.py --all --variants
    python3 pipeline/machine/compress_catalogue.py --controls        # negative controls only

WHAT THIS IS FOR
----------------
Measured on the live catalogue 2026-08-21 (mobile gate, CHECKPOINT.md):

  * 1,042 of 1,043 approved entries have `mobileGlbUrl` IDENTICAL to
    `desktopGlbUrl`. There is no distinct mobile asset anywhere.
  * 64.3% of approved assets exceed 5 MB; 29.8% exceed 20 MB.
    Median 10.1 MB, p90 34.0 MB, max 47.9 MB.
  * 8,056 colour-variant GLBs need the same treatment.

Draco on the Golf test bed gave 28.704 -> 3.654 MB (7.85x) at PSNR 39.81 dB with
0 validator errors. The compression works and is nearly free. **What was missing
was anything that produces the asset.** This file produces it.

SCOPE -- WHAT THIS DELIBERATELY DOES NOT DO
-------------------------------------------
It writes compressed objects into `car-meshes/staging/compressed/` and a
MANIFEST mapping assetId -> compressed object. It NEVER touches the live
catalogue index, never changes a URL, and publishes nothing customer-visible.
A separate owner owns `platform/resolver/index.ts` and wires the serving path.

THE RECIPE
----------
`gltf-transform draco` -- GEOMETRY ONLY. Textures, materials, node names, node
transforms and KHR material extensions pass through untouched, which is checked
rather than assumed (G4). Decimation is NOT in the recipe and must not be added
without new evidence: measured on this programme the first 5% of triangles costs
3.85 dB because the loss is the clearcoat specular highlight breaking up across
large smooth panels, not the silhouette.

THE FIVE GATES -- every one must pass or the asset is REJECTED, not shipped
--------------------------------------------------------------------------
G0  SIZE      bytes must SHRINK, and the image payload must not grow.
              **DRACO CAN INFLATE A FILE.** A previous pass on this programme
              compressed geometry 8.9x and still grew the file by +12.70 MB,
              because 4 images sharing 2 bufferViews each got a copy. A
              "compression" that grows the file is a loud FAIL, never a ship.

G1  GLAZING   `glass_probe` verdict on the WRITTEN file, AND a glass-AREA
              retention figure. **The probe alone is not sufficient and two
              agents proved it independently on 2026-08-21**: it returned
              clear/proven on a car whose glazing geometry was cut to 2.5% of
              its area, and on a car with every KHR extension stripped. It reads
              the material TABLE and never asks how much SURFACE carries that
              material. The verdict is always paired with the area figure here.
              `opaque`+`proven` is a hard fail (owner ruling 2026-08-11);
              `ambiguous` is NOT a fail and routes to the eye.

G2  TYRES     tyre-class materials keep a dark, unchanged baseColorFactor and
              keep their surface area. HONEST SCOPE: CLAUDE.md 2026-08-11
              records a glTF tyre probe validated at RECALL 0/8 against 131
              ground-truthed cars. This is an INVARIANCE check on the
              compression, not a verdict on the car.

G3  RESPRAY   a name-targeted respray of the asset's own paint material(s) must
              MOVE the body and must NOT move tyres, rims or lamps -- run
              through the live <model-viewer> material API, the same path the
              product uses, with flat-emissive isolation passes to attribute
              every changed pixel. CLAUDE.md 2026-08-15: every automated gate
              passed a car whose separation was fake and only the respray
              control caught it -- "the control is not a formality, it is the
              verdict."

G4  FILE      official Khronos validator, ZERO errors, plus NORMAL accessors on
              every primitive, node names, material names and per-material KHR
              extensions all preserved -- read back off the WRITTEN FILE, never
              trusted from the writer. `trimesh` silently drops every KHR
              material extension on any glTF round-trip (transmission, IOR,
              clearcoat gone while alphaMode survives), so glass_probe keeps
              passing glazing that has stopped refracting. This gate is the
              thing that catches it; negative control NC4 proves it fires.

G5  PSNR      >= 35 dB at matched cameras against the uncompressed master.
              **NOT silhouette IoU.** IoU is measured NON-MONOTONIC in damage on
              this project's own data: ratio 0.30 scored min IoU 0.97683, HIGHER
              than ratio 0.90's 0.97594, at two thirds fewer triangles and 9.5 dB
              worse. IoU is kept as a gross-failure channel only.

WHERE A FAILURE COMES FROM
--------------------------
Every gate is run against the CANDIDATE in absolute terms, and where the
candidate fails, the MASTER is checked too. A live asset whose master already
fails a gate is reported `blocked-by-master` -- it is still not shipped, but the
compression did not break it and saying so is the difference between a useful
report and a wrong one.

RESUMABILITY
------------
One receipt per asset at `car-meshes/staging/compressed/receipts/<id>.json`.
A re-run LISTS that prefix once and skips everything already receipted. This
container has rolled back six times in one day; the bucket and origin are the
only things that survive, so the artefact goes up the moment it passes and the
local copy is pruned.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "mobile"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "pipeline", "ingest"))
sys.path.insert(0, os.path.join(HERE, "buildstages"))

import mobile_metrics as MM                                     # noqa: E402
import fidelity as FID                                          # noqa: E402
import glass_probe as GP                                        # noqa: E402

GLTF_TRANSFORM = shutil.which("gltf-transform") or "/opt/node22/bin/gltf-transform"
VALIDATE = os.path.join(HERE, "gltf_validate.py")

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
PREFIX = "staging/compressed"
CATALOGUE_URL = f"{SB}/storage/v1/object/public/car-renders/catalogue.v2.json"

# ---- material classes -----------------------------------------------------
# GLASSY comes from glass_probe so the two can never drift apart -- CLAUDE.md:
# "a retro check that reimplements them drifts from the wave check, and then the
# two disagree about the same car."
GLASSY = GP.GLASSY

# ---------------------------------------------------------------------------
# CORRECTED 2026-08-21. These three were written with word-boundary lookarounds
# on BOTH sides. Measured against 60 random live catalogue cars, the tyre form
# MISSED a tyre material in **10 of them** -- and the dominant miss is the plain
# English PLURAL, because the trailing `(?![a-z0-9])` refuses the `s`:
#     Tires · tires · Pneus · M_2022_Mercedes_AMG_GLS63_Tires · tirea0
#     XJ220MI_Thick_Tire1 · advantyre.001 · Meshestire0021Mtl
# On those cars G2 printed "no tyre-NAMED material in this car -- G2 has nothing
# to check", which reads as a fact about the CAR and was a fact about the REGEX.
# `glass_probe.GLASSY` is a plain substring match and never had the problem,
# which is exactly why glazing area was being measured on cars whose tyre area
# was not. The two classes were simply inconsistent.
#
# The relaxation is the direction that manufactures FALSE POSITIVES, so it is
# fenced by `pipeline/machine/test_compress_regex.py`, which asserts BOTH
# directions against 3,082 distinct real catalogue material names plus every
# trap this project has recorded. RUN IT AFTER ANY EDIT TO THESE THREE LINES.
#
# A generic right-hand guard does NOT work and the first attempt at one was
# wrong: `tire(?!s?[a-z])` still refuses `tires`, because `s?` backtracks to
# empty and `[a-z]` then matches the `s` itself. The guards below are therefore
# an EXPLICIT list of the English continuations that actually exist
# (`tired`/`tireless`/`tiresome`, `discovery`, `trim`, `primer`), which is
# checkable against the corpus in a way a clever generic rule is not.
# ---------------------------------------------------------------------------
TYRE_MAT = re.compile(
    r"(?:(?<!en)(?<!at)(?<!re)(?<!sa)tire(?!d|less|some)"
    r"|tyre"
    r"|rubber"
    r"|pneu(?!matic)"
    r"|neumatico|reifen)", re.I)

# `light` must NOT be followed by a colour word: the 2026 Clio's BODY material is
# `M_0132_LightGray` and a naive /light/ ate it. That guard is KEPT and widened
# to allow a separator, because the real names are `LightGray`, `light_blue` and
# `M_0132_LightGray` alike. The left guards are `flight`/`highlight`/`slight`,
# which are the only English words in 3,082 real names that end in `light`.
LAMP_MAT = re.compile(
    r"(?:lamp"
    r"|lens"
    r"|(?:head|tail|rear|fog|stop|brake|reverse|indicator|turn)[\W_]*light"
    r"|(?<!f)(?<!high)(?<!s)light"
    r"(?![\W_]*(?:gray|grey|blue|green|red|brown|beige|silver|white))(?!ing)"
    r"|phare|feux|faro|scheinwerfer)", re.I)

# `rim` needs a LEFT boundary and nothing else: `rims?` on its own matched
# `chrome_trim` (and would have matched `primer`), which is a false LEAK on a
# gated class. `disc` needs `(?!over)` or every Land Rover Discovery material
# books as a brake disc.
RIM_MAT = re.compile(
    r"(?:(?<![a-z])rim"
    r"|alloy|wheel|jante|felge|rines|llanta"
    r"|disc(?!over)|brake|caliper)", re.I)
PAINT_HINT = GP.BODYISH

DEFAULT_MIN_PSNR = 35.0
DEFAULT_MIN_AREA_RATIO = 0.98      # a COMPRESSION must not lose surface at all;
                                   # 0.98 is slack for float rounding, not for loss.
RESPRAY_MOVE_MIN = 0.15
RESPRAY_LEAK_TOL = 0.03


# ==========================================================================
# small helpers
# ==========================================================================

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _sbhdr():
    k = os.environ.get("SB_KEY")
    if not k:
        raise RuntimeError("SB_KEY not in env. `set -a; . /root/.alam3d_env; set +a`")
    # BOTH headers. With `Authorization` alone this storage returns
    # `403 Invalid Compact JWS`, which looks exactly like an expired key.
    return {"apikey": k, "Authorization": f"Bearer {k}"}


def sb_put(key, data, content_type="application/octet-stream"):
    url = f"{SB}/storage/v1/object/{BUCKET}/{key}"
    h = dict(_sbhdr())
    h["Content-Type"] = content_type
    h["x-upsert"] = "true"
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status
    except urllib.error.HTTPError as e:
        if e.code in (400, 409):
            req = urllib.request.Request(url, data=data, headers=h, method="PUT")
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.status
        raise


def sb_list(prefix):
    """Full listing of a prefix, offset-paginated.

    CLAUDE.md: a truncated 50-row listing once produced a confident and wrong
    "the artefact is not in the bucket". List the FULL prefix, always.
    """
    out, off = {}, 0
    while True:
        body = json.dumps({"prefix": prefix, "limit": 100, "offset": off,
                           "sortBy": {"column": "name", "order": "asc"}}).encode()
        h = dict(_sbhdr())
        h["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{SB}/storage/v1/object/list/{BUCKET}",
                                     data=body, headers=h)
        d = json.load(urllib.request.urlopen(req, timeout=120))
        if not d:
            break
        for o in d:
            out[o["name"]] = (o.get("metadata") or {}).get("size")
        off += len(d)
        if len(d) < 100:
            break
    return out


def download(url, dst, tries=4):
    """Fetch, and VERIFY the byte count against Content-Length.

    A silent short read is not hypothetical here: the first run of this tool
    pulled 36,067,392 of jeep-grand-cherokee-jpw1-v1's 47,934,668 bytes with no
    exception at all, and the failure surfaced three stages later as
    `gltf-transform draco: Invalid typed array length`. A truncated master would
    otherwise become a "compression" measured against the wrong denominator.
    """
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=900) as r:
                want = r.headers.get("Content-Length")
                want = int(want) if want else None
                with open(dst, "wb") as fh:
                    shutil.copyfileobj(r, fh, 1 << 20)
            got = os.path.getsize(dst)
            if want is not None and got != want:
                raise RuntimeError("short read: %d of %d bytes" % (got, want))
            if got < 20:
                raise RuntimeError("implausibly small download: %d bytes" % got)
            return got
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"download failed after {tries}: {url}: {last}")


def gt(args, timeout=3600):
    p = subprocess.run([GLTF_TRANSFORM] + args, capture_output=True, text=True,
                       timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("gltf-transform %s failed rc=%d: %s"
                           % (args[0], p.returncode, (p.stderr or p.stdout)[-800:]))
    return p.stdout


# ==========================================================================
# THE RECIPE
# ==========================================================================

def compress(master, out, recipe="draco", quantize_position=14):
    """Geometry-only compression. Returns a log dict.

    `--quantization-volume scene` is NOT used: the default per-mesh volume gives
    each mesh its own quantisation grid, which is strictly higher precision for a
    car assembled from many small parts (a wheel nut quantised over the whole
    car's bounds is the low-precision case). The cost of `mesh` volume is that
    coincident vertices in DIFFERENT meshes can separate; on a car those are
    material boundaries, not welds, and G5 measures the result rather than
    assuming it.
    """
    t0 = time.time()
    if recipe == "draco":
        gt(["draco", master, out,
            "--quantize-position", str(quantize_position),
            "--quantize-normal", "10",
            "--quantize-texcoord", "12",
            "--quantize-color", "8",
            "--quantize-generic", "12"])
    elif recipe == "meshopt":
        gt(["meshopt", master, out])
    elif recipe == "copy":          # control: rewrite with no compression
        gt(["copy", master, out])
    else:
        raise ValueError("unknown recipe %r" % recipe)
    return {"recipe": recipe, "seconds": round(time.time() - t0, 2),
            "quantizePosition": quantize_position}


# ==========================================================================
# G0 -- SIZE. The inflation trap.
# ==========================================================================

def g0_size(mm_master, mm_cand, bytes_in, bytes_out):
    img_in = mm_master["payload"]["textureBytes"]
    img_out = mm_cand["payload"]["textureBytes"]
    grew = bytes_out >= bytes_in
    img_grew = img_out > img_in * 1.001 + 1024
    fails = []
    if grew:
        fails.append("FILE GREW: %d -> %d bytes (+%.2f MB). Draco duplicating "
                     "shared image bufferViews is the documented mechanism "
                     "(+12.70 MB on a previous pass here)."
                     % (bytes_in, bytes_out, (bytes_out - bytes_in) / 1e6))
    if img_grew:
        fails.append("IMAGE PAYLOAD GREW: %d -> %d bytes; unique image "
                     "bufferViews %s -> %s (sharing %s -> %s)"
                     % (img_in, img_out,
                        mm_master["payload"]["uniqueImageBufferViews"],
                        mm_cand["payload"]["uniqueImageBufferViews"],
                        mm_master.get("imageViewSharing"),
                        mm_cand.get("imageViewSharing")))
    # ADVISORY, never a gate. Measured 2026-08-21: `audi-a2-v1` compresses
    # 0.149 -> 0.148 MB (x1.003) and passes G0 correctly -- it DID shrink. The
    # small end of this catalogue is already Draco-compressed and
    # texture-dominated, so there is nothing left for geometry compression to
    # take. That is a fact about the asset, not a defect in the candidate, so it
    # must not fail a gate; it is flagged here so the manifest's consumer can
    # skip re-serving a file that saves nothing.
    notes = []
    if not grew and bytes_out > 0.95 * bytes_in:
        notes.append("MARGINAL: only %.1f%% saved. This asset is already "
                     "texture-dominated (geometry is %s%% of the master's "
                     "payload); geometry compression has little left to take. "
                     "Not a failure -- a fact about the asset."
                     % (100.0 * (bytes_in - bytes_out) / bytes_in,
                        mm_master["payload"]["geometryPct"]))
    return {"status": "FAIL" if fails else "PASS",
            "bytesIn": bytes_in, "bytesOut": bytes_out,
            "marginal": bool(notes), "notes": notes,
            "ratio": round(bytes_in / bytes_out, 3) if bytes_out else None,
            "savedBytes": bytes_in - bytes_out,
            "imageBytesIn": img_in, "imageBytesOut": img_out,
            "imageViewSharingIn": mm_master.get("imageViewSharing"),
            "imageViewSharingOut": mm_cand.get("imageViewSharing"),
            "geometryPctIn": mm_master["payload"]["geometryPct"],
            "failures": fails}


# ==========================================================================
# G1 -- GLAZING: probe verdict AND glass AREA retention. Never one alone.
# ==========================================================================

def glass_probe_local(path):
    """glass_probe's own rules against a local file. Rules are NOT reimplemented."""
    js, _ = MM.glb_read(path)
    orig = GP.gltf_json
    try:
        GP.gltf_json = lambda _u: js
        return GP.probe(os.path.basename(path), url="local://%s" % path)
    finally:
        GP.gltf_json = orig


def _class_area(per_material, rx):
    return sum(d["area"] for n, d in per_material.items() if n and rx.search(n))


def g1_glazing(master_probe, cand_probe, per_m, per_c, min_ratio):
    fails, notes = [], []
    v, c = cand_probe["verdict"], cand_probe["certainty"]
    if v == "opaque" and c == "proven":
        fails.append("glazing verdict opaque/proven -- hard scrap under the "
                     "owner ruling 2026-08-11")
    if (master_probe["verdict"], master_probe["certainty"]) != (v, c):
        fails.append("glazing verdict CHANGED by compression: %s/%s -> %s/%s"
                     % (master_probe["verdict"], master_probe["certainty"], v, c))
    if v == "ambiguous":
        notes.append("verdict `ambiguous` -- NOT a fail; routes to the eye "
                     "(owner ruling: a misspelt `Widnwos`/`Windiow` and lamp "
                     "lenses voting have all landed here on good cars)")
    am = _class_area(per_m, GLASSY)
    ac = _class_area(per_c, GLASSY)
    ratio = (ac / am) if am > 0 else None
    if am <= 0:
        notes.append("no glass-NAMED material carries geometry in the master -- "
                     "area retention NOT APPLICABLE; the verdict stands alone "
                     "here and it is the weaker evidence for it")
    elif ratio < min_ratio:
        fails.append("GLASS AREA retained only %.2f%% (need >= %.0f%%). This is "
                     "the check `glass_probe` cannot make: it reads the material "
                     "table and would still say %s/%s with no glass in the car."
                     % (100 * ratio, 100 * min_ratio, v, c))
    return {"status": "FAIL" if fails else "PASS",
            "verdictMaster": "%s/%s" % (master_probe["verdict"], master_probe["certainty"]),
            "verdictCandidate": "%s/%s" % (v, c),
            "glassAreaMaster": round(am, 6), "glassAreaCandidate": round(ac, 6),
            "glassAreaRatio": round(ratio, 5) if ratio is not None else None,
            "glazingNamed": [g.get("name") for g in cand_probe.get("glazing_named") or []],
            "flatShell": cand_probe.get("flat_shell"),
            "alphaShell": cand_probe.get("alpha_shell"),
            "failures": fails, "notes": notes}


# ==========================================================================
# G2 -- TYRES
# ==========================================================================

def tyre_rows(path):
    js, _ = MM.glb_read(path)
    rows = []
    for m in js.get("materials", []):
        nm = m.get("name") or ""
        if not TYRE_MAT.search(nm):
            continue
        pbr = m.get("pbrMetallicRoughness") or {}
        bcf = pbr.get("baseColorFactor") or [1, 1, 1, 1]
        lum = 0.2126 * bcf[0] + 0.7152 * bcf[1] + 0.0722 * bcf[2]
        textured = bool(pbr.get("baseColorTexture"))
        rows.append({"material": nm, "baseColorFactor": [round(float(x), 6) for x in bcf],
                     "luminance": round(float(lum), 5), "textured": textured,
                     # An unreadable or absent texture must score UNKNOWN, never
                     # "opaque"/"pale": the factor on a textured material is a
                     # MULTIPLIER and is [1,1,1] on nearly all of them, so
                     # treating it as the colour invents a tyre failure.
                     "black": (None if textured else bool(lum < 0.12))})
    return rows


def g2_tyres(path_m, path_c, per_m, per_c, min_ratio):
    rm, rc = tyre_rows(path_m), tyre_rows(path_c)
    fails, notes = [], []
    if not rm:
        notes.append("no tyre-NAMED material in this car -- G2 has nothing to "
                     "check. It never had. (A glTF tyre probe scored RECALL 0/8 "
                     "against 131 ground-truthed cars; three of the eight real "
                     "failures name no tyre material at all.)")
    if {r["material"] for r in rm} != {r["material"] for r in rc}:
        fails.append("tyre material set changed: %s -> %s"
                     % (sorted(r["material"] for r in rm),
                        sorted(r["material"] for r in rc)))
    bym = {r["material"]: r for r in rm}
    for r in rc:
        o = bym.get(r["material"])
        if o and o["baseColorFactor"] != r["baseColorFactor"]:
            fails.append("tyre `%s` baseColorFactor CHANGED %s -> %s"
                         % (r["material"], o["baseColorFactor"], r["baseColorFactor"]))
        if r["black"] is False:
            fails.append("tyre `%s` is not black: baseColor luminance %.4f "
                         "(body-paint-over-rubber / flat-shell signature)"
                         % (r["material"], r["luminance"]))
        if r["black"] is None:
            notes.append("tyre `%s` is TEXTURED -- the factor is a multiplier, "
                         "not the colour; scored UNKNOWN, not black and not pale"
                         % r["material"])
    am, ac = _class_area(per_m, TYRE_MAT), _class_area(per_c, TYRE_MAT)
    ratio = (ac / am) if am > 0 else None
    if ratio is not None and ratio < min_ratio:
        fails.append("TYRE AREA retained only %.2f%% (need >= %.0f%%)"
                     % (100 * ratio, 100 * min_ratio))
    return {"status": "FAIL" if fails else "PASS",
            "master": rm, "candidate": rc,
            "tyreAreaRatio": round(ratio, 5) if ratio is not None else None,
            "scope": "invariance check on the compression only. CLAUDE.md "
                     "2026-08-11: a glTF tyre probe cannot see the per-corner "
                     "render artefact -- recall 0/8. A black reading here rules "
                     "out body-paint-over-rubber and the flat shell for this "
                     "car; it does NOT clear the car.",
            "failures": fails, "notes": notes}


# ==========================================================================
# G4 -- the WRITTEN FILE: validator + structure. Re-read, never trusted.
# ==========================================================================

def khr_material_exts(path):
    js, _ = MM.glb_read(path)
    out = {}
    for m in js.get("materials", []):
        out[m.get("name") or "<unnamed>"] = sorted((m.get("extensions") or {}).keys())
    return out


def validate(path, out_json):
    p = subprocess.run([sys.executable, VALIDATE, path, "--quiet", "--json", out_json],
                       capture_output=True, text=True, timeout=1800)
    rep = None
    if os.path.exists(out_json):
        rep = json.load(open(out_json))
        if isinstance(rep, list):
            rep = rep[0] if rep else None
    if not isinstance(rep, dict):
        return {"status": "NOT_TESTED",
                "reason": (p.stderr or p.stdout)[-400:]}
    counts = rep.get("counts") or rep
    err = counts.get("errors")
    warn = counts.get("warnings")
    if err is None:
        txt = json.dumps(rep)
        err, warn = txt.count('"severity": 0'), txt.count('"severity": 1')
    return {"status": "PASS" if err == 0 else "FAIL",
            "errors": err, "warnings": warn,
            "errorList": (rep.get("errorList") or rep.get("issues", {}).get("messages", []))[:8]}


def g4_file(path_m, path_c, mm_m, mm_c, work):
    """Everything that must survive the write, asserted on the RE-READ file."""
    fails = []
    v = validate(path_c, os.path.join(work, "validate_candidate.json"))
    if v["status"] == "FAIL":
        fails.append("Khronos validator: %s errors" % v["errors"])
    if v["status"] == "NOT_TESTED":
        fails.append("Khronos validator did not run: %s" % v.get("reason"))

    js, _ = MM.glb_read(path_c)
    jm, _ = MM.glb_read(path_m)

    def prim_norms(j):
        t = m2 = 0
        for me in j.get("meshes", []):
            for p in me["primitives"]:
                t += 1
                m2 += ("NORMAL" in p["attributes"])
        return t, m2
    tm, nm = prim_norms(jm)
    tc, nc = prim_norms(js)
    if tm != tc:
        fails.append("primitive count changed %d -> %d" % (tm, tc))
    if nm and nc < nm:
        fails.append("NORMAL accessors LOST: %d/%d -> %d/%d. This renders as "
                     "crumpled foil under the studio clearcoat and this project "
                     "has paid for it three times." % (nm, tm, nc, tc))

    lost_nodes = [n for n in mm_m["nodeNames"] if n not in set(mm_c["nodeNames"])]
    if lost_nodes:
        fails.append("NODE NAMES LOST (%d): %s -- the viewer's component "
                     "toggling depends on them" % (len(lost_nodes), lost_nodes[:8]))
    lost_mats = [n for n in mm_m["materialNames"] if n not in set(mm_c["materialNames"])]
    if lost_mats:
        fails.append("MATERIAL NAMES LOST (%d): %s" % (len(lost_mats), lost_mats[:8]))

    em, ec = khr_material_exts(path_m), khr_material_exts(path_c)
    dropped = {k: sorted(set(em[k]) - set(ec.get(k, []))) for k in em
               if set(em[k]) - set(ec.get(k, []))}
    if dropped:
        fails.append("KHR MATERIAL EXTENSIONS DROPPED: %s. transmission / IOR / "
                     "clearcoat vanish on a trimesh round-trip while alphaMode "
                     "survives, so glass_probe keeps passing glazing that has "
                     "stopped refracting." % dict(list(dropped.items())[:4]))

    return {"status": "FAIL" if fails else "PASS",
            "validator": v,
            "primitives": {"master": tm, "candidate": tc},
            "normalAccessors": {"master": "%d/%d" % (nm, tm),
                                "candidate": "%d/%d" % (nc, tc)},
            "nodeNames": {"master": len(mm_m["nodeNames"]),
                          "candidate": len(mm_c["nodeNames"]), "lost": lost_nodes[:20]},
            "materialNames": {"master": len(mm_m["materialNames"]),
                              "candidate": len(mm_c["materialNames"]), "lost": lost_mats},
            "khrMaterialExtensionsDropped": dropped,
            "failures": fails}


# ==========================================================================
# G5 -- PSNR at matched cameras. Cameras generalise to a SOURCED car.
# ==========================================================================

def catalogue_cameras(mm_master, orbit_az=None):
    """Orbit + close-ups derived from the MASTER's world bounds and its own
    material classes.

    `fidelity.CLOSEUPS` matches NODE names from the machine's own naming
    convention (`wheel_fl_tyre`, `glass_side_l`); a sourced Sketchfab car has
    none of those, so every close-up silently vanished and the verdict became a
    whole-car average -- exactly the "full-car beauty sheets average away
    component failures" failure CLAUDE.md records. These close-ups are found by
    MATERIAL CLASS instead, which every catalogue car has.

    ONE NODE PER ZONE, never the union: the first draft of the machine's version
    unioned both front wheels and framed the whole car under a "close-up" label,
    which is worse than no close-up because it looks like coverage.
    """
    lo, hi = [np.array(v, float) for v in mm_master["boundsWorld"]]
    c = (lo + hi) / 2.0
    diag = float(np.linalg.norm(hi - lo))
    tgt = "%.4fm %.4fm %.4fm" % (c[0], c[1], c[2])
    cams = [{"view": "az%03d" % az, "zone": "full",
             "orbit": "%ddeg %.1fdeg %.4fm" % (az, FID.ORBIT_EL_DEG, diag * 1.05),
             "target": tgt, "fov": "30deg"}
            for az in (orbit_az or FID.ORBIT_AZ)]

    js, bin_ = MM.glb_read(mm_master["_decodedPath"])
    xf = MM.node_world_translations(js)
    mats = js.get("materials", [])
    for label, rx in (("cu_tyre", TYRE_MAT), ("cu_glazing", GLASSY), ("cu_lamp", LAMP_MAT)):
        node_box = None
        for ni, n in enumerate(js.get("nodes", [])):
            if "mesh" not in n:
                continue
            prims = js["meshes"][n["mesh"]]["primitives"]
            hit = [p for p in prims if "material" in p
                   and rx.search(mats[p["material"]].get("name") or "")]
            if not hit:
                continue
            M = xf.get(ni, np.eye(4))
            lo2 = np.array([np.inf] * 3); hi2 = np.array([-np.inf] * 3)
            for p in hit:
                pos = MM.read_accessor(js, bin_, p["attributes"]["POSITION"]).astype(float)
                w = pos @ M[:3, :3].T + M[:3, 3]
                lo2 = np.minimum(lo2, w.min(axis=0)); hi2 = np.maximum(hi2, w.max(axis=0))
            node_box = (lo2, hi2)
            break                                   # FIRST matching node only
        if node_box is None:
            continue
        lo2, hi2 = node_box
        cc = (lo2 + hi2) / 2.0
        # A CLOSE-UP IS A NARROWER FOV, NOT A NEARER CAMERA.
        #
        # This used to pull the camera in to `clip(size*2.5, 0.35*diag,
        # 0.55*diag)`. The FLOOR of that band, 0.35 x diag, is SMALLER than the
        # model's own bounding-sphere radius of 0.5 x diag -- so on any car
        # whose component is small the camera ends up INSIDE the bodywork. That
        # is the failure CLAUDE.md already records for the machine's lamp
        # camera ("a small component puts the camera INSIDE the body"), and the
        # clamp that was supposed to prevent it had its floor set below the
        # thing it was protecting against.
        #
        # Measured cost, and this is why it matters rather than being untidy:
        # rendering nissan-gt-r-2013-nw1-v1 against a `gltf-transform copy` of
        # ITSELF -- byte-different, geometrically IDENTICAL -- the eight orbit
        # views scored 46.8-64.1 dB while the three close-ups scored 19.31 /
        # 20.62 / 20.39 dB. The difference image is a clean outline of the whole
        # car: the two loads framed the car in DIFFERENT PLACES. That is a
        # registration shift worth ~44 dB, and G5's verdict was being set by it.
        # A gate cannot have a 44 dB noise floor and a 35 dB threshold.
        #
        # Holding the camera at the full-car radius and narrowing the field of
        # view instead keeps it outside the body by construction, keeps the
        # framing stable, and still zooms.
        span = float(np.linalg.norm(hi2 - lo2))
        rr = diag * 1.05
        half = np.degrees(np.arctan2(max(span * 0.75, 1e-9), rr))
        fov = float(np.clip(2.0 * half, 6.0, 30.0))
        az = 250 if cc[2] < 0 else 290
        cams.append({"view": label, "zone": "closeup",
                     "orbit": "%ddeg 85deg %.6fm" % (az, rr),
                     "target": "%.6fm %.6fm %.6fm" % (cc[0], cc[1], cc[2]),
                     "fov": "%.2fdeg" % fov})
    return cams


def g5_psnr(master, cand, out_dir, cams, min_psnr):
    r = FID.appearance(master, cand, out_dir, cams=cams, min_psnr=min_psnr,
                       verbose=False)
    if r.get("status") == "NOT_TESTED":
        return {"status": "NOT_TESTED", "reason": r.get("reason"), "raw": r}
    return {"status": r["status"], "psnrMin": r.get("psnrMin"),
            "psnrMean": r.get("psnrMean"),
            "psnrMinFullCar": r.get("psnrMinFullCar"),
            "psnrMinCloseup": r.get("psnrMinCloseup"),
            "iouMin": r.get("iouMin"),
            "iouNote": "SANITY CHANNEL ONLY -- IoU is non-monotonic in damage "
                       "(ratio 0.30 scored 0.97683 vs ratio 0.90's 0.97594 on "
                       "this project's own data). It never decides.",
            "threshold": min_psnr, "views": r.get("views")}


# ==========================================================================
# G3 -- RESPRAY CONTROL, class-grouped isolation passes
# ==========================================================================

RESPRAY_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="icon" href="data:,">
<style>html,body{margin:0;background:#202024}
model-viewer{width:768px;height:576px;background:#202024}</style></head><body>
<model-viewer id="mv" disable-pan disable-zoom interaction-prompt="none"
  shadow-intensity="0" exposure="1" environment-image="neutral"
  min-field-of-view="1deg" max-field-of-view="120deg"></model-viewer>
<!-- min/max-camera-orbit REMOVED 2026-08-21 for the same reason as in
     fidelity.PAGE: pinning the max orbit radius to 1000 m renders any model
     around 0.05 units as a completely blank frame (measured on
     nissan-gt-r-2013-nw1-v1: 0 car pixels with, 180,263 without), while
     leaving a 4-18 unit car bit-identical. Here it would have made the
     respray control measure a respray of nothing. -->
<script>window.__loaded=false;window.__failed=null;
const mv=document.getElementById('mv');
mv.addEventListener('load',()=>{window.__loaded=true;});
mv.addEventListener('error',e=>{window.__failed=JSON.stringify(e.detail||'error');});</script>
<script type="module">
import '/model-viewer.min.js';
await customElements.whenDefined('model-viewer');
const MV=customElements.get('model-viewer');
MV.meshoptDecoderLocation='/meshopt_decoder.js'; MV.dracoDecoderLocation='/draco/';
const mv=document.getElementById('mv');
window.__setSrc=(s)=>{window.__loaded=false;window.__failed=null;mv.src=s;};
window.__cam=(o,t,f)=>{mv.cameraOrbit=o;mv.cameraTarget=t;mv.fieldOfView=f;
  mv.jumpCameraToGoal();};
// isLoaded is EVIDENCE, not defensive coding: <model-viewer> refuses to load a
// material no primitive references, so an UNLOADED material is exactly the
// phantom signature -- in the table, bound to nothing on screen.
window.__mats=()=>mv.model.materials.map(m=>({name:m.name,loaded:!!m.isLoaded}));
window.__paint=(names,rgba)=>{let n=0;mv.model.materials.forEach(m=>{
  if(names.indexOf(m.name)>=0&&m.isLoaded){
    m.pbrMetallicRoughness.setBaseColorFactor(rgba);n++;}});return n;};
// CLASS isolation: everything matte black, the whole class emissive WHITE.
// One screenshot per CLASS, not per material -- a catalogue car carries up to
// 54 materials and the per-material form costs a screenshot each.
window.__isoInit=()=>{mv.model.materials.forEach(m=>{
  if(!m.isLoaded) return;
  m.pbrMetallicRoughness.setBaseColorFactor([0,0,0,1]);
  m.pbrMetallicRoughness.setMetallicFactor(0);
  m.pbrMetallicRoughness.setRoughnessFactor(1);
  m.setEmissiveFactor([0,0,0]);});};
window.__isoSet=(idxs)=>{const ms=mv.model.materials;
  ms.forEach(m=>{if(m.isLoaded)m.setEmissiveFactor([0,0,0]);});
  idxs.forEach(k=>{if(ms[k]&&ms[k].isLoaded)ms[k].setEmissiveFactor([1,1,1]);});};
window.__ready=true;
</script></body></html>"""


def classify_materials(names, paint_names):
    """material index -> class. Order matters and is deliberate.

    paint wins over every hint (an asset's OWN recorded paint material is
    stronger evidence than any regex), then glazing, then lamp, then tyre, then
    rim. `light` is checked BEFORE `rim`/`wheel` because a lamp lens is often
    called `headlight_glass`; glazing is checked first because `lights_glass`
    and `backlight_glass` are real glazing on some cars and real lamps on
    others -- CLAUDE.md calls that one genuinely undecidable from the file, so
    it is grouped with glazing, which is EXEMPT from the leak test rather than
    gated by it. Grouping an undecidable material into the exempt class is the
    safe direction: it cannot manufacture a failure.
    """
    pset = set(paint_names or [])
    cls = {}
    for i, nm in enumerate(names):
        n = nm or ""
        if n in pset:
            cls[i] = "paint"
        elif GLASSY.search(n):
            cls[i] = "glazing"
        elif LAMP_MAT.search(n):
            cls[i] = "lamp"
        elif TYRE_MAT.search(n):
            cls[i] = "tyre"
        elif RIM_MAT.search(n):
            cls[i] = "rim"
        else:
            cls[i] = "other"
    return cls


def resolve_paint_names(path, recorded):
    """Map catalogue `paintMaterialNames` onto the file's real material names.

    `paintMaterialNames` is BLENDER's name space, not the glTF's (CLAUDE.md
    2026-08-11): Blender invents `.001`/`.002` siblings and truncates at 63
    characters. The resolver is deliberately narrow so it cannot widen paint onto
    trim -- exact hit stops there; only an unmatched name falls back to its
    `.NNN` base, then `.NNN` siblings, then a prefix ONLY at exactly 63 chars.
    """
    js, _ = MM.glb_read(path)
    have = [m.get("name") or "" for m in js.get("materials", [])]
    hs = set(have)
    out, how = [], {}
    for want in (recorded or []):
        if want in hs:
            out.append(want); how[want] = "exact"; continue
        base = re.sub(r"\.\d{3}$", "", want)
        if base in hs:
            out.append(base); how[want] = "dotNNN-base"; continue
        sib = [h for h in have if re.sub(r"\.\d{3}$", "", h) == base]
        if sib:
            out += sib; how[want] = "dotNNN-siblings"; continue
        if len(want) == 63:
            pre = [h for h in have if h.startswith(want)]
            if pre:
                out += pre; how[want] = "63char-prefix"; continue
        how[want] = "UNRESOLVED"
    return sorted(set(out)), how, have


def infer_paint_names(path):
    """Fallback for the 233 approved entries with no recorded paintMaterialNames.

    Largest-AREA material that is not glazing/tyre/lamp/rim and whose name looks
    body-ish, else simply the largest-area non-excluded material. RANK BY AREA,
    NEVER BY VERTEX COUNT -- CLAUDE.md 2026-08-14: a smooth body panel is a few
    big quads and is vertex-cheap; the 2026 Clio's body is 18.4% of area at 4.8%
    of verts and ranking by verts put it 11th of 12.
    """
    dec = FID.decode(path, os.path.join(os.path.dirname(path), "_pw"))
    m = MM.measure(dec)
    if not m.get("geometryDecoded"):
        return [], "geometry-not-decoded"
    per = m["perMaterial"]
    cand = [(n, d["area"]) for n, d in per.items()
            if n and not GLASSY.search(n) and not TYRE_MAT.search(n)
            and not LAMP_MAT.search(n) and not RIM_MAT.search(n)]
    if not cand:
        return [], "no-candidate"
    hint = [c for c in cand if PAINT_HINT.search(c[0]) and not TYRE_MAT.search(c[0])]
    pool = hint or cand
    pool.sort(key=lambda kv: -kv[1])
    return [pool[0][0]], ("bodyish-name+area" if hint else "largest-area")


def respray_control(path, out_dir, cam, paint_names, min_mask_coverage=0.90,
                    move_min=RESPRAY_MOVE_MIN, leak_tol=RESPRAY_LEAK_TOL,
                    min_sample_px=800, paint_share_max=0.90):
    """Blue-respray `paint_names` in the live viewer; attribute every changed
    pixel to a material CLASS via flat-emissive isolation passes.

    PASS needs BOTH halves. A respray that moves nothing ships eight identical
    files (`corolla-cross` at dist 0.004); a respray that moves everything is the
    `toyota-auris` cov=1.000 retirement.

    GLAZING IS EXEMPT FROM THE LEAK TEST and that is not a loophole: transmissive
    glass shows the body THROUGH it, so repainting the body necessarily changes
    glazing pixels (measured 29.1% on a car with no leak at all). Glazing is
    gated by G1, which is the stronger test for it.

    THE INSTRUMENT CHECKS ITSELF: the union of class masks must cover
    `min_mask_coverage` of the car's silhouette or the result is NOT_TESTED --
    never PASS, never a named FAIL. The first version of this instrument on this
    programme lacked that check and produced a confident false leak off a mask
    covering 882 pixels of the car.
    """
    from PIL import Image
    from playwright.sync_api import sync_playwright
    import viewer_check as VC

    mv = VC.find_model_viewer(); exe = VC.find_chromium()
    if not mv or not exe:
        return {"status": "NOT_TESTED", "reason": "model-viewer or Chromium unavailable"}
    if not paint_names:
        return {"status": "NOT_TESTED", "reason": "no paint material resolved"}

    os.makedirs(out_dir, exist_ok=True)
    web = os.path.join(out_dir, "web"); os.makedirs(web, exist_ok=True)
    shutil.copy(path, os.path.join(web, "c.glb"))
    shutil.copy(mv, os.path.join(web, "model-viewer.min.js"))
    VC.vendor_decoders(web)
    open(os.path.join(web, "index.html"), "w").write(RESPRAY_PAGE)
    handler = lambda *a, **k: VC.Quiet(*a, directory=web, **k)   # noqa: E731
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    shots, names, loaded, cls = {}, [], [], {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, executable_path=exe, args=[
                "--use-gl=angle", "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader", "--no-sandbox", "--disable-dev-shm-usage"])
            p = b.new_page(viewport={"width": 820, "height": 620})
            # 180 s, not playwright's 30 s default: a whole-material-table update
            # makes three.js re-upload and recompile and SwiftShader then needs
            # tens of seconds to redraw ~1M triangles.
            p.set_default_timeout(180000)
            p.goto("http://127.0.0.1:%d/index.html" % port)
            p.wait_for_function("()=>window.__ready===true", timeout=60000)
            p.evaluate("s=>window.__setSrc(s)", "/c.glb")
            p.wait_for_function("()=>window.__loaded===true||window.__failed!==null",
                                timeout=600000)
            if p.evaluate("window.__failed"):
                raise RuntimeError(p.evaluate("window.__failed"))
            p.wait_for_timeout(1200)
            p.evaluate("a=>window.__cam(a[0],a[1],a[2])",
                       [cam["orbit"], cam["target"], cam["fov"]])
            p.wait_for_timeout(600)
            mi = p.evaluate("()=>window.__mats()")
            names = [m["name"] for m in mi]
            loaded = [bool(m["loaded"]) for m in mi]
            cls = classify_materials(names, paint_names)
            box = p.locator("#mv").bounding_box()
            clip = {"x": box["x"], "y": box["y"],
                    "width": box["width"], "height": box["height"]}

            # ORDER: before -> paint -> after, isolation LAST. Running the
            # isolation passes between the two measured frames and restoring
            # afterwards captured an "after" frame on a car still half-black and
            # reported ten simultaneous paint leaks on a car with none.
            shots["before"] = os.path.join(out_dir, "respray_before.png")
            _settle(p, clip, out_dir)
            p.screenshot(path=shots["before"], clip=clip)
            npainted = p.evaluate("a=>window.__paint(a[0],a[1])",
                                  [paint_names, [0.05, 0.12, 0.75, 1.0]])
            _settle(p, clip, out_dir)
            shots["after"] = os.path.join(out_dir, "respray_after.png")
            p.screenshot(path=shots["after"], clip=clip)

            p.evaluate("()=>window.__isoInit()")
            _settle(p, clip, out_dir)
            classes = sorted(set(cls.values()))
            for cname in classes:
                idxs = [i for i, c in cls.items() if c == cname]
                p.evaluate("k=>window.__isoSet(k)", idxs)
                p.wait_for_timeout(500)
                fp = os.path.join(out_dir, "iso_%s.png" % cname)
                p.screenshot(path=fp, clip=clip)
                shots["iso_" + cname] = fp
            b.close()
    finally:
        httpd.shutdown()

    A = np.asarray(Image.open(shots["before"]).convert("RGB")).astype(np.int16)
    B = np.asarray(Image.open(shots["after"]).convert("RGB")).astype(np.int16)
    changed = np.abs(A - B).max(axis=2) > 16
    bg = np.array([0x20, 0x20, 0x24])
    car = (np.abs(A - bg).sum(axis=2) > 24) | (np.abs(B - bg).sum(axis=2) > 24)

    # ARGMAX over class luminance, never a brightness THRESHOLD. A threshold was
    # the wrong instrument on this programme: model-viewer's material API does
    # not expose KHR_materials_clearcoat, so a "matte black" material still
    # throws a specular highlight from the neutral IBL and the masks overlapped
    # 2.2x. A full white emissive always beats a highlight on black.
    classes = sorted(set(cls.values()))
    lums = []
    for cname in classes:
        I = np.asarray(Image.open(shots["iso_" + cname]).convert("RGB")).astype(np.float64)
        lums.append(0.2126 * I[:, :, 0] + 0.7152 * I[:, :, 1] + 0.0722 * I[:, :, 2])
    L = np.stack(lums)
    best = L.argmax(axis=0)
    top = L.max(axis=0)
    second = np.sort(L, axis=0)[-2] if len(classes) > 1 else np.zeros_like(top)
    part = (top > 25) & ((top - second) > 12) & car
    coverage = float(part.sum()) / float(car.sum()) if car.sum() else 0.0

    def erode1(m):
        e = m.copy()
        e[1:, :] &= m[:-1, :]; e[:-1, :] &= m[1:, :]
        e[:, 1:] &= m[:, :-1]; e[:, :-1] &= m[:, 1:]
        return e

    gi = classes.index("glazing") if "glazing" in classes else None
    glass_front = (lums[gi] > 60) if gi is not None else np.zeros_like(car)

    rows, fails, advisory = [], [], []
    for k, cname in enumerate(classes):
        raw = part & (best == k)
        m = erode1(raw)
        sample = m if cname == "glazing" else (m & ~glass_front)
        px, spx = int(raw.sum()), int(sample.sum())
        frac = float(changed[sample].mean()) if spx else None
        row = {"class": cname, "materials": [names[i] for i, c in cls.items() if c == cname],
               "maskPixels": px, "samplePixels": spx,
               "maskShareOfCar": round(px / float(car.sum()), 4) if car.sum() else 0,
               "changedFraction": round(frac, 4) if frac is not None else None}
        rows.append(row)
        if cname == "paint":
            if frac is None or frac < move_min:
                fails.append("paint did NOT move: class `paint` changed on %s of "
                             "its own pixels (need >= %.0f%%)"
                             % ("no" if frac is None else "%.1f%%" % (100 * frac),
                                100 * move_min))
            if row["maskShareOfCar"] > paint_share_max:
                fails.append("paint covers %.1f%% of the car (ceiling %.0f%%) -- "
                             "one material over the whole model is the "
                             "toyota-auris cov=1.000 retirement signature"
                             % (100 * row["maskShareOfCar"], 100 * paint_share_max))
        elif cname == "glazing":
            advisory.append("glazing changed %s -- EXPECTED where it is "
                            "transmissive; gated by G1, not here"
                            % ("n/a" if frac is None else "%.1f%%" % (100 * frac)))
        elif cname == "other":
            advisory.append("class `other` changed %s -- reported, NOT gated: it "
                            "is the unclassified remainder and on a sourced car "
                            "it routinely contains body panels under junk names "
                            "(`Material_2125670220` IS the Tucson's body skin)"
                            % ("n/a" if frac is None else "%.1f%%" % (100 * frac)))
        elif spx < min_sample_px:
            advisory.append("class `%s` sample only %d px after erosion and "
                            "glazing exclusion -- reported, not gated" % (cname, spx))
        elif frac > leak_tol:
            fails.append("PAINT LEAK onto `%s`: %.1f%% of its pixels changed "
                         "(tolerance %.1f%%); materials %s"
                         % (cname, 100 * frac, 100 * leak_tol, row["materials"][:6]))

    status = "PASS"
    if coverage < min_mask_coverage:
        status = "NOT_TESTED"
        advisory.append("class masks cover only %.1f%% of the car silhouette "
                        "(need %.0f%%) -- the masks are not a partition, so this "
                        "result is NOT_TESTED, never PASS and never a named FAIL"
                        % (100 * coverage, 100 * min_mask_coverage))
    elif fails:
        status = "FAIL"
    return {"status": status, "paintMaterials": paint_names,
            "paintedInViewer": npainted, "maskCoverage": round(coverage, 4),
            "classes": rows, "failures": fails, "advisory": advisory,
            "unloadedMaterials": [n for n, l in zip(names, loaded) if not l]}


def _settle(page, clip, tmpdir, max_wait_s=90.0, tol=1.0):
    """Block until two consecutive frames match. A fixed wait is not a settle
    check: under SwiftShader a large model keeps refining for tens of seconds."""
    from PIL import Image
    prev, t0 = None, time.time()
    fp = os.path.join(tmpdir, "_settle.png")
    while time.time() - t0 < max_wait_s:
        page.screenshot(path=fp, clip=clip)
        cur = np.asarray(Image.open(fp).convert("RGB")).astype(np.float64)
        if prev is not None and np.abs(cur - prev).mean() < tol:
            return True
        prev = cur
        page.wait_for_timeout(700)
    return False


# ==========================================================================
# NEGATIVE CONTROLS -- generators ONLY. Never production stages.
# ==========================================================================
# "A metric that has never returned a failure is not a metric." Two checks on
# this programme were found to have never once fired: a WRONG_CLASS regex ending
# in a literal \b, and a wheel gate that was empty by construction. Four more
# were found on 2026-08-21, one of which reported PASS while 8 of 14 components
# were missing.

def nc_decimate(src, dst):
    """NC1 -- destroy the surface. Must FAIL G5 while IoU survives."""
    gt(["simplify", src, dst, "--ratio", "0.02", "--error", "1",
        "--lock-border", "false"])


def nc_gut_glass(src, dst, keep_every=40):
    """NC2 -- delete the glazing GEOMETRY, leave the material TABLE untouched.

    Must show `glass_probe` STILL returning its clear verdict (the blind spot,
    demonstrated) while the paired area figure FAILS (the blind spot, covered).
    """
    dec = os.path.join(os.path.dirname(dst), "_ncdec.glb")
    gt(["copy", src, dec])
    js, bin_ = MM.glb_read(dec)
    mats = js.get("materials", [])
    tgt = {i for i, m in enumerate(mats) if GLASSY.search(m.get("name") or "")}
    if not tgt:
        raise RuntimeError("no glazing material to gut")
    bins = bytearray(bin_)
    bvs = js["bufferViews"]
    n = 0
    for me in js.get("meshes", []):
        for p in me["primitives"]:
            if p.get("material") not in tgt or "indices" not in p:
                continue
            acc = js["accessors"][p["indices"]]
            bv = bvs[acc["bufferView"]]
            dt, sz = MM.COMP[acc["componentType"]]
            off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            arr = np.frombuffer(bytes(bins[off:off + acc["count"] * sz]),
                                dtype=dt).copy()
            tri = arr.reshape(-1, 3)
            keep = np.zeros(len(tri), bool)
            keep[::keep_every] = True
            # CORRECTED 2026-08-21. This line was `tri[~keep] = tri[0]`, with the
            # comment "degenerate: zero area, valid index". It is NEITHER: it
            # copies TRIANGLE 0, which has full area, so the gutted file kept
            # N x area(tri0) of glazing and the control reported the glass area
            # falling only to 65.18% while describing itself as having gutted
            # the glazing. It still FIRED, so nothing looked wrong -- a control
            # firing for the wrong reason is the least visible kind of broken
            # instrument. All three indices must point at ONE vertex for the
            # triangle to have zero area.
            tri[~keep] = tri[0, 0]
            bins[off:off + acc["count"] * sz] = tri.reshape(-1).astype(dt).tobytes()
            n += 1
    if not n:
        raise RuntimeError("no glazing primitive found to gut")
    MM.glb_write(dst, js, bytes(bins))


def nc_rebind_tyre_to_paint(src, dst, paint_names):
    """NC3 -- bind the tyre geometry to the paint material.

    CORRECTION recorded in code by an earlier agent and reproduced here: a
    material bound to NOTHING owns no pixels, so the respray PIXEL test alone
    does not always catch this. The binding half of G2 does. Both are checked.
    """
    dec = os.path.join(os.path.dirname(dst), "_ncdec3.glb")
    gt(["copy", src, dec])
    js, bin_ = MM.glb_read(dec)
    mats = js.get("materials", [])
    pi = next((i for i, m in enumerate(mats) if (m.get("name") or "") in set(paint_names)), None)
    ti = {i for i, m in enumerate(mats) if TYRE_MAT.search(m.get("name") or "")}
    if pi is None or not ti:
        raise RuntimeError("need both a paint and a tyre material")
    n = 0
    for me in js.get("meshes", []):
        for p in me["primitives"]:
            if p.get("material") in ti:
                p["material"] = pi
                n += 1
    if not n:
        raise RuntimeError("no tyre primitive to rebind")
    MM.glb_write(dst, js, bin_)


def nc_strip_khr(src, dst):
    """NC4 -- strip every KHR material extension, exactly as a trimesh
    round-trip does. `alphaMode` survives, so glass_probe keeps passing."""
    dec = os.path.join(os.path.dirname(dst), "_ncdec4.glb")
    gt(["copy", src, dec])
    js, bin_ = MM.glb_read(dec)
    n = 0
    for m in js.get("materials", []):
        if m.get("extensions"):
            n += len(m["extensions"])
            m.pop("extensions")
    if not n:
        raise RuntimeError("no KHR material extension to strip")
    keep = [e for e in js.get("extensionsUsed", []) if not e.startswith("KHR_materials_")]
    js["extensionsUsed"] = keep
    js["extensionsRequired"] = [e for e in js.get("extensionsRequired", [])
                                if not e.startswith("KHR_materials_")] or None
    if js["extensionsRequired"] is None:
        js.pop("extensionsRequired")
    MM.glb_write(dst, js, bin_)


def nc_drop_normals(src, dst):
    """NC6 -- drop every NORMAL accessor. The crumpled-foil defect."""
    dec = os.path.join(os.path.dirname(dst), "_ncdec6.glb")
    gt(["copy", src, dec])
    js, bin_ = MM.glb_read(dec)
    n = 0
    for me in js.get("meshes", []):
        for p in me["primitives"]:
            if "NORMAL" in p["attributes"]:
                p["attributes"].pop("NORMAL")
                n += 1
    if not n:
        raise RuntimeError("no NORMAL accessor to drop")
    MM.glb_write(dst, js, bin_)


def nc_inflate(src, dst):
    """NC5 -- grow the file. Reproduces the +12.70 MB image-duplication trap by
    un-sharing image bufferViews, and pads if the car has no images to un-share."""
    dec = os.path.join(os.path.dirname(dst), "_ncdec5.glb")
    gt(["copy", src, dec])
    js, bin_ = MM.glb_read(dec)
    bins = bytearray(bin_)
    imgs = js.get("images") or []
    added = 0
    for im in imgs:
        if "bufferView" not in im:
            continue
        bv = js["bufferViews"][im["bufferView"]]
        o = bv.get("byteOffset", 0)
        blob = bytes(bins[o:o + bv["byteLength"]])
        while len(bins) % 4:
            bins.append(0)
        js["bufferViews"].append({"buffer": 0, "byteOffset": len(bins),
                                  "byteLength": len(blob)})
        bins += blob
        im["bufferView"] = len(js["bufferViews"]) - 1
        added += len(blob)
    if added < 1024:                     # texture-free car: pad instead
        pad = max(2 << 20, len(bins) // 4)
        while len(bins) % 4:
            bins.append(0)
        js["bufferViews"].append({"buffer": 0, "byteOffset": len(bins), "byteLength": pad})
        bins += bytes(pad)
        added = pad
    MM.glb_write(dst, js, bytes(bins))
    return added


# ==========================================================================
# per-asset pipeline
# ==========================================================================

def gate_asset(asset_id, master_path, cand_path, work, paint_recorded,
               min_psnr=DEFAULT_MIN_PSNR, min_area=DEFAULT_MIN_AREA_RATIO,
               skip_respray=False, skip_psnr=False):
    """Run all five gates. Returns the gate block; does not decide shipping."""
    g = {}
    mdec = FID.decode(master_path, os.path.join(work, "dec"))
    cdec = FID.decode(cand_path, os.path.join(work, "dec"))
    mm_m = MM.measure(mdec); mm_m["_decodedPath"] = mdec
    mm_c = MM.measure(cdec); mm_c["_decodedPath"] = cdec
    raw_m = MM.measure(master_path, geometry=False)
    raw_c = MM.measure(cand_path, geometry=False)
    per_m = mm_m.get("perMaterial") or {}
    per_c = mm_c.get("perMaterial") or {}
    if not (mm_m.get("geometryDecoded") and mm_c.get("geometryDecoded")):
        return {"error": "geometry census unavailable: %s / %s"
                         % (mm_m.get("geometryError"), mm_c.get("geometryError"))}, \
               mm_m, mm_c

    g["G0_size"] = g0_size(raw_m, raw_c,
                           os.path.getsize(master_path), os.path.getsize(cand_path))
    g["G1_glazing"] = g1_glazing(glass_probe_local(master_path),
                                 glass_probe_local(cand_path), per_m, per_c, min_area)
    g["G2_tyres"] = g2_tyres(master_path, cand_path, per_m, per_c, min_area)
    g["G4_file"] = g4_file(master_path, cand_path, mm_m, mm_c, work)

    cams = catalogue_cameras(mm_m)
    if skip_psnr:
        g["G5_psnr"] = {"status": "NOT_TESTED", "reason": "--skip-psnr"}
    else:
        g["G5_psnr"] = g5_psnr(master_path, cand_path,
                               os.path.join(work, "psnr"), cams, min_psnr)

    if skip_respray:
        g["G3_respray"] = {"status": "NOT_TESTED", "reason": "--skip-respray"}
    else:
        names, how, _have = resolve_paint_names(cand_path, paint_recorded)
        route = "catalogue.paintMaterialNames"
        if not names:
            names, why = infer_paint_names(cand_path)
            route = "inferred:" + why
        # az215 = a three-quarter view. az000/az090 are end-on and a lamp or a
        # wheel simply is not visible there, which produced a false "absorbed by
        # another material" failure inside this gate's ancestor.
        cam = next((c for c in cams if c["view"] == "az215"), cams[0])
        r = respray_control(cand_path, os.path.join(work, "respray"), cam, names)
        r["paintRoute"] = route
        r["paintResolution"] = how
        g["G3_respray"] = r
    return g, mm_m, mm_c


def verdict(gates):
    """PASS only if all five gates pass. Anything else is NOT SHIPPED."""
    order = ["G0_size", "G1_glazing", "G2_tyres", "G3_respray", "G4_file", "G5_psnr"]
    st = {k: gates.get(k, {}).get("status", "MISSING") for k in order}
    if all(v == "PASS" for v in st.values()):
        return "PASS", st, []
    reasons = []
    for k in order:
        if st[k] == "FAIL":
            reasons += ["%s: %s" % (k, f) for f in (gates[k].get("failures") or ["FAIL"])]
        elif st[k] in ("NOT_TESTED", "MISSING"):
            reasons.append("%s: %s (%s)" % (k, st[k], gates.get(k, {}).get("reason", "")))
    return ("REJECT" if any(v == "FAIL" for v in st.values()) else "BLOCKED"), st, reasons


def process_one(entry, args, work_root, already):
    aid = entry["assetId"]
    url = entry["url"]
    kind = entry.get("kind", "base")
    rid = entry.get("receiptId", aid)
    if rid in already and not args.force:
        return {"assetId": aid, "receiptId": rid, "status": "SKIP-already-receipted"}
    work = os.path.join(work_root, re.sub(r"[^A-Za-z0-9_.-]", "_", rid))
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    rec = {"assetId": aid, "receiptId": rid, "kind": kind, "sourceUrl": url,
           "tool": "pipeline/machine/compress_catalogue.py",
           "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        master = os.path.join(work, "master.glb")
        rec["masterBytes"] = download(url, master)
        rec["masterSha256"] = sha256(master)
        cand = os.path.join(work, "%s.glb" % rid)
        rec["compress"] = compress(master, cand, args.recipe, args.quantize_position)
        rec["candidateBytes"] = os.path.getsize(cand)
        rec["candidateSha256"] = sha256(cand)
        gates, mm_m, mm_c = gate_asset(aid, master, cand, work,
                                       entry.get("paintMaterialNames"),
                                       min_psnr=args.min_psnr,
                                       min_area=args.min_area_ratio,
                                       skip_respray=args.skip_respray,
                                       skip_psnr=args.skip_psnr)
        if isinstance(gates, dict) and gates.get("error"):
            rec["status"] = "ERROR"; rec["error"] = gates["error"]
        else:
            rec["gates"] = gates
            rec["masterMetrics"] = {k: mm_m[k] for k in
                                    ("sizeBytes", "triangles", "vertices", "materials",
                                     "nodes", "payload", "gpuBufferBytes",
                                     "textureVramBytesRGBA8", "extents") if k in mm_m}
            rec["candidateMetrics"] = {k: mm_c[k] for k in
                                       ("sizeBytes", "triangles", "vertices", "materials",
                                        "nodes", "payload", "gpuBufferBytes") if k in mm_c}
            v, st, reasons = verdict(gates)
            rec["verdict"] = v
            rec["gateStatus"] = st
            rec["rejectReasons"] = reasons
            rec["status"] = v
            if v == "PASS" and not args.dry_run:
                key = "%s/glb/%s.glb" % (PREFIX, rid)
                sb_put(key, open(cand, "rb").read(), "model/gltf-binary")
                rec["compressedObject"] = key
                rec["compressedUrl"] = ("%s/storage/v1/object/public/%s/%s"
                                        % (SB, BUCKET, key))
    except Exception as e:                                       # noqa: BLE001
        rec["status"] = "ERROR"
        rec["error"] = "%s: %s" % (type(e).__name__, e)
        rec["traceback"] = traceback.format_exc()[-2000:]
    rec["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # THE RECEIPT GOES UP EVEN ON FAILURE -- a rejected asset must stay rejected
    # across a rollback, or the next run re-downloads 48 MB to learn the same thing.
    if not args.dry_run:
        try:
            sb_put("%s/receipts/%s.json" % (PREFIX, rid),
                   json.dumps(rec, indent=1).encode(), "application/json")
            rec["receiptUploaded"] = True
        except Exception as e:                                   # noqa: BLE001
            rec["receiptUploaded"] = False
            rec["receiptError"] = str(e)
    os.makedirs(args.out_dir, exist_ok=True)
    json.dump(rec, open(os.path.join(args.out_dir, "%s.json" % rid), "w"), indent=1)
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return rec


# ==========================================================================
# the control harness -- every gate must be SHOWN to fire
# ==========================================================================

def run_controls(master, work, args):
    """Build a broken asset per gate, run that gate, and REQUIRE it to fail.

    Reports the control's number AND the healthy baseline's number side by side,
    because "it failed" without the pair is not evidence that the threshold sits
    anywhere useful.

    If any control does NOT fire, this returns BLOCKED. A run whose instruments
    cannot be shown to work has measured nothing.
    """
    os.makedirs(work, exist_ok=True)
    base = os.path.join(work, "base.glb")
    compress(master, base, args.recipe, args.quantize_position)

    mdec = FID.decode(master, os.path.join(work, "dec"))
    mm_m = MM.measure(mdec); mm_m["_decodedPath"] = mdec
    per_m = mm_m["perMaterial"]
    bdec = FID.decode(base, os.path.join(work, "dec"))
    mm_b = MM.measure(bdec)
    raw_m = MM.measure(master, geometry=False)
    raw_b = MM.measure(base, geometry=False)
    probe_m = glass_probe_local(master)
    cams = catalogue_cameras(mm_m)
    names, _how, _h = resolve_paint_names(base, args.paint_names)
    if not names:
        names, _why = infer_paint_names(base)

    out = {"master": master, "paintMaterials": names, "controls": {}}

    def rec(tag, fired, detail):
        out["controls"][tag] = {"fired": bool(fired), **detail}
        print("  %-26s %s   %s" % (tag, "FIRED" if fired else "*** DID NOT FIRE ***",
                                   detail.get("summary", "")), flush=True)

    # ---- baseline: the healthy candidate must PASS every gate --------------
    b_g0 = g0_size(raw_m, raw_b, os.path.getsize(master), os.path.getsize(base))
    b_g1 = g1_glazing(probe_m, glass_probe_local(base), per_m,
                      mm_b["perMaterial"], args.min_area_ratio)
    b_g2 = g2_tyres(master, base, per_m, mm_b["perMaterial"], args.min_area_ratio)
    b_g4 = g4_file(master, base, mm_m, mm_b, work)
    b_g5 = g5_psnr(master, base, os.path.join(work, "psnr_base"), cams, args.min_psnr)
    out["baseline"] = {"G0": b_g0["status"], "G1": b_g1["status"], "G2": b_g2["status"],
                       "G4": b_g4["status"], "G5": b_g5["status"],
                       "ratio": b_g0["ratio"], "psnrMin": b_g5.get("psnrMin"),
                       "iouMin": b_g5.get("iouMin"),
                       "glassAreaRatio": b_g1["glassAreaRatio"]}
    print("baseline (healthy draco): %s" % json.dumps(out["baseline"]), flush=True)

    # ---- NC1 over-decimation -> G5 -----------------------------------------
    try:
        p = os.path.join(work, "nc1.glb"); nc_decimate(master, p)
        r = g5_psnr(master, p, os.path.join(work, "psnr_nc1"), cams, args.min_psnr)
        n1 = MM.measure(FID.decode(p, os.path.join(work, "dec")))
        rec("NC1_overdecimate", r["status"] == "FAIL",
            {"psnrMin": r.get("psnrMin"), "psnrMinHealthy": b_g5.get("psnrMin"),
             "iouMin": r.get("iouMin"), "iouMinHealthy": b_g5.get("iouMin"),
             "trianglesHealthy": mm_b.get("triangles"), "triangles": n1.get("triangles"),
             "summary": "PSNR %.2f dB vs healthy %.2f dB; IoU %.5f vs %.5f "
                        "(IoU is the channel that survives -- the documented trap, "
                        "reproduced in this run)"
                        % (r.get("psnrMin", -1), b_g5.get("psnrMin", -1),
                           r.get("iouMin", -1), b_g5.get("iouMin", -1))})
    except Exception as e:                                       # noqa: BLE001
        rec("NC1_overdecimate", False, {"error": str(e), "summary": "control build failed"})

    # ---- NC2 glazing gutted -> G1 (and the probe's blind spot, shown) ------
    try:
        p = os.path.join(work, "nc2.glb"); nc_gut_glass(master, p)
        pr = glass_probe_local(p)
        n2 = MM.measure(FID.decode(p, os.path.join(work, "dec")))
        r = g1_glazing(probe_m, pr, per_m, n2["perMaterial"], args.min_area_ratio)
        blind = (pr["verdict"], pr["certainty"]) == (probe_m["verdict"], probe_m["certainty"])
        rec("NC2_glazing_gutted", r["status"] == "FAIL",
            {"glassAreaRatio": r["glassAreaRatio"],
             "glassAreaRatioHealthy": b_g1["glassAreaRatio"],
             "probeVerdictUnchanged": blind,
             "probeVerdict": r["verdictCandidate"],
             "summary": "glass area %.2f%% of master (healthy %.2f%%) while "
                        "glass_probe STILL says %s -- the probe's blind spot, "
                        "demonstrated, and covered by the paired area figure"
                        % (100 * (r["glassAreaRatio"] or 0),
                           100 * (b_g1["glassAreaRatio"] or 0), r["verdictCandidate"])})
    except Exception as e:                                       # noqa: BLE001
        rec("NC2_glazing_gutted", False, {"error": str(e), "summary": "control build failed"})

    # ---- NC3 tyre geometry rebound to paint -> G2 (+ G3) --------------------
    try:
        p = os.path.join(work, "nc3.glb"); nc_rebind_tyre_to_paint(master, p, names)
        n3 = MM.measure(FID.decode(p, os.path.join(work, "dec")))
        r2 = g2_tyres(master, p, per_m, n3["perMaterial"], args.min_area_ratio)
        r3 = {"status": "SKIPPED"}
        if not args.skip_respray:
            cam = next((c for c in cams if c["view"] == "az215"), cams[0])
            r3 = respray_control(p, os.path.join(work, "respray_nc3"), cam, names)
        rec("NC3_paint_on_rubber", r2["status"] == "FAIL",
            {"G2": r2["status"], "G2failures": r2["failures"][:3],
             "G3": r3["status"], "G3failures": (r3.get("failures") or [])[:3],
             "tyreAreaRatio": r2["tyreAreaRatio"],
             "summary": "G2 %s (tyre area %s), G3 %s. NOTE: a material bound to "
                        "NOTHING owns no pixels, so the respray PIXEL test alone "
                        "does not always catch this -- the BINDING half of G2 is "
                        "what fires."
                        % (r2["status"], r2["tyreAreaRatio"], r3["status"])})
    except Exception as e:                                       # noqa: BLE001
        rec("NC3_paint_on_rubber", False, {"error": str(e), "summary": "control build failed"})

    # ---- NC4 KHR material extensions stripped -> G4 -------------------------
    try:
        p = os.path.join(work, "nc4.glb"); nc_strip_khr(master, p)
        n4 = MM.measure(FID.decode(p, os.path.join(work, "dec")))
        r = g4_file(master, p, mm_m, n4, work)
        pr = glass_probe_local(p)
        rec("NC4_khr_stripped", r["status"] == "FAIL",
            {"dropped": r["khrMaterialExtensionsDropped"],
             "glassProbeStillSays": "%s/%s" % (pr["verdict"], pr["certainty"]),
             "summary": "G4 %s; glass_probe STILL says %s/%s on a file whose "
                        "transmission/IOR/clearcoat are gone -- the second "
                        "independently-proven way the probe alone is insufficient"
                        % (r["status"], pr["verdict"], pr["certainty"])})
    except Exception as e:                                       # noqa: BLE001
        rec("NC4_khr_stripped", False, {"error": str(e), "summary": "control build failed"})

    # ---- NC5 inflation -> G0 ------------------------------------------------
    try:
        p = os.path.join(work, "nc5.glb"); added = nc_inflate(master, p)
        r = g0_size(raw_m, MM.measure(p, geometry=False),
                    os.path.getsize(master), os.path.getsize(p))
        rec("NC5_inflated", r["status"] == "FAIL",
            {"bytesIn": r["bytesIn"], "bytesOut": r["bytesOut"],
             "healthyBytesOut": b_g0["bytesOut"], "addedBytes": added,
             "summary": "%.3f -> %.3f MB (+%.3f MB) vs healthy %.3f MB"
                        % (r["bytesIn"] / 1e6, r["bytesOut"] / 1e6,
                           (r["bytesOut"] - r["bytesIn"]) / 1e6,
                           b_g0["bytesOut"] / 1e6)})
    except Exception as e:                                       # noqa: BLE001
        rec("NC5_inflated", False, {"error": str(e), "summary": "control build failed"})

    # ---- NC6 NORMAL accessors dropped -> G4 --------------------------------
    try:
        p = os.path.join(work, "nc6.glb"); nc_drop_normals(master, p)
        n6 = MM.measure(FID.decode(p, os.path.join(work, "dec")))
        r = g4_file(master, p, mm_m, n6, work)
        rec("NC6_normals_dropped", r["status"] == "FAIL",
            {"normalAccessors": r["normalAccessors"],
             "healthy": b_g4["normalAccessors"],
             "summary": "normals %s vs healthy %s"
                        % (r["normalAccessors"]["candidate"],
                           b_g4["normalAccessors"]["candidate"])})
    except Exception as e:                                       # noqa: BLE001
        rec("NC6_normals_dropped", False, {"error": str(e), "summary": "control build failed"})

    fired = [k for k, v in out["controls"].items() if v["fired"]]
    out["status"] = ("OK" if len(fired) == len(out["controls"])
                     and all(v == "PASS" for v in out["baseline"].values()
                             if isinstance(v, str))
                     else "BLOCKED")
    out["fired"] = "%d/%d" % (len(fired), len(out["controls"]))
    print("\ncontrols fired %s -> %s" % (out["fired"], out["status"]), flush=True)
    return out


# ==========================================================================
# selection
# ==========================================================================

def controls_entry(a):
    """`--controls <assetId|path.glb>`: resolve a master, run the harness, and
    persist the result. Exits non-zero if any control DID NOT FIRE -- a run
    whose instruments cannot be shown to work has measured nothing, so that
    must be an error status and not a line of prose in a log.
    """
    work = os.path.join(a.work_dir, "_controls")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    src = a.controls
    if os.path.exists(src):
        master = os.path.join(work, "master.glb")
        shutil.copy(src, master)
        origin = os.path.abspath(src)
    else:
        cat = load_catalogue(a.catalogue_cache)
        e = next((x for x in cat if x.get("assetId") == src), None)
        if not e or not e.get("desktopGlbUrl"):
            raise SystemExit("no local file and no approved catalogue entry "
                             "named %r" % src)
        master = os.path.join(work, "master.glb")
        download(e["desktopGlbUrl"], master)
        origin = e["desktopGlbUrl"]
        if a.paint_names is None:
            a.paint_names = e.get("paintMaterialNames")
    print("controls master: %s (%.3f MB, sha %s)"
          % (origin, os.path.getsize(master) / 1e6, sha256(master)[:12]), flush=True)
    out = run_controls(master, work, a)
    out["masterOrigin"] = origin
    out["masterSha256"] = sha256(master)
    p = os.path.join(a.out_dir, "CONTROLS.json")
    json.dump(out, open(p, "w"), indent=1)
    if not a.dry_run:
        try:
            sb_put("%s/CONTROLS.json" % PREFIX, json.dumps(out, indent=1).encode(),
                   "application/json")
            print("controls uploaded to %s/%s/CONTROLS.json" % (BUCKET, PREFIX))
        except Exception as ex:                                  # noqa: BLE001
            print("controls upload FAILED: %s" % ex)
    print("wrote %s -> %s" % (p, out["status"]))
    if out["status"] != "OK":
        raise SystemExit(2)
    return out


def load_catalogue(cache):
    if os.path.exists(cache) and os.path.getsize(cache) > 1000:
        return json.load(open(cache))
    d = json.load(urllib.request.urlopen(CATALOGUE_URL, timeout=300))
    json.dump(d, open(cache, "w"))
    return d


def select(cat, args):
    ap = [e for e in cat if e.get("publicationStatus") == "approved"
          and e.get("desktopGlbUrl")]
    rows = []
    for e in ap:
        rows.append({"assetId": e["assetId"], "receiptId": e["assetId"], "kind": "base",
                     "url": e["desktopGlbUrl"], "bytes": e.get("fileSizeBytes"),
                     "paintMaterialNames": e.get("paintMaterialNames")})
        if args.variants:
            for ck, cu in (e.get("colourVariants") or {}).items():
                rows.append({"assetId": e["assetId"],
                             "receiptId": "%s__%s" % (e["assetId"], ck),
                             "kind": "variant", "colour": ck, "url": cu,
                             "bytes": e.get("fileSizeBytes"),
                             "paintMaterialNames": e.get("paintMaterialNames")})
    if args.ids:
        want = set(args.ids)
        rows = [r for r in rows if r["assetId"] in want or r["receiptId"] in want]
        return rows
    if args.sample:
        # SPAN THE SIZE RANGE, do not take the head. Compression behaviour is a
        # function of the payload split and that tracks size hard here: the
        # small end of this catalogue is already Draco-compressed and
        # texture-dominated, the large end is 100% uncompressed geometry.
        base = [r for r in rows if r["kind"] == "base" and r["bytes"]]
        base.sort(key=lambda r: r["bytes"])
        n = args.sample
        nb = n - (2 if args.variants else 0)
        idx = [int(round(i * (len(base) - 1) / (nb - 1))) for i in range(nb)]
        out, seen = [], set()
        for i in idx:
            j = i
            while base[j]["receiptId"] in seen and j + 1 < len(base):
                j += 1
            out.append(base[j]); seen.add(base[j]["receiptId"])
        if args.variants:
            for e in cat:
                if e.get("publicationStatus") != "approved":
                    continue
                cv = e.get("colourVariants") or {}
                if not cv:
                    continue
                ck = sorted(cv)[0]
                out.append({"assetId": e["assetId"],
                            "receiptId": "%s__%s" % (e["assetId"], ck),
                            "kind": "variant", "colour": ck, "url": cv[ck],
                            "bytes": e.get("fileSizeBytes"),
                            "paintMaterialNames": e.get("paintMaterialNames")})
                if sum(1 for r in out if r["kind"] == "variant") >= 2:
                    break
        return out
    return rows


# ==========================================================================
# main
# ==========================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="/tmp/compress_out")
    ap.add_argument("--work-dir", default="/tmp/compress_work")
    ap.add_argument("--catalogue-cache", default="/tmp/compress_out/catalogue.v2.json")
    ap.add_argument("--sample", type=int, help="N assets spanning the size range")
    ap.add_argument("--ids", nargs="*", help="explicit assetIds / receiptIds")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--variants", action="store_true", help="include colour variants")
    ap.add_argument("--recipe", default="draco", choices=["draco", "meshopt", "copy"])
    ap.add_argument("--quantize-position", type=int, default=14)
    ap.add_argument("--min-psnr", type=float, default=DEFAULT_MIN_PSNR)
    ap.add_argument("--min-area-ratio", type=float, default=DEFAULT_MIN_AREA_RATIO)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="ignore existing receipts")
    ap.add_argument("--dry-run", action="store_true", help="no uploads")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--skip-respray", action="store_true")
    ap.add_argument("--skip-psnr", action="store_true")
    ap.add_argument("--manifest", action="store_true",
                    help="rebuild MANIFEST.json from the bucket receipts and exit")
    # --- the control harness ------------------------------------------------
    # WIRED 2026-08-21. It was NOT wired before: `run_controls()` existed, the
    # module docstring advertised `--controls`, argparse had no such flag and
    # nothing called the function -- so the six negative controls had never once
    # been run. That is precisely the failure class this project keeps paying
    # for (a WRONG_CLASS regex ending in a literal \b; a wheel gate empty by
    # construction). `--paint-names` was read by run_controls and likewise had
    # no flag, so the function could not have run even if it had been called.
    ap.add_argument("--controls", metavar="ASSET_ID_OR_GLB",
                    help="build a broken asset per gate from this master and "
                         "REQUIRE each gate to fail; then exit. Takes a local "
                         ".glb path or a catalogue assetId.")
    ap.add_argument("--paint-names", nargs="*", default=None,
                    help="override the paint material names for --controls")
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.work_dir, exist_ok=True)

    if a.manifest:
        return build_manifest(a)

    if a.controls:
        return controls_entry(a)

    cat = load_catalogue(a.catalogue_cache)
    rows = select(cat, a)
    if not (a.sample or a.ids or a.all):
        ap.error("choose one of --sample N / --ids ... / --all")

    already = set()
    if not a.force and not a.dry_run:
        for k in sb_list("%s/receipts/" % PREFIX):
            if k.endswith(".json"):
                already.add(k[:-5])
        print("resume: %d receipts already in the bucket" % len(already))

    todo = [r for r in rows if a.force or r["receiptId"] not in already]
    print("selected %d rows, %d to do" % (len(rows), len(todo)))
    results = []
    t0 = time.time()
    if a.jobs > 1:
        with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            futs = {ex.submit(process_one, r, a, a.work_dir, already): r for r in todo}
            for f in cf.as_completed(futs):
                results.append(f.result())
                _line(results[-1], len(results), len(todo))
    else:
        for i, r in enumerate(todo, 1):
            results.append(process_one(r, a, a.work_dir, already))
            _line(results[-1], i, len(todo))
    print("\nelapsed %.1f min" % ((time.time() - t0) / 60.0))
    json.dump(results, open(os.path.join(a.out_dir, "RUN.json"), "w"), indent=1)
    summarise(results)


def _line(rec, i, n):
    g = rec.get("gateStatus") or {}
    print("[%d/%d] %-42s %-8s %8.3f -> %7.3f MB  x%-5s %s"
          % (i, n, rec.get("receiptId", "?")[:42], rec.get("status", "?"),
             (rec.get("masterBytes") or 0) / 1e6,
             (rec.get("candidateBytes") or 0) / 1e6,
             (rec.get("gates", {}).get("G0_size", {}) or {}).get("ratio", "-"),
             " ".join("%s=%s" % (k.split("_")[0], v[0]) for k, v in g.items())),
          flush=True)


def summarise(results):
    ok = [r for r in results if r.get("status") == "PASS"]
    bad = [r for r in results if r.get("status") not in ("PASS", "SKIP-already-receipted")]
    bin_ = sum(r.get("masterBytes") or 0 for r in results if r.get("masterBytes"))
    bout = sum(r.get("candidateBytes") or 0 for r in results if r.get("candidateBytes"))
    print("\n%s\nAGGREGATE over %d processed" % ("=" * 78, len(results)))
    print("  in  %10.3f MB\n  out %10.3f MB\n  ratio %.2fx   saved %.3f MB (%.1f%%)"
          % (bin_ / 1e6, bout / 1e6, (bin_ / bout) if bout else 0,
             (bin_ - bout) / 1e6, 100.0 * (bin_ - bout) / bin_ if bin_ else 0))
    print("  PASS %d   not shipped %d" % (len(ok), len(bad)))
    for r in bad:
        print("    %-42s %-8s %s" % (r.get("receiptId", "?")[:42], r.get("status"),
                                     "; ".join((r.get("rejectReasons") or
                                                [r.get("error", "")]))[:170]))


def build_manifest(a):
    """assetId -> compressed object, rebuilt from the bucket, not from memory."""
    have = sb_list("%s/receipts/" % PREFIX)
    man, agg_in, agg_out = {}, 0, 0
    for name in sorted(have):
        if not name.endswith(".json"):
            continue
        u = "%s/storage/v1/object/public/%s/%s/receipts/%s" % (SB, BUCKET, PREFIX, name)
        try:
            r = json.load(urllib.request.urlopen(u, timeout=120))
        except Exception:                                        # noqa: BLE001
            continue
        if r.get("status") != "PASS":
            continue
        agg_in += r.get("masterBytes") or 0
        agg_out += r.get("candidateBytes") or 0
        man[r["receiptId"]] = {
            "assetId": r["assetId"], "kind": r.get("kind"),
            "colour": r.get("colour"),
            "sourceUrl": r["sourceUrl"], "sourceBytes": r.get("masterBytes"),
            "compressedObject": r.get("compressedObject"),
            "compressedUrl": r.get("compressedUrl"),
            "compressedBytes": r.get("candidateBytes"),
            "compressedSha256": r.get("candidateSha256"),
            "ratio": (r.get("gates", {}).get("G0_size", {}) or {}).get("ratio"),
            "psnrMin": (r.get("gates", {}).get("G5_psnr", {}) or {}).get("psnrMin"),
            "recipe": (r.get("compress") or {}).get("recipe"),
        }
    out = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": "assetId -> compressed object. NOT wired to serving; the "
                   "resolver owner does that. No catalogue URL was changed.",
           "prefix": "%s/%s/glb/" % (BUCKET, PREFIX),
           "count": len(man), "sourceBytes": agg_in, "compressedBytes": agg_out,
           "ratio": round(agg_in / agg_out, 3) if agg_out else None,
           "assets": man}
    p = os.path.join(a.out_dir, "MANIFEST.json")
    json.dump(out, open(p, "w"), indent=1)
    if not a.dry_run:
        sb_put("%s/MANIFEST.json" % PREFIX, json.dumps(out, indent=1).encode(),
               "application/json")
    print("manifest: %d assets, %.3f -> %.3f MB (%.2fx) -> %s"
          % (len(man), agg_in / 1e6, agg_out / 1e6,
             (agg_in / agg_out) if agg_out else 0, p))
    return out


if __name__ == "__main__":
    main()
