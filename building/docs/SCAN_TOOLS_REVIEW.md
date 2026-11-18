# The four tools from the video — searched, checked, decided

Reviewed 2026-11-18, against a request to "install this on my app".
Method: the search-first workflow — search this repo before the web,
judge on fit, upkeep, licence, safety and cost, and check what the
video claims against the source.

## The finding, in one line

**Three of the four were already in this repository, and the fourth
should not be installed.** The video recommends Gaussian splatting,
Microsoft TRELLIS, Blender camera-projection and Blender MCP. This
project already runs the first three, in a more rigorous form than the
video describes, and reached that position in `IMAGE_TO_3D.md` on
2026-08-14.

## Candidates

| Tool | Fit | Upkeep | Licence | Risk | Decision |
|---|---|---|---|---|---|
| Gaussian splatting | already built — `building/splat.py` | ours | gsplat Apache-2.0 | none new | **already installed** |
| Microsoft TRELLIS | already running — `trellis2/`, `trellis/` | ours | — | vehicle project, do not touch | **already installed** |
| Camera projection | already built, and better — `building/facade.py` | ours | ours | none | **already installed** |
| Blender MCP | interactive desktop tool, not a server | MIT, 34.9k★, pushed today | MIT | arbitrary code by design | **do not install** |

Verified by running them: `building/test_facade.py` and
`building/test_splat.py` — **54 passed, 0 failed**.

## 1. Gaussian splatting — built, and the licence trap already dodged

`building/splat.py` exists and its header records the check that
matters: **gsplat 1.5.3 is Apache-2.0** (Nerfstudio's reimplementation)
while **the original INRIA 3DGS is research-only and would be fatal to
a commercial product**. `plyfile` is GPL-3 and was rejected; the PLY
reader and writer are stdlib.

A video that says "free GitHub repo" is describing the code licence and
usually not the model or data licence. Here the distinction is the
difference between a shippable product and one that cannot be sold.

## 2. TRELLIS — already running, and it is the OTHER project

`trellis2/` serves the vehicle endpoints and is not to be disturbed.
More to the point, `IMAGE_TO_3D.md` §4 already evaluated TRELLIS 2,
Hunyuan3D and TripoSR and recorded the governing sentence:

> Every one of these tools turns pictures into APPEARANCE. Not one of
> them returns a dimension you may trust.

For a surveying product that is disqualifying on its own. TRELLIS from
one photo of a house invents the three facades the camera cannot see.
Installing it "for the building app" would add a second, unmeasured
geometry source next to a measured one, which is the exact confusion
this codebase is built to prevent.

## 3. Camera projection — ours is better than the video's

The video shows the standard Blender route: guess the camera with fSpy
or Perspective Plotter, then **Project From View** to drape the photo
over geometry. `facade.py` already does this and does not guess:

> fSpy exists to GUESS the camera because the modeller has no true
> dimensions. We do.

Four facade corners plus the measured width and height determine an
8-parameter **homography** outright — no camera estimate, no
perspective artefacts, no subdividing geometry to hide them. It returns
openings in **metres** (`opening_from_box`) and cross-checks against the
brick-course ruler in `scale.py` (`BRICK_COURSE = 75 mm`;
`check_brick_course`). The Blender manual's own caveat about projection
artefacts on coarse geometry does not apply, because there is no
perspective interpolation.

## 4. Blender MCP — the one to decline, and why it is not alarmism

`ahujasid/mcp-for-blender` (renamed from `blender-mcp`): MIT, 34,932
stars, 3,190 forks, last push 2026-11-18, 65 open issues. Genuinely
alive and genuinely popular. Two CVEs, stated fairly:

| CVE | Weakness | Severity | State |
|---|---|---|---|
| CVE-2026-10661 | injection via `input_image_url` | **low** (CVSS 4.3 / v4 2.1) | patched, `5b37be2` |
| CVE-2026-10662 | SSRF via `zip_file_url` | **low** (CVSS 6.3 / v4 2.1) | patched, `5b37be2` |

Both are low, both are patched, both have EPSS under 0.3%. They are not
the reason to decline. Issue #201 ("RCE via unsanitized `exec()` in
`execute_blender_code`") is likewise not really a defect: executing
Blender Python is the tool's whole purpose.

**The reason to decline is fit.** Blender MCP drives a *running Blender
GUI* through an addon so a person can say "change the scene" and watch
it happen. This app needs the opposite: a headless, deterministic,
testable render that produces the same image twice and can run on a
server with no display. That is `twin/blender.py`, which already renders
the measured model with Cycles, needs no key, no account and no network,
and is covered by nine tests.

Adding an interactive agent that can run arbitrary Python inside the
renderer would make the one output whose integrity is guaranteed by
construction — *the geometry cannot drift because nothing regenerates
it* — depend on what an LLM decided to type that day.

## The gap this review actually found

`building/facade.py` produces a rectified, scaled orthophoto of a real
facade. `twin/blender.py` renders the measured model with flat colours.
**Nothing connects them** — `twin/` does not import `facade` anywhere.

Joining them is the honest route to "a homeowner cannot tell it from a
photo" for an existing house, and it needs no new dependency:

1. `facade.rectify()` → orthophoto of the real elevation, in metres
2. UV-map it onto the matching wall of the Blender mesh
3. Cycles renders measured geometry wearing its own photograph

Every pixel is then either survey-derived geometry or a photograph of
the actual building. Nothing is generated, so nothing needs the
fidelity check in `twin/fidelity.py`, and the caption stays
**MEASURED GEOMETRY** rather than **ARTIST'S IMPRESSION**.

## What was not checked

- Blender MCP's addon source was not read line by line; the decision
  rests on fit, not on an audit.
- The video's star and repo counts were not reconciled; the figures
  above come from the GitHub API, not the video.
- `building/`'s own test suite beyond `test_facade` and `test_splat`
  was not run for this review.
