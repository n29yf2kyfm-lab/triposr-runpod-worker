# The GLB machine

Ask for a car in plain words and get back an interactive GLB: every door, the
bonnet and the tailgate open (glTF animation clips), the glass is clear, the
model's cabin is kept, and a generic engine bay and exhaust sit under it,
painted the colour asked for. Python (numpy, scipy, Pillow) and Node; **no
Blender**, no GPU. ExpertCarCheck's own software: see `LICENSE` and, for every
component and the car models' licences, `THIRD_PARTY.md`.

## Install and run

```
pip install -r pipeline/realcar/requirements.txt
python3 pipeline/realcar/glbmachine.py setup          # npm install + work folder (~/.glbmachine)
python3 pipeline/realcar/glbmachine.py make "Nissan Micra 2004 red"
python3 pipeline/realcar/glbmachine.py make "Ford Fiesta 2012 blue" --no-sheet
python3 pipeline/realcar/glbmachine.py batch --top 20 --workers 3
python3 pipeline/realcar/glbmachine.py serve --port 8080
```

Or as one image (Python, Node 22, Chromium):

```
docker build -f pipeline/realcar/Dockerfile -t glbmachine .
docker run -p 8080:8080 -v glbdata:/data -e GLBMACHINE_KEYS=key1,key2 glbmachine
docker run --rm -v glbdata:/data glbmachine make "Toyota Yaris 2003 silver"
```

The web API (`serve`): `POST /v1/cars {"request": "...", "sheet": false}`
answers with an id; `GET /v1/cars/ID` gives the status and the report;
`GET /v1/cars/ID/car.glb` and `/sheet.jpg` give the files. With
`GLBMACHINE_KEYS` set, each call needs `Authorization: Bearer KEY`, which is
where licence keys plug in.

## GLB Studio: fix a car by hand

When the machine gets a part wrong (a welded bonnet it could not find, a
boot lid cut wrong, stray sheets in the bay), open the car in the Studio:

```
python3 pipeline/realcar/glbmachine.py serve --port 8080   # then http://localhost:8080/studio/
```

1. Pick the car from the list (every car built here that kept its rig).
2. Click a panel: the selection grows from that face to the nearest crease or
   shut line (*Panel*), takes a whole loose piece (*Piece*), or everything
   facing you in a box you drag (*Box*). Shift adds, Alt takes away.
3. Say what it is: Bonnet (B), Tailgate (T), a door (1-4), Body (0) or
   Remove (Del). Ctrl-Z undoes. A coloured line shows where each part will
   hinge; change the edge (a rear-hinged door, a side-hinged tailgate) or the
   angle in the parts list.
4. Build car: the server applies the edits to the rigger's own parts
   (`edits.py`, kept apart so they can be changed or undone at any time) and
   finishes the car again (`finish.py` takes hand-set parts as they are).
   About 5 s. The Result view opens each part.

Tested 2026-10-16: the Qashqai J11 and the Fiat 500e, both "bonnet missing",
fixed with one click and one key each; both now build with everything
opening. "Back to automatic" throws the edits away. The edits are saved with
the car, so later rebuilds (and batch runs) keep them.

## Ask for a car

The steps, in order:
1. The approved catalogue is searched for that model in a generation on
   sale that year.
2. If it isn't there, Sketchfab is searched (`source.py`). The best match is
   downloaded with the `SKETCHFAB_TOKEN` environment variable.
3. The file is decoded (`decode.mjs`), rigged (`rig.py`), finished in the
   colour asked for (`finish.py`), validated, compressed and, unless
   `--no-sheet`, drawn on a four-view check sheet.

Timed on catalogue cars (2026-10-16, one at a time):

| Step | Fiesta 2009 | Micra 2004 | Yaris 2001 (in Docker) |
| --- | --- | --- | --- |
| download | 1.0 s | 0.5 s | 0.9 s |
| decode | 0.3 s | 0.3 s | 0.6 s |
| rig | 1.1 s | 1.9 s | 2.6 s |
| finish | 0.5 s | 0.9 s | 1.5 s |
| validator and web copy | 1.3 s | 1.6 s | 2.4 s |
| **car ready** | **about 5 s** | **about 6 s** | **about 9 s** |
| check sheet (optional) | | 20 s | 29 s |

The largest catalogue cars (Juke, Clio) rig in 13-21 s. The top-20 UK
sellers, three at a time: 7 min 16 s in all.

