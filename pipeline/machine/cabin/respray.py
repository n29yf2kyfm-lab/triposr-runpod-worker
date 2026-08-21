#!/usr/bin/env python3
"""respray.py — RED/BLUE control. The arbiter, not a formality.

CLAUDE.md: "a generated car is not material-clear until a --colour red respray
leaves glazing and tyres dark. Gates + eye + texture all agreed and all three
were wrong; only the respray was right."

Writes <car>__red.glb and <car>__blue.glb by editing ONLY the `carpaint`
material's baseColorFactor in the glTF JSON (BIN chunk verbatim), then the
caller renders them through the SAME frozen cameras and measures each material's
own pixels using the label pass as the mask.

Run:  python3 respray.py make <car.glb>
      python3 respray.py measure <labeldir> <label_prefix> <labels.json> \
                        <shipped.png> <red.png> <blue.png> <car.glb> [out.json]
"""
import json
import struct
import sys
import numpy as np
from PIL import Image

COLOURS = {"red": [0.776, 0.012, 0.012, 1.0],
           "blue": [0.043, 0.106, 0.545, 1.0]}


def read_glb(p):
    d = open(p, "rb").read()
    off, js, bin_ = 12, None, None
    while off < len(d):
        ln, ty = struct.unpack_from("<II", d, off)
        c = d[off + 8:off + 8 + ln]
        if ty == 0x4E4F534A:
            js = json.loads(c)
        elif ty == 0x004E4942:
            bin_ = c
        off += 8 + ln + ((-ln) % 4)
    return js, bin_


def write_glb(js, bin_, p):
    jb = json.dumps(js, separators=(",", ":")).encode()
    jb += b" " * ((-len(jb)) % 4)
    tot = 12 + 8 + len(jb) + 8 + len(bin_)
    with open(p, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, tot))
        f.write(struct.pack("<II", len(jb), 0x4E4F534A) + jb)
        f.write(struct.pack("<II", len(bin_), 0x004E4942) + bin_)


if sys.argv[1] == "make":
    car = sys.argv[2]
    js, bin_ = read_glb(car)
    names = [m["name"] for m in js["materials"]]
    assert "carpaint" in names, names
    for tag, col in COLOURS.items():
        j2 = json.loads(json.dumps(js))
        for m in j2["materials"]:
            if m["name"] == "carpaint":
                m["pbrMetallicRoughness"]["baseColorFactor"] = col
        out = car.replace(".glb", f"__{tag}.glb")
        write_glb(j2, bin_, out)
        print(f"wrote {out}")
    sys.exit()

# ------------------------------------------------------------------- measure
D, PRE, LBL = sys.argv[2], sys.argv[3], sys.argv[4]
SHIP, RED, BLUE, CAR = sys.argv[5], sys.argv[6], sys.argv[7], sys.argv[8]
OUT = sys.argv[9] if len(sys.argv) > 9 else None


def srgb8(l):
    c = np.asarray(l, float) / 255.0
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return np.clip(np.rint(s * 255.0), 0, 255).astype(int)


LEV = srgb8(np.array([40 + i * 43 for i in range(6)]))
labels = json.load(open(LBL))
js, _ = read_glb(CAR)
mat_of_node = {}
for nd in js["nodes"]:
    if "mesh" in nd:
        m = js["meshes"][nd["mesh"]]
        mi = m["primitives"][0].get("material")
        mat_of_node[nd["name"]] = js["materials"][mi]["name"] if mi is not None \
            else "<none>"

view = SHIP.rsplit("_", 2)
a = np.asarray(Image.open(f"{D}/{PRE}").convert("RGB")).astype(int)
d = np.abs(a[..., None] - LEV[None, None, None, :])
a = LEV[d.argmin(-1)]

imgs = {k: np.asarray(Image.open(v).convert("RGB")).astype(float)
        for k, v in (("shipped", SHIP), ("red", RED), ("blue", BLUE))}

bymat = {}
for node, col in labels.items():
    c = srgb8(np.array(col))
    m = (a[:, :, 0] == c[0]) & (a[:, :, 1] == c[1]) & (a[:, :, 2] == c[2])
    if m.sum() < 40:
        continue
    mt = mat_of_node.get(node, "?")
    bymat.setdefault(mt, np.zeros(m.shape, bool))
    bymat[mt] |= m

rep = {}
print(f"{'material':20s} {'shipped':>18s} {'RED':>18s} {'BLUE':>18s} {'px':>8s}")
for mt, m in sorted(bymat.items()):
    row = {k: [round(float(v[m][:, i].mean()), 1) for i in range(3)]
           for k, v in imgs.items()}
    rep[mt] = {"px": int(m.sum()), **row}
    f = lambda k: "[" + " ".join(f"{v:5.1f}" for v in row[k]) + "]"
    print(f"{mt:20s} {f('shipped'):>18s} {f('red'):>18s} {f('blue'):>18s} "
          f"{int(m.sum()):8d}")

# the verdict, stated as a rule rather than left to the eye
def moved(mt):
    s = np.array(rep[mt]["shipped"])
    r = np.array(rep[mt]["red"])
    b = np.array(rep[mt]["blue"])
    return float(np.abs(r - b).max())


print()
for mt in sorted(rep):
    mv = moved(mt)
    want = "MUST MOVE" if mt == "carpaint" else "must hold"
    ok = (mv > 40) if mt == "carpaint" else (mv < 22)
    print(f"  {mt:20s} red-vs-blue max channel delta {mv:6.1f}  {want}  "
          f"{'PASS' if ok else 'FAIL'}")
if OUT:
    json.dump({"per_material": rep,
               "delta_red_blue": {k: moved(k) for k in rep}},
              open(OUT, "w"), indent=1)
    print("wrote", OUT)
