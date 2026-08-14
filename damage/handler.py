"""Damage scanner — RunPod serverless worker.

The best of every AI car-damage app on one contract, plus the thing none of
them have: findings pinned onto the 3D model this platform already builds. See
DAMAGE_APPS.md for the teardown that shaped the feature set.

DEPLOYMENT ISOLATION (PLAN.md §2.3): shares NOTHING at runtime with the live
vehicle worker (trellis2/) or the building worker. Own endpoint, own image tag
(alamk123/damage-scan:*), own CI (damage/** only), own bucket, own output dir.
Nothing here imports from trellis2/ or building/, and neither is edited — so
this directory cannot rebuild another product's image.

THE PIPELINE (mode=inspect):
    photos ─► analyse (VLM) ─► findings
                                 ├─► condition score / grade   (severity.py)
                                 ├─► repair estimate range     (repair.py)
                                 ├─► capture quality + gaps    (quality.py)
                                 ├─► 3D pins on the model      (fusion.py)
                                 └─► report JSON + HTML        (report.py)

The vision stage is swappable and absent-safe: pass `findings` directly and the
whole deterministic half runs with no model and no GPU. That is the same
honesty the building worker practices — every stage that can run, runs; the
one that needs a model says so plainly instead of faking a result.
"""
import os
import sys
import json
import base64
import traceback

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

if os.environ.get("OFFLINE") == "1":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runpod  # noqa: E402

from validation import parse_job, InputError  # noqa: E402
from progress import Progress  # noqa: E402
import delivery  # noqa: E402
import paths  # noqa: E402
import severity as sev_mod  # noqa: E402
import repair as repair_mod  # noqa: E402
import quality as quality_mod  # noqa: E402
import fusion as fusion_mod  # noqa: E402
import report as report_mod  # noqa: E402
import compare as compare_mod  # noqa: E402

OUTPUT_DIR = paths.resolve("DAMAGE_OUTPUT_DIR", "damage-outputs",
                           "damage-outputs")


def _get_findings(spec, prog, vision_fn=None):
    """Findings for this job: supplied directly, or produced by the VLM.

    Returns (findings, images, meta). When `findings` is supplied it is
    normalised through the same path the model output takes, so a caller's
    hand-authored or externally-detected findings get the same guarantees
    (canonical panels, clamped severity, evidence enforced).
    """
    import analyze
    if spec["findings"] is None and not (spec["image_urls"]
                                         or spec["image_b64s"]):
        # A gauge-only job: readings, no photos. There is nothing for the
        # vision stage to look at, and loading a VLM to analyse zero images
        # would fail the job for no reason. Validation has already guaranteed
        # SOMETHING is present, so an empty vision result here is correct
        # rather than a silent hole.
        prog.stage("analysing", source="none", count=0)
        return [], [], {"summary": "", "vehicle_observed": {}}
    if spec["findings"] is not None:
        prog.stage("analysing", source="supplied",
                   count=len(spec["findings"]))
        market = (spec["vehicle"] or {}).get("market") \
            or (spec["vehicle"] or {}).get("region")
        findings = analyze.normalize_findings(
            spec["findings"], spec["vehicle"], market)
        return findings, [], {"summary": "", "vehicle_observed": {}}

    prog.stage("analysing", source="vision",
               images=len(spec["image_urls"]) + len(spec["image_b64s"]))
    image_refs = _prepare_images(spec)
    findings, images, meta = analyze.analyze(
        image_refs, spec["vehicle"], vision_fn=vision_fn)
    return findings, images, meta


def _prepare_images(spec):
    """URLs pass through; base64 images are written to the output dir so the
    backend can load them as files. URLs are already SSRF-checked."""
    refs = list(spec["image_urls"])
    if spec["image_b64s"]:
        out = paths.ensure(OUTPUT_DIR)
        for i, b in enumerate(spec["image_b64s"]):
            try:
                data = base64.b64decode(b)
            except Exception:
                raise InputError(f"image_b64s[{i}] is not valid base64")
            p = os.path.join(out, f"in_{i}.jpg")
            with open(p, "wb") as f:
                f.write(data)
            refs.append(p)
    return refs


