# Architects' drawing conventions — how the plans must be drawn

Learned from primary sources on 2026-08-14 (marraum.co.uk drawing
standards; firstinarchitecture.co.uk floor plan checklist; BS 8541
series via bsigroup/designingbuildings; cedreo/janedrawsplans symbol
guides; Wikipedia floor-plan article for the cut convention). This file
is the standard our generated plans are drawn against, and the audit of
where our current output falls short.

## 1. Projection and the cut

- A floor plan is an ORTHOGRAPHIC projection: no perspective, true
  lengths, drawn as a horizontal section cut ~1.2 m (4 ft) above
  finished floor — through the windows, below the lintels. (Our viewer
  cuts at 1.4 m: within convention.)
- Everything CUT is drawn heaviest (walls in poche or solid); everything
  seen BELOW the cut is medium (fixtures, floor edges); anything ABOVE
  the cut (rooflights, high-level cupboards, the void over a stair) is
  dashed.
- Elevations and sections are the same discipline vertically; every
  section needs a section line + arrows on the plan naming it (A-A).

## 2. Scales and sheet discipline (UK metric practice)

- Location plan 1:1250 or 1:2500 (red line round the site).
- Block/site plan 1:200 or 1:500.
- Floor plans, elevations, sections: 1:100 general, 1:50 detailed.
- Construction details: 1:20, 1:10, 1:5.
- Every sheet: title block (project, drawing title, number, revision,
  date, scale, "do not scale" note), scale bar, north point on every
  plan. Revisions lettered and clouded.

## 3. Line weight hierarchy

The drawing reads by weight, thickest to thinnest:
1. Cut elements (walls at the section plane) — heaviest, or filled
   poche; external walls read thicker than internal partitions.
2. Profiles/outlines of elements below the cut.
3. Furniture, fittings, sanitaryware — light.
4. Dimension lines, leaders, hatching — lightest.
5. Hidden/above-the-cut — dashed; centrelines — chain-dashed.

## 4. Dimensioning rules

- MILLIMETRES, no unit suffix: 2400, not 2.4 m. (Levels in metres to
  3 dp on datums: +0.000, +2.700.)
- Three tiers of dimension line outside the plan: overall; wall-to-wall
  (structural openings/grid); openings (jamb-to-jamb with cill/head
  noted on the window schedule).
- Internal room dimensions inside the room; running dimensions from a
  fixed datum where setting-out matters.
- Never dimension to plaster: dimension to structure, note finishes.
- Room name + area (m²) in every room; floor level stated per storey.

## 5. Symbols (BS 8541-2 family)

- Doors: leaf drawn open at 90° + quarter-circle swing arc; the arc
  tells the builder handing and clearance. Sliding/pocket doors drawn
  in their track.
- Windows: three parallel lines in the wall (frame-glass-frame);
  operation (casement hinge point / sash) per the window schedule.
- Stairs: treads numbered with an UP arrow along the walking line,
  drawn cut at the plan level with the diagonal break line; the void
  above dashed on the upper plan.
- Radiators: outline rectangle on the wall face, labelled.
- Electrical (BS 8541 symbols): socket = circle with two parallel lines
  (twin), switch = circle with diagonal flick, consumer unit = boxed
  CU, smoke detector = circled SD, heat = HD, extract fan = circled
  fan blades with l/s rate.
- Section markers, drawing references, grid bubbles on structural grids.

## 6. The drawing SET (what an architect actually issues)

Planning set (Stage 3): location plan, block plan, existing + proposed
floor plans, existing + proposed elevations (all affected), at least
one section, roof plan, Design & Access statement where required.
Building Regulations / working set (Stage 4): everything above at 1:50
plus construction details, structural grid + engineer's drawings,
drainage plan, window/door schedules, finishes schedule, and the
services layouts — heating (radiator positions + sizes), ventilation
(fan positions + rates), electrical (socket/switch/CU positions) — the
three layers our pipeline now computes.

## 7. Audit — our generated plan vs the standard

Already right (viewer floor-plan mode, 2026-08-14): orthographic cut
(1.4 m), external walls heavier than internal, door swing arcs, window
triple-line symbol, stair treads + UP/DN with walking line, radiators
drawn from the sized design, extract fans with rates, room names +
areas + design loss, north point, per-storey plans.

Missing to reach issue-quality (build-phase work order):
1. Dimension lines — none drawn. Add the three outside tiers (overall,
   wall-to-wall, openings) + internal room dimensions, all in mm.
2. Title block, scale bar, drawing number/revision — none.
3. Above-the-cut dashed convention (stair void on first-floor plan is
   not dashed; rooflights would not show).
4. Electrical symbols on plan (sockets/switches/CU/SD are computed in
   electrics.py but only partially drawn — sockets and CU not yet).
5. Section line A-A on plan + a generated section drawing (we have the
   geometry; no section view exists).
6. Window/door schedules as a table (data exists in the model JSON).
7. Walking-line numbering on stair treads (1..13).
8. PDF sheet export at true 1:50/1:100 scale — the viewer is a screen;
   an architect issues sheets. drawing.py reads drawings; nothing yet
   WRITES one.
