# Template cars — a real car, reshaped, built offline

```
node pipeline/template/tools/decode.mjs MASTER_WEB.glb master.glb   # once per master
python3 pipeline/template/morph.py master.glb specs/fiesta.json fiesta.glb
node pipeline/template/tools/encode.mjs fiesta.glb fiesta.web.glb    # optional, for the browser
```

`morph.py` needs numpy and scipy and nothing else: no Blender, no GPU, no
network. About 4 seconds a car on a laptop CPU.

A **master** is a properly built car: separate doors, bonnet and tailgate,
clear glass, a full cabin. Every car made from it inherits all of that, so
the output always opens and always shows an interior through clear glass.

The warp, in the master's frame (y up, nose +z, the car's left +x):

* **along the car** — a smooth monotone map through the tail, both wheel
  arches and the nose: the target's overhangs and wheelbase, with each arch
  kept at the wheel's own scale so it stays round around the new wheel;
* **up the car** — below the arch tops everything scales with the wheel;
  above, each station is stretched so the roofline meets the target's, from
  its side photograph when given, otherwise its published height;
* **across** — the published width;
* **wheels, tyres, discs, calipers** — moved rigidly to the new axles and
  track and scaled to the new wheel; never squashed.

Normals and tangents go through the warp's Jacobian. Doors, bonnet and
tailgate hang from pivot nodes on their own hinge edges, and the GLB carries
animation clips (`door_FL_open` … `tailgate_open`, `doors_open`, `all_open`),
so any glTF viewer can open them with no code of its own.

## First proof (2026-10-15)

Master: 2021 Golf GTI by Ddiaz Design, CC BY-NC-SA 4.0 (the workshop's
car, with the bonnet and left mirror already cut as separate panels).
Targets: Ford Fiesta Mk7, Vauxhall Corsa F, VW Polo Mk6 from their Wikipedia
infobox figures (`specs/`). Identity check: the master's own measurements in
reproduce it (scale factors 0.9995–1.0004).

What it proves: a real-looking car, at the target's size and proportions,
with everything opening, clear glass and the cabin, from one command,
offline. What it does not do yet: the face, lamps, wheels and badges are
still the master's, so a "Fiesta" reads as a smaller Golf; the engine bay
is empty. Those are the next two stages (per-car face from photographs on a
neutral master; the engine family library).

Licence: outputs are derivatives of the master and carry its licence
(ShareAlike) and its credit.

## Second round (2026-10-16): the car's own face — a negative result, kept on purpose

Built and measured:

* `kit.py` — a plain five-spoke alloy, so a made car does not wear the GTI's wheels;
* the master's light signatures, GTI badges and red trim taken off; cabin neutral;
* `tools/export_engine_bay.mjs` — the petrol bay, gearbox, exhaust and suspension
  exported from the eHybrid workshop scene (built from the owner's photos), merged by
  `gltf.append` and warped with the car (`engine_pack`). The bonnet now opens on an engine;
* `photoproj.py` — fits a camera to a street photograph from the car's outline and paints
  the photograph onto every outside triangle that faces it (mirrored to the far side).

The camera fit WORKS, with a positive control: on a synthetic render it recovers the
camera (azimuth -40.0 vs -40, elevation 7.6 vs 8, distance 6.47 vs 6.5 m); on a real
Commons photo of a Golf Mk8 it lands at azimuth 47-49, elevation 10, roll 1 — an
eye-level street shot. It needed three fixes, each found by looking at the overlay:
glass belongs in the outline (a cut-out includes the windows); the bottom 30% of a
cut-out is shadow, not car, so the score uses the upper 70% and the top contour; and
the outline alone cannot tell an eye-level 50-degree shot from a high side-on one
(Polo: cost 0.165 vs 0.167), so there is a soft preference for eye level.

The PAINTING does not work on a template, and no tuning will make it: a Polo photograph
painted onto a Golf-shaped body puts the Polo's windows and wheels on the Golf's doors
(`polo2` render, 2026-10-16). Photo projection needs the photographed car's own shape.
Keep `photoproj.py` for that case (texturing or checking a real model of the car);
do not use it to give a template a face.
