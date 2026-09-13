"""Building scanner — RunPod serverless worker.

Scan a real building, reconstruct it 1:1 inside and out including the
services behind the walls, price the job, order the materials, audit the
condition, design the extension. See PLAN.md for the full spec.

DEPLOYMENT ISOLATION (PLAN.md §2.3): this worker shares NOTHING at runtime
with the live vehicle worker in trellis2/. Own endpoint, own image tag, own
CI workflow, own volume, own bucket, own output directory. Nothing here
imports from trellis2/, and trellis2/ is never edited — its CI only triggers
on trellis2/**, so this directory cannot rebuild the production vehicle
image. The duplicated helpers in validation.py and delivery.py are that
isolation, deliberately paid for.

Status: every mode validation.MODES accepts dispatches to a real module —
the table in _pipeline_available is the authoritative list — EXCEPT
condition and design, which report the phase that implements them rather
than pretending to work. reconstruct's orchestration is complete but its
model call has never been run on a GPU. Counts are deliberately not written
here: an earlier hand count ("eleven of thirteen") went stale as modes
shipped and quietly told auditors that four live surfaces did not exist, so
test_handler.py now pins the two exceptions to the dispatch table instead.

That statement is kept honest deliberately. Three forensic audits of this
code found a mode that crashed on every job, an X-ray that could not report
a hazard, and wall lengths five times over — all behind green ticks, all
found by executing rather than reading, with 1231 tests passing throughout.
"""
import os
import sys
import json
import tempfile
import traceback

# Match the environment before any heavy import, as the vehicle worker does.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

# OFFLINE=1 forbids model downloads at request time — every weight must
# already be cached (see preload_models.py). A cache miss then fails fast
# with a clear error instead of hanging on a multi-GB download mid-job.
if os.environ.get("OFFLINE") == "1":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runpod  # noqa: E402

from validation import parse_job, InputError, NoDataError  # noqa: E402
from progress import Progress  # noqa: E402
import delivery  # noqa: E402
import paths  # noqa: E402

# Own output directory — NOT the vehicle worker's /runpod-volume/outputs.
#
# Resolved against what is actually writable rather than assumed: an endpoint
# only has /runpod-volume when a network volume is attached to it, and this
# worker writes kilobytes of JSON that must not depend on that being true.
OUTPUT_DIR = paths.resolve("BUILDING_OUTPUT_DIR", "building-outputs",
                           "building-outputs")

# Modes whose geometry comes off a camera or a depth sensor, and which
# therefore have a scale that can be wrong.
#
# Everything else starts from something already dimensioned: a postcode, a
# figured drawing, a list of quantities. Asking those to "include a scale
# reference in frame" is nonsense, and printing it on every response is how
# the one job that genuinely IS unscaled gets waved through.
#
# structure, services and register take a point cloud rather than a capture,
# but that cloud carries whatever scale reconstruct gave it — so the warning
# stays relevant and they stay in.
CAPTURE_MODES = frozenset({
    "reconstruct",   # video / images in
    "structure",     # consumes a cloud whose scale it inherits
    "services",      # same, and this one is the X-ray
    "register",      # aligns two clouds; a scale error misaligns both
    "condition",     # imagery and thermal
    # A phone splat is a camera capture whose scale is exactly what this
    # warning is about — scanin has a whole function to catch a splat that
    # came back at 0.3x — and with no address to check it against, its own
    # report can only say "scale checked against nothing". It was missing
    # from this set, so the one job class that most needs the warning was
    # the one that never got it.
    "scan",
})

