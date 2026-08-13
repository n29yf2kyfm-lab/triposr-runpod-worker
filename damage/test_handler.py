"""Tests for the damage worker — GPU-free, dependency-free, network-free.

Run: python damage/test_handler.py

Same discipline as the other workers here: a wrong result costs a user money
(an over-charged driver, a mis-priced repair, a missed structural crack), so
the deterministic core is pinned hard. The vision model is never loaded — a
fake vision_fn returns canned JSON, which also proves the parser survives the
messy things real VLMs emit (fences, prose, percentages, synonyms).
"""
import os
import sys
import json
import types
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ---- stub the RunPod SDK before importing the handler ---------------------
# The CI runner is a bare Python by design; runpod is not installed. Same
# approach the vehicle and building workers prove.
_runpod = types.ModuleType("runpod")
_serverless = types.ModuleType("runpod.serverless")
_serverless.start = lambda *a, **k: None
_serverless.progress_update = lambda *a, **k: None
_runpod.serverless = _serverless
sys.modules.setdefault("runpod", _runpod)
sys.modules.setdefault("runpod.serverless", _serverless)

# Isolate outputs so tests never touch a real volume, and force storage
# unconfigured so the no-upload delivery path is what runs.
os.environ["DAMAGE_OUTPUT_DIR"] = tempfile.mkdtemp(prefix="damage-test-")
for _k in ("SUPABASE_URL", "SUPABASE_KEY"):
    os.environ.pop(_k, None)

import taxonomy as TAX      # noqa: E402
import severity as SEV      # noqa: E402
import repair as REP        # noqa: E402
import quality as QUAL      # noqa: E402
import analyze as AN        # noqa: E402
import fusion as FUSE       # noqa: E402
import report as REP_HTML   # noqa: E402
import compare as CMP       # noqa: E402
import validation as VAL    # noqa: E402
import handler as H         # noqa: E402
from progress import Progress  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


# ---- 1. taxonomy: panel + damage normalisation ---------------------------
check("1a exact panel id passes through",
      TAX.canonical_panel("front_left_door") == "front_left_door")
check("1b free-form maps",
      TAX.canonical_panel("left front door") == "front_left_door")
check("1c UK nearside -> left",
      TAX.canonical_panel("n/s front wing") == "front_left_fender")
check("1d windscreen -> windshield",
      TAX.canonical_panel("windscreen") == "windshield")
check("1e rear windscreen distinct",
      TAX.canonical_panel("rear windscreen") == "rear_windshield")
check("1f unknown -> None (caller falls back)",
      TAX.canonical_panel("flux capacitor") is None)
check("1g damage synonym maps",
      TAX.canonical_damage("spiderweb cracking") == "shattered_glass")
check("1h ding -> dent", TAX.canonical_damage("ding") == "dent")
check("1i severity clamps high", TAX.clamp_severity(99) == 10)
check("1j severity clamps low", TAX.clamp_severity(-4) == 1)
check("1k severity bad -> default", TAX.clamp_severity("nope") == 5)
band, colour = TAX.severity_band(9)
check("1l sev 9 is severe", band == "severe")


# ---- 2. severity scoring -------------------------------------------------
check("2a clean car scores 100", SEV.condition_score([]) == 100)

minor = [{"panel": "front_bumper", "damage_type": "scuff", "severity": 2}]
check("2b one cosmetic scuff stays high", SEV.condition_score(minor) >= 90)

severe = [{"panel": "windshield", "damage_type": "shattered_glass",
           "severity": 9}]
sc = SEV.condition_score(severe)
check("2c one severe structural item caps the score low", sc <= 40, str(sc))

# more damage must never raise the score
many = minor + severe + [{"panel": "hood", "damage_type": "dent",
                          "severity": 6}]
check("2d more damage never scores higher",
      SEV.condition_score(many) <= SEV.condition_score(severe))

# worst-caps: twenty clean-ish panels cannot bury one catastrophe
buried = ([{"panel": "front_bumper", "damage_type": "scuff", "severity": 1}] * 20
          + severe)
check("2e worst finding caps despite many minor ones",
      SEV.condition_score(buried) <= 40)

roll = SEV.summarize(many)
check("2f rollup reports a grade", roll["grade"] in ("A", "B", "C", "D", "F"))
check("2g rollup flags structural concern", roll["structural_concern"] is True)
check("2h worst finding surfaced",
      roll["worst_finding"]["damage_type"] == "shattered_glass")

