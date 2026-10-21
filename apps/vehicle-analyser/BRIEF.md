# Vehicle Analyser: build brief

A teaching app for trainee mechanics. Pick a car, van or motorbike, open
every door and lid, take every panel off, see the engine run and the
suspension work, follow real inspection procedures, then test yourself.
Phone first, Apple-grade finish, lots of considered motion.

Everything 3D comes from the ExpertCarCheck GLB machine (this repository).
The app never builds models itself; it loads the pack below.

## The pack

Base URL (raw files on GitHub, branch `claude/lovable-connection-ki7jch`):

    https://raw.githubusercontent.com/n29yf2kyfm-lab/triposr-runpod-worker/claude/lovable-connection-ki7jch/apps/vehicle-analyser/

| File | What it is |
|---|---|
| `fleet/index.json` | The vehicles: id, title, kind (`car`, `van`, `motorbike`), body, hero image, part count, what opens, credit line |
| `fleet/<id>.glb` | The vehicle. meshopt-compressed glTF: load with `GLTFLoader` + `MeshoptDecoder` (drei's `useGLTF` does this by default) |
| `fleet/<id>.json` | Everything about it (schema `expertcarcheck.vehicle/1`, below) |
| `fleet/<id>.webp` | A studio picture with a transparent background, for the garage |
| `kit/running-engine.js` | A running, cut-open inline four (ES module) |
| `kit/suspension-corner.js` | A working MacPherson-strut front corner (ES module) |

Copy every file into the project's own assets once (the way
`engine_pack.glb` was brought in). Do not load from GitHub at run time.

Vehicles: Volkswagen Golf 2017, Nissan Qashqai 2018, BMW 3 Series Touring
2014, Land Rover Defender Works V8 Trophy 2021, Porsche 911, Renault Master
(van), and a heavy cruiser motorbike modelled in code. GLBs are 0.9 to 19 MB.

### The vehicle file

Frame for every position: metres, +Y up, the nose towards +Z, the
vehicle's left towards +X, the ground at y = 0.

