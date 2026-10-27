"""The car machine's rules that went wrong in the 1,000-vehicle run, each
tested against the case that showed it, and the cases it must leave alone.

    python3 -m pytest pipeline/realcar/test_rules.py -q
"""
import json
import os
import struct
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import finish  # noqa: E402
import make  # noqa: E402


# ── material names ───────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["internal", "Interior", "Carro_Interno", "seat_leather", "Material.int", "paint_int"])
def test_an_inside_by_its_name(name):
    assert finish.INSIDE.search(name)


@pytest.mark.parametrize("name", ["carpaint.198", "rrghost_paint.001", "Paint", "phong7_paint", "print", "tint_glass"])
def test_no_inside_in_a_paint_name(name):
    # "int." in "carpaint.198" once read as an inside: the GL-Class and RCZ paint lost half its weight
    assert not finish.INSIDE.search(name)


@pytest.mark.parametrize("name", ["carpaint", "Main_Color_paint", "Paint1", "Lack_rot", "Carpaint_Simple_Ruby.004"])
def test_a_paint_by_its_name(name):
    assert finish.PAINT_NAME.search(name)


@pytest.mark.parametrize("name", ["black", "Black1", "black_trim", "M_2022_Suzuki_Swift_SWIFT_ZP_EX_WHEEL_BLACK_MAT",
                                  "CabrioM_Opaque_PlasticRoughBlack_Max1"])
def test_black_is_no_paint(name):
    # the "lack" (German: paint) in "black" painted black trim the body colour on 32 cars
    assert not finish.PAINT_NAME.search(name)


@pytest.mark.parametrize("name", ["M_2022_Suzuki_Swift_SWIFT_ZP_EX_WHEEL_BLACK_MAT", "wheel_rim", "rims", "Tyre", "hubcap"])
def test_a_wheel_by_its_name(name):
    assert finish.WHEELISH.search(name)


def _mat(name, rgb):
    lin = [(c / 255) ** 2.2 for c in rgb]
    return {"name": name, "pbrMetallicRoughness": {"baseColorFactor": lin + [1.0]}}


def test_a_wheel_in_the_paints_colour_is_not_painted_but_blacked():
    # the 2022 Swift's wheel material is its own paint's red: it was painted
    # white on a white Celerio, then showed red rims once it was not
    mats = [_mat("Pearl_Ablaze_Red_paint", (177, 6, 38)), _mat("SWIFT_WHEEL_BLACK_MAT", (175, 8, 36)),
            _mat("door_trim_red", (178, 7, 37))]
    assert finish.same_paint(mats, 0, set()) == {2}
    assert finish.wheels_in_paint(mats, 0, set()) == {1}


# ── words in a request or a title ────────────────────────────────────────

@pytest.mark.parametrize("req,body", [
    ("BMW 3 Series M Sport Touring 2019", "estate"),       # BMW's estate, broken once by the rule below
    ("BMW 5 Series Touring", "estate"),
    ("Audi A4 Avant", "estate"),
    ("Nissan 370Z Sport Touring", None),                    # a trim, not an estate
    ("Honda Civic Sport Touring", None),
    ("Porsche 911 GT3 Touring", None),
])
def test_estate_words(req, body):
    assert make.parse(req).get("body") == body


@pytest.mark.parametrize("model", ["V Class", "Multivan", "Caravelle", "Tourneo Custom", "Rifter", "Berlingo", "SpaceTourer",
                                   "Traveller", "Viano", "Qubo"])
def test_a_people_carrier_on_a_vans_body(model):
    assert make.PASSENGER_MODEL.search(model)


@pytest.mark.parametrize("model", ["Transit", "Sprinter", "Ducato", "Master", "Movano", "Golf"])
def test_no_people_carrier(model):
    assert not make.PASSENGER_MODEL.search(model)


def test_the_proace_city_verso_is_the_berlingos_twin_not_the_spacetourers():
    pattern, face = make.TWIN[("toyota", "proace-city-verso")]
    assert pattern.search("berlingo") and pattern.search("rifter") and pattern.search("combo life")
    assert not pattern.search("spacetourer") and face == "citroen"


# ── a mesh's broken shading ──────────────────────────────────────────────