# a structural finding severe enough to raise the banner can NEVER co-exist with
# an "excellent/good" headline — grade and banner must always agree.
struct6 = [{"panel": "hood", "damage_type": "dent", "severity": 6}]
r6 = SEV.summarize(struct6)
check("2i structural concern forbids an excellent/good headline",
      not (r6["structural_concern"] and r6["grade"] in ("A", "B")),
      f'grade={r6["grade"]} concern={r6["structural_concern"]} '
      f'score={r6["condition_score"]}')
check("2j structural concern caps the score at 'fair' or below",
      SEV.condition_score(struct6) <= 74, str(SEV.condition_score(struct6)))


# ---- 3. repair estimation ------------------------------------------------
f_dent = {"panel": "front_left_door", "damage_type": "dent", "severity": 6}
est = REP.estimate_one(f_dent, "us")
check("3a estimate is a range", est["low"] < est["high"])
check("3b estimate carries currency", est["currency"] == "USD")
check("3c low assumption is PDR", "dent" in est["assumption_low"].lower()
      or "paintless" in est["assumption_low"].lower())

uk = REP.estimate_one(f_dent, "uk")
check("3d region changes currency", uk["currency"] == "GBP")

asia = REP.estimate_one(f_dent, "asia")
check("3e cheaper-labour region lowers cost", asia["high"] <= est["high"])

# severity monotonicity: a worse dent never costs less
worse = REP.estimate_one({**f_dent, "severity": 9}, "us")
check("3f higher severity costs at least as much", worse["high"] >= est["high"])

# glass replacement has little low/high spread (it's replace-or-replace)
glass = REP.estimate_one({"panel": "windshield",
                          "damage_type": "shattered_glass", "severity": 8}, "us")
check("3g glass estimate is tight", glass["high"] <= glass["low"] * 2.2)

allrep = REP.estimate_all([f_dent, glass], "us")
check("3h totals sum the lines",
      allrep["total_low"] > 0 and allrep["total_high"] >= allrep["total_low"])
check("3i unknown region falls back to US, never errors",
      REP.estimate_all([f_dent], "narnia")["region"] == "us")

# hidden-damage contingency is probability-weighted and SEPARATE from the total
hid = [{"panel": "front_bumper", "damage_type": "deformation", "severity": 7,
        "hidden_damage": [{"system": "radar", "probability": 0.5,
                           "est_cost_high": 1000}]}]
ce = REP.estimate_all(hid, "us")
check("3j hidden contingency is prob-weighted (0.5*1000=500)",
      ce["hidden_contingency_high"] == 500, str(ce["hidden_contingency_high"]))
check("3k percentage probability accepted",
      REP.hidden_contingency([{"hidden_damage": [
          {"system": "x", "probability": 50, "est_cost_high": 1000}]}], "us")
      == 500)


# ---- 4. analyze: parsing the messy things VLMs emit ----------------------
raw_fenced = """Sure, here is the analysis:
```json
{"findings": [
  {"panel": "left front door", "damage_type": "ding", "severity": "7",
   "confidence": 85, "evidence": ["visible dent below the handle"],
   "hidden_damage": [{"system": "intrusion beam", "probability": "40%",
                      "rationale": "hard impact"}],
   "model_specific_risks": ["aluminium door — no PDR"]}],
 "images": [{"index": 0, "panels_visible": ["front left door"],
             "tags": ["good_lighting","reflection on panels"]}],
 "summary": "One dent."}
```
Hope that helps!"""


def fake_vision(prompt, image_urls):
    return raw_fenced


findings, images, meta = AN.analyze(["http://x/a.jpg"], {"make": "Audi"},
                                    vision_fn=fake_vision)
check("4a fenced+prose JSON parsed", len(findings) == 1)
f0 = findings[0]
check("4b panel canonicalised", f0["panel"] == "front_left_door")
check("4c damage synonym canonicalised", f0["damage_type"] == "dent")
check("4d string severity coerced", f0["severity"] == 7)
check("4e percent confidence -> 0-1", 0.8 <= f0["confidence"] <= 0.9)
check("4f percent probability -> 0-1",
      abs(f0["hidden_damage"][0]["probability"] - 0.4) < 1e-6)
check("4g region on finding", f0["region"] == "left")
check("4h image tags carried", "reflection on panels" in images[0]["tags"])
check("4i summary parsed", meta["summary"] == "One dent.")

