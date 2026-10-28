"""Tests for the vehicle model's own code: no image encoder needed (a stand-in gives the numbers).

    python3 -m pytest pipeline/realcar/ai/test_ai.py -q
"""
import json
import os
import sys

import numpy as np
import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import heads as H  # noqa: E402
import predict  # noqa: E402
import vision  # noqa: E402

HEADS = os.path.join(HERE, "heads.json")


def test_a_wide_photo_is_padded_whole_not_cropped():
    # a car photo is wide; its nose or tail at the edge is what tells its side
    im = Image.new("RGB", (600, 300), (128, 128, 128))
    im.paste((255, 0, 0), (0, 0, 30, 300))
    a = vision.prep(im)
    assert a.shape == (3, 224, 224)
    red = (np.array([1.0, 0, 0]) - vision.MEAN) / vision.STD
    assert np.allclose(a[:, 112, 2], red, atol=0.05)            # the left edge is still there
    assert np.allclose(a[:, 5, 112], 0, atol=0.02)              # padded above, in CLIP's mean colour


def test_a_cut_out_is_read_on_white():
    im = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    p = os.path.join(os.environ.get("TMPDIR", "/tmp"), "vehicle_ai_cut.png")
    im.save(p)
    assert vision.load(p).getpixel((5, 5)) == (255, 255, 255)


def test_lab_is_opencvs_8_bit_lab():
    lab = H.lab([[255, 255, 255], [0, 0, 0], [255, 0, 0]])
    assert np.allclose(lab[0], [255, 128, 128], atol=1)
    assert np.allclose(lab[1], [0, 128, 128], atol=1)
    assert np.allclose(lab[2], [136, 208, 195], atol=1.5)       # cv2.cvtColor's red


def test_a_head_gives_probabilities_as_sklearn_does():
    LogisticRegression = pytest.importorskip("sklearn.linear_model").LogisticRegression
    rng = np.random.default_rng(0)
    X = rng.normal(size=(60, 5))
    for y in ([0, 1] * 30, [0, 1, 2] * 20):
        m = LogisticRegression(C=10, max_iter=5000).fit(X, y)
        h = H.Head(m.classes_.tolist(), m.coef_, m.intercept_)
        assert np.allclose(h.proba(X), m.predict_proba(X), atol=1e-5)
        h2 = H.Head.from_json(json.loads(json.dumps(h.to_json())))
        assert np.allclose(h2.proba(X), m.predict_proba(X), atol=1e-4)


def test_a_mirrored_picture_reads_the_other_side():
    rng = np.random.default_rng(1)
    h = H.Head(["left", "right"], rng.normal(size=(1, 8)), [0.3])
    e, ef = rng.normal(size=(4, 8)), rng.normal(size=(4, 8))
    assert np.allclose(H.side_proba(h, e, ef), H.side_proba(h, ef, e)[:, ::-1])


def test_next_shades():
    paint = json.load(open(HEADS))["card"]["paint"]
    assert predict.next_shade(paint, "grey", "dark-grey")
    assert predict.next_shade(paint, "white", "pearl-white")
    assert not predict.next_shade(paint, "red", "blue")
    assert not predict.next_shade(paint, "white", "black")


def test_the_trained_heads_are_whole():
    hs, card = H.load_heads(HEADS)
    assert set(hs) == {"colour", "side", "kind", "match"}
    assert hs["side"].classes == ["left", "right"]
    assert set(hs["kind"].classes) == {"car", "van", "motorbike"}
    assert set(hs["colour"].classes) <= set(card["paint"])
    assert hs["colour"].W.shape[1] == 512 + int(np.prod(H.HIST_BINS))
    assert hs["match"].W.shape[1] == 1024
    assert card["encoder_sha256"] == vision.ENCODERS["clip-b32"][3]
    for k in ("colour_photo", "side_photo", "kind_photo", "match_pairs"):
        assert k in card["held_out_scores"]


class _Enc:
    """Stands in for the encoder: a picture's numbers are what the test gives it."""
    path = "stand-in"

    def __init__(self, table):
        self.table = table

    def embed(self, images, flip=False):
        return np.stack([self.table[(im.size, flip)] for im in images])


def test_check_flags_a_build_that_is_not_the_photos_vehicle(tmp_path):
    hs, card = H.load_heads(HEADS)
    rng = np.random.default_rng(2)
    a, b = rng.normal(size=512), rng.normal(size=512)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    ph, bu = tmp_path / "p.jpg", tmp_path / "b.png"
    Image.new("RGB", (60, 40), (200, 30, 30)).save(ph)
    Image.new("RGB", (50, 40), (200, 30, 30)).save(bu)
    ai = predict.VehicleAI.__new__(predict.VehicleAI)
    ai.heads, ai.card, ai.th, ai.paint = hs, card, card["thresholds"], card["paint"]
    ai.enc = _Enc({((60, 40), False): a, ((60, 40), True): a[::-1], ((50, 40), False): b, ((50, 40), True): b[::-1]})
    same = ai.check(str(ph), str(ph))
    other = ai.check(str(ph), str(bu))
    assert same["match"] > other["match"]
    assert other["answer"] == "look" and any(f.startswith("shape") for f in other["flags"])
    assert not any(f.startswith("shape") for f in same["flags"])


def test_the_held_out_draw_is_fixed():
    import dataset
    keys = [f"k{i}" for i in range(500)]
    assert dataset.split(keys) == dataset.split(list(reversed(keys)))
    assert len(dataset.split(keys)) == 100


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
