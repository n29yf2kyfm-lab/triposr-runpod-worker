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
# The output directory is now resolved at runtime rather than hardcoded (an
# endpoint only has /runpod-volume when a volume is attached), so the
# isolation requirement is checked against the subdirectory it resolves to.
# The requirement itself is unchanged: never the vehicle worker's directory.
with open(os.path.join(HERE, "paths.py")) as f:
    src += f.read()
check("16c own output dir, not the vehicle worker's",
      "building-outputs" in src and '"/runpod-volume/outputs"' not in src)
check("16c2 the output dir is resolved, not hardcoded to a volume",
      'paths.resolve("BUILDING_OUTPUT_DIR"' in src
      and '"/runpod-volume/building-outputs")' not in src)
check("16d own default bucket",
      'SUPABASE_BUCKET", "building-scans"' in src)

# ---- Test 18: quantities and the supply contract --------------------------
# A quantity is what gets ordered and what gets charged, so a malformed one
# must fail at the door rather than turn into a delivery.
s = parse_job({"mode": "price", "quantities": {"battens": 503.3}})
check("18a quantities reach the spec", s["quantities"] == {"battens": 503.3},
      str(s["quantities"]))
check("18b price mode is reachable from quantities alone", True)

for bad, label in [({"battens": -5}, "negative"),
                   ({"battens": float("inf")}, "infinite"),
                   ({"": 5}, "unnamed"),
                   ([("battens", 5)], "not an object")]:
    try:
        parse_job({"mode": "price", "quantities": bad})
        check(f"18c {label} quantity refused", False)
    except InputError:
        check(f"18c {label} quantity refused", True)

# THE roof -> price chain. Verified against the exact quantities block a real
# RunPod roof job returned for B36 8AR. The first version of this validator
# refused zero, and a plain gable — the commonest roof in Britain — reports
# hip_m: 0 and valley_m: 0 because it genuinely has neither. That made roof
# output unpriceable, breaking the one path the two modes exist to create.
REAL_ROOF_QUANTITIES = {
    "eaves_m": 45.09, "flat_area_m2": 24.8, "hip_m": 0,
    "materials": {"battens_m": 508.5, "covering": "concrete_interlocking",
                  "covering_units": 1527, "guttering_m": 45.1,
                  "membrane_m2": 159.6, "ridge_units": 23, "valley_m": 0,
                  "waste_factor": 1.1},
    "pitch_uncertainty_deg": 5.7, "plan_area_m2": 121.09,
    "plan_area_source": "footprint_polygon", "plane_count": 3,
    "predominant_pitch_deg": 32, "sampled_plan_area_m2": 44,
    "ridge_m": 6.05, "slope_uplift_pct": 14.6, "sloped_area_m2": 138.82,
    "valley_m": 0,
}
try:
    _s = parse_job({"mode": "price", "quantities": REAL_ROOF_QUANTITIES})
    check("18c2 real roof output survives validation", True)
    check("18c3 zero-length elements are kept, not refused",
          _s["quantities"]["hip_m"] == 0)
    check("18c4 the nested materials block passes through intact",
          _s["quantities"]["materials"]["covering_units"] == 1527)
    check("18c5 a text field passes through",
          _s["quantities"]["plan_area_source"] == "footprint_polygon")
    check("18c6 the sloped area survives — the number the product exists for",
          _s["quantities"]["sloped_area_m2"] == 138.82)
except InputError as e:
    for _n in ("18c2 real roof output survives validation",
               "18c3 zero-length elements are kept, not refused",
               "18c4 the nested materials block passes through intact",
               "18c5 a text field passes through",
               "18c6 the sloped area survives — the number the product exists for"):
        check(_n, False, str(e))

# Price mode with nothing at all to work from must still refuse.
try:
    parse_job({"mode": "price"})
    check("18d price with no source of quantities refused", False)
except InputError as e:
    check("18d price with no source of quantities refused",
          "quantities" in str(e), str(e))

check("18e supply is implemented", "supply" in IMPLEMENTED, str(IMPLEMENTED))
check("18e2 valuation is implemented", "valuation" in IMPLEMENTED,
      str(IMPLEMENTED))
check("18e2b drawing is implemented", "drawing" in IMPLEMENTED,
      str(IMPLEMENTED))

# Drawing mode: the scale must never arrive already confirmed by default,
# because a confirmed scale is what unlocks quantities.
s = parse_job({"mode": "drawing", "drawing_url": "https://x/y.pdf"})
check("18e2c confirm_scale defaults to False", s["confirm_scale"] is False)
check("18e2d page defaults to the first", s["page"] == 0)
try:
    parse_job({"mode": "drawing"})
    check("18e2e drawing with nothing to measure refused", False)
