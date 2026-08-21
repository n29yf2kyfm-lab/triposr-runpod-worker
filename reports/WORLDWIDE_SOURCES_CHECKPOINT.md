# CHECKPOINT — worldwide / non-English open-source car-geometry research

Agent: WORLDWIDE SOURCES researcher. Branch `claude/lovable-connection-ki7jch`.
Deliverable: `reports/WORLDWIDE_SOURCES.md` (also `car-meshes/staging/research/WORLDWIDE_SOURCES.md`,
readback verified byte-identical, sha256 b8598707d7d0406e…, 24,951 bytes).

## STATUS: COMPLETE. Nothing in flight, no GPU rented, no money spent, nothing published.

## HEADLINE
No free source anywhere gives a premium model of a specific real nameplate — the 2026-08-13 RCA
stands. Three verified levers do change the margin, all with weights/files public:
  1. TripoSF / SparseFlex (VAST-AI, MIT, HF) — 1024^3 mesh-in/mesh-out reconstruction VAE, 12GB.
  2. Hunyuan3D-Omni (Tencent, HF) — generation controlled by POINT CLOUD / VOXEL / BBOX, 10GB.
  3. Direct3D-S2 (DreamTech, MIT, HF) — native 1024^3 image-to-geometry, 24GB.
Plus DrivAer STEP/IGES (free, registration form needed — a human must fill it) and 3DRealCar
(Apache-2.0, 2,500 real cars x ~200 RGB-D views, real dimensions).

## THE ONE TEST TO RUN NEXT (not run — owner decision)
One pod, one point cloud sampled from the Kia Sportage (recorded crease 270.7), <= $0.60:
  leg A = TripoSF round trip   -> can a 1024^3 representation HOLD a real car's sharpness?
  leg B = Hunyuan3D-Omni point -> can a 3D-conditioned generator PRODUCE it?
Pre-registered gate: crease retention >= 80% of 270.7 AND a visible door shut line at a locked
camera. Leg A failing closes the open-source surfacing question for good — a cheap negative.

## TWO CORRECTIONS RECORDED IN THE REPORT
* "every generator melts, Pixal3D included" is contradicted by this repo's own memory
  (2026-08-15 crease 271.6 vs catalogue band 162-271; 2026-08-19 Yaris with badge, lamp
  internals, shut lines). The blockers recorded after Pixal are fascia/doors/apertures, i.e.
  construction, not melt.
* The Nyquist claim is half wrong: it forbids the shut-line GROOVE, not a sharp CREASE, because
  Flexicubes-family extraction places vertices sub-voxel (INFERRED, measured by leg A).
  Practical answer to the groove: project it as a normal-mapped decal, do not generate it.

## NOT REACHABLE FROM THIS CONTAINER (do not re-attempt blind)
bcebos.com (ApolloCar3D data) 403 · grabcad / turbosquid / free3d / hum3d / aigei 403 ·
cgmodel.com, 3dxy.com no connection · Cranfield DSpace bot wall · HF MoElrefaie/DrivAerNet gated.
openxlab.org.cn + wisemodel.cn are UP but client-rendered — UNSURVEYED, not empty.
ModelScope IS searchable via https://www.modelscope.cn/api/v1/dolphin/models (PUT, JSON body) —
searched EN + Chinese; everything 3D-native on it mirrors HF/GitHub.
