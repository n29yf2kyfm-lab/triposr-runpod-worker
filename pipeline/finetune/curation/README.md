# Training-set curation — per-shape cull verdict

`train_cull_verdict.json` is one row per volume-resident training shape (964 of
them), keyed by the sha256 the dataset uses:

```json
{"n": 1, "sheet": 1, "sha256": "001c39ee…", "verdict": "cull",
 "reason": "dune buggy - not a road car"}
```

`verdict` is `keep`, `cull`, or `ungraded`.

## How the calls were made

Every shape was eyeballed in the 33 contact sheets under
`car-meshes/audit/train/` (one tile per shape, `#N + sha prefix`, mapped by
`INDEX.json`). No GPU, no render spend — the sheets reuse the conditioning
renders that already existed.

The bar is the owner's audit rubric in `CLAUDE.md`: premium fidelity, correct
vehicle, clean geometry. Applied as these rules, in order:

1. **Not a vehicle** → cull. Statues, busts, skulls, houses, dioramas, sofas,
   rocks, exhibition stands, molecules, primitives.
2. **Wrong vehicle class** → cull. Vans and van-derived MPVs, pickups, lorries,
   artic units, buses, military, agricultural/plant, motorcycles, single-seaters.
   The product turns a UK reg into a *car*; a Transit teaches the model the
   wrong prior.
3. **Outside the modern UK-road era** (roughly pre-1990) → cull. Classic 500s,
   E-Types, Beetles, 1980s cabrios. They are real cars but not what a plate
   lookup returns, and their geometry drags the prior backwards.
4. **Broken geometry or presentation** → cull. Rotated 90°/top-down, wrecks,
   detached panels, floating fragments, baked ground planes and display discs,
   wireframe/mesh-line artifacts, near-empty tiles.
5. **Scan mush / no readable detail** → cull. Featureless blobs, noisy
   photogrammetry, magenta missing-texture patches, near-black silhouettes.
6. **Non-stock** → cull. Race, police, camo, advertising and custom liveries,
   roof light bars, overland builds, rat rods, toys.

Untextured grey models are **kept** — flat colour is fine for shape supervision
as long as the body reads sharply. Blobby untextured bodies are not.

## Known limits, stated plainly

* **Sheet 6 is missing from the bucket**, so shapes #151–#180 are `ungraded`.
  They are neither kept nor culled until that sheet is regenerated.
* One tile per shape is a single view. It reliably catches wrong-vehicle, junk
  and broken geometry; it does *not* prove the far side of a car is clean.
* Rule 3's era cutoff is a judgement call, not a measurement. It is the single
  rule most likely to be overridden, and it is recorded per row so an override
  is a filter, not a re-audit.