# Which phase implements each mode. Returned verbatim to callers hitting an
# unimplemented mode, so the API is honest about what it can do today rather
# than failing with a bare 500.
PHASE_OF_MODE = {
    "reconstruct": ("1", "MapAnything fast path, COLMAP quality path, "
                         "metric scale enforced"),
    "register":    ("1", "ICP alignment; open<->closed pairing lands in Phase 4"),
    "roof":        ("1b", "open LIDAR (EA National LIDAR Programme, ~99% of "
                          "England at 1m, free) -> roof planes, pitch, areas; "
                          "OpenDroneMap for optional drone capture"),
    "price":       ("2", "quantities from RoomPlan parametric output -> "
                         "rate card -> quote"),
    "supply":      ("2b", "basket -> merchant RFQ -> order; invoice OCR "
                          "price index"),
    "structure":   ("3", "Cloud2BIM: point cloud -> IFC walls/slabs/"
                         "openings/rooms"),
    "services":    ("4", "pipe and cable extraction -> IFC systems -> AR X-ray"),
    "condition":   ("5", "YOLO + SAM 2 defect detection -> 3D pins -> "
                         "costed remedies"),
    "design":      ("6", "procedural massing + permitted-development checks"),
    "valuation":   ("2c", "Land Registry Price Paid + UKHPI -> value, street "
                          "ceiling, extension uplift"),
    "drawing":     ("7", "2D PDF/DXF -> confirmed scale -> assisted takeoff"),
    "planning":    ("2d", "Planning Data platform -> Article 4, conservation "
                          "area, listed, green belt, flood zone, TPO -> is "
                          "this permitted development?"),
    "model":       ("3b", "drawing's figured dimensions -> walls, storeys, "
                          "roof -> OBJ + IFC + take-off"),
    "scan":        ("1", "phone splat export -> verified, oriented, "
                         "scale-checked against the mapped footprint"),
    "propose":     ("6", "address -> OSM outline + Solar roof + Street View "
                         "orientation + measured clearances -> existing house "
                         "and designed extension as GLB/OBJ/IFC"),
}


def _pipeline_available(mode):
    """True if the implementation module for this mode is importable.

    Phase 0 ships none of them; each phase adds its module and this starts
    returning True without any change here.
    """
    module = {
        "reconstruct": "reconstruct", "register": "register",
        "structure": "structure", "services": "services",
        "roof": "roof", "price": "takeoff", "supply": "supply",
        "condition": "condition", "design": "design",
        "valuation": "valuation", "drawing": "drawing",
        "planning": "planning", "model": "model3d",
        "render": "sitevisual", "propose": "propose",
        "scan": "scanin",
    }.get(mode)
    if not module:
        return False
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def _resolve_scale_source(spec):
    """Decide how this job gets metric scale.

    A building model without real dimensions is worthless and actively
    dangerous to quote or cut from, so this never silently yields "unscaled".

    LiDAR depth is metric directly and is always preferred. Failing that,
    known-object anchors: UK brick coursing (4 courses = 300mm exactly, a
    national standard visible on nearly every house, and self-averaging over
    many courses) outside, and Part M socket/switch heights (450mm / 1200mm,
    regulation-mandated) inside. See PLAN.md Part 6.
    """
    if spec["scale_source"] != "auto":
        return spec["scale_source"]
    if spec["depth_url"] or spec["roomplan_url"]:
        # RoomPlan output is LiDAR-derived and already metric.
        return "lidar"
    if spec["scale_reference_m"]:
        return "manual"
    return "anchors"


def _resolve_roof_source(spec):
    """Decide how this job gets roof geometry.

    Open LIDAR first, deliberately. The Environment Agency's National LIDAR
    Programme covers ~99% of England at 1m resolution with +/-15cm vertical
    RMSE, free and without an account. That is enough for pitch, plane areas
    and ridge/hip/valley lines — enough to price a re-roof — from an address
    alone, with no site visit, no aircraft and no CAA paperwork.

    Drone last. UK rules from January 2026 require Flyer and Operator IDs, an
    A2 CofC for closer work, and separation distances that make close roof
    surveys impractical on an ordinary residential street.
    """
    if spec["roof_source"] != "auto":
        return spec["roof_source"]
    if spec["address"] or spec["gps"]:
        return "lidar_open"
    if spec["drone_image_urls"]:
        return "drone"
    return "ground"


