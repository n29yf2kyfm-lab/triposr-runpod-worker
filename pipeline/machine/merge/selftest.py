#!/usr/bin/env python3
"""selftest.py — prove merge_op is reusable, not just that it ran once.

The whole point of building this as an OPERATOR is that Gate 3 v7 is rebuilding
the front fascia on the same rebound base and its output will need the same
treatment. "It will generalise" is a claim, and this project's own history is
full of claims that were never tested at the INTEGRATION level — CLAUDE.md's
`geom_audit` entry is exactly that: "I tested the FUNCTION and never tested the
INTEGRATION, which is the exact failure this file already warns about."

So this builds a V7-SHAPED input out of the real base — the fascia nodes
renamed and rebound to a new material, which is what a front rebuild does — and
runs the operator on it end to end. It then asserts the things that must hold:

  1. the operator does not refuse
  2. the wheel plan is IDENTICAL to the plan on the unmodified base, to 1e-9.
     A front rebuild must not move the wheels, and the only way that is
     guaranteed is if the wheel stage never looks at the fascia. It does not:
     corners come from node geometry, and the pose comes from a recorded
     matrix, so a changed nose cannot perturb a wheel. This asserts it.
  3. the new node names and the new material survive into the output
  4. all four tyres are grounded in the new file too

It also runs the refusal paths, because a refusal that has never fired is not a
refusal: an instanced mesh, a corner label that disagrees with geometry, and a
missing NORMAL accessor must each stop the operator rather than be worked
around.

Run:
    python3 selftest.py BASE.glb --pose-json op_pose.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from glb_io import GLB, binding_table, material_table    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OP = os.path.join(HERE, "merge_op.py")

RENAME = {"Bumper_Front_Paint": "Fascia_Front_v7",
          "Bumper_Front_Trim": "Grille_Front_v7",
          "Headlamp_L": "Headlamp_L_v7",
          "Headlamp_R": "Headlamp_R_v7"}


def make_v7_like(src, out):
    """Rename the fascia nodes and bind the grille to a NEW material."""
    g = GLB(src)
    for nd in g.g["nodes"]:
        if nd.get("name") in RENAME:
            nd["name"] = RENAME[nd["name"]]
    for mh in g.g["meshes"]:
        if mh.get("name") in RENAME:
            mh["name"] = RENAME[mh["name"]]
    new = json.loads(json.dumps(g.g["materials"][0]))
    new["name"] = "Grille_Mesh_v7"
    new["pbrMetallicRoughness"] = dict(baseColorFactor=[0.03, 0.03, 0.035, 1.0],
                                       metallicFactor=0.4, roughnessFactor=0.5)
    g.g["materials"].append(new)
    mi = len(g.g["materials"]) - 1
    idx = {i for i, nd in enumerate(g.g["nodes"])
           if nd.get("name") == "Grille_Front_v7"}
    for i in idx:
        for p in g.g["meshes"][g.g["nodes"][i]["mesh"]]["primitives"]:
            p["material"] = mi
    g.save(out)
    return out


def run_op(glb, out, pose_json, report, extra=()):
    cmd = [sys.executable, OP, glb, out, "--pose-mode", "record",
           "--pose-json", pose_json, "--report", report, *extra]
    return subprocess.run(cmd, capture_output=True, text=True)


def break_it(src, kind, out):
    g = GLB(src)
    if kind == "instanced":
        n0 = g.g["nodes"][0]
        g.g["nodes"].append(dict(name="CLONE", mesh=n0["mesh"]))
        g.g["scenes"][0]["nodes"].append(len(g.g["nodes"]) - 1)
    elif kind == "mislabelled_corner":
        for nd in g.g["nodes"]:
            if nd.get("name", "").startswith("Wheel_FL_"):
                nd["name"] = nd["name"].replace("Wheel_FL_", "Wheel_RR_")
            elif nd.get("name", "").startswith("Wheel_RR_"):
                nd["name"] = nd["name"].replace("Wheel_RR_", "Wheel_FL_")
    elif kind == "no_normal":
        for mh in g.g["meshes"]:
            if mh.get("name") == "Mirror_L":
                mh["primitives"][0]["attributes"].pop("NORMAL", None)
    g.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--pose-json", required=True)
    a = ap.parse_args()
    ok = True
    with tempfile.TemporaryDirectory() as td:
        j = lambda *p: os.path.join(td, *p)                    # noqa: E731

        print("1. reference run on the unmodified base")
        r0 = run_op(a.base, j("ref.glb"), a.pose_json, j("ref.json"))
        assert r0.returncode == 0, r0.stderr[-2000:]
        ref = json.load(open(j("ref.json")))

        print("2. v7-shaped input: fascia nodes renamed, grille rebound to a "
              "new material")
        v7 = make_v7_like(a.base, j("v7in.glb"))
        r1 = run_op(v7, j("v7out.glb"), a.pose_json, j("v7.json"))
        if r1.returncode != 0:
            print("   REFUSED (should not have):", r1.stdout[-800:],
                  r1.stderr[-800:])
            ok = False
        else:
            rep = json.load(open(j("v7.json")))
            worst = 0.0
            for k in ("FL", "FR", "RL", "RR"):
                for f in ("s_rad", "s_ax"):
                    worst = max(worst, abs(rep["wheels"][k][f]
                                           - ref["wheels"][k][f]))
                for i in range(3):
                    worst = max(worst, abs(rep["wheels"][k]["hub_to"][i]
                                           - ref["wheels"][k]["hub_to"][i]))
            same = worst < 1e-9
            print(f"   wheel plan identical to the reference run: {same} "
                  f"(worst delta {worst:.3e})")
            ok &= same
            out = GLB(j("v7out.glb"))
            names = set(binding_table(out))
            got = all(v in names for v in RENAME.values())
            mats = set(material_table(out))
            gm = "Grille_Mesh_v7" in mats
            bot = {k: v["tyre_bottom_m"] for k, v in rep["wheels"].items()}
            grounded = all(abs(v) < 5e-4 for v in bot.values())
            print(f"   renamed nodes survive: {got}")
            print(f"   new material survives : {gm} "
                  f"({len(mats)} materials, was {len(material_table(GLB(a.base)))})")
            print(f"   all four grounded     : {grounded} "
                  f"{ {k: round(v * 1000, 5) for k, v in bot.items()} }")
            ok &= got and gm and grounded

        print("3. refusal paths — each must STOP the operator")
        for kind, expect in (("instanced", "shared by several nodes"),
                             ("mislabelled_corner", "disagree with geometry"),
                             ("no_normal", "has no NORMAL accessor")):
            p = break_it(a.base, kind, j(kind + ".glb"))
            r = run_op(p, j(kind + "_out.glb"), a.pose_json, j(kind + ".json"))
            txt = (r.stdout or "") + (r.stderr or "")
            fired = r.returncode != 0 and expect in txt
            print(f"   {kind:20s} refused: {fired}")
            ok &= fired

    print(f"\nSELFTEST_OK: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
