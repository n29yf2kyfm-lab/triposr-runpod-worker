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

## On demand

`handler.py` is the same thing as a RunPod serverless job:

```json
{"input": {"glb_url": "https://…/car.glb", "size": "1280x800", "samples": 24}}
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