# evidence is mandatory: a finding with none is dropped
dropped = AN.normalize_findings([
    {"panel": "hood", "damage_type": "dent", "severity": 5, "evidence": []},
    {"panel": "hood", "damage_type": "dent", "severity": 5,
     "evidence": ["clear crease"]}])
check("4j evidence-less finding dropped", len(dropped) == 1)

# driver/passenger resolves by market
lhd = AN.normalize_findings(
    [{"panel": "driver door", "damage_type": "scratch", "severity": 3,
      "evidence": ["scratch"]}], market="us")
rhd = AN.normalize_findings(
    [{"panel": "driver door", "damage_type": "scratch", "severity": 3,
      "evidence": ["scratch"]}], market="uk")
check("4k driver door -> left in US (LHD)", lhd[0]["panel"] == "front_left_door")
check("4l driver door -> right in UK (RHD)", rhd[0]["panel"] == "front_right_door")

# bad JSON raises a diagnosable error
try:
    AN._extract_json("total garbage no braces")
    check("4m garbage raises", False)
except ValueError:
    check("4m garbage raises", True)

# bbox clamped / degenerate dropped
nb = AN._bbox_or_none([0.5, 0.5, 9, 9])
check("4n bbox clamped into unit square", nb[2] <= 0.5 and nb[3] <= 0.5)
check("4o degenerate bbox -> None", AN._bbox_or_none([0.5, 0.5, 0, 0]) is None)


# ---- 5. quality + completeness -------------------------------------------
imgs = [{"tags": ["good_lighting"], "panels": ["front_bumper", "hood"]},
        {"tags": ["blurry", "water droplets"], "panels": ["rear_bumper"]}]
oq = QUAL.overall_quality(imgs)
check("5a blocking tag makes an image unusable",
      oq["images"][1]["usable"] is False)
check("5b good image usable", oq["images"][0]["usable"] is True)
check("5c water droplets is qualifying not blocking",
      "water_droplets" in oq["images"][1]["qualifying_tags"])

comp = QUAL.completeness(
    [{"panel": "front_bumper"}, {"panel": "hood"}], imgs)
check("5d completeness under 1 when sides missing",
      comp["overall_coverage"] < 1.0)
check("5e guidance names missing regions",
      any("left" in g.lower() or "right" in g.lower()
          for g in comp["guidance"]))
full_imgs = [{"panels": list(p)} for p in TAX.CAPTURE_GRID.values()]
check("5f full grid coverage is complete",
      QUAL.completeness([], full_imgs)["overall_coverage"] >= 0.9)


# ---- 6. fusion: 3D pins --------------------------------------------------
fus = FUSE.fuse(findings, glb_url="https://x/model.glb")
check("6a a pin per finding", fus["count"] == len(findings))
pin = fus["pins"][0]
check("6b pin has an anchor in the car frame", len(pin["anchor"]) == 3)
check("6c anchor within normalised extents",
      all(-0.5 <= c <= 0.5 for c in pin["anchor"]))
check("6d pin carries severity colour", pin["colour"].startswith("#"))
check("6e pin precision is honestly labelled", pin["precision"] == "panel")
check("6f fused flag set with glb", fus["fused"] is True)
check("6g without glb, pins still valid + note present",
      FUSE.fuse(findings)["fused"] is False
      and "note" in FUSE.fuse(findings))
# side panel normal points sideways, roof points up
rp = FUSE.pin_for({"panel": "roof", "damage_type": "dent", "severity": 4})
check("6h roof pin faces up", rp["normal"] == [0.0, 1.0, 0.0])
lp = FUSE.pin_for({"panel": "front_left_door", "damage_type": "dent",
                   "severity": 4})
check("6i left door pin faces -x", lp["normal"][0] == -1.0)


# ---- 7. compare: before/after diff ---------------------------------------
baseline = [
    {"panel": "front_bumper", "damage_type": "scuff", "severity": 3,
     "evidence": ["scuff"]},
    {"panel": "rear_bumper", "damage_type": "scratch", "severity": 2,
     "evidence": ["scratch"]},
]
current = [
    {"panel": "front_bumper", "damage_type": "scuff", "severity": 3,
     "evidence": ["scuff"]},                       # unchanged
    {"panel": "front_left_door", "damage_type": "dent", "severity": 6,
     "evidence": ["new dent"]},                    # new
    {"panel": "rear_bumper", "damage_type": "scratch", "severity": 6,
     "evidence": ["deeper scratch"]},              # worsened (2->6)
]
d = CMP.diff(current, baseline)
check("7a one new finding", d["summary"]["new"] == 1)
check("7b one worsened finding", d["summary"]["worsened"] == 1)
check("7c one unchanged (pre-existing)", d["summary"]["unchanged"] == 1)
check("7d chargeable = new + worsened", d["summary"]["chargeable"] == 2)
check("7e worsened carries the delta",
      d["worsened"][0]["severity_delta"] == 4)