**The rigger** (`rig.py`) is the old Blender rig step ported rule for rule
to numpy, then checked against Blender on the 21 UK top-seller catalogue
cars: the same parts open on 20, with hinges within 5 mm. The one difference
(the catalogue's mislabelled "Honda Jazz") is better in `rig.py`. Blender is
GPL, and code that drives it would have made the whole product GPL; that is
why it was replaced.

**Size.** About half the catalogue's models are not at metre scale. The
rigger sizes those from a guessed wheel height, which can be 15% out.
`wheelbase.py` looks the car up instead:
1. It reads the model's English Wikipedia page and every generation page it
   links to (page text only, since the search API is rate-limited on shared
   addresses).
2. It takes the infobox on sale in the model's year. When two generations
   overlap that year, it takes the one whose wheelbase-to-length proportion
   matches the 3D model.
3. The answer is used only if it leaves the wheels a real car's size
   (0.50–0.85 m). Otherwise the car is flagged.

Answers are cached in `wheelbase_cache.json`, and hand-checked figures in
`batch.WHEELBASE` win. Tested on seven cars against hand-read infoboxes:
Micra K12, Fiesta Mk6, Golf Mk8, Qashqai J11, Polo Mk6, Focus Mk4 and
Corsa D (through Vauxhall to Opel). All matched, and the A-Class W176/W177
overlap was settled by proportion.

## The steps by hand

```
node pipeline/realcar/decode.mjs SRC.glb PLAIN.glb               # Draco / meshopt -> plain
python3 pipeline/realcar/rig.py PLAIN.glb OUT_DIR                 # cut: doors, wheels, frame
python3 pipeline/realcar/finish.py OUT_DIR/src.glb SPEC.json CAR.glb
node pipeline/realcar/encode.mjs CAR.glb CAR_web.glb              # meshopt web copy
```

`SPEC.json` (see `specs/polo_mk6.json`): `name`, `wheelbase` (mm, the car
is rescaled to it), `engine_pack` (the workshop petrol bay, exported by
`pipeline/template/tools/export_engine_bay.mjs`), and `credit` (written to
`asset.copyright`).

## What it does

| Step | How |
| --- | --- |
| Bonnet | A modelled car's panels are separate pieces. The bonnet is the largest paint piece lying flat over the front axle, plus the badges on it. Hinged at its rear edge, opens 55°. |
| Bonnet, welded | When the bonnet is welded into one shell with the wings and has no shut line in the mesh, it is cut. The region is the shell's top over the front: ahead of the windscreen base plus the cowl, facing up, and above the wheels. The line is that region's half-width along the car, median- then Gaussian-smoothed, and straight across at the cowl. Triangles that cross the line are split along it, with every attribute interpolated, so the edge is a clean curve rather than a staircase. |
| Tailgate | The rear window, the paint panel directly under it, and every piece inside the box they span that sits on the car's rear skin (within 12 cm of the rearmost surface). That takes the tail-lamp inners, the badge, the wiper and the spoiler, and leaves the boot trim and the corner lamps on the body. Hinged at its top edge, opens 75°. |
| Tailgate, from the rig | If no rear window is found (some models make it from dark plastic, not glass), the rig machine's tailgate stands. Like a door, it then takes every piece in its box that touches it: the rear window and the inner lamps. |
| Doors | The rig machine's door cut, plus every small piece inside a door's box and above the wheels that touches the door (within 1 cm of its surface): window frames, belt mouldings and mirrors. Seats and brakes in the same box don't touch the door, so they stay on the body. Hinged at the front edge, opens 65°. |
| Glass | Every blended, colourless material becomes clear (light tint, alpha 0.14, glossy). Lamp lenses keep their colour. |
| Engine | The workshop's petrol bay goes in. The bay, engine, gearbox and front suspension are scaled to this car's track about the front axle. The rear suspension and fuel tank are placed about the rear axle. The exhaust is stretched from the front pipe back to 10 cm inside the rear bumper. Pieces reaching below the ground (workshop leftovers) are dropped. |
| Frame | The car is centred on its wheelbase, with x = 0 down the middle and the ground at y = 0. Nose is +z and the car's left is +x, the same frame as the template cars. |
| Clips | `door_fl_open` … `door_rr_open`, `bonnet_open`, `tailgate_open`, `doors_open`, `all_open`. |

## First proof: Volkswagen Polo Mk6 GTI (2026-10-16)

Source: catalogue `volkswagen-polo-2023-v1`, "2023 Volkswagen Polo GTI" by
tonielpro520, CC BY 4.0 (commercial use allowed, credit required).

- The rig machine alone gave four doors and a 42-triangle strip it took for
  the bonnet. It found no tailgate, and it left the window frames floating
  when the doors opened.
- After the finisher, everything opens:
  - bonnet: one 1.4 m² panel, 26 pieces;
  - tailgate: 245 pieces;
  - 42–46 trim pieces per door.
- Glass: the windows and headlamp lenses are cleared.
- Engine: the bay is scaled ×0.963 and the exhaust stretched ×0.960.
- Size: rescaled ×0.970 to the 2564 mm wheelbase. The output is 27.5 MB,
  and the meshopt web copy is 9.0 MB.
- glTF validator: 0 errors. The 49 warnings are the engine pack's
  normal-mapped parts, which have no tangents.

![Polo Mk6 finished](polo_mk6_sheet.jpg)

Known limits:
- The engine is the workshop's petrol bay, not each car's own engine.
- The inside face of the tailgate is the outer panel's back (no trim card).
- The model is 4.13 m long on the published wheelbase. This source runs about
  1% long.

## Second proof: Nissan Qashqai Mk2 J11 (2026-10-16)

Source: catalogue `nissan-qashqai-2018-v1`, "2018 Nissan Qashqai" by
Ddiaz Design, CC BY-NC-SA 4.0. The catalogue had this as CC-BY; Sketchfab
says NC-SA, so it is free-app use only.

- The rig machine alone gave four doors and the tailgate panel. It found no
  bonnet (the body is one welded shell) and left the rear window (dark
  plastic) on the body.
- After the finisher, everything opens:
  - bonnet: cut along a smoothed shut line, 1.16 m², 212 triangles split;
  - tailgate: took 34 touching pieces, including the rear window and the
    inner lamps.
- Glass: the windows and lamp lenses are cleared.
- Size: rescaled ×1.008 to the 2646 mm wheelbase. The meshopt web copy is
  7.5 MB.
- glTF validator: 0 errors.
- Polo re-run with this code: same bonnet, doors and trims. The tailgate
  takes 11 more small touching pieces (checked by eye).

![Qashqai finished](qashqai_j11_sheet.jpg)
