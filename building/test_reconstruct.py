"""Tests for Phase 1 reconstruction — no GPU, no network, no model.

The model itself is pretrained and used zero-shot, so what needs testing is
everything around it: which frames get fed in, whether the output is metric,
and whether an implausible result is refused rather than exported.

Run: python building/test_reconstruct.py
"""
import os
import sys
import json
import struct
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import reconstruct as R  # noqa: E402
import scale as S  # noqa: E402

PASSED, FAILED = [], []
TMP = tempfile.mkdtemp(prefix="recon-test-")


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


# ==========================================================================
# 1. Frame selection — coverage first, sharpness within it
# ==========================================================================

# THE failure this design exists to prevent. The sharpest frames cluster
# where the person stood still, so "top N by sharpness" reconstructs the
# spot they paused in beautifully and loses the rest of the property.
# Here frames 0-9 are razor sharp (someone paused); 10-99 are workable.
clustered = [100.0] * 10 + [10.0] * 90
picked = R.select_frames(clustered, 10)
check("1a selection spans the whole capture",
      max(picked) > 50, f"picked {picked}")
check("1b it does not just take the sharp cluster",
      len([i for i in picked if i < 10]) <= 2, str(picked))
check("1c returns the requested count", len(picked) == 10, str(len(picked)))
check("1d indices are sorted", picked == sorted(picked))

# Within each span, the sharpest frame wins.
alternating = [1.0, 9.0] * 10
picked = R.select_frames(alternating, 10)
check("1e picks the sharper frame in each span",
      all(alternating[i] == 9.0 for i in picked), str(picked))

# Fewer frames than requested: keep them all, minus the unusable.
check("1f fewer frames than target returns them all",
      R.select_frames([5.0, 5.0, 5.0], 10) == [0, 1, 2])
check("1g empty input is handled", R.select_frames([], 10) == [])

try:
    R.select_frames([1.0], 0)
    check("1h zero target refused", False)
except R.ReconstructError:
    check("1h zero target refused", True)

# Blur floor: badly soft frames add nothing and drag the pose solution, so
# they are dropped rather than fed in.
with_blur = [10.0] * 20 + [0.1] * 5 + [10.0] * 20
picked = R.select_frames(with_blur, 45)
check("1i blurred frames dropped",
      not any(20 <= i < 25 for i in picked), str([i for i in picked if 20 <= i < 25]))
check("1j sharp frames survive", len(picked) >= 35, str(len(picked)))

# Uniform sharpness -> even spacing, which is the right fallback when
# OpenCV is unavailable and every score is neutral.
picked = R.select_frames([1.0] * 100, 10)
spacings = [b - a for a, b in zip(picked, picked[1:])]
check("1k uniform input gives even spacing",
      max(spacings) - min(spacings) <= 1, str(spacings))


# ==========================================================================
# 2. Coverage gaps — a gap is a wall nobody has a viewpoint on
# ==========================================================================
check("2a contiguous selection has no gaps",
      R.coverage_gaps(list(range(0, 100, 10)), 100, 10) == [])
gaps = R.coverage_gaps([0, 1, 2, 3, 97, 98, 99], 100, 10)
check("2b a hole in the middle is found", len(gaps) >= 1, str(gaps))
check("2c the gap covers the missing span",
      any(g[0] <= 50 <= g[1] for g in gaps), str(gaps))
check("2d no frames at all is one whole gap",
      R.coverage_gaps([], 100, 10) == [(0, 100)])
check("2e zero-length capture handled", R.coverage_gaps([], 0, 10) == [])


# ==========================================================================
# 3. PLY output
# ==========================================================================
pts = [(0.0, 0.0, 0.0), (1.5, -2.5, 3.0), (10.0, 10.0, 10.0)]
p = os.path.join(TMP, "a.ply")
check("3a returns the point count", R.write_ply(p, pts) == 3)

with open(p, "rb") as f:
    blob = f.read()
head = blob.split(b"end_header\n")[0].decode()
check("3b binary little-endian header", "binary_little_endian" in head)
check("3c vertex count in header", "element vertex 3" in head)
check("3d no colour properties when none given", "red" not in head)

body = blob.split(b"end_header\n", 1)[1]
check("3e body is 3 floats per point", len(body) == 3 * 12, str(len(body)))
first = struct.unpack("<fff", body[:12])
check("3f coordinates round-trip", first == (0.0, 0.0, 0.0), str(first))
second = struct.unpack("<fff", body[12:24])
check("3g negatives survive", abs(second[1] + 2.5) < 1e-6, str(second))

