"""Metric scale for a reconstruction — pure stdlib.

Photogrammetry recovers shape, not size. A reconstruction from a phone
camera is correct in every proportion and arbitrary in every dimension, so
without an external reference a beautiful model of a house is also a
beautiful model of a doll's house. Everything downstream — quantities,
prices, whether an extension fits — depends on getting this one number
right, which is why it lives in its own module with its own tests.

Two paths, in order of trust:

  LiDAR   depth is metric at capture. Nothing to estimate.
  ANCHORS objects of known real size, measured in model units.

The anchor table is UK-specific and deliberately so. Hover's US patent
(US20160224696A1) matches door and brick RATIOS against a standards
library; this does something better suited to British stock — see
BRICK_COURSE below.
"""
import math
import statistics

# --- UK reference dimensions ----------------------------------------------
#
# Each entry: (metres, tolerance_m, note). Tolerance is real-world variation
# in the stock itself, not measurement error — a door is 762mm by standard,
# but the one in front of you might not be.

# THE best scale reference in Britain. A standard brick is 215x102.5x65mm
# laid with a 10mm joint, so four courses rise exactly 300mm. It is a
# national standard, it appears on most of the housing stock, it is visible
# in any exterior photograph, and — the part that matters — it REPEATS.
# Measuring twenty courses averages the error across twenty joints instead
# of trusting one object, which is why it beats a door by a wide margin.
BRICK_COURSE = (0.075, 0.004, "one brick course incl. 10mm joint")
BRICK_COORD = (0.225, 0.006, "brick coordinating length incl. joint")

REFERENCES = {
    "brick_course":     BRICK_COURSE,
    "brick_length":     BRICK_COORD,
    # Building Regs Part M mandates these, so they are enforced rather than
    # conventional — the most dependable INDOOR anchors, and not something
    # an exterior-focused method covers at all.
    "socket_height":    (0.450, 0.025, "Part M socket centre above FFL"),
    "switch_height":    (1.200, 0.050, "Part M switch centre above FFL"),
    "door_internal_w":  (0.762, 0.012, "standard internal door leaf"),
    "door_internal_h":  (1.981, 0.010, "standard internal door leaf"),
    "door_external_w":  (0.838, 0.025, "common external door leaf"),
    "plasterboard_w":   (1.200, 0.005, "standard board"),
    "plasterboard_h":   (2.400, 0.005, "standard board"),
    "scaffold_tube":    (0.0483, 0.0005, "scaffold tube outside diameter"),
    "stair_rise":       (0.200, 0.020, "typical domestic rise — WEAK"),
    "ceiling_height":   (2.400, 0.150, "typical domestic — WEAK"),
}

# Anchors whose real-world spread is wide enough that they should never
# decide a scale on their own.
WEAK = {"stair_rise", "ceiling_height"}

# Below this, refuse to report a scale at all. One observation cannot be
# checked against anything, and an unverified scale is worse than none —
# it looks authoritative and quietly multiplies through every quantity.
MIN_OBSERVATIONS = 2

# Reject an observation this many robust deviations from the median.
OUTLIER_MADS = 3.0

# Above this relative spread the observations are not describing the same
# scene at the same scale, and no median of them is trustworthy.
MAX_SPREAD = 0.10


class ScaleError(ValueError):
    """Raised when a metric scale cannot be established. Deliberately fatal:
    the caller must not fall back to 'unscaled but probably fine'."""


