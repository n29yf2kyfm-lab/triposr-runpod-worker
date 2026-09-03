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

## The UNSOURCED pool (37,568 rows), read by class
First-ingestion projects (manifest minus reingest): 22 projects, 33,624 declared images.
Nine are industrial corrosion and five are concrete/pavement cracks -- but the class map
excluded those already (they are the 31,419 "not in the seven-class corpus" scraps), so
they are NOT in the keep set. Verified by eye: unsourced crack_glass is car glass
throughout, unsourced rust_paint is car paint throughout.
The remaining first-ingestion car projects include three 4,000-image copies of one
"vehicle-damage-detection" export with identical class lists, which is where the
unsourced dent/scratch noise-and-cutout frames come from.
| UNSOURCED crack_glass (2,888) | ~15/20 usable | one shutterstock bar, one "Helico" logo, one press photo, one tint-film application |
| UNSOURCED rust_paint (1,079) | ~17/20 usable | clean |
| UNSOURCED dent (10,885) | ~10/20 usable | noise aug + pasted cutout rectangles on 5, shutterstock bars on 2, one undamaged BMW |
Per-image provenance for these rows needs HF_TOKEN (private zips on Alamj/tier1-roboflow-yolo);
not available in this session. They are handled per image by audit_corpus.py instead.

## Council corrections (2026-09-03)
Four independent adversarial reviews of the above. What did not survive:
- **"watermarks ~15%"** -- an unweighted average over three per-class sheets in which panel_gap (0.11% of the population) supplied most of the hits. Size-weighted, the same 60 images give **7.2%**; two independent checks land at 4-7%. The OCR figure gets *worse*: only 14 of its 86 flags were direct reads, so tesseract's real recall is **under 1%**.
- **panel_gap "3 of 20 showed a gap"** -- sampled from the 78 images whose PRIMARY class is panel_gap (7.5% of the 1,036 carrying its boxes, and selected for multi-panel wrecks), then judged by image not box. A random draw of 20 BOXES: ~16 sit on a real seam or separation. **Fold reversed.**
- **datasetyolo DROP** -- measured flag rate 4.0%, cleaner than four kept projects; a 20-image sheet cannot reject "60% good" (P=0.95). Cost 38% of lamp_wheel. **Restored to per-image filtering.**
- **rfvnx DROP** -- 8/20 bad is the reading four kept projects got. **Restored.** Its images are also the entire keep set of asandes-workspace and skillfactory (re-exports of one dataset); rang-04bzz (9,617 rows) is greyscale scrap that never reached the keep set.
- **grain 3.0** -- 1:1 crops of KEPT images show the 1.5-3.0 band is noise augmentation throughout: ~12,200 augmented frames (21.8%) survived. **Now 1.5**, crack_glass exempt (crack webs score as grain).
- **edge_bar 0.60** -- "zero false positives on 60" had an 83% chance of passing at the true FP rate. Precision ~30% in 0.60-0.70, ~100% at >= 0.80. **Now 0.80.**
- **dedup** -- bucketing on the top 16 bits misses 84% of Hamming-6 pairs; 700 held-out images had a train twin. **Replaced with an exact 7x9-bit index**, and verify_index.py now produces the leak audit idx18 never had.
- **drive** -- never given a verdict; median grain 4.71, stock marks throughout. **DROP by provenance.**
- **sha->project join** was last-line-wins over a many-to-one file; 2,276 drops depended on line order. Now: all sources kept, drop if any is a drop project.
What stood: container (25/25 containers), curacel, yjf3z (for a better reason: 77% letterboxed, so edge_bar is blind to it), seam filter (19/20), and apply_clean_verdicts.py (all 174,050 boxes re-derived, 0 errors).