def _glb(path, positions, normals, indices):
    """A one-mesh GLB: positions and normals (float32), indices (uint32), one material."""
    P, N, I = np.asarray(positions, np.float32), np.asarray(normals, np.float32), np.asarray(indices, np.uint32)
    blob = P.tobytes() + N.tobytes() + I.tobytes()
    j = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
         "materials": [{"name": "carpaint"}],
         "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
         "buffers": [{"byteLength": len(blob)}],
         "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": P.nbytes},
                         {"buffer": 0, "byteOffset": P.nbytes, "byteLength": N.nbytes},
                         {"buffer": 0, "byteOffset": P.nbytes + N.nbytes, "byteLength": I.nbytes}],
         "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(P), "type": "VEC3",
                        "min": P.min(0).tolist(), "max": P.max(0).tolist()},
                       {"bufferView": 1, "componentType": 5126, "count": len(N), "type": "VEC3"},
                       {"bufferView": 2, "componentType": 5125, "count": I.size, "type": "SCALAR"}]}
    js = json.dumps(j).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fh.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


def test_triangles_lit_from_inside_are_mended_and_the_rest_left(tmp_path):
    from gltf import GLTF
    # two panels facing +z; the second one's corners point down -z (the Sprinter's grey quarter)
    P = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [2, 0, 0], [3, 0, 0], [2, 1, 0]]
    N = [[0, 0, 1]] * 3 + [[0, 0, -1]] * 3
    _glb(str(tmp_path / "m.glb"), P, N, [0, 1, 2, 3, 4, 5])
    g = GLTF(str(tmp_path / "m.glb"))
    assert finish.mend_normals(g, {0}) == 1
    prims = g.j["meshes"][0]["primitives"]
    assert len(prims) == 2
    kept = g.accessor(prims[0]["indices"]).ravel()
    assert list(kept) == [0, 1, 2]
    new_n = g.accessor(prims[1]["attributes"]["NORMAL"])
    assert np.allclose(new_n, [[0, 0, 1]] * 3)            # flat, by the face


def test_a_mesh_shaded_its_own_way_all_over_is_left(tmp_path):
    from gltf import GLTF
    P = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    _glb(str(tmp_path / "m.glb"), P, [[0, 0, -1]] * 3, [0, 1, 2])
    g = GLTF(str(tmp_path / "m.glb"))
    assert finish.mend_normals(g, {0}) == 0


# ── a stand-in's roof in its donor's colour ──────────────────────────────

