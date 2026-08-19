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


# ---- 19. paint film thickness -----------------------------------------------
# The measured channel. This is legally the sharpest thing the product says —
# "this panel reads like it was resprayed" is a claim about a car's HISTORY —
# so the arithmetic, the fallbacks, the false positives and the WORDING are all
# pinned here. Every threshold under test is cited in paint_thickness.py's
# docstring; anything unsourced is deliberately absent rather than invented.
import paint_thickness as PT  # noqa: E402

# -- 19.1 unit conversion --------------------------------------------------
check("19a mils<->um conversion is the real 25.4 factor",
      PT.mils_to_um(4) == 101.6 and PT.um_to_mils(101.6) == 4.0)

# -- 19.2 the lookup: tiers, fallbacks, and a confidence per tier -----------
ex_model = PT.expected_range("BMW", "X5", 2019, "front_left_door")
check("19b exact model row answers, with its source attached",
      ex_model["tier"] in ("model", "model_year")
      and ex_model["min_um"] == 120 and ex_model["max_um"] == 165
      and "ETARI" in ex_model["source"])

ex_make = PT.expected_range("BMW", "i8", 2019, "front_left_door")
check("19c unknown model falls back to the make average",
      ex_make["tier"] == "make" and ex_make["min_um"] == 102)
check("19d make tier is less confident than model tier",
      ex_make["confidence"] < ex_model["confidence"])

ex_global = PT.expected_range("Hyundai", "Tucson", 2020, "hood")
check("19e no sourced Korean figure -> global default, lowest confidence",
      ex_global["tier"] == "global"
      and (ex_global["min_um"], ex_global["max_um"]) == PT.GLOBAL_DEFAULT_UM
      and ex_global["confidence"] <= 0.4)
check("19f global tier says why it answered",
      "no reference row" in ex_global["note"])

ex_old = PT.expected_range("Toyota", "Corolla", 1998, "hood")
check("19g pre-2007 widens the band and drops a tier",
      ex_old["tier"] == "make_era"
      and ex_old["max_um"] > PT.MAKE_DEFAULTS["toyota"][1])

# a conflicted source row cannot ride an exact-model match to high confidence
ex_conflict = PT.expected_range("Mercedes", "C-Class", 2018, "hood")
check("19h conflicting sources cap the confidence of an exact match",
      ex_conflict["confidence"] <= 0.45, str(ex_conflict["confidence"]))
check("19i make alias normalised (mercedes -> mercedes-benz)",
      PT.normalize_make("Mercedes") == "mercedes-benz"
      and PT.normalize_model("C-Class") == "c class")

# -- 19.3 panel class: the classic false positives --------------------------
check("19j bumper is plastic, gets its own band, not the body band",
      PT.expected_range("BMW", "X5", 2019, "front_bumper")["panel_class"]
      == "plastic_bumper")
check("19k plastic bumper band reaches the GM ADAS 330 um limit",
      PT.expected_range("BMW", "X5", 2019, "rear_bumper")["max_um"] == 330)
rock = PT.expected_range("BMW", "X5", 2019, "left_rocker")
check("19l rocker gets the anti-stonechip allowance on the upper bound only",
      rock["max_um"] == 165 + PT.ROCKER_ALLOWANCE_UM
      and rock["min_um"] == 120)
check("19m glass/lamps/wheels are not paintable surfaces",
      PT.expected_range("BMW", "X5", 2019, "windshield")["panel_class"]
      == "not_paintable")
tri = PT.expected_range("BMW", "X5", 2019, "hood", paint_system="tri_coat")
check("19n tri-coat widens the upper bound and labels the allowance DERIVED",
      tri["max_um"] == 165 + 30
      and any("derived" in a.lower() for a in tri["adjustments"]))

# -- 19.4 classifying a reading --------------------------------------------
def _verdict(panel, points, make="BMW", model="X5", year=2019, ref=None,
             ref_panel=None, **kw):
    r = PT.normalize_reading({"panel": panel, "points_um": points, **kw})
    e = PT.expected_range(make, model, year, panel)
    return r, e, PT.classify_reading(r, e, ref, ref_panel)

