# MetaHuman Worker — What Was Built (Handoff)

A plain-language summary of the work, for a non-developer. The actual code lives
in this same `metahuman/` folder; this file just explains it.

---

## In one sentence

A new **RunPod serverless GPU worker** that takes **one photo of a person** and
returns a **3D model of them** (a `.glb` file) — built to plug into your app the
same way your existing 3D and video workers do.

---

## Why it exists

Your app ("Alam GPT") already has workers that each power one AI feature:

| Worker | What it does |
|--------|--------------|
| TripoSR | photo → 3D object |
| TRELLIS | photo/text → 3D object |
| Video (PR #12) | text/photo → video |
| **MetaHuman (this one)** | **photo → 3D human** |

This adds the "turn a photo of a person into a 3D avatar" feature.

---

## The files I added (all in `metahuman/`)

| File | What it is |
|------|-----------|
| `Dockerfile` | The recipe that builds the GPU image (installs the model + code) |
| `handler.py` | The worker logic: photo in → 3D model out |
| `gen_rect.py` | A helper that finds the person in the photo before making the 3D model |
| `README.md` | The technical detail, deployment notes, and known risks |
| `HANDOFF.md` | This file |
| `.github/workflows/metahuman-docker-build.yml` | Auto-builds the image when this reaches `main` |

All of it is **committed and pushed** to the branch `claude/meta-human-clone-uihgxq`.

---

## How to use it (the input/output)

**Send it:** a photo, as a URL or base64.

```json
{ "input": { "image_url": "https://example.com/person.jpg" } }
```

**Get back:** a 3D model as base64.

```json
{ "status": "success", "glb_b64": "<the 3D model>", "message": "GLB generated successfully" }
```

Same shape as your other workers, so the app calls it the same way.

---

## The model: PIFuHD (and an honest expectation)

I used **PIFuHD**, an open-source model from Facebook Research, because its files
download freely with no signup. The better-looking alternatives (ECON, SIFU)
require a manual license registration that can't be automated, which would break
your automatic builds.

**Set expectations:** PIFuHD makes a solid single 3D shape of the person. It is
**not** the same as Unreal Engine's "MetaHuman" (no movie-quality rig, hair, or
face animation). It's the open-source "photo → 3D human" that will actually
build and deploy on your setup.

---

## The one important caveat

I could **not test this on a real GPU** from where I work — there's no graphics
card in my environment. This is the exact same situation your previous developer
was in when the TRELLIS worker was first written (see the repo's PR history).

The real test is: build it, then run one job on RunPod. The `README.md` lists
the most likely first problems and how to fix each one, in order.

---

## What happens next (your steps)

1. **Get it onto `main`.** Once the code reaches your `main` branch, the build
   runs automatically and produces an image tagged
   `alamk123/ai-mechanic:metahuman-latest`. (I have NOT opened a pull request —
   tell me if you want me to.)
2. **Create the RunPod endpoint.** Make a new serverless endpoint pointing at
   that image. Any Ampere GPU works (e.g. AMPERE_48).
3. **Run one test job** with a person photo and confirm you get a `.glb` back.
4. **If it errors,** send me the error text from the job — the README tells me
   exactly where to look, and I fix it and push again.

---

## Status

- Code: **written, committed, pushed** to `claude/meta-human-clone-uihgxq`
- Build tested on a GPU: **not yet** (needs step 1–2 above)
- Pull request: **not opened** (waiting on you)
