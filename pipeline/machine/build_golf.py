#!/usr/bin/env python3
"""build_golf.py — ONE car carrying all six gates, from ONE re-runnable pipeline.

Six gates each repaired their own zone of the Golf test bed on their own copy and
were never combined.  This does NOT diff or stitch their six output files.  It
REPLAYS each gate's OPERATIONS, in order, onto one base, so the result has one
material table, one node graph and one provenance chain.

    BASE  car-meshes/staging/gate78/car_rebound.glb
          sha256 5380761c…c88e0 · 28,703,944 B · 30 nodes · 985,227 faces
          (Gate 7+8's material rebind: glazing clear/proven, black tyres,
           respray holds, validator clean.)

STAGE ORDER, and the reason for it
----------------------------------
 1  glass   LABEL-ONLY.  Grows `Glass_Windscreen` from 0.1622 m² across the
            fitted screen surface, evicts spill, culls debris, re-assigns panes
            geometrically.  Runs FIRST because its X landmarks are WORLD-space
            and were calibrated in the base's own (nose-up) pose — the glass
            gate itself recorded that a stale beltline constant evicted 31% of
            the glazing when the same tool was run on the grounded copy.
 2  front   STRIP then REBUILD (gate3v7).  Deletion moves no vertex, which is
            what makes it safe when 25,369 `carpaint` vertices are exactly
            coincident with `interior` vertices.
 3  rear    REPLAY of rear v2 onto THIS lineage (see THE HARD JOIN below).
 4  cabin   Aperture open (delete fragments + the blocking interior skin) then
            the parametric cabin kit.  Runs AFTER front and rear because both
            of those iterate every node and cut anything inside their footprint
            — a parcel shelf built first would be cut by the rear strip.
 5  skin    LABEL-ONLY.  Absorbs the speckled Body_Shell/Interior partition.
            Runs LAST of the label ops, NOT first: it writes a SECOND PRIMITIVE
            onto existing meshes, and trimesh then loads those as `Body_Shell`,
            `Body_Shell_1`, `Body_Shell_2`…  Measured — every downstream stage
            that reads `sc.graph["Body_Shell"]` would silently see 171,314 of
            190,385 faces, and `cabin/assemble.py` asserts one primitive per
            mesh.  It is provably topology-preserving (face count, area to 9 dp
            and the triangle multiset are unchanged), so it composes anywhere;
            here is the only place it composes SAFELY.
 6  pose    The merge operator's grounding, LAST, so everything upstream is
            built in one consistent pose.  One rigid 4.730° rotation for the
            body, each wheel placed separately.
 7  finish  Material extensions restored, duplicate material names merged,
            NORMAL asserted on the WRITTEN file, Khronos validator.
 8  mobile  Draco export.
 9  sheet   Eight views for the owner's eye.

THE HARD JOIN — stated, with the risk accepted
----------------------------------------------
Rear v2 was built on Gate 4's `rear_v3.glb`, not on this lineage.  I REPLAY its
operations here rather than transplanting its components.  The decision was made
on a measurement, not a preference:

  * the two files are THE SAME CAR IN THE SAME WORLD FRAME — identical bbox
    minimum, identical height, and a tail profile agreeing to under 2 mm at
    every height sampled from y 0.225 to y 1.375 (the 16.8 mm at y=0.375 and
    4.4 mm at y=0.875 are Gate 4's own constructed plate and lamp solids
    standing proud of the skin).  So rear v2's world-space band constants
    transfer directly and did not have to be re-derived.
  * TRANSPLANTING was rejected because `rear_v3` carries Gate 4's material
    table — `extensionsUsed: null`, i.e. no transmission, no IOR, no clearcoat
    at all, and a textured `carpaint` at metallic 1.0 — and has NO per-corner
    wheel nodes, only single `Rim_Alloy` / `Tyre_Rubber` nodes.  `merge_op`
    refuses that file outright (it needs `Wheel_{FL,FR,RL,RR}_*`), so a
    transplant would have had to carry Gate 4's materials into this car's table
    or rebind four constructed lamp solids by hand.
  * WHAT I WOULD HAVE SEEN IF THIS WERE THE WRONG CALL: the replayed panels
    would not have landed on the car — the fitted surface would sit tens of
    millimetres off the measured skin, the strip footprint would cut geometry
    the new panels do not cover, and the hole test would find open rays through
    the tail.  All three are measured on the output, not assumed.
  * WHAT IS NOT CARRIED: Gate 4's four constructed tail-lamp solids do not
    exist on this lineage, so rear v2's acceptance criterion 4 (lamps intact
    through a respray) is Gate 4's win, not rear v2's, and is not claimed.  The
    rear v2 win claimed here is the one in the merge brief's table: rebuilt
    hatch/bumper waviness against the melt, and hidden melt under the new skin.

RESUMABILITY
------------
Every stage writes `work/<stage>.glb` and `receipts/<stage>.json`.  A stage is
skipped when its receipt records the same INPUT sha and its output file still
hashes to the recorded sha — so a re-run after a container rollback resumes,
and a changed upstream stage correctly invalidates everything after it.

Run:
    python3 pipeline/machine/build_golf.py --root <workdir>
    python3 pipeline/machine/build_golf.py --root <workdir> --from rear
    python3 pipeline/machine/build_golf.py --root <workdir> --only glass
    python3 pipeline/machine/build_golf.py --root <workdir> --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "buildstages"))

import gates                                                     # noqa: E402
import glbmeas                                                   # noqa: E402
import render as RR                                              # noqa: E402

BASE_SHA = "5380761c01dded53b286fafec22255237042d7d2effcd1192e79f10f374c88e0"
BASE_KEY = "staging/gate78/car_rebound.glb"
BUCKET = "car-meshes"

STAGE_ORDER = ["base", "glass", "front", "rear", "cabin", "skin", "pose",
               "finish", "mobile", "sheet"]


# --------------------------------------------------------------------- utils
def run(cmd, cwd=None, env=None, log=None, check=True, timeout=7200):
    e = dict(os.environ)
    if env:
        e.update(env)
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True,
                       timeout=timeout)
    out = r.stdout + r.stderr
    if log:
        with open(log, "a") as fh:
            fh.write(f"\n$ {' '.join(str(c) for c in cmd)}\n(cwd={cwd})\n{out}\n"
                     f"[rc={r.returncode} {time.time()-t0:.1f}s]\n")
    if check and r.returncode != 0:
        raise SystemExit(f"COMMAND FAILED rc={r.returncode}: {' '.join(str(c) for c in cmd)}\n"
                         f"{out[-4000:]}")
    return r.returncode, out


def sb_get(key, dst):
    import urllib.request
    k = os.environ["SB_KEY"]
    url = f"https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/{BUCKET}/{key}"
    req = urllib.request.Request(url, headers={"apikey": k, "Authorization": f"Bearer {k}"})
    with urllib.request.urlopen(req) as f, open(dst, "wb") as o:
        shutil.copyfileobj(f, o)
    return dst


class Ctx:
    def __init__(self, root, args):
        self.root = os.path.abspath(root)
        self.args = args
        for d in ("in", "work", "ev", "logs", "receipts", "stage"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        self.ref = None                    # the base measurement, for retention

    def p(self, *a):
        return os.path.join(self.root, *a)

    def log(self, stage):
        return self.p("logs", f"{stage}.log")

    def sw(self, stage):
        d = self.p("stage", stage)
        os.makedirs(d, exist_ok=True)
        return d


# -------------------------------------------------------------------- stages
def stage_base(ctx, _inp):
    """Fetch and VERIFY the base.  A wrong base silently invalidates everything."""
    out = ctx.p("in", "car_rebound.glb")
    if not os.path.exists(out):
        sb_get(BASE_KEY, out)
    got = glbmeas.sha256(out)
    if got != BASE_SHA:
        raise SystemExit(f"REFUSED: base sha {got} != expected {BASE_SHA}")
    return out


def stage_glass(ctx, inp):
    """Gate GLASS — label-only windscreen stamp + spill eviction + pane split."""
    w = ctx.sw("glass")
    lg = ctx.log("glass")
    raw = os.path.join(w, "glass_raw.glb")
    out = ctx.p("work", "glass.glb")
    run([sys.executable, os.path.join(_HERE, "glass", "glass_repair.py"), inp, raw,
         "--report", os.path.join(w, "repair.json")], log=lg)
    # glass_repair writes through trimesh, which drops every KHR material
    # extension.  finish.py restores them BY NAME from the base and asserts
    # NORMAL on the WRITTEN file.
    run([sys.executable, os.path.join(_HERE, "gate3v7", "finish.py"), raw,
         ctx.p("in", "car_rebound.glb"), out, os.path.join(w, "finish.json")],
        log=lg, check=False)
    if not os.path.exists(out):
        raise SystemExit("glass stage: finish.py produced no output")
    os.remove(raw)
    return out


def stage_front(ctx, inp):
    """Gate 3 v7 — strip the melted front fascia, rebuild 20 components."""
    w = ctx.sw("front")
    lg = ctx.log("front")
    G = os.path.join(_HERE, "gate3v7")
    survey = os.path.join(w, "survey.json")
    ftex = os.path.join(w, "ftex.npz")
    plan = os.path.join(w, "plan.json")
    stripped = os.path.join(w, "stripped.glb")
    rebuilt = os.path.join(w, "rebuilt.glb")
    out = ctx.p("work", "front.glb")
    run([sys.executable, os.path.join(G, "survey.py"), inp, survey], log=lg)
    run([sys.executable, os.path.join(G, "front_tex.py"), inp, survey, ftex], log=lg)
    run([sys.executable, os.path.join(G, "plan7.py"), ftex, survey, plan, inp], log=lg)
    run([sys.executable, os.path.join(G, "strip.py"), inp, ftex, plan, stripped,
         os.path.join(w, "strip.json")], log=lg)
    run([sys.executable, os.path.join(G, "rebuild7.py"), stripped, ftex, plan, rebuilt,
         os.path.join(w, "rebuild.json")], log=lg)
    run([sys.executable, os.path.join(G, "finish.py"), rebuilt,
         ctx.p("in", "car_rebound.glb"), out, os.path.join(w, "finish.json")],
        log=lg, check=False)
    if not os.path.exists(out):
        raise SystemExit("front stage: finish.py produced no output")
    # keep the STRIPPED car: the cavity render is the proof the rebuild replaced
    # the melt rather than being laid over it.
    shutil.move(stripped, os.path.join(w, "front_stripped.glb"))
    os.remove(rebuilt)
    return out


def stage_rear(ctx, inp):
    """Rear v2 REPLAYED on this lineage — see THE HARD JOIN in the docstring."""
    import rear_replay
    return rear_replay.run(ctx, inp)


def stage_cabin(ctx, inp):
    """Gate CABIN — open the apertures, then fit the parametric cabin."""
    w = ctx.sw("cabin")
    lg = ctx.log("cabin")
    C = os.path.join(_HERE, "cabin")
    car = os.path.join(w, "car.glb")
    shutil.copy(inp, car)
    surf = os.path.join(w, "body_surf.npz")
    kit = os.path.join(w, "cabin_kit.npz")
    raw = os.path.join(w, "cabin_raw.glb")
    out = ctx.p("work", "cabin.glb")
    env = {"CABIN_CAR": car, "CABIN_SURF": surf}
    run([sys.executable, os.path.join(C, "body_surf.py")], cwd=w, env=env, log=lg)
    run([sys.executable, os.path.join(C, "aperture_open.py"), "--controls"],
        cwd=w, env=env, log=lg)
    run([sys.executable, os.path.join(C, "cabin_build.py"), kit], cwd=w, env=env, log=lg)
    run([sys.executable, os.path.join(C, "assemble.py"), car, kit, raw],
        cwd=w, env=env, log=lg)
    run([sys.executable, os.path.join(_HERE, "gate3v7", "finish.py"), raw,
         ctx.p("in", "car_rebound.glb"), out, os.path.join(w, "finish.json")],
        log=lg, check=False)
    if not os.path.exists(out):
        raise SystemExit("cabin stage: finish.py produced no output")
    os.remove(raw)
    os.remove(car)
    return out


def stage_skin(ctx, inp):
    """Gate SKIN — absorb the speckled shell/interior label partition."""
    w = ctx.sw("skin")
    lg = ctx.log("skin")
    out = ctx.p("work", "skin.glb")
    run([sys.executable, os.path.join(_HERE, "skin", "relabel.py"), inp, out,
         "--report", os.path.join(w, "relabel.json")], log=lg)
    return out


def stage_pose(ctx, inp):
    """The merge operator — Gate 6's grounding + per-corner wheel placement."""
    w = ctx.sw("pose")
    lg = ctx.log("pose")
    out = ctx.p("work", "pose.glb")
    pose_json = ctx.p("in", "op_pose.json")
    if not os.path.exists(pose_json):
        sb_get("staging/gate6/op_pose.json", pose_json)
    run([sys.executable, os.path.join(_HERE, "merge", "merge_op.py"), inp, out,
         "--stages", "pose,wheels", "--pose-mode", "record",
         "--pose-json", pose_json, "--report", os.path.join(w, "merge.json")], log=lg)
    return out


