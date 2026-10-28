"""Tests for the vehicle model's own code: no image encoder needed (the tests give the numbers).

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


def test_a_cut_out_is_cropped_to_its_vehicle_and_read_on_white(tmp_path):
    # a build's full studio picture and its small copy (webp.py) frame the car differently:
    # both are read cropped to it, so they read alike
    big = Image.new("RGBA", (1600, 1000), (0, 0, 0, 0))
    big.paste((200, 30, 30, 255), (400, 300, 1200, 700))
    small = big.crop((370, 270, 1230, 730)).resize((430, 230))
    big.save(tmp_path / "big.png")
    small.save(tmp_path / "small.png")
    a, b = vision.load(tmp_path / "big.png"), vision.load(tmp_path / "small.png")
    assert abs(a.width / a.height - b.width / b.height) < 0.03
    assert a.getpixel((2, 2)) == (255, 255, 255)
    assert np.abs(vision.prep(a) - vision.prep(b)).mean() < 0.05    # alike but for the box's edge pixels


@pytest.mark.parametrize("make", ["missing", "empty", "text", "cut short", "tiny"])
def test_a_file_that_is_not_a_readable_picture_is_refused_by_name(tmp_path, make):
    p = tmp_path / "x.jpg"
    good = tmp_path / "good.jpg"
    Image.new("RGB", (300, 200), (90, 90, 90)).save(good, quality=95)
    if make == "empty":
        p.write_bytes(b"")
    elif make == "text":
        p.write_text("hello")
    elif make == "cut short":
        p.write_bytes(good.read_bytes()[:300])
    elif make == "tiny":
        Image.new("RGB", (8, 5), "red").save(p)
    with pytest.raises(vision.Unreadable):
        vision.load(p)
    # and the tool reports it, and goes on to the next
    def answer(f):
        vision.load(f)
        return {"file": str(f), "ok": True}
    assert predict.safe(answer, p)["error"]
    assert predict.safe(answer, good) == {"file": str(good), "ok": True}


def test_lab_is_opencvs_8_bit_lab():
    lab = H.lab([[255, 255, 255], [0, 0, 0], [255, 0, 0]])
    assert np.allclose(lab[0], [255, 128, 128], atol=1)
    assert np.allclose(lab[1], [0, 128, 128], atol=1)
    assert np.allclose(lab[2], [136, 208, 195], atol=1.5)       # cv2.cvtColor's red


@pytest.mark.parametrize("paint", ["#efc21a", "#b3131c", "#2a5aa6", "#e2601d", "#eeefed", "#141518"])
def test_the_colour_histogram_counts_every_paint(paint):
    # a strong yellow is b = 206 on this scale, past the histogram's last bin: it used to be left out,
    # so a yellow car's histogram described only its background
    rgb = tuple(int(paint[i:i + 2], 16) for i in (1, 3, 5))
    im = Image.new("RGB", (300, 200), (128, 128, 128))
    im.paste(rgb, (50, 30, 250, 170))                            # the vehicle fills the middle
    h = H.colour_hist(im) ** 2
    assert abs(h.sum() - 1) < 1e-5
    lab = np.clip(H.lab([rgb])[0], [0, 64, 64], [255.999, 191.999, 191.999])
    edges = [np.linspace(lo, hi, n + 1) for (lo, hi), n in zip(H.HIST_RANGE, H.HIST_BINS)]
    i = [min(np.searchsorted(e, v, side="right") - 1, n - 1) for e, v, n in zip(edges, lab, H.HIST_BINS)]
    assert h.reshape(H.HIST_BINS)[tuple(i)] > 0.9                # the paint's own bin holds the middle


def test_a_neutral_colour_is_in_the_middle_of_a_bin_not_on_an_edge():
    # white, grey and black are a = b = 128: on an edge, the last digit of the arithmetic picks the bin
    for (lo, hi), n in list(zip(H.HIST_RANGE, H.HIST_BINS))[1:]:
        edges = np.linspace(lo, hi, n + 1)
        assert np.abs(edges - 128).min() > 5
    for rgb in ((255, 255, 255), (0, 0, 0), (200, 200, 200)):
        assert H.colour_hist(Image.new("RGB", (300, 200), rgb)).max() > 0.99    # all in one bin


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
    assert H.next_shade(paint, "grey", "dark-grey")
    assert H.next_shade(paint, "white", "pearl-white")
    assert not H.next_shade(paint, "red", "blue")
    assert not H.next_shade(paint, "white", "black")


def test_the_trained_heads_are_whole():
    hs, card = H.load_heads(HEADS)
    assert set(hs) == {"colour", "side", "kind", "match"}
    assert hs["side"].classes == ["left", "right"]
    assert set(hs["kind"].classes) == {"car", "van", "motorbike"}
    assert set(hs["colour"].classes) <= set(card["paint"])
    assert hs["colour"].W.shape[1] == 512 + int(np.prod(H.HIST_BINS))
    assert hs["match"].W.shape[1] == 1024
    assert card["encoder_sha256"] == vision.ENCODERS["clip-b32"][3]
    assert set(card["thresholds"]) == {"kind", "side", "colour", "match"}
    for k in ("colour_photo", "side_photo", "kind_photo", "match_pairs"):
        assert k in card["held_out_scores"]


def _feats(rng):
    e = rng.normal(size=512)
    e /= np.linalg.norm(e)
    h = np.zeros(int(np.prod(H.HIST_BINS)), np.float32)
    h[0] = 1
    return e, e[::-1].copy(), h


def test_check_flags_a_build_that_is_not_the_photos_vehicle():
    hs, card = H.load_heads(HEADS)
    rng = np.random.default_rng(2)
    p, b = _feats(rng), _feats(rng)
    same = H.judge(hs, card["thresholds"], card["paint"], p, p)
    other = H.judge(hs, card["thresholds"], card["paint"], p, b)
    assert same["match"] > other["match"]
    assert other["answer"] == "look" and any(f.startswith("shape") for f in other["flags"])
    assert not any(f.startswith("shape") for f in same["flags"])


def test_an_answer_counts_against_a_build_only_when_both_readings_are_sure():
    hs = {"kind": H.Head(["car", "motorbike", "van"], np.eye(3, 4), np.zeros(3)),
          "side": H.Head(["left", "right"], [[1, 0, 0, 0]], [0]),
          "colour": H.Head(["red", "blue"], np.zeros((2, 4 + 1)), [0, 0]),
          "match": H.Head([0, 1], [[0] * 8], [5])}
    paint = {"red": "#b3131c", "blue": "#2a5aa6"}
    car, van = (np.array([9, 0, 0, 0.]), np.array([9, 0, 0, 0.]), np.ones(1)), (np.array([0, 0, 9, 0.]),) * 2 + (np.ones(1),)
    th = {"kind": 0.9, "side": 1.01, "colour": 1.01, "match": 0.5}
    assert any(f.startswith("kind") for f in H.judge(hs, th, paint, car, van)["flags"])
    assert H.judge(hs, {**th, "kind": 1.01}, paint, car, van)["flags"] == []


def test_the_threshold_is_where_answers_are_right_99_in_100():
    import train
    ps = np.linspace(0.5, 1, 200)
    rights = ps > 0.6                     # every answer under 0.6 wrong, every one over right
    assert 0.59 < train.threshold(ps, rights) < 0.62
    assert 0.59 < train.threshold(ps, rights, want=0.97) < 0.62
    assert train.threshold(ps, np.zeros(200, bool)) > 1          # never sure enough: never counts


def test_scores_with_nothing_to_score_are_none_not_a_crash():
    import train
    assert train.auc([], [0.3]) is None and train.r3(None) is None
    assert train.reviewed([(0.9, {"key": "a", "verdict": "ok", "faults": []})], 0.5)["own_model_vs_standin"]["auc"] is None


def test_the_cache_is_another_file_for_another_encoder_or_reading():
    import train
    a = train.cache_file("/c", "ab" * 32)
    assert a != train.cache_file("/c", "cd" * 32)
    assert f"v{H.FEATURES_VERSION}" in a


def test_a_vehicle_keeps_its_fold_when_others_come_and_go():
    import dataset
    keys = [f"k{i}" for i in range(1000)]
    before = {k: dataset.fold(k) for k in keys}
    assert all(dataset.fold(k) == before[k] for k in keys[::7])
    share = np.bincount([before[k] for k in keys], minlength=5) / len(keys)
    assert share.min() > 0.15 and share.max() < 0.25


def test_vehicles_sharing_a_picture_share_a_fold(tmp_path):
    # twins with one photo, a van and its car version with one build: tested on a picture trained on, otherwise
    import dataset
    a, b, c = tmp_path / "a.jpg", tmp_path / "b.jpg", tmp_path / "c.jpg"
    a.write_bytes(b"one photo")
    b.write_bytes(b"another")
    c.write_bytes(b"a third")
    its = [{"key": f"k{i}", "photo": str(a if i in (0, 7) else b if i == 3 else c)} for i in range(12)]
    its[5]["build"] = str(b)
    f = dataset.folds(its)
    assert f["k0"] == f["k7"] and f["k3"] == f["k5"]
    looks = {it["key"]: "0" * 64 for it in its}
    looks["k1"], looks["k2"] = "f" * 64, "f" * 63 + "e"             # one photo saved twice: 1 bit apart
    f = dataset.folds(its, looks={"k1": looks["k1"], "k2": looks["k2"]})
    assert f["k1"] == f["k2"]


def test_a_verdict_counts_only_on_the_build_and_photo_it_judged(tmp_path):
    import dataset
    ph = tmp_path / "p.jpg"
    ph.write_bytes(b"photo")
    v = {"verdict": "ok", "built_at": "2026-10-27 10:00:00", "photo_sha": dataset.paths.sha(str(ph))}
    assert dataset.fresh(v, {"built_at": "2026-10-27 10:00:00"}, str(ph)) == v
    assert dataset.fresh(v, {"built_at": "2026-10-28 09:00:00"}, str(ph)) is None     # rebuilt since
    ph.write_bytes(b"another photo")
    assert dataset.fresh(v, {"built_at": "2026-10-27 10:00:00"}, str(ph)) is None     # a new photo since


def test_the_phone_page_has_its_slots_and_its_twin_rules():
    # build.py fills these in; the page's reading mirrors vision and heads (web/check.py runs both on pictures)
    page = open(os.path.join(HERE, "web", "index.html")).read()
    for slot in ("/*MODEL*/", "/*EXAMPLE*/", "/*END*/"):
        assert slot in page
    assert f"MIN_SIDE = {vision.MIN_SIDE}" in page and f"SIZE = {vision.SIZE}" in page
    assert str(list(H.HIST_BINS)).replace(" ", "") in page.replace(" ", "")
    assert "clip-b32-int8" in vision.ENCODERS


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