# a baseline item not re-seen is 'resolved', never charged
d2 = CMP.diff([current[0]], baseline)
check("7f un-recaptured baseline item -> resolved",
      d2["summary"]["resolved"] == 1 and d2["summary"]["chargeable"] == 0)


# ---- 8. report render ----------------------------------------------------
report = REP_HTML.assemble(
    findings,
    repair=REP.estimate_all(findings, "us"),
    fusion=fus, vehicle={"make": "Audi", "model": "Q7", "year": 2024},
    scan_id="scan-123", generated_at="2026-01-01T00:00:00Z")
check("8a report has a condition score",
      isinstance(report["condition"]["score"], int))
html = REP_HTML.render_html(report)
check("8b html is self-contained (has <style>, no external src)",
      "<style>" in html and "http://" not in html.split("</style>")[0])
check("8c html shows the vehicle", "Audi" in html and "Q7" in html)
check("8d html shows an evidence phrase", "dent below the handle" in html)
check("8e html shows hidden damage with a percentage", "p=40%" in html)
check("8f html shows model-specific risk", "aluminium" in html.lower())
check("8g empty-findings report renders 'No damage'",
      "No damage" in REP_HTML.render_html(REP_HTML.assemble([])))


# ---- 9. validation -------------------------------------------------------
def bad(job, needle=None):
    try:
        VAL.parse_job(job)
        return False
    except VAL.InputError as e:
        return (needle in str(e)) if needle else True


check("9a inspect needs images or findings",
      bad({"mode": "inspect"}, "inspect needs"))
check("9b report needs findings", bad({"mode": "report"}, "report mode"))
check("9c compare needs a baseline",
      bad({"mode": "compare",
           "findings": [{"panel": "hood", "damage_type": "dent",
                         "severity": 5, "evidence": ["x"]}]}, "baseline"))
check("9d unknown mode rejected", bad({"mode": "teleport"}))
check("9e too many images rejected",
      bad({"image_urls": ["http://x/%d.jpg" % i for i in range(50)]}))
spec_ok = VAL.parse_job({"mode": "inspect",
                         "findings": [{"panel": "hood",
                                       "damage_type": "dent", "severity": 5,
                                       "evidence": ["x"]}],
                         "region": "uk"})
check("9f findings-only inspect validates", spec_ok["mode"] == "inspect")
check("9g region parsed", spec_ok["region"] == "uk")
# SSRF: a private-address URL is refused
check("9h SSRF blocks localhost image url",
      bad({"image_urls": ["http://127.0.0.1/a.jpg"]}, "private or reserved"))
check("9i SSRF blocks non-http scheme",
      bad({"image_urls": ["file:///etc/passwd"]}))


# ---- 10. handler: full pipeline, findings-only (no model) ----------------
job = {"id": "job-1", "input": {
    "mode": "inspect",
    "region": "uk",
    "glb_url": "https://example.com/car.glb",
    "vehicle": {"make": "Tesla", "model": "Model 3", "year": 2022,
                "market": "us"},
    "findings": [
        {"panel": "windshield", "damage_type": "shattered_glass",
         "severity": 8, "evidence": ["spiderweb cracking across the glass"],
         "hidden_damage": [{"system": "ADAS camera", "probability": 0.6,
                            "rationale": "camera mounts on the windshield",
                            "est_cost_high": 1500}],
         "model_specific_risks": ["autopilot camera recalibration required"]},
        {"panel": "front_bumper", "damage_type": "paint_chip", "severity": 3,
         "evidence": ["multiple chips on the bumper face"]},
    ]}}
resp = H.handler(job)
check("10a handler succeeds", resp.get("status") == "success")
check("10b condition score present",
      isinstance(resp["condition"]["score"], int))
check("10c repair in GBP (region=uk)", resp["repair"]["currency"] == "GBP")
check("10d hidden contingency computed (0.6*1500=900)",
      resp["repair"]["hidden_contingency_high"] == 900)
check("10e 3D fusion produced pins", resp["fusion"]["count"] == 2)
check("10f fusion bound to the glb", resp["fusion"]["fused"] is True)
check("10g report artifact delivered",
      any(k.endswith(".json") for k in resp["artifacts"]))
