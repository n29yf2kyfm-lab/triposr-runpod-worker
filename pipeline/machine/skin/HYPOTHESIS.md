# Double-skin: hypothesis and falsification, written BEFORE any probe was built

Date: 2026-08-21. Input: car_rebound.glb, sha256 5380761c…c88e0, 985,227 faces, 30 meshes.

## H1 (the claim I am testing)
A subset of faces form NEAR-COINCIDENT ANTI-PARALLEL PAIRS: two sheets of surface at
essentially zero separation, one of which is a redundant copy of the other. A ray tracer
cannot order them, so it returns a random one per sample → speckle in the render, in the
colours of the two materials involved.

## What would prove H1 WRONG — decided now, checked later

F1. **Separation distribution.** If the pair separations cluster at a PHYSICALLY REAL
    thickness (glass 2–5 mm, a bumper lip, a tyre sidewall, a mirror stalk), the pairs are
    the two faces of a THIN SOLID and deleting one sheet destroys real geometry.
    H1 requires a spike at ~0 mm (sub-0.5 mm), not a bump at a real thickness.

F2. **Two-sided visibility.** If BOTH sheets of a pair are "first thing hit from outside"
    from a comparable share of directions, the pair is a thin solid seen from both sides
    (mirror stalk, spoiler blade, an open panel edge). H1 requires an ASYMMETRY: one sheet
    is first-hit from outside, the other essentially never is.

F3. **Hole opening.** If deleting the loser sheet lets rays that previously hit the car now
    pass through, the loser was load-bearing, not redundant. Any new escape is a
    falsification for that face.

F4. **The speckle survives.** If the matched before/after render at the same camera and
    exposure shows the same speckle count, the doubling was not its cause and I must say so.

F5. **Detector cannot fail.** If a synthetic SINGLE-sheet panel scores > 2% doubled, or a
    synthetic deliberately-doubled panel scores < 90%, the detector is measuring itself and
    nothing it says is admissible.

## Traps I must not walk into (from CLAUDE.md and the brief)
- NOT by face normal — 46% of faces in the lamp band are flipped; Gate 5 found inward-
  pointing faces on a correct surface.
- NOT by centroid-inward test — reads 44.89% on v5 lenses that are demonstrably correct.
- NOT by material name — `interior` holds ~45% of exterior panel area on this family.
- The keeper is decided by RAY/OPENNESS from outside, never by normal direction.
- openness v1 (rays outward from the face) self-hits and reads 0.000 for everything
  including its own exterior control. Use INVERTED rays: start outside, shoot inward,
  ask whether this face is the FIRST hit.
