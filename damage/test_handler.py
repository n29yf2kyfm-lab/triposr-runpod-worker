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


# ---- report ---------------------------------------------------------------
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for f in FAILED:
    print(f"  FAIL: {f}")
sys.exit(1 if FAILED else 0)
