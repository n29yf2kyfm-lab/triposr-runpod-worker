# Design language — how the houses should LOOK

Learned from primary sources on 2026-08-14. This is the artistic half of
the knowledge base: the pattern rules that make a facade read as a real
UK house rather than an extrusion, and the rendering rules that make an
image read as a photograph rather than CAD. Each rule is written so a
generator can enforce it.

---

## 1. Georgian pattern language (the reference standard)

Sources: timberwindows-direct.co.uk 6-over-6 guide; gshaydon.co.uk sash
guide; woodenwindows-online.co.uk; scottjameswindows.co.uk

The Georgian terrace is the benchmark UK buyers instinctively read as
"correct". Its rules are numeric and enforceable:

- **Window proportion**: overall sash windows are vertical — height
  ≈ 1.6× width (golden-ratio neighbourhood) up to 2× on principal
  floors. Never wider than tall on a classical facade.
- **Pane proportion**: individual panes ≈ 1.5× taller than wide;
  classic layout 6-over-6 (3 across × 2 high per sash); 8-over-8 on
  wider windows. Glazing bars form a symmetrical grid, equal pane
  counts top and bottom sash.
- **Symmetry**: openings mirror about the front-door axis; the door
  carries a fanlight and the surround (pilasters/pediment) is the one
  place ornament concentrates.
- **Floor hierarchy**: tallest windows on the principal floor, shorter
  above — window HEIGHT diminishes with storey, window HEADS align per
  storey, sills align per storey.
- **Brickwork**: Flemish bond (alternating headers and stretchers in
  each course) is the Georgian signature; gauged brick flat arches over
  openings; parapets hiding shallow roofs on the grandest examples.

## 2. General UK facade rules (any era, incl. modern developer housing)

Derived from the Georgian rules + National Design Guide "Identity/Built
form" + observation of what estates get through committee:

- **Alignment discipline**: window heads align along each storey; cills
  align; upper-floor windows sit over ground-floor openings or the
  centreline between them. Vertical stacks: bathroom/landing windows may
  break rhythm but should still share a head height.
- **Wall-to-window ratio**: solid should dominate; Part L's notional cap
  (openings ≤ 25% of floor area) and Part O's tables coincidentally
  enforce the traditional look.
- **Roof**: 35–45° gables read "UK house"; verge and eaves need TRIM
  (bargeboard, fascia, soffit) — a raw roof edge is the #1 "render
  tell". Ridge/eaves lines should run level and continuous.
- **Brick detail that sells realism**: stretcher bond for modern,
  Flemish for Georgian; soldier-course or brick-arch heads over
  openings; projecting stone/concrete cills; a dpc line two courses
  above ground; corbelled eaves course on better work.
- **Materials palette**: one primary (brick), one secondary (render or
  contrasting brick band), one roof material. West Midlands vernacular:
  orange-red brick, blue-grey (Staffordshire) engineering brick plinths,
  grey concrete tile or slate roofs.
- **Boundary furniture**: front gardens with low walls/hedges, close-
  boarded fences to rear — the plot reads as owned space (our viewer
  already does this).

## 3. What councils judge (aesthetics as compliance)

Source: National Design Guide (gov.uk, 10 characteristics).

Context · Identity · Built form · Movement · Nature · Public spaces ·
Uses · Homes & buildings · Resources · Lifespan. For a householder
extension the officer's questions reduce to: does it match or
deliberately complement (materials, eaves, window proportions)? is it
subordinate (set down ridge, set back face)? does it protect neighbour
amenity (45°/25° daylight tests, overlooking)? Speak those terms in the
Design & Access statement.

## 4. Archviz: making the image read as a photograph

Sources: maxon.net architectural rendering guide; xrender.studio;
gmsvision.de; myarchitectai.com; renderexpo.com

- **Camera**: eye height 1.5–1.7 m for street views (not drone-high);
  verticals kept vertical (two-point perspective — tilt the film back /
  shift, never the camera); 24–35 mm equivalent for exteriors; place the
  camera where a photographer could stand.
- **Lighting hierarchy**: ONE dominant source (the sun), sky as fill;
  golden-hour sun angles (low, warm) flatter brick; overcast for
  material-honest elevations. Shadows must agree with the sky image.
- **Materials**: PBR always; realism lives in ROUGHNESS VARIATION, not
  albedo — plastic-looking renders are wrong roughness, not wrong
  colour. Keep albedo physically plausible (no pure white/black).
- **Imperfection**: subtle weathering at drips/copings, mortar
  variation, slight ground unevenness, not-quite-uniform grass. Perfect
  repetition is the tell — our per-brick hash tint does this correctly.
- **Context**: an object floating on green is a render; a house with
  drive, path, fences, planting, sky with clouds is a photograph. Scale
  cues (bins, doors at 2.0 m, gutters) anchor believability.
- **Composition**: rule of thirds; foreground element (fence line, tree
  edge) for depth; let the building occupy ~60% of frame height.

## 5. Cross-check against our three.js viewer (2026-08-14 state)

Already right: PBR + ACES + real shadows; world-space procedural brick
(215×65 course), roughness varied; trim set (fascia/soffit/gutters/
bargeboards/ridge/cills/frames); plot context; gradient sky + sun disc
+ clouds; computed solar position (Birmingham) in progress.

Gaps this knowledge exposes (build-phase list):
1. **Facade composer**: nothing enforces head/sill alignment or window
   proportion when a plan is generated — add alignment + proportion
   checks (H ≥ 1.3×W for principal windows; heads level per storey) to
   the elevation validator, and a "Georgian mode" (6-over-6 glazing bar
   overlay, Flemish-bond shader variant, door surround + fanlight).
2. **Brick heads/cills**: openings currently have frames+cills but no
   soldier course or arch over heads; add to trim pass.
3. **Camera presets**: orbit default is higher than eye level; add a
   "street view" preset at 1.65 m with verticals corrected.
4. **Golden hour preset**: solar engine exists — add one-click
   "evening" (low-sun) preset; warm the sun colour below ~15° altitude.
5. **DPC/plinth line**: two courses of darker engineering brick at the
   base grounds the elevation (West Midlands vernacular).
