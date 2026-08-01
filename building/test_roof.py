"""Tests for Roof Mode — no GPU, no network, pure geometry.

Run: python building/test_roof.py
"""
import os
import sys
import math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import osgb  # noqa: E402
import roof_geometry as rg  # noqa: E402
import roof  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


# ==========================================================================
# OSGB — the National Grid conversion every UK elevation dataset needs
# ==========================================================================

# The worked example from OS 'A Guide to Coordinate Systems in Great Britain':
# Caister Water Tower, OSGB36 52°39'27.2531"N 1°43'4.5177"E
# -> E 651409.903, N 313177.270
_real_shift = osgb.wgs84_to_osgb36
osgb.wgs84_to_osgb36 = lambda a, b, h=0.0: (math.radians(a), math.radians(b), 0.0)
e, n = osgb.latlon_to_easting_northing(52 + 39 / 60 + 27.2531 / 3600,
                                       1 + 43 / 60 + 4.5177 / 3600)
err_mm = math.hypot(e - 651409.903, n - 313177.270) * 1000
check("1a transverse Mercator matches the OS worked example",
      err_mm < 10, f"{err_mm:.1f}mm off")
osgb.wgs84_to_osgb36 = _real_shift

# Grid squares across Great Britain.
for name, lat, lon, want in [
    ("Trafalgar Square", 51.50780, -0.12800, "TQ"),
    ("Caister", 52.65800, 1.71800, "TG"),
    ("Edinburgh", 55.95330, -3.18830, "NT"),
    ("Cardiff", 51.48160, -3.17910, "ST"),
    ("Newcastle", 54.97830, -1.61780, "NZ"),
    ("Penzance", 50.11860, -5.53730, "SW"),
]:
    ee, nn = osgb.latlon_to_easting_northing(lat, lon)
    got = osgb.grid_square(ee, nn)
    check(f"1b grid square {name}", got == want, f"got {got}, want {want}")

# The datum shift must actually do something — WGS84 and OSGB36 differ by
# roughly 50-120m across GB, and skipping it silently would put a property
# in the wrong LIDAR tile.
lat_w, lon_w = 51.5078, -0.1280
lat_o, lon_o, _ = osgb.wgs84_to_osgb36(lat_w, lon_w)
shift_m = math.hypot((math.degrees(lat_o) - lat_w) * 111_320,
                     (math.degrees(lon_o) - lon_w) * 111_320
                     * math.cos(math.radians(lat_w)))
check("1c datum shift is applied and plausible", 30 < shift_m < 200,
      f"{shift_m:.0f}m")

# Tile naming — what makes tile URLs derivable without a formal API.
e, n = osgb.latlon_to_easting_northing(51.50780, -0.12800)
check("1d 5km tile name", osgb.lidar_tile_name(e, n) == "TQ38sw",
      osgb.lidar_tile_name(e, n))
check("1e 10km tile name", osgb.lidar_tile_name(e, n, 10) == "TQ38",
      osgb.lidar_tile_name(e, n, 10))
check("1f grid ref format", osgb.grid_ref(e, n).startswith("TQ"),
      osgb.grid_ref(e, n))

try:
    osgb.grid_square(-50000, 50)
    check("1g off-grid rejected", False)
except ValueError as ex:
    check("1g off-grid rejected", "Great Britain" in str(ex))

bb = osgb.bbox_around(500000, 200000, 60)
check("1h bbox spans 2x radius", bb == (499940, 199940, 500060, 200060), str(bb))


# ==========================================================================
# Roof geometry
# ==========================================================================
CELL = 0.5
PITCH = math.radians(35)
SLOPE = math.tan(PITCH)


def grid(fn, w=10, d=8, cell=CELL):
    return [(i * cell, j * cell, fn(i * cell, j * cell))
            for i in range(int(w / cell)) for j in range(int(d / cell))]


GABLE = grid(lambda x, y: 3 + (y * SLOPE if y <= 4 else (8 - y) * SLOPE))
VALLEY = grid(lambda x, y: 3 + ((4 - y) * SLOPE if y < 4 else (y - 4) * SLOPE))
HIPPED = grid(lambda x, y: 3 + min(x, 10 - x, y, 8 - y) * SLOPE)
MONO = grid(lambda x, y: 3 + y * SLOPE)
FLAT = grid(lambda x, y: 3.0)