_r, _e, v_factory = _verdict("front_left_door", [130, 138, 142, 135])
check("19o in-band reading classifies factory",
      v_factory["class"] == "factory")

_r, _e, v_resp = _verdict("front_left_door", [305, 312, 298, 320])
check("19p 2x-factory reading classifies refinished",
      v_resp["class"] == "refinished" and v_resp["basis"] == "absolute")

# BOTH gates must open: a small absolute excess on a thin-paint car must not
# become an accusation
_r, _e, v_thin = _verdict("hood", [130, 132, 128, 131],
                          make="Volkswagen", model="Tiguan", year=2018)
check("19q +45 um over a thin factory band is inconclusive, not an accusation",
      v_thin["class"] == "inconclusive", v_thin["class"])

_r, _e, v_fill = _verdict("left_quarter_panel", [640, 655, 620, 660])
check("19r past the professional gauge's 500 um range -> filler_suspect",
      v_fill["class"] == "filler_suspect")

# no reading: opposite meaning on metal vs plastic — the classic false positive
_r, _e, v_nr_metal = _verdict("front_left_door", [], no_reading=True)
check("19s no reading on METAL is the filler signal",
      v_nr_metal["class"] == "filler_suspect")
_r, _e, v_nr_plastic = _verdict("front_bumper", [], no_reading=True)
check("19t no reading on a PLASTIC bumper is the wrong-probe signal, not filler",
      v_nr_plastic["class"] == "not_measurable"
      and any("ultrasonic" in c for c in v_nr_plastic["caveats"]))

# a bumper can never be accused of a respray on thickness alone
_r, _e, v_bump = _verdict("front_bumper", [300, 305, 295, 310])
check("19u a thick-but-legal bumper reading is never called a respray",
      v_bump["class"] != "refinished", v_bump["class"])
# every plastic-skinned panel, not just the bumpers — a painted mirror cap
# gives a magnetic gauge nothing, and that must not read as filler
check("19u2 no plastic panel can produce a filler accusation",
      all(PT.classify_reading(
              PT.normalize_reading({"panel": p, "points_um": [],
                                    "no_reading": True}),
              PT.expected_range("BMW", "X5", 2019, p))["class"]
          == "not_measurable"
          for p in ("front_bumper", "rear_bumper", "grille",
                    "left_mirror", "right_mirror")))

# -- 19.5 relative comparison beats absolute -------------------------------
# The same 200 um reads differently depending on what the rest of the car does.
_r, _e, v_rel_ok = _verdict("front_left_door", [200, 202, 198, 204],
                            make="Nowhere", model="Nothing", ref=195.0,
                            ref_panel="roof")
check("19v within 15 um of the same car's roof is factory, whatever the table says",
      v_rel_ok["class"] == "factory" and v_rel_ok["basis"] == "relative")
_r, _e, v_rel_bad = _verdict("front_left_door", [200, 202, 198, 204],
                             make="Nowhere", model="Nothing", ref=120.0,
                             ref_panel="roof")
check("19w 40+ um above the same car's reference is the red flag",
      v_rel_bad["class"] == "refinished" and v_rel_bad["basis"] == "relative")
check("19x the relative delta is reported, not just the verdict",
      abs(v_rel_bad["delta_reference_um"] - 81.0) < 1.0,
      str(v_rel_bad["delta_reference_um"]))
_r, _e, v_rel_mid = _verdict("front_left_door", [150, 152, 148, 154],
                             make="Nowhere", model="Nothing", ref=125.0,
                             ref_panel="roof")
check("19y a 25 um difference is a real difference but not a red flag",
      v_rel_mid["class"] == "inconclusive")

# -- 19.6 measurement quality and caveats ----------------------------------
_r1, _e1, v_one = _verdict("front_left_door", [305])
_r4, _e4, v_four = _verdict("front_left_door", [305, 312, 298, 320])
check("19z one point is trusted less than four across the panel",
      v_one["confidence"] < v_four["confidence"])
