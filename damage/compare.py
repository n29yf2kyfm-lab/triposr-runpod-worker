"""Before/after damage diff — DAMAGE iD's "Going Out" vs "Return".

The single most valuable thing a fleet, a rental desk or a car-share does with
an inspection is compare it to the last one: what is NEW since the vehicle went
out. That is the whole basis of a damage claim against a driver, and getting it
right — not flagging pre-existing damage as new — is what makes the claim
stick or fail.

The diff is on FINDINGS, not pixels: two inspections, each already reduced to
panel + damage_type + severity, are matched. A finding matches its baseline
when the same damage_type sits on the same panel. Then:

  new       in the current inspection, no baseline match  -> chargeable
  worsened  matched, but severity rose by >= the threshold -> chargeable delta
  resolved  in the baseline, gone now (repaired, or not re-captured)
  unchanged matched at similar severity                    -> pre-existing

`resolved` is reported but never charged — a panel not re-photographed on
return looks "resolved", and calling that a repair would be wrong. The honest
line, same as everywhere in this codebase: coverage gaps are surfaced, not
papered over.
"""
from taxonomy import clamp_severity, canonical_panel, canonical_damage

# How much severity must rise on a matched finding to count as "worsened"
# rather than measurement noise between two shoots.
WORSEN_THRESHOLD = 2


def _key(f):
    return (canonical_panel(f.get("panel")) or "body_other",
            canonical_damage(f.get("damage_type")))


def diff(current, baseline):
    """Diff current findings against a baseline. Returns the four buckets and
    a chargeable summary."""
    base_by_key = {}
    for f in baseline or []:
        base_by_key.setdefault(_key(f), []).append(f)

    new, worsened, unchanged = [], [], []
    used = set()

    for f in current or []:
        k = _key(f)
        pool = base_by_key.get(k, [])
        # find an unused baseline finding on the same panel+type
        match_idx = next((i for i, _b in enumerate(pool)
                          if (k, i) not in used), None)
        if match_idx is None:
            new.append(f)
            continue
        used.add((k, match_idx))
        b = pool[match_idx]
        cur_sev = clamp_severity(f.get("severity", 5))
        base_sev = clamp_severity(b.get("severity", 5))
        if cur_sev - base_sev >= WORSEN_THRESHOLD:
            worsened.append({**f, "baseline_severity": base_sev,
                             "severity_delta": cur_sev - base_sev})
        else:
            unchanged.append(f)

    resolved = []
    for k, pool in base_by_key.items():
        for i, b in enumerate(pool):
            if (k, i) not in used:
                resolved.append(b)

    chargeable = new + worsened
    return {
        "new": new,
        "worsened": worsened,
        "unchanged": unchanged,
        "resolved": resolved,
        "chargeable": chargeable,
        "summary": {
            "new": len(new),
            "worsened": len(worsened),
            "unchanged": len(unchanged),
            "resolved": len(resolved),
            "chargeable": len(chargeable),
        },
        "note": ("'resolved' items were in the baseline but not the current "
                 "capture — repaired, or simply not re-photographed. They are "
                 "never charged. Re-capture the same angles to be certain."),
    }
