"""Tests for the building worker — no GPU, no network, seconds to run.

Same approach the vehicle worker proved: stub the heavy modules before
importing the handler, so every bit of contract logic (validation, clamping,
scale resolution, routing, delivery, error handling) is testable in CI.

Run: python building/test_handler.py
"""
import os
import sys
import json
import types
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ---- stub heavy modules before importing the handler ----------------------
_runpod = types.ModuleType("runpod")
_serverless = types.ModuleType("runpod.serverless")
_serverless.start = lambda *a, **k: None
_serverless.progress_update = lambda *a, **k: None
_runpod.serverless = _serverless
sys.modules.setdefault("runpod", _runpod)
sys.modules.setdefault("runpod.serverless", _serverless)

# Isolate outputs so tests never touch a real volume.
_TMP = tempfile.mkdtemp(prefix="building-test-")
os.environ["BUILDING_OUTPUT_DIR"] = _TMP
# Ensure storage is unconfigured so tests exercise the no-upload path.
for _k in ("SUPABASE_URL", "SUPABASE_KEY"):
    os.environ.pop(_k, None)

import validation  # noqa: E402
from validation import parse_job, InputError  # noqa: E402
import delivery  # noqa: E402
import progress  # noqa: E402
import handler as H  # noqa: E402

# delivery caches env at import; force the unconfigured state.
delivery.SUPABASE_URL = ""
delivery.SUPABASE_KEY = ""

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
    else:
        FAILED.append(f"{name}{' — ' + detail if detail else ''}")


def run(job_input, job_id="test"):
    return H.handler({"id": job_id, "input": job_input})


# ---- Test 1: empty / malformed input -------------------------------------
r = run({})
check("1a empty input errors", "error" in r, str(r)[:120])
r = run({"mode": "reconstruct"})
check("1b reconstruct without capture errors", "error" in r)
check("1c error names the accepted fields",
      "video_url" in r.get("error", ""), r.get("error", ""))
r = H.handler({"id": "t", "input": "not-a-dict"})
check("1d non-dict input errors", "error" in r)

# ---- Test 2: unknown enum values are rejected with the allowed list -------
try:
    parse_job({"mode": "teleport"})
    check("2a bad mode rejected", False)
except InputError as e:
    check("2a bad mode rejected", True)
    check("2b bad mode lists valid modes", "reconstruct" in str(e), str(e))

try:
    parse_job({"mode": "reconstruct", "video_url": "u", "quality": "ultra"})
    check("2c bad quality rejected", False)
except InputError as e:
    check("2c bad quality rejected", True)

# ---- Test 3: clamping stops a caller OOMing the worker -------------------
s = parse_job({"mode": "reconstruct", "video_url": "u",
               "max_frames": 999_999, "max_points": 999_999_999})
check("3a max_frames clamped", s["max_frames"] == validation.MAX_FRAMES,
      str(s["max_frames"]))
check("3b max_points clamped", s["max_points"] == validation.MAX_POINTS,
      str(s["max_points"]))
s = parse_job({"mode": "reconstruct", "video_url": "u", "max_frames": -5})
check("3c max_frames floored", s["max_frames"] == 2, str(s["max_frames"]))

try:
    parse_job({"mode": "reconstruct", "video_url": "u", "max_frames": "lots"})
    check("3d non-numeric rejected", False)
except InputError as e:
    check("3d non-numeric rejected", "max_frames" in str(e), str(e))

# ---- Test 4: image list cap -----------------------------------------------
try:
    parse_job({"mode": "reconstruct",
               "image_urls": ["u"] * (validation.MAX_FRAMES + 1)})
    check("4a oversized image list rejected", False)
except InputError as e:
    check("4a oversized image list rejected", True)
    check("4b cap error suggests a remedy", "tiling" in str(e), str(e))

s = parse_job({"mode": "reconstruct", "image_urls": "single-string"})
check("4c bare string coerced to list", s["image_urls"] == ["single-string"])

# ---- Test 5: scale resolution — the safety-critical path ------------------
s = parse_job({"mode": "reconstruct", "video_url": "u"})
check("5a no depth -> anchors", H._resolve_scale_source(s) == "anchors")

s = parse_job({"mode": "reconstruct", "video_url": "u", "depth_url": "d"})
check("5b depth -> lidar", H._resolve_scale_source(s) == "lidar")

s = parse_job({"mode": "reconstruct", "roomplan_url": "r"})
check("5c roomplan -> lidar", H._resolve_scale_source(s) == "lidar")

s = parse_job({"mode": "reconstruct", "video_url": "u",
               "scale_reference_m": 0.9})
check("5d manual reference -> manual", H._resolve_scale_source(s) == "manual")

s = parse_job({"mode": "reconstruct", "video_url": "u",
               "scale_source": "gps"})
check("5e explicit source honoured", H._resolve_scale_source(s) == "gps")