check("19aa PPF is always raised as an alternative explanation",
      any("protection film" in c for c in v_four["caveats"]))
_r, _e, v_ppf = _verdict("front_left_door", [305, 312, 298, 320], has_film=True)
check("19ab a known PPF panel is heavily discounted",
      v_ppf["confidence"] < v_four["confidence"] - 0.2)

# -- 19.7 reference selection ----------------------------------------------
_rd = [PT.normalize_reading(x) for x in [
    {"panel": "roof", "points_um": [120]},
    {"panel": "hood", "points_um": [125]},
    {"panel": "front_left_door", "points_um": [300]}]]
check("19ac the roof is chosen as the same-car reference",
      PT.pick_reference(_rd)[1] == "roof")
_rd2 = [PT.normalize_reading({"panel": "front_bumper", "points_um": [200]})]
check("19ad a plastic bumper is never used as the reference",
      PT.pick_reference(_rd2)[0] is None)
_rd3 = [PT.normalize_reading({"panel": "front_left_door", "points_um": [120]}),
        PT.normalize_reading({"panel": "rear_left_door", "points_um": [300]})]
check("19ae two panels cannot vote — no reference rather than a bad one",
      PT.pick_reference(_rd3)[2] == "insufficient")

# -- 19.8 findings drop into the EXISTING pipeline unchanged ---------------
session = [
    {"panel": "roof", "points_um": [118, 122, 120, 119]},
    {"panel": "hood", "points_um": [125, 121, 128, 124]},
    {"panel": "front_left_door", "points_um": [305, 312, 298, 320]},
    {"panel": "front_bumper", "points_um": [], "no_reading": True},
]
pt_f, pt_notes, pt_ctx = PT.readings_to_findings(
    session, {"make": "BMW", "model": "X5", "year": 2019})
check("19af only the flagged panel becomes a finding", len(pt_f) == 1,
      str([f["panel"] for f in pt_f]))
check("19ag factory/unmeasurable panels travel as NOTES, never as findings",
      len(pt_notes) == 3
      and {n["class"] for n in pt_notes} == {"factory", "not_measurable"})
pf = pt_f[0]
check("19ah the finding uses the new taxonomy id",
      pf["damage_type"] == "prior_refinish"
      and pf["damage_type"] in TAX.DAMAGE_TYPES)
check("19ai evidence is the measurement itself, and is concrete",
      pf["evidence"] and "µm" in pf["evidence"][0] or "um" in pf["evidence"][0])
check("19aj evidence cites the reference band and its source",
      any("ETARI" in e for e in pf["evidence"]))
check("19ak context names the reference panel and the method",
      pt_ctx["reference_panel"] == "roof" and "same vehicle" in pt_ctx["method_note"])
check("19al the built-in table is flagged as a placeholder",
      pt_ctx["table_is_placeholder"] is True)

# the shape must survive analyze.py's normaliser untouched — that is the proof
# it is the same shape a VLM finding is
_pt_rt = AN.normalize_findings(pt_f)
check("19am measured findings survive normalize_findings", len(_pt_rt) == 1
      and _pt_rt[0]["damage_type"] == "prior_refinish")

# ...and through severity and repair with no branching
check("19an a respray moves the condition score off 100",
      SEV.condition_score(pt_f) < 100)
_pt_est = REP.estimate_all(pt_f, "us")
check("19ao a respray costs NOTHING to repair — it is a value finding",
      _pt_est["total_low"] == 0 and _pt_est["total_high"] == 0)
check("19ap and says so instead of printing a fake quote",
      "no repair required" in _pt_est["lines"][0]["assumption_low"])

# filler is different: it IS a structural concern and it DOES cost money
fill_f, _, _ = PT.readings_to_findings(
    [{"panel": "roof", "points_um": [118, 122, 120, 119]},
     {"panel": "hood", "points_um": [121, 125, 119, 123]},
     {"panel": "left_quarter_panel", "points_um": [640, 655, 620, 660]}],
    {"make": "BMW", "model": "X5", "year": 2019})
