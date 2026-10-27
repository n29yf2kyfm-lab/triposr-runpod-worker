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