def _car_glb(path, top_name="2020_Peugeot_e-2008_black", roof_mat=1, slope=0.0, roof_side=False, flat_strip=False,
            windscreen=False, hidden_glass=False, glass_roof=False, side_window=False):
    """A box car 4 m long, 1.8 m wide, 1.52 m high: painted sides, a roof in
    another material, a thin roof rail in it too, and a wheel. WINDSCREEN: a
    raked one ahead of the roof, two triangles of glass, trims of the roof's
    material along its sides joined to it, an A-pillar of it away from the
    glass, and a black band lying on it.
    HIDDEN_GLASS: the roof's front edge a row of small triangles over glass
    running on under it, every other one of them near it. GLASS_ROOF: a flat
    glass roof a centimetre under the roof's skin. SIDE_WINDOW: a side window
    under the roof's side, and a pillar of the roof's material beside it."""
    from gltf import GLTF  # noqa: F401
    def quad(x0, x1, y0, y1, z0, z1, axis):
        if axis == "y":
            P = [[x0, y0 - slope, z0], [x1, y0 - slope, z0], [x1, y0, z1], [x0, y0, z1]]
            I = [0, 2, 1, 0, 3, 2]                          # facing up (+y)
        else:
            P = [[x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]]
            I = [0, 1, 2, 0, 2, 3]
        return P, I
    roof = quad(-0.7, 0.7, 1.5, 1.5, 1, 2.9 if hidden_glass else 3, "y")
    if hidden_glass:                                      # the front edge, z 2.9 to 3: ten teeth up, nine down
        xs = np.linspace(-0.7, 0.7, 11)
        fp = [[x, 1.5, 3.0] for x in xs] + [[(a + b) / 2, 1.5, 2.9] for a, b in zip(xs[:-1], xs[1:])]
        fi = []
        for k in range(10):
            fi += [k, k + 1, 11 + k]                      # a tooth on the front edge, over the glass
            if k < 9:
                fi += [k + 1, 12 + k, 11 + k]             # one between, behind it
        roof = (roof[0] + fp, roof[1] + [i + 4 for i in fi])
    if roof_side:                                         # the roof's own side, upright, in the same piece
        sp, si = quad(0.7, 0.7, 1.3, 1.5, 1, 3, "x")
        roof = (roof[0] + sp, roof[1] + [i + 4 for i in si])
    if flat_strip:                                        # a flat strip on its top end, in the same piece
        fp = [[-0.7, 1.5, 3.0], [0.7, 1.5, 3.0], [0.7, 1.5, 3.2], [-0.7, 1.5, 3.2]]
        roof = (roof[0] + fp, roof[1] + [4, 6, 5, 4, 7, 6])
    def raked(x0, x1, z1=3.6, lift=0.0):                  # from the roof's front edge down to z1, facing up and forward
        n = np.array([0, 0.6, 0.3]) / np.linalg.norm([0, 0.6, 0.3]) * lift
        y1 = 1.5 - 0.5 * (z1 - 3.0)
        return [list(np.add(q, n)) for q in ([x0, 1.5, 3.0], [x1, 1.5, 3.0], [x1, y1, z1], [x0, y1, z1])], [0, 3, 1, 1, 3, 2]
    extra = []
    if glass_roof:                                        # flat, 1 cm under the skin (the bZ4X's)
        extra += [("body", [[-0.6, 1.49, 1.2], [0.6, 1.49, 1.2], [0.6, 1.49, 2.8], [-0.6, 1.49, 2.8]], [0, 2, 1, 0, 3, 2], 3)]
    if side_window:                                       # upright, its top 5 cm under the roof's side
        extra += [("body", *quad(0.72, 0.72, 0.95, 1.25, 1.2, 2.8, "x"), 3)]
        pp, pi = quad(0.7, 0.7, 0.95, 1.25, 1.95, 2.05, "x")   # a pillar beside it, in the roof's piece
        roof = (roof[0] + pp, roof[1] + [i + len(roof[0]) for i in pi])
    if hidden_glass:                                      # the windscreen's top, on under the roof's edge
        extra += [("body", [[-0.7, 1.48, 3.0], [0.7, 1.48, 3.0], [0.7, 1.497, 2.97], [-0.7, 1.497, 2.97]],
                  [0, 3, 1, 1, 3, 2], 3)]
    if windscreen:
        for x0, x1 in ((0.6, 0.62), (-0.62, -0.6), (0.66, 0.7)):  # trims along its sides, a pillar, in the roof's piece
            ap, ai = raked(x0, x1)
            roof = (roof[0] + ap, roof[1] + [i + len(roof[0]) for i in ai])
        extra += [("body", *raked(-0.6, 0.6), 3),          # the windscreen: two triangles
                 ("body", *raked(-0.5, 0.5, z1=3.1, lift=0.002), roof_mat)]   # its black band, on the glass
    parts = [("body", *quad(0.9, 0.9, 0.3, 1.2, 0, 4, "x"), 0), ("body", *quad(-0.9, -0.9, 0.3, 1.2, 0, 4, "x"), 0),
             ("body", *roof, roof_mat),                   # the roof: 2.8 m², 39% of the footprint
             ("body", *quad(0.75, 0.8, 1.52, 1.52, 1, 3, "y"), 1),        # a rail: 0.1 m², 1.4%
             ("wheel_fl", *quad(0.9, 0.9, 0.0, 0.6, 3.2, 3.8, "x"), 2)] + extra
    blob, views, accs, prims = b"", [], [], []
    for name, P, I, mat in parts:
        P, I = np.asarray(P, np.float32), np.asarray(I, np.uint32)
        for arr, typ, ct in ((P, "VEC3", 5126), (I, "SCALAR", 5125)):
            views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes})
            acc = {"bufferView": len(views) - 1, "componentType": ct, "count": len(arr) if typ == "VEC3" else arr.size, "type": typ}
            if typ == "VEC3":
                acc.update(min=P.min(0).tolist(), max=P.max(0).tolist())
            accs.append(acc)
            blob += arr.tobytes()
        prims.append((name, {"attributes": {"POSITION": len(accs) - 2}, "indices": len(accs) - 1, "material": mat}))
    nodes, meshes = [], []
    for name, p in prims:
        meshes.append({"primitives": [p]})
        nodes.append({"name": name, "mesh": len(meshes) - 1})
    j = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes,
         "materials": [{"name": "Bianca_White_paint"}, {"name": top_name}, {"name": "tyre"},
                       {"name": "windscreen", "alphaMode": "BLEND"}], "meshes": meshes,
         "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accs}
    js = json.dumps(j).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fh.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


