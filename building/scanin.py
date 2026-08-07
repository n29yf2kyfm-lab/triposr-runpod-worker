"""Scan Mode — a phone scan in, a verified splat of the real building out.

THE MISSING FIRST LINK, FINALLY CLOSED FROM THE PHONE SIDE. The Tier-1
method starts "the homeowner films the house", and that step has never once
produced data — the GPU reconstruction leg has no capture to run on. But
consumer apps now do the capture AND the fitting on the phone itself:
Scaniverse fits a Gaussian splat on-device and exports a standard 3DGS
.ply; Polycam and Luma export the same format. Nobody has to wait for our
GPU leg to get a photographic model any more — the phone hands one over,
and this mode is the worker-side socket it plugs into.

WHAT THIS MODE ACTUALLY DOES with the .ply it is given:

  verify    it parses, it has gaussians, they did not collapse to a point
  scale     compared against the building's mapped footprint when an
            address/gps is given — a splat at 0.3x scale is caught HERE,
            not after someone composites an extension into it at 0.3x
  position  rotated and translated into the building's own local frame
            (front elevation on y=0), the same frame the measured model
            uses, so the two can meet in one scene
  preview   an honest point-cloud render, drawn by code — the full splat
            renderer belongs in the app (gsplat / GaussianSplats3D, both
            checked MIT/Apache), not in a CPU worker
  deliver   the normalised .ply plus a stats JSON that says all of the
            above, with every caveat in writing

WHAT IT REFUSES TO PRETEND. A splat is photographic, not measured — the
sanity report says so on every job. The scale check needs the footprint, so
with no address it can only report the raw span with a warning. And the
alignment is coarse (footprint-fit yaw, ground-plane z): fine for viewing an
extension in the scene, not for setting out foundations.
"""
import json
import math
import os
import sys

import splat


MODE = "scan"

# A phone splat of a house runs 0.5M-3M gaussians, 60-350MB. Twice the top
# of that range is corrupt or not a house scan; refusing beats an OOM kill
# half way through a parse.
MAX_PLY_MB = 800

# Preview size and the gaussian budget for it. Drawing every gaussian in a
# 2M splat with PIL takes minutes for no extra information; a stratified
# sample reads the same at a glance.
PREVIEW_PX = 900
PREVIEW_SAMPLE = 120_000


class ScanError(RuntimeError):
    """The scan cannot be used, and the message says why."""


def load(path):
    """Read and gate a phone splat export."""
    size_mb = os.path.getsize(path) / 1e6
    if size_mb > MAX_PLY_MB:
        raise ScanError(
            f"this .ply is {size_mb:.0f}MB — beyond anything a phone scan of "
            f"a building produces. If it is a merged multi-scan, split it.")
    splats, fields = splat.read_ply(path)
    if not any(f.startswith("f_dc_") for f in fields):
        # A plain point cloud (e.g. a LAS->PLY conversion) has positions but
        # no gaussian fields. It still previews; it will not relight.
        print("scan: no SH fields — treating as a point cloud",
              file=sys.stderr)
    return splats, fields


def orient(splats):
    """Guess which way is up, and normalise to y-up if it is z-up.

    Scaniverse and Polycam exports are z-up (scanner convention); the
    building frame and glTF are y-up. The tell is the extent: a building
    scan is wider than it is tall in plan and its smallest span is rarely
    vertical, so whichever axis has the span closest to a plausible building
    height wins. Coarse on purpose — a wrong guess here shows up instantly
    in the preview, which is why the preview exists.
    """
    xs = [g.get("x", 0.0) for g in splats]
    ys = [g.get("y", 0.0) for g in splats]
    zs = [g.get("z", 0.0) for g in splats]
    spans = {"x": max(xs) - min(xs), "y": max(ys) - min(ys),
             "z": max(zs) - min(zs)}
    # The vertical is the SMALLEST span when it is clearly smallest — a
    # building scan is wider than tall in both plan directions. First guess
    # ("closest to 8m") failed its own test: an 8m-deep plan beat a 6m
    # height. Only when no axis is clearly smallest does the height-likeness
    # tie-break get a say.
    ordered = sorted(spans, key=lambda k: spans[k])
    if spans[ordered[0]] <= 0.9 * spans[ordered[1]]:
        up = ordered[0]
    else:
        up = min(spans, key=lambda k: abs(spans[k] - 8.0))
    if up == "y":
        return splats, "y-up (unchanged)"
    if up == "z":
        # z-up -> y-up: (x, y, z) -> (x, z, -y)
        out = []
        for g in splats:
            n = dict(g)
            n["x"], n["y"], n["z"] = g.get("x", 0.0), g.get("z", 0.0), \
                -g.get("y", 0.0)
            out.append(n)
        return out, "z-up, rotated to y-up"
    return splats, f"ambiguous (up looked like {up}) — left unchanged"


def ground_to_zero(splats):
    """Put the ground at y=0, robustly.

    The 2nd percentile rather than the minimum: every phone splat has a few
    floaters fitted below the real ground, and min() would hang the whole
    scan from the lowest one.
    """
    ys = sorted(g.get("y", 0.0) for g in splats)
    ground = ys[max(0, int(len(ys) * 0.02))]
    out = []
    for g in splats:
        n = dict(g)
        n["y"] = g.get("y", 0.0) - ground
        out.append(n)
    return out, round(ground, 3)