def _render_overlays(spec, findings, image_refs, prog):
    """Colour-coded annotated images, one per input photo.

    Best-effort by design: a failed overlay must never fail an inspection that
    already has a valid score and price, so each image is caught individually
    and the reason is recorded instead of raised. Findings with no bbox cannot
    be drawn, and that count is reported rather than hidden — an empty overlay
    must not be able to read as "no damage found".
    """
    mode = spec.get("overlay")
    if not mode or not image_refs or not findings:
        return None
    try:
        import overlay as overlay_mod
    except Exception as e:                       # Pillow absent in some builds
        return {"rendered": 0, "error": f"{type(e).__name__}: {e}"}

    prog.stage("rendering_overlays", images=len(image_refs), mode=mode)
    out, errors = [], []
    for i, ref in enumerate(image_refs):
        try:
            uri, m = overlay_mod.render_data_uri(
                _overlay_source(ref), findings, mode=mode, image_index=i)
            out.append({"index": i, "mode": mode, "data_uri": uri,
                        "drawn": m["drawn"],
                        "skipped_no_bbox": m["skipped_no_bbox"]})
        except Exception as e:
            errors.append({"index": i, "error": f"{type(e).__name__}: {e}"})
    return {"rendered": len(out), "images": out,
            "errors": errors} if (out or errors) else None


def _overlay_source(ref):
    """A local path for `ref`; remote URLs are fetched once to a temp file."""
    s = str(ref)
    if not s.startswith(("http://", "https://")):
        return s
    import tempfile
    import requests
    from analyze import FETCH_HEADERS
    r = requests.get(s, headers=FETCH_HEADERS, timeout=30)
    r.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=".jpg")
    with os.fdopen(fd, "wb") as f:
        f.write(r.content)
    return path


def _paint_thickness(spec, findings, prog):
    """Fold paint-depth-gauge readings in beside the vision findings.

    Runs only when the caller sent `paint_readings`, and cannot fail the job:
    an inspection that already has a valid score and price must not be lost to
    a malformed reading. Returns (merged_findings, block) where `block` is the
    measured section the report renders — including the panels that came back
    CLEAN, because "we measured the roof, the hood and both doors and three of
    them read factory" is itself a result the buyer paid for.
    """
    readings = spec.get("paint_readings")
    if not readings:
        return findings, None
    try:
        import paint_thickness as pt_mod
        prog.stage("measuring", panels=len(readings))
        pt_findings, notes, ctx = pt_mod.readings_to_findings(
            readings, spec["vehicle"], paint_system=spec.get("paint_system"))
        fused = pt_mod.fuse_with_vision(findings, pt_findings)
        return fused["findings"], {
            "panels_measured": ctx["panels_measured"],
            "reference_panel": ctx["reference_panel"],
            "reference_um": ctx["reference_um"],
            "reference_basis": ctx["reference_basis"],
            "method_note": ctx["method_note"],
            "table_is_placeholder": ctx["table_is_placeholder"],
            "flagged": len(pt_findings),
            "clear": notes,
            "corroboration": fused["corroboration"],
        }
    except Exception as e:
        return findings, {"error": f"{type(e).__name__}: {e}",
                          "panels_measured": len(readings)}


def _inspect(spec, prog, vision_fn=None):
    findings, images, meta = _get_findings(spec, prog, vision_fn)
    findings, paint = _paint_thickness(spec, findings, prog)

    prog.stage("scoring", findings=len(findings))
    roll = sev_mod.summarize(findings)

    prog.stage("pricing")
    region = spec["region"] or (spec["vehicle"] or {}).get("region") \
        or (spec["vehicle"] or {}).get("market")
    repair = repair_mod.estimate_all(findings, region)

    quality = quality_mod.overall_quality(images)
    completeness = quality_mod.completeness(findings, images)

    fusion = None
    if spec["want_fusion"]:
        prog.stage("mapping_3d")
        fusion = fusion_mod.fuse(findings, spec["glb_url"])

    # Overlays need the source pixels. _prepare_images is idempotent (base64
    # inputs rewrite to the same paths), so calling it again is cheap and keeps
    # the findings path unchanged.
    overlays = None
    if spec["image_urls"] or spec["image_b64s"]:
        overlays = _render_overlays(spec, findings, _prepare_images(spec), prog)

    prog.stage("reporting")
    report = report_mod.assemble(
        findings, images=images, meta=meta, repair=repair, quality=quality,
        completeness=completeness, fusion=fusion, vehicle=spec["vehicle"],
        scan_id=spec["scan_id"])
    if overlays:
        report["overlays"] = overlays
    if paint:
        report["paint_thickness"] = paint
    return report


def _report_only(spec, prog):
    """Re-render an existing inspection: score/price/report from supplied
    findings, no vision stage. Useful after editing findings or switching
    region."""
    import analyze
    market = (spec["vehicle"] or {}).get("market") \
        or (spec["vehicle"] or {}).get("region")
    findings = analyze.normalize_findings(spec["findings"], spec["vehicle"],
                                          market)
    prog.stage("scoring", findings=len(findings))
    region = spec["region"] or market
    prog.stage("pricing")
    repair = repair_mod.estimate_all(findings, region)
    fusion = fusion_mod.fuse(findings, spec["glb_url"]) if spec["want_fusion"] \
        else None
    prog.stage("reporting")
    return report_mod.assemble(
        findings, repair=repair, fusion=fusion, vehicle=spec["vehicle"],
        scan_id=spec["scan_id"])


