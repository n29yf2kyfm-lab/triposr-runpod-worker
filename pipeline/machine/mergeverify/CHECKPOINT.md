# CHECKPOINT — INDEPENDENT VERIFIER (merged Golf Mk8)

Working dir: `.../scratchpad/mergeverify/` · branch `claude/lovable-connection-ki7jch`
Tools commit to `pipeline/machine/mergeverify/`. Evidence to
`car-meshes/staging/mergeverify/`.

## STATE: harness built and CALIBRATED on the six source cars. Merged car NOT YET PUBLISHED.
`car-meshes/staging/merged/` was EMPTY at last check. Nothing has been measured on a
merged car; every number below is a BASELINE on a gate's own file.

## Files fetched and sha256-VERIFIED against their MANIFESTs (7/7 byte-exact)
gate78 car_rebound 5380761c · merge car_merged 09897d20 · skin car_deskin 2029b2ec ·
glass car_glass_v4 1a20abdd · cabin car_cabin 796c7d47 · v7 GOLF_V7_FRONT_GATE 3f681443 ·
rear rear2_v4 4444e379

## Frame, derived not assumed
length on X (4.2825 m), up on Y, side on Z. **Nose at −X — CONFIRMED BY RENDER**
(`rend/orient_az270.png`: nose on image-left; camera at Blender −Y ⇒ image-left = −X).
MY az convention is NOT the gate rigs': my az 270 is a SIDE view.

## Rig calibration (meta/LIGHT_CALIB.txt)
CYCLES, use_denoising=False, Standard transform, ORTHO. world 0.22 → backdrop sRGB
129.5. LIGHT_GAIN 25 adopted: 0.38% of car px clipped (gain 60 → 5.83%, 120 → 22.2%).

## REPRODUCED EXACTLY on the gate's own file
| gate | claim | my measurement |
|---|---|---|
| merge | 4 tyre bottoms 0.000 mm | 0.000/0.000/0.000/0.000; base FL 183.178 FR 189.636 RL 0.316 RR 14.735 |
| glass | Glass_Windscreen 0.9894 m² | 0.9894 (base 0.1622); glazing total 3.1742→3.3956 |
| v7 | 20 components | 20/20 present, all real geometry |
| v7 | 0.0% centroid coincidence | 0/36,692 faces at 1e-6 m (min d 0.17 mm) |
| v7 | symmetry 5.9e-05 mm | 5.922e-05 mm worst pair (about the kit datum z=+27.30 mm) |
| v7 | badge/plate centreline 0.0000 | ≤7e-6 mm from that datum |
| rear | hidden melt hatch 1.92% | 1.89% at matched ray grid |
| rear | hidden melt bumper 3.61% | 3.58% at matched ray grid |
| all | validator 0 errors | 0 errors / 0 warnings on all 7 (official Khronos via node) |

## NOT reproduced / qualified — carry these forward
1. **rear2_v4.glb FAILS the must-not-break material set.** `extensionsUsed` ABSENT
   (no transmission/IOR/clearcoat); `carpaint` = [1,1,1,1] metallic 1 rough 1 (glTF
   DEFAULTS, the recorded flat-shell trap); `Rim_Alloy` the same; Tyre_Rubber 0.0484
   not 0.0288. Its GEOMETRY win is real; its material table must NOT be merged.
2. **rear2_v4 is a different lineage**: node names carpaint/interior/glass, 1,046,660
   faces. Geometric provenance vs car_rebound: 12 nodes 100% coincident (melt),
   14 nodes 0% (new-built, 61,404 faces). car_rebound IS its geometric base.
3. **Front and rear kits use DIFFERENT lateral datums.** v7 front kit z=+27.30 mm
   (= front-axle centre +30.28); rear v2 kit z≈−66…−82 mm (= rear-axle centre −69.06);
   Body_Shell best mirror plane ≤−25 mm. Spread ≈105 mm.
4. **rear tail lamps are NOT L/R symmetric** (max 82 mm about their own pair-mid)
   where v7's front lamps are 3e-05 mm.
5. **Waviness absolute numbers do not reproduce** (definition differs). Like-for-like
   at 20 mm radius: Hatch 0.589 vs melt 2.872; Bumper_Rear 0.202 vs melt 1.201 — the
   direction and ratio hold at every radius 20–80 mm.
6. **Hidden melt is ray-placement sensitive (±2 pp).** 0.87–3.79% for the same panel.
7. **glass fix and v7 front kit do NOT carry the merge grounding** (their tyres are
   still 183/189 mm up). Merge must transport them.

## CONTROLS PROVEN TO FIRE (nc/)
NC1 tyre +5.000 mm → reported 5.0000 (slope 1.000) · NC2 glazing geometry to 2.5% →
windscreen 0.9894→0.0238 m² · NC3 KHR stripped → detected · NC4 NORMALs dropped →
30/30 · NC6 3.000 mm shift → 3.000030 mm · NC8 flat paint → detected ·
NC7 8% of Body_Shell deleted → hole test (running).
**The real `glass_probe` returns clear/proven on NC2, NC3 AND NC5** — pairing with a
glass-AREA figure is mandatory and is now built in.

## NEXT
- finish hole-test self-test, through-glass, respray control on car_merged
- dark-speck / clay-floor measure (skin gate win)
- when the merged car appears: run the whole table against it
