"""Strip the baked GB plates from a GLB by editing the JSON chunk only.

The plate quads were added as their own nodes/meshes/materials, so detaching
those nodes from the scene graph removes them from every renderer. The binary
chunk is copied through byte-for-byte — no Draco decode, no geometry re-export,
no quality risk, and it runs in milliseconds instead of the 30-60s a Blender
re-bake costs.

Only nodes whose name matches OUR bake are touched; a model's own plate is left
alone (it is usually painted into a texture anyway and cannot be removed here).
"""
import json, os, re, struct, sys

OURS = re.compile(r"^plate_(front|rear)(_m)?(\.\d+)?$", re.I)


def strip(src, dst):
    d = open(src, "rb").read()
    if d[:4] != b"glTF":
        raise ValueError("not a GLB")
    jl = struct.unpack("<I", d[12:16])[0]
    j = json.loads(d[20:20 + jl])
    rest = d[20 + jl:]

    kill = {i for i, n in enumerate(j.get("nodes", []))
            if OURS.match((n.get("name") or ""))}
    # also catch a node that carries a mesh named like our plate
    meshes = j.get("meshes", [])
    for i, n in enumerate(j.get("nodes", [])):
        mi = n.get("mesh")
        if mi is not None and OURS.match((meshes[mi].get("name") or "")):
            kill.add(i)
    if not kill:
        return None

    # Do NOT detach the node from the scene. Blender still instantiates an
    # orphaned glTF node as an object datablock, but leaves it out of the view
    # layer, and the render worker's select-all loop then dies with
    #   Object 'plate_front' can't be selected because it is not in View Layer
    # (verified against the live worker 2026-07-30). Keeping the node attached
    # and dropping only its mesh leaves a harmless empty transform.
    for i in kill:
        j["nodes"][i].pop("mesh", None)

    nj = json.dumps(j, separators=(",", ":")).encode()
    nj += b" " * ((4 - len(nj) % 4) % 4)
    out = (b"glTF" + struct.pack("<II", 2, 12 + 8 + len(nj) + len(rest))
           + struct.pack("<I", len(nj)) + b"JSON" + nj + rest)
    open(dst, "wb").write(out)
    with open(dst, "rb") as f:
        assert struct.unpack("<I", f.read(12)[8:12])[0] == os.path.getsize(dst)
    return sorted(kill)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        out = p.replace(".glb", "_noplate.glb")
        k = strip(p, out)
        print(f"{os.path.basename(p):<34} removed nodes={k}")
