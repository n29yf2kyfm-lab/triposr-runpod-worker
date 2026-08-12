"""Google Photorealistic 3D Tiles -> the real captured mesh of ONE building.

WHY THIS EXISTS. Every render this project made from its own parametric model
looked like CGI, because the existing house was an APPROXIMATION — greedy
rectangles over a height map, edges that did not meet, a model that leaked.
Google already holds a photographic, aircraft-captured 3D mesh of the same
address. This module pulls it, puts it in the building's own local frame, and
crops it to the plot, so the extension can be set into the REAL scene — roofs,
gardens, cars, fences, neighbours — instead of a green plane.

LICENCE — READ THIS BEFORE SHIPPING ANYTHING. Google's 3D Tiles are
DISPLAY-ONLY under the Maps Platform terms. You may render them and you MUST
show Google attribution on any frame that contains them. You may NOT extract
the mesh and hand it to a client as a model file. So: tiles for the PICTURES;
the GLB/OBJ/IFC a builder receives always comes from the measured model. That
is the same real-for-looks / measured-for-numbers split the product already
runs on.

TWO BUGS COST HOURS EACH. Both are written here so nobody pays again:

  1. THE GEOID. ECEF wants height above the WGS84 *ellipsoid*. Ordnance Datum
     (what Solar's ground_od_m reports, what "184.81m" means) sits ~48m BELOW
     the ellipsoid in the UK. Targeting the point at OD height buried it 48m
     underground, and every fine tile — a few metres across at street level —
     correctly rejected a point outside its box. The descent died at 128m
     geometric error. Adding GEOID_SEPARATION_M lifted it to the surface and
     the same walk reached 2.01m detail. From 12,763km to 2m by adding 48.

  2. ECEF IS BLENDER WORLD SPACE. A tile's glTF node matrix is already
     ECEF-oriented (y=Z_ecef, z=-Y_ecef); Blender's Y-up->Z-up import undoes
     exactly that, so a mesh's WORLD coordinates ARE ECEF metres. An extra
     "un-rotate" correction threw the mesh 6,000km off and the plot crop
     deleted every face. No correction is needed: subtract the target ECEF,
     rotate by the ENU basis, done.

STILL OPEN (the camera): after transform+crop the mesh sits with its ground at
about z=+2m in the local frame, not z=0 — the plot is not perfectly flat and
the tile's floor is not the datum. A camera placed at eye height above z=0
ends up UNDER the mesh looking at roof undersides. The fix is the same
discipline as the geoid: MEASURE the ground (2nd-percentile z of the cropped
verts, as scanin.ground_to_zero already does) and stand the camera on that,
not on an assumed zero. Left as build_scene()'s one TODO.
"""
import json
import math
import os
import sys
import urllib.parse


ROOT_URL = "https://tile.googleapis.com/v1/3dtiles/root.json"
BASE = "https://tile.googleapis.com"

# UK geoid-ellipsoid separation. Varies ~45-50m across GB; 48 is a safe
# central value for reaching a building, where the tile boxes are metres
# wide and a few metres of vertical slack is inside the pad anyway. A
# per-site value (from an OSGM lookup) would be more exact but is not needed
# to make the descent land.
GEOID_SEPARATION_M = 48.0

# Below this geometric error a tile is street-level detail — a house reads.
# 6m keeps a couple of levels of margin over the ~2m Google actually serves,
# so the walk still lands if the finest layer is a touch coarser here.
LEAF_ERROR_M = 6.0

# Bounding-box padding. At depth the target-containing tiles are only metres
# across; 1.30 tolerates the geoid slack and datum wobble without pulling in
# the whole street. 1.05 lost two levels of descent in testing.
BOX_PAD = 1.30

MAX_FETCH = 400
PLOT_HALF_M = 26.0        # crop half-extent: plot + immediate neighbours


def api_key():
    return os.environ.get("GOOGLE_SOLAR_API_KEY") or \
        os.environ.get("GOOGLE_AI_API_KEY") or ""


def ecef(lat, lon, h):
    """Earth-centred earth-fixed metres. h is ELLIPSOID height — see the
    module docstring; feed it ground_od_m + GEOID_SEPARATION_M, never the
    Ordnance Datum height on its own."""
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    la, lo = math.radians(lat), math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((N + h) * math.cos(la) * math.cos(lo),
            (N + h) * math.cos(la) * math.sin(lo),
            (N * (1 - e2) + h) * math.sin(la))


def enu_basis(lat, lon):
    """East/North/Up unit vectors at a point, rows of the ECEF->ENU rotation."""
    la, lo = math.radians(lat), math.radians(lon)
    east = (-math.sin(lo), math.cos(lo), 0.0)
    north = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo),
             math.cos(la))
    up = (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo),
          math.sin(la))
    return east, north, up


