"""Tests for Scan Mode — the socket a phone splat plugs into.

The whole mode is offline-testable except the footprint lookup, which is
skipped by giving no address: a synthetic splat of a known "building" goes
in on scan_path, and everything the mode claims to do — verify, orient,
ground, preview, deliver — is checked on what actually comes out.

Run: python building/test_scanin.py
"""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scanin as SC   # noqa: E402
import splat as S     # noqa: E402
import validation     # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


class Prog:
    def stage(self, n, **k): pass
    def note(self, m, **k): pass


def house_splat(zup=True, n_side=40):
    """A synthetic 12 x 8 x 6m 'house' of gaussians, z-up like Scaniverse."""
    out = []
    for i in range(n_side):
        for j in range(n_side):
            x = i / (n_side - 1) * 12.0
            h = j / (n_side - 1) * 6.0
            depth = (i * 7 + j * 3) % 8
            g = {"x": x, "opacity": 1.0, "f_dc_0": 0.4, "f_dc_1": 0.1,
                 "f_dc_2": 0.0, "scale_0": -3.0, "scale_1": -3.0,
                 "scale_2": -3.0, "rot_0": 1.0}
            if zup:
                g["y"], g["z"] = depth, h + 1.5   # z is height, off ground
            else:
                g["y"], g["z"] = h + 1.5, depth
            out.append(g)
    return out


# --- 1. orientation and grounding -------------------------------------------
zs, note = SC.orient(house_splat(zup=True))
check("1a a z-up scan is detected and rotated", "z-up" in note, note)
ys = [g["y"] for g in zs]
check("1b height ends up on y after rotation",
      abs((max(ys) - min(ys)) - 6.0) < 0.1, str(max(ys) - min(ys)))

ys2, note2 = SC.orient(house_splat(zup=False))
check("1c a y-up scan is left alone", "unchanged" in note2, note2)

grounded, shift = SC.ground_to_zero(zs)
check("1d the ground lands at about zero",
      abs(min(g["y"] for g in grounded)) < 0.3,
      str(min(g["y"] for g in grounded)))
check("1e and the shift is reported", abs(shift - 1.5) < 0.3, str(shift))


# --- 2. gates ---------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    big = os.path.join(td, "big.ply")
    with open(big, "wb") as f:
        f.write(b"ply\n")
        f.seek(int(SC.MAX_PLY_MB * 1e6) + 100)
        f.write(b"x")
    try:
        SC.load(big)
        check("2a an absurd file size is refused before parsing", False)
    except SC.ScanError as e:
        check("2a an absurd file size is refused before parsing",
              "MB" in str(e), str(e))


# --- 3. the whole mode, end to end, offline ---------------------------------
with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "phone.ply")
    S.write_ply(house_splat(zup=True), src)
    spec = {"scan_path": src, "scan_id": "t1"}
    arts, result = SC.run(spec, Prog(), td)

    names = [os.path.basename(p) for p, _, _ in arts]
    check("3a the normalised splat is delivered", "t1.splat.ply" in names,
          str(names))
    check("3b the stats json is delivered", "t1.scan.json" in names)
    check("3c the preview is delivered", "t1.preview.png" in names)
    check("3d the keys say scans/", all(k.startswith("scans/")
                                        for _, k, _ in arts))

    back, _ = S.read_ply(os.path.join(td, "t1.splat.ply"))
    check("3e every gaussian survives the round trip",
          len(back) == 1600, str(len(back)))
    ymin = min(g["y"] for g in back)
    ymax = max(g["y"] for g in back)
    check("3f the delivered splat is grounded and y-up",
          abs(ymin) < 0.3 and 5.5 < ymax < 6.5, f"{ymin:.2f}..{ymax:.2f}")

    check("3g the result says photographic, not measured",
          "does not measure" in result["warning_scan"])
    check("3h no address means the scale check says so",
          "checked against nothing" in result["site"], result["site"])
    check("3i orientation note is in the delivered stats",
          "z-up" in result["orientation"])
    # The docstring once claimed footprint-fit yaw into the building frame;
    # run() only swaps the up-axis and grounds. The claim and the code must
    # agree, and the delivered stats must state the real frame.
    check("3i2 the stats say the splat is NOT in the building frame",
          "NOT" in result.get("frame", "")
          and "building" in result.get("frame", ""),
          str(result.get("frame")))
    check("3i3 and point at the alignment step a compositor needs",
          "to_building_frame" in result.get("frame", ""))
    check("3i4 the module docstring states the splat stays in the scan "
          "frame",
          "NOT rotated into the building's local frame"
          in " ".join(SC.__doc__.split()))

    stats = json.load(open(os.path.join(td, "t1.scan.json")))
    check("3j the stats file matches the result",
          stats["gaussians"] == result["gaussians"])

    if "t1.preview.png" in names:
        from PIL import Image
        im = Image.open(os.path.join(td, "t1.preview.png")).convert("RGB")
        cols = im.getcolors(SC.PREVIEW_PX ** 2) or []
        lit = sum(n for n, c in cols if sum(c) > 120)
        check("3k the preview actually shows the scan",
              lit > 1000, f"{lit} lit pixels")

    # No file and no url: the refusal names the app export path.
    try:
        SC.run({"scan_id": "x"}, Prog(), td)
        check("3l a jobless job is refused", False)
    except SC.ScanError as e:
        check("3l a jobless job is refused", "Scaniverse" in str(e), str(e))


# --- 4. the validator and the wiring ----------------------------------------
check("4a scan is a known mode", "scan" in validation.MODES)
try:
    validation.parse_job({"mode": "scan"})
    check("4b scan with nothing to scan is refused", False)
except validation.InputError as e:
    check("4b scan with nothing to scan is refused",
          "Scaniverse" in str(e), str(e))
spec = validation.parse_job({"mode": "scan", "scan_url":
                             "https://example.com/house.ply"})
check("4c scan_url survives validation",
      spec["scan_url"] == "https://example.com/house.ply")
spec2 = validation.parse_job({"mode": "scan", "scan_path": "/tmp/x.ply",
                              "address": "3 Basons Lane B68 9SQ"})
check("4d scan_path plus address survives",
      spec2["scan_path"] == "/tmp/x.ply" and spec2["address"])

import types
_runpod = types.ModuleType("runpod")
_sv = types.ModuleType("runpod.serverless")
_sv.progress_update = lambda *a, **k: None
_runpod.serverless = _sv
sys.modules.setdefault("runpod", _runpod)
sys.modules.setdefault("runpod.serverless", _sv)
import handler   # noqa: E402
check("4e the handler knows the module", handler._pipeline_available("scan"))
import progress  # noqa: E402
check("4f progress has the stage plan",
      progress.STAGE_PLANS["scan"] == ["fetching", "verifying", "orienting",
                                       "delivering"])

# THE WHOLE WORKER PATH, not just the module. The handler contract is
# run() -> (artifacts, extra); this mode shipped returning (result,
# artifacts), every direct-call test above stayed green, and the first job
# on the live endpoint died in result.update() with the artifact tuples.
# Only a job pushed through handler.handler can catch contract drift.
with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "phone.ply")
    S.write_ply(house_splat(zup=True), src)
    out = handler.handler({"id": "t-handler", "input": {
        "mode": "scan", "scan_path": src, "scan_id": "th"}})
    check("4g a scan job survives the whole handler path",
          out.get("status") == "success" and "gaussians" in out,
          str(out)[:200])
    check("4h the handler result carries the artifact map",
          isinstance(out.get("artifacts"), dict), str(out.get("artifacts")))


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
