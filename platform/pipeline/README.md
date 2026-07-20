# GLB ingest / fix pipeline

Offline pipeline that turns sourced CC-BY car GLBs into premium, plated,
recolourable catalogue assets. Two phases:

1. **Process** (`ingest_process_hard.py`) — download → material-preserving
   hardening (bake transforms, recalc normals on opaque body faces, bake GB
   plates) → webp → draco. Render-verifies each and auto-falls back to a
   plateless path (`copy → webp → draco`, no Blender) when the plated result
   comes out dark/blob, recovering models whose material graph Blender mangles.
   Writes a verification contact sheet for the manual eyeball gate.
2. **Commit** (`ingest_commit.py`) — promotes the verified GLBs live: uploads to
   the serving Supabase, renders a hero poster, bakes the 4 colour variants
   (grey/silver/black/white) on the worker-reported body materials, and writes
   the schema-v2 catalogue entry.

`live_cand.py` is the sourcing front-end: it searches Sketchfab (downloadable,
CC-BY/CC0), junk-filters, and renders the top candidates per model into
per-model sheets so you can pick the genuine ones before ingesting.

## Scripts

| Script | Role |
|---|---|
| `config.py` | central env-based config (secrets + paths); no keys committed |
| `live_cand.py` | Sketchfab search → render candidate sheets |
| `ingest_process_hard.py` | download + harden + plate + verify-render (phase 1) |
| `ingest_commit.py` | promote live: hero + 4 colour variants + catalogue (phase 2) |
| `fix_glb_hard.py` | Blender fixer: bake transforms, recalc opaque normals, plates |
| `fix_glb_np.py` | Blender fixer variant with active re-upright (for tipped sources) |
| `bake_colour.py` | Blender flat-respray of named body materials to a linear RGB |

## Configuration (environment variables)

Secrets are **never** committed — supply them via the environment.

Required for the networked scripts:

```
SKETCHFAB_TOKENS       comma-separated Sketchfab API tokens (rotated on 429/403)
SUPABASE_SERVICE_KEY   service-role key for the serving Supabase project
RUNPOD_API_KEY         RunPod API key (rpa_...)
```

Optional (defaults shown):

```
PIPELINE_WORKDIR       ./pipeline_work        scratch for downloads/renders/staging
PIPELINE_ASSETS        ./assets               plate_front.png / plate_rear.png
RUNPOD_RENDER_ENDPOINT ng8oiz4p2l0xa0         render endpoint id
SUPABASE_OBJECT_URL    <public serving object base>
PIPELINE_REPO          <repo root>            where catalogue.v2.json lives
PIPELINE_CATALOGUE     $PIPELINE_REPO/platform/catalogue/catalogue.v2.json
```

Dev fallback: if a secret env var is unset, `config.py` will try to read it from
an untracked `golf_publish.py` in `PIPELINE_WORKDIR` (the historic scratchpad
layout), so an existing working checkout keeps running without extra setup.

## Usage

```bash
export SKETCHFAB_TOKENS=... SUPABASE_SERVICE_KEY=... RUNPOD_API_KEY=...

# 1. source candidates for a batch of targets
python3 live_cand.py targets.json mybatch
#    targets.json = [[make, model_key, "Human Name", "search query"], ...]
#    -> review pipeline_work/batch/mybatch/*.jpg, keep the genuine UIDs

# 2. process the winners (spec = list of {assetId, make, model, aliases,
#    bodyStyle, uid, upright, grade, sourceTitle, mode}) 
python3 ingest_process_hard.py spec.json mybatch
#    -> eyeball pipeline_work/ingest/mybatch/sheet.jpg (glass/wheels/orientation)

# 3. commit the ones that pass the eyeball gate
python3 ingest_commit.py spec.json mybatch "assetId1,assetId2,..."
#    -> updates catalogue.v2.json + pushes GLBs/variants/poster to Supabase
```

## Design notes

- **Material preservation:** we decode Draco with `gltf-transform copy` (never
  `optimize`, which merges materials and destroys the glass/body separation the
  recolour and glass-tint depend on).
- **Glass/light normals are never recalculated** (`fix_glb_hard.py`). Recalcing
  "outward" normals on thin transmissive surfaces flips the authored normals and
  shatters the refraction into a camo/leopard mottle (root-caused 2026-07-20 on
  Cupra Ateca, Volvo C30, Toyota Proace — clean at decode, broken only after the
  Blender fixer; webp/draco were innocent). The fixer excludes glass/light/
  transmissive faces — matched by material name **and** by blend-mode /
  transmission / alpha, so unnamed glass is caught too — while still recalcing
  opaque body faces (which keeps the mirrored/negative-scale dark-render fix).
- **Plateless fallback:** the Blender export can mangle complex multi-material
  bodies into a half-black render; the brightness gate detects this and reruns a
  no-Blender `copy → webp → draco` path that renders like the raw source.
- **Manual eyeball gate is mandatory.** Programmatic checks pass many defective
  models (frosty/camo glass, transparent bodies, on-side orientation, exploded
  meshes, wrong vehicle). Always review the contact sheet before committing.
