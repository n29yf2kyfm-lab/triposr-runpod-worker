"""From a list of findings to one honest number — pure stdlib.

AutoScan shows a car a "46/100". A single headline score is good product
design: it is what a buyer, a fleet manager or a rental-return clerk actually
wants first. But a score is only as trustworthy as the way it is computed, so
this module is deliberately explicit about the arithmetic and never hides a
severe finding inside an average.

Design rules, each learned from how the competitor scores mislead:

  1. The score is DAMAGE SUBTRACTED FROM 100, not an average of panel scores.
     Averaging lets twenty clean panels bury one cracked chassis rail. We
     subtract a penalty per finding, so more damage always lowers the score.

  2. Penalty grows FASTER than linearly with severity. A sev-8 structural
     crack is far more than twice a sev-4 scuff. Squared severity captures
     that without needing a bespoke curve.

  3. Structural and safety panels weigh more (taxonomy.PANEL_WEIGHT) and
     structural damage types weigh more again. A windshield crack and a
     bumper scuff at the same severity are not the same event.

  4. The worst single finding sets a CEILING on the score. One sev-10 finding
     (write-off risk, airbag deployment, structural) cannot coexist with a
     "clean" headline number no matter how tidy the rest of the car is.
"""
from taxonomy import (clamp_severity, severity_band, PANEL_WEIGHT,
                      DEFAULT_PANEL_WEIGHT, DAMAGE_TYPES)

# Damage-type multipliers on top of the panel weight. Structural / safety
# damage costs value out of proportion to how it looks.
DAMAGE_WEIGHT = {
    "shattered_glass": 1.6, "crack": 1.5, "rust": 1.5, "deformation": 1.4,
    "missing_part": 1.4, "misalignment": 1.3, "dent": 1.1, "lamp_damage": 1.2,
    "tire_damage": 1.2,
}
DEFAULT_DAMAGE_WEIGHT = 1.0

# The per-finding penalty at severity s, before weighting:
#   PENALTY_K * (s/10)^2 * 100
# Tuned so a single moderate cosmetic finding (sev 4, weight 1.0) costs ~3
# points, a major structural one (sev 8, weights ~2.2) costs ~34, and a
# handful of severe findings drive the score into the danger zone — matching
# how AutoScan's 46/100 reads against "significant rust and major dents".
PENALTY_K = 0.18

# Score bands -> letter grade + descriptor. The app colours the gauge from
# the band; the descriptor is what goes on the report headline.
GRADE_BANDS = [
    (90, 100, "A", "excellent",  "#3fb950"),
    (75, 89,  "B", "good",       "#9ece6a"),
    (60, 74,  "C", "fair",       "#e3b341"),
    (40, 59,  "D", "poor",       "#f0883e"),
    (0,  39,  "F", "severe",     "#f85149"),
]


def finding_weight(finding):
    """Combined structural weight of a single finding."""
    pw = PANEL_WEIGHT.get(finding.get("panel"), DEFAULT_PANEL_WEIGHT)
    dw = DAMAGE_WEIGHT.get(finding.get("damage_type"), DEFAULT_DAMAGE_WEIGHT)
    return pw * dw


def finding_penalty(finding):
    """Points this finding removes from a perfect 100."""
    sev = clamp_severity(finding.get("severity", 5))
    base = PENALTY_K * (sev / 10.0) ** 2 * 100.0
    return base * finding_weight(finding)


def grade_for(score):
    """(letter, descriptor, colour) for a 0-100 score."""
    score = max(0, min(100, score))
    for lo, hi, letter, descriptor, colour in GRADE_BANDS:
        if lo <= score <= hi:
            return letter, descriptor, colour
    return "F", "severe", "#f85149"


def condition_score(findings):
    """Overall 0-100 condition score for a set of findings.

    Returns the integer score. Empty findings -> 100 (nothing found IS the
    result, not a missing value). The worst finding caps the score so a single
    catastrophic item cannot be averaged away.
    """
    if not findings:
        return 100
    total_penalty = sum(finding_penalty(f) for f in findings)
    score = 100.0 - total_penalty

    # Ceiling from the single worst finding: a sev-9/10 structural item alone
    # limits how high the headline can be, regardless of the total.
    worst = max(clamp_severity(f.get("severity", 5)) * finding_weight(f)
                for f in findings)
    if worst >= 14:      # e.g. sev 9-10 on a structural/safety panel
        score = min(score, 35)
    elif worst >= 10:    # e.g. sev 8 structural, or sev 10 cosmetic
        score = min(score, 55)
    elif worst >= 7:
        score = min(score, 72)

    return int(max(0, min(100, round(score))))


def summarize(findings):
    """A compact roll-up the report and the app both consume.

    counts by severity band and by region, the headline score and grade, and
    the single worst finding — everything needed to render the top of a report
    without re-walking the finding list.
    """
    score = condition_score(findings)
    letter, descriptor, colour = grade_for(score)

    by_band, by_region, by_type = {}, {}, {}
    worst = None
    for f in findings:
        sev = clamp_severity(f.get("severity", 5))
        band, _ = severity_band(sev)
        by_band[band] = by_band.get(band, 0) + 1
        region = f.get("region") or "other"
        by_region[region] = by_region.get(region, 0) + 1
        dtype = f.get("damage_type", "other")
        by_type[dtype] = by_type.get(dtype, 0) + 1
        if worst is None or sev > clamp_severity(worst.get("severity", 5)):
            worst = f

    return {
        "condition_score": score,
        "grade": letter,
        "grade_descriptor": descriptor,
        "grade_colour": colour,
        "finding_count": len(findings),
        "by_severity_band": by_band,
        "by_region": by_region,
        "by_damage_type": by_type,
        "worst_finding": ({
            "panel": worst.get("panel"),
            "damage_type": worst.get("damage_type"),
            "severity": clamp_severity(worst.get("severity", 5)),
        } if worst else None),
        # a structural flag the app can gate a "get this inspected" banner on
        "structural_concern": any(
            DAMAGE_TYPES.get(f.get("damage_type", "other"), (None, False))[1]
            and clamp_severity(f.get("severity", 5)) >= 6
            for f in findings),
    }
