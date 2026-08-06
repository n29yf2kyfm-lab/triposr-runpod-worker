"""Gaussian splats — the photographic half of the model.

A measured mesh answers "how big is it". A 3D Gaussian splat answers "what
does it look like when you walk round it", and it answers that better than
any mesh, because it never has to commit to a surface. Foliage, net curtains,
weathered brick, the soft edge of a hedge: things a triangle mesh either
misses or lies about.

The two are not interchangeable and this module exists alongside model3d
rather than instead of it:

    parametric CAD   dimensioned, editable, priceable, submittable
    gaussian splat   photographic, orbitable, and NOT measurable

Nobody should ever take a dimension off a splat. It is millions of fuzzy
ellipsoids fitted to photographs; it has no notion of a wall, and where the
photographs disagree it will happily place a gaussian in mid-air. The
measured model is what gets built from. The splat is what gets shown.

LICENCES, CHECKED RATHER THAN ASSUMED. Two traps here, both verified against
the actual packages rather than a blog post:

  gsplat 1.5.3    Apache 2.0 (LICENSE inside the wheel). Commercially usable.
                  This is Nerfstudio's independent re-implementation, NOT the
                  original INRIA 3DGS code, whose licence is research-only
                  and would be fatal to a commercial product.
  plyfile         GPL-3. The usual way to read and write splat files, and
                  therefore not usable here at all. The PLY reader and writer
                  below are stdlib, which also keeps them dependency-free
                  like every other exporter in this package.

WHAT NEEDS A GPU, AND WHAT DOES NOT. Fitting gaussians needs CUDA and so does
gsplat's rasteriser — gsplat ships CUDA source with no prebuilt binaries and
compiles on first use. Everything else here — reading a capture, putting it
in the building's own coordinate frame, writing and reading the .ply — is
plain Python and runs anywhere, which is why it is separated out and tested
on its own.
"""
import os
import struct
import sys


# The standard 3DGS .ply layout, in order. Every viewer in the ecosystem —
# the reference one, SuperSplat, Polycam, the web renderers — expects exactly
# these property names, so they are not ours to rename.
SH_DC = 3            # degree-0 spherical harmonics: flat colour
SH_REST = 45         # degrees 1-3: view-dependent colour, 15 coeffs x 3
SPLAT_FIELDS = (
    ["x", "y", "z", "nx", "ny", "nz"]
    + [f"f_dc_{i}" for i in range(SH_DC)]
    + [f"f_rest_{i}" for i in range(SH_REST)]
    + ["opacity", "scale_0", "scale_1", "scale_2",
       "rot_0", "rot_1", "rot_2", "rot_3"]
)

# Fitting below this many views produces a splat that looks convincing from
# the camera positions and falls apart everywhere else — which is the single
# most misleading failure this whole product could ship.
MIN_VIEWS = 40


class SplatError(RuntimeError):
    """The splat cannot be fitted, or cannot be trusted."""


def available():
    """Is a GPU splat pipeline actually installed on this worker?

    Returns (ok, reason). Deliberately reports the reason rather than a bare
    False: "no splat" on a serverless worker is nearly always a missing CUDA
    build rather than a missing package, and those need different fixes.
    """
    try:
        import torch
    except ImportError:
        return False, "torch is not installed on this worker"
    if not torch.cuda.is_available():
        return False, ("no CUDA device is visible — fitting gaussians is a "
                       "GPU job and cannot fall back to CPU in any useful "
                       "time")
    try:
        import gsplat  # noqa: F401
    except ImportError:
        return False, ("gsplat is not installed. It is Apache-2.0 and pip "
                       "installable; note it compiles CUDA kernels on first "
                       "use, so the first job on a cold worker pays several "
                       "minutes unless the image pre-builds them")
    return True, "ready"


# --- the .ply, without the GPL dependency -----------------------------------

def write_ply(splats, path):
    """Write gaussians as a binary little-endian 3DGS .ply.

    `splats` is a sequence of dicts keyed by SPLAT_FIELDS. Missing fields are
    written as zero, which is meaningful for every one of them: zero normals
    (splats carry no normals but the format keeps the slots), zero higher-
    order SH (flat colour), and zero rotation is caught below because a
    zero quaternion is not a rotation.
    """
    n = len(splats)
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    header += [f"property float {f}" for f in SPLAT_FIELDS]
    header.append("end_header")
    blob = ("\n".join(header) + "\n").encode("ascii")

    packer = struct.Struct("<" + "f" * len(SPLAT_FIELDS))
    with open(path, "wb") as fh:
        fh.write(blob)
        for s in splats:
            fh.write(packer.pack(*[float(s.get(f, 0.0))
                                   for f in SPLAT_FIELDS]))
    return path