except InputError as e:
    check("18e2e drawing with nothing to measure refused",
          "drawing_url" in str(e), str(e))

s = parse_job({"mode": "valuation", "postcode": "B36 8AR",
               "region": "Birmingham", "floor_area_m2": 96.0,
               "extension_m2": 20.0, "build_cost": 55_000})
check("18e3 valuation fields reach the spec",
      s["postcode"] == "B36 8AR" and s["extension_m2"] == 20.0, str(s))
check("18e4 the UKHPI region is lowercased for the API",
      s["region"] == "birmingham", str(s["region"]))

try:
    parse_job({"mode": "valuation"})
    check("18e5 valuation with no postcode refused", False)
except InputError as e:
    check("18e5 valuation with no postcode refused", "postcode" in str(e))
    check("18e6 and states the coverage limit",
          "England and Wales" in str(e), str(e))

try:
    parse_job({"mode": "valuation", "postcode": "B36 8AR",
               "property_type": "mansion"})
    check("18e7 unknown property type refused", False)
except InputError:
    check("18e7 unknown property type refused", True)
s = parse_job({"mode": "supply", "price_list_csv": "a,b\n1,2\n",
               "vat": "ex", "channel": "trade_account"})
check("18f supply fields reach the spec",
      s["vat"] == "ex" and s["channel"] == "trade_account", str(s["vat"]))
check("18g vat defaults to unknown, never to a guess",
      parse_job({"mode": "supply", "price_list_url": "u"})["vat"] == "unknown")

try:
    parse_job({"mode": "supply"})
    check("18h supply with no price list refused", False)
except InputError as e:
    check("18h supply with no price list refused", "price list" in str(e),
          str(e))

for bad, label in [({"channel": "carrier_pigeon"}, "channel"),
                   ({"vat": "maybe"}, "vat"),
                   ({"tier": "deluxe"}, "tier")]:
    try:
        parse_job(dict({"mode": "supply", "price_list_url": "u"}, **bad))
        check(f"18i unknown {label} refused", False)
    except InputError:
        check(f"18i unknown {label} refused", True)


# ---- Test 20: the worker must not fetch on a caller's behalf --------------
# Left open, a caller-supplied URL turns this endpoint into a proxy for the
# private network it sits in — cloud metadata, internal APIs, localhost — and
# the fetched content comes back in the response.
for url, label in [("file:///etc/passwd", "file scheme"),
                   ("/etc/passwd", "bare local path"),
                   ("../../etc/passwd", "relative path"),
                   ("gopher://evil/x", "gopher scheme"),
                   ("http://127.0.0.1:8080/x", "loopback"),
                   ("http://localhost/admin", "localhost by name"),
                   ("http://169.254.169.254/latest/meta-data/", "metadata"),
                   ("http://10.0.0.5/internal", "private 10/8"),
                   ("http://192.168.1.1/admin", "private 192.168/16"),
                   ("http://[::1]/x", "IPv6 loopback"),
                   ("", "empty")]:
    try:
        validation.check_fetchable_url(url, "test_url")
        check(f"20a refused: {label}", False, f"ALLOWED {url}")
    except validation.UnsafeURLError:
        check(f"20a refused: {label}", True)

check("20b an ordinary public URL is still allowed",
      validation.check_fetchable_url(
          "https://landregistry.data.gov.uk/x.csv", "u").startswith("https://"))
check("20c UnsafeURLError is an InputError, so the handler answers cleanly",
      issubclass(validation.UnsafeURLError, InputError))

_supply_src = open(os.path.join(HERE, "supply.py")).read()
check("20d supply no longer reads local paths",
      "os.path.exists(url)" not in _supply_src)
check("20e supply checks the URL before fetching",
      "check_fetchable_url" in _supply_src)
_recon_src = open(os.path.join(HERE, "reconstruct.py")).read()
check("20f reconstruct checks its URLs too",
      _recon_src.count("check_fetchable_url") >= 2)
check("20g local capture is opt-in only",
      "BUILDING_ALLOW_LOCAL_CAPTURE" in _recon_src)


# ---- Test 19: the SDK progress call must stay opt-in ----------------------
# Bought expensively on the live endpoint: every job that called
# runpod.serverless.progress_update() reached its final stage and then never
# finalised, across every mode including one that makes no network calls. The
# only job that ever returned cleanly was one rejected by validation, which
# returns before Progress is constructed. 224ms against seven minutes.
check("19a SDK progress is off by default", progress.SDK_PROGRESS is False,
      str(progress.SDK_PROGRESS))
