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
- `ehybrid.js` — loads the real Mk8, fits bay, DSG, suspension and hybrid parts; explode,
  see-through body, 11-step engine-out / strip / refit job, parts list and part sheet.

Licence: the car body is "2021 Volkswagen Golf GTI" by Ddiaz Design (Sketchfab),
CC BY-NC-SA 4.0 — non-commercial only. No OEM part numbers or torque values are included.