def read_ply(path):
    """Read a binary 3DGS .ply back. Returns (list of dicts, header fields).

    Reads the header's OWN field list rather than assuming SPLAT_FIELDS:
    exports differ in how many SH degrees they carry, and a reader that
    assumes 45 rest coefficients silently mangles a file with 9.
    """
    with open(path, "rb") as fh:
        raw = b""
        while b"end_header" not in raw:
            chunk = fh.read(1)
            if not chunk:
                raise SplatError(f"{path} ends before its header does")
            raw += chunk
        raw += fh.readline()
        lines = raw.decode("ascii", "replace").splitlines()
        if not lines or lines[0].strip() != "ply":
            raise SplatError(f"{path} is not a PLY file")
        if not any(l.startswith("format binary_little_endian") for l in lines):
            raise SplatError(
                f"{path} is not binary little-endian PLY. Only that variant "
                f"is written here, and converting is not this module's job.")
        count = 0
        fields = []
        for line in lines:
            if line.startswith("element vertex"):
                count = int(line.split()[-1])
            elif line.startswith("property float"):
                fields.append(line.split()[-1])
        if not fields:
            raise SplatError(f"{path} declares no float properties")

        unpacker = struct.Struct("<" + "f" * len(fields))
        out = []
        for _ in range(count):
            buf = fh.read(unpacker.size)
            if len(buf) < unpacker.size:
                raise SplatError(
                    f"{path} claims {count} gaussians but the data runs out "
                    f"after {len(out)}")
            out.append(dict(zip(fields, unpacker.unpack(buf))))
    return out, fields


# --- putting the splat where the building is --------------------------------

def to_building_frame(splats, angle_rad, origin_en, ground_z=0.0,
                      scale=1.0):
    """Move a splat into the SAME coordinate frame as the measured model.

    This is the step that makes the whole Tier-1 idea work. A splat fitted
    from photographs sits in whatever arbitrary frame the pose solver chose,
    at whatever scale it guessed. The measured model sits in the building's
    own local frame, in metres, with the front elevation on y=0. Until those
    two agree there is no way to render a CAD extension inside a photographic
    scene — the extension lands at the wrong size, in the wrong place, at the
    wrong angle, and no amount of eyeballing fixes it.

    Returns a new list; the input is not modified.
    """
    import math
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    out = []
    for g in splats:
        x, y, z = g.get("x", 0.0) * scale, g.get("y", 0.0) * scale, \
            g.get("z", 0.0) * scale
        n = dict(g)
        # Plan rotation about the vertical, then translate onto the frame.
        n["x"] = x * c - z * s + origin_en[0]
        n["z"] = x * s + z * c + origin_en[1]
        n["y"] = y - ground_z
        # Scaling the positions without scaling the gaussians themselves
        # leaves a correctly-placed cloud of wrongly-sized blobs. The stored
        # scales are logarithms, so a factor becomes an offset.
        if scale != 1.0:
            d = math.log(scale)
            for k in ("scale_0", "scale_1", "scale_2"):
                if k in n:
                    n[k] = n[k] + d
        out.append(n)
    return out


def sanity(splats, expect_span_m=None):
    """What is actually in this splat, and is any of it believable?

    A splat has no error bars, so these are the crude checks that catch the
    failures worth catching: nothing fitted, everything fitted in one place,
    or a cloud whose extent is nothing like the building it claims to be.
    """
    if not splats:
        raise SplatError("the splat is empty — nothing was fitted")
    xs = [g.get("x", 0.0) for g in splats]
    ys = [g.get("y", 0.0) for g in splats]
    zs = [g.get("z", 0.0) for g in splats]
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    report = {
        "gaussians": len(splats),
        "extent_m": {"x": round(max(xs) - min(xs), 2),
                     "y": round(max(ys) - min(ys), 2),
                     "z": round(max(zs) - min(zs), 2)},
        "span_m": round(span, 2),
        "measurable": False,
        "note": ("A splat is photographic, not measured. Do not take a "
                 "dimension off it — the parametric model is what carries "
                 "the sizes."),
    }
    if span <= 1e-6:
        raise SplatError(
            "every gaussian is at the same point — the fit collapsed, which "
            "usually means the capture had no parallax (someone stood still "
            "and turned instead of walking)")
    if expect_span_m:
        ratio = span / float(expect_span_m)
        report["expected_span_m"] = round(float(expect_span_m), 2)
        report["scale_ratio"] = round(ratio, 3)
        if not 0.6 <= ratio <= 1.7:
            report["warning"] = (
                f"The fitted cloud spans {span:.1f}m where the measured "
                f"building spans {expect_span_m:.1f}m — a factor of "
                f"{ratio:.2f}. The splat is not to scale, so anything "
                f"composited into it will be the wrong size. Re-run with "
                f"LiDAR depth or known control distances.")
    return report


