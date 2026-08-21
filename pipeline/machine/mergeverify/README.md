# mergeverify — the independent verifier for the merged Golf Mk8

Built to answer one question in advance of the merge: **what does "all six gates'
wins survived" measurably mean, and can each of those measurements FAIL?**

Nothing here reads another agent's report to produce a number. Reports are read only
to learn what quantity was claimed, so the same quantity is measured.

## The rules this harness is built around (each already paid for in CLAUDE.md)

* **Never round-trip through trimesh to judge materials.** trimesh silently drops
  every KHR material extension on any glTF round-trip — transmission, IOR and
  clearcoat vanish while `alphaMode` survives. `glbcore.Glb` parses the GLB
  container and reads the JSON chunk directly, so the material table judged is the
  one the file ships.
* **`glass_probe` alone is NOT sufficient.** It reads the material TABLE and never
  asks how much SURFACE carries it. Demonstrated here end-to-end: the real
  `glass_probe` returns `clear / proven` on a car whose windscreen geometry was cut
  to 2.5% of its area, on a car whose windscreen is bound to `carpaint`, and on a
  car with every KHR extension stripped. Every glazing verdict is therefore a PAIR
  — verdict **and** glass-area retention (`matcheck.glazing_pair`).
* **Grounding is measured from the TYRE NODES' world-space minima**, never the
  whole-model bbox: on this very car the bbox reads −4.6 mm while the tyres are on
  the floor, and `viewer_check.py` passes a car with its front tyres 183 mm up.
* **Measure from TRANSFORMED vertices**, never node translations — downstream stages
  bake instance transforms and a graph read returns zeros.
* **A gate that cannot fire is not a gate.** `glbedit.py` builds real files with a
  real defect injected, and every check is run end-to-end over them. Injected
  magnitudes come back at slope 1.000 (5.000 mm → 5.0000 mm; 3.000 mm → 3.000030 mm)
  — the point of injecting into the real CLI path rather than unit-testing a fitter.
* **The hole test must not use `intersects_any`**, which can never see a hole because
  the cabin sits behind every panel. `holes.py` reports LOST first-surface *and*
  RECEDED first-surface, so an outer skin that vanishes behind an interior is caught.
* **Blender: CYCLES only, `use_denoising=False`** (no OIDN in this container — the
  render dies after "Blender quit" prints and leaves stale frames; wait on this
  script's own `BL_RENDER_DONE_MARKER`), **Standard view transform never AgX**,
  orthographic, and exposure verified numerically with the clipped fraction reported.

## Modules
| file | what it measures |
|---|---|
| `glbcore.py` | GLB/glTF reader: scene graph with world matrices, accessors incl. sparse and interleaved |
| `measure.py` | frame derivation, tyre grounding, node/material area, centroid provenance, symmetry, centreline |
| `matcheck.py` | NORMAL accessors, written material table incl. KHR extensions, glazing verdict+area PAIR, tyre and paint checks |
| `raycast.py` | all-hits Möller–Trumbore + a binned accelerator; `selftest()` proves 2 hits on a closed shell and detects a punched cap |
| `holes.py` | 15 directions (az 0/±22/±40 × el 0/±18), before vs after: lost / gained / receded / advanced |
| `panel.py` | waviness as quadric residual at a fixed PHYSICAL radius, plus fit-free dihedral roughness |
| `respray.py` | per-material respray control against a material-ID pass at the same locked camera; dark-speck count with its clay floor |
| `glbedit.py` | negative-control builder (append-only BIN edits) |
| `gltf_validate.js` | official Khronos validator with JSON output (`gltf-transform validate` has no json format) |

## Known limits, stated rather than hidden
* `panel.waviness` conflates intentional creases with ripple, so it is only valid
  comparing large smooth panels like-for-like. It reports v7's grille as "wavy".
* Hidden-melt percentage is ray-placement sensitive by roughly ±2 pp.
* The through-glass ray bundle is aimed along a node's mean normal, which is
  meaningless for a wrap-around node whose normals cancel (`Glass_Rear` here) —
  that node is NOT TESTED by it rather than silently scored.