check("10h html artifact present + inlined",
      any(k.endswith(".html") for k in resp["artifacts"])
      and any("html_b64" in v for v in resp["artifacts"].values()))
check("10i structural concern flagged",
      resp["rollup"]["structural_concern"] is True)


# ---- 11. handler: vision path with an injected fake model ----------------
job2 = {"id": "job-2", "input": {"mode": "inspect",
                                 "image_urls": ["https://example.com/a.jpg"]}}
spec2 = VAL.parse_job(job2["input"])
prog2 = Progress(job2, "inspect")
res2 = H.run(spec2, prog2, vision_fn=fake_vision)
check("11a vision path yields findings", len(res2["findings"]) == 1)
check("11b vision path scored", res2["condition"]["score"] < 100)


# ---- 12. handler: compare mode end to end --------------------------------
job3 = {"id": "job-3", "input": {
    "mode": "compare",
    "baseline_findings": baseline,
    "findings": current}}
resp3 = H.handler(job3)
check("12a compare succeeds", resp3.get("status") == "success")
check("12b compare returns the diff buckets",
      resp3["comparison"]["summary"]["chargeable"] == 2)
check("12c compare prices only the chargeable delta",
      len(resp3["repair"]["lines"]) == 2)


# ---- 13. handler: compare needs baseline findings, not just an id --------
job4 = {"id": "job-4", "input": {
    "mode": "compare", "findings": current, "baseline_scan_id": "old-1"}}
resp4 = H.handler(job4)
check("13a missing baseline findings -> needs_baseline, not silent over-charge",
      resp4.get("status") == "needs_baseline")


# ---- 14. image fetch sends browser-like headers ---------------------------
# Regression: a live job died with "403 Forbidden" fetching a Wikimedia photo
# because _load_images sent a bare python-requests User-Agent. Many image hosts
# reject that outright, and users paste URLs from wherever their photos live.
check("14a fetch headers defined", isinstance(AN.FETCH_HEADERS, dict))
check("14b sends a non-default User-Agent",
      "Mozilla" in AN.FETCH_HEADERS.get("User-Agent", ""))
check("14c accepts image content types",
      "image/" in AN.FETCH_HEADERS.get("Accept", ""))
import inspect as _inspect  # noqa: E402
_src = _inspect.getsource(AN._load_images)
check("14d _load_images actually passes the headers",
      "headers=FETCH_HEADERS" in _src)
check("14e _load_images still raises on a bad response",
      "raise_for_status" in _src)


# ---- 15. anthropic (frontier) vision backend --------------------------------
# The recommended backend. Stub the SDK so no key or network is needed; prove
# selection, message shape, and that the deterministic pipeline consumes its
# output exactly like the local model's.
import base64 as _b64  # noqa: E402

_captured = {}


class _FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text


class _FakeMsg:
    stop_reason = "end_turn"
    def __init__(self, text): self.content = [_FakeBlock(text)]


class _FakeMessages:
    def create(self, **kw):
        _captured.update(kw)
        # echo a minimal valid inspection so analyze() parses it
        return _FakeMsg('{"findings": [{"panel":"windshield",'
                        '"damage_type":"shattered glass","severity":8,'
                        '"evidence":["spiderweb cracking"]}],'
                        '"images": [], "summary": "one crack"}')


class _FakeAnthropic:
    def __init__(self, *a, **k): self.messages = _FakeMessages()


_fake_anthropic = types.ModuleType("anthropic")
_fake_anthropic.Anthropic = _FakeAnthropic
sys.modules["anthropic"] = _fake_anthropic

check("15a anthropic backend selected by env",
      callable(AN._anthropic_backend()))

# image blocks: URL passes through as url; local file becomes base64
url_block = AN._anthropic_image_blocks(["https://example.com/a.jpg"])[0]
check("15b url image -> url source", url_block["source"]["type"] == "url")
# a real local file (this test file) -> base64 source
local_block = AN._anthropic_image_blocks([__file__])[0]
check("15c local image -> base64 source",
      local_block["source"]["type"] == "base64" and local_block["source"]["data"])

# end to end through analyze() with the stubbed SDK
import os as _os  # noqa: E402
_os.environ["DAMAGE_BACKEND"] = "anthropic"
fn = AN.get_backend()
findings_a, images_a, meta_a = AN.analyze(
    ["https://example.com/car.jpg"], {"make": "BMW"}, vision_fn=fn)
