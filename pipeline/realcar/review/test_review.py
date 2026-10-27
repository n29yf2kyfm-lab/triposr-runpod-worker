"""The review toolkit's guards, gold checks and consistency gate, each tested
against the mistake it exists for (the run of October 2026).

    python3 -m pytest pipeline/realcar/review/test_review.py -q
"""
import json
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_review  # noqa: E402
import check  # noqa: E402
import fleet  # noqa: E402
import gold  # noqa: E402
import paint_label  # noqa: E402
import paths  # noqa: E402
import photo_paint  # noqa: E402
import view_label  # noqa: E402
import web_photo  # noqa: E402

BUILT = "2026-10-27 10:00:00"


def _jpg(path, colour=(40, 40, 200)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = np.full((200, 300, 3), 128, np.uint8)
    im[60:160, 40:260] = colour
    cv2.imwrite(path, im)


@pytest.fixture()
def run(tmp_path, monkeypatch):
    """A run of three cars: a built Fiesta, a stand-in Note, a failed one."""
    home = tmp_path / "f1k"
    home.mkdir()
    monkeypatch.setenv("F1K_HOME", str(home))
    monkeypatch.setenv("F1K_GOLD", str(tmp_path / "gold.json"))
    monkeypatch.setenv("GLBMACHINE_HOME", str(tmp_path / "gmhome"))
    targets = [{"key": k, "class": "car", "rank": i, "genModel": k.upper(), "make": "M", "model": k, "licensed": 1,
                "request": k} for i, k in enumerate(("car-fiesta", "car-note", "car-gone"), 1)]
    paths.save(str(home / "targets.json"), targets)
    for r in ({"key": "car-fiesta", "status": "built", "asset": "ford-fiesta-2009", "title": "Ford Fiesta", "paint": "#eeefed",
               "built_at": BUILT, "years": [2008, 2017]},
              {"key": "car-note", "status": "standin", "asset": "nissan-cube", "title": "Nissan Note", "paint": "#2a5aa6",
               "built_at": BUILT, "years": [2020, None]},
              {"key": "car-gone", "status": "failed", "error": "not in the catalogue", "built_at": BUILT}):
        paths.append_row(dict(r, **{k: v for k, v in targets[0].items() if k not in ("key",)}) | {"key": r["key"]})
    for k in ("car-fiesta", "car-note"):
        _jpg(str(home / "car_photos" / f"{k}.jpg"))
        _jpg(str(home / "hero_png" / f"{k}.png"))
    monkeypatch.setattr(photo_paint, "paint_of", lambda key: {"rgb": [238, 239, 237], "hex": "#eeefed", "kind": "light"})
    return home


# ── the results file ─────────────────────────────────────────────────────

def test_a_cut_line_is_read_past_not_fatal(run):
    with open(run / "results.jsonl", "a") as fh:
        fh.write('{"key": "car-x", "status": "bui')          # what a full disk left on 27 October
    rows, bad = paths.rows()
    assert bad == 1 and set(rows) == {"car-fiesta", "car-note", "car-gone"}


def test_a_short_write_leaves_nothing_behind(run, monkeypatch):
    size = os.path.getsize(run / "results.jsonl")
    real = os.write
    monkeypatch.setattr(paths.os, "write", lambda fd, data: real(fd, data[:5]))
    with pytest.raises(OSError):
        paths.append_row({"key": "car-y", "status": "built"})
    assert os.path.getsize(run / "results.jsonl") == size


# ── verdicts that cannot be right are refused ────────────────────────────

@pytest.mark.parametrize("key,v,faults,note,needle", [
    ("car-fiests", "ok", [], "", "not a key of this run"),
    ("car-gone", "ok", [], "", "was not built"),
    ("car-fiesta", "ok", ["colour"], "", "ok build has no faults"),
    ("car-fiesta", "bad", [], "too blue", "at least one fault"),
    ("car-fiesta", "bad", ["colour"], "blue", "in a few words"),
    ("car-fiesta", "bad", ["paint"], "the wrong blue", "unknown fault"),
    ("car-fiesta", "bad", ["photo"], "photo is the old shape", "only for a photo you replaced"),
])
def test_impossible_verdicts_are_refused(run, key, v, faults, note, needle):
    with pytest.raises(build_review.Refused, match=needle):
        build_review.verdict(key, v, faults, note)
    assert key not in paths.load(build_review.OUT())


def test_a_photo_fault_after_a_replacement_is_taken(run):
    paths.save(str(run / "photo_review.json"), {"car-fiesta": {"replaced_at": "2026-10-27 11:00:00"}})
    build_review.verdict("car-fiesta", "bad", ["photo"], "photo replaced: it was the Mk8")
    v = paths.load(build_review.OUT())["car-fiesta"]
    assert v["built_at"] == BUILT and v["photo_sha"] == paths.sha(paths.photo("car-fiesta"))


def test_side_and_colour_faults_ask_for_the_label_again(run):
    build_review.verdict("car-note", "bad", ["side", "colour"], "nose the other way, and too dark")
    q = paths.load(str(run / "needs_label.json"))
    assert "car-note" in q["side"] and "car-note" in q["colour"]
    view_label.label("car-note=right")
    assert "car-note" not in paths.load(str(run / "needs_label.json"))["side"]


def test_a_roof_fault_asks_for_the_roof_painted_in_the_rebuild(run):
    # the donor's black roof on the white Fiat 600: the reviewer's fault is the fix
    with pytest.raises(build_review.Refused, match="--roof body"):
        build_review.verdict("car-note", "bad", ["roof"], "the donor's black roof; the photo's is white")
    with pytest.raises(build_review.Refused, match="colour family"):
        build_review.verdict("car-note", "bad", ["roof"], "the donor's black roof; the photo's is white", "snow")
    build_review.verdict("car-note", "bad", ["roof"], "the donor's black roof; the photo's is white", "body")
    assert paths.load(str(run / "roof_label.json"))["car-note"]["roof"] == "body"
    assert "car-note" in paths.load(str(run / "needs_rebuild.json"))
    assert fleet._roof_words("car-note") == ["body", "coloured", "roof"]
    assert fleet._roof_words("car-fiesta") == []
    # the Captur's photo: a white roof on a blue body
    build_review.verdict("car-fiesta", "bad", ["roof"], "black roof; the photo's roof is white on blue", "white")
    assert fleet._roof_words("car-fiesta") == ["#eeefed", "roof"]


def test_the_roof_pass_records_and_queues_and_its_checked_roofs_teach(run):
    build_review.roof("car-fiesta", "same")
    assert paths.load(str(run / "roof_check.json"))["car-fiesta"]["answer"] == "same"
    assert "car-fiesta" not in paths.load(str(run / "needs_rebuild.json"), {})
    with pytest.raises(build_review.Refused, match="same, body or a colour family"):
        build_review.roof("car-note", "sameish")
    # the Kamiq: its model's black roof beside a photo of a silver car
    gold.add("roof", "car-note", "body", "the model's black roof; the photo's car is silver all over")
    with pytest.raises(build_review.Refused, match="checked by hand and is body"):
        build_review.roof("car-note", "same")
    build_review.roof("car-note", "body")
    assert paths.load(str(run / "roof_label.json"))["car-note"]["roof"] == "body"
    assert "car-note" in paths.load(str(run / "needs_rebuild.json"))
    # a checked roof is about that build: after a rebuild it drops out
    paths.append_row({"key": "car-note", "status": "standin", "built_at": "2026-10-28 09:00:00"})
    assert gold.judge("roof", "car-note", "same") is None


def test_the_commands_as_the_agents_type_them(run, monkeypatch, capsys):
    # every command the prompts give, through main(): the roof pass's first
    # batch found "roof KEY same" failing on a name main() hid
    for argv in (["roof", "car-fiesta", "same"],
                 ["verdict", "car-note", "bad", "roof", "the donor's black roof on a white car", "--roof", "body"],
                 ["verdict", "car-fiesta", "ok"]):
        monkeypatch.setattr(sys, "argv", ["build_review.py", *argv])
        build_review.main()
    out = capsys.readouterr().out
    assert "recorded roof car-fiesta same" in out and "recorded car-note bad" in out
    assert paths.load(str(run / "roof_label.json"))["car-note"]["roof"] == "body"


# ── gold: a wrong answer on a checked item teaches, and is counted ───────

def test_a_wrong_answer_on_a_checked_build_is_refused_and_counted(run):
    gold.add("build", "car-note", "bad", "a Cube box stands in for the Note hatch", ["body"])
    gold.note_sheet(str(run / "sheets" / "b5_s00.jpg"), "batch5", ["car-fiesta", "car-note"], ["car-note"])
    with pytest.raises(build_review.Refused, match="checked by hand and is bad"):
        build_review.verdict("car-note", "ok", [], "")
    assert "car-note" not in paths.load(build_review.OUT())
    with pytest.raises(build_review.Refused, match="checked by hand"):
        build_review.verdict("car-note", "bad", ["colour"], "colour is a bit bright")    # bad, but not for the reason
    build_review.verdict("car-note", "bad", ["body"], "a boxy Cube for a modern hatch")
    s = gold.scores()["batch5"]
    assert s == {"answered": 1, "missed": 1, "misses": ["build car-note: said ok"], "resolved": None}


def test_an_answer_counts_for_the_batch_that_gave_it(run, monkeypatch):
    # two batches' sheets carried the same checked item: only the one whose
    # agent answered wrongly is charged (October 2026: rev6 was charged rev1's)
    gold.add("build", "car-note", "bad", "a Cube box stands in for the Note hatch", ["body"])
    gold.note_sheet(str(run / "sheets" / "a_s00.jpg"), "batchA", ["car-note"], ["car-note"])
    gold.note_sheet(str(run / "sheets" / "b_s00.jpg"), "batchB", ["car-note"], ["car-note"])
    monkeypatch.setenv("F1K_BATCH", "batchA")
    with pytest.raises(build_review.Refused):
        build_review.verdict("car-note", "ok", [], "")
    monkeypatch.setenv("F1K_BATCH", "batchB")
    build_review.verdict("car-note", "bad", ["body"], "a boxy Cube for a modern hatch")
    sc = gold.scores()
    assert sc["batchA"]["missed"] == 1 and sc["batchB"]["missed"] == 0
    # the manifest is kept away from the sheets the agents open
    assert not (run / "sheets" / "manifest.json").exists()


def test_a_withdrawn_answer_is_not_used_or_scored_and_a_resolved_batch_passes(run):
    gold.add("build", "car-note", "ok", "looked right at the time")
    with pytest.raises(build_review.Refused):
        build_review.verdict("car-note", "bad", ["broken"], "grey tyres and flat grey grille")
    assert gold.scores()["?"]["missed"] == 1
    gold.withdraw("build", "car-note", "arguable: grey tyres are a fault to some")
    assert gold.judge("build", "car-note", "bad", ["broken"]) is None
    assert "?" not in gold.scores()
    gold.add("build", "car-note", "bad", "a Cube for the Note", ["body"])
    with pytest.raises(build_review.Refused):
        build_review.verdict("car-note", "ok", [], "")
    assert check.run()["gold"]
    gold.resolved("?", "its sheets judged again by batch7")
    assert not check.run()["gold"]


def test_a_build_checked_ok_takes_photo_alone_after_its_photo_is_replaced(run):
    gold.add("build", "car-fiesta", "ok", "the same car as the photo")
    assert gold.judge("build", "car-fiesta", "bad", ["photo"])["right"]
    assert not gold.judge("build", "car-fiesta", "bad", ["photo", "broken"])["right"]


def test_a_checked_build_no_longer_counts_after_a_rebuild(run):
    gold.add("build", "car-note", "bad", "a Cube for the Note", ["body"])
    paths.append_row({"key": "car-note", "status": "standin", "built_at": "2026-10-28 09:00:00"})
    assert gold.judge("build", "car-note", "ok") is None
    build_review.verdict("car-note", "ok", [], "")


def test_side_labels_are_refused_together_when_a_checked_one_is_wrong(run):
    gold.add("side", "car-fiesta", "left", "its front is at the picture's left")
    with pytest.raises(SystemExit) as e:
        view_label.label("car-fiesta=right car-note=left")
    assert e.value.code == 2
    assert paths.load(view_label.LABELS()) == {}


def test_a_side_label_against_its_picture_queues_a_rebuild(run):
    view_label.label("car-fiesta=right car-note=left")       # pictured nose-left by default
    q = paths.load(str(run / "needs_rebuild.json"))
    assert list(q) == ["car-fiesta"]


def test_a_colour_label_reads_the_paint_and_queues_a_changed_colour(run):
    paint_label.label("car-note=white")
    assert paths.load(str(run / "photo_paint.json"))["car-note"]["photo_sha"] == paths.sha(paths.photo("car-note"))
    assert "car-note" in paths.load(str(run / "needs_rebuild.json"))      # built blue, its photo is white
    with pytest.raises(SystemExit):
        paint_label.label("car-note=teal")                                 # no such family


def test_sheets_mix_in_checked_items_and_note_them(run):
    gold.add("side", "car-note", "left", "front at the left")
    out = str(run / "sheets" / "v00.jpg")
    keys = gold.mix(["car-fiesta"], "side", 1, out, "side1")
    assert sorted(keys) == ["car-fiesta", "car-note"]
    assert paths.load(str(run / "review_runs" / "manifest.json"))[out]["gold"] == ["car-note"]


# ── a new photo: everything it needs at once ─────────────────────────────

def _cand(run, key, n, **m):
    d = run / "web_cand" / key
    _jpg(str(d / f"{n}.jpg"), (30, 30, 30))
    c = paths.load(str(d / "cands.json"), [])
    c.append({"n": n, "url": "https://example.com/p.jpg", "page": "https://example.com", "title": "a photo",
              "site": "example.com", "path": str(d / f"{n}.jpg"), **m})
    paths.save(str(d / "cands.json"), c)


def test_a_photo_of_no_whole_car_is_refused(run):
    _cand(run, "car-fiesta", 0, fill=0.06, off_frame=False)          # the XC90's wheel close-up
    with pytest.raises(web_photo.Refused, match="fills 6%"):
        web_photo.choose("car-fiesta", 0, (2008, 2017), "Mk7", "white", "left")
    _cand(run, "car-fiesta", 1, error="no car found in it")
    with pytest.raises(web_photo.Refused, match="no car found"):
        web_photo.choose("car-fiesta", 1, (2008, 2017), "Mk7", "white", "left")


def test_a_whole_car_with_parked_cars_behind_it_is_not_cut_off(run, monkeypatch):
    # the MG4's and the 206's photos: a row of parked cars behind, joined to
    # the car's outline, touched the frame; the car itself was whole
    p = str(run / "w.jpg")
    cv2.imwrite(p, np.full((300, 480, 3), 128, np.uint8))
    m = np.zeros((300, 480), np.uint8)
    m[100:250, 60:400] = 1
    m[110:125, 0:60] = 1
    monkeypatch.setattr(photo_paint, "car_mask", lambda img: m)
    assert not web_photo.measure(p)["off_frame"]
    m[:] = 0
    m[60:250, 0:300] = 1                                  # the front cut off by the frame
    assert web_photo.measure(p)["off_frame"]


def test_a_photo_of_another_generation_is_refused(run):
    _cand(run, "car-fiesta", 0, fill=0.5, off_frame=False)
    # a 2018-on Mk8 photo for the 2008-2017 Mk7 build (the classic Mini given a modern Mini's photo)
    with pytest.raises(web_photo.Refused, match="another car"):
        web_photo.choose("car-fiesta", 0, (2018, 2023), "Mk8", "white", "left")


def test_choosing_a_photo_sets_its_paint_side_and_rebuild(run):
    _cand(run, "car-fiesta", 0, fill=0.5, off_frame=False)
    out = web_photo.choose("car-fiesta", 0, (2008, 2017), "Mk7", "white", "right")
    assert out["paint"] == "#eeefed"
    assert paths.load(str(run / "paint_label.json"))["car-fiesta"] == "white"
    assert paths.load(str(run / "view_label.json"))["car-fiesta"] == "right"
    assert paths.load(str(run / "photo_paint.json"))["car-fiesta"]["photo_sha"] == paths.sha(paths.photo("car-fiesta"))
    assert "car-fiesta" in paths.load(str(run / "needs_rebuild.json"))
    assert paths.load(str(run / "photo_review.json"))["car-fiesta"]["replaced_at"] > BUILT


# ── the gate ─────────────────────────────────────────────────────────────

def test_the_gate_finds_each_stale_record(run):
    photo_paint.read(["car-fiesta", "car-note"])
    paint_label.label("car-fiesta=white car-note=white")
    view_label.label("car-fiesta=left car-note=left")
    build_review.verdict("car-fiesta", "ok", [], "")
    _jpg(str(run / "car_photos" / "car-fiesta.jpg"), (0, 200, 0))     # a new photo, its paint not read again (the 300C)
    paths.append_row({"key": "car-note", "status": "standin", "paint": "#2a5aa6", "built_at": "2026-10-28 09:00:00"})
    found = check.run()
    assert any("older photo" in x for x in found["paint"])
    assert any("car-note: built #2a5aa6" in x for x in found["built"])
    assert any("car-note: no verdict" in x for x in found["verdict"])
    assert any(x.startswith("car-fiesta: verdict on an older photo") for x in found["verdict"])


def test_the_gate_finds_a_paint_read_for_another_colour_than_the_label(run):
    paths.save(str(run / "paint_label.json"), {"car-fiesta": "silver"})
    paths.save(str(run / "photo_paint.json"), {"car-fiesta": {"hex": "#a3b884", "family": "light-green",
                                                              "photo_sha": paths.sha(paths.photo("car-fiesta"))}})
    assert any("named silver" in x for x in check.run()["paint"])


def test_the_gate_is_clear_when_all_is_current(run):
    paint_label.label("car-fiesta=white car-note=white")
    view_label.label("car-fiesta=left car-note=left")
    paths.append_row({"key": "car-note", "status": "standin", "paint": "#eeefed", "built_at": "2026-10-28 09:00:00"})
    build_review.verdict("car-fiesta", "ok", [], "")
    build_review.verdict("car-note", "ok", [], "")
    found = check.run()
    assert not any(found[k] for k in check.BLOCKING if k != "results"), {k: v for k, v in found.items() if v}


def test_the_gate_reports_a_batch_that_missed_a_checked_item(run):
    gold.add("build", "car-note", "bad", "a Cube for the Note", ["body"])
    gold.note_sheet(str(run / "sheets" / "b6.jpg"), "batch6", ["car-note"], ["car-note"])
    with pytest.raises(build_review.Refused):
        build_review.verdict("car-note", "ok", [], "")
    assert any("batch batch6: missed 1 of 1" in x for x in check.run()["gold"])


# ── the runner ───────────────────────────────────────────────────────────

def test_the_runner_starts_nothing_on_a_full_disk(run, monkeypatch):
    rows = run / "results.jsonl"
    rows.write_text("")
    monkeypatch.setattr(fleet, "room", lambda: False)
    monkeypatch.setattr(fleet, "one", lambda t: pytest.fail("a build was started on a full disk"))
    with pytest.raises(SystemExit) as e:
        fleet.build(2)
    assert e.value.code == 3 and rows.read_text() == ""


def test_the_runner_stamps_each_row_and_meets_the_queue(run, monkeypatch):
    (run / "results.jsonl").write_text("")
    paths.queue_rebuild("car-fiesta", "new photo")
    monkeypatch.setattr(fleet, "room", lambda: True)
    monkeypatch.setattr(fleet, "one", lambda t: {"key": t["key"], "class": "car", "rank": t["rank"], "genModel": t["genModel"],
                                                 "status": "built", "built_at": paths.now()})
    fleet.build(2)
    rows, bad = paths.rows()
    assert bad == 0 and set(rows) == {"car-fiesta", "car-note", "car-gone"}
    assert "car-fiesta" not in paths.load(str(run / "needs_rebuild.json"))