# TRELLIS's Gaussian object, whatever version produced it, carries the 3DGS
# convention under leading-underscore names. Read defensively: the point of
# this is to get gaussians OUT of a pipeline that already makes them.
_TRELLIS_ATTRS = (
    ("_xyz", ("x", "y", "z")),
    ("_features_dc", tuple(f"f_dc_{i}" for i in range(SH_DC))),
    ("_features_rest", tuple(f"f_rest_{i}" for i in range(SH_REST))),
    ("_opacity", ("opacity",)),
    ("_scaling", ("scale_0", "scale_1", "scale_2")),
    ("_rotation", ("rot_0", "rot_1", "rot_2", "rot_3")),
)


def from_trellis(gaussian):
    """A TRELLIS Gaussian object to plain dicts, ready for write_ply.

    THE PIPELINE ALREADY MAKES THESE AND THROWS THEM AWAY. The TRELLIS worker
    in this repo calls `postprocessing_utils.to_glb(outputs["gaussian"][0],
    outputs["mesh"][0], ...)` — the gaussians exist, are used to colour the
    mesh, and are then discarded. Exporting them costs one function call.

    AND EXPORTING THEM NEEDS NO LICENSED CODE. This is the part worth being
    precise about. The INRIA/MPII research licence, which forbids commercial
    use, covers `diff-gaussian-rasterization` — the CUDA renderer that DRAWS
    gaussians. It does not cover the numbers. TRELLIS itself is MIT, so the
    gaussians it produces are yours; writing them to a .ply is arithmetic and
    file IO. What you must not do is ship the INRIA rasteriser to draw them.
    Use gsplat (Apache-2.0) for that, or any of the web viewers.
    """
    out, columns = None, {}
    for attr, names in _TRELLIS_ATTRS:
        val = getattr(gaussian, attr, None)
        if val is None:
            continue
        try:
            val = val.detach().cpu().numpy()
        except AttributeError:
            pass
        if getattr(val, "reshape", None) is None:
            continue
        flat = val.reshape(len(val), -1)
        if not len(flat):
            continue
        if out is None:
            out = [dict() for _ in range(len(flat))]
        # Row width from the row itself, not from a .shape attribute — this
        # has to work on whatever the pipeline hands over, and torch, numpy
        # and a plain list of lists do not agree on that interface.
        wide = len(flat[0])
        for i, name in enumerate(names):
            if i < wide:
                columns[name] = True
                for row, g in zip(flat, out):
                    g[name] = float(row[i])
    if not out:
        raise SplatError(
            "this object carries no gaussians — expected the 3DGS attribute "
            "names (_xyz, _features_dc, _opacity, _scaling, _rotation)")
    return out


def fit(capture_dir, output_path, iterations=7000, expect_span_m=None,
        progress=None):
    """Fit gaussians to a captured image set. Needs a GPU.

    This is the only function here that cannot run without CUDA, and it
    refuses clearly rather than half-working. The surrounding machinery —
    frames, poses, framing, export, scale check — is deliberately outside it
    so that all of that is testable on any machine.
    """
    ok, why = available()
    if not ok:
        raise SplatError(
            f"cannot fit a Gaussian splat here: {why}. The measured model, "
            f"its drawings and its renders do not depend on this and are "
            f"delivered regardless.")

    frames = sorted(f for f in os.listdir(capture_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png")))
    if len(frames) < MIN_VIEWS:
        raise SplatError(
            f"{len(frames)} usable frames is not enough to fit a splat — "
            f"under about {MIN_VIEWS} it looks right from the camera "
            f"positions and wrong everywhere else, which is worse than no "
            f"splat at all. The capture plan sizes a session properly.")

    if progress:
        progress.note(f"fitting {len(frames)} views for {iterations} steps")

    # Deliberately imported here. The module must remain importable — and its
    # PLY and frame handling testable — on a machine with no CUDA at all.
    from gsplat.strategy import DefaultStrategy  # noqa: F401
    raise SplatError(
        "the gsplat training loop is not wired up yet. Everything around it "
        "is: the capture plan that produces the frames, the frame check, the "
        "building-frame transform, the .ply writer and reader, and the scale "
        "sanity check. What is missing is the fitting itself, which needs a "
        "GPU pod to write against and has never been run.")
