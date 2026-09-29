# Rig machine: send a car GLB, get it back opening

One command takes any car GLB, finds its doors, bonnet and tailgate, and hangs
each one on a measured hinge. It then renders the car shut and open, and writes
a page where you can open the parts yourself in the browser.

```
python3 platform/rigmachine/run.py CAR.glb OUT_DIR                  # a local file
python3 platform/rigmachine/run.py https://…/car.glb OUT_DIR        # or a link
        [--size=1280x800] [--samples=24]
```

Needs Blender 4.5 on PATH (or `BLENDER_BIN`) and Pillow. `gltf-transform` is
optional; it adds the compressed copy for the browser.

## What comes back

| file | what it is |
|---|---|
| `<car>.glb` | the rigged car, shut. Parts are named `SB_<part>__<n>` (door_fl, door_rr, panel_bonnet, tailgate, wheel_fl …) |
| `<car>.web.glb` | the same car, meshopt-compressed for the browser (RS6: 9.1 MB → 3.0 MB). Names survive |
| `<car>.report.json` | the rigger's report: hinge points, sliding and barn doors, what it could not find |
| `<car>_<state>_<view>.png` | one still per state per camera |
| `sheet.jpg` | every still on one captioned image |
| `viewer.html` | drag to turn; tap a part, or a button, to open it. Serve the folder over http |
| `result.json` | status, the parts that open, timings, and why, if it refused |

States: **shut**, **doors** (every side door), **ends** (bonnet and tailgate),
**open** (everything). A state is left out when the car has none of its parts.
Cameras: front-left and rear-right three-quarter views, one framing for all
states so a sheet reads as the same car opening.

Exit code 0 when the car was rigged, 2 when it was refused, 1 on an error.

## From a vehicle: doors open, glass cleared, engine in the bay

```
python3 platform/rigmachine/car.py OUT_DIR --make=Volkswagen --model=Sharan --year=2014 \
        --fuel=DIESEL --cc=1968 --colour=RED
```

The input is what the app **already decodes from a registration**. The
registration itself is never an input, never logged and never stored; one sent
by mistake is dropped. DVLA's own lookup gives make, year, fuel, engine size and
colour but **not the model**. The model comes from the app's existing decode.

1. **Match.** `resolve.mjs` runs the live resolver (`platform/resolver/index.ts`,
   unchanged) under Node. It picks the catalogue car, the colour variant and
   the honesty disclosure ("representative", "generation-correct" …).
2. **Engine choice.** An electric drive unit for `ELECTRICITY`, a V8 from 3.5 litres,
   otherwise an inline four. It sits lengthways for BMW, Mercedes, Jaguar,
   Porsche, most Audis and so on, and across the car otherwise. It is always
   labelled as a stand-in, not the car's own engine.
3. **Showcase render** (`run.py --showcase`):
   - every door, the bonnet and the tailgate open;
   - the windows cleared, so the cabin shows. Only glass-named materials on the
     glazing and doors are cleared, and lamp lenses keep their colour;
   - the engine fitted in the bay, sized from the car's own wheels and bonnet;
   - stills: front-left, rear-right, an engine-bay close-up and a cabin view,
     plus two shut stills.
   - The viewer page opens with everything open, names the car and shows the
     disclosure.
4. **If the car already has a modelled engine bay**, the car keeps its own engine
   and ours is not added. A bay counts as modelled when it has a part named
   engine, or more than 1,500 vertices under the bonnet. Calibrated on two cars
   only: the RS6 (its own V8, 2,847 vertices, kept) and the Sharan (empty shell,
   729 vertices, ours added). Treat that threshold as provisional.

Engine models: `parts/` (meshopt; credits in `parts/CREDITS.json`, all CC-BY),
decoded per job with `gltf-transform` because Blender cannot read meshopt.

| vehicle in | catalogue car | result |
|---|---|---|
| 2021 Audi RS6, petrol, 3996 cc | `audi-rs6-v1` | all open, own V8 kept, glass cleared |
| 2014 VW Sharan, diesel, 1968 cc, red | `volkswagen-sharan-vw1-v1__red` | doors (rear sliding) and bonnet open, inline four fitted, glass cleared |
| 2019 Ford Fiesta, petrol, 998 cc | `ford-fiesta-2009-w12-v1` (representative) | **refused**: the file names no wheels |

## On demand

`handler.py` is the same thing as a RunPod serverless job:

```json
{"input": {"vehicle": {"make": "Volkswagen", "model": "Sharan", "year": 2014, "fuel": "DIESEL", "cc": 1968, "colour": "RED"}}}
{"input": {"glb_url": "https://…/car.glb", "showcase": true, "engine": "i4", "mount": "trans"}}
```

It returns `result.json` with a public link to every file, uploaded to
`car-meshes/rigmachine/<car>/<run id>/`, and deletes its local copy. It needs
`SB_KEY` on the worker to upload; without it, it returns the result and says the
files were not uploaded. **It is not deployed.** Deploying it means a new endpoint
(or a new image), and that costs money per car, so it is the owner's call. It
must not be hot-pinned onto the shared render worker while a wave is running.

## Measured (2026-09-29, CPU Cycles with the denoiser, 960×600, 16 samples)

| car | result | time |
|---|---|---|
| Audi RS6 Avant (`audi-rs6-v1`) | 4 doors, bonnet, tailgate | rig 16 s, 8 stills 78 s |
| VW Sharan (`volkswagen-sharan-vw1-v1`) | 4 doors (rear ones **slide**), bonnet. No tailgate found: `partial` | rig 11 s, 8 stills 139 s |
| BMW 5 Series 1995, Suzuki Swace, Nissan GT-R 2013 (random catalogue picks) | refused: no part names to find the nose from, or no wheels named | 3–12 s each |

## What it cannot do

The rigger opens parts that are **separate pieces in the file**. A car whose
doors are welded into one body mesh has nothing to open, and it is refused with
the reason rather than faked. Most of our own catalogue is like that: a survey
found 128 of 1,044 cars with named parts, and all three random picks above were
refused. Cars bought or modelled for configurators (separate doors, named
parts) are what it is built for. Splitting a welded shell into doors is a
separate, much harder job (see `trainer/blender_addon/README.md`, step 3).

The rigger itself is `platform/trainer/blender_addon/strip_bay_rigger`, used
unchanged. Its `selftest.py` must pass after any change to it.