# --- plane fitting --------------------------------------------------------
p = rg.fit_plane([(0, 0, 0), (1, 0, 1), (0, 1, 2)])
check("2a fits a plane", p is not None)
check("2b coefficients correct", abs(p.a - 1) < 1e-9 and abs(p.b - 2) < 1e-9)
check("2c too few points -> None", rg.fit_plane([(0, 0, 0), (1, 1, 1)]) is None)
# Collinear-in-plan points are degenerate and must not yield a bogus plane.
check("2d degenerate -> None",
      rg.fit_plane([(0, 0, 0), (1, 0, 1), (2, 0, 2)]) is None)

# --- pitch, aspect, area --------------------------------------------------
p = rg.fit_plane([(0, 0, 0), (1, 0, 0), (0, 1, SLOPE)])
check("2e pitch matches construction", abs(p.pitch_deg - 35) < 0.01,
      f"{p.pitch_deg:.3f}")
check("2f slope factor is 1/cos(pitch)",
      abs(p.slope_factor - 1 / math.cos(PITCH)) < 1e-9)
check("2g flat plane detected", rg.fit_plane(
    [(0, 0, 5), (1, 0, 5), (0, 1, 5)]).is_flat)
check("2h flat plane has no aspect", rg.fit_plane(
    [(0, 0, 5), (1, 0, 5), (0, 1, 5)]).aspect_deg is None)
# A plane rising to the north faces south (downslope points south = 180).
check("2i aspect points downslope", abs(p.aspect_deg - 180) < 0.01,
      f"{p.aspect_deg}")

# --- segmentation ---------------------------------------------------------
planes = rg.segment_planes(GABLE, inlier_m=0.05, min_points=20)
check("3a gable -> 2 planes", len(planes) == 2, str(len(planes)))
check("3b both at 35 degrees",
      all(abs(pl.pitch_deg - 35) < 0.5 for pl in planes),
      str([round(pl.pitch_deg, 1) for pl in planes]))
check("3c mono -> 1 plane",
      len(rg.segment_planes(MONO, inlier_m=0.05, min_points=20)) == 1)
check("3d hipped -> 4 planes",
      len(rg.segment_planes(HIPPED, inlier_m=0.05, min_points=15)) == 4,
      str(len(rg.segment_planes(HIPPED, inlier_m=0.05, min_points=15))))

# Determinism: a quote that changes between runs on identical input is
# not a quote anyone can rely on.
a = rg.segment_planes(GABLE, inlier_m=0.05, min_points=20)
b = rg.segment_planes(GABLE, inlier_m=0.05, min_points=20)
check("3e segmentation is deterministic",
      [round(x.pitch_deg, 6) for x in a] == [round(x.pitch_deg, 6) for x in b])

# --- edge classification --------------------------------------------------
def edges_of(pts, mp=20):
    pl = rg.segment_planes(pts, inlier_m=0.05, min_points=mp)
    return pl, rg.find_edges(pl, CELL)


pl, ed = edges_of(GABLE)
check("4a gable -> one ridge", [e.kind for e in ed] == ["ridge"],
      str([e.kind for e in ed]))
check("4b ridge length ~10m", abs(ed[0].length_m - 10) < 1.0,
      f"{ed[0].length_m:.1f}")
check("4c ridge is horizontal", ed[0].slope_deg < 1.0)

pl, ed = edges_of(VALLEY)
check("4d valley detected", [e.kind for e in ed] == ["valley"],
      str([e.kind for e in ed]))

pl, ed = edges_of(HIPPED, mp=15)
kinds = sorted(e.kind for e in ed)
check("4e hipped roof yields 4 hips", kinds.count("hip") == 4, str(kinds))
check("4f hipped roof yields its ridge", kinds.count("ridge") == 1, str(kinds))

pl, ed = edges_of(MONO)
check("4g single plane -> no edges", ed == [])
pl, ed = edges_of(FLAT)
check("4h flat roof -> no edges", ed == [])

# Phantom-edge guard: without a seam-adjacency test, ANY two planes appear
# to meet, and a hipped roof's opposite slopes invent a junction the length
# of the whole building.
pl = rg.segment_planes(HIPPED, inlier_m=0.05, min_points=15)
opposite = [(i, j) for i in range(len(pl)) for j in range(i + 1, len(pl))]
check("4i no edge exceeds the building's longest dimension",
      all(e.length_m <= 14 for e in rg.find_edges(pl, CELL)),
      str([round(e.length_m, 1) for e in rg.find_edges(pl, CELL)]))