check("19aq filler_suspect maps to body_filler", len(fill_f) == 1
      and fill_f[0]["damage_type"] == "body_filler")
check("19ar body_filler is a structural candidate -> raises the inspect banner",
      SEV.is_structural_concern(fill_f) is True)
check("19as filler carries a hidden-damage inference with a probability",
      fill_f[0]["hidden_damage"]
      and 0 < fill_f[0]["hidden_damage"][0]["probability"] <= 1)
check("19at filler IS priced (unlike a respray)",
      REP.estimate_all(fill_f, "us")["total_high"] > 0)

# several resprayed panels escalate — one is a scrape, three is an impact
multi, _, _ = PT.readings_to_findings(
    [{"panel": "roof", "points_um": [118, 122, 120, 119]},
     {"panel": "front_left_door", "points_um": [300, 305, 310, 302]},
     {"panel": "rear_left_door", "points_um": [295, 300, 305, 298]},
     {"panel": "left_quarter_panel", "points_um": [290, 295, 300, 292]}],
    {"make": "BMW", "model": "X5", "year": 2019})
check("19au three refinished panels score worse than one",
      len(multi) == 3
      and multi[0]["severity"] > pf["severity"], str(multi[0]["severity"]))

# -- 19.9 fusion with the vision channel -----------------------------------
vis_confirm = [{"panel": "front_left_door", "damage_type": "paint_mismatch",
                "damage_label": "Paint mismatch", "severity": 4,
                "confidence": 0.7, "evidence": ["door reads bluer than the wing"]}]
fz = PT.fuse_with_vision(vis_confirm, pt_f)
check("19av agreement keeps BOTH findings and raises both confidences",
      len(fz["findings"]) == 2
      and fz["findings"][0]["confidence"] > 0.7
      and fz["findings"][1]["confidence"] > pf["confidence"] - 1e-9)
check("19aw agreement is recorded in the audit trail",
      any(c["state"] == "confirms" for c in fz["corroboration"]))
check("19ax each channel cites the other in its evidence",
      any("Visual inspection" in e for e in fz["findings"][1]["evidence"])
      and any("thickness" in e for e in fz["findings"][0]["evidence"]))

# CONTRADICTION: the camera flagged paint work, the gauge read factory. The
# measurement must NOT delete the observation — a blended repair reads normal.
vis_contra = [{"panel": "rear_right_door", "damage_type": "paint_mismatch",
               "damage_label": "Paint mismatch", "severity": 4,
               "confidence": 0.8, "evidence": ["colour steps at the shut line"]}]
fz2 = PT.fuse_with_vision(vis_contra, pt_f)
check("19ay a contradicting measurement never deletes the visual finding",
      len(fz2["findings"]) == 2)
check("19az it lowers the visual finding's confidence instead",
      fz2["findings"][0]["confidence"] < 0.8)
check("19ba and states the contradiction in that finding's evidence",
      any("within the expected factory range" in e
          for e in fz2["findings"][0]["evidence"]))
check("19bb the contradiction is in the audit trail",
      any(c["state"] == "contradicts" for c in fz2["corroboration"]))

# thickness-only: the invisible respray, which is the whole point of the feature
fz3 = PT.fuse_with_vision([], pt_f)
check("19bc a measured finding stands alone when the camera saw nothing",
      len(fz3["findings"]) == 1
      and fz3["corroboration"][0]["state"] == "unseen")

# -- 19.10 the wording. This is the legally sensitive surface. -------------
_r, _e, _v = _verdict("front_left_door", [305, 312, 298, 320])
say_resp = PT.describe(_r, _e, _v)
check("19bd respray wording never asserts the car's history",
      "has been resprayed" not in say_resp.lower()
      and "was repainted" not in say_resp.lower())