def _compare(spec, prog, vision_fn=None):
    """Diff the current capture against a baseline inspection."""
    current, images, meta = _get_findings(spec, prog, vision_fn)
    if spec["baseline_findings"] is None:
        # baseline_scan_id given but no findings inline: the app is expected to
        # supply the stored baseline findings. Say so rather than silently
        # treating everything as new (which would over-charge a driver).
        return {
            "status": "needs_baseline",
            "message": (f"compare needs the baseline findings for scan "
                        f"{spec['baseline_scan_id']!r}. Pass them as "
                        f"baseline_findings — this worker does not store "
                        f"prior scans."),
            "current_findings": current,
        }
    import analyze
    baseline = analyze.normalize_findings(spec["baseline_findings"])
    prog.stage("diffing", current=len(current), baseline=len(baseline))
    d = compare_mod.diff(current, baseline)

    prog.stage("reporting")
    region = spec["region"] or (spec["vehicle"] or {}).get("market")
    # price only the chargeable delta — that is what the comparison is for
    chargeable_repair = repair_mod.estimate_all(d["chargeable"], region)
    report = report_mod.assemble(
        d["chargeable"], meta=meta, repair=chargeable_repair,
        vehicle=spec["vehicle"], scan_id=spec["scan_id"])
    report["type"] = "vehicle_damage_comparison"
    report["comparison"] = d
    report["baseline_scan_id"] = spec["baseline_scan_id"]
    return report


def run(spec, prog, vision_fn=None):
    """Dispatch a validated spec to its mode. Separated from handler() so
    tests drive the full pipeline with an injected vision_fn."""
    mode = spec["mode"]
    if mode == "inspect":
        return _inspect(spec, prog, vision_fn)
    if mode == "report":
        return _report_only(spec, prog)
    if mode == "compare":
        return _compare(spec, prog, vision_fn)
    raise InputError(f"unhandled mode {mode!r}")


def _deliver_report(report, job_id, want_html):
    """Write the JSON report and (optionally) the HTML, deliver both."""
    out = paths.ensure(OUTPUT_DIR)
    artifacts = []
    json_path = os.path.join(out, f"{job_id}.report.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    artifacts.append((json_path, f"reports/{job_id}.json", None))
    if want_html:
        html_path = os.path.join(out, f"{job_id}.report.html")
        with open(html_path, "w") as f:
            f.write(report_mod.render_html(report))
        artifacts.append((html_path, f"reports/{job_id}.html", "html_b64"))
    return delivery.deliver_many(artifacts)


def handler(job):
    job_input = job.get("input", {})
    job_id = job.get("id", "local")

    try:
        spec = parse_job(job_input)
    except InputError as e:
        return {"error": str(e)}

    prog = Progress(job, spec["mode"])
    try:
        paths.ensure(OUTPUT_DIR)
        prog.stage("fetching", mode=spec["mode"])
        result = run(spec, prog)

        # Non-report control results (needs_baseline) pass straight through.
        if result.get("status") in ("needs_baseline",):
            return result

        delivered = _deliver_report(result, job_id, spec["want_html"])
        # Overlays carry multi-hundred-KB data URIs. They were present in
        # `result` for the artifacts (the JSON file and the HTML embed them);
        # popping them here, AFTER delivery, means the response body carries
        # them exactly once at the top level instead of twice — with several
        # photos the duplicate copy alone could push a response past RunPod's
        # payload limit.
        overlays = result.pop("overlays", None)
        response = {
            "status": "success",
            "mode": spec["mode"],
            "scan_id": spec["scan_id"],
            "condition": result.get("condition"),
            "rollup": result.get("rollup"),
            "findings": result.get("findings"),
            "repair": result.get("repair"),
            "completeness": result.get("completeness"),
            "quality": result.get("quality"),
            "fusion": result.get("fusion"),
            "paint_thickness": result.get("paint_thickness"),
            "overlays": overlays,
            "summary": result.get("summary"),
            "report": result,
            "artifacts": delivered,
        }
        if result.get("type") == "vehicle_damage_comparison":
            response["comparison"] = result.get("comparison")
        return response

    except InputError as e:
        return {"error": str(e)}
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
        if os.environ.get("DEBUG") == "1":
            result["traceback"] = traceback.format_exc()
        else:
            print(traceback.format_exc(), file=sys.stderr)
        return result


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
