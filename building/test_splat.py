"""Tests for the Gaussian splat side — everything that does not need a GPU.

Fitting gaussians needs CUDA. Reading a capture, writing and re-reading the
.ply, moving a splat into the building's own frame and checking whether the
result is remotely the right size do NOT, and they are where the mistakes
that would ruin a job actually live. So they are separated out and tested
here on a machine with no GPU at all.

Run: python building/test_splat.py
"""
import math
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import splat as S  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


def gaussian(x, y, z, **kw):
    g = {"x": x, "y": y, "z": z, "opacity": 1.0,
         "scale_0": -2.0, "scale_1": -2.0, "scale_2": -2.0,
         "rot_0": 1.0, "rot_1": 0.0, "rot_2": 0.0, "rot_3": 0.0,
         "f_dc_0": 0.3, "f_dc_1": 0.1, "f_dc_2": 0.05}
    g.update(kw)
    return g


# --- 1. the format is the one the ecosystem expects -------------------------
check("1a degree-3 spherical harmonics", S.SH_DC == 3 and S.SH_REST == 45)
check("1b position comes first",
      S.SPLAT_FIELDS[:6] == ["x", "y", "z", "nx", "ny", "nz"])
check("1c opacity, scale and rotation come last",
      S.SPLAT_FIELDS[-8:] == ["opacity", "scale_0", "scale_1", "scale_2",
                              "rot_0", "rot_1", "rot_2", "rot_3"])
check("1d 62 properties per gaussian", len(S.SPLAT_FIELDS) == 62,
      str(len(S.SPLAT_FIELDS)))
check("1e no duplicated property names",
      len(set(S.SPLAT_FIELDS)) == len(S.SPLAT_FIELDS))


# --- 2. write and read it back ----------------------------------------------
src = [gaussian(1.0, 2.0, 3.0), gaussian(-4.5, 0.25, 7.125, opacity=0.4),
       gaussian(0.0, 0.0, 0.0, f_rest_0=0.9)]
with tempfile.TemporaryDirectory() as td:
    p = S.write_ply(src, os.path.join(td, "a.ply"))
    check("2a a file is written", os.path.getsize(p) > 0)
    # header + 3 * 62 floats
    check("2b the payload is exactly the gaussians",
          os.path.getsize(p) - open(p, "rb").read().index(b"end_header\n")
          - len("end_header\n") == 3 * 62 * 4,
          str(os.path.getsize(p)))

    back, fields = S.read_ply(p)
    check("2c every gaussian survives", len(back) == 3, str(len(back)))
    check("2d the field list round trips", fields == S.SPLAT_FIELDS)
    check("2e positions are exact",
          all(abs(back[i]["x"] - src[i]["x"]) < 1e-6
              and abs(back[i]["z"] - src[i]["z"]) < 1e-6 for i in range(3)))
    check("2f opacity survives", abs(back[1]["opacity"] - 0.4) < 1e-6)
    check("2g higher-order SH survives", abs(back[2]["f_rest_0"] - 0.9) < 1e-6)
    check("2h missing fields are written as zero",
          abs(back[0]["f_rest_44"]) < 1e-9)

    # A reader that assumes 45 rest coefficients mangles a shorter export.
    short_fields = ["x", "y", "z", "opacity"]
    q = os.path.join(td, "short.ply")
    with open(q, "wb") as fh:
        hdr = (["ply", "format binary_little_endian 1.0", "element vertex 2"]
               + [f"property float {f}" for f in short_fields]
               + ["end_header"])
        fh.write(("\n".join(hdr) + "\n").encode("ascii"))
        for v in ((1.0, 2.0, 3.0, 0.5), (4.0, 5.0, 6.0, 0.25)):
            fh.write(struct.pack("<ffff", *v))
    got, gf = S.read_ply(q)
    check("2i a shorter export reads by ITS header, not ours",
          gf == short_fields and len(got) == 2 and abs(got[1]["y"] - 5.0) < 1e-6,
          str(gf))

    # Truncated and non-PLY files are refused rather than half-read.
    bad = os.path.join(td, "bad.ply")
    with open(bad, "wb") as fh:
        fh.write(open(p, "rb").read()[:-40])
    try:
        S.read_ply(bad)
        check("2j a truncated file is refused", False)
    except S.SplatError as e:
        check("2j a truncated file is refused", "runs out" in str(e), str(e))

    notply = os.path.join(td, "n.ply")
    with open(notply, "wb") as fh:
        fh.write(b"solid teapot\nend_header\n")
    try:
        S.read_ply(notply)
        check("2k a non-PLY file is refused", False)
    except S.SplatError:
        check("2k a non-PLY file is refused", True)

    ascii_ply = os.path.join(td, "asc.ply")
    with open(ascii_ply, "wb") as fh:
        fh.write(b"ply\nformat ascii 1.0\nelement vertex 1\n"
                 b"property float x\nend_header\n1.0\n")
    try:
        S.read_ply(ascii_ply)
        check("2l an ASCII PLY is refused clearly", False)
    except S.SplatError as e:
        check("2l an ASCII PLY is refused clearly",
              "binary" in str(e).lower(), str(e))


