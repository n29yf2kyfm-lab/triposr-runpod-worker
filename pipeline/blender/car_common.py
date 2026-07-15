"""car_common.py — single source of truth for the car-geometry heuristics and
role-name conventions the Blender pipeline scripts share.

Before this module existed the wheel-arch histogram, length-axis detection and
paint/glass/wheel name rules were copy-pasted into cabin_assembly, prop_fix and
wheel_replace with drifting constants (and wheel_replace simply ASSUMED y was
the length axis). One implementation lives here; per-script tolerances stay
overridable parameters so validated behaviour is unchanged.

NOTE for the render worker: render/handler.py is built from its own Docker
context and cannot import this file — its _GLASS/_PAINT regexes and glass
alpha threshold must be kept in sync with the values here by hand.

Import pattern for headless Blender scripts (script dir is not on sys.path):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from car_common import detect_axes, wheel_arches, ...
"""
import re
import numpy as np

# ---- role-name conventions (align with pipeline/qc/asset_audit.py) ---------
PAINT_RE = re.compile(r"paint|body|carpaint|lack|carros", re.I)
GLASS_RE = re.compile(r"glass|window|windscreen|windshield|screen", re.I)
WHEEL_RE = re.compile(r"wheel|tyre|tire|rim\b|alloy|hub", re.I)

# BLEND-mode alpha below this = real see-through glass. Must match
# asset_audit gate G2 and render/handler.py's classifier.
GLASS_ALPHA_MAX = 0.9

# Wheel radius as a fraction of car length (hatch/saloon calibrated).
WHEEL_R_FRAC = 0.085


def mesh_verts(obj):
    """World-ignorant (N,3) vertex array of a mesh object (glTF import bakes
    transforms into vertices for our single-object shells)."""
    return np.array([v.co[:] for v in obj.data.vertices])


def detect_axes(vs):
    """(length_axis, width_axis) among horizontal x/y — Blender is z-up after
    glTF import. Never returns z."""
    d = vs.max(0) - vs.min(0)
    la = int(np.argmax([d[0], d[1], 0]))
    return la, 1 - la


def body_width(vs, wa, band_frac=0.50, pct=(0.5, 99.5)):
    """Mirror-safe body width: percentile spread of the lower band, so door
    mirrors / stray verts don't inflate it. Same measure as asset_audit G1."""
    lo_z = vs[:, 2].min()
    h = vs[:, 2].max() - lo_z
    band = vs[vs[:, 2] < lo_z + band_frac * h]
    return float(np.percentile(band[:, wa], pct[1]) -
                 np.percentile(band[:, wa], pct[0]))


def wheel_arches(vs, la, bins=40, band_frac=0.22):
    """Locate the front/rear axles from the vertex-density histogram of the
    lower body band along the length axis.

    Returns dict(front, rear, R, czw, wheel_top_frac_h) where:
      front/rear = axle positions on the length axis (front = the lo-side
                   density peak — 'front' means nothing more than that),
      R          = wheel radius estimate (WHEEL_R_FRAC * length),
      czw        = wheel-centre height (floor + R).
    """
    lo, hi = vs.min(0), vs.max(0)
    d = hi - lo
    length, height = d[la], d[2]
    cl = (lo[la] + hi[la]) / 2
    band = vs[vs[:, 2] < lo[2] + band_frac * height]
    histo, edges = np.histogram(band[:, la], bins=bins)
    front = float(edges[np.argmax(histo * (edges[:-1] < cl))])
    rear = float(edges[np.argmax(histo * (edges[:-1] >= cl))])
    r = WHEEL_R_FRAC * length
    return dict(front=front, rear=rear, R=r, czw=float(lo[2] + r))


def in_wheel(c_l, c_z, arches, radius_factor=1.2, axle_inset=0.0):
    """Is a point (length-axis coord, z) inside either wheel cylinder?
    radius_factor and axle_inset are the per-script tuning knobs that used to
    drift (cabin_assembly 1.18/R*0.2, prop_fix 1.35/0, wheel_replace 1.10/0)."""
    r2 = (arches["R"] * radius_factor) ** 2
    for ay in (arches["front"] + axle_inset, arches["rear"] - axle_inset):
        if (c_l - ay) ** 2 + (c_z - arches["czw"]) ** 2 < r2:
            return True
    return False
