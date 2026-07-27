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

## Second pass: the hardened title audit

The visual verdict was then put through the repo's own "hard audit" gates
(`objaverse_wave4.py`: `BAD`, `WRONG_CLASS`, `VEHICLE_NAME`). Joining the two
required a sha256 → title map, which was rebuilt by streaming all 1,111
catalogue/wave GLBs and hashing the bytes — the same hash
`prepare_dataset.py` uses. 889 of 964 shapes joined; the other 75 carry
`title_audit: "unjoined"` and rest on the visual call alone.

**Running the gates first exposed three defects in the gates themselves**, each
verified against real titles rather than assumed:

| Defect | Effect | Evidence |
|---|---|---|
| `WRONG_CLASS` ended `)\\b` in an r-string | matched **nothing**, ever | 0/8 hits on the titles it was claimed to catch |
| `BAD` had **no** closing `\b` | matched prefixes: "toy" in **Toyota**, "scan" in "scanner", "pack" in "Packard" | 15 Toyotas flagged as toy assets |
| `norm()` left `-` and `_` intact | `\b` never fires beside `_`; hyphens split marques | "Rolls-Royce Ghost", "Renault_Kadjar_2018", "Cupra_Terramar" all rejected as "not a car" |

`BRANDS` was also missing Ferrari, Lamborghini, McLaren, Lincoln, Polestar,
BYD, Alpina and Pontiac, which alone rejected 31 genuine cars.

After the fixes the gates were re-tested in both directions (18 must-pass,
17 must-flag, 0 failures) and measured over 2,155 real titles: 48 hits, all 48
genuine non-cars, **zero false positives**.

The audit then changed 21 verdicts:

* **5 keeps → culls.** Three unmarked police vehicles, a race-team car and a
  photogrammetry scan. All five render as ordinary stock cars — no single view
  could have caught them. This is the audit earning its place.
* **16 of the 30 sheet-6 shapes decided** from their titles ("Truck Nutz",
  "Beast Van Shelf", "Sugar Rush Vanellope car", Dutch museum boards whose
  "van" is a name particle, a Fiat Ducato, a Jeep Gladiator, an E30 DTM).
  14 remain `ungraded` — their titles read like real cars, and a title cannot
  prove a model is *good*.

Where the audit disagreed with the eye and the eye was right, the eye won:
"Speed Pack" is a Jaguar trim, "Juke" and "Rav4" are cars whose titles omit the
marque, and `norm()` strips CJK entirely so 五菱星辰 (Wuling Xingchen) reads as
an empty string. Those stay `keep`.

Every row now carries `source_title`, `title_audit` and `decided_by`, so any
verdict can be traced to what decided it.

## Known limits, stated plainly

* **Sheet 6 is missing from the bucket.** 16 of its 30 shapes were settled by
  the title audit; the remaining 14 stay `ungraded` until it is regenerated.
* **75 shapes never joined to a source title** — they are on the volume but not
  in `audit_manifest.json`, so only the visual call applies to them.
* A title audit cannot see quality. It catches wrong class, junk and non-stock
  provenance; it cannot tell a sharp model from a soft one.
* `norm()` drops non-ASCII, so CJK-titled assets reach the name test empty and
  fail it. Treat "name does not identify a car/van" on a CJK title as no
  information, not as a cull.
* One tile per shape is a single view. It reliably catches wrong-vehicle, junk
  and broken geometry; it does *not* prove the far side of a car is clean.
* Rule 3's era cutoff is a judgement call, not a measurement. It is the single
  rule most likely to be overridden, and it is recorded per row so an override
  is a filter, not a re-audit.
