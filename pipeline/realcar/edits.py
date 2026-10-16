#!/usr/bin/env python3
"""edits.py — a person's corrections to a rigged car, made in the Studio.

    python3 pipeline/realcar/edits.py RIG_DIR EDITS.json

The rigger's file (RIG_DIR/src.glb, nodes SB_<part>__<n>) is kept untouched
as src.orig.glb the first time; every set of edits is applied to that
original, so edits can be changed or undone at any time and never stack.

EDITS.json, as the Studio sends it:
    {"version": 1,
     "assign": [{"node": "SB_body__3", "prim": 0,
                 "runs": [[first_triangle, count, "panel_bonnet"], ...]}, ...],
     "hinges": {"bonnet": {"edge": "rear", "deg": 55}, ...}}

A part name is one of the rig's (body, panel_bonnet, tailgate, door_fl ...);
"drop" removes the triangles from the car. A door's dark inner card follows
its skin. Written back: RIG_DIR/src.glb (the parts as edited) and
RIG_DIR/edits.json, which adds "manual": the parts the person set by hand,
so finish.py takes those as they are instead of searching for them.
"""
import json
import os
import re
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "template"))
from gltf import GLTF  # noqa: E402

PARTS = {"body", "panel_bonnet", "tailgate", "door_fl", "door_fr", "door_rl", "door_rr", "drop"}
HINGE_EDGES = {"door": {"front", "rear"}, "bonnet": {"rear", "front"}, "tailgate": {"top", "bottom", "left", "right"}}


def part_of(name):
    m = re.match(r"SB_(.+?)(__\d+)?$", name or "")
    return m.group(1) if m else "body"


def clean(edits):
    """Only what the Studio may send: known parts, sane runs, known hinges."""
    out = {"version": 1, "assign": [], "hinges": {}}
    for a in edits.get("assign", []):
        runs = [[int(s), int(n), str(p)] for s, n, p in a.get("runs", []) if p in PARTS and int(s) >= 0 and int(n) > 0]
        if runs:
            out["assign"].append({"node": str(a["node"]), "prim": int(a.get("prim", 0)), "runs": runs})
    for part, h in (edits.get("hinges") or {}).items():
        part = "bonnet" if part == "panel_bonnet" else part     # the finisher's name for it
        kind = "door" if part.startswith("door_") else part
        if kind in HINGE_EDGES and h.get("edge") in HINGE_EDGES[kind]:
            out["hinges"][part] = {"edge": h["edge"], "deg": float(min(max(float(h.get("deg", 60)), 5), 120))}
    return out


def apply(rig_dir, edits):
    """Apply EDITS to RIG_DIR's original rig; returns the edits as saved."""
    edits = clean(edits)
    src, orig = os.path.join(rig_dir, "src.glb"), os.path.join(rig_dir, "src.orig.glb")
    if not os.path.exists(orig):
        shutil.copyfile(src, orig)
    g = GLTF(orig)
    j = g.j
    by_node = {}
    for a in edits["assign"]:
        by_node.setdefault(a["node"], {}).setdefault(a["prim"], []).extend(a["runs"])
    cards = {i for i, m in enumerate(j.get("materials", [])) if m.get("name") == "SB_door_inner"}

    manual = set()
    meshes, nodes, count = [], [dict(j["nodes"][0], children=[])], {}
    for n in j["nodes"][1:]:
        if "mesh" not in n:
            continue
        own = part_of(n["name"])
        groups = {}                                   # part -> [primitive]
        prev_tp = None
        for pi, p in enumerate(j["meshes"][n["mesh"]]["primitives"]):
            I = g.accessor(p["indices"]).reshape(-1, 3)
            tp = np.full(len(I), own, dtype=object)
            if p.get("material") in cards and prev_tp is not None and len(prev_tp) == len(I):
                tp = prev_tp.copy()                   # the card follows its skin, triangle for triangle
            for s, c, part in by_node.get(n["name"], {}).get(pi, []):
                tp[s:s + c] = part
            if p.get("material") not in cards:
                prev_tp = tp
            for part in np.unique(tp):
                if part != own:
                    manual.update({part, own})
                if part == "drop":
                    continue
                sel = I[tp == part]
                q = {k: v for k, v in p.items() if k != "indices"}
                q["indices"] = g.add_accessor(sel.ravel().astype(np.uint32), ctype=5125, atype="SCALAR", target=34963)
                groups.setdefault(part, []).append(q)
        for part, prims in groups.items():
            k = count.get(part, 0)
            count[part] = k + 1
            meshes.append({"name": f"SB_{part}__{k}", "primitives": prims})
            node = {"name": f"SB_{part}__{k}", "mesh": len(meshes) - 1}
            for t in ("matrix", "translation", "rotation", "scale"):
                if t in n:
                    node[t] = n[t]
            nodes.append(node)
            nodes[0]["children"].append(len(nodes) - 1)
    j["meshes"], j["nodes"] = meshes, nodes
    j["scenes"] = [{"name": "car", "nodes": [0]}]
    g.save(src)
    manual.discard("drop")
    edits["manual"] = sorted(("bonnet" if p == "panel_bonnet" else p) for p in manual
                             if p in PARTS and p != "body")
    json.dump(edits, open(os.path.join(rig_dir, "edits.json"), "w"), indent=1)
    return edits


def reset(rig_dir):
    """Back to the rigger's own parts."""
    orig = os.path.join(rig_dir, "src.orig.glb")
    if os.path.exists(orig):
        shutil.copyfile(orig, os.path.join(rig_dir, "src.glb"))
        os.remove(orig)
    if os.path.exists(os.path.join(rig_dir, "edits.json")):
        os.remove(os.path.join(rig_dir, "edits.json"))


if __name__ == "__main__":
    print(json.dumps(apply(sys.argv[1], json.load(open(sys.argv[2]))), indent=1))
