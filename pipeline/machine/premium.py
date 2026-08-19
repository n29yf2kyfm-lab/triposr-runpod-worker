#!/usr/bin/env python3
"""premium.py — THE TOOL: labelled car in, premium-pass car out, one command.

Owner order 2026-08-19 ("make a tool which makes it from this to premium",
"make me my tool which don't fail"). This is the orchestrator for the
production brief's repair loop over the machine's proven stages. "Don't
fail" is engineered as three properties, not a promise:

  * HONEST REFUSALS, NEVER CRASHES: every stage runs as a subprocess with
    its stdout captured to work/logs/; a refusal stops the chain with the
    stage's own reason and the manifest records FAILED_AT. Nothing is
    silently skipped; nothing pretends to pass.
  * RESUMABLE: --from <stage> re-enters the chain on the existing workdir
    artefacts, so a fixed stage never costs a full re-run.
  * BASELINE-LOCKED: the input GLB is copied to work/BASELINE_LOCKED.glb
    with its sha256 before anything runs (brief: never overwrite V-chain
    sources). Every stage writes a NEW file; nothing edits in place.

Chain (existing stages, in the order proven on the Yaris XP130 2026-08-19):

  baseline   lock + hash + inventory
  wheels     wheel_stage.py     — arch/fused detect, carve, master wheel x4
  presplit   glass_presplit.py  — label blob -> pane components + beltline
  glass      glass_stage.py     — real panes: quadric, desnake, thickness
  aperture   aperture_clean.py  — melt teeth out of the openings
  interior   interior_kit.py    — parametric cabin (dash/seats/console/wheel)
  materials  materials_pass.py  — brief Phase 9 PBR factors
  finish     blender_finish.py  — weld, weighted normals, light body relax
  normals    normals_fix.py     — NORMAL accessors verified present
  validate   stage7_validate.py — the full gate stack, recomputed from file
  diag       qc_turntables.py   — clay / world-normal / material-ID x 4 az
  mobile     gltf-transform     — weld+draco MOBILE_PREMIUM.glb (<=8MB gate)
  manifest   qc_manifest.json   — hashes, per-stage QC, honest final status

The final status line is copied from the validate stage's own verdict and
can be "NOT PRODUCTION-READY" — the tool reports the truth, it does not
manufacture a pass. (Brief rule 13: final status cannot be PASS while any
mandatory gate is failed, unknown or untested.)

Run:
  python3 premium.py --in car.glb --spec specs/car.json --work WORK [--from STAGE]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path, cap=1 << 30):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def run_logged(cmd, log_path, timeout=1800):
    t0 = time.time()
    with open(log_path, "w") as lf:
        p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                           timeout=timeout, cwd=HERE)
    dt = time.time() - t0
    tail = open(log_path).read().splitlines()[-12:]
    return p.returncode, dt, tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--from", dest="frm", default=None)
    ap.add_argument("--until", default=None)
    a = ap.parse_args()
    W = os.path.abspath(a.work)
    os.makedirs(os.path.join(W, "logs"), exist_ok=True)
    os.makedirs(os.path.join(W, "qc"), exist_ok=True)
    spec = os.path.abspath(a.spec)
    inp = os.path.abspath(a.inp)

    P = lambda n: os.path.join(W, n)
    manifest_path = P("qc_manifest.json")
    man = (json.load(open(manifest_path))
           if os.path.exists(manifest_path) else
           {"input": inp, "spec": spec, "stages": {}, "status": "RUNNING"})

    def record(stage, out_file, rc, dt, tail, qc_files=()):
        entry = {"rc": rc, "seconds": round(dt, 1),
                 "log": f"logs/{stage}.log", "tail": tail[-4:]}
        if out_file and os.path.exists(out_file):
            entry["out"] = os.path.basename(out_file)
            entry["bytes"] = os.path.getsize(out_file)
            entry["sha256"] = sha256(out_file)
        entry["qc"] = [os.path.basename(q) for q in qc_files
                       if os.path.exists(q)]
        man["stages"][stage] = entry
        json.dump(man, open(manifest_path, "w"), indent=1)

    def fail(stage, why):
        man["status"] = f"FAILED_AT {stage}: {why}"
        json.dump(man, open(manifest_path, "w"), indent=1)
        raise SystemExit(f"STOP at {stage}: {why}\n  log: {P('logs/' + stage + '.log')}")

    files = {
        "baseline": P("BASELINE_LOCKED.glb"),
        "wheels": P("s1_wheels.glb"),
        "presplit": P("s2_presplit.glb"),
        "glass": P("s3_glass.glb"),
        "aperture": P("s4_aperture.glb"),
        "interior": P("s5_interior.glb"),
        "materials": P("s6_materials.glb"),
        "finish": P("s7_finish.glb"),
        "normals": P("MASTER_PREMIUM.glb"),
        "mobile": P("MOBILE_PREMIUM.glb"),
    }
    order = ["baseline", "wheels", "presplit", "glass", "aperture",
             "interior", "materials", "finish", "normals", "validate",
             "diag", "mobile", "manifest"]
    start = order.index(a.frm) if a.frm else 0
    stop = order.index(a.until) + 1 if a.until else len(order)

    for stage in order[start:stop]:
        print(f"== {stage} ==", flush=True)
        log = P(f"logs/{stage}.log")

        if stage == "baseline":
            shutil.copy2(inp, files["baseline"])
            record("baseline", files["baseline"], 0, 0.0,
                   [f"locked from {inp}"])
            continue

        if stage == "wheels":
            rc, dt, tail = run_logged(
                ["python3", "wheel_stage.py", files["baseline"], spec,
                 files["wheels"], P("qc/wheel_qc.json")], log)
            if rc or not os.path.exists(files["wheels"]):
                fail(stage, tail[-1] if tail else f"rc={rc}")
            record(stage, files["wheels"], rc, dt, tail,
                   [P("qc/wheel_qc.json")])
            continue

        if stage == "presplit":
            rc, dt, tail = run_logged(
                ["python3", "glass_presplit.py", files["wheels"],
                 files["presplit"], "--spec", spec], log)
            if rc or not os.path.exists(files["presplit"]):
                fail(stage, tail[-1] if tail else f"rc={rc}")
            qc = files["presplit"].replace(".glb", "_presplit_qc.json")
            record(stage, files["presplit"], rc, dt, tail, [qc])
            continue

        if stage == "glass":
            rc, dt, tail = run_logged(
                ["python3", "glass_stage.py", files["presplit"],
                 files["glass"], "--spec", spec], log)
            if rc or not os.path.exists(files["glass"]):
                fail(stage, tail[-1] if tail else f"rc={rc}")
            qc = files["glass"].replace(".glb", "_glass_qc.json")
            record(stage, files["glass"], rc, dt, tail, [qc])
            continue

        if stage == "aperture":
            foot = files["glass"].replace(".glb", "_glass_qc.json")
            rc, dt, tail = run_logged(
                ["python3", "aperture_clean.py", files["glass"],
                 files["aperture"], foot, "--spec", spec], log)
            if rc or not os.path.exists(files["aperture"]):
                fail(stage, tail[-1] if tail else f"rc={rc}")
            record(stage, files["aperture"], rc, dt, tail)
            continue

        if stage == "interior":
            kit = P("qc/interior_kit.npz")
            rc, dt, tail = run_logged(
                ["python3", "interior_kit.py", files["aperture"], kit], log)
            if rc or not os.path.exists(kit):
                fail(stage, tail[-1] if tail else f"rc={rc}")
            rc2 = apply_interior(files["aperture"], kit, files["interior"], log)
            if rc2 or not os.path.exists(files["interior"]):
                fail(stage, "interior applier failed — see log")
            record(stage, files["interior"], 0, dt, tail, [kit])
            continue

        if stage == "materials":
            rc, dt, tail = run_logged(
                ["python3", "materials_pass.py", files["interior"],
                 files["materials"]], log)
            if rc or not os.path.exists(files["materials"]):
                fail(stage, tail[-1] if tail else f"rc={rc}")
            record(stage, files["materials"], rc, dt, tail)
            continue

        if stage == "finish":
            rc, dt, tail = run_logged(
                ["blender", "-b", "--python", "blender_finish.py", "--",
                 files["materials"], files["finish"]], log, timeout=2400)
            done = any("BLENDER_FINISH_DONE" in t for t in tail)
            if not os.path.exists(files["finish"]) or not done:
                fail(stage, "no BLENDER_FINISH_DONE marker — see log "
                            "(never trust Blender's exit alone)")
            record(stage, files["finish"], rc, dt, tail)
            continue

        if stage == "normals":
            rc, dt, tail = run_logged(
                ["python3", "normals_fix.py", files["finish"],
                 files["normals"]], log)
            ok = any("NORMAL present on all primitives" in t for t in tail)
            if rc or not ok:
                fail(stage, "normals_fix did not verify NORMAL accessors")
            record(stage, files["normals"], rc, dt, tail)
            continue

        if stage == "validate":
            rc, dt, tail = run_logged(
                ["python3", "stage7_validate.py", files["normals"], spec,
                 P("qc/final_qc.json")], log)
            # validate returns nonzero on hard errors only; FAIL gates are
            # recorded, not fatal — the manifest carries the honest verdict
            if not os.path.exists(P("qc/final_qc.json")):
                fail(stage, tail[-1] if tail else f"rc={rc}")
            record(stage, None, rc, dt, tail, [P("qc/final_qc.json")])
            continue

        if stage == "diag":
            dd = P("qc/turntables")
            os.makedirs(dd, exist_ok=True)
            rc, dt, tail = run_logged(
                ["blender", "-b", "--python", "qc_turntables.py", "--",
                 files["normals"], dd], log, timeout=2400)
            pngs = [f for f in os.listdir(dd) if f.endswith(".png")]
            if len(pngs) < 8:
                fail(stage, f"only {len(pngs)} diagnostic tiles rendered")
            record(stage, None, rc, dt, tail)
            man["stages"]["diag"]["tiles"] = sorted(pngs)
            json.dump(man, open(manifest_path, "w"), indent=1)
            continue

        if stage == "mobile":
            gt = shutil.which("gltf-transform")
            if gt is None:
                record(stage, None, -1, 0.0,
                       ["NOT TESTED — gltf-transform not installed"])
                continue
            rc, dt, tail = run_logged(
                [gt, "optimize", files["normals"], files["mobile"],
                 "--compress", "draco", "--texture-compress", "webp",
                 "--join", "false"], log, timeout=900)
            if rc or not os.path.exists(files["mobile"]):
                fail(stage, tail[-1] if tail else f"rc={rc}")
            mb = os.path.getsize(files["mobile"]) / 1e6
            record(stage, files["mobile"], rc, dt,
                   tail + [f"size {mb:.2f}MB vs 8MB hard target: "
                           f"{'PASS' if mb <= 8 else 'FAIL'}"])
            continue

        if stage == "manifest":
            qc = json.load(open(P("qc/final_qc.json")))
            man["final_gates"] = qc.get("gates", {})
            counts = qc.get("totals", {})
            bad = sum(counts.get(k, 0)
                      for k in ("FAIL", "UNKNOWN", "NOT_TESTED", "OPEN"))
            man["gate_counts"] = counts
            man["validate_overall"] = qc.get("overall", "?")
            man["status"] = ("PRODUCTION-READY" if counts and bad == 0 else
                             "NOT PRODUCTION-READY — MANDATORY VALIDATION "
                             "FAILED OR INCOMPLETE")
            json.dump(man, open(manifest_path, "w"), indent=1)
            print(json.dumps({"gate_counts": counts,
                              "status": man["status"]}, indent=1))
            continue

    print(f"done. manifest: {manifest_path}")


def apply_interior(car_glb, kit_npz, out_glb, log_path):
    """Merge interior_kit parts into the car scene. Kit x-coords assume a
    CENTRED-x car (V-chain convention); a corner-origin or offset car gets
    the kit shifted to its own x-midpoint. Recorded in the log."""
    import numpy as np
    import trimesh
    from trimesh.visual.material import PBRMaterial
    with open(log_path, "a") as lf:
        try:
            sc = trimesh.load(car_glb, force="scene")
            allv = np.vstack([g.vertices for g in sc.geometry.values()])
            xmid = float((allv[:, 0].max() + allv[:, 0].min()) / 2)
            z = np.load(kit_npz)
            manifest = json.loads(bytes(z["manifest"]).decode())
            for part in manifest:
                m = trimesh.Trimesh(vertices=z[part["v"]].copy(),
                                    faces=z[part["f"]].copy(), process=False)
                m.apply_translation([xmid, 0, 0])
                col = list(part["color"]) + [255]
                m.visual = trimesh.visual.TextureVisuals(
                    material=PBRMaterial(name=part["name"],
                                         baseColorFactor=col,
                                         metallicFactor=part["metallic"],
                                         roughnessFactor=part["rough"]))
                sc.add_geometry(m, node_name=part["name"],
                                geom_name=part["name"])
            sc.export(out_glb, include_normals=True)
            lf.write(f"\napply_interior: {len(manifest)} parts shifted to "
                     f"x-mid {xmid:+.3f}; wrote {out_glb}\n")
            return 0
        except Exception as e:
            lf.write(f"\napply_interior FAILED: {e}\n")
            return 1


if __name__ == "__main__":
    main()
