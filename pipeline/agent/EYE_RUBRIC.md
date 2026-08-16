# Car-sheet eye-audit rubric (owner standard, distilled from CLAUDE.md 2026-07-27 → 2026-08-16)

You are auditing ONE four-view contact sheet of a 3D car model (front34, front34_L, side, rear34
tiles). Decide if this SOURCED asset is fit for a premium car catalogue. Judge the RENDER — the
file-level gates (glazing probe, pose, dupes) already ran; your job is what only eyes catch.

## Hard SCRAP (any one of these):
- EXPLODED / DETACHED PARTS: body floating above the floor, wheels sitting detached under the car,
  bonnet/doors/windscreen hovering open or separated, engine bay exposed with panels adrift.
- MISSING WHEELS: any corner with an empty arch (suspension visible, no wheel).
- TUNER/KIT CAR: giant aftermarket wing, roof box/scoop, widebody kit, visible intercooler through
  bumper, race livery/roll cage/racing number. OEM performance trims (OPC, GSi, VXR) are FINE.
- NON-ROAD VEHICLE: military truck, race-only car (DTM/BTCC), heavy plant, boats, parts/props.
- GAME-RIP QUALITY: visible triangle faceting across body panels, low-poly silhouette, melted or
  smeared details, baked-on texture seams, cartoon features (eyes/mouth).
- PAINTED GLAZING: windscreen/windows render as solid body colour (you cannot see through or into
  the cabin AND the glass area is the same colour/material as the body). Dark tinted glass is fine.
- BAKED TEXTURE MESS: body shows patchy mixed colours the studio respray obviously could not
  unify (e.g. black body with white patches).

## PASS looks like:
- proportions read as the right car instantly; strong front three-quarter
- roof, pillars, wheelbase consistent across all four tiles; wheels grounded and all present
- glazing reads as glass (interior or transparency visible); tyres read as dark rubber
- clean reflections, premium paint finish

## FLAG (report, do NOT scrap on it):
- PALE/WHITE TYRE on one corner while others are black: this is a KNOWN RENDER ARTEFACT
  (per-corner, proven on byte-identical materials). Flag "tyre-probe" — the glTF probe decides.
- WHITEWALL tyres (white sidewall ring, black tread in 3/4 views) on classics: authentic, PASS.
- Dark/carbon door or panel on an otherwise uniform body: flag "material-split" for recolour audit.
- Nose pointing the wrong way vs tile label (front34 shows the rear): flag "nose-flip" — fixed by
  a pose sidecar, not a defect.
- Anything you are genuinely unsure about: verdict UNSURE with the reason. UNSURE is routed to a
  human; it is NEVER treated as a scrap. When in doubt, UNSURE — a wrong SCRAP loses a good car.

## Output
Reply with ONLY a JSON object, no prose, no code fences:
{"verdict": "PASS" | "SCRAP" | "UNSURE", "reasons": ["short reason", ...], "flags": ["tyre-probe" | "material-split" | "nose-flip" | ...]}