class Observation:
    """One sighting of a known object, measured in arbitrary model units.

    `repeats` is what makes brick coursing strong: measuring 20 courses in
    one span is a single observation carrying 20x the evidence, because the
    per-joint error averages down rather than accumulating.
    """

    def __init__(self, kind, measured_units, repeats=1, weight=1.0):
        if kind not in REFERENCES:
            raise ScaleError(
                f"unknown reference {kind!r}; known: "
                f"{', '.join(sorted(REFERENCES))}")
        if measured_units <= 0:
            raise ScaleError(f"{kind}: measured_units must be positive")
        if repeats < 1:
            raise ScaleError(f"{kind}: repeats must be at least 1")

        self.kind = kind
        self.measured_units = float(measured_units)
        self.repeats = int(repeats)
        self.weight = float(weight)

    @property
    def real_metres(self):
        return REFERENCES[self.kind][0] * self.repeats

    @property
    def scale(self):
        """Metres per model unit."""
        return self.real_metres / self.measured_units

    @property
    def relative_tolerance(self):
        """Fractional uncertainty from the stock's own variation.

        Repeats reduce it as sqrt(n): independent joint-to-joint variation
        partially cancels rather than compounding.
        """
        metres, tol, _ = REFERENCES[self.kind]
        return (tol / metres) / math.sqrt(self.repeats)

    @property
    def effective_weight(self):
        """Tighter references and longer spans count for more."""
        base = self.weight / max(self.relative_tolerance, 1e-6)
        if self.kind in WEAK:
            base *= 0.25
        return base

    def __repr__(self):
        return (f"Observation({self.kind}, {self.measured_units:.4f}u x"
                f"{self.repeats} -> {self.scale:.6f} m/u)")


