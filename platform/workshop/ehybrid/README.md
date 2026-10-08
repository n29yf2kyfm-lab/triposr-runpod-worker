# Golf Mk8 eHybrid workshop

Published as a private artifact: https://claude.ai/artifact/17U3LhXH5hBdz8G6qtkFmJ

Built on the Golf Workshop artifact (Mwv7ahiqrWymYQhvheLkg9). The publish copies these
files from it server side, so they are not duplicated here: `fleet.js`, `powertrain.js`,
`engine-bay-detail.js`, `engine-bay-shell.js`, `transmission-detail.js`, `front-bumper.js`,
`engine-internals.js`, `golf.glb.wasm` and the vendored three.js r169 under `lib/` (including the post-processing passes for ambient occlusion).

New here:
- `hybrid-parts.js` — the eHybrid parts (e-motor/K0 module, inverter, HV cables, charge
  socket, 13 kWh battery, 40 L tank, exhaust) and the EA211 strip-down set with its bolts
  and seals. Constructed geometry: published figures where they exist, estimates elsewhere.
- `front-corner.js` — both front corners, modelled from photos of a removed Golf 8 / A3 8Y
  1.4 eHybrid near-side corner: strut with spring, gaiter and top mount; cast-aluminium wheel
  bearing housing with pinch clamp; pressed-steel lower link and its bushes; swivel joint;
  track rod end; drop link; wheel bearing unit; ventilated disc; floating caliper, carrier and
  pads; splash plate; ABS sensor; brake hose; drive shafts. Plus subframe, rack and anti-roll
  bar. Built for the left side and mirrored. Replaces the model's GTI brakes and the generic
  struts and shafts.
- `jobs.js` — the tool tray and every fastener set: tool, torque, angle stage and renew flag.
- `ehybrid.js` — loads the real Mk8, fits bay, DSG, suspension and hybrid parts; explode,
  see-through body, 11-step engine-out / strip / refit job, parts list and part sheet;
  remove and refit in workshop order with each bolt undone and torqued with the right tool.
  Add `?debug` to the URL to expose the scene for scripted tests.
- `training.js` — assessed workshop training, built on the Strip Bay trainer's method
  (`platform/trainer/sim.js`): stages locked until right, every wrong action logged with the
  reason, conditions randomised each run, a sign-off report at the end. The hands-on stages run
  on this car bolt by bolt: the trainee picks the tool and sets the torque wrench, and the
  workshop reports wrong tools, wrong order, wrong torque and parts outside the stage as faults.
  Jobs: front brakes (pads and discs, measured and decided), front strut (find the leak,
  remove, refit to the data), spark plugs on the 1.4 eHybrid (an engine that can start itself),
  and high-voltage awareness. The engine-out walkthrough stays as an unassessed demonstration.
  `tests/tr_brakes.mjs` and `tests/tr_rest.mjs` drive every job through the page as a trainee
  would (needs the page served locally with `?debug`).
- Photo studio: a seamless cyclorama with a glowing light wall, lit by the CC0 HDRI
  `studio.hdr.wasm` (*Studio Small 09*, Sergej Majboroda, Poly Haven; `.wasm` so the artifact
  host serves it). The car's materials are corrected to real-world values (clear-coated paint,
  non-metal rubber and leather, glowing screens) and its packed vertices unpacked to floats.
- Photoreal: path-traces the current view on demand (three-gpu-pathtracer 0.0.23 with
  three-mesh-bvh 0.7.8, both MIT, vendored under `lib/`), with optional depth of field on the
  selected part and Save photo through the artifact `downloads` capability.

Licence: the car body is "2021 Volkswagen Golf GTI" by Ddiaz Design (Sketchfab),
CC BY-NC-SA 4.0 — non-commercial only. No OEM part numbers are included. Torque, angle and
renew figures come from the Golf Mk7 workshop-manual data in
`platform/trainer/data/golf_mk7_assemblies.json`; anything not in it is marked for erWin.
