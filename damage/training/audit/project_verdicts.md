# Per-project verdicts (20-image sheet each, keep rows only)

| project | keep rows | verdict | what I saw |
|---|---|---|---|
| container-damage-ke5bc/dent-detection-4qxiu | 961 | DROP | shipping containers, not cars |
| vehicle-detection-yjf3z/car-dent-scratch-detection | 8,168 | DROP | an augmented export: vertical flips (cars upside down), heavy noise/HDR, and alamy watermarks that are MIRRORED -- which is exactly why OCR never read them |
| changs-workspace-hnorg/vehicle-damage-gwmh4 | 5,896 | KEEP, filter | best source seen: real phone photos of Thai pickups, fingers pointing at damage. ~5/20 have detector prediction boxes baked into the pixels ("minor-scratch 0.43") -- label leakage, must be filtered |
| haedars-workspace/car-scratch-new | 4,744 | KEEP, filter | stock-heavy: tiled alamy on ~3/20, a mechanic posing, one illustration; rust labelled scratch x2; ~11/20 genuinely usable |
| UNSOURCED (first ingestion, zips gone) | 37,568 | per-image | mixed ~50%: dreamstime watermark, a NASCAR car labelled dent, no-damage BMW labelled dent, plus plenty of clean frames |
| datasetyolo/broken-car-od | 3,365 | DROP | augmented export: cars upside down (#8, #9, #13), rotated frames, shutterstock 2018098433 on a vintage car in grass with no damage |
| damage-detection-d25qu/vehicle-damage-detection-hhxfj | 3,343 | KEEP | real collision photos, mild rotation only, hand-with-tape measuring a scratch; ~17/20 usable |
| curacel-ai/car-damage-detection-5ioys | 2,971 | DROP | the watermark motherlode: shutterstock/dreamstime bars on nearly every frame, many rotated 90 degrees, heavy noise |
| project-joggx/car-damage-assessment-8mb45 | 2,774 | KEEP | Indian insurance-inspection photos with GPS/time stamps (Delhi, Noida, Faridabad); ~16/20 usable; second-best source after changs |
| rfvnx-dgm7e/car-damage-c1f0i-epb08 | 2,276 | DROP | alamy/dreamstime/shutterstock on ~8/20, noise aug, one flip; shutterstock 1107699365 appears here AND in the dent sheet -- a cross-project duplicate the hash dedup missed because noise aug changed the pixels |

Running total of sourced keep rows: DROP 17,741 / KEEP 12,013 / KEEP-with-filter 4,744 / unsourced 37,568.
Pattern: every DROP is a project that exported with Roboflow augmentations (flip, rotate, noise) or scraped stock sites. Both defeat hash dedup and OCR.
| cardamage-jrvmi/car-damage-cqreo | 1,163 | KEEP, filter | real photos, mild rotation; gettyimages on one, a "Quick Dent Removal" business logo on one; a panel_gap box sits on a crushed Mazda front (collision, not a gap); ~15/20 usable |
| cardamage-fvhwg/car-damage-f7gsv | 1,127 | KEEP-weak, filter | whole-car press photos: crime-scene tape, a crowd at a crash, "photo by Doug Springer (NWS)", "Central European News"; several undamaged cars labelled dent; this project is where panel_gap came from; ~10/20 usable |
| sidh-euwcy/car-scratch-dataset | 876 | KEEP, filter | real Indian scratch close-ups but noise aug on ~7/20; one side-by-side duplicate composite; one claw-scratch DECAL labelled scratch; ~13/20 usable |
| gp2-hknp7/car-damage-detection-mwbgo | 725 | KEEP | excellent: salvage-auction whole-car photos, consistent, no watermarks, no augmentation |
| sidh-euwcy/scratch-sjpy0 | 678 | KEEP, filter | real Indian photos, noise aug on ~4/20, one turntable stock shot and one posing mechanic with no damage; ~14/20 usable |
| agni-4nqn3/car-damage-segmentation-bk7wi | 588 | KEEP, filter | tiled alamy x2, shutterstock side-by-side composite, a checkered DECAL labelled scratch, firefighters at a wreck; ~12/20 usable |
| autodentify/car-damage-detection-ggmju | 453 | KEEP-weak, filter | tiny letterboxed whole-car crash photos, shutterstock bar, quikr.com classifieds watermark, an undamaged AMG GT labelled dent; ~11/20 |
| beena-txfr0/car-damage-detection-tuzuq | 328 | KEEP | best lamp_wheel source: real headlight-damage close-ups; one man sitting on a car, one baked-in yellow box; ~17/20 |
| haedars-workspace/scratch-segmentation-gsw1t | 170 | KEEP | real Indian photos, subtle scratches; the SAME turntable i20 stock shot as sidh/scratch-sjpy0 (cross-project dup) |
| car-damage-ymlgz/scratch-dent-car | 139 | KEEP, filter | good dent close-ups but shutterstock/alamy/gettyimages on 3, a side-by-side composite with red circles baked in |
| uniud-g3oa7/scratch-detection-hnk3o | 110 | KEEP | clean real Indian scratch photos, no watermarks; a few whole cars with no visible damage |
| (4 projects with 2-9 rows) | 19 | ignore | negligible |

## Totals over the 40,874 sourced keep rows
DROP (5 projects): 17,741 = 43%
KEEP clean (6 projects): changs 5,896 + d25qu 3,343 + joggx 2,774 + gp2 725 + beena 328 + haedars-seg 170 + uniud 110 = 13,346
KEEP with per-image filter (8 projects): 9,768
UNSOURCED, no provenance: 37,568 -- must be filtered per image

## Mechanical filters validated against these sheets
- grain score (mean |x - median3(x)| in the flattest quarter of blocks): >= 2.0 flags additive noise aug. curacel 3-7, clean projects 0.2-1.3. Does NOT catch HDR/tone-map aug (vehicle-detection-yjf3z scores ~0) -- that project is dropped by provenance.
- still needed: edge-bar watermark (shutterstock/dreamstime/getty bottom bar), tiled watermark (alamy), baked-in prediction boxes (changs, beena), side-by-side composites (2 identical halves), perceptual-hash cross-project dedup.
