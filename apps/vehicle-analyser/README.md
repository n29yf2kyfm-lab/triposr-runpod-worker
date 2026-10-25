# Vehicle Analyser pack

What the Vehicle Analyser app (Lovable project "Clone Companion") loads:
vehicles built by the ExpertCarCheck GLB machine, each as a GLB plus a
vehicle file, and two working mechanisms to teach with. `BRIEF.md` is the
app's build brief.

| Path | |
|---|---|
| `fleet.spec.json` | What is in the fleet: each vehicle as the request the machine is asked (or the bike), with its kind, body, summary and the real layout to show beside the teaching engine |
| `fleet/` | The built pack: `<id>.json`, `<id>.webp`, `index.json`. The `<id>.glb` files are built beside them but stay out of git (the repository ignores car GLBs on purpose); the app gets them as uploads |
| `kit/running-engine.js` | The car page's running inline four as an ES module |
| `kit/suspension-corner.js` | A MacPherson-strut front corner, solved live: bump, droop, steer, brake, teardown |

## Rebuild the pack

From the repository root, with the machine set up (`GLBMACHINE_HOME` if used):

    python3 pipeline/realcar/app_pack.py apps/vehicle-analyser/fleet apps/vehicle-analyser/fleet.spec.json
    node pipeline/realcar/app_hero.mjs apps/vehicle-analyser/fleet
    python3 pipeline/realcar/app_pack.py --heroes apps/vehicle-analyser/fleet

The first builds every vehicle through `glbmachine.py car` (seconds each for
cars rigged before) and the bike with `bikes/cruiser.mjs --parts`, and
writes the files. Rebuilt from the same spec, the vehicle files are the same
and the GLBs byte-identical. The second renders a studio picture of each
(headless Chromium); the third crops them to WebP.

To add a vehicle, add a line to `fleet.spec.json` and rebuild. Check its
picture before shipping it: in this fleet's first pass the picture showed a
Focus with its radiator through the bumper and a "Ford Ranger" source file
that is really a Suzuki Vitara, neither of which the build log caught.

## What the files say, and do not

- Every car's engine bay is the machine's engine pack, one representative
  teaching engine, the same in each car. The vehicle file says so
  (`engine.representative`) and gives the car's real layout beside it.
- The pack's sided parts (struts, driveshafts, outputs) are labelled by where
  they actually sit. The engine pack's own names have its driveshaft-output
  flanges the other way round, and in the 911 the pack is turned round at the
  back, so its "front left" strut is the rear right one.
- A van's sliding side doors are hinges of `"type": "slide"`: they move out
  and back along the body (`slide.out_x`, `slide.back_z`), they do not turn.
  The Vito's model has its sliding door on the right only.
- Each car's credit line (CC BY) is in its file and must be shown.
