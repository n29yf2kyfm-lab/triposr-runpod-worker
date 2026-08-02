"""Phase 1 — capture bundle to a metric point cloud.

    video / images / RoomPlan  ->  frames  ->  poses + dense points
                               ->  metric scale  ->  PLY + metadata

The reconstruction model itself is pretrained and used zero-shot, so nothing
here trains anything. What this module owns is everything around the model:
choosing which frames to feed it, enforcing that the result is metric, and
refusing to emit dimensions that cannot be trusted.

WHY FRAME SELECTION MATTERS MORE THAN IT SOUNDS. Feed-forward reconstruction
scales VRAM with frame count, so a 4-minute walk-around at 30fps cannot go
in whole — something must choose ~600 frames from 7,000. Choosing the
sharpest frames alone is a trap: the sharpest frames cluster where the
person stood still, so a naive "top N by sharpness" reconstructs the hallway
they paused in beautifully and loses the far side of the house entirely.
Selection therefore guarantees COVERAGE first and optimises sharpness within
it — see select_frames().
"""
import os
import sys
import json
import math
import shutil
import subprocess

import scale as scale_mod

# Feed-forward models degrade badly on motion blur: a blurred frame does not
# merely add nothing, it drags the pose solution. This is a relative floor —
# a frame is dropped when it is much softer than its neighbours, not against
# an absolute number, because absolute sharpness varies with scene and lens.
BLUR_REL_FLOOR = 0.35

# Sampling rate when decoding a walk-around. 4fps at normal walking pace
# gives roughly 40cm between viewpoints, which is comfortable overlap for
# matching without flooding the selector.
DEFAULT_SAMPLE_FPS = 4.0

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


class ReconstructError(RuntimeError):
    """Fatal: the capture cannot produce a trustworthy model."""


# ---------------------------------------------------------------------------
# Frame selection — pure, and the part worth getting right
# ---------------------------------------------------------------------------

def select_frames(sharpness, target, min_relative=BLUR_REL_FLOOR):
    """Choose `target` frame indices from a sequence of sharpness scores.

    Bucketed best-of: split the sequence into `target` equal spans and take
    the sharpest frame in each. That guarantees the selection is spread
    across the whole capture — every part of the walk-around is represented —
    while still preferring the crispest view available locally.

    Frames far softer than the sequence median are dropped outright, so a
    bucket spanning a moment of heavy blur contributes nothing rather than
    contributing rubbish.

    Returns a sorted list of indices into `sharpness`.
    """
    n = len(sharpness)
    if n == 0:
        return []
    if target <= 0:
        raise ReconstructError("target frame count must be positive")
    if n <= target:
        # Still drop the unusable ones — fewer good frames beat more bad.
        return [i for i, s in enumerate(sharpness)
                if s >= _blur_floor(sharpness, min_relative)]

    floor = _blur_floor(sharpness, min_relative)
    chosen = []
    for b in range(target):
        lo = (b * n) // target
        hi = ((b + 1) * n) // target
        if hi <= lo:
            continue
        span = range(lo, hi)
        best = max(span, key=lambda i: sharpness[i])
        if sharpness[best] >= floor:
            chosen.append(best)
    return sorted(chosen)


def _blur_floor(sharpness, min_relative):
    """Sharpness below which a frame is considered unusable."""
    ordered = sorted(sharpness)
    median = ordered[len(ordered) // 2]
    return median * min_relative


def coverage_gaps(indices, total, target):
    """Spans of the capture with no selected frame, as (start, end) pairs.

    A reconstruction is only as complete as its coverage, and a gap means a
    wall nobody has a viewpoint on. Reported so the response can say "the
    back of the property is thin" instead of silently returning a model with
    a hole in it.
    """
    if not indices or total <= 0:
        return [(0, total)] if total else []
    # A gap matters when it exceeds twice the expected spacing.
    threshold = max(2, (total // max(target, 1)) * 2)
    gaps, previous = [], -1
    for i in list(indices) + [total]:
        if i - previous > threshold:
            gaps.append((previous + 1, i - 1))
        previous = i
    return gaps


# ---------------------------------------------------------------------------
# Point cloud output
# ---------------------------------------------------------------------------

def write_ply(path, points, colours=None):
    """Write a binary-little-endian PLY. Returns the number of points.

    Binary rather than ASCII deliberately: a dense room scan runs to millions
    of points, where ASCII is roughly three times the size and slow to parse
    at both ends.
    """
    import struct

    n = len(points)
    if colours is not None and len(colours) != n:
        raise ReconstructError(
            f"colour count ({len(colours)}) does not match point count ({n})")

    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}",
              "property float x", "property float y", "property float z"]
    if colours is not None:
        header += ["property uchar red", "property uchar green",
                   "property uchar blue"]
    header.append("end_header")

    with open(path, "wb") as f:
        f.write(("\n".join(header) + "\n").encode("ascii"))
        if colours is None:
            for x, y, z in points:
                f.write(struct.pack("<fff", x, y, z))
        else:
            for (x, y, z), (r, g, b) in zip(points, colours):
                f.write(struct.pack("<fffBBB", x, y, z,
                                    int(r) & 255, int(g) & 255, int(b) & 255))
    return n


def bounds(points):
    """Axis-aligned extent, in whatever units the points are in."""
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
        "size": [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)],
    }


