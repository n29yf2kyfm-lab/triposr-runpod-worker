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
#   nose      nose_fix.py               put the NOSE at +x. MUST precede the
#                                       views: lamp_boost picks nose views by
#                                       index before any label exists, so a
#                                       wrong sign boosts the tail lamps
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
#   interior  interior_kit + apply      dash, seats, headrests, RHD wheel
#   polish    glass_polish              paint OFF the windows (5960->0 on the
#                                       Golf), then paint_pbr sets the body
#                                       PBR AFTER the last round trip —
#                                       PAINT_PRESET=studio (default, the
#                                       owner's near-black studio look) or
#                                       =premium (brief values + clearcoat)
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
  local order="canon deyaw nose views masks lamps project refine boundary assemble finish normals tangents nmap interior polish surgical clean render"
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

if stage nose; then
  mark nose
  python3 "$R/machine/nose_fix.py" "$W/s2_deyaw.glb" "$W/s2b_nose.glb" \
    --report "$W/nose.json"
fi

if stage views; then
  mark views
  rm -rf "$W/views"; mkdir -p "$W/views"
  blender -b --python "$R/trellis/seg_views.py" -- "$W/s2b_nose.glb" "$W/views"
  SEG_VIEWS_SPEC="0:-6,45:-6,90:-6,135:-6,180:-6,225:-6,270:-6,315:-6" \
    SEG_VIEW_OFFSET=10 \
    blender -b --python "$R/trellis/seg_views.py" -- "$W/s2b_nose.glb" "$W/views"
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
  python3 -u "$R/trellis/seg_project.py" "$W/s2b_nose.glb" "$W/views" "$W/car"
fi

if stage refine; then
  mark refine
  python3 -u "$R/trellis/seg_refine.py" "$W/s2b_nose.glb" \
    "$W/car_labels.npy" "$W/car_r.npy"
fi

if stage boundary; then
  mark boundary
  GLASS_STENCIL=0 LAMP_STENCIL=0 python3 -u "$R/machine/seg_boundary.py" \
    "$W/s2b_nose.glb" "$W/car_r.npy" "$W/car_b.npy"
fi

if stage assemble; then
  mark assemble
  python3 -u "$R/trellis/seg_assemble.py" "$W/s2b_nose.glb" "$W/car_b.npy" \
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

if stage interior; then
  mark interior
  python3 -u "$R/machine/interior_kit.py" "$W/s13_nmap.glb" "$W/int_kit.npz"
  python3 -c "
import sys; sys.path.insert(0,'$R/machine')
from premium import apply_interior
apply_interior('$W/s13_nmap.glb','$W/int_kit.npz','$W/s14_interior.glb','$W/int.log')"
  python3 - "$W" <<'PYEOF'
import json, struct, sys
W = sys.argv[1]
# the kit ships near-black (20-30/255) which is invisible behind a 0.353
# tint; these read as a real dark cabin through the glass
# TONED DOWN 2026-08-29. The first values (52-66) were calibrated against
# crinkled glass; once glass_smooth flattened the panes and the paint went
# to the studio preset, the cabin read as pale slabs floating behind clean
# glazing. A real cabin is much darker than its own paint.
# TONED AGAINST MEASURED RENDER BRIGHTNESS, not by eye. Through the back
# glass the cabin was reading BRIGHTER than the car: parcel shelf mean luma
# 142, rear headrest 124, front seat back 99 - against a tailgate panel at
# 83 and the backdrop at 155. An interior seen through tinted glazing has to
# sit well below the bodywork or it reads as clutter floating in the window,
# which is what the owner saw ("clean the back glass"). Roughly a 1.8x
# albedo cut across the cabin and 4x on the parcel shelf, which is the flat
# surface staring straight up into the overhead softbox.
T = {"Int_Floor":12,"Int_Dash":20,"Int_Console":21,"Int_SeatFR_C":25,
     "Int_SeatFR_B":23,"Int_SeatFR_H":26,"Int_SeatFL_C":25,"Int_SeatFL_B":23,
     "Int_SeatFL_H":26,"Int_BenchC":22,"Int_BenchB":21,"Int_Wheel":15,
     "Int_SeatFR_BolR":21,"Int_SeatFR_BolL":21,
     "Int_SeatFL_BolR":21,"Int_SeatFL_BolL":21,
     "Int_HeadRR":26,"Int_HeadRL":26,"Int_Shelf":8}
