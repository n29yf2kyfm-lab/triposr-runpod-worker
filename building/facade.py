"""Rectify a photograph of an elevation into a measured orthophoto.

THE JOIN between the two halves of this project. Everything that turns
pictures into 3D — Vizcom, SAM 3D, TripoSR, TRELLIS, photogrammetry,
splats — returns appearance in arbitrary units (docs/IMAGE_TO_3D.md).
Everything that measures — LiDAR, OS heights, RoomPlan, figured
dimensions — returns metres and no looks. This module fuses them the one
honest way: it takes a photograph and a wall whose true size is ALREADY
KNOWN, and warps the photograph onto that known rectangle.

The Blender/fSpy workflow exists to GUESS a camera, because a modeller
starting from a photo has no true dimensions. We are not in that
position. Four facade corners located in the photo, plus the measured
width and height of that facade, determine a homography outright — no
camera estimate, no perspective-interpolation artefacts, no subdividing
geometry to hide them.

What that buys, in order of value to a builder:
  1. Openings that can be MEASURED off the photograph. A window's
     position, width, height and sill come out in metres, in exactly the
     dict shape model3d.apply_facade_openings consumes — so a photo of a
     real house becomes the real openings of its model.
  2. An elevation underlay to draw over, which is how existing-building
     surveys are actually done.
  3. A photoreal texture that sits on measured geometry, which is the
     only honest route to "a homeowner cannot tell it from a photo".

LIMITS, STATED. A homography rectifies a PLANE. Bay windows, deep
reveals, porches and anything standing proud of the wall plane are
correct only where they touch that plane and progressively wrong as they
project. Lens distortion is not corrected — a wide phone lens bows
straight lines, and this assumes a pinhole camera; shoot from further
back with less zoom, or undistort first. And the four corners are an
input: garbage corners, garbage metres.
"""

# --- linear algebra, stdlib -------------------------------------------


