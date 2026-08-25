# PRESERVE mode — the joint Fable5 + ox plan (2026-08-25)

Problem, measured on the Yaris XP130 three-row sheet: the premium chain outputs
a WORSE car than the raw Pixal3D input. Three mechanisms, all verified in the
files: materials_pass flattens to 0 textures (deletes the badge/plate/grille —
on a generated car the identity lives in the texture); the front/rear kits paste
placeholder primitives (Grille_Upper 356 faces, Number_Plate 2 faces) over a
detailed 324k-face nose; constructed glass panes under-reach their apertures.
Root cause: every construction stage runs unconditionally. The kits were
justified on MELT geometry; on a detailed car each one replaces information
with scaffolding.

Keep what the chain genuinely adds: component wheels, exact track/wheelbase,
ground contact, transparent named glass, validator 0 errors, mobile export.

ox's review (ox_review.md in the yaris_premium bucket prefix) found five
failures in the draft and redesigned the respray. All incorporated below —
the deltas are marked [ox].

## Material classes — the exception list is explicit [ox]

| class    | treatment |
|----------|-----------|
| body     | TEXTURED (preserve albedo), named `carpaint`, factor (1,1,1) |
| rim      | TEXTURED (the 2026-08-19 rule) |
| glass    | FLAT override — dark base, BLEND ~0.35, NO texture. The baked sky in the glazing texels would show through BLEND as milky grey [ox] |
| tyre     | FLAT dark rubber |
| interior | FLAT dark matte (worker forces transmission; noisy texture behind glass reads as crinkled silver) |

Texture #2's slot (albedo vs ORM) must be identified in Phase 0.5 and assigned,
not assumed [ox]. UV sanity (no degenerate/stretched islands) is a precondition
for preserve mode [ox].

## Respray: REBAKE PER VARIANT, never factor-multiply [ox — supersedes the draft]

baseColorFactor multiplies ALL carpaint texels: badge, plate and lamp decals
share the body's UV space, so a red respray turns chrome pink; baked AO shifts
the achieved colour off-spec; multiplication cannot exceed texel luminance
(fine from white, fatal generally). Instead: rasterise the carpaint CLASS MASK
(labels, not colour similarity) into UV space, recolour those pixels in the
albedo PNG, emit one cached variant GLB per colour, factor stays (1,1,1).
Decals stay bit-identical. This matches how the catalogue already serves 8
variant GLBs per car as separate files. recolour_audit --stamp is the exit
criterion of Phase 1, not a Phase 5 afterthought [ox].

## Phases

0.  Lock input renders/cameras BEFORE any mutation (Phase 5 diffs against
    them) [ox]. Rebuild the seg labels on pixal_yaris_raw.glb (the labelled
    input was deleted un-uploaded — process fix below). ~30 min CPU.
0.5 LABEL QA GATE [ox]: matID render + per-class coverage % + boundary overlay
    sheet. Nothing consumes labels that haven't passed the eye. A few percent
    of misprojected DLO boundary reproduces the torn-glass symptom through a
    different mechanism, so this gate is not optional.
1.  VERTICAL SLICE [ox reorder]: labels → preserve materials → stencil glass on
    the CAR's OWN glazing faces (constructed panes remain the melt path only)
    → ONE rebaked colour variant → served GLB → red control + recolour_audit.
    Proves the whole serving chain before any gate polish. Split spec: seam
    vertices duplicated at class boundaries need a weld/normal-transfer pass
    (normals_fix), asserted at this phase's exit.
2.  Stage gates, SEMANTIC not statistical [ox]: construct a class only where
    the labels show it ABSENT (or below a floor area) in its zone — lamp label
    present in the front band → skip the head kit. Deterministic and matches
    what the kits are for: hole-filling. Crease/texture-edge scores are logged
    evidence only; no threshold trusted until controls exceed n=2.
    NEGATIVE INVARIANT after any kit: zero occlusion of identity-class faces
    by kit geometry [ox] — catches the P2 failure regardless of trigger.
3.  wheel_stage as today, plus per-class texture assertions (body + rim albedo
    present and BYTE-IDENTICAL) at the exit of EVERY stage, not a global image
    count — glass/tyre legitimately drop textures, so a count check would
    either always fail or get waived [ox].
4.  Verdict: side-by-side against the Phase-0 locked renders. Defined fallback
    if input wins [ox]: ship raw + wheels/stance/glass-material only — the
    minimal net-positive subset — never the full chain. Owner's eye decides.
    No publish without sign-off.

## Process fixes

- Every stage artefact uploads to the bucket ON COMPLETION, enforced in the
  runner not by discipline — Phase 0 exists because polished_f34r.glb was
  deleted un-uploaded during a disk purge.
- Worker-rendered waves on a bright textured body: the recorded heuristic
  repaint bug fires on exactly this surface — file-level controls govern where
  posterUrl is null; RIM_FLAT-class protection defaults ON for worker renders.
