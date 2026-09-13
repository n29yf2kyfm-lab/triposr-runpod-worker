"""Did the picture keep the geometry it was given?

WHY THIS EXISTS. An image model is asked to dress a measured massing in
brick and glass without moving a wall. Nothing about a prompt makes it
obey; a depth-conditioned model obeys more often, and a free-form one
less. Either way the only honest position is to CHECK, on every image,
and to refuse the ones that drifted — because a photoreal picture with
the ridge 40 cm too high is not a slightly worse picture, it is a
falsified survey with good lighting.

THE MEASURE. The massing render has hard edges exactly where the
geometry is: eaves, ridge, verges, corners, the line where wall meets
ground. A faithful re-render keeps an edge at every one of those places
(it may add many more — windows, bricks, gutters — which is fine). So
this measures EDGE RECALL: of the reference's edge pixels, what fraction
has an edge in the candidate within a few pixels? Windows do not lower
it; a moved roof line does. Restricting the reference edges to the
building's own silhouette (via the mask pass) keeps the ground plane and
the sky out of the score.

It is deliberately simple — Sobel, a threshold, a dilation — so that
what it accepts and refuses can be reasoned about, and so that it runs
in a few hundred milliseconds with nothing but Pillow and numpy.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter

# Below this, the picture did not keep the measured geometry.
FIDELITY_MIN = 0.80
# An edge counts as kept if the candidate has one within this many
# pixels at reference resolution. Six pixels at ~1000 px wide is under
# 1% of the frame — a moved ridge is tens of pixels.
TOLERANCE_PX = 6
WORK_W = 1024


def _grey(png: bytes, size=None) -> np.ndarray:
    im = Image.open(io.BytesIO(png)).convert("L")
    if size and im.size != size:
        im = im.resize(size, Image.BILINEAR)
    return np.asarray(im, dtype=np.float32) / 255.0


def _edges(g: np.ndarray, keep_fraction: float = 0.06) -> np.ndarray:
    """Sobel magnitude, thresholded so the strongest `keep_fraction` of
    pixels count as edge. A relative threshold makes the measure
    indifferent to overall contrast — a dim render and a bright photo
    yield edge maps of comparable density."""
    gx = np.zeros_like(g)
    gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1, :] = g[2:, :] - g[:-2, :]
    mag = np.hypot(gx, gy)
    if not mag.any():
        return np.zeros(g.shape, dtype=bool)
    cut = np.quantile(mag, 1.0 - keep_fraction)
    return mag > max(cut, 1e-4)


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    im = Image.fromarray((mask * 255).astype(np.uint8))
    size = 2 * r + 1
    return np.asarray(im.filter(ImageFilter.MaxFilter(size))) > 0


def edge_recall(reference_png: bytes, candidate_png: bytes,
                mask_png: bytes | None = None,
                tolerance_px: int = TOLERANCE_PX) -> dict:
    """Fraction of the reference's geometry edges the candidate kept.

    reference_png: the massing render (the geometry, as drawn)
    candidate_png: the generated picture, any size — resized to match
    mask_png:      optional silhouette pass; white = building. When
                   given, only reference edges on or near the building
                   are scored, so ground texture never counts.
    """
    ref_im = Image.open(io.BytesIO(reference_png))
    w, h = ref_im.size
    if w > WORK_W:
        h = int(round(h * WORK_W / w))
        w = WORK_W
    size = (w, h)
    ref = _grey(reference_png, size)
    cand = _grey(candidate_png, size)
    scale = max(1, int(round(tolerance_px * w / max(w, 1))))

    ref_e = _edges(ref)
    if mask_png is not None:
        m = _grey(mask_png, size) > 0.5
        ref_e &= _dilate(m, scale * 2)
    cand_e = _dilate(_edges(cand), scale)

    total = int(ref_e.sum())
    if total == 0:
        return {"recall": 0.0, "reference_edge_px": 0, "matched_px": 0,
                "tolerance_px": tolerance_px, "threshold": FIDELITY_MIN,
                "passed": False,
                "reason": "the reference render has no edges to check "
                          "against — was the canvas blank?"}
    matched = int((ref_e & cand_e).sum())
    recall = matched / total
    return {"recall": round(recall, 4), "reference_edge_px": total,
            "matched_px": matched, "tolerance_px": tolerance_px,
            "threshold": FIDELITY_MIN, "passed": recall >= FIDELITY_MIN,
            "reason": ("" if recall >= FIDELITY_MIN else
                       f"the picture kept only {recall * 100:.0f}% of the "
                       f"measured geometry's edges (needs "
                       f"{FIDELITY_MIN * 100:.0f}%) — a wall, roof line "
                       f"or the camera moved")}
