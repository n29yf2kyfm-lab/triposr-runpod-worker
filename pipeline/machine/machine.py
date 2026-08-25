#!/usr/bin/env python3
"""machine.py — the owner's photos->GLB machine, one command.

Chains every stage this project has proven, in the order the evidence
settled on (2026-08-16, the gseg Golf):

  geometry   Pixal3D on a RunPod A100 (see README.md — pod bootstrap, ~12min,
             ~$0.65/car). Manual/pod stage; everything after runs locally.
  canon      canon.py — camera-space -> length on X, Y up, grounded.
  seg        seg_views (Blender, 10 calibrated views + depth EXR)
             -> seg_masks (GroundingDINO + SAM, CPU)
             -> seg_project (z-buffer vote) -> seg_refine (symmetry).
  boundary   seg_boundary.py — per-window 2D stencils straighten the glass
             borders; stray glass smears die (glass becomes exhaustive).
  surface    surface_clean.py — bilateral NORMAL filtering (edge-preserving;
             NOT Taubin, which was measured to kill creases with the noise).
  assemble   seg_assemble.py — textured carpaint body, factor-transparent
             glass, quadrant tyre/rim split, lamp lens.
  gates      upload to staging -> glass_probe (clear/proven required,
             flat_shell + alpha_shell must be False).
  prod       production endpoint: 4 rubric views silver + blue control.
             THE CONTROL IS THE VERDICT — body shifts colour, glass and
             tyres must not. Then the eye (wave_agent EYE_RUBRIC), then the
             owner. Nothing ships without the owner's sign-off.

Run:
  python3 machine.py all   --canon car.glb --work WORKDIR --tag mytag
  python3 machine.py seg   --canon car.glb --work WORKDIR
  python3 machine.py finish --work WORKDIR --tag mytag     (boundary onward)

Requires: blender, torch+transformers (CPU ok), trimesh, scipy, OpenEXR.
Credentials via ~/.alam3d_env (SB_KEY, RUNPOD_API_KEY) — never in the repo.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRELLIS = os.path.join(HERE, "..", "trellis")
SB = "https://tfkvthprsntexrcuqpyd.supabase.co"


# THE MACHINE'S BLENDER STAGES ARE PINNED TO 4.5.x, DELIBERATELY.
#
# Blender 5.2 breaks seg_views.py in FIVE separate ways, found one at a time by
# running it:
#   1. `scene.node_tree` removed -> `scene.compositing_node_group`, a node group
#      that must be created and assigned
#   2. `CompositorNodeComposite` removed -> the group's own NodeGroupOutput
#   3. `CompositorNodeOutputFile.base_path` -> `.directory`
#   4. `.file_slots` -> `.file_output_items`
#   5. the file format enum no longer accepts 'OPEN_EXR', only
#      'OPEN_EXR_MULTILAYER' -- which would ALSO break seg_project's depth
#      reader, since it expects single-layer EXRs at a known filename
#
# The first four are shimmed in seg_views.py and cost nothing to keep. The fifth
# is not a shim, it is a port of the depth path, and a silently wrong depth
# buffer would poison every label this stage produces. This chain was proven on
# 4.x; it stays there until someone ports and RE-VALIDATES it against a known
# car. 5.2 remains the default for everything else via the shim.
BLENDER = os.environ.get("MACHINE_BLENDER",
                         "/opt/blender-4.5.12-linux-x64/blender")


def sh(cmd, **kw):
    if cmd and cmd[0] == "blender":
        env = dict(os.environ)
        if os.path.exists(BLENDER):
            env["BLENDER_BIN"] = BLENDER
        kw.setdefault("env", env)
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def stage_seg(canon, work):
    views = os.path.join(work, "views")
    sh(["blender", "-b", "--python", os.path.join(TRELLIS, "seg_views.py"),
        "--", canon, views])
    sh([sys.executable, os.path.join(TRELLIS, "seg_masks.py"), views])
    sh([sys.executable, os.path.join(TRELLIS, "seg_project.py"),
        canon, views, os.path.join(work, "car")])
    sh([sys.executable, os.path.join(TRELLIS, "seg_refine.py"),
        canon, os.path.join(work, "car_labels.npy"),
        os.path.join(work, "car_labels_r.npy")])


def stage_finish(canon, work):
    labels_b = os.path.join(work, "car_labels_b.npy")
    sh([sys.executable, os.path.join(HERE, "seg_boundary.py"),
        canon, os.path.join(work, "car_labels_r.npy"), labels_b])
    clean = os.path.join(work, "canon_clean.glb")
    sh([sys.executable, os.path.join(HERE, "surface_clean.py"), canon, clean])
    flat = os.path.join(work, "canon_flat.glb")
    sh([sys.executable, os.path.join(HERE, "glass_smooth.py"),
        clean, labels_b, flat])
    raw = os.path.join(work, "car_raw.glb")
    sh([sys.executable, os.path.join(TRELLIS, "seg_assemble.py"),
        flat, labels_b, raw])
    # NEVER ship without this: trimesh submesh exports drop vertex normals and
    # the car renders as crumpled foil (measured v6 -> v7)
    sh([sys.executable, os.path.join(HERE, "normals_fix.py"),
        raw, os.path.join(work, "car_final.glb")])


def stage_gates(work, tag):
    import urllib.request
    glb = os.path.join(work, "car_final.glb")
    key = os.environ["SB_KEY"]
    url = f"{SB}/storage/v1/object/car-meshes/staging/{tag}/car_final.glb"
    rq = urllib.request.Request(url, data=open(glb, "rb").read(), method="POST",
                                headers={"apikey": key,
                                         "Authorization": f"Bearer {key}",
                                         "Content-Type": "model/gltf-binary",
                                         "x-upsert": "true"})
    urllib.request.urlopen(rq, timeout=300)
    print("staged", url)
    sys.path.insert(0, os.path.join(HERE, "..", "ingest"))
    import glass_probe as gp
    r = gp.probe("car_final", stage=f"staging/{tag}")
    verdict = (r.get("verdict"), r.get("certainty"),
               r.get("flat_shell"), r.get("alpha_shell"))
    print("glass_probe:", verdict)
    ok = (r.get("verdict") == "clear" and r.get("certainty") == "proven"
          and not r.get("flat_shell") and not r.get("alpha_shell"))
    if not ok:
        raise SystemExit(f"GATES FAILED: {verdict} — do not render, fix first")
    print("GATES PASS — next: production renders + blue control + eye + OWNER")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["all", "seg", "finish", "gates"])
    ap.add_argument("--canon", help="canonicalised GLB (from canon.py)")
    ap.add_argument("--work", required=True)
    ap.add_argument("--tag", default="machine")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    if a.cmd in ("all", "seg"):
        stage_seg(a.canon, a.work)
    if a.cmd in ("all", "finish"):
        stage_finish(a.canon, a.work)
    if a.cmd in ("all", "gates"):
        stage_gates(a.work, a.tag)