def sanity_check_dimensions(box, stage):
    """Reject a scaled model whose size is not physically credible.

    The last line of defence against a bad scale factor. A domestic room is
    not 40cm across and a house is not 400m; either means the scale is wrong,
    and a wrong scale is far more dangerous than a failed job because every
    downstream quantity inherits it while looking entirely plausible.
    """
    if not box:
        return []
    longest = max(box["size"])
    notes = []
    if longest < 1.0:
        raise ReconstructError(
            f"Scaled model is only {longest:.2f}m across its longest axis, "
            f"which is not a building. The scale reference was almost "
            f"certainly misread — do not quote from this.")
    if longest > 200.0:
        raise ReconstructError(
            f"Scaled model spans {longest:.0f}m, far larger than a domestic "
            f"property. Either the scale reference was misread or the "
            f"capture drifted badly.")
    if stage == "open" and longest > 60.0:
        notes.append(
            f"Open scan spans {longest:.0f}m — larger than a typical "
            f"first-fix area. Check the capture covers one property.")
    return notes


# ---------------------------------------------------------------------------
# Capture handling
# ---------------------------------------------------------------------------

def extract_frames(video_path, out_dir, fps=DEFAULT_SAMPLE_FPS):
    """Decode a walk-around video to still frames. Returns their paths."""
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "f%06d.jpg")
    cmd = [FFMPEG, "-nostdin", "-loglevel", "error", "-i", video_path,
           "-vf", f"fps={fps}", "-q:v", "2", pattern]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    except FileNotFoundError:
        raise ReconstructError(
            "ffmpeg is not available, so video captures cannot be decoded. "
            "Supply image_urls instead.")
    except subprocess.CalledProcessError as e:
        raise ReconstructError(
            f"could not decode the video: {e.stderr.decode()[:200]}")
    except subprocess.TimeoutExpired:
        raise ReconstructError("video decoding timed out — the file is too long")

    frames = sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir)
                    if f.startswith("f") and f.endswith(".jpg"))
    if not frames:
        raise ReconstructError("the video decoded to no frames")
    return frames


def sharpness_scores(frame_paths):
    """Variance of the Laplacian per frame — the standard blur measure.

    Falls back to a neutral score when OpenCV is unavailable, so selection
    degrades to even temporal sampling rather than failing outright.
    """
    try:
        import cv2
    except ImportError:
        print("opencv unavailable — selecting on spacing alone",
              file=sys.stderr)
        return [1.0] * len(frame_paths)

    scores = []
    for path in frame_paths:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        scores.append(0.0 if img is None
                      else float(cv2.Laplacian(img, cv2.CV_64F).var()))
    return scores


def _requests():
    """Imported lazily, as in every other module here — see delivery.py."""
    import requests
    return requests