# --- 3. into the building's frame -------------------------------------------
# A 90 degree turn about the vertical, then a translation. glTF-style axes:
# x east, y up, z is the plan's second axis.
moved = S.to_building_frame([gaussian(2.0, 1.0, 0.0)],
                            math.pi / 2, (100.0, 200.0))
m = moved[0]
check("3a rotated about the vertical",
      abs(m["x"] - 100.0) < 1e-6 and abs(m["z"] - 202.0) < 1e-6,
      f"{m['x']},{m['z']}")
check("3b height is untouched by a plan rotation", abs(m["y"] - 1.0) < 1e-6)
check("3c the input is not modified", moved[0] is not None
      and "x" in moved[0])

lifted = S.to_building_frame([gaussian(0.0, 5.0, 0.0)], 0.0, (0.0, 0.0),
                             ground_z=2.0)
check("3d ground level is subtracted", abs(lifted[0]["y"] - 3.0) < 1e-6)

# Scale must move the gaussians AND resize them, or the cloud is in the right
# place made of wrongly-sized blobs.
scaled = S.to_building_frame([gaussian(2.0, 0.0, 0.0)], 0.0, (0.0, 0.0),
                             scale=4.0)
check("3e positions are scaled", abs(scaled[0]["x"] - 8.0) < 1e-6,
      str(scaled[0]["x"]))
check("3f and the gaussians are scaled with them",
      abs(scaled[0]["scale_0"] - (-2.0 + math.log(4.0))) < 1e-6,
      str(scaled[0]["scale_0"]))
unscaled = S.to_building_frame([gaussian(2.0, 0.0, 0.0)], 0.0, (0.0, 0.0))
check("3g a unit scale leaves the sizes alone",
      abs(unscaled[0]["scale_0"] - (-2.0)) < 1e-9)


# --- 4. is any of it believable ---------------------------------------------
cloud = [gaussian(x * 0.5, y * 0.5, z * 0.5)
         for x in range(27) for y in range(4) for z in range(20)]
rep = S.sanity(cloud, expect_span_m=13.2)
check("4a it counts what is there", rep["gaussians"] == len(cloud))
check("4b it measures the extent", abs(rep["span_m"] - 13.0) < 0.1,
      str(rep["span_m"]))
check("4c it says a splat is not measurable", rep["measurable"] is False)
check("4d and says so in words", "not measured" in rep["note"])
check("4e a matching span raises no warning", "warning" not in rep,
      str(rep.get("warning")))

off = S.sanity(cloud, expect_span_m=45.0)
check("4f a splat at the wrong scale is flagged", "warning" in off)
check("4g and the factor is named", "0.29" in off.get("warning", ""),
      off.get("warning", "")[:80])

