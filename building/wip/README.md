# Work in progress — not wired in, not shipped

## register.py.wip — open↔closed scan alignment

Deliberately parked with a `.wip` extension so the handler cannot import it.
`handler.py` maps mode `register` to a module named `register`, so simply
creating `building/register.py` would have made the mode LIVE. For a module
whose entire purpose is to refuse unless it is certain, shipping an
unverified version would contradict the thing it exists to do — a bad
registration puts a live cable somewhere other than where the app draws it.

### What works

- 3-DOF rigid transform (yaw + translation), composition verified against
  sequential application
- Closed-form 2D Procrustes step — recovers a known rotation and translation
  exactly, no SVD or numpy needed
- Spatial hash for neighbour lookup, ~15 lines, no KD-tree
- **Global yaw via the Manhattan prior** — sweep the plan-view bounding box
  and take the minimum-area angle, then refine locally. This recovers 12° as
  11.97° and −8° as −7.93°, and unlike ICP it cannot slide into a local
  minimum because it does not descend anything
- Accept-only-improving ICP steps against a truncated least-squares cost
- The verify()/align() split, so a caller cannot use a fit nobody checked

### What does not

End-to-end alignment leaves a **~13 mm median residual** where it should be
near zero, and the inlier ratio sits around 0.26 against a 0.35 floor — so
`verify()` correctly refuses its own output on a synthetic room it should
align perfectly. Yaw is right; something in the translation or the
correspondence set is not.

### What was learned along the way, all of it real

- **Point-to-point ICP slides on flat surfaces**, and a room is mostly flat
  surfaces. Left unchecked it walks away from a good global alignment into a
  worse one that still reduces its own local objective.
- **Converge on the step, not the error.** RMSE plateaus while the transform
  is still sliding.
- **Never thin the target.** Only the source costs time; a denser target
  strictly improves every correspondence. Worse, point clouds are written in
  a structured order, so striding decimates along one axis instead of
  sampling evenly.
- **A bare rectangular room is 180°-symmetric**, so a flipped alignment fits
  it exactly as well as the right one. Real rooms have a chimney breast, a
  bay or a door; a test fixture needs one too or it is genuinely ambiguous.
- **A regular lattice is an unrealistic worst case.** Rotate one and every
  point lands between grid nodes, so nothing finds a neighbour inside the
  inlier radius however good the alignment is.

### Next step

Point-to-plane ICP, which does not slide on flat surfaces — it needs surface
normals, which `structure.py` already computes planes for. That is the
standard fix and it is the right one here.
