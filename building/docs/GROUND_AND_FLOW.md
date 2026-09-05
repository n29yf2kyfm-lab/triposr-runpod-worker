# Ground and flow — soil, foundations, site, and how plans move

Learned from live web sources on 2026-08-14. Sources inline. This file
covers what sits UNDER the house (groundworks, soil, foundations), what
sits AROUND it (site/atmosphere), and how architects analyse the way
people MOVE through a plan — including the graph mathematics that lets
us code it.

---

## 1. Groundworks — the sequence a groundworker prices

- Strip topsoil and set out → reduce dig → foundation excavation →
  concrete → substructure masonry to dpc → drainage runs + service
  trenches (water 750 mm cover, electric 450–600, gas 375–600) →
  oversite (beam-and-block or ground-bearing slab on dpm + insulation)
  → backfill and external works.
- This is the least predictable cost in a build: access, spoil cartage,
  water table, obstructions, and SOIL decide it, not the drawing.

## 2. Soil — what the ground will carry

Sources: dbstructural.co.uk foundation types; abcivils.co.uk;
reinforcementproductsonline.co.uk; NHBC Standards chapter 4.
Presumed allowable bearing values (verify on site, BS 8004 territory):
- Rock: very high. Dense gravel/sand: 200–600 kN/m².
- Stiff clay: 100–200 kN/m². Firm clay: 75–100 kN/m².
- Soft clay/silt: < 75 kN/m² — engineered solution territory.
- Made ground/peat: no presumed value — investigate, pile or raft.
- A two-storey house wall drops roughly 30–50 kN/m along its strip; on
  100 kN/m² clay that is why 600–750 mm wide strips are the norm.
- Desk study first: BGS GeoIndex borehole viewer (free), coal authority
  report in the West Midlands (mining legacy), radon map, flood map.
  Then trial pits. Never price foundations off a postcode.
- Birmingham area note: commonly Mercia Mudstone Group and sandstones
  with glacial till pockets — treat as MODERATELY SHRINKABLE unless a
  soil report says otherwise, and check coal-mining risk on the east
  and north of the city. (Desk-study claim — verify per site with BGS.)

## 3. Foundations — choosing and depths

Sources: NHBC Standards 4.2/4.3 (nhbc-standards.co.uk); newbuild
inspections.com chapter summaries; dbstructural.co.uk.

- **Strip**: the default on decent ground; min 150 mm thick concrete,
  typically 600–750 wide for two storeys; NHBC minimum depth 750 mm on
  clay (frost/moisture), commonly 1.0 m in practice.
- **Trench fill**: same plan, filled to near ground level — swaps
  bricklaying below ground for concrete; usually cheaper overall and
  the small-builder default.