def _in_box(box, p, pad=BOX_PAD):
    """Oriented-bounding-box containment. box = [cx,cy,cz, x-axis, y-axis,
    z-axis] as 3D Tiles gives it."""
    c = box[0:3]
    d = [p[i] - c[i] for i in range(3)]
    for k in (3, 6, 9):
        ax = box[k:k + 3]
        L = math.sqrt(sum(v * v for v in ax))
        if L == 0:
            continue
        if abs(sum(d[i] * ax[i] for i in range(3)) / L) > L * pad:
            return False
    return True


def _contains(node, p):
    box = (node.get("boundingVolume") or {}).get("box")
    return True if not box else _in_box(box, p)


class Walker:
    """Descends the REPLACE-refined tile tree, keeping only the deepest mesh
    that still contains the target — a parent is a COARSER copy of its
    children, so only the leaf is worth downloading."""

    def __init__(self, target_ecef, out_dir, key=None):
        self.target = target_ecef
        self.out = out_dir
        self.key = key or api_key()
        self.session = None
        self.glbs = []
        self.fetches = 0
        os.makedirs(out_dir, exist_ok=True)

    def _url(self, uri):
        q = {"key": self.key}
        s = urllib.parse.parse_qs(urllib.parse.urlparse(uri).query)
        if s.get("session"):
            self.session = s["session"][0]     # sessions carry down the tree
        if self.session:
            q["session"] = self.session
        full = uri if uri.startswith("http") else BASE + uri
        sep = "&" if "?" in full else "?"
        return full + sep + urllib.parse.urlencode(q)

    def _fetch(self, uri):
        if self.fetches >= MAX_FETCH:
            return None
        self.fetches += 1
        import requests
        try:
            r = requests.get(self._url(uri), timeout=60)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"  tiles: skip {type(e).__name__} {uri[:60]}",
                  file=sys.stderr)
            return None

    def _descend(self, node, depth=0):
        if not _contains(node, self.target) or depth > 32:
            return False
        err = node.get("geometricError", 1e18)
        kept_below = False
        for c in (node.get("children") or []):
            kept_below |= self._descend(c, depth + 1)

        cont = node.get("content") or {}
        uri = cont.get("uri") or cont.get("url")
        if not uri:
            return kept_below

        if uri.split("?")[0].endswith(".json"):
            r = self._fetch(uri)
            if r is None:
                return kept_below
            sub = r.json()
            return self._descend(sub.get("root") or sub, depth + 1) \
                or kept_below

        # A mesh: keep only where nothing finer was kept below and this is
        # already street-level detail.
        if kept_below or err > LEAF_ERROR_M:
            return kept_below
        r = self._fetch(uri)
        if r is None:
            return kept_below
        path = os.path.join(self.out, f"tile_{len(self.glbs):03d}.glb")
        with open(path, "wb") as f:
            f.write(r.content)
        self.glbs.append(path)
        print(f"  tiles: keep err={err:.2f}m depth={depth} {len(r.content)}B")
        return True

    def run(self):
        r = self._fetch(ROOT_URL)
        if r is None:
            return []
        doc = r.json()
        self._descend(doc.get("root") or doc)
        return self.glbs


def fetch_house(lat, lon, ground_od_m, out_dir, key=None):
    """The captured mesh tiles for one address, or [].

    ground_od_m is Solar's measured ground height (Ordnance Datum). The geoid
    correction to ellipsoid height happens HERE — callers pass the OD number
    they already have and never think about datums.
    """
    key = key or api_key()
    if not key:
        return []
    h = (ground_od_m or 0.0) + GEOID_SEPARATION_M
    return Walker(ecef(lat, lon, h), out_dir, key=key).run()


