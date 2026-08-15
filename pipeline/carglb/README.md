# car-glb — photos in, gate-passing GLB out

The orchestrator from `pipeline/trellis/IMAGE_TO_GLB_PLAN.md`. One command
wiring the chain this repo has already proven piece by piece:

```
python3 pipeline/carglb/carglb.py check    <folder>          # free — no GPU
python3 pipeline/carglb/carglb.py generate <folder> -o car.glb
python3 pipeline/carglb/carglb.py gates    <some.glb>        # gates only
```

Folder contract: `dims.json` (published mm, required — pixels never set
scale) + `front.png rear.png` (RGBA cutouts, required) + `left/right/f34.png`
(recommended). `check` runs the capture gate and prints warnings; `generate`
refuses dirty masks and missing dims loudly, BEFORE any GPU money.

Stages: capture gate → upload views → `shape_boot.sh` on a RunPod box
(Hunyuan-2mv shape + PartCrafter parts, hardened bootstrap: preflighted URL,
torch pin + assert, artefact asserts, log-file monitoring — never
desiredStatus) → `build_car.py`'s fatal gates (glass clear/proven, glazing
band, four corners, material names, red respray) → production-rig QC renders +
`mesh_forensics` numbers written next to the GLB.

HONESTY CONTRACT: output is gap-filler tier. No shut lines, badges, or premium
panel language — measured (STUDY_3D.md) to be below the representable
bandwidth of every open generator. Output lands in `staging/carglb/`; nothing
ships without the owner's per-car sign-off (standing rule 2026-08-14).