- `title`, `kind`, `body`, `summary`, `hero`, `glb`, `bytes`, `box` (the whole vehicle's min/max).
- `parts[]`: one entry per part a learner can pick.
  - `id`, `label`, `section` (Body and openings, Wheels, Engine bay, Under the car), `system`
    (Body, Wheels, Engine, Cooling, Electrical, Transmission, Air and fuel, Exhaust, Suspension, Steering, Brakes, Chassis).
  - `node`: the glTF node name. Many engine-bay parts are several nodes sharing one name; the part is all of them.
  - `node_loaded`: the name three.js gives it after loading (`bay:blk` becomes `bayblk`; repeats get `_1`, `_2`).
    Safest match: `gltf.parser.associations.get(object).nodes` gives the node index, and
    `gltf.parser.json.nodes[index].name` the original name, so compare with `node` exactly.
  - `opens`: true if it has a hinge. `removable`: true for everything but the body shell.
  - `box`: where it sits (min/max), for framing the camera and placing labels.
  - `remove`: `{dir, dist}`, the way it comes off: doors out sideways, the bonnet up and forward,
    a tailgate up and back, a van's barn doors back and out, wheels off the hub, engine parts up out of the bay.
  - `representative`: true for the engine-bay parts (see the rules below).
  - Motorbike parts also have `moves_with` (`steer`, `wheel_f`, `wheel_r`, `stand` or `body`).
- `hinges[]`: `{part, node, node_loaded, pivot, axis, open_deg, clip}`. To open a part, rotate the
  `<part>_hinge` node about its local `axis` (also in the node's `userData.axis`) by `open_deg` degrees.
  Drive it with a spring, not a linear tween. `clip` names the baked open animation if you would rather play that.
- `clips[]`: baked animations (`door_fl_open`, `all_open` ...; the bike has `wheels_spin`, `steer_left`,
  `steer_right`, `stand_down`).
- `procedures[]`: `{title, steps[{text, view, parts, open}]}`. Real inspection routines written by the machine
  (walk-round, under the bonnet, doors and cabin, boot and underside; the bike has T-CLOCS, brakes, engine top end).
  `open` lists what must be open for the step; `parts` what to highlight; `view` is a hint
  (`front`, `nearside`, `wheel:fl`, `door:fl`, `bay`, `boot`, `under`, `part`).
- `engine`: `{representative, at, lid, note, real_layout}`. `at` is `front` or `rear` (the 911), `lid` the part over it.
- `paint`: `{hex, finish, materials, wheel_materials, caliper_materials}`: material names for a recolour.
- `credit`: `{line, title, author, licence, url}`.

## Rules that must hold

1. **The engine bay is a teaching engine.** Every car carries the machine's engine pack: one representative
   transverse four-cylinder with its gearbox, cooling, front suspension and driveshafts, the same in each car.
   Wherever an engine-bay part is shown, show a small "Teaching engine" chip, and in the vehicle's info show
   `engine.note` and `engine.real_layout`. Never call it the vehicle's own engine.
2. **Credit the model.** Show `credit.line` in each vehicle's info sheet (the models are CC BY).
3. **No invented facts.** No power, torque, engine codes or prices that are not in the files.
4. Respect `prefers-reduced-motion`: keep the springs, drop the long camera flights and auto-orbit.

## Screens

### Garage (home)
- Large title, a segmented control: All, Cars, Vans, Motorbikes.
- A card per vehicle: the hero WebP floating over a soft hazard-yellow glow, with a slow parallax tilt
  (pointer on desktop, device tilt on phones where allowed), title, body, "68 parts", "6 open".
- Load no GLB here. Tap a card: the hero image flies into place as the 3D view loads behind it
  (shared-element transition), with a progress ring until the model is ready.

### Vehicle (full-screen 3D)
Top bar: back, title, info (summary, `real_layout`, credit). A glass bottom sheet, draggable between
three heights, with tabs:

- **Explore**: a button for each hinged part and "Open all". Doors swing on springs with a slight overshoot.
  Bike: steer left and right, side stand, spin the wheels (its clips).
- **Strip**: the parts by section. Tap a part: the others fade, it glows, the camera flies to it, its label pins to it.
  "Remove" runs a short unbolt (four bolt heads turn and lift), then the part lifts along `remove.dir`, arcs out by
  `remove.dist` and settles on the workshop floor beside the vehicle with its own shadow. "Refit" reverses it.
  "Strip all panels" removes the doors, lids and wheels one after another; a counter shows parts off.
- **Systems**: chips for each `system`. Tap one: its parts stay solid, the rest go to a faint X-ray,
  and an explode slider spreads that system's parts out from its centre.
- **Workshop**:
  - *Ramp*: the vehicle rises on a two-post lift; the wheels can come off.
  - *See the engine run*: `kit/running-engine.js` on its own stage. Play and pause, speed (show `rpm()`),
    a stroke chip per cylinder from `strokes()` in its colour, the firing order 1-3-4-2, systems
    (`setSystem`: air, fuel, spark, exhaust, cooling, oil), teardown (`setStrip`), and tap-a-part text from `parts`.
    Set `renderer.localClippingEnabled = true` for its cut-away.
  - *Test the suspension*: `kit/suspension-corner.js`. A "Drive over a bump" button (`setMode('bump')`),
    a healthy / worn damper switch (`setDamping(0.3)` / `setDamping(0.05)`), a steering slider (`setSteer`),
    a brake button (`setBrake`, `setSpeed`), teardown (`setExplode`), tap a part for its text (`parts`, `highlight`, `anchor`),
    and a live readout from `readout()` with a moving trace of wheel travel. The worn damper visibly keeps bouncing.
- **Learn**: the vehicle's `procedures`. Each step flies the camera, opens what `open` lists, highlights `parts`,
  shows the text; progress dots; mark done. Then a quiz built from the files: "Which part is glowing?",
  "Which system is this part in?", and questions from the engine and suspension texts. Score with a calm animation.

## Look and motion

- The project's palette: hazard yellow `#F2C200` on near-black `#0E0F11`, white text, one accent only.
  Its modern tech font for display, the system UI stack for text.
- Glass sheets (backdrop blur), generous radius, soft shadows; one hero idea per screen.
- Springs for everything that moves (Framer Motion's `motion` for UI; critically damped springs or `maath/easing`
  for 3D). Staggered entrances. Haptic tick (`navigator.vibrate(8)`) on remove and refit where supported.
- 60 frames a second on a mid phone: `frameloop="demand"` and `invalidate()` when nothing moves, `dpr` capped at 2,
  shadows only from one light, dispose a vehicle's GLB when leaving it.

## Done means

- All seven vehicles load. Every hinge opens and closes. Every removable part comes off and goes back,
  and the counter returns to zero.
- The "Teaching engine" chip, the real layout and the credit line show where they should.
- The running engine shows four pistons moving, the stroke chips cycling and firing in the order 1-3-4-2.
- The suspension bump test settles with the healthy damper and keeps bouncing with the worn one; the readout moves.
- Phone (390 x 844) and desktop (1440 x 900) both work, with no sideways scrolling.
- No GLB is downloaded on the Garage screen.
