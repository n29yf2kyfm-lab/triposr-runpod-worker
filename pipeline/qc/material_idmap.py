"""Build a material-ID GLB: every material gets a distinct flat hue with its
base-colour texture dropped, so a single render shows EXACTLY which surfaces
each material owns. Rewrites only the JSON chunk, so the binary (incl. Draco)
is untouched. Material names alone have proven unreliable on these 19 cars —
this measures the real coverage instead.
"""
import json, os, struct, sys

# 22 maximally-distinct sRGB hues; index 0 is reserved for "not ranked"
SWATCH = ["ff0000", "00ff00", "0000ff", "ffff00", "ff00ff", "00ffff",
          "ff8000", "8000ff", "0080ff", "80ff00", "ff0080", "00ff80",
          "804000", "408000", "004080", "800040", "ffffff", "808080",
          "ff8080", "80ff80", "8080ff", "ffc0cb"]
GREY = "202020"

def s2l(h):
    def c(x):
        x = int(x, 16) / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return [c(h[0:2]), c(h[2:4]), c(h[4:6])]

def build(inp, outp, topn=22):
    d = open(inp, "rb").read()
    jl = struct.unpack("<I", d[12:16])[0]
    j = json.loads(d[20:20 + jl])
    rest = d[20 + jl:]

    acc = j.get("accessors", [])
    tris = {}
    for me in j.get("meshes", []):
        for pr in me.get("primitives", []):
            mi = pr.get("material")
            if mi is None: continue
            ia = pr.get("indices")
            tris[mi] = tris.get(mi, 0) + ((acc[ia]["count"] // 3) if ia is not None else 0)
    tot = sum(tris.values()) or 1
    order = sorted(range(len(j.get("materials", []))), key=lambda i: -tris.get(i, 0))

    legend = []
    for rank, mi in enumerate(order):
        m = j["materials"][mi]
        hexv = SWATCH[rank] if rank < topn else GREY
        pmr = m.setdefault("pbrMetallicRoughness", {})
        pmr.pop("baseColorTexture", None)
        alpha = (pmr.get("baseColorFactor") or [1, 1, 1, 1])[3]
        pmr["baseColorFactor"] = s2l(hexv) + [alpha]
        pmr["metallicFactor"] = 0.0
        pmr["roughnessFactor"] = 0.75
        # kill anything that would repaint or wash out the flat hue
        m.pop("emissiveTexture", None); m.pop("emissiveFactor", None)
        m.pop("extensions", None)
        legend.append({"rank": rank, "hex": hexv if rank < topn else GREY,
                       "name": m.get("name") or f"<unnamed{mi}>",
                       "pct": round(100 * tris.get(mi, 0) / tot, 2),
                       "alphaMode": m.get("alphaMode", "OPAQUE"), "alpha": round(alpha, 2)})

    nj = json.dumps(j, separators=(",", ":")).encode()
    nj += b" " * ((4 - len(nj) % 4) % 4)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(nj) + len(rest)) \
        + struct.pack("<I", len(nj)) + b"JSON" + nj + rest
    open(outp, "wb").write(out)
    assert struct.unpack("<I", open(outp, "rb").read(12)[8:12])[0] == os.path.getsize(outp)
    return legend

if __name__ == "__main__":
    W = f"{os.path.dirname(os.path.abspath(__file__))}/work"
    out = {}
    for f in sorted(os.listdir(W)):
        if not f.endswith(".glb") or f.endswith("_id.glb"):
            continue
        aid = f[:-4]
        try:
            out[aid] = build(f"{W}/{f}", f"{W}/{aid}_id.glb")
            print(f"{aid}: {len(out[aid])} mats", flush=True)
        except Exception as ex:
            print(f"{aid}: FAIL {type(ex).__name__} {ex}", flush=True)
    json.dump(out, open(f"{os.path.dirname(os.path.abspath(__file__))}/LEGEND.json", "w"), indent=1)
    print("IDMAP_OK", len(out))