pc = os.path.join(TMP, "c.ply")
R.write_ply(pc, pts, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
with open(pc, "rb") as f:
    cblob = f.read()
chead = cblob.split(b"end_header\n")[0].decode()
check("3h colour properties present", "property uchar red" in chead)
cbody = cblob.split(b"end_header\n", 1)[1]
check("3i body is 15 bytes per coloured point", len(cbody) == 3 * 15)

try:
    R.write_ply(os.path.join(TMP, "bad.ply"), pts, [(1, 2, 3)])
    check("3j mismatched colour count refused", False)
except R.ReconstructError as e:
    check("3j mismatched colour count refused", "colour count" in str(e))

check("3k empty cloud writes cleanly",
      R.write_ply(os.path.join(TMP, "e.ply"), []) == 0)


# ==========================================================================
# 4. Bounds and the dimension sanity check
# ==========================================================================
b = R.bounds([(0, 0, 0), (10, 5, 3)])
check("4a bounds min", b["min"] == [0, 0, 0])
check("4b bounds size", b["size"] == [10, 5, 3])
check("4c empty cloud has no bounds", R.bounds([]) is None)

# This is the last line of defence against a bad scale factor. A wrong scale
# is more dangerous than a failed job, because every downstream quantity
# inherits it while looking entirely plausible.
check("4d a credible house passes",
      R.sanity_check_dimensions({"size": [12, 9, 7]}, "closed") == [])

try:
    R.sanity_check_dimensions({"size": [0.4, 0.3, 0.2]}, "closed")
    check("4e doll's-house scale refused", False)
except R.ReconstructError as e:
    check("4e doll's-house scale refused", "not a building" in str(e))
    check("4f refusal warns against quoting", "do not quote" in str(e))

try:
    R.sanity_check_dimensions({"size": [400, 300, 50]}, "closed")
    check("4g absurdly large scale refused", False)
except R.ReconstructError as e:
    check("4g absurdly large scale refused", "far larger" in str(e))

notes = R.sanity_check_dimensions({"size": [80, 40, 10]}, "open")
check("4h oversized first-fix area warns but passes",
      len(notes) == 1 and "one property" in notes[0], str(notes))
check("4i same size on a closed scan does not warn",
      R.sanity_check_dimensions({"size": [80, 40, 10]}, "closed") == [])


# ==========================================================================
# 5. Scale resolution — the model must never emit unscaled dimensions
# ==========================================================================
r = R.resolve_scale({"scale_source": "auto", "depth_url": "d.bin"}, False)
check("5a depth resolves to lidar", r["source"] == "lidar")
r = R.resolve_scale({"scale_source": "auto", "roomplan_url": "r.usdz"}, False)
check("5b roomplan resolves to lidar", r["source"] == "lidar")

r = R.resolve_scale({"scale_source": "auto", "scale_reference_m": 3.6,
                     "scale_reference_units": 360.0}, False)
check("5c manual reference used", r["source"] == "manual")
check("5d manual scale computed", abs(r["scale_m_per_unit"] - 0.01) < 1e-12)

r = R.resolve_scale({"scale_source": "auto", "scale_observations": [
    {"kind": "brick_course", "measured_units": 150.0, "repeats": 20},
    {"kind": "socket_height", "measured_units": 45.0}]}, False)
check("5e observations resolve to anchors", r["source"] == "anchors")
check("5f anchor scale correct", abs(r["scale_m_per_unit"] - 0.01) < 1e-9)

# The model predicts its own metric scale. Usable, but it is an inference
# from image content rather than a measurement, and must say so.
r = R.resolve_scale({"scale_source": "auto"}, True)
check("5g model scale used as a fallback", r["source"] == "model_metric")
check("5h model scale is not overstated", r["confidence"] == "fair")
check("5i model scale warns before quoting", "before quoting" in r["note"])

# No scale available at all is fatal, not a shrug.
try:
    R.resolve_scale({"scale_source": "auto"}, False)
    check("5j no scale is refused", False)
except S.ScaleError as e:
    check("5j no scale is refused", "No way to establish" in str(e))
    check("5k refusal lists the options", "brick coursing" in str(e))

try:
    R.resolve_scale({"scale_source": "lidar"}, False)
    check("5l lidar requested but absent is refused", False)
except S.ScaleError as e:
    check("5l lidar requested but absent is refused", "no depth" in str(e))


# ==========================================================================
# 6. Model availability is reported, not faked
# ==========================================================================
check("6a availability is a real check",
      R.model_available() == R.model_available())
if not R.model_available():
    try:
        R.run_mapanything(["a.jpg"], "fast")
        check("6b missing model refused", False)
    except R.ReconstructError as e:
        check("6b missing model refused", "not installed" in str(e))
        check("6c error suggests what still works",
              "roof" in str(e) and "price" in str(e), str(e)[:120])


# ==========================================================================
# 7. Capture handling
# ==========================================================================
try:
    R.fetch_capture({}, os.path.join(TMP, "w1"))
    check("7a empty capture refused", False)
except R.ReconstructError as e:
    check("7a empty capture refused", "no video_url or image_urls" in str(e))

check("7b sharpness degrades gracefully without opencv",
      len(R.sharpness_scores([os.path.join(TMP, "nope.jpg")])) == 1)


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