def stage_finish(ctx, inp):
    """Restore extensions, merge duplicate material names, assert on the file."""
    w = ctx.sw("finish")
    lg = ctx.log("finish")
    out = ctx.p("work", "GOLF_ALL_GATES.glb")
    rc, txt = run([sys.executable, os.path.join(_HERE, "gate3v7", "finish.py"), inp,
                   ctx.p("in", "car_rebound.glb"), out, os.path.join(w, "finish.json")],
                  log=lg, check=False)
    if not os.path.exists(out):
        raise SystemExit("finish stage produced no output")
    if rc != 0:
        raise SystemExit(f"finish stage INCOMPLETE:\n{txt[-2000:]}")
    return out


def stage_mobile(ctx, inp):
    """Draco mobile export.  `--join false` keeps the component node names."""
    w = ctx.sw("mobile")
    lg = ctx.log("mobile")
    out = ctx.p("work", "GOLF_ALL_GATES_mobile.glb")
    run(["gltf-transform", "optimize", inp, out, "--compress", "draco",
         "--texture-compress", "false", "--join", "false", "--simplify", "false"],
        log=lg)
    return out


def stage_sheet(ctx, inp):
    """Eight views, so the owner can look at the thing rather than the numbers."""
    import evidence
    return evidence.run(ctx, inp)