check("19b it is controlled by an env var, not a constant",
      'os.environ.get("BUILDING_SDK_PROGRESS"' in
      open(os.path.join(HERE, "progress.py")).read())

# Stage reporting must still WORK — the logging is what makes a four-minute
# job legible, and it is what survived.
_p = progress.Progress({"id": "t"}, "supply")
_p.stage("fetching")
_p.stage("quoting")
check("19c stages are still recorded", len(_p.emitted) == 2, str(_p.emitted))
check("19d step index still advances", _p.emitted[-1]["step"] == 3,
      str(_p.emitted[-1]))
check("19e the stage plan is still reported",
      _p.emitted[-1]["steps"] == 4, str(_p.emitted[-1]))

# And publishing must never raise, whatever the SDK does.
class _Boom:
    class serverless:
        @staticmethod
        def progress_update(job, payload):
            raise RuntimeError("SDK exploded")


_saved_rp, _saved_flag = progress.runpod, progress.SDK_PROGRESS
progress.runpod, progress.SDK_PROGRESS = _Boom, True
try:
    progress.Progress({"id": "t"}, "supply").stage("fetching")
    check("19f a failing SDK never kills the job", True)
except Exception as e:
    check("19f a failing SDK never kills the job", False, str(e))
finally:
    progress.runpod, progress.SDK_PROGRESS = _saved_rp, _saved_flag


# ---- Test 17: the suite must run on a bare Python --------------------------
# CI installs nothing: these tests exist to run with no GPU, no network and
# no dependencies. A module-level `import requests` in delivery.py broke the
# whole suite on the first merge to main, so every worker module is checked
# for third-party imports outside a function.
import ast as _ast

_THIRD_PARTY = {"requests", "numpy", "torch", "cv2", "PIL", "mapanything",
                "open3d", "ifcopenshell", "scipy", "sklearn", "transformers"}
_offenders = {}
for _f in sorted(os.listdir(HERE)):
    if not _f.endswith(".py") or _f.startswith("test_"):
        continue
    _tree = _ast.parse(open(os.path.join(HERE, _f)).read())
    _bad = []
    for _node in _tree.body:            # module level only — nested is fine
        if isinstance(_node, _ast.Import):
            _bad += [n.name.split(".")[0] for n in _node.names
                     if n.name.split(".")[0] in _THIRD_PARTY]
        elif isinstance(_node, _ast.ImportFrom) and _node.module:
            if _node.module.split(".")[0] in _THIRD_PARTY:
                _bad.append(_node.module.split(".")[0])
    if _bad:
        _offenders[_f] = _bad

check("17a no module-level third-party imports", not _offenders,
      str(_offenders))
check("17b delivery imports requests lazily",
      "def _requests" in open(os.path.join(HERE, "delivery.py")).read())

# 17a only sees MODULE-level imports. The second failure on main was subtler:
# `import requests` sat at the top of a function BODY, above that function's
# own input validation, so calling it with junk raised ModuleNotFoundError
# instead of the actionable error the caller was meant to get. Validate
# first, import second — checked behaviourally, and by blocking the module
# rather than relying on CI happening to be bare, so this keeps its teeth if
# dependencies are ever installed.
class _Blocked:
    """Make `import requests` fail regardless of what is installed."""

    def find_module(self, name, path=None):        # py2-style, still honoured
        return self if name.split(".")[0] == "requests" else None

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "requests":
            raise ImportError("blocked by test 17c")
        return None


_blocker = _Blocked()
_saved = sys.modules.pop("requests", None)
sys.meta_path.insert(0, _blocker)
try:
    import reconstruct as _R

    try:
        _R.fetch_capture({}, os.path.join(tempfile.gettempdir(), "b17"))
        check("17c empty capture refused before any network import", False)
    except _R.ReconstructError as e:
        check("17c empty capture refused before any network import",
              "image_urls" in str(e), str(e))
    except ImportError as e:
        check("17c empty capture refused before any network import", False,
              f"imported before validating: {e}")

    _r = run({"mode": "roof", "address": "not a real postcode"})
    check("17d unreachable geocoder still yields an actionable error",
          "postcode" in _r.get("error", "") or "gps" in _r.get("error", ""),
          _r.get("error", "")[:160])
finally:
    sys.meta_path.remove(_blocker)
    if _saved is not None:
        sys.modules["requests"] = _saved


# ---- summary --------------------------------------------------------------
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