check("15d anthropic path yields a finding", len(findings_a) == 1)
check("15e finding normalised (shattered_glass)",
      findings_a[0]["damage_type"] == "shattered_glass")
check("15f system prompt passed to the model",
      "damage appraiser" in _captured.get("system", ""))
check("15g image block sent to the model",
      any(b.get("type") == "image" for b in _captured.get("messages", [{}])[0]
          .get("content", [])))
_os.environ.pop("DAMAGE_BACKEND", None)


# ---- 16. openrouter (free, no-GPU) vision backend ---------------------------
# The zero-marginal-cost path. Stub `requests` so no key and no network are
# needed; prove selection, the OpenAI-shaped payload, data-URI inlining for
# local files, that a 429 explains the free-tier caps instead of leaking a bare
# HTTP error, and that the deterministic pipeline consumes its output unchanged.
_or_captured = {}


class _FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self): return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_post(url, headers=None, data=None, timeout=None):
    _or_captured["url"] = url
    _or_captured["headers"] = headers or {}
    _or_captured["payload"] = json.loads(data)
    if _or_captured.get("force_429"):
        return _FakeResp(429)
    return _FakeResp(200, {"choices": [{"message": {"content":
        '{"findings": [{"panel":"front bumper","damage_type":"dent",'
        '"severity":5,"evidence":["crease left of the plate"]}],'
        '"images": [], "summary": "one dent"}'}}]})


_fake_requests = types.ModuleType("requests")
_fake_requests.post = _fake_post
_fake_requests.get = lambda *a, **k: _FakeResp(200)
_real_requests = sys.modules.get("requests")
sys.modules["requests"] = _fake_requests

_os.environ["DAMAGE_BACKEND"] = "openrouter"
_os.environ["OPENROUTER_API_KEY"] = "test-key"
check("16a openrouter backend selected by env", callable(AN.get_backend()))

# image blocks use the OpenAI shape; local files inline as data URIs
ob = AN._openai_image_blocks(["https://example.com/a.jpg"])[0]
check("16b url image -> image_url block",
      ob["type"] == "image_url" and ob["image_url"]["url"].startswith("https://"))
ob_local = AN._openai_image_blocks([__file__])[0]
check("16c local image -> data URI",
      ob_local["image_url"]["url"].startswith("data:"))

# end to end through analyze() with the stubbed transport
fn_or = AN.get_backend()
findings_o, images_o, meta_o = AN.analyze(
    ["https://example.com/car.jpg"], {"make": "Toyota"}, vision_fn=fn_or)
check("16d openrouter path yields a finding", len(findings_o) == 1)
check("16e finding normalised (front_bumper/dent)",
      findings_o[0]["panel"] == "front_bumper"
      and findings_o[0]["damage_type"] == "dent")
check("16f defaults to a free model tag",
      _or_captured["payload"]["model"].endswith(":free"))
check("16g system prompt sent as a system message",
      _or_captured["payload"]["messages"][0]["role"] == "system"
      and "damage appraiser" in _or_captured["payload"]["messages"][0]["content"])
check("16h api key sent as a bearer token",
      _or_captured["headers"].get("Authorization") == "Bearer test-key")

# a 429 must explain the free-tier caps, not leak a bare HTTP error
_or_captured["force_429"] = True
try:
    AN.get_backend()("p", ["https://example.com/car.jpg"])
    _429 = ""
except Exception as e:
    _429 = str(e)
check("16i 429 explains the free-tier limits",
      "req/day" in _429 or "requests/day" in _429 or "50 req" in _429, _429[:90])
_or_captured.pop("force_429")

# a missing key must name the variable rather than fail deep in the transport
_os.environ.pop("OPENROUTER_API_KEY")
try:
    AN.get_backend()("p", ["https://example.com/car.jpg"])
    _nokey = ""
except Exception as e:
    _nokey = str(e)
check("16j missing key names OPENROUTER_API_KEY",
      "OPENROUTER_API_KEY" in _nokey, _nokey[:90])

if _real_requests is not None:
    sys.modules["requests"] = _real_requests
else:
    sys.modules.pop("requests", None)
_os.environ.pop("DAMAGE_BACKEND", None)


# ---- 17. local CPU detector backend -----------------------------------------
# The self-hosted path. Everything tested here is pure arithmetic on detector
# output — no weights, no onnxruntime, no network — because that is exactly the
# half that decides what lands on a customer's invoice.
import detect as DET  # noqa: E402

SIZE = (1000, 1000)

