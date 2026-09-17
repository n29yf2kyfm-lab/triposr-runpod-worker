# Strip Bay — mechanics teardown trainer

`golf-bay.html` is the whole app: one file, seven bays, no build step.
Published 2026-09-17 as a private artifact.

## What is REAL and what is CONSTRUCTED

This distinction is load-bearing and it is shown on screen in every bay,
because a trainer that blurs it teaches the wrong thing.

REAL, from `volkswagen-golf-2021-w12-v1` (163 named meshes, 543,082 triangles):
four doors with cards/glass/speakers, the **door check straps**
(`Ext_Door_Limiter_*`), four rims + tyres, front discs and calipers per side,
rear discs/calipers (as one L+R mesh), tailgate with its hinge arms, seats,
steering wheel, **eight separate airbags**, carpets, headlining, pillars,
lamps, glazing, sunroof.

CONSTRUCTED in code, and captioned as such:
door internals (regulator, latch, beam, loom, barrier), starter motor,
four-stroke engine, brake pads, the four door hinge bolts, the loom boot,
the door prop, the bench circuit.

ABSENT from the car file entirely — checked across all 163 meshes, zero
matches: bumper (welded into the body mesh with bonnet, wings and roof),
engine, starter, battery, suspension, exhaust, door internals.

## Rebuilding the asset

The GLB is NOT in this repo (standing order: no GLBs on the box). Rebuild it:

```sh
curl -sO https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/\
car-meshes/finished/volkswagen/volkswagen-golf-2021-w12-v1.glb
python3 ../../pipeline/machine/scale_normalise.py \
    volkswagen-golf-2021-w12-v1.glb golf_m.glb     # 43 mm -> 4.295 m
npx -y @gltf-transform/cli meshopt golf_m.glb golf.glb.wasm --level medium
```

25.38 MB -> 8.42 MB, all 328 node names and all 543,082 triangles preserved
(verified). `scale_normalise` first: the source carries a spurious FBX
centimetre conversion and renders as a 43 mm speck otherwise.

**Why `.glb.wasm`.** Artifact hosting serves a fixed set of extensions and
`.glb` is not one of them under any content type, while `.wasm` is served and
is binary-safe. GLTFLoader identifies the file by its `glTF` magic bytes, so
the extension is irrelevant to parsing. Byte-identical file.

three.js r169 is vendored beside the page rather than loaded from a CDN, so
the only network fetch the app makes is the car itself:

```sh
B=https://cdn.jsdelivr.net/npm/three@0.169.0
curl -sS $B/build/three.module.js -o lib/three.module.js
for f in loaders/GLTFLoader.js controls/OrbitControls.js \
         libs/meshopt_decoder.module.js environments/RoomEnvironment.js \
         utils/BufferGeometryUtils.js; do
  mkdir -p lib/addons/$(dirname $f); curl -sS $B/examples/jsm/$f -o lib/addons/$f
done
```
The import graph is closed — every import in those six files resolves to
"three" or a sibling.

## Verifying it

Three harnesses, and they exist because this app shipped two bugs that were
invisible in the source and invisible in a screenshot:

* `verify.mjs` — loads every bay in real Chromium, screenshots each, records
  panel size / manual count / HUD count, and collects console + page errors.
* `probe.mjs` — asserts on STATE, not pixels. `partIds` is the one that
  matters: 23 is healthy, 1 means classification failed.
* `doorprobe.mjs` — walks the door job in the WRONG order and asserts each
  hard stop fires, then does it right and checks the door actually leaves.

```sh
npm i puppeteer-core@23
node verify.mjs ./ ./shots
node doorprobe.mjs ./ ./shots
```

Software rendering here (no GPU), so timings mean nothing — these prove
behaviour, not performance.

## Two traps this app paid for

**`#loading{display:grid}` beats `[hidden]{display:none}`.** The loading
overlay could never be dismissed and the app sat behind it forever, on every
device. The code read correctly. One line fixes it:
`[hidden]{display:none !important}`.

**three.js DELETES the colon in a node name.** Every node in the GLB is
`G:Ext_Door_FL_…`; `PropertyBinding.sanitizeNodeName` strips reserved
characters, so the mesh arrives as `GExt_Door_FL_…`. A leading-`G:` test never
fires, every rule misses, and the catch-all swallowed all 163 meshes —
`partIds` 1 instead of 23, every teardown action hitting `if(!p) return`, no
error, and a flawless-looking render. `classify()` now matches the raw name
and both de-prefixed forms, and the app shouts on screen if fewer than ten
part groups are recognised.

## Teaching content

Reviewed 2026-09-17 by `stealth/union-alpha` via `pipeline/machine/ox.py`,
which found four hard factual errors (timing BELT on a chain-driven EA888;
"air and fuel" intake on a direct-injection engine; pawl/claw conflated in a
rotary latch; a wheel-bolt socket size) and eleven places stating a diagnosis
as a certainty. All corrected. Every manual closes with a standing line: the
bay teaches how the thing works, and the workshop data for the actual car
governs the specifics.

Torque and size figures are labelled "typical — confirm against the data".
Nothing model-specific is asserted that was not measured off the asset.

## Not built yet

Timing drive (belt AND chain, one tooth out = valve/piston contact), head off
(bolt sequence, stretch bolts, warp check), piston rings, alternator (diode
ripple on the scope, which links to the bench), engine out. Union Alpha's
spec for engine removal and five scope/meter diagnosis scenarios is in the
session record.