def _job_manifest(spec, job_id, scale_source):
    """The normalised job description. Returned on every response so a
    caller can see exactly how their input was interpreted — which is also
    what makes a wrong quantity traceable back to its inputs later."""
    frames = len(spec["image_urls"])
    return {
        "job_id": job_id,
        "mode": spec["mode"],
        "stage": spec["stage"],
        "quality": spec["quality"],
        "project_id": spec["project_id"],
        "scan_id": spec["scan_id"],
        "scale_source": scale_source,
        "inputs": {
            "video": bool(spec["video_url"]),
            "images": frames,
            "roomplan": bool(spec["roomplan_url"]),
            "depth": bool(spec["depth_url"]),
            "poses": bool(spec["poses_url"]),
            "thermal": len(spec["thermal_urls"]),
            "point_cloud": bool(spec["point_cloud_url"]),
            "ifc": bool(spec["ifc_url"]),
            "drone_images": len(spec["drone_image_urls"]),
            "address": bool(spec["address"]),
        },
        "roof_source": _resolve_roof_source(spec) if spec["mode"] == "roof"
                       else None,
        "limits": {
            "max_frames": spec["max_frames"],
            "max_points": spec["max_points"],
        },
    }


def handler(job):
    job_input = job.get("input", {})
    job_id = job.get("id", "local")

    # --- validate ------------------------------------------------------
    try:
        spec = parse_job(job_input)
    except InputError as e:
        return {"error": str(e)}

    mode = spec["mode"]
    prog = Progress(job, mode)
    scale_source = _resolve_scale_source(spec)
    manifest = _job_manifest(spec, job_id, scale_source)

    warnings = list(spec.get("warnings", []))

    # An unscaled model is the one failure that must never pass silently —
    # but only where there is something to scale. This fired on EVERY job,
    # including a roof take-off from a postcode and a valuation from an
    # address, telling the caller to "include a scale reference in frame" on
    # a job that has no frame and no camera. A warning that appears on every
    # response is a warning nobody reads, which costs exactly the times it
    # matters.
    if scale_source == "anchors" and mode in CAPTURE_MODES:
        warnings.append(
            "No LiDAR depth in this capture — scale will be derived from "
            "known-object anchors (UK brick coursing outside, Part M socket "
            "and switch heights inside). Include a scale reference in frame, "
            "and treat exported dimensions as provisional until validated.")

    try:
        paths.ensure(OUTPUT_DIR)
        prog.stage("fetching", **manifest["inputs"])

        # --- route ------------------------------------------------------
        if not _pipeline_available(mode):
            phase, description = PHASE_OF_MODE.get(mode, ("?", "unspecified"))
            # Deliberately not an exception: the contract, validation,
            # scale resolution and delivery all ran and their results are
            # useful. Say plainly what is not built yet.
            result = {
                "status": "not_implemented",
                "mode": mode,
                "phase": phase,
                "message": (f"Mode '{mode}' is implemented in Phase {phase}: "
                            f"{description}. The job contract validated "
                            f"successfully — see manifest."),
                "manifest": manifest,
            }
            if warnings:
                result["warnings"] = warnings
            _persist_manifest(manifest, job_id, result)
            return result

        # Phases 1+ dispatch here. Each module exposes run(spec, prog,
        # output_dir) and returns a list of (path, object_name, inline_key)
        # artifacts plus a result dict.
        artifacts, extra = _dispatch(mode, spec, prog)

        prog.stage("exporting")
        delivered = delivery.deliver_many(artifacts) if artifacts else {}
        for item in delivered.values():
            if item.get("warning"):
                warnings.append(item["warning"])

        result = {
            "status": "success",
            "mode": mode,
            "manifest": manifest,
            "artifacts": delivered,
        }
        result.update(extra or {})
        # MERGE the module's warnings with the handler's, never replace.
        # `extra` carries the warnings the mode module promoted precisely so
        # a caller reading only result["warnings"] cannot miss them — NOT
        # BUILDABLE and REGS FAIL from model mode, the BS 7671
        # outside-every-zone count from services. Assigning the handler-local
        # list over the top erased them on any job that also had an
        # anchor-scale or delivery warning, which for services is essentially
        # every job. Module warnings come first: they are the louder ones.
        module_warnings = list((extra or {}).get("warnings") or [])
        merged = module_warnings + [w for w in warnings
                                    if w not in module_warnings]
        if merged:
            result["warnings"] = merged
        # On EVERY path, as the comment below _fail says. It was persisted
        # only on the two failure paths, so the successful scans — the ones
        # actually worth keeping — got no durable record at all.
        _persist_manifest(manifest, job_id, result)
        return result

    except NoDataError as e:
        # NOT a failure. The input was valid, the work ran, and the answer is
        # that the source holds nothing for this address. Returning it as an
        # error made RunPod mark the job FAILED, which is most of why this
        # endpoint reads 14 completed against 13 failed with nothing broken —
        # and it left the app unable to tell a dead worker from a new-build
        # with no sale history, so it would retry forever or show a crash.
        #
        # Checked BEFORE InputError and Exception: NoDataError subclasses
        # ValueError, and several of these also subclass their module's own
        # error, so an earlier clause would swallow them.
        result = {
            "status": "no_data",
            "mode": mode,
            "reason": str(e),
            "source": type(e).__name__,
            "manifest": manifest,
        }
        if warnings:
            result["warnings"] = warnings
        _persist_manifest(manifest, job_id, result)
        return result

    except InputError as e:
        return _fail({"error": str(e)}, manifest, warnings, job_id)
    except Exception as e:
        # Tracebacks leak paths and internals to whoever calls the endpoint.
        # Ship them only under DEBUG=1; production gets the message and the
        # full trace goes to worker logs. Same policy as the vehicle worker.
        result = {"error": f"{type(e).__name__}: {e}"}
        if os.environ.get("DEBUG") == "1":
            result["traceback"] = traceback.format_exc()
        else:
            print(traceback.format_exc(), file=sys.stderr)
        return _fail(result, manifest, warnings, job_id)


