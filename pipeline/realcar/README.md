# Real-car finisher

Takes a real catalogue car that the rig machine has cut, and finishes it to
the owner's standard: every door, the bonnet and the tailgate open (glTF
animation clips), the glass is clear, the cabin is kept, and there is an
engine bay and an exhaust under it. Pure Python (numpy, scipy): no Blender,
no GPU, no network. About 2 s per car.

```
python3 platform/rigmachine/run.py SRC.glb OUT_DIR          # cut: doors, wheels, frame (Blender, offline)
python3 pipeline/realcar/finish.py OUT_DIR/SRC.glb SPEC.json CAR.glb
node pipeline/template/tools/encode.mjs CAR.glb CAR_web.glb  # meshopt web copy
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