def fetch_capture(spec, work_dir):
    """Assemble the capture into a list of local frame paths.

    The input is validated BEFORE the HTTP library is touched, and the local
    video path never touches it at all. An empty capture must surface as a
    ReconstructError the caller can act on; importing first turned that into
    an ImportError raised before the input had even been looked at.
    """
    if not spec.get("image_urls") and not spec.get("video_url"):
        raise ReconstructError("no video_url or image_urls in this capture")

    os.makedirs(work_dir, exist_ok=True)

    import validation

    if spec.get("image_urls"):
        requests = _requests()
        paths = []
        for i, url in enumerate(spec["image_urls"]):
            dest = os.path.join(work_dir, f"i{i:06d}.jpg")
            try:
                r = validation.fetch_checked(url, f"image_urls[{i}]",
                                             timeout=60)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(r.content)
                paths.append(dest)
            except Exception as e:
                print(f"skipped {url}: {type(e).__name__}", file=sys.stderr)
        if not paths:
            raise ReconstructError("none of the supplied images could be fetched")
        return paths

    if spec.get("video_url"):
        video = os.path.join(work_dir, "capture.mp4")
        # A local path is honoured only when the operator has explicitly
        # opted in. Left open, a caller-supplied string could name any file
        # the worker can read and have it treated as a capture.
        local_ok = os.environ.get("BUILDING_ALLOW_LOCAL_CAPTURE") == "1"
        if local_ok and os.path.exists(spec["video_url"]):
            shutil.copy(spec["video_url"], video)
        else:
            r = validation.fetch_checked(spec["video_url"], "video_url",
                                         timeout=600, stream=True)
            r.raise_for_status()
            with open(video, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        return extract_frames(video, os.path.join(work_dir, "frames"))


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def model_available():
    try:
        import mapanything  # noqa: F401
        return True
    except ImportError:
        return False


# WHICH CHECKPOINT, and why it is not the obvious one.
#
# MapAnything ships two sets of weights with DIFFERENT licences, trained on
# different data:
#
#   facebook/map-anything          CC-BY-NC 4.0  — non-commercial
#   facebook/map-anything-apache   Apache 2.0    — commercial
#
# The Apache repo is used here deliberately. The plain name is the one the
# documentation reaches for first and it scores slightly better, so taking
# it is the natural mistake — and it would quietly make the whole product
# non-commercial. This is exactly the trap the engine research flagged: a
# project's CODE licence and its CHECKPOINT licence are separate things, and
# only the checkpoint follows the training data.
MODEL_ID = os.environ.get("MAPANYTHING_MODEL", "facebook/map-anything-apache")


def run_mapanything(frame_paths, quality):
    """Feed-forward reconstruction. Returns (points, colours, info).

    MapAnything predicts metric scale, but from image content rather than
    measurement, so the result still goes through scale.py rather than being
    trusted outright.
    """
    if not model_available():
        raise ReconstructError(
            "The reconstruction model is not installed in this image. "
            "MapAnything is fetched at build time; check the build log for a "
            "failed install, or run the roof or price modes, which do not "
            "need it.")

    from mapanything.models import MapAnything
    from mapanything.utils.image import load_images
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = MapAnything.from_pretrained(MODEL_ID).to(device).eval()

    # infer() takes NORMALISED TENSORS plus a data_norm_type, not paths.
    # load_images does the resize, normalisation and packing that infer()
    # validates against. The first version of this function passed
    # [{"img_path": p}] and would have failed on the first real job.
    views = load_images(list(frame_paths))
    if not views:
        raise ReconstructError("no frames survived preprocessing")

    with torch.no_grad():
        predictions = model.infer(
            views,
            # Trades negligible speed for far more views per card. The first
            # version disabled this on the fast tier, which capped how much
            # of a property fits in one job for no real gain.
            memory_efficient_inference=True,
            use_amp=True,
            amp_dtype="bf16",
            apply_mask=True,
            mask_edges=True,
            apply_confidence_mask=(quality != "fast"),
        )

    points, colours, scale_factors = [], [], []
    for pred in predictions:
        pts = pred["pts3d"].reshape(-1, 3).float().cpu().numpy()
        keep = None
        if pred.get("mask") is not None:
            keep = pred["mask"].reshape(-1).cpu().numpy().astype(bool)
            pts = pts[keep]
        points.extend(map(tuple, pts.tolist()))

        # RGB comes back as 'img_no_norm'. 'img' is the NORMALISED tensor,
        # so colouring from it would tint the whole cloud with whatever the
        # encoder's normalisation happens to look like.
        rgb = pred.get("img_no_norm")
        if rgb is not None:
            cols = rgb.reshape(-1, 3).float().cpu().numpy()
            if cols.max() <= 1.0 + 1e-6:
                cols = cols * 255.0
            if keep is not None:
                cols = cols[keep]
            colours.extend(map(tuple, cols.astype("uint8").tolist()))

        if pred.get("metric_scaling_factor") is not None:
            try:
                scale_factors.append(
                    float(pred["metric_scaling_factor"].reshape(-1)[0]))
            except Exception:
                pass

    if not points:
        raise ReconstructError("the model returned no geometry for this capture")

    info = {"model": MODEL_ID, "views": len(predictions),
            "metric_scaling_factor": (
                round(sum(scale_factors) / len(scale_factors), 6)
                if scale_factors else None)}
    return points, (colours if len(colours) == len(points) else None), info


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def resolve_scale(spec, model_metric):
    """Establish metres per model unit, or fail."""
    source = spec.get("scale_source", "auto")

    if spec.get("scale_reference_m") and source in ("auto", "manual"):
        return scale_mod.from_manual(spec["scale_reference_m"],
                                     spec.get("scale_reference_units") or 1.0)

    if source in ("auto", "lidar"):
        if spec.get("depth_url") or spec.get("roomplan_url"):
            return scale_mod.from_lidar()
        if source == "lidar":
            raise scale_mod.ScaleError(
                "scale_source='lidar' but the capture carries no depth")

    observations = spec.get("scale_observations") or []
    if observations:
        return scale_mod.estimate_scale(
            scale_mod.Observation(o["kind"], o["measured_units"],
                                  o.get("repeats", 1))
            for o in observations)

    if model_metric:
        # MapAnything predicts metric scale itself. Usable, but it is an
        # inference from image content rather than a measurement, so it is
        # reported as such and not dressed up as a survey.
        return {
            "scale_m_per_unit": 1.0, "source": "model_metric",
            "uncertainty_pct": 8.0, "observations_used": 0,
            "observations_rejected": 0, "rejected": [], "references": [],
            "total_repeats": 0, "spread_pct": 0.0, "confidence": "fair",
            "note": "Scale predicted by the reconstruction model, not "
                    "measured. Good enough to visualise; add a scale "
                    "reference before quoting from these dimensions.",
        }

    raise scale_mod.ScaleError(
        "No way to establish metric scale for this capture. Provide LiDAR "
        "depth, a measured reference (scale_reference_m), or scale "
        "observations such as a run of brick coursing.")


def run(spec, prog, output_dir):
    """Reconstruct mode. Returns (artifacts, result_fields)."""
    scan = spec.get("scan_id") or "scan"
    work = os.path.join(output_dir, f"work_{scan}")
    os.makedirs(output_dir, exist_ok=True)

    prog.stage("fetching")
    frames = fetch_capture(spec, work)
    prog.note(f"{len(frames)} frames available")

    # --- selection ------------------------------------------------------
    prog.stage("poses")
    scores = sharpness_scores(frames)
    target = spec.get("max_frames") or 600
    chosen = select_frames(scores, target)
    if not chosen:
        raise ReconstructError(
            "Every frame in this capture was too blurred to use. Re-shoot "
            "moving slowly, pausing briefly at each viewpoint.")

    gaps = coverage_gaps(chosen, len(frames), target)
    dropped = len(frames) - len(chosen)
    prog.note(f"{len(chosen)} frames selected, {dropped} dropped",
              gaps=len(gaps))

    selected_paths = [frames[i] for i in chosen]

    # --- reconstruction --------------------------------------------------
    prog.stage("densifying")
    points, colours, model_info = run_mapanything(
        selected_paths, spec.get("quality", "fast"))
    prog.note(f"{len(points)} points reconstructed")

    if len(points) > spec.get("max_points", 8_000_000):
        step = math.ceil(len(points) / spec["max_points"])
        points = points[::step]
        colours = colours[::step] if colours else None
        prog.note(f"decimated to {len(points)} points")

    # --- scale ------------------------------------------------------------
    prog.stage("scaling")
    scale_report = resolve_scale(spec, model_metric=True)
    factor = scale_report["scale_m_per_unit"]
    if factor != 1.0:
        points = scale_mod.apply(points, factor)
    prog.note(scale_mod.describe(scale_report))

    box = bounds(points)
    notes = sanity_check_dimensions(box, spec.get("stage"))
    if scale_report.get("note"):
        notes.append(scale_report["note"])
    if gaps:
        notes.append(
            f"{len(gaps)} span(s) of the capture had no usable frame, so "
            f"parts of the property may be missing or thin. Re-walk those "
            f"areas if a dimension there matters.")

    # --- export -----------------------------------------------------------
    prog.stage("exporting")
    ply = os.path.join(output_dir, f"{scan}.ply")
    write_ply(ply, points, colours)

    meta = {
        "scan_id": scan,
        "stage": spec.get("stage"),
        "quality": spec.get("quality"),
        "frames_available": len(frames),
        "frames_used": len(chosen),
        "frames_dropped": dropped,
        "coverage_gaps": gaps,
        "points": len(points),
        "model": model_info,
        "scale": scale_report,
        "bounds_m": box,
        "notes": notes,
    }
    meta_path = os.path.join(output_dir, f"{scan}.meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    try:
        shutil.rmtree(work)
    except OSError:
        pass

    return ([(ply, f"clouds/{scan}.ply", None),
             (meta_path, f"clouds/{scan}.meta.json", None)],
            {"reconstruction": meta, "warnings": notes})