# The Blender-side transform + crop + render. A STRING run in a subprocess,
# never imported — the GPL boundary blend.py documents, and bpy pins numpy<2
# which the rest of the worker cannot take. Kept here so the whole tiles
# path is one file.
STREET_SCENE = r'''
import bpy, sys, math, glob, bmesh
from mathutils import Vector, Matrix

out, td, lat, lon, h, front_deg, half = (
    sys.argv[-7], sys.argv[-6], float(sys.argv[-5]), float(sys.argv[-4]),
    float(sys.argv[-3]), float(sys.argv[-2]), float(sys.argv[-1]))

def ecef(la_, lo_, hh):
    a, f = 6378137.0, 1/298.257223563; e2 = f*(2-f)
    la, lo = math.radians(la_), math.radians(lo_)
    N = a/math.sqrt(1-e2*math.sin(la)**2)
    return Vector(((N+hh)*math.cos(la)*math.cos(lo),
                   (N+hh)*math.cos(la)*math.sin(lo),
                   (N*(1-e2)+hh)*math.sin(la)))

bpy.ops.wm.read_factory_settings(use_empty=True)
for f_ in sorted(glob.glob(td + "/*.glb")):
    bpy.ops.import_scene.gltf(filepath=f_)
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']

T = ecef(lat, lon, h)
la, lo = math.radians(lat), math.radians(lon)
east  = Vector((-math.sin(lo), math.cos(lo), 0.0))
north = Vector((-math.sin(la)*math.cos(lo), -math.sin(la)*math.sin(lo), math.cos(la)))
up    = Vector(( math.cos(la)*math.cos(lo),  math.cos(la)*math.sin(lo), math.sin(la)))
R = Matrix((east, north, up))
# NO extra rotation: Blender world space is already ECEF (see tiles.py).
for o in objs:
    mw = o.matrix_world
    for v in o.data.vertices:
        v.co = R @ ((mw @ v.co) - T)
    o.matrix_world = Matrix.Identity(4)
    bm = bmesh.new(); bm.from_mesh(o.data)
    dead = [fa for fa in bm.faces
            if abs(fa.calc_center_median().x) > half
            or abs(fa.calc_center_median().y) > half]
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    bm.to_mesh(o.data); bm.free()

# Ground is MEASURED, not assumed — the plot floor sits near z=+2 in this
# frame (the tile's zero is not the datum), and a camera at an assumed zero
# ends up under the mesh. 2nd percentile, robust to floaters, like Scan Mode.
zs = sorted(v.co.z for o in objs for v in o.data.vertices)
ground = zs[max(0, int(len(zs)*0.02))] if zs else 0.0

# SHOOT AT THE ANGLE WHERE PHOTOGRAMMETRY HOLDS UP. Google's mesh is aircraft
# capture: it has almost no data on VERTICAL faces, so a low, near-horizontal
# camera renders the walls as melted curtains (learned the hard way — a
# street-level shot of this mesh is unusable). A HIGH oblique — ~55 deg above
# the horizon, the angle Google Earth itself uses — looks down mostly onto
# roofs and ground, which the mesh HAS, so it reads cleanly: roofs, the yard,
# boundaries, neighbours, all real. This is a context/massing view, not a
# sharp ground elevation; the vertical faces still need a ground photo.
b = math.radians(front_deg)
pitch = math.radians(55.0)
dist = 42.0
ctr = Vector((0.0, 0.0, ground + 3.0))
w = bpy.data.worlds.new("w"); bpy.context.scene.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs[1].default_value = 3.0
eye = ctr + Vector((math.sin(b)*dist*math.cos(pitch),
                    math.cos(b)*dist*math.cos(pitch),
                    dist*math.sin(pitch)))
bpy.ops.object.camera_add(location=eye)
cam = bpy.context.active_object; cam.data.lens = 40
cam.rotation_euler = (ctr-eye).to_track_quat('-Z','Y').to_euler()
bpy.context.scene.camera = cam
sc = bpy.context.scene
sc.render.engine='CYCLES'; sc.cycles.device='CPU'; sc.cycles.samples=18
sc.render.resolution_x=1100; sc.render.resolution_y=1000
sc.view_settings.view_transform='Standard'
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print("TILES_STREET_OK ground=%.2f" % ground)
'''


def build_scene(tile_dir, out_png, lat, lon, ground_od_m,
                front_bearing_deg, python=None, half_m=PLOT_HALF_M):
    """Render the cropped captured mesh from the pavement. Returns out_png or
    None. `python` is the bpy interpreter (subprocess, GPL boundary)."""
    import subprocess
    import tempfile
    exe = python or sys.executable
    h = (ground_od_m or 0.0) + GEOID_SEPARATION_M
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(STREET_SCENE)
        script = f.name
    try:
        r = subprocess.run(
            [exe, script, "--", out_png, tile_dir, str(lat), str(lon),
             str(h), str(front_bearing_deg), str(half_m)],
            capture_output=True, text=True, timeout=600)
        ok = "TILES_STREET_OK" in r.stdout
        if not ok:
            print(r.stdout[-500:], r.stderr[-500:], file=sys.stderr)
        return out_png if ok else None
    finally:
        os.unlink(script)


if __name__ == "__main__":
    # Standalone: python tiles.py <out_dir> [lat] [lon] [ground_od_m]
    out = sys.argv[1]
    lat = float(sys.argv[2]) if len(sys.argv) > 2 else 52.490637625
    lon = float(sys.argv[3]) if len(sys.argv) > 3 else -1.996275446
    gnd = float(sys.argv[4]) if len(sys.argv) > 4 else 184.81
    g = fetch_house(lat, lon, gnd, out)
    print("TILES", len(g))
