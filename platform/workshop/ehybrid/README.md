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

Licence: the car body is "2021 Volkswagen Golf GTI" by Ddiaz Design (Sketchfab),
CC BY-NC-SA 4.0 — non-commercial only. No OEM part numbers are included. Torque, angle and
renew figures come from the Golf Mk7 workshop-manual data in
`platform/trainer/data/golf_mk7_assemblies.json`; anything not in it is marked for erWin.