p = f"{W}/s14_interior.glb"
d = open(p,"rb").read(); ln = struct.unpack("<I", d[12:16])[0]
j = json.loads(d[20:20+ln]); rest = d[20+ln:]
n = 0
for m in j.get("materials", []):
    t = T.get(m.get("name",""))
    if t is None: continue
    pbr = m.setdefault("pbrMetallicRoughness", {})
    pbr["baseColorFactor"] = [t/255, t/255, (t+3)/255, 1.0]
    pbr["roughnessFactor"] = 0.82; pbr["metallicFactor"] = 0.0
    n += 1
if n < 17: raise SystemExit(f"REFUSED: only {n} interior materials found")
js = json.dumps(j, separators=(",",":")).encode(); js += b" "*((4-len(js)%4)%4)
open(p,"wb").write(b"glTF"+struct.pack("<II",2,12+8+len(js)+len(rest))
                   +struct.pack("<I",len(js))+b"JSON"+js+rest)
print(f"interior toned: {n} materials")
PYEOF
fi

if stage polish; then
  mark polish
  python3 -u "$R/machine/glass_polish.py" "$W/s14_interior.glb" "$W/s15_polish.glb"
  python3 -u "$R/machine/normals_fix.py" "$W/s15_polish.glb" "$W/s15_polish_n.glb"
  npx --yes @gltf-transform/cli tangents "$W/s15_polish_n.glb" "$W/s15_tangented.glb"
  # PAINT PBR IS SET AFTER THE LAST ROUND TRIP, NOT INSIDE glass_polish.
  # normals_fix and the tangents pass both round-trip the file, and a
  # trimesh round trip drops every KHR material extension — glass_polish's
  # clearcoat was written and then silently eaten, while its metallic and
  # roughness survived (those are core, not extensions), so the log read
  # as a success with half the edit missing. Preset is the owner's, by eye.
  python3 -u "$R/machine/paint_pbr.py" "$W/s15_tangented.glb" "$W/s15_paint.glb" \
    --preset "${PAINT_PRESET:-studio}"
  # AND THE NORMAL-MAP SCALE HAS TO BE RE-APPLIED HERE, for the same reason.
  # The nmap stage sets normalTexture.scale 0.35 at s13 and the interior and
  # polish stages round-trip the file through trimesh, which drops it — the
  # key is core glTF, not an extension, and it goes anyway. Default is 1.0,
  # so the deliverable shipped with the normal map at FULL strength: the
  # wavy-panel look nmap exists to remove, silently back. Measured on the
  # multiview Golf, carpaint normalTexture in CAR_FINAL carried no scale at
  # all while the v31 car it was being compared against carried 0.35.
  python3 -u "$R/machine/normalmap_scale.py" "$W/s15_paint.glb" "$W/CAR_FINAL.glb" \
    --scale "${NMAP_SCALE:-0.35}"
  python3 - "$W/CAR_FINAL.glb" <<'PYEOF'
import json, struct, sys
d = open(sys.argv[1], "rb").read()
j = json.loads(d[20:20 + struct.unpack("<I", d[12:16])[0]])
m = [x for x in j.get("materials", []) if x.get("name") == "carpaint"]
if not m:
    raise SystemExit("REFUSED: CAR_FINAL has no carpaint material")
nt = m[0].get("normalTexture")
if nt is not None and "scale" not in nt:
    raise SystemExit("REFUSED: carpaint normalTexture lost its scale again — "
                     "a later round trip is eating it")
print(f"CAR_FINAL carpaint verified: {json.dumps(m[0])}")
PYEOF
  echo "CAR_FINAL.glb = polished output, paint preset ${PAINT_PRESET:-studio}, "\
"nmap ${NMAP_SCALE:-0.35}"
fi

if [ "$WITH_SURGICAL" = "1" ] && stage surgical; then
  mark surgical
  python3 -u "$R/machine/surgical_fix.py" "$W/CAR_FINAL.glb" "$W/s14_surg_raw.glb"
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
    "$W/CAR_FINAL.glb" "$W/renders" "${SHOW_MODES:-beauty,clay,matid}"
fi

echo "TRIPO_CAR_DONE $(date -u +%H:%M:%S) — deliverable: $W/CAR_FINAL.glb"