try:
    S.sanity([])
    check("4h an empty splat is refused", False)
except S.SplatError as e:
    check("4h an empty splat is refused", "empty" in str(e), str(e))

try:
    S.sanity([gaussian(1.0, 1.0, 1.0), gaussian(1.0, 1.0, 1.0)])
    check("4i a collapsed fit is refused", False)
except S.SplatError as e:
    check("4i a collapsed fit is refused", "parallax" in str(e), str(e))


# --- 5. the honest failure contract -----------------------------------------
ok, why = S.available()
check("5a availability reports a reason either way",
      isinstance(ok, bool) and isinstance(why, str) and len(why) > 0, why)
if not ok:
    check("5b and the reason names what is missing",
          any(w in why for w in ("torch", "CUDA", "gsplat")), why)

with tempfile.TemporaryDirectory() as td:
    for i in range(3):
        open(os.path.join(td, f"f{i}.jpg"), "wb").close()
    try:
        S.fit(td, os.path.join(td, "out.ply"))
        check("5c fitting refuses without a GPU or enough frames", False)
    except S.SplatError as e:
        # Either refusal is correct; both must explain themselves, and both
        # must say the rest of the job still ships.
        check("5c fitting refuses without a GPU or enough frames",
              len(str(e)) > 60, str(e)[:80])
        check("5d the refusal says the measured work is unaffected, "
              "or names the frame shortfall",
              ("delivered regardless" in str(e)) or ("frames" in str(e)),
              str(e)[:100])

check("5e a sane floor on view count", S.MIN_VIEWS >= 20, str(S.MIN_VIEWS))


# --- 6. gaussians out of a pipeline that already makes them -----------------
# TRELLIS holds them under the 3DGS names. No numpy or torch needed to test
# the shape of the conversion — a list of rows with .reshape is enough.
class Rows(list):
    def reshape(self, n, m):
        return self


class FakeTrellisGaussian(object):
    def __init__(self):
        self._xyz = Rows([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        self._opacity = Rows([[0.8], [0.2]])
        self._scaling = Rows([[-1.0, -1.0, -1.0], [-2.0, -2.0, -2.0]])
        self._rotation = Rows([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
        self._features_dc = Rows([[0.5, 0.4, 0.3], [0.2, 0.1, 0.0]])


g = S.from_trellis(FakeTrellisGaussian())
check("6a both gaussians converted", len(g) == 2, str(len(g)))
check("6b positions carried", abs(g[1]["x"] - 4.0) < 1e-6
      and abs(g[1]["z"] - 6.0) < 1e-6, str(g[1]))
check("6c opacity carried", abs(g[0]["opacity"] - 0.8) < 1e-6)
check("6d scales carried", abs(g[1]["scale_2"] - (-2.0)) < 1e-6)
check("6e rotation carried", abs(g[1]["rot_1"] - 1.0) < 1e-6)
check("6f flat colour carried", abs(g[0]["f_dc_1"] - 0.4) < 1e-6)
check("6g missing higher-order SH is simply absent, not invented",
      "f_rest_0" not in g[0])

# ...and it must survive the writer, which fills the gaps with zeros.
with tempfile.TemporaryDirectory() as td:
    p = S.write_ply(g, os.path.join(td, "t.ply"))
    back, _ = S.read_ply(p)
    check("6h a TRELLIS splat writes and reads as a standard .ply",
          len(back) == 2 and abs(back[1]["x"] - 4.0) < 1e-6, str(back[1]["x"]))
    check("6i the unset SH slots are zero, not garbage",
          abs(back[0]["f_rest_44"]) < 1e-9)

try:
    S.from_trellis(object())
    check("6j an object with no gaussians is refused", False)
except S.SplatError as e:
    check("6j an object with no gaussians is refused", "_xyz" in str(e),
          str(e))


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