def test_a_stand_ins_black_roof_takes_the_paint_and_its_rails_keep_theirs(tmp_path):
    # the bZ4X's and the 2008's black roofs on the white Fiat 600, Lexus RZ, Omoda 9 (build review)
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"))
    g = GLTF(str(tmp_path / "c.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, set())
    assert out and out["triangles"] == 2 and out["materials"] == ["2020_Peugeot_e-2008_black"]
    mats = [p["material"] for m in g.j["meshes"] for p in m["primitives"]]
    assert mats == [0, 0, 0, 1, 2]                        # the roof painted, the rail and the wheel left


def test_a_roofs_sides_down_to_the_windows_are_painted_its_pillars_are_not(tmp_path):
    # round 3: a roof-named piece painted whole spilt down the pillars; its top
    # alone left the Captur's sides black down to the windows, a two-tone roof
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"), top_name="BlackRoof", roof_side=True)
    g = GLTF(str(tmp_path / "c.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, set())
    assert out and out["triangles"] == 2                 # no side window: no line to paint down to
    _car_glb(str(tmp_path / "s.glb"), top_name="BlackRoof", roof_side=True, side_window=True)
    g = GLTF(str(tmp_path / "s.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, set())
    assert out and out["triangles"] == 4                 # the top and its side; not the pillar


def test_a_roof_over_a_flat_glass_roof_is_painted_whole(tmp_path):
    # the bZ4X's black roof lies a centimetre over a glass roof: taken for a
    # trim on the glass, two thirds of it were left black (round 4)
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"), glass_roof=True)
    g = GLTF(str(tmp_path / "c.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, {3})
    assert out and "2020_Peugeot_e-2008_black" in out["materials"]
    roof = g.j["meshes"][g.j["nodes"][2]["mesh"]]["primitives"]
    assert [p["material"] for p in roof] == [0]           # all of it, not a triangle left black


def test_a_glass_roof_is_dark_and_the_windscreen_clear(tmp_path):
    # cleared like the windows, the Model Y's glass roof showed its headliner:
    # a white roof on the Polestar 3, whose photo's roof is black (round 4)
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"), glass_roof=True, windscreen=True)
    g = GLTF(str(tmp_path / "c.glb"))
    mats = g.j["materials"]
    out = finish.roof_glass_dark(g, mats, {3})
    assert out and out["m2"] == 1.92                     # the roof's 1.2 x 1.6 m
    dark = [i for i, m in enumerate(mats) if m.get("name") == "roof_glass"]
    used = [p["material"] for m in g.j["meshes"] for p in m["primitives"]]
    assert len(dark) == 1 and used.count(dark[0]) == 1 and used.count(3) == 1   # the windscreen still glass


def test_what_lies_on_the_glass_is_never_painted(tmp_path):
    # round 3: a windscreen's black band (the Fiat 600's, its glass two big
    # triangles, so far from their corners), the trims along it and the
    # A-pillars joined to the roof were painted with it, patches of body
    # colour on the windscreen and the pillars
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"), windscreen=True)
    g = GLTF(str(tmp_path / "c.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, set())
    assert out and out["triangles"] == 2                 # the roof alone
    by_node = [(n["name"], p["material"]) for n in g.j["nodes"] for p in g.j["meshes"][n["mesh"]]["primitives"]]
    assert by_node[-1] == ("body", 1)                    # the band keeps its black
    assert ("body", 3) in by_node                        # the glass its own


def test_a_roofs_edge_over_glass_running_on_under_it_is_painted_whole(tmp_path):
    # the RAV4's windscreen runs on under the roof: its front edge, triangle
    # by triangle near the glass or not, was left a saw's teeth of black
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"), hidden_glass=True)
    g = GLTF(str(tmp_path / "c.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, set())
    assert out and out["triangles"] == 2 + 19             # the roof and its whole edge


def test_a_roof_sloping_to_the_tail_is_painted_to_its_end(tmp_path):
    # the Captur's and the RAV4's black roofs: the top tenth of the car only took the front of them
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"), slope=0.25)
    g = GLTF(str(tmp_path / "c.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, set())
    assert out and out["triangles"] == 2
    assert [p["material"] for m in g.j["meshes"] for p in m["primitives"]][2] == 0


def test_a_flat_glass_roof_is_a_roof_and_a_raked_pane_is_not(tmp_path):
    # the 207's dark panoramic roof on the DS3 made from it, whose photo's roof is white
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"), top_name="panoramic_glass_roof")
    g = GLTF(str(tmp_path / "c.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, {1})
    assert out and out["materials"] == ["panoramic_glass_roof"]
    # glass raked like a windscreen (24 degrees and more): never painted
    _car_glb(str(tmp_path / "d.glb"), top_name="windscreen_glass", slope=0.9)
    g = GLTF(str(tmp_path / "d.glb"))
    assert finish.roof_in_paint(g, g.j["materials"], 0, {0}, {1}) is None
    # nor a raked pane whose top strip lies flat (a windscreen curving into the
    # roof: the Fiat 600's mirror-mount patch): judged as a whole pane
    _car_glb(str(tmp_path / "e.glb"), top_name="windscreen_glass", slope=0.9, flat_strip=True)
    g = GLTF(str(tmp_path / "e.glb"))
    assert finish.roof_in_paint(g, g.j["materials"], 0, {0}, {1}) is None


def test_a_white_roof_asked_is_painted_white_on_a_roof_in_the_body_paint(tmp_path):
    # the Captur's and the Mini First's photos: a white roof on a blue body
    from gltf import GLTF
    _car_glb(str(tmp_path / "c.glb"), roof_mat=0)
    g = GLTF(str(tmp_path / "c.glb"))
    out = finish.roof_in_paint(g, g.j["materials"], 0, {0}, set(), colour=(245, 245, 242))
    assert out and out["triangles"] == 2
    roof = g.j["materials"][-1]
    assert roof["name"] == "Bianca_White_paint_roof" and roof["pbrMetallicRoughness"]["baseColorFactor"][0] > 0.85
    mats = [p["material"] for m in g.j["meshes"] for p in m["primitives"]]
    assert mats == [0, 0, len(g.j["materials"]) - 1, 1, 2]
    # with no colour asked, a roof in the body's paint is the paint: nothing to do
    _car_glb(str(tmp_path / "d.glb"), roof_mat=0)
    g = GLTF(str(tmp_path / "d.glb"))
    assert finish.roof_in_paint(g, g.j["materials"], 0, {0}, set()) is None


@pytest.mark.parametrize("text, colour, roof", [
    ("Mini Cooper blue with a white roof", "blue", "white"),
    ("Mini Cooper white with a contrast roof", "white", "contrast"),
    ("Fiat 500 two-tone red", "red", "contrast"),
    ("Nissan Juke blue with body coloured roof", "blue", "body"),
    ("Peugeot 2008 black", "black", None),               # the paint, not a roof
    ("Renault Captur #106baf #eeefed roof", "#106baf", "#eeefed"),     # the fleet's: the photo's paint and roof
])
def test_the_roof_asked_for_is_read_before_the_paint(text, colour, roof):
    w = make.parse(text)
    assert w.get("colour") == colour and w.get("roof") == roof


# ── a low-roof van made from a high-roof one ─────────────────────────────

SPRINTER = {"R": 0.34, "zf": -0.917, "zr": -4.69, "wheelbase": 3.773, "zmin": -6.066, "zmax": 0.006, "length": 6.072,
            "width": 2.098, "height": 2.388, "cab_top": 1.898, "track": 1.526}


def test_a_low_roof_van_takes_its_height_out_of_a_high_roof_donors_roof():
    # every Transit, Transit Custom and iLoad made from the Sprinter still looked a high-roof van (build review)
    import standin
    t = {"length": 4863, "wheelbase": 2933, "width": 1974, "height": 2083, "body": "van"}
    p = standin.plan(SPRINTER, t)
    rise = p["log"]["roof_lowered"]["roof_over_windscreen_m"]
    assert rise[0] == 0.49 and rise[1] < 0.25
    assert abs(float(p["y"](SPRINTER["height"])) - 2.083) < 1e-6          # the published height kept
    # a high-roof van asked, a tall one, or a car: the even stretch as before
    for t2 in (dict(t, high_roof=True), dict(t, height=2524), dict(t, body="mpv")):
        assert "roof_lowered" not in standin.plan(SPRINTER, t2)["log"]
