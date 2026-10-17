# What the GLB machine is made of, and under which licences

Checked 2026-10-16 on the installed packages (`npx license-checker --production`).
Every component the software runs is under a **permissive** licence: it may be
used in a closed, paid product, provided its copyright notice and licence text
travel with it (they do: each package keeps its own LICENSE file in
`node_modules`, and Python's in `site-packages`).

## Ours

| Part | Where it came from |
| --- | --- |
| `rig.py`, `finish.py`, `edits.py`, `make.py`, `batch.py`, `wheelbase.py`, `glbmachine.py`, `importer.py`, the `.mjs` tools, `view.html`, `maker/` (GLB Maker), `studio/` (GLB Studio), `../template/gltf.py` | written for ExpertCarCheck |
| `assets/engine_pack.glb` (engine, gearbox, cooling, battery, suspension, exhaust) | exported from our own constructed geometry (`platform/trainer/engine-bay-detail.js`, `platform/workshop/ehybrid/hybrid-parts.js`: `sourceType: constructed-training-geometry`); its 11 textures are generated in code. Nothing in it is cut from a third-party model. |
| `vendor/no-sharp` | a stand-in so the LGPL image library below is never installed |

## Taken out on purpose

| Was | Licence | Why it is gone |
| --- | --- | --- |
| Blender (the old rig step, `platform/rigmachine`, `platform/trainer/blender_addon`) | GPL-3.0 | code that drives Blender's Python API is a derivative of Blender; shipped together, the product would have to be GPL. The rig step is now `rig.py` (numpy), checked against Blender on 21 cars. |
| sharp / libvips | LGPL-3.0 | pulled in by gltf-transform for texture resizing, which the machine never does |

The Blender folders still sit in the repository for comparison; they are not
part of the product and the Docker image does not contain them.

## Python (pip)

| Package | Licence |
| --- | --- |
| numpy | BSD-3-Clause |
| scipy | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| Python itself | PSF License |

## Node (npm, 103 packages: MIT 72, Apache-2.0 13, ISC 8, BSD-2 5, BSD-3 3, 0BSD 1)

| Main package | Licence | Used for |
| --- | --- | --- |
| @gltf-transform/core, extensions, functions | MIT | reading and writing glTF |
| draco3dgltf | Apache-2.0 | opening Draco-compressed catalogue files |
| meshoptimizer | MIT | opening and writing meshopt-compressed files |
| gltf-validator (Khronos) | Apache-2.0 | checking every finished car |
| puppeteer-core | Apache-2.0 | driving the browser that draws check sheets |
| three (three.js r169, with its GLTFLoader, OrbitControls, RoomEnvironment and meshopt decoder add-ons) | MIT | the check-sheet page and GLB Studio |

Apache-2.0 asks that its NOTICE files are kept when redistributed; they are,
inside `node_modules`.

## Other programs

| Program | Licence | Note |
| --- | --- | --- |
| Node.js | MIT | |
| Chromium | BSD-3-Clause (plus bundled permissive parts) | only for check sheets; the car is built without it (`--no-sheet`) |

## Data

| Data | Licence | Note |
| --- | --- | --- |
| UK vehicle licensing statistics (DfT VEH0120) behind `top2000_cars.csv` | Open Government Licence v3.0 | credit: "Contains public sector information licensed under the Open Government Licence v3.0." |
| Wheelbases read once from Wikipedia infoboxes into `wheelbase_table.json` | facts (not protected) | only the numbers (years, wheelbase, length) and page titles are kept; nothing is fetched while building a car |

## The cars: separate from the software

The software is ours to license. **The car models it processes are not.**
Each finished GLB is a modified copy of a 3D model by someone else and keeps
that model's licence; the machine writes the author, title, licence and link
into the file (`asset.copyright`) and into the build report.

| Model licence | Can a finished car be used commercially? |
| --- | --- |
| CC BY 4.0 | yes, with the credit shown where the car is shown |
| CC BY-SA 4.0 | yes, with credit; the finished car must also be offered under CC BY-SA |
| CC0 | yes |
| CC BY-NC / BY-NC-SA | **no**: non-commercial use only. Many catalogue models are NC. |
| NoDerivatives (ND) | never used: the machine refuses them |

So: licensing the **software** to another company is clean; what each customer
may do with the **cars** it builds depends on each model's licence. A
solicitor should confirm both before the first licence is sold, in particular
whether ExpertCarCheck's free app counts as non-commercial for the NC models.