# The anchor path must WARN — an unscaled model is dangerous to quote from.
r = run({"mode": "reconstruct", "video_url": "u"})
check("5f anchor scale warns", any("anchor" in w.lower()
                                   for w in r.get("warnings", [])),
      str(r.get("warnings")))
r = run({"mode": "reconstruct", "roomplan_url": "r"})
check("5g lidar scale does not warn about anchors",
      not any("anchor" in w.lower() for w in r.get("warnings", [])))

# ---- Test 6: open (first-fix) scans warn on the fast tier -----------------
# The wall cannot be recaptured once boarded, so a thin-services miss is
# permanent. Must be flagged.
s = parse_job({"mode": "reconstruct", "video_url": "u",
               "stage": "open", "quality": "fast"})
check("6a open+fast warns", any("boarded" in w for w in s.get("warnings", [])),
      str(s.get("warnings")))
s = parse_job({"mode": "reconstruct", "video_url": "u",
               "stage": "open", "quality": "survey"})
check("6b open+survey does not warn", not s.get("warnings"))

# ---- Test 7: per-mode required inputs ------------------------------------
cases = [
    ({"mode": "structure"}, "point_cloud_url"),
    ({"mode": "register", "point_cloud_url": "p"}, "registration_target"),
    ({"mode": "price"}, "ifc_url"),
    ({"mode": "condition"}, "image_urls"),
    ({"mode": "design"}, "ifc_url"),
    ({"mode": "roof"}, "address"),
]
for job_input, expected in cases:
    r = run(job_input)
    check(f"7 {job_input['mode']} requires {expected}",
          "error" in r and expected in r["error"], str(r)[:140])

# ---- Test 8: routing ------------------------------------------------------
# Implemented modes dispatch; the rest report the phase that builds them,
# so the API is honest about what it can do today.
IMPLEMENTED = {m for m in H.PHASE_OF_MODE if H._pipeline_available(m)}
check("8-0 roof is implemented", "roof" in IMPLEMENTED, str(IMPLEMENTED))

for mode, (phase, _desc) in H.PHASE_OF_MODE.items():
    if mode in IMPLEMENTED:
        continue
    job_input = {
        "mode": mode, "video_url": "u", "point_cloud_url": "p",
        "ifc_url": "i", "image_urls": ["a"], "registration_target": "scan1",
        "address": "12 Acacia Avenue",
    }
    r = run(job_input)
    check(f"8 {mode} routed", r.get("status") == "not_implemented",
          str(r)[:120])
    check(f"8 {mode} reports phase {phase}", r.get("phase") == phase)
    check(f"8 {mode} returns a manifest", "manifest" in r)

# An implemented mode that cannot reach its data must fail with an
# actionable message, not a traceback — the worker has no network here.
r = run({"mode": "roof", "address": "not a real postcode"})
check("8-1 roof dispatches for real", "error" in r, str(r)[:120])
check("8-2 roof error is actionable",
      "postcode" in r.get("error", "") or "gps" in r.get("error", ""),
      r.get("error", "")[:160])
check("8-3 no traceback leaked", "traceback" not in r)

# ---- Test 8b: roof source resolution -------------------------------------
# Open LIDAR must win whenever an address or GPS is available: it covers
# ~99% of England at 1m free, so most roofs need no site visit and no drone.
s = parse_job({"mode": "roof", "address": "12 Acacia Avenue"})
check("8b-1 address -> open lidar", H._resolve_roof_source(s) == "lidar_open")
s = parse_job({"mode": "roof", "gps": {"lat": 51.5, "lon": -0.1}})
check("8b-2 gps -> open lidar", H._resolve_roof_source(s) == "lidar_open")
s = parse_job({"mode": "roof", "drone_image_urls": ["d1", "d2"]})
check("8b-3 drone imagery -> drone", H._resolve_roof_source(s) == "drone")
s = parse_job({"mode": "roof", "image_urls": ["g1"]})
check("8b-4 ground imagery only -> ground",
      H._resolve_roof_source(s) == "ground")
# An address plus drone imagery still prefers the free, instant path.
s = parse_job({"mode": "roof", "address": "12 Acacia Avenue",
               "drone_image_urls": ["d1"]})
check("8b-5 address beats drone", H._resolve_roof_source(s) == "lidar_open")
s = parse_job({"mode": "roof", "address": "x", "roof_source": "drone"})
check("8b-6 explicit source honoured", H._resolve_roof_source(s) == "drone")
r = run({"mode": "roof", "address": "12 Acacia Avenue"})
check("8b-7 roof source in manifest",
      r["manifest"]["roof_source"] == "lidar_open", str(r["manifest"])[:160])
r = run({"mode": "reconstruct", "video_url": "u"})
check("8b-8 roof source absent for other modes",
      r["manifest"]["roof_source"] is None)

# ---- Test 9: the manifest reflects the input faithfully ------------------
r = run({"mode": "reconstruct", "image_urls": ["a", "b", "c"],
         "thermal_urls": ["t"], "project_id": "42 ", "stage": "open",
         "quality": "survey"}, job_id="job-9")