def _solve(a, b):
    """Gaussian elimination with partial pivoting. a is n x n, b is n."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        p = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[p][col]) < 1e-12:
            raise ValueError(
                "the four corners are degenerate — three of them are in "
                "line, or two are the same point, so no unique rectification "
                "exists. Re-pick the corners of the facade.")
        m[col], m[p] = m[p], m[col]
        piv = m[col][col]
        for r in range(n):
            if r == col:
                continue
            f = m[r][col] / piv
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def solve_homography(src, dst):
    """8 coefficients mapping src -> dst (h8 fixed at 1).

    src and dst are four (x, y) pairs in corresponding order.
    """
    if len(src) != 4 or len(dst) != 4:
        raise ValueError("a homography needs exactly four point pairs")
    a, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return _solve(a, b)


def project(h, x, y):
    d = h[6] * x + h[7] * y + 1.0
    if abs(d) < 1e-12:
        raise ValueError("point projects to infinity under this homography")
    return ((h[0] * x + h[1] * y + h[2]) / d,
            (h[3] * x + h[4] * y + h[5]) / d)


def residual(h, src, dst):
    """Largest corner error in pixels — ~0 for an exact 4-point solve, and
    a real number if a 5th check point is included."""
    worst = 0.0
    for (x, y), (u, v) in zip(src, dst):
        px, py = project(h, x, y)
        worst = max(worst, ((px - u) ** 2 + (py - v) ** 2) ** 0.5)
    return worst


# --- the elevation ----------------------------------------------------

DEFAULT_PX_PER_M = 200.0        # 5mm per pixel: plenty for 1:50 drawing


def rectify(image, corners_px, width_m, height_m,
            px_per_m=DEFAULT_PX_PER_M):
    """Warp a photo of one elevation into a scaled orthophoto.

    corners_px: the facade's four corners AS SEEN IN THE PHOTO, in the
    order top-left, top-right, bottom-right, bottom-left of the WALL —
    i.e. going round the rectangle, starting at the eaves end of the
    left-hand corner.

    Returns (PIL.Image, meta). meta carries px_per_m and the facade size,
    which is what makes every later measurement metric.
    """
    if width_m <= 0 or height_m <= 0:
        raise ValueError("the facade's measured width and height must be "
                         "positive metres — they are the scale")
    w_px = max(2, int(round(width_m * px_per_m)))
    h_px = max(2, int(round(height_m * px_per_m)))
    dst = [(0, 0), (w_px, 0), (w_px, h_px), (0, h_px)]
    # PIL's PERSPECTIVE transform wants coefficients mapping DESTINATION
    # back into the SOURCE, so solve that direction directly.
    inv = solve_homography(dst, [tuple(map(float, c)) for c in corners_px])
    try:
        from PIL import Image
    except ImportError:                          # pragma: no cover
        raise RuntimeError(
            "rectifying a photograph needs Pillow (it is in "
            "requirements.txt); the homography maths in this module works "
            "without it")
    out = image.transform((w_px, h_px), Image.PERSPECTIVE, inv,
                          resample=Image.BICUBIC)
    # No corner residual in meta, deliberately. Four point pairs determine
    # the homography exactly, so residual() over those same four points is
    # ~0 for ANY corners — garbage included. It used to sit here as
    # "corner_residual_px" and read as a quality measurement that never
    # happened: a tautology wearing a metric's clothes. The verification
    # that IS real is independent — check_brick_course, against a ruler
    # the photograph carries in its own brickwork.
    meta = {
        "px_per_m": px_per_m,
        "width_m": float(width_m), "height_m": float(height_m),
        "size_px": [w_px, h_px],
        "corners_px": [list(map(float, c)) for c in corners_px],
        "notes": [
            "Rectified to the wall PLANE. Anything proud of it — bays, "
            "reveals, porches, gutters — is correct only where it meets "
            "the plane.",
            "No lens distortion correction: shoot from further back "
            "rather than zooming wide, or undistort first.",
        ],
    }
    return out, meta


def to_metres(meta, x_px, y_px):
    """Pixel in the rectified elevation -> (along_m, height_m).

    Along runs left to right as the elevation is drawn; height runs UP
    from the base of the facade, because that is how a sill is quoted.
    """
    s = meta["px_per_m"]
    return (x_px / s, meta["height_m"] - y_px / s)


def opening_from_box(meta, box_px, kind="window", level=None,
                     base_offset_m=0.0):
    """A rectangle drawn round a window in the rectified photo, returned
    in the exact shape model3d.apply_facade_openings consumes.

    box_px is (x0, y0, x1, y1) in rectified pixels. base_offset_m is the
    height of the facade's base above finished floor level, in the rare
    case the photographed corners started above the floor.
    """
    x0, y0, x1, y1 = box_px
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    along, top = to_metres(meta, x0, y0)
    right, sill = to_metres(meta, x1, y1)
    out = {
        "kind": kind,
        "along": round(along, 3),
        "width": round(right - along, 3),
        "height": round(top - sill, 3),
        "sill": round(sill - base_offset_m, 3),
    }
    if level is not None:
        out["level"] = level
    return out


# --- cross-checks -----------------------------------------------------

BRICK_COURSE_M = 0.075          # matches scale.py: 65mm brick + 10mm joint
FOUR_COURSES_M = 0.300


def check_brick_course(meta, course_px, courses=1):
    """Independent verification against the best ruler in any British
    photograph. scale.py already trusts brick courses for scaling a
    reconstruction; here they check a rectification that was scaled from
    the measured facade instead — two different routes to the same metre.

    course_px: measured pixel height spanning `courses` brick courses in
    the rectified image.
    """
    if course_px <= 0 or courses <= 0:
        raise ValueError("course height in pixels and the number of "
                         "courses must both be positive")
    implied = (course_px / courses) / meta["px_per_m"]
    err = (implied - BRICK_COURSE_M) / BRICK_COURSE_M
    return {
        "implied_course_m": round(implied, 4),
        "expected_course_m": BRICK_COURSE_M,
        "error_pct": round(err * 100.0, 2),
        "agrees": abs(err) <= 0.05,
        "note": ("four courses rise 300mm in British brickwork; a "
                 "disagreement over 5% means the corners, the measured "
                 "facade size, or the assumption that this is standard "
                 "brickwork is wrong"),
    }


def describe(meta):
    # The corner residual is gone from this line on purpose: it printed
    # 0.000 px for every rectification, garbage corners included, because
    # an exact 4-point solve reproduces its own corners by construction.
    # Scale verification, when wanted, is check_brick_course — a real one.
    return (f"Elevation {meta['width_m']:.2f} x {meta['height_m']:.2f} m "
            f"rectified to {meta['size_px'][0]} x {meta['size_px'][1]} px "
            f"at {meta['px_per_m']:.0f} px/m "
            f"({1000.0 / meta['px_per_m']:.1f} mm per pixel)")
