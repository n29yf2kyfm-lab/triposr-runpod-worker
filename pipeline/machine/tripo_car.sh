#!/bin/bash
# tripo_car.sh — raw Tripo GLB -> finished car, the ENTIRE proven chain.
#
# Codified from the 2026-08-28/29 Golf RF67 session at the owner's order
# ("Take the pipeline when we done this"). Every stage below earned its place
# by a measured fix that day; the war stories live in CLAUDE.md and in each
# tool's own docstring. One command, resumable, artefact per stage.
#
#   bash tripo_car.sh <raw.glb> <workdir> <spec.json> [from_stage]
#
# Stages (name = the [from_stage] token):
#   canon     canon.py --spec           pose + published dims (±1%)
#   deyaw     deyaw.py                  mirror-plane yaw fix (66.9->9.8mm on
#                                       the Golf); ALREADY-ALIGNED is a pass
#   views     seg_views x18             10 standard + 8 at el -6 (sills)
#   masks     seg_masks                 DINO+SAM, SEG_BOX_THR=0.18
#   lamps     lamp_boost                6 nose views, thr 0.16 (L/R 0.49->0.79)
#   project   seg_project               fixed roof rule (|n_x| exemption);
#                                       glass_relabel SKIPPED — dense mesh
#   refine    seg_refine
#   boundary  seg_boundary              stencils off (crease-bounded labels)
#   assemble  seg_assemble
#   finish    blender_finish            weld + weighted normals
#   normals   normals_fix               NORMAL verified present
#   tangents  gltf-transform tangents   MikkTSpace (3rd trimesh-drop class)
#   nmap      normalmap_scale 0.35      wavy-bonnet fix (map, NOT the mesh)
#                                       *** THE DELIVERABLE STOPS HERE ***
#   render    showroom.py               8 views, glTF-compliant culling
#
# OPTIONAL, OFF BY DEFAULT (run with --with-surgical / --with-clean):
#   surgical  surgical_fix              cabin occluder + smoked lamps
#   clean     self-colour respray       door-sampled hex; factor MULTIPLIES
#                                       the texture so badge/plate survive
#
# WHY THE CHAIN STOPS AT nmap — OWNER'S CHOICE, 2026-08-29. Shown five
# variants of the same car, the owner picked the nmap output and said "go
# back to this". Identified by feature, not by guess: pale (untinted)
# lamps, gloss-black textured alloys, a legible RF67 FPX plate and the blue
# GTE grille line. NOTE the whole-frame pixel diff could NOT tell the five
# apart (all ~55, dominated by background and crop offset) — another metric
# measuring something adjacent to the question; the discriminating features
# settled it.
#
# What the owner's choice rejects, and it is worth being precise:
#   * surgical's SMOKED LAMPS. Darkening the lens is materially more
#     correct than a pale baked graphic, and it still lost — dark lamps on
#     a dark car read as "no lamps". Correctness lost to legibility.
#   * the CLEAN RESPRAY. It removes the photo-baked mottle, which is a real
#     defect, but dims the badge/plate/grille with it. Identity beat
#     paint quality.
# Both remain one flag away for a car where the trade goes the other way
# (a pale car, or one whose baked lighting is worse than its badges).
#
# NOT in this chain, deliberately: premium.py construction. On a dense
# textured generator it substitutes worse parts for better ones (blank
# plates, silver donor rims — measured). Run it separately when a car NEEDS
# constructed components, and strip the substitutions after.
set -e
WITH_SURGICAL=0; WITH_CLEAN=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --with-surgical) WITH_SURGICAL=1 ;;
    --with-clean)    WITH_CLEAN=1; WITH_SURGICAL=1 ;;   # clean consumes surgical output
    *) ARGS+=("$a") ;;
  esac
done
set -- "${ARGS[@]}"
RAW="$1"; W="$2"; SPEC="$3"; FROM="${4:-canon}"
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$W"
cd "$W"

stage() {  # stage <name> -> 0 if it should run
  local order="canon deyaw views masks lamps project refine boundary assemble finish normals tangents nmap surgical clean render"
  local seen=0
  for s in $order; do
    [ "$s" = "$FROM" ] && seen=1
    [ "$s" = "$1" ] && { [ $seen -eq 1 ] && return 0 || return 1; }
  done
  return 1
}
mark() { echo "=== $1 $(date -u +%H:%M:%S)"; }

if stage canon; then
  mark canon
  python3 "$R/machine/canon.py" "$RAW" "$W/s1_canon.glb" --spec "$SPEC"
fi

if stage deyaw; then
  mark deyaw
  # an already-aligned car REFUSES with gain<min — that is a PASS, not a
  # failure: carry the input forward instead of aborting the chain
  if python3 "$R/machine/deyaw.py" "$W/s1_canon.glb" "$W/s2_deyaw.glb" \
       --report "$W/deyaw.json" 2>&1 | tee "$W/deyaw.log"; then :; fi
  if [ ! -f "$W/s2_deyaw.glb" ]; then
    if grep -q "already aligned" "$W/deyaw.log"; then
      cp "$W/s1_canon.glb" "$W/s2_deyaw.glb"
      echo "deyaw: already aligned — carried forward"
    else
      echo "deyaw FAILED for a reason other than alignment"; exit 1
    fi
  fi
fi