check("19be respray wording reports the measurement first",
      "305" in say_resp or "309" in say_resp or "µm" in say_resp or "um" in say_resp)
check("19bf respray wording names the alternative explanations",
      "protection film" in say_resp and "two-tone" in say_resp)
check("19bg respray wording tells the reader what to do with it",
      "history" in say_resp.lower())

_r, _e, _v = _verdict("front_bumper", [], no_reading=True)
say_plastic = PT.describe(_r, _e, _v)
check("19bh a no-reading bumper explicitly denies the filler reading",
      "does not indicate filler" in say_plastic)

_r, _e, _v = _verdict("front_left_door", [130, 138, 142, 135])
say_ok = PT.describe(_r, _e, _v)
check("19bi a clean reading is not sold as proof of originality",
      "not proof" in say_ok)

_r, _e, _v = _verdict("left_quarter_panel", [640, 655, 620, 660])
say_fill = PT.describe(_r, _e, _v)
check("19bj filler wording sends the reader to an in-person check",
      "in person" in say_fill)

# -- 19.11 the finding renders as a MEASUREMENT, not as an observation -----
rep19 = REP_HTML.assemble(pt_f, repair=REP.estimate_all(pt_f, "us"),
                          vehicle={"make": "BMW", "model": "X5", "year": 2019},
                          generated_at="2026-01-01T00:00:00Z")
html19 = REP_HTML.render_html(rep19)
check("19bk the report shows the reading and the factory band",
      "µm" in html19 and "factory" in html19.lower())
check("19bl the report always shows what else explains the reading",
      "What else could explain" in html19)
check("19bm the report cites the reference source",
      "ETARI" in html19)

# -- 19.12 loading the owner's dataset shape -------------------------------
owner_rows = [
    {"make": "Kia", "model": "Sportage", "year": 2021, "min_um": 88,
     "max_um": 112, "avg_um": 100, "avg_mils": 3.94,
     "oem_range_mils": "3.5-4.4", "source": "MASTER unified",
     "confidence": 0.8},
    {"make": "Genesis", "model": "G70", "year": 2020,
     "expected_min_um": 95, "expected_max_um": 130,
     "source": "oem_paint_thickness", "confidence": 0.7},
    {"make": "Ghost", "model": "None", "source": "x"},      # unusable -> dropped
]
loaded = PT.load_table(owner_rows)
check("19bn owner dataset rows load onto the schema", len(loaded) == 2)
check("19bo rows without a usable band are dropped, never guessed",
      all(r["make"] != "ghost" for r in loaded))
kia = PT.expected_range("Kia", "Sportage", 2021, "hood", table=loaded)
check("19bp the loaded table answers where the placeholder could not",
      kia["tier"] == "model_year" and kia["max_um"] == 112
      and kia["confidence"] > 0.7)
check("19bq a year-scoped row does not answer for a different year",
      PT.expected_range("Kia", "Sportage", 2005, "hood",
                        table=loaded)["tier"] != "model_year")
check("19br mils ranges parse when microns are absent",
      PT._parse_mils_range("4.0 - 6.0 mils")[0] == 101.6)

# -- 19.13 taxonomy edits did not break the existing vocabulary ------------
check("19bs 'respray' now routes to the measured id, not paint_mismatch",
      TAX.canonical_damage("respray") == "prior_refinish")
check("19bt visual colour language still routes to paint_mismatch",
      TAX.canonical_damage("colour mismatch between panels") == "paint_mismatch"
      and TAX.canonical_damage("overspray on the trim") == "paint_mismatch")
check("19bu 'bondo' routes to body_filler",
      TAX.canonical_damage("bondo under the paint") == "body_filler")


