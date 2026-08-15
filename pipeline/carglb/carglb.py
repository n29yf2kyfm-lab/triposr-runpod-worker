#!/usr/bin/env python3
"""car-glb — one command: a folder of photos in, a gate-passing GLB out.

The orchestrator planned in pipeline/trellis/IMAGE_TO_GLB_PLAN.md. It invents
NOTHING: every stage is a tool this repo has already built and tested, wired
in the order build_car.py proved. What it adds is the discipline around them —
capture gating before any GPU money is spent, artefact-asserted pod runs,
fatal gates, and QC renders written next to the output.

    python3 pipeline/carglb/carglb.py check    <folder>       # free, no GPU
    python3 pipeline/carglb/carglb.py generate <folder> -o car.glb
    python3 pipeline/carglb/carglb.py gates    <some.glb>     # gates only

FOLDER CONTRACT (same as the owner's demo README):
    dims.json          REQUIRED - published mm; pixels never set scale
    front.png rear.png REQUIRED - background-removed RGBA
    left.png right.png recommended (4-view generation)
    f34.png            optional  (structure stage conditioning)

HONESTY CONTRACT (IMAGE_TO_GLB_PLAN §0/§4, do not delete):
    output is gap-filler tier. No shut lines, badges or premium panel language
    — measured to be below the representable bandwidth of every open
    generator. Output lands in staging; NOTHING ships without the owner's
    per-car sign-off.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "ingest"))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "trellis"))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "authoring"))

SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
STAGING = "car-meshes/staging/carglb"
REQUIRED_VIEWS = ("front", "rear")
GOOD_VIEWS = ("front", "rear", "left", "right")
MIN_PIXELS = 0.5e6          # half the demo README's 1MP floor: warn, don't block
MIN_ALPHA_FRAC = 0.08       # a cutout with less car than this is a bad mask


class CaptureError(SystemExit):
    pass


# --------------------------------------------------------------- A. capture
def check_captures(folder, strict=True):
    """The gate that runs BEFORE any GPU money. Returns the manifest."""
    from PIL import Image
    import numpy as np

    dims_path = os.path.join(folder, "dims.json")
    if not os.path.exists(dims_path):
        raise CaptureError(f"{folder}/dims.json missing — published dimensions "
                           "are required; this pipeline never estimates size "
                           "from pixels")
    dims = json.load(open(dims_path))
    for k in ("name", "length", "width", "height", "wheelbase"):
        if k not in dims:
            raise CaptureError(f"dims.json missing '{k}'")

    manifest = {"dims": dims, "views": {}, "warnings": []}
    for view in GOOD_VIEWS + ("f34",):
        p = os.path.join(folder, f"{view}.png")
        if not os.path.exists(p):
            if view in REQUIRED_VIEWS:
                raise CaptureError(f"required view missing: {view}.png")
            manifest["warnings"].append(f"view missing: {view}.png")
            continue
        im = Image.open(p)
        if im.mode != "RGBA":
            raise CaptureError(f"{view}.png is {im.mode}, need RGBA cutout — "
                               "background junk becomes mesh spikes (measured)")
        a = np.asarray(im)[:, :, 3]
        frac = float((a > 24).mean())
        if frac < MIN_ALPHA_FRAC:
            raise CaptureError(f"{view}.png: only {frac:.0%} of the frame is "
                               "car — bad mask, refusing")
        mp = im.width * im.height / 1e6
        if mp * frac < MIN_PIXELS / 1e6:
            manifest["warnings"].append(f"{view}.png is low resolution "
                                        f"({mp:.2f}MP, car {frac:.0%})")
        manifest["views"][view] = {"px": [im.width, im.height],
                                  "car_frac": round(frac, 3)}
    n = len([v for v in manifest["views"] if v in GOOD_VIEWS])
    if n < 4:
        manifest["warnings"].append(
            f"only {n} of 4 principal views — generation quality drops; "
            "Vizcom's own contract wants consistent views of all sides")
    if strict and manifest["warnings"]:
        print("capture warnings:")
        for w in manifest["warnings"]:
            print("  -", w)
    return manifest


# ----------------------------------------------------------------- B. shape
def run_shape_pod(folder, manifest, out_dir, timeout_s=5400):
    """Submit the shape+structure job to a RunPod box via the hardened
    bootstrap pattern, wait on ARTEFACTS (never desiredStatus), pull results.

    The bootstrap itself is pipeline/carglb/shape_boot.sh — the proven
    Hunyuan-2mv recipe. Requires SB_KEY/RUNPOD_API_KEY/HF_TOKEN in env
    (source /root/.alam3d_env).
    """
    import urllib.request

    key = os.environ.get("RUNPOD_API_KEY")
    sb_key = os.environ.get("SB_KEY")
    if not (key and sb_key):
        raise SystemExit("RUNPOD_API_KEY / SB_KEY not in env — "
                         "source /root/.alam3d_env")
    job = manifest["dims"]["name"].lower().replace(" ", "-")
    pre = f"{STAGING}/{job}"

    def put(local, remote):
        req = urllib.request.Request(
            f"{SB}/{pre}/{remote}", data=open(local, "rb").read(), method="POST",
            headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                     "x-upsert": "true",
                     "Content-Type": "application/octet-stream"})
        urllib.request.urlopen(req, timeout=120)

    for view in manifest["views"]:
        put(os.path.join(folder, f"{view}.png"), f"{view}.png")
    boot = os.path.join(HERE, "shape_boot.sh")
    put(boot, "shape_boot.sh")
    # RESET the job log before launching: the monitor reads the log's last
    # marker, and a stale FAIL from a previous attempt killed a healthy fresh
    # pod at t=0 (measured). The pod's first report overwrites this.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        tmplog = tf.name
    put(tmplog, "shape_log.txt")
    os.unlink(tmplog)
    # preflight the bootstrap URL BEFORE renting a GPU (the sed-URL lesson)
    url = f"{SB}/public/{pre}/shape_boot.sh"
    if urllib.request.urlopen(url, timeout=30).status != 200:
        raise SystemExit("bootstrap preflight failed")

    body = {
        "name": f"carglb-{job}"[:60],
        "imageName": "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
        "gpuTypeIds": ["NVIDIA GeForce RTX 4090", "NVIDIA RTX A6000",
                       "NVIDIA A40", "NVIDIA RTX A5000"],
        "gpuTypePriority": "availability",
        "gpuCount": 1, "containerDiskInGb": 60, "volumeInGb": 0,
        "cloudType": "SECURE",
        "dockerStartCmd": ["bash", "-c",
                           f"export CARGLB_JOB={job}; "
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; "
                           "sleep infinity"],
        "env": {"SB_KEY": sb_key, "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
                "HUGGING_FACE_HUB_TOKEN": os.environ.get("HF_TOKEN", ""),
                "HF_HOME": "/workspace/hf", "CARGLB_JOB": job},
    }
    req = urllib.request.Request(
        "https://rest.runpod.io/v1/pods", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    pod = json.load(urllib.request.urlopen(req, timeout=60))
    pod_id = pod.get("id")
    if not pod_id:
        raise SystemExit(f"pod launch failed: {pod}")
    print(f"shape pod {pod_id} launched; waiting on artefacts")

    log_url = f"{SB}/public/{pre}/shape_log.txt"
    t0, last = time.time(), ""
    ok = False
    try:
        while time.time() - t0 < timeout_s:
            try:
                log = urllib.request.urlopen(
                    f"{log_url}?cb={int(time.time())}", timeout=30).read().decode(
                    "utf-8", "replace")
                lines = [l for l in log.splitlines() if l.startswith("=== ")]
                if lines and lines[-1] != last:
                    last = lines[-1]
                    print(f"  [{int(time.time()-t0)}s] {last}")
                if "ALL_OK" in last:
                    ok = True
                    break
                if "FAIL" in last:
                    break
            except Exception:
                pass
            time.sleep(45)
    finally:
        # terminate either way, and VERIFY the termination
        req = urllib.request.Request(f"https://rest.runpod.io/v1/pods/{pod_id}",
                                     method="DELETE",
                                     headers={"Authorization": f"Bearer {key}"})
        try:
            urllib.request.urlopen(req, timeout=60)
        except Exception as e:                                   # noqa: BLE001
            print(f"POD DELETE FAILED — kill {pod_id} by hand: {e}")
    if not ok:
        raise SystemExit(f"shape stage did not reach ALL_OK (last: {last}) — "
                         f"log: {log_url}")
    os.makedirs(out_dir, exist_ok=True)
    got = {}
    for f in ("shape.glb", "parts.glb", "nparts.txt"):
        try:
            data = urllib.request.urlopen(f"{SB}/public/{pre}/{f}",
                                          timeout=300).read()
            open(os.path.join(out_dir, f), "wb").write(data)
            got[f] = len(data)
        except Exception:
            got[f] = None
    # size-cap fallback: object.glb may bounce off the bucket's per-file cap;
    # the pod also uploads each part_NN.glb, which we merge locally
    if not got.get("parts.glb") and got.get("nparts.txt"):
        import trimesh
        n = int(open(os.path.join(out_dir, "nparts.txt")).read().strip())
        scene = trimesh.Scene()
        pulled = 0
        for i in range(n):
            fn = f"part_{i:02}.glb"
            try:
                data = urllib.request.urlopen(f"{SB}/public/{pre}/{fn}",
                                              timeout=300).read()
                lp = os.path.join(out_dir, fn)
                open(lp, "wb").write(data)
                part = trimesh.load(lp, force="mesh")
                scene.add_geometry(part, node_name=f"part_{i:02}",
                                   geom_name=f"part_{i:02}")
                pulled += 1
            except Exception as e:                               # noqa: BLE001
                print(f"  part {fn} failed: {e}")
        if pulled:
            merged = os.path.join(out_dir, "parts.glb")
            scene.export(merged)
            got["parts.glb"] = os.path.getsize(merged)
            print(f"merged {pulled}/{n} parts locally")
    print("pulled:", got)
    if not got.get("shape.glb"):
        raise SystemExit("shape.glb missing from bucket after ALL_OK")
    return os.path.join(out_dir, "shape.glb"), (
        os.path.join(out_dir, "parts.glb") if got.get("parts.glb") else None)


# ------------------------------------------------------- E-G. local pipeline
def ensure_donor():
    donor = os.path.join(ROOT, "pipeline", "trellis", "donor_wheel.glb")
    if not os.path.exists(donor):
        # the 12MB donor binary lives in the bucket, not in git — fetch the
        # catalogue GR Supra and decompress it (wheel_swap needs raw geometry;
        # Draco donors import as placeholder zeros, the paid-for trap)
        import urllib.request
        src = (SB + "/public/car-meshes/finished/toyota/toyota-gr-supra-v1.glb")
        tmp = donor + ".draco"
        open(tmp, "wb").write(urllib.request.urlopen(src, timeout=300).read())
        r = subprocess.run(["gltf-transform", "copy", tmp, donor],
                           capture_output=True, text=True)
        os.unlink(tmp)
        if r.returncode != 0 or not os.path.exists(donor):
            raise SystemExit(f"donor fetch/decompress failed: {r.stderr[-300:]}")
        print("wheel donor fetched from catalogue")
    return donor


def run_local(shape_glb, parts_glb, dims, out_glb, renders_dir=None,
              photos_dir=None):
    """Panes + wheels + gates. Two paths, tried in evidence order.

    A) OPEN-GLAZING path (Hi3DGen's mode, measured 2026-08-15): fit_panes
       constructs the glazing from the apertures and needs NO parts GLB. Its
       hollow-cabin guard refuses fused shells (largest side aperture 139px
       vs 1508px on a real one), so trying it first is safe.
    B) FUSED-SHELL fallback: build_car.py's hybrid chain, which needs the
       PartCrafter parts to label glazing.
    Then wheel_swap puts catalogue donor wheels on either result, and if the
    capture photos are to hand, photo_project bakes them on as the HERO
    variant (identity: grille/badges/lamps live in texture at viewer scale).
    """
    donor = ensure_donor()
    paned = out_glb + ".paned.glb"
    cmd = [sys.executable,
           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fit_panes.py"),
           shape_glb, paned, str(dims["length"] / 1000.0)]
    print("$", " ".join(cmd))
    p = subprocess.run(cmd)
    if p.returncode == 0:
        cmd = [sys.executable, os.path.join(ROOT, "pipeline", "trellis",
                                            "wheel_swap.py"),
               "--car", paned, "--donor", donor, "--out", out_glb]
        print("$", " ".join(cmd))
        p = subprocess.run(cmd)
        if p.returncode != 0:
            raise SystemExit(f"wheel_swap failed ({p.returncode}) — the car "
                             "is NOT shippable")
        os.unlink(paned)
    else:
        print("fit_panes refused — falling back to the fused-shell chain")
        if parts_glb is None:
            raise SystemExit(
                "no parts GLB — a fused shell needs the structure stage to "
                "label glazing (P3-SAM measurably cannot cut glazing out of "
                "one). Re-run the pod stage.")
        cmd = [sys.executable, os.path.join(ROOT, "pipeline", "trellis",
                                            "build_car.py"),
               "--parts", parts_glb, "--mesh", shape_glb, "--out", out_glb,
               "--donor", donor]
        if renders_dir:
            cmd += ["--renders", renders_dir]
        print("$", " ".join(cmd))
        p = subprocess.run(cmd)
        if p.returncode != 0:
            raise SystemExit(f"build_car gates failed ({p.returncode}) — the "
                             "car is NOT shippable; read the gate output above")
    outputs = [out_glb]
    if photos_dir:
        hero = out_glb.replace(".glb", "_hero.glb")
        cmd = [sys.executable,
               os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "photo_project.py"), out_glb, photos_dir, hero]
        print("$", " ".join(cmd))
        if subprocess.run(cmd).returncode == 0:
            print(f"hero (photo-textured) variant: {hero}")
            outputs.append(hero)
        else:
            print("photo bake failed — flat build stands alone")
    # LAST step: rotate to the catalogue axis convention (length Z, nose -Z)
    # so the studio rig's absolute azimuths land the same tiles as every
    # shipped car. Internal tools all assume the authoring frame, which is
    # why this must stay last.
    for f in outputs:
        cmd = [sys.executable,
               os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "orient_catalogue.py"), f, f]
        p = subprocess.run(cmd)
        if p.returncode != 0:
            raise SystemExit(f"orient_catalogue failed on {f}")
    return out_glb


# ----------------------------------------------------------------- H. QC out
def qc(out_glb, renders_dir):
    os.makedirs(renders_dir, exist_ok=True)
    env = dict(os.environ,
               HDRI_PATH=os.path.join(ROOT, "render", "assets", "hdri.hdr"))
    for az in (35, 215):
        png = os.path.join(renders_dir, f"qc_{az}.png")
        subprocess.run(["xvfb-run", "-a", "blender", "-b", "--factory-startup",
                        "-noaudio", "-P",
                        os.path.join(ROOT, "pipeline", "qc", "prod_render.py"),
                        "--", os.path.join(ROOT, "render", "handler.py"),
                        out_glb, png, str(az), "40"], env=env,
                       capture_output=True)
    fr = subprocess.run([sys.executable,
                         os.path.join(ROOT, "pipeline", "qc",
                                      "mesh_forensics.py"), out_glb],
                        capture_output=True, text=True)
    report = os.path.join(renders_dir, "forensics.txt")
    open(report, "w").write(fr.stdout)
    print(fr.stdout.splitlines()[1] if fr.stdout else "forensics failed")
    print(f"QC written to {renders_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["check", "generate", "gates"])
    ap.add_argument("target")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    if a.cmd == "check":
        m = check_captures(a.target)
        print(json.dumps(m, indent=1))
        return

    if a.cmd == "gates":
        from build_car import materials, EXPECTED_MATS          # noqa: F401
        import glass_probe as gp
        import json as _json, struct
        raw = open(a.target, "rb").read()
        ln = struct.unpack("<I", raw[12:16])[0]
        gp.gltf_json = lambda url: _json.loads(raw[20:20 + ln])
        r = gp.probe(os.path.basename(a.target), url="local")
        print("glass:", r["verdict"], "/", r["certainty"],
              "| flat_shell:", r["flat_shell"],
              "| alpha_shell:", r["alpha_shell"])
        have = set(materials(a.target))
        print("materials:", sorted(have))
        missing = EXPECTED_MATS - have
        if missing:
            raise SystemExit(f"GATE FAIL: missing materials {sorted(missing)}")
        if r["verdict"] == "opaque" and r["certainty"] == "proven":
            raise SystemExit("GATE FAIL: glazing opaque (proven) — owner "
                             "ruling 2026-08-11: hard fail")
        return

    folder = a.target
    manifest = check_captures(folder)
    out = a.out or os.path.join(folder,
                                manifest["dims"]["name"].lower() + ".glb")
    work = os.path.join(folder, "work")
    shape, parts = run_shape_pod(folder, manifest, work)
    run_local(shape, parts, manifest["dims"], out,
              renders_dir=os.path.join(folder, "qc"), photos_dir=folder)
    qc(out, os.path.join(folder, "qc"))
    print(f"\nDONE: {out}")
    print("staging only — nothing ships without the owner's sign-off.")


if __name__ == "__main__":
    main()