STAGES = {
    "base": stage_base, "glass": stage_glass, "front": stage_front,
    "rear": stage_rear, "cabin": stage_cabin, "skin": stage_skin,
    "pose": stage_pose, "finish": stage_finish, "mobile": stage_mobile,
    "sheet": stage_sheet,
}

# Stages whose output is not a full car and must not be gated as one.
NO_GATE = {"mobile", "sheet"}


# ----------------------------------------------------------------- the driver
def gate_stage(ctx, name, out, res, samples):
    """The hard gate.  A stage that regresses a must-not-break property FAILS."""
    if name in NO_GATE:
        return None
    w = ctx.p("ev", name)
    cam = None
    if ctx.ref is not None:
        cam = RR.camera_for(ctx.ref, dist_mul=1.45)
        cam["shots"] = RR.shots([(305, 12, "f34"), (125, 12, "r34")])
    p = gates.panel(out, w, ref=ctx.ref, cam=cam, do_respray=True,
                    res=res, samples=samples, tag=name)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--from", dest="frm", default=None,
                    help="force a re-run from this stage onward")
    ap.add_argument("--only", default=None)
    ap.add_argument("--to", default=None)
    ap.add_argument("--selftest", action="store_true",
                    help="prove every gate can FAIL, then exit")
    ap.add_argument("--no-gate", action="store_true",
                    help="run the stages without the gate panel (debug only)")
    ap.add_argument("--res", type=int, default=700)
    ap.add_argument("--samples", type=int, default=24)
    a = ap.parse_args()

    ctx = Ctx(a.root, a)
    order = list(STAGE_ORDER)
    if a.only:
        order = [s for s in order if s == a.only or s == "base"]
    if a.to:
        order = order[:order.index(a.to) + 1]

    inp = None
    force = False
    board = []
    for name in order:
        if a.frm and name == a.frm:
            force = True
        rec_p = ctx.p("receipts", f"{name}.json")
        in_sha = glbmeas.sha256(inp) if inp else None
        rec = json.load(open(rec_p)) if os.path.exists(rec_p) else None
        fresh = (rec and not force and rec.get("in_sha") == in_sha
                 and rec.get("out") and os.path.exists(rec["out"])
                 and glbmeas.sha256(rec["out"]) == rec.get("out_sha"))
        if fresh:
            print(f"[{name}] SKIP (receipt fresh)  -> {os.path.basename(rec['out'])}")
            inp = rec["out"]
            if name == "base":
                ctx.ref = glbmeas.measure(inp)
                if a.selftest:
                    r = gates.selftest(inp, ctx.p("ev", "selftest"))
                    json.dump(r, open(ctx.p("ev", "SELFTEST.json"), "w"), indent=1)
                    print(json.dumps({"base_clean": r["base_clean"],
                                      "all_fired": r["all_fired"],
                                      "controls": {k: v["fired"]
                                                   for k, v in r["controls"].items()}},
                                     indent=1))
                    return 0
            board.append((name, rec.get("gate_summary", "-"), True))
            continue

        force = True                       # anything after a re-run is stale
        print(f"\n=== STAGE {name} " + "=" * 50)
        t0 = time.time()
        try:
            out = STAGES[name](ctx, inp)
        except Exception:
            traceback.print_exc()
            raise SystemExit(f"STAGE {name} FAILED")
        rec = {"stage": name, "in": inp, "in_sha": in_sha, "out": out,
               "out_sha": glbmeas.sha256(out) if out.endswith(".glb") else None,
               "out_bytes": os.path.getsize(out) if os.path.exists(out) else None,
               "seconds": round(time.time() - t0, 1),
               "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if name == "base":
            ctx.ref = glbmeas.measure(out)
            json.dump(ctx.ref, open(ctx.p("ev", "BASE_MEASURE.json"), "w"), indent=1)
            if a.selftest:
                r = gates.selftest(out, ctx.p("ev", "selftest"))
                json.dump(r, open(ctx.p("ev", "SELFTEST.json"), "w"), indent=1)
                print(json.dumps({"base_clean": r["base_clean"],
                                  "all_fired": r["all_fired"]}, indent=1))
                return 0
        if not a.no_gate:
            p = gate_stage(ctx, name, out, a.res, a.samples)
            if p is not None:
                rec["gate"] = p
                rec["gate_summary"] = gates.summary_line(p)
                print(f"[{name}] {rec['gate_summary']}")
                if not p["all_pass"]:
                    json.dump(rec, open(rec_p, "w"), indent=1, default=str)
                    raise SystemExit(
                        f"STAGE {name} REGRESSED a must-not-break property: "
                        f"{p['failed']}. Fix the stage; do not continue and hope.")
        json.dump(rec, open(rec_p, "w"), indent=1, default=str)
        board.append((name, rec.get("gate_summary", "-"), False))
        inp = out

    print("\n" + "=" * 78)
    for n, s, sk in board:
        print(f"  {'skip' if sk else 'run '} {n:8s} {s}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
