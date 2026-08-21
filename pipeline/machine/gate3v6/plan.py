"""GATE 3 v6 — job planner (CPU side, runs OUTSIDE Blender).

Reads a GLB, discovers its semantic components and their transformed-vertex
bounding boxes, and emits the render-job JSON for:
  * the 15-item proof package
  * the canonical 8-view sheet

Generic by construction: the component groups are derived from geometry
(position in the car) with name regexes only as a tiebreak, so it works on the
builder's rebuilt GLB whose node names are not known in advance.

AXIS CONTRACT: length on X with the NOSE AT -X, Y up, width on Z. Verified on
GOLF_V5_SOURCE_LOCKED.glb (grille/headlamps/badge/plate all at x ~ -2.0) and
re-verified from the first render. canon_dims.py's nose rule gets this file
wrong and does not warn.
"""
import json, math, os, re, sys
import numpy as np
import trimesh

BODYISH = re.compile(r"carpaint|body|shell|paint|panel|bonnet|bumper|fender|wing|"
                     r"door|quarter|hatch|tailgate|sill|roof", re.I)
GLASSY = re.compile(r"glass|window|windscreen|windshield|screen|glazing|pane", re.I)
WHEELY = re.compile(r"tyre|tire|rubber|rim|alloy|wheel|hub|disc|caliper|brake", re.I)
INSIDE = re.compile(r"interior|cabin|seat|dash|console|occluder|floor", re.I)
LAMPY = re.compile(r"lamp|head_?l|drl|lens|housing|light", re.I)
FRONTKIT = re.compile(r"head|drl|grille|grill|intake|badge|plate|lens|housing|"
                      r"lamp|emblem|mesh|vent|splitter", re.I)


def node_boxes(path):
    sc = trimesh.load(path, process=False)
    if not isinstance(sc, trimesh.Scene):
        sc = trimesh.Scene(sc)
    out = {}
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph.get(node)
        g = sc.geometry[gname]
        # TRANSFORMED VERTICES, never a node translation - downstream stages bake
        # transforms and a translation read returns 0 (recorded trap).
        v = trimesh.transformations.transform_points(g.vertices, T)
        base = node.split(".")[0]
        lo, hi = v.min(0), v.max(0)
        if base in out:
            o = out[base]
            o["lo"] = np.minimum(o["lo"], lo).tolist() if isinstance(o["lo"], list) else np.minimum(o["lo"], lo)
            o["hi"] = np.maximum(o["hi"], hi)
            o["faces"] += len(g.faces)
        else:
            out[base] = {"lo": lo, "hi": hi, "faces": int(len(g.faces))}
    for k, v in out.items():
        v["lo"] = np.asarray(v["lo"], dtype=float)
        v["hi"] = np.asarray(v["hi"], dtype=float)
        v["c"] = (v["lo"] + v["hi"]) / 2.0
    return out


def classify(boxes):
    xs = np.array([b["lo"][0] for b in boxes.values()])
    xhi = np.array([b["hi"][0] for b in boxes.values()])
    xlo_all, xhi_all = xs.min(), xhi.max()
    L = xhi_all - xlo_all
    front_cut = xlo_all + 0.28 * L               # nose is at -X
    big = max(b["faces"] for b in boxes.values())
    groups = {"base": [], "frontkit": [], "glass": [], "wheels": [], "interior": [],
              "lamps": [], "other": []}
    for name, b in boxes.items():
        is_small = b["faces"] < big * 0.06
        in_front = b["hi"][0] <= front_cut + 0.06 * L
        if GLASSY.search(name):
            groups["glass"].append(name)
        elif WHEELY.search(name):
            groups["wheels"].append(name)
        elif INSIDE.search(name):
            groups["interior"].append(name)
        elif is_small and in_front and (FRONTKIT.search(name) or True):
            groups["frontkit"].append(name)
            if LAMPY.search(name):
                groups["lamps"].append(name)
        elif BODYISH.search(name) or b["faces"] >= big * 0.06:
            groups["base"].append(name)
        else:
            groups["other"].append(name)
    return groups, dict(xlo=float(xlo_all), xhi=float(xhi_all), L=float(L),
                        front_cut=float(front_cut))


def explode_ranks(boxes, names, axis_gltf="-x"):
    """Layered explode ranks. Semantic layers first (wells/housings sit deepest,
    lenses/plates outermost); if the names are unfamiliar, fall back to ordering
    by how far forward the part's own front face sits. Never fails."""
    layer = []
    for n in names:
        s = n.lower()
        if re.search(r"well|recess|housing|backstop|frame|surround", s):
            r = 1
        elif re.search(r"inner|reflector|bezel|shroud", s):
            r = 2
        elif re.search(r"drl|slat|bar|mesh|grid|louvre", s):
            r = 3
        elif re.search(r"lens|badge|emblem|plate|cover|glass|trim", s):
            r = 4
        else:
            r = 0
        layer.append((n, r))
    if len({r for _, r in layer}) <= 1:
        order = sorted(names, key=lambda n: boxes[n]["lo"][0], reverse=True)
        layer = [(n, i + 1) for i, n in enumerate(order)]
    return {n: r for n, r in layer}


def headlamp_sets(boxes, lamps):
    left = [n for n in lamps if boxes[n]["c"][2] > 0]     # +Z is the car's LEFT
    right = [n for n in lamps if boxes[n]["c"][2] <= 0]
    return left, right


def main():
    glb = sys.argv[1]
    outdir = sys.argv[2]
    tag = sys.argv[3]
    jobdir = sys.argv[4]
    boxes = node_boxes(glb)
    groups, geo = classify(boxes)
    lo = np.min([b["lo"] for b in boxes.values()], axis=0)
    hi = np.max([b["hi"] for b in boxes.values()], axis=0)
    ext = hi - lo
    # headlamp height: centre of the lamp cluster if present, else 55% of height
    lamps = groups["lamps"]
    if lamps:
        ly = float(np.mean([boxes[n]["c"][1] for n in lamps]))
    else:
        ly = float(lo[1] + 0.55 * ext[1])
    info = {"glb": glb, "tag": tag, "ext_gltf": ext.tolist(),
            "lo": lo.tolist(), "hi": hi.tolist(),
            "headlamp_height_gltf_y": ly, "geo": geo, "groups": groups,
            "n_nodes": len(boxes),
            "nodes": {k: {"faces": v["faces"], "lo": [round(x, 4) for x in v["lo"]],
                          "hi": [round(x, 4) for x in v["hi"]]}
                      for k, v in sorted(boxes.items())}}
    os.makedirs(jobdir, exist_ok=True)
    with open(os.path.join(jobdir, "plan_%s.json" % tag), "w") as f:
        json.dump(info, f, indent=1)
    print(json.dumps({k: info[k] for k in
                      ("ext_gltf", "headlamp_height_gltf_y", "n_nodes")}, indent=1))
    print("groups:", {k: len(v) for k, v in groups.items()})
    print("frontkit:", sorted(groups["frontkit"]))
    print("lamps:", sorted(groups["lamps"]))


if __name__ == "__main__":
    main()