m = r["manifest"]
check("9a counts images", m["inputs"]["images"] == 3)
check("9b counts thermal", m["inputs"]["thermal"] == 1)
check("9c trims project_id", m["project_id"] == "42")
check("9d records stage", m["stage"] == "open")
check("9e records quality", m["quality"] == "survey")
check("9f records job id", m["job_id"] == "job-9")
check("9g records scale source", m["scale_source"] == "anchors")

# ---- Test 10: manifest persisted on every path ---------------------------
# The manifest records how the input was interpreted, which matters most
# when the job did NOT do what the caller expected — so it is written
# whether the job succeeded, was unimplemented, or failed outright.
path = os.path.join(_TMP, "job-9.manifest.json")
check("10a manifest written", os.path.exists(path))
r = run({"mode": "reconstruct", "video_url": "u"}, job_id="job-fail")
check("10c manifest written even when the job fails",
      os.path.exists(os.path.join(_TMP, "job-fail.manifest.json")),
      str(r)[:100])
check("10d failed job still carries its warnings",
      any("anchor" in w.lower() for w in r.get("warnings", [])),
      str(r.get("warnings")))
if os.path.exists(path):
    with open(path) as f:
        saved = json.load(f)
    check("10b manifest json valid", saved["manifest"]["job_id"] == "job-9")

# ---- Test 11: delivery size gating ---------------------------------------
small = os.path.join(_TMP, "small.ply")
with open(small, "wb") as f:
    f.write(b"x" * 1000)
d = delivery.deliver(small, "test/small.ply", inline_key="ply_b64")
check("11a small file inlined", "ply_b64" in d)
check("11b no warning for small file", "warning" not in d)

big = os.path.join(_TMP, "big.ply")
with open(big, "wb") as f:
    f.write(b"x" * (delivery.MAX_INLINE_BYTES + 10))
d = delivery.deliver(big, "test/big.ply", inline_key="ply_b64")
check("11c large file not inlined", "ply_b64" not in d)
check("11d large file undeliverable warns loudly", "warning" in d, str(d)[:160])
check("11e warning names the risk",
      "lost when the worker recycles" in d.get("warning", ""))

# ---- Test 12: content types for building formats -------------------------
check("12a ifc content type",
      delivery.content_type_for("m.ifc") == "application/x-step")
check("12b glb content type",
      delivery.content_type_for("m.glb") == "model/gltf-binary")
check("12c unknown falls back",
      delivery.content_type_for("m.zzz") == "application/octet-stream")

# ---- Test 13: upload is safe when unconfigured ---------------------------
check("13a storage reports unconfigured", not delivery.storage_configured())
check("13b upload returns None, does not raise",
      delivery.upload(small, "x/y.ply") is None)
check("13c upload of missing file returns None",
      delivery.upload(os.path.join(_TMP, "nope.ply"), "x/y.ply") is None)

# ---- Test 14: progress staging -------------------------------------------
p = progress.Progress({"id": "t"}, "reconstruct")
p.stage("fetching")
p.stage("poses")
p.note("142 frames")
check("14a stages advance", p.emitted[1]["step"] == 2, str(p.emitted[1]))
check("14b step count exposed", p.emitted[0]["steps"] == 6)
check("14c notes do not advance", p.emitted[2]["stage"] == "note")
check("14d every mode has a stage plan",
      all(m in progress.STAGE_PLANS for m in validation.MODES),
      str(set(validation.MODES) - set(progress.STAGE_PLANS)))

# ---- Test 15: errors never leak tracebacks without DEBUG -----------------
def _boom(*a, **k):
    raise RuntimeError("internal detail /secret/path")


_orig = H._pipeline_available
H._pipeline_available = _boom
os.environ.pop("DEBUG", None)
r = run({"mode": "reconstruct", "video_url": "u"})
check("15a error returned", "error" in r)
check("15b no traceback without DEBUG", "traceback" not in r)
os.environ["DEBUG"] = "1"
r = run({"mode": "reconstruct", "video_url": "u"})
check("15c traceback under DEBUG", "traceback" in r)
os.environ.pop("DEBUG", None)
H._pipeline_available = _orig

# ---- Test 16: isolation from the live vehicle worker ---------------------
# PLAN.md §2.3 — the single constraint that protects the earning product.
src = ""
for name in ("handler.py", "validation.py", "delivery.py", "progress.py"):
    with open(os.path.join(HERE, name)) as f:
        src += f.read()
check("16a no import of trellis2", "import trellis2" not in src)
check("16b no trellis2 path insertion", "/app/TRELLIS" not in src)
check("16c own output dir, not the vehicle worker's",
      "/runpod-volume/building-outputs" in src
      and '"/runpod-volume/outputs"' not in src)
check("16d own default bucket",
      'SUPABASE_BUCKET", "building-scans"' in src)

# ---- summary --------------------------------------------------------------
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