def _weighted_median(pairs):
    """Median of (value, weight), by cumulative weight."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return statistics.median([v for v, _ in pairs])
    half, run = total / 2.0, 0.0
    for value, weight in pairs:
        run += weight
        if run >= half:
            return value
    return pairs[-1][0]


def estimate_scale(observations, min_observations=MIN_OBSERVATIONS):
    """Combine observations into one metres-per-model-unit factor.

    Robust by construction: a weighted median rather than a mean, then
    outlier rejection by median absolute deviation, then a spread check.
    A single mis-detected reference — a fire door counted as a standard
    one, a soldier course counted as stretchers — should move the answer
    barely at all, and if it cannot be outvoted the whole estimate is
    refused rather than quietly skewed.

    Returns a report dict. Raises ScaleError when no trustworthy scale
    exists; callers must not paper over that.
    """
    observations = list(observations)
    if len(observations) < min_observations:
        raise ScaleError(
            f"need at least {min_observations} scale references, got "
            f"{len(observations)}. A single reference cannot be checked "
            f"against anything. Capture a run of brickwork (best), or a "
            f"socket and a door in the same pass.")

    # ROBUSTNESS FIRST, precision second. The centre used for outlier
    # detection is an UNWEIGHTED median.
    #
    # Weighting it would defeat the purpose: weight rises as stated
    # tolerance falls, and a door leaf is specified more tightly than a
    # brick joint — so a single misidentified door outvoted twenty courses
    # of brickwork that agreed with each other, and the "robust" median
    # landed on the one wrong reading. Every observation gets one vote here;
    # weights are applied only to the survivors below.
    scales_all = [o.scale for o in observations]
    median = statistics.median(scales_all)

    # Median absolute deviation — a robust stand-in for standard deviation.
    deviations = [abs(s - median) for s in scales_all]
    mad = statistics.median(deviations)

    kept, rejected = [], []
    for obs, dev in zip(observations, deviations):
        # With a tight cluster MAD collapses toward zero, so allow each
        # observation its own stated tolerance before calling it an outlier.
        allowance = max(OUTLIER_MADS * mad,
                        median * obs.relative_tolerance * 2.0)
        (kept if dev <= allowance else rejected).append(obs)

    if len(kept) < min_observations:
        raise ScaleError(
            f"scale references disagree: {len(rejected)} of "
            f"{len(observations)} rejected as outliers, leaving too few to "
            f"agree on a scale. Likely a misidentified reference — check "
            f"the detections before trusting any dimension.")

    # Weights now apply, but capped: no single observation may carry more
    # than half the total, so precision-weighting can refine the answer
    # without any one reading being able to dictate it.
    #
    # The cap is each weight against the SUM OF THE OTHERS. Capping against
    # half the RAW total looked equivalent and was not: clipping the big
    # weight shrinks the total too, so a door leaf (specified to 0.5%,
    # weight ~200) reading high within its outlier allowance still held two
    # thirds of the FINAL total and the weighted median sat exactly on the
    # door, against a socket and a ceiling that agreed with each other. At
    # most one weight can exceed the sum of the rest, so at most one is
    # clipped — to exactly half the final total, where it can tie but never
    # decide the median alone.
    raw = [o.effective_weight for o in kept]
    if len(raw) > 1:
        capped = [min(w, sum(raw) - w) for w in raw]
    else:
        capped = raw
    final_pairs = [(o.scale, w) for o, w in zip(kept, capped)]
    scale = _weighted_median(final_pairs)

    scales = [s for s, _ in final_pairs]
    spread = (max(scales) - min(scales)) / scale if scale else float("inf")
    if spread > MAX_SPREAD:
        raise ScaleError(
            f"scale references span {spread * 100:.1f}% ({min(scales):.5f} "
            f"to {max(scales):.5f} m/unit), beyond the "
            f"{MAX_SPREAD * 100:.0f}% limit. The reconstruction may have "
            f"drifted, or references from different rooms were mixed. "
            f"Re-capture rather than quote from this.")

    # Uncertainty: the better of what the references claim and what they
    # actually agree on — never flatter than the observed disagreement.
    claimed = min(o.relative_tolerance for o in kept)
    observed = spread / 2.0 if len(kept) > 1 else claimed
    uncertainty = max(claimed, observed)

    return {
        "scale_m_per_unit": scale,
        "source": "anchors",
        "uncertainty_pct": round(uncertainty * 100, 2),
        "observations_used": len(kept),
        "observations_rejected": len(rejected),
        "rejected": [o.kind for o in rejected],
        "references": sorted({o.kind for o in kept}),
        "total_repeats": sum(o.repeats for o in kept),
        "spread_pct": round(spread * 100, 2),
        "confidence": _confidence(kept, uncertainty, rejected),
    }


def _confidence(kept, uncertainty, rejected):
    """A word, not a number — a quote needs a decision, not a probability."""
    distinct = len({o.kind for o in kept})
    repeats = sum(o.repeats for o in kept)
    strong = [o for o in kept if o.kind not in WEAK]

    if not strong:
        return "low"
    if uncertainty <= 0.01 and distinct >= 2 and repeats >= 8:
        return "high"
    if uncertainty <= 0.03 and (distinct >= 2 or repeats >= 6):
        return "good"
    if uncertainty <= 0.06:
        return "fair"
    return "low"


def from_lidar(depth_available=True):
    """Scale when the capture carries LiDAR depth: it is already metric."""
    if not depth_available:
        raise ScaleError("no LiDAR depth in this capture")
    return {
        "scale_m_per_unit": 1.0,
        "source": "lidar",
        # Apple's LiDAR is roughly 1% over domestic room distances; it
        # degrades past ~5m and on dark, glossy or transparent surfaces.
        "uncertainty_pct": 1.0,
        "observations_used": 0,
        "observations_rejected": 0,
        "rejected": [],
        "references": [],
        "total_repeats": 0,
        "spread_pct": 0.0,
        "confidence": "high",
    }


def from_manual(measured_m, model_units):
    """Scale from one dimension the user measured with a tape.

    Trusted, because a person deliberately measuring a wall is better
    evidence than any automatic detection — but still single-point, so it
    carries no cross-check and says so.
    """
    if measured_m <= 0 or model_units <= 0:
        raise ScaleError("manual scale needs positive measurement and span")
    return {
        "scale_m_per_unit": measured_m / model_units,
        "source": "manual",
        "uncertainty_pct": 1.0,
        "observations_used": 1,
        "observations_rejected": 0,
        "rejected": [],
        "references": ["manual"],
        "total_repeats": 1,
        "spread_pct": 0.0,
        "confidence": "good",
        "note": "Single manual reference — no independent check. An error "
                "here scales every dimension in the model.",
    }


def apply(points, scale_m_per_unit):
    """Scale a point set into metres."""
    s = scale_m_per_unit
    return [(x * s, y * s, z * s) for x, y, z in points]


def describe(report):
    """One line for logs and the job response."""
    if report["source"] == "lidar":
        return "scale from LiDAR depth (metric at capture, ~1%)"
    if report["source"] == "manual":
        return (f"scale from a manual measurement "
                f"(±{report['uncertainty_pct']}%, no cross-check)")
    return (f"scale from {report['observations_used']} references "
            f"({', '.join(report['references'])}), "
            f"{report['total_repeats']} repeats, "
            f"±{report['uncertainty_pct']}% — {report['confidence']}")