# --- quantities -----------------------------------------------------------
pl, ed = edges_of(GABLE)
q = rg.quantities(pl, ed, CELL * CELL, CELL, eaves_length_m=20.0)
check("5a plan area correct", abs(q["plan_area_m2"] - 80) < 1.0,
      str(q["plan_area_m2"]))
# THE number that stops the classic under-order.
check("5b sloped area is plan/cos(pitch)",
      abs(q["sloped_area_m2"] - 80 / math.cos(PITCH)) < 1.5,
      f'{q["sloped_area_m2"]} vs {80 / math.cos(PITCH):.1f}')
check("5c slope uplift reported", abs(q["slope_uplift_pct"] - 22.1) < 1.0,
      str(q["slope_uplift_pct"]))
check("5d sloped area exceeds plan area",
      q["sloped_area_m2"] > q["plan_area_m2"])
check("5e predominant pitch", q["predominant_pitch_deg"] == 35,
      str(q["predominant_pitch_deg"]))
check("5f ridge length carried through", abs(q["ridge_m"] - 10) < 1.0)
check("5g eaves becomes guttering",
      q["materials"]["guttering_m"] == 20.0)
check("5h tiles derive from sloped not plan area",
      q["materials"]["covering_units"] > 80 * 10,
      str(q["materials"]["covering_units"]))
check("5i waste factor applied", q["materials"]["waste_factor"] == 1.10)
check("5j membrane includes laps",
      q["materials"]["membrane_m2"] > q["sloped_area_m2"])

try:
    rg.quantities(pl, ed, CELL * CELL, CELL, materials={"covering": "thatch"})
    check("5k unknown covering rejected", False)
except ValueError as ex:
    check("5k unknown covering rejected", "thatch" in str(ex))

# Alternative coverings change the count, not the area.
q2 = rg.quantities(pl, ed, CELL * CELL, CELL,
                   materials={"covering": "plain_tile"})
check("5l plain tile needs ~6x the units",
      q2["materials"]["covering_units"] > 5 * q["materials"]["covering_units"])
check("5m area unchanged by covering",
      q2["sloped_area_m2"] == q["sloped_area_m2"])

# --- uncertainty ----------------------------------------------------------
check("6a pitch uncertainty over 4m run",
      3 < rg.pitch_uncertainty_deg(0.15, 4.0) < 6,
      str(rg.pitch_uncertainty_deg(0.15, 4.0)))
check("6b shorter run is less certain",
      rg.pitch_uncertainty_deg(0.15, 2.0)
      > rg.pitch_uncertainty_deg(0.15, 8.0))
check("6c zero run -> None", rg.pitch_uncertainty_deg(0.15, 0) is None)


# ==========================================================================
# roof.py helpers (pure parts — no network)
# ==========================================================================
square = [(0, 0), (10, 0), (10, 8), (0, 8)]
check("7a point inside footprint", roof.point_in_polygon(5, 4, square))
check("7b point outside footprint", not roof.point_in_polygon(15, 4, square))
check("7c point outside in y", not roof.point_in_polygon(5, 20, square))
check("7d perimeter correct",
      abs(roof.polygon_perimeter(square) - 36) < 1e-6,
      str(roof.polygon_perimeter(square)))

# normalise: DSM minus DTM keeps only what stands above ground.
dsm = [(0, 0, 10.0), (1, 0, 10.0), (2, 0, 3.2)]
dtm = [(0, 0, 3.0), (1, 0, 3.0), (2, 0, 3.0)]
kept = roof.normalise(dsm, dtm, min_height_m=2.0)
check("7e keeps the building", len(kept) == 2, str(kept))
check("7f drops low clutter", all(p[2] > 5 for p in kept))
check("7g no DTM -> passthrough", roof.normalise(dsm, None) == dsm)

pts = roof.load_points([(1, 2, 3), (4, 5, 6)])
check("7h loads supplied point list", pts == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])

# Location resolution must accept explicit GPS without any network call.
loc = roof.resolve_location({"gps": {"lat": 51.5078, "lon": -0.1280}})
check("7i resolves gps to grid", loc["lidar_tile"] == "TQ38sw",
      str(loc))
check("7j carries a grid reference", loc["grid_ref"].startswith("TQ"))

try:
    roof.resolve_location({})
    check("7k missing location rejected", False)
except ValueError as ex:
    check("7k missing location rejected", "gps or address" in str(ex))


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
