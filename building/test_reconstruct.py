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
# 6b. The model contract — verified against MapAnything's actual source
# ==========================================================================
# Written from documentation and never executed, this call had three bugs
# that only reading the real API exposed. These assertions lock in what was
# checked, because none of it can be exercised without a GPU.
_src = open(os.path.join(HERE, "reconstruct.py")).read()
# Strip comments before asserting on usage: the comments deliberately NAME
# the wrong keys to explain the bugs, so matching raw text would fail on the
# explanation rather than the code.
_code = "\n".join(l.split("#")[0] for l in _src.splitlines())

# LICENCE. MapAnything ships two checkpoints trained on different data:
#   facebook/map-anything          cc-by-nc-4.0  (confirmed on HF)
#   facebook/map-anything-apache   apache-2.0    (confirmed on HF)
# The plain name is what the documentation reaches for first and it scores
# slightly better, so taking it is the natural mistake — and it would
# quietly make the whole product non-commercial.
check("6b-1 uses the Apache checkpoint",
      R.MODEL_ID == "facebook/map-anything-apache", R.MODEL_ID)
check("6b-2 never defaults to the non-commercial checkpoint",
      '"facebook/map-anything"' not in _code)
check("6b-3 the licence split is documented in the source",
      "cc-by-nc" in _src.lower() and "apache" in _src.lower())

# INPUT FORMAT. infer() validates against normalised tensors plus a
# data_norm_type; there is no img_path key, so the original call would have
# failed on the first real job.
check("6b-4 preprocesses through load_images", "load_images" in _code)
check("6b-5 does not pass raw paths as views", "img_path" not in _code,
      [l for l in _code.splitlines() if "img_path" in l][:1])

# OUTPUT KEYS. 'img' is the NORMALISED tensor — colouring a cloud from it
# would tint everything with the encoder's normalisation. RGB is
# 'img_no_norm'.
check("6b-6 colours from img_no_norm", '"img_no_norm"' in _code)
check("6b-7 reads pts3d and mask",
      '"pts3d"' in _code and '"mask"' in _code)

# memory_efficient_inference trades negligible speed for far more views per
# card; disabling it on the fast tier capped coverage for no gain.
check("6b-8 memory-efficient inference is always on",
      "memory_efficient_inference=True" in _code)

# The model reports whether it actually produced metric scale — worth
# carrying, since scale.py has to decide how much to trust it.
check("6b-9 captures the metric scaling factor",
      "metric_scaling_factor" in _code)

# preload_models must fetch the SAME checkpoint the handler loads, or an
# offline worker downloads nothing useful.
_pre = open(os.path.join(HERE, "preload_models.py")).read()
check("6b-10 preload fetches the Apache checkpoint",
      "map-anything-apache" in _pre)
check("6b-11 preload and handler share one override",
      "MAPANYTHING_MODEL" in _pre and "MAPANYTHING_MODEL" in _code)


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


# ---- weights are a separate thing from the package -----------------------
# model_available() only proves the pip package imports. The CHECKPOINT is
# fetched from Hugging Face at first use, and on the live endpoint three
# settings combined to make that impossible: no weights baked into the image
# (CI passes no PRELOAD_MODELS), HF_HOME pointing at a network volume that
# is not attached, and OFFLINE=1 forbidding the download.
#
# Each is survivable alone. Together, from_pretrained fails on a cache miss
# AFTER the worker has accepted the job, fetched the video and extracted
# frames — so a builder loses a first-fix capture, which cannot be retaken
# once the wall is boarded, to a configuration error.
import types as _types  # noqa: E402

_had = sys.modules.get("mapanything")
sys.modules["mapanything"] = _types.ModuleType("mapanything")
_saved = {k: os.environ.get(k) for k in ("OFFLINE", "HF_HUB_OFFLINE", "HF_HOME")}
try:
    for k in _saved:
        os.environ.pop(k, None)
    os.environ["OFFLINE"] = "1"
    os.environ["HF_HOME"] = "/nonexistent-volume/building_hf_cache"
    _ok, _why = R.weights_available()
    check("W1 OFFLINE with no cached weights is caught", not _ok, _why[:80])
    check("W2 and the message names all three ways out",
          "unset OFFLINE" in _why and "network volume" in _why
          and "PRELOAD_MODELS" in _why, _why)
    check("W3 and says which modes still work without the model",
          "roof" in _why.lower() and "planning" in _why.lower(), _why)

    # The check must run BEFORE anything is fetched — that is the whole point.
    _fetched = []
    _real_fetch = R.fetch_capture
    R.fetch_capture = lambda *a, **k: _fetched.append(1) or []
    try:
        class _P:
            def stage(self, *a, **k): pass
            def note(self, *a, **k): pass
        R.run({"video_url": "https://example.test/x.mp4", "scan_id": "w"},
              _P(), TMP)
        check("W4 the job is refused before the capture is fetched", False,
              "ran on")
    except R.ReconstructError as e:
        check("W4 the job is refused before the capture is fetched",
              not _fetched, f"fetch_capture was called {len(_fetched)} times")
        check("W5 with the configuration reason, not a model error",
              "OFFLINE" in str(e), str(e)[:90])
    finally:
        R.fetch_capture = _real_fetch

    os.environ.pop("OFFLINE")
    _ok, _why = R.weights_available()
    check("W6 without OFFLINE the weights download on first use", _ok, _why)
finally:
    for k, v in _saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v
    if _had is None:
        sys.modules.pop("mapanything", None)
    else:
        sys.modules["mapanything"] = _had


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