# class mapping is generous about the spellings real datasets ship
check("17a maps dataset spellings onto the taxonomy",
      DET.DAMAGE_CLASS_MAP["glass shatter"] == "shattered_glass"
      and DET.DAMAGE_CLASS_MAP["lamp_broken"] == "lamp_damage"
      and DET.DAMAGE_CLASS_MAP["flat_tire"] == "tire_damage")

# severity rises with box area, and never leaves 1..10
small = DET.severity_from_box("dent", 0.005, 0.9)
big = DET.severity_from_box("dent", 0.30, 0.9)
check("17b bigger box -> higher severity", small < big, f"{small} < {big}")
check("17c severity stays in band",
      all(1 <= DET.severity_from_box("dent", a, 0.9) <= 10
          for a in (0.0, 0.001, 0.05, 0.5, 1.0)))

# type floors and ceilings hold: glass is never trivial, a scratch never severe
check("17d shattered glass never scores trivial",
      DET.severity_from_box("shattered_glass", 0.0001, 0.9) >= 7)
check("17e a scratch never scores catastrophic",
      DET.severity_from_box("scratch", 1.0, 0.99) <= 6)

# a low-confidence detection must not drive a severe headline
check("17f low confidence lowers severity",
      DET.severity_from_box("dent", 0.3, 0.4)
      < DET.severity_from_box("dent", 0.3, 0.9))

dets = [
    {"label": "dent", "box": [100, 100, 300, 300], "score": 0.91},
    {"label": "glass shatter", "box": [400, 100, 700, 400], "score": 0.88},
    {"label": "scratch", "box": [10, 10, 40, 40], "score": 0.10},   # below floor
    {"label": "unicorn", "box": [0, 0, 10, 10], "score": 0.99},     # unknown class
]
f17 = DET.detections_to_findings(dets, SIZE, panel_hint="hood")
check("17g low-confidence and unknown classes are dropped", len(f17) == 2,
      str(len(f17)))
check("17h panel hint applied", all(f["panel"] == "hood" for f in f17))
check("17i bbox emitted NORMALISED so it survives normalize_findings",
      f17[0]["bbox"] == [0.1, 0.1, 0.2, 0.2], str(f17[0]["bbox"]))
# the regression that made this convention explicit: pixel corners are clamped
# to the unit square by _bbox_or_none, silently losing every box
_rt = AN.normalize_findings(f17)
check("17r detector boxes survive the normaliser",
      all(x["bbox"] for x in _rt), str([x["bbox"] for x in _rt]))

# evidence must be concrete — normalize_findings DROPS evidence-less findings,
# so a detector that cannot say what it saw must not become a charge
check("17j every detection carries concrete evidence",
      all(f["evidence"] and "detector found" in f["evidence"][0] for f in f17))
survived = AN.normalize_findings(f17)
check("17k findings survive normalisation", len(survived) == 2)
check("17l normalised onto the taxonomy",
      {s["damage_type"] for s in survived} == {"dent", "shattered_glass"})

# the JSON envelope is the drop-in trick: analyze() parses it unchanged
env = DET.detections_to_json([(dets, SIZE, "hood")])
parsed = AN._extract_json(env)
check("17m emits the same envelope a VLM returns",
      "findings" in parsed and len(parsed["findings"]) == 2)

# and the whole pipeline runs off it with no branching
fn_det = lambda prompt, refs: env  # noqa: E731
fd, _id, _md = AN.analyze(["x.jpg"], {"make": "Toyota"}, vision_fn=fn_det)
roll17 = SEV.summarize(fd)
check("17n detector output scores through the real pipeline",
      len(fd) == 2 and 0 <= roll17["condition_score"] <= 100
      and roll17["structural_concern"] is True)

# box geometry -> original-image pixels
scaled = DET.parse_detections(
    [[[0, 0, 320, 320]], [0.9], [0]], (1280, 640), (640, 640), labels=["dent"])
check("17o boxes rescale to source-image pixels",
      scaled[0]["box"] == [0.0, 0.0, 640.0, 320.0], str(scaled[0]["box"]))
check("17p class ids resolve to labels", scaled[0]["label"] == "dent")

# missing model config must name the variable, not fail deep in onnxruntime
try:
    DET.detector_backend()("p", ["a.jpg"])
    _nomodel = ""
except Exception as e:
    _nomodel = str(e)
check("17q missing model names DAMAGE_DETECTOR_MODEL",
      "DAMAGE_DETECTOR_MODEL" in _nomodel, _nomodel[:80])