- **Raft**: spreads load on weak/variable ground or over mining legacy.
- **Piled (+ ground beams)**: soft ground, trees on shrinkable clay,
  or when depth to good ground > ~2.5 m (deep trenches beat piles on
  cost only while they're shallow and safe).
- **Trees on shrinkable clay (NHBC 4.2)**: foundation depth is set from
  charts by soil shrinkability (high/medium/low), tree water demand
  (species class) and the ratio of distance-to-tree to mature height.
  Within influence of a high-water-demand tree (oak, poplar, willow)
  depths of 1.5–3.0 m+ are routine; beyond that, pile. Heave protection
  (compressible board, void formers) on the inside faces where clay may
  swell back after tree removal. THE CHART GOVERNS — any single formula
  found online is a simplification; use NHBC 4.2 tables per job.
- Foundations acceptable in shrinkable soils: strip, trench fill,
  pier-and-beam, pile-and-beam, raft (NHBC 4.2.7).

## 4. Site and atmosphere — what surrounds the house

Sources: AD F Section 2 (read in full, 2026 PDF); AD O Appendix C;
National Design Guide (context/nature).

- **Orientation**: living spaces and main glazing to the sun path we
  now compute (solar engine, Birmingham 52.48°N); Part O caps the
  glazing appetite — especially west-facing (11% moderate risk).
- **Wind**: prevailing SW; porches/entrances sheltered from it; fences
  and planting as windbreaks on exposed plots.
- **Air quality (AD F Section 2)**: ventilation INTAKES away from the
  road/exhaust side on polluted sites; exhaust outlets placed so they
  don't re-enter intakes.
- **Overshadowing/daylight**: the 45° rule (horizontal and vertical
  from neighbouring windows) is the council officer's daylight test for
  extensions; keep new two-storey mass out of neighbours' 45° arcs.
- **Radon/contamination (AD C)**: radon map check; contaminated-land
  history for infill plots (former industry is common in Birmingham).

## 5. Flow planning — how architects study movement, and the maths

Sources: archisoup.com bubble-diagrams + adjacency-diagrams; mdpi.com
"Bill Hillier's Legacy — Space Syntax synopsis"; researchgate justified
plan graph theory; QGIS ssjgraph plugin docs; arxiv 2602.22507
space-syntax-guided floor plan generation; Cambridge automated
circulation generation paper.

The design process:
1. **Brief → adjacency matrix**: every pair of rooms scored
   (must-adjoin / should / neutral / must-separate).
2. **Bubble diagram**: rooms as bubbles sized by area, adjacency as
   links — topology before geometry.
3. **Plan**: geometry that honours the topology; circulation (hall,
   landing, corridor) is designed FIRST, not left over. (Our 3-bed was
   designed exactly this way after the 4-bed failure.)

The mathematics — space syntax (Hillier & Hanson 1984):
- Rooms = nodes; door/opening connections = edges → the plan is a graph.
- **Justified graph**: BFS from a root (usually the entrance); each
  room's DEPTH = steps from root. Draw levels bottom-up and a plan's
  social structure becomes visible (deep = private, shallow = public).
- **Connectivity** C_i = number of rooms directly connected to room i.
- **Mean depth** MD_i = (Σ shortest-path steps to every other room) /
  (k−1), k = room count.
- **Relative asymmetry / integration**:
  RA_i = 2(MD_i − 1)/(k − 2), 0 = maximally integrated (public heart),
  1 = maximally segregated (deepest privacy). Integration is usually
  reported as 1/RA (higher = more integrated).
- Tools: depthmapX (UCL, open source); QGIS ssjgraph plugin computes
  integration/mean depth/RA on plan graphs.
- Research state: space-syntax measures now guide generative floor-plan
  models (arxiv 2602.22507) and automated circulation generation
  (Cambridge AI EDAM 2025) — the metrics are objective enough to train
  against, i.e. definitely codeable.

Dwelling flow rules (bubble-diagram conventions, UK practice):
- Kitchen adjoins dining; dining adjoins living; kitchen near the
  entrance for shopping-in, with a service route not through living.
- WC off hall/circulation, never off living/kitchen directly (also our
  Part G-adjacent lobby conventions); never bedroom-through-bedroom.
- Stairs land centrally; landing serves all upstairs doors (our
  arrival check); bathroom central to bedrooms; master may take ensuite.
- Utility as mud-room on the garden/drive side; plant (boiler/cylinder)
  on the wet stack.
- Target justified-graph shape for a house: living/kitchen shallow
  (depth 1–2, integrated), bedrooms/baths deep (3+, segregated), no
  habitable room used as a through-route (tree-like beyond the hall).

---

## Work order this file creates

1. `flow.py`: build the room graph we already have in
   `buildable.circulation` into space-syntax metrics — connectivity,
   mean depth, RA/integration per room, justified-graph levels from the
   entrance — plus the adjacency rulebook (kitchen–dining, WC-off-hall,
   no through-bedrooms) as findings. Score every generated plan.
2. `groundworks.py`: foundation selector (soil class + trees + storeys
   → type, depth band, width, concrete m³) with NHBC-4.2-shaped inputs
   and honest "chart governs, verify on site" flags; feeds pricing.
3. Site pass in `planning.py`: orientation vs sun path, 45° daylight
   check to neighbour windows, intake-side note for busy roads.
4. Viewer plan mode: optional justified-graph overlay (depth-coloured
   rooms) — the flow picture an architect draws, computed live.