if stage views; then
  mark views
  rm -rf "$W/views"; mkdir -p "$W/views"
  blender -b --python "$R/trellis/seg_views.py" -- "$W/s2_deyaw.glb" "$W/views"
  SEG_VIEWS_SPEC="0:-6,45:-6,90:-6,135:-6,180:-6,225:-6,270:-6,315:-6" \
    SEG_VIEW_OFFSET=10 \
    blender -b --python "$R/trellis/seg_views.py" -- "$W/s2_deyaw.glb" "$W/views"
fi

if stage masks; then
  mark masks
  SEG_BOX_THR=0.18 python3 -u "$R/trellis/seg_masks.py" "$W/views"
fi

if stage lamps; then
  mark lamps
  python3 -u "$R/machine/lamp_boost.py" "$W/views" \
    view_00 view_01 view_07 view_10 view_11 view_17
fi

if stage project; then
  mark project
  python3 -u "$R/trellis/seg_project.py" "$W/s2_deyaw.glb" "$W/views" "$W/car"
fi

if stage refine; then
  mark refine
  python3 -u "$R/trellis/seg_refine.py" "$W/s2_deyaw.glb" \
    "$W/car_labels.npy" "$W/car_r.npy"
fi

if stage boundary; then
  mark boundary
  GLASS_STENCIL=0 LAMP_STENCIL=0 python3 -u "$R/machine/seg_boundary.py" \
    "$W/s2_deyaw.glb" "$W/car_r.npy" "$W/car_b.npy"
fi

if stage assemble; then
  mark assemble
  python3 -u "$R/trellis/seg_assemble.py" "$W/s2_deyaw.glb" "$W/car_b.npy" \
    "$W/s9_materialised.glb"
fi

if stage finish; then
  mark finish
  blender -b --python "$R/machine/blender_finish.py" -- \
    "$W/s9_materialised.glb" "$W/s10_finished.glb"
fi

if stage normals; then
  mark normals
  python3 -u "$R/machine/normals_fix.py" "$W/s10_finished.glb" "$W/s11_normed.glb"
fi

if stage tangents; then
  mark tangents
  npx --yes @gltf-transform/cli tangents "$W/s11_normed.glb" "$W/s12_tangented.glb"
fi

if stage nmap; then
  mark nmap
  python3 -u "$R/machine/normalmap_scale.py" "$W/s12_tangented.glb" \
    "$W/s13_nmap.glb" --scale 0.35 --materials carpaint
fi

# the owner's chosen deliverable is the nmap output — name it now, so a run
# that stops here still leaves CAR_FINAL.glb rather than an unnamed stage file
if stage nmap; then
  cp "$W/s13_nmap.glb" "$W/CAR_FINAL.glb"
  echo "CAR_FINAL.glb = nmap output (owner's chosen state)"
fi

if [ "$WITH_SURGICAL" = "1" ] && stage surgical; then
  mark surgical
  python3 -u "$R/machine/surgical_fix.py" "$W/s13_nmap.glb" "$W/s14_surg_raw.glb"
  python3 -u "$R/machine/normals_fix.py" "$W/s14_surg_raw.glb" "$W/s14_surg_n.glb"
  npx --yes @gltf-transform/cli tangents "$W/s14_surg_n.glb" "$W/s14_surgical.glb"
  [ "$WITH_CLEAN" = "1" ] || cp "$W/s14_surgical.glb" "$W/CAR_FINAL.glb"
fi

if [ "$WITH_CLEAN" = "1" ] && stage clean; then
  mark clean
  python3 - "$W" <<'PYEOF'
import sys, numpy as np, trimesh
W = sys.argv[1]
sc = trimesh.load(f"{W}/s14_surgical.glb", force="scene")
cp = sc.geometry["carpaint"]
img = np.asarray(cp.visual.material.baseColorTexture.convert("RGB"), np.float32)
c = cp.triangles_center; uv = cp.visual.uv
allv = np.vstack([g.vertices for g in sc.geometry.values()])
x0, x1 = allv[:, 0].min(), allv[:, 0].max()
y0 = allv[:, 1].min(); H = allv[:, 1].max() - y0
xf = (c[:, 0] - x0) / (x1 - x0); yf = (c[:, 1] - y0) / H
z = np.abs(c[:, 2])
band = (xf > 0.30) & (xf < 0.62) & (yf > 0.35) & (yf < 0.55)
door = band & (z > np.percentile(z[band], 75))       # outermost quartile
fuv = uv[cp.faces].mean(1); ih, iw = img.shape[:2]
px = np.clip((fuv[door][:, 0] * (iw - 1)).astype(int), 0, iw - 1)
py = np.clip(((1 - fuv[door][:, 1]) * (ih - 1)).astype(int), 0, ih - 1)
med = np.median(img[py, px], axis=0)
h = "".join(f"{int(v):02x}" for v in med)
open(f"{W}/bodyhex.txt", "w").write(h)
print("door-sampled body colour:", h)
PYEOF
  python3 -c "
import sys; sys.path.insert(0, '$R/publish')
from respray_gltf import respray
hexcol = open('$W/bodyhex.txt').read().strip()
respray('$W/s14_surgical.glb', '$W/CAR_FINAL.glb', ['carpaint'], hexcol)
print('clean respray at', hexcol)"
fi

if stage render; then
  mark render
  rm -rf "$W/renders"; mkdir -p "$W/renders"
  SHOW_SAMPLES=${SHOW_SAMPLES:-54} blender -b --python "$R/machine/showroom.py" -- \
    "$W/CAR_FINAL.glb" "$W/renders" beauty,clay,matid
fi

echo "TRIPO_CAR_DONE $(date -u +%H:%M:%S) — deliverable: $W/CAR_FINAL.glb"