# ---- 20. paint thickness through the real handler ---------------------------
# The whole point of matching analyze.py's finding shape is that NOTHING
# downstream needs a branch. This runs gauge readings through the actual job
# path — validate, score, price, pin in 3D, render — to prove that.
job20 = {"id": "job-20", "input": {
    "mode": "inspect",
    "vehicle": {"make": "BMW", "model": "X5", "year": 2019, "market": "us"},
    "paint_readings": [
        {"panel": "roof", "points_um": [118, 122, 120, 119]},
        {"panel": "hood", "points_um": [125, 121, 128, 124]},
        {"panel": "front_left_door", "points_um": [305, 312, 298, 320]},
        {"panel": "front_bumper", "points_um": [], "no_reading": True},
    ],
    "findings": [
        {"panel": "front_left_door", "damage_type": "paint_mismatch",
         "severity": 4, "confidence": 0.7,
         "evidence": ["door reads a shade bluer than the front wing"]},
    ]}}
resp20 = H.handler(job20)
check("20a gauge readings run through the real handler",
      resp20.get("status") == "success", str(resp20)[:160])
check("20b the measured finding joined the vision finding",
      len(resp20["findings"]) == 2
      and {f["damage_type"] for f in resp20["findings"]}
      == {"paint_mismatch", "prior_refinish"})
check("20c the paint block reports what was measured AND what read clean",
      resp20["paint_thickness"]["panels_measured"] == 4
      and resp20["paint_thickness"]["flagged"] == 1
      and len(resp20["paint_thickness"]["clear"]) == 3)
check("20d the reference panel is named in the output",
      resp20["paint_thickness"]["reference_panel"] == "roof")
check("20e corroboration between the two channels is recorded",
      any(c["state"] == "confirms"
          for c in resp20["paint_thickness"]["corroboration"]))
check("20f a respray does not inflate the repair estimate",
      resp20["repair"]["total_high"] ==
      REP.estimate_all([f for f in resp20["findings"]
                        if f["damage_type"] == "paint_mismatch"],
                       "us")["total_high"])
check("20g measured findings still get a 3D pin",
      resp20["fusion"]["count"] == 2)
_h20 = _b64.b64decode(
    next(v["html_b64"] for v in resp20["artifacts"].values()
         if "html_b64" in v)).decode()
check("20h the rendered report has the gauge section",
      "Paint depth gauge" in _h20)
check("20i clean panels are printed, not only failures",
      "Roof" in _h20 and "Hood" in _h20)

# a gauge-only job — no photos at all — is a complete inspection
job21 = {"id": "job-21", "input": {
    "mode": "inspect",
    "vehicle": {"make": "Toyota", "model": "Camry", "year": 2020},
    "paint_readings": [
        {"panel": "roof", "points_um": [105, 108, 103, 106]},
        {"panel": "front_left_fender", "points_um": [104, 107, 102, 105]},
        {"panel": "front_left_door", "points_um": [101, 104, 99, 103]},
    ]}}
resp21 = H.handler(job21)
check("20j readings alone are a valid inspection (no photos required)",
      resp21.get("status") == "success")
check("20k a car that measures factory throughout still scores 100",
      resp21["condition"]["score"] == 100
      and resp21["paint_thickness"]["flagged"] == 0)

# a malformed reading must never lose an otherwise-valid inspection
job22 = {"id": "job-22", "input": {
    "mode": "inspect",
    "paint_readings": ["not a reading at all", {"panel": None}],
    "findings": [{"panel": "hood", "damage_type": "dent", "severity": 5,
                  "evidence": ["crease"]}]}}
resp22 = H.handler(job22)
check("20l a malformed reading degrades, never fails the job",
      resp22.get("status") == "success" and len(resp22["findings"]) >= 1)
# ...and, the sharper point: a broken payload must never become the gravest
# claim the module can make. "The gauge would not read" is diagnostic; "the
# field was missing" is not, and conflating them accused a car of filler on
# the strength of a typo.
check("20m a malformed reading is NOT read as the filler signal",
      all(f["damage_type"] != "body_filler" for f in resp22["findings"]),
      str([f["damage_type"] for f in resp22["findings"]]))
_bad = PT.normalize_reading({"panel": "hood"})
check("20n a missing value is invalid, not a no-reading",
      _bad["valid"] is False and _bad["no_reading"] is False)