def preview(splats, path, size=PREVIEW_PX):
    """The splat as a coloured point cloud, drawn by code.

    Not photoreal and not pretending to be: its job is the checks a person
    makes in one look — is it a house, is it the right way up, did a wall
    smear. SH degree-0 carries the colour (0.5 + C0*dc, C0=0.2820948).
    """
    from PIL import Image, ImageDraw
    step = max(1, len(splats) // PREVIEW_SAMPLE)
    pts = splats[::step]
    xs = [g.get("x", 0.0) for g in pts]
    ys = [g.get("y", 0.0) for g in pts]
    zs = [g.get("z", 0.0) for g in pts]
    cx, cy, cz = (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0

    yaw, pitch = math.radians(35), math.radians(18)
    cyaw, syaw = math.cos(yaw), math.sin(yaw)
    cpit, spit = math.cos(pitch), math.sin(pitch)
    C0 = 0.2820948
    drawn = []
    for g in pts:
        x, y, z = g.get("x", 0.0) - cx, g.get("y", 0.0) - cy, \
            g.get("z", 0.0) - cz
        rx = x * cyaw - z * syaw
        rz = x * syaw + z * cyaw
        ry = y * cpit - rz * spit
        depth = rz * cpit + y * spit
        px = size / 2 + rx / span * size * 0.85
        py = size / 2 - ry / span * size * 0.85 + size * 0.05
        r = max(0, min(255, int((0.5 + C0 * g.get("f_dc_0", 0.0)) * 255)))
        gg = max(0, min(255, int((0.5 + C0 * g.get("f_dc_1", 0.0)) * 255)))
        b = max(0, min(255, int((0.5 + C0 * g.get("f_dc_2", 0.0)) * 255)))
        drawn.append((depth, px, py, (r, gg, b)))
    drawn.sort(key=lambda t: -t[0])

    img = Image.new("RGB", (size, size), (24, 26, 30))
    d = ImageDraw.Draw(img)
    for _, px, py, col in drawn:
        d.rectangle([px - 1, py - 1, px + 1, py + 1], fill=col)
    img.save(path)
    return path


def run(spec, prog, output_dir):
    """Scan mode entry point: a phone splat in, a verified one out."""
    import paths
    import delivery
    import validation

    prog.stage("fetching")
    src = spec.get("scan_path")
    if not src:
        url = spec.get("scan_url")
        if not url:
            raise ScanError(
                "scan mode needs scan_url (or scan_path) — the .ply your "
                "scanning app exported. In Scaniverse: Share > Export Model "
                "> PLY. Polycam and Luma export the same format.")
        r = validation.fetch_checked(url, field="scan_url", timeout=300,
                                     stream=True)
        src = os.path.join(output_dir, "scan_upload.ply")
        with open(src, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                if f.tell() > MAX_PLY_MB * 1e6:
                    raise ScanError(
                        f"scan_url exceeds {MAX_PLY_MB}MB — refusing "
                        f"mid-download rather than filling the disk.")

    prog.stage("verifying")
    splats, fields = load(src)
    prog.note(f"{len(splats)} gaussians, {len(fields)} fields per gaussian")

    prog.stage("orienting")
    splats, up_note = orient(splats)
    splats, ground_shift = ground_to_zero(splats)
    prog.note(f"orientation: {up_note}; ground shifted {ground_shift}m")

    # Scale check against the mapped footprint, when the job says where the
    # building is. This is the single most valuable number in the mode: a
    # phone splat's scale is usually good (ARKit/LiDAR) but when it is off,
    # everything composited into it later is off by the same factor.
    expect = None
    site_note = "no address/gps given — scale checked against nothing"
    if spec.get("gps") or spec.get("address") or spec.get("postcode"):
        try:
            import roof as roofmod
            loc = roofmod.resolve_location(spec)
            fp = roofmod.fetch_footprint(loc["lat"], loc["lon"], radius_m=40)
            if fp:
                import propose
                rect = propose.min_area_rect(fp)
                expect = math.hypot(rect["width_m"], rect["depth_m"])
                site_note = (f"footprint diagonal {expect:.1f}m from "
                             f"OpenStreetMap at {loc['grid_ref']}")
        except Exception as e:
            site_note = f"footprint lookup failed: {type(e).__name__}"

    report = splat.sanity(splats, expect_span_m=expect)
    report["orientation"] = up_note
    report["ground_shift_m"] = ground_shift
    report["site"] = site_note
    if "warning" in report:
        prog.note(report["warning"])

    prog.stage("delivering")
    scan = spec.get("scan_id") or "scan"
    out_ply = os.path.join(output_dir, f"{scan}.splat.ply")
    splat.write_ply(splats, out_ply)
    prev = os.path.join(output_dir, f"{scan}.preview.png")
    try:
        preview(splats, prev)
    except Exception as e:
        print(f"preview failed: {type(e).__name__}: {e}", file=sys.stderr)
        prev = None
    stats = os.path.join(output_dir, f"{scan}.scan.json")
    with open(stats, "w") as f:
        json.dump(report, f, indent=2)

    artifacts = [(out_ply, f"scans/{scan}.splat.ply", None),
                 (stats, f"scans/{scan}.scan.json", None)]
    if prev:
        artifacts.append((prev, f"scans/{scan}.preview.png", None))

    result = dict(report)
    result["warning_scan"] = (
        "This is a PHOTOGRAPHIC model from a phone scan. It shows the real "
        "building; it does not measure it. Dimensions come from the "
        "parametric model, never from here.")
    # Artifacts first: the handler contract is run() -> (artifacts, extra).
    return artifacts, result