# ---- 18. colour-coded overlays (box / heat / light) -------------------------
# The visual surface. The colours MUST come from the same severity table that
# drives the grade — an amber box beside a "severe" finding destroys trust
# faster than a missing feature — so that agreement is pinned here.
import overlay as OV  # noqa: E402

check("18a ramp starts at the cosmetic colour and ends at severe",
      OV.ramp_colour(0.0) == OV.hex_to_rgb(TAX.SEVERITY_BANDS[0][3])
      and OV.ramp_colour(1.0) == OV.hex_to_rgb(TAX.SEVERITY_BANDS[-1][3]))
check("18b ramp is continuous and clamped",
      OV.ramp_colour(-5) == OV.ramp_colour(0.0)
      and OV.ramp_colour(99) == OV.ramp_colour(1.0))
check("18c box colour == the report's band colour for that severity",
      all(OV.severity_colour(s) == OV.hex_to_rgb(TAX.severity_band(s)[1])
          for s in range(1, 11)))

# findings with no usable box are COUNTED, never silently dropped: an empty
# overlay must not be able to read as "no damage found"
# bboxes are NORMALISED [x, y, w, h] — the product's single convention
mixed = [
    {"panel": "hood", "damage_type": "dent", "severity": 8,
     "image_index": 0, "bbox": [0.1, 0.1, 0.3, 0.4]},
    {"panel": "roof", "damage_type": "dent", "severity": 4},           # no bbox
    {"panel": "door", "damage_type": "dent", "severity": 4,
     "image_index": 0, "bbox": [0.2, 0.2, 0.0, 0.0]},                  # degenerate
    {"panel": "boot", "damage_type": "dent", "severity": 4,
     "image_index": 1, "bbox": [0.0, 0.0, 0.5, 0.5]},                  # other image
]
items, skipped = OV.drawable(mixed, (200, 120), image_index=0)
check("18d2 normalised box scales to this image's pixels",
      [round(v) for v in items[0][1]] == [20, 12, 80, 60],
      str([round(v) for v in items[0][1]]))
check("18d only usable boxes on this image are drawn", len(items) == 1,
      str(len(items)))
check("18e unusable findings are counted, not dropped", skipped == 2, str(skipped))

# class mode: categorical palette, distinct from the severity ramp
check("18f-1 each damage type gets its own colour",
      len({OV.class_colour(t) for t in
           ("dent","scratch","crack","rust","shattered_glass","tire_damage")}) == 6)
check("18f-2 finding_colour routes by mode",
      OV.finding_colour({"damage_type":"rust","severity":9}, "class")
      == OV.class_colour("rust")
      and OV.finding_colour({"damage_type":"rust","severity":9}, "severity")
      == OV.severity_colour(9))
check("18f-3 unknown damage type falls back, never crashes",
      OV.class_colour("no_such_type") == OV.hex_to_rgb(OV.DEFAULT_CLASS_COLOUR))
check("18f label names panel, damage and severity",
      OV.finding_label(mixed[0]) == "Hood / bonnet · Dent · 8",
      OV.finding_label(mixed[0]))

# rendering: exercised only if Pillow is present, so the suite stays deps-free
try:
    from PIL import Image as _PILImage
    _has_pil = True
except ImportError:
    _has_pil = False

if _has_pil:
    import tempfile as _tf
    _p = os.path.join(_tf.mkdtemp(), "t.jpg")
    _PILImage.new("RGB", (200, 120), (90, 90, 90)).save(_p)
    for _mode in ("box", "heat", "light", "both"):
        _im, _meta = OV.render(_p, mixed, mode=_mode)
        check(f"18g[{_mode}] renders at source size and reports coverage",
              _im.size == (200, 120) and _meta["drawn"] == 1
              and _meta["skipped_no_bbox"] == 2)
    # a clean car must render unchanged rather than crash on an empty mask
    _clean, _cmeta = OV.render(_p, [], mode="both")
    check("18h no findings renders cleanly", _clean.size == (200, 120)
          and _cmeta["drawn"] == 0)
    _uri, _umeta = OV.render_data_uri(_p, mixed, mode="both")
    check("18i data URI is inlineable jpeg",
          _uri.startswith("data:image/jpeg;base64,") and _umeta["bytes"] > 0)
else:
    check("18g rendering skipped (no Pillow)", True)


# ---- report ---------------------------------------------------------------
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for f in FAILED:
    print(f"  FAIL: {f}")
sys.exit(1 if FAILED else 0)