_explicit = PT.normalize_reading({"panel": "hood", "no_reading": True})
check("20o an EXPLICIT no-reading stays diagnostic",
      _explicit["valid"] is True and _explicit["no_reading"] is True)
check("20p and only the explicit one reaches filler_suspect",
      PT.classify_reading(_explicit,
                          PT.expected_range("BMW", "X5", 2019, "hood"))["class"]
      == "filler_suspect"
      and PT.classify_reading(_bad,
                              PT.expected_range("BMW", "X5", 2019, "hood"))
      ["class"] == "not_measurable")


# ---- RF-DETR ONNX output contract -----------------------------------------
# These pin the real exported model's format, verified against
# detector/v8-6class/rfdetr-base.onnx:
#     dets   (1, 300, 4)  normalised cx, cy, w, h
#     labels (1, 300, 7)  raw logits
# The generic parser assumed pixel x1,y1,x2,y2 corners plus ready-made scores
# and was wrong in three ways at once, silently: it read centres as corners and
# treated negative logits as confidences, so nothing ever cleared the floor and
# nothing ever raised. Every assertion here is a way that failure could return.
import numpy as _np                                                   # noqa: E402

_L = ["_placeholder_", "crack_glass", "dent", "lamp_wheel", "rust_paint",
      "scratch_scuff", "structural"]
_dets = _np.zeros((1, 3, 4), dtype="float32")
_dets[0, 0] = [0.5, 0.5, 0.2, 0.4]      # centred, 20% x 40%
_dets[0, 1] = [0.25, 0.25, 0.1, 0.1]
_dets[0, 2] = [0.9, 0.9, 0.05, 0.05]
_log = _np.full((1, 3, 7), -9.0, dtype="float32")
_log[0, 0, 2] = 3.0                      # dent, sigmoid 0.953
_log[0, 1, 5] = 1.0                      # scratch_scuff, sigmoid 0.731
_out = DET.parse_detections([_dets, _log], (1000, 500), (560, 560), _L, 0.3)

check("21a rfdetr output shape is recognised", DET._is_rfdetr([_dets, _log]))
check("21b a (boxes,scores,labels) triple is NOT taken for rfdetr",
      not DET._is_rfdetr([_dets, _log, _log]))
check("21c cxcywh becomes pixel corners on the ORIGINAL frame",
      _out and _out[0]["box"] == [400.0, 150.0, 600.0, 350.0],
      str(_out[0]["box"]) if _out else "none")
check("21d logits become probabilities through a sigmoid",
      _out and abs(_out[0]["score"] - 0.9525741) < 1e-5)
check("21e the class index survives dropping the placeholder",
      _out and _out[0]["label"] == "dent")
check("21f a second class maps correctly too",
      len(_out) > 1 and _out[1]["label"] == "scratch_scuff")
check("21g queries below the floor are dropped", len(_out) == 2,
      f"{len(_out)} kept")
# The placeholder must never win a query, or a detection arrives with no class.
_ph = _np.full((1, 1, 7), -9.0, dtype="float32")
_ph[0, 0, 0] = 5.0
check("21h the reserved placeholder can never be predicted",
      DET.parse_detections([_dets[:, :1], _ph], (100, 100), (560, 560),
                           _L, 0.3) == [])
# A normalised box must not be scaled by the model/original ratio as well.
_one = _np.array([[[0.5, 0.5, 1.0, 1.0]]], dtype="float32")
_onel = _np.full((1, 1, 7), -9.0, dtype="float32")
_onel[0, 0, 1] = 3.0
_full = DET.parse_detections([_one, _onel], (800, 600), (560, 560), _L, 0.3)
check("21i a full-frame box maps to the full frame, not a scaled one",
      _full and _full[0]["box"] == [0.0, 0.0, 800.0, 600.0],
      str(_full[0]["box"]) if _full else "none")


# ---- report ---------------------------------------------------------------
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for f in FAILED:
    print(f"  FAIL: {f}")
sys.exit(1 if FAILED else 0)
