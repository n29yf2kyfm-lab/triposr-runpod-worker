# Strip Bay Rigger — a Blender add-on

Takes car and van GLBs and makes them open up: doors, bonnet, tailgate,
sliding side doors, van barn doors and wheels. It does one car at a time with
sliders, or a whole folder unattended. Every car gets a report saying what it
found. A car it cannot rig safely is refused, with the reason given, rather
than faked.

## Install

1. Download `strip_bay_rigger.zip` from this folder.
2. In Blender (3.6 or newer; tested on 4.5 LTS), go to **Edit → Preferences → Add-ons → Install…**, pick the zip, then tick **Strip Bay Rigger**.
3. In the 3D view, press **N** and open the **Strip Bay** tab.

## Rig one car

**Rig a car GLB…** imports the file and rigs it. You then get one slider per
moving part: `door fl`, `door rr`, `bonnet`, `tailgate`, `wheel fl` and so on.
Drag a slider from 0 (shut) to 1 (open).

- **Rear doors: make them slide / swing** switches an MPV's rear side doors
  between sliding on a rail and swinging on hinges. Use it when the rigger
  guessed wrong. The shape alone cannot always tell (see below).
- **Shut everything** puts every part back.
- **Export rigged car…** writes the car shut, as a GLB with parts named
  `SB_<part>__<n>`, plus a `.report.json` next to it. The web trainer reads
  both files.

## A whole folder (1,000 cars)

In the panel, set **Input** and **Output** folders and press **Process folder**.
Or run it with no window, which is faster, and overnight is fine:

```
blender -b --factory-startup --python strip_bay_rigger/cli.py -- IN_DIR OUT_DIR [--blend] [--redo] [--limit N]
```

For every car, the output folder gets:

- `<name>.glb`: the rigged car, only when it succeeded
- `<name>.report.json`: every decision, or the reason it was refused
- `<name>.blend`: with `--blend`, the car with its sliders

When the batch finishes, it also writes `summary.csv`, one row per car:
status (`ok`, `partial`, `refused` or `error`), reason, doors, bonnet,
tailgate, sliding/barn doors, drive side and paint.

The batch **resumes**. A car that already has a report is skipped, so an
interrupted run carries on where it stopped. Use `--redo` to process
everything again. One broken file never stops the batch.

## What it can and cannot do

- **It needs the doors to be separate objects in the file.** A car whose
  doors are welded into one body mesh cannot be opened by renaming anything,
  so it is refused. Of the 1,044 catalogue cars, a survey found 128 whose
  parts are separately named at all (916 are one welded mesh), and not all of
  the 128 have separate doors. Expect most of a random folder to be refused
  until the shape-based door finder (step 3) exists.
- **It needs four road wheels.** Some game files carry one wheel that the
  game copies four times; those are refused and say so.
- **Names say WHAT a part is, never WHICH one.** Corners (front left, rear
  right…) come from where the part sits, because every file spells them
  differently.
- **Sliding doors.** A rear side door slides if any of these holds:
  - the file names it sliding;
  - it has the van signature: the rear door is taller than the front door
    and the vehicle is at least 2.6 wheel-diameters tall;
  - `overrides.json` says so.

  An MPV like the VW Sharan is the same shape as a Mazda 3 by every measure
  tried, so it needs the override. Nothing is judged in metres, because
  catalogue files are modelled at different scales.
- **Barn doors.** Doors across the back of a van swing 100° on their outer
  edges. A van with barn doors is not given a tailgate.

## overrides.json

Per-car rulings for what geometry cannot decide, keyed by file name without
`.glb`:

```json
{ "volkswagen-sharan-vw1-v1": {"door_rl": "slide", "door_rr": "slide"} }
```

The copy inside the add-on is read first. A copy in your input folder is
read second and wins.

## Test it after any change

```
blender -b --factory-startup --python selftest.py -- FOLDER_OF_GLBS
```

The self-test rigs every car, moves every slider and checks that each part
moves the right way and returns. It also covers a bug that shipped once:
every slider on a freshly rigged car was dead until the file was saved and
reopened. A saved `.blend` hides that bug, so the test never reloads.