def _fail(result, manifest, warnings, job_id):
    """Attach everything the caller can still act on to a failed job.

    Warnings are computed before the work starts — an anchor-derived scale,
    a first-fix scan on the fast tier — and they stay relevant when the job
    fails. Dropping them on the error path throws away the diagnosis at
    exactly the moment someone needs it.

    The manifest is persisted on every path for the same reason: it records
    how the input was interpreted, which is most valuable when the result
    was not what the caller expected.
    """
    result["manifest"] = manifest
    if warnings:
        result["warnings"] = warnings
    _persist_manifest(manifest, job_id, result)
    return result


def _dispatch(mode, spec, prog):
    """Import and run the implementation module for this mode."""
    module_name = {
        "reconstruct": "reconstruct", "register": "register",
        "structure": "structure", "services": "services",
        "roof": "roof", "price": "takeoff", "supply": "supply",
        "condition": "condition", "design": "design",
        "valuation": "valuation", "drawing": "drawing",
        "planning": "planning", "model": "model3d",
        "render": "sitevisual", "propose": "propose",
        "scan": "scanin",
    }[mode]
    module = __import__(module_name)
    return module.run(spec, prog, OUTPUT_DIR)


def _persist_manifest(manifest, job_id, result):
    """Write the job manifest beside the outputs.

    RunPod job outputs expire in about 30 minutes; a scan is worth more than
    that. Cheap insurance, and it gives every scan a durable record of how it
    was interpreted.
    """
    try:
        path = os.path.join(paths.ensure(OUTPUT_DIR),
                            f"{job_id}.manifest.json")
        with open(path, "w") as f:
            json.dump({"manifest": manifest, "result": result}, f, indent=2)
        url = delivery.upload(path, f"manifests/{job_id}.json",
                              "application/json")
        if url:
            result["manifest_url"] = url
            # Written twice deliberately. The URL is only known after the
            # upload, and without this the stored record is the one copy
            # that does not carry its own address.
            with open(path, "w") as f:
                json.dump({"manifest": manifest, "result": result}, f,
                          indent=2)
    except Exception as e:
        print(f"manifest persist skipped: {e}", file=sys.stderr)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
