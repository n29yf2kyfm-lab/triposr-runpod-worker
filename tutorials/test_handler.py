"""Unit tests for the CPU-testable parts of the assembler — no ffmpeg, no
Kokoro, no network. Run: python -m pytest tutorials/test_handler.py -q"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import assemble
import cache
import script_gen


def test_list_procedures_includes_brake_pads():
    assert "brake_pads_front" in script_gen.list_procedures()


def test_build_script_fills_vehicle():
    script = script_gen.build_script("brake_pads_front", vehicle="a 2020 Golf R")
    assert "a 2020 Golf R" in script["title"]
    joined = " ".join(s["narration"] for s in script["steps"])
    assert "a 2020 Golf R" in joined
    assert "{vehicle}" not in joined


def test_build_script_defaults_leave_no_placeholders():
    script = script_gen.build_script("brake_pads_front")
    for step in script["steps"]:
        assert "{" not in step["narration"], step["id"]
        assert step["est_seconds"] >= script_gen.MIN_STEP_SECONDS
        assert step["broll"], f"step {step['id']} should reference library b-roll"
    assert script["safety_critical"] is True
    assert script["disclaimer"]
    # Tutorial should land near the 60s target once cards are added.
    assert 30 <= script["est_total_seconds"] <= 120


def test_unknown_procedure_rejected():
    with pytest.raises(ValueError, match="Unknown procedure"):
        script_gen.build_script("no_such_procedure")
    with pytest.raises(ValueError, match="Invalid procedure id"):
        script_gen.build_script("../etc/passwd")


def test_polish_noop_without_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    script = script_gen.build_script("brake_pads_front")
    before = [s["narration"] for s in script["steps"]]
    after = script_gen.polish_narration(script)
    assert [s["narration"] for s in after["steps"]] == before


def test_video_key_stable_and_sensitive(tmp_path):
    proc = script_gen.PROCEDURES_DIR / "brake_pads_front.yaml"
    k1 = cache.video_key(proc, "Golf R", "bf_emma", "landscape")
    k2 = cache.video_key(proc, "Golf R", "bf_emma", "landscape")
    assert k1 == k2  # deterministic -> cache hits work
    assert k1 != cache.video_key(proc, "BMW M4", "bf_emma", "landscape")
    assert k1 != cache.video_key(proc, "Golf R", "bf_emma", "portrait")
    edited = tmp_path / "edited.yaml"
    edited.write_bytes(proc.read_bytes() + b"\n# rev")
    assert k1 != cache.video_key(edited, "Golf R", "bf_emma", "landscape")


def test_srt_generation(tmp_path):
    srt = tmp_path / "subs.srt"
    assemble.build_srt(
        [(0.0, 4.0, "First sentence. Second one!"), (4.0, 3.0, "Third.")],
        str(srt),
    )
    text = srt.read_text()
    assert "1\n00:00:00,000 -->" in text
    assert "First sentence." in text and "Third." in text
    # Cues from the second step start where the first step's window ends.
    assert "00:00:04,000" in text


def test_srt_times_format():
    assert assemble._srt_time(0) == "00:00:00,000"
    assert assemble._srt_time(3661.5) == "01:01:01,500"


def test_split_sentences():
    parts = assemble._split_sentences("One. Two? Three")
    assert parts == ["One.", "Two?", "Three"]
    assert assemble._split_sentences("no punctuation") == ["no punctuation"]


def test_cards_render(tmp_path):
    import cards
    p1 = cards.title_card(str(tmp_path / "t.png"), (640, 360), "How to Change Brake Pads",
                          "ExpertCarCheck")
    p2 = cards.text_card(str(tmp_path / "x.png"), (640, 360), "You'll need",
                         ["Jack and axle stands", "Torque wrench"])
    p3 = cards.lower_third(str(tmp_path / "l.png"), (640, 360), 3, "Free the caliper")
    from PIL import Image
    for p, mode in ((p1, "RGB"), (p2, "RGB"), (p3, "RGBA")):
        img = Image.open(p)
        assert img.size == (640, 360)
        assert img.mode == mode


def test_handler_validates_format():
    import handler
    out = handler.handler({"input": {"procedure": "brake_pads_front",
                                     "formats": ["square"]}})
    assert "unknown formats" in out["error"]


def test_handler_lists():
    import handler
    out = handler.handler({"input": {"mode": "list"}})
    assert "brake_pads_front" in out["procedures"]


def test_wan_shots_cover_procedure_broll():
    """Every b-roll key a template references must exist in the wan/ library
    manifest — this is the cross-worker contract."""
    wan_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wan")
    sys.path.insert(0, wan_dir)
    import shots
    script = script_gen.build_script("brake_pads_front")
    for step in script["steps"]:
        assert step["broll"] in shots.BROLL_LIBRARY, (
            f"step {step['id']} references '{step['broll']}' which is not in "
            "wan/shots.py::BROLL_LIBRARY")
