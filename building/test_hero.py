"""Tests for hero.py — the guard against the pretty lie.

hero.make decides whether an AI-restyled image is trusted, rejected or
composited, and until now it was the only shipped module with no test at
all: invert the guard comparison and every redrawn building shipped
labelled "verified against the measured render" with the whole suite
green. The decision logic is pure once restyle() is stubbed, so these
tests run with no network and no key.

The synthetic pairs pin the metric itself: a restyle (same edges, new
materials and noise) must score far above GUARD_MIN_CORRELATION and a
moved building far below it, or the threshold separates nothing.
"""
import os
import random
import shutil
import tempfile
import unittest

from PIL import Image, ImageDraw

import hero


def draw_house(path, dx=0, fill=(120, 120, 120), roof=(90, 90, 90),
               win=(40, 40, 40), bg=(230, 230, 230), noise=0):
    """A massing-render stand-in: block, roof, extension, openings."""
    img = Image.new("RGB", (480, 360), bg)
    dr = ImageDraw.Draw(img)
    dr.rectangle([120 + dx, 160, 320 + dx, 320], fill=fill,
                 outline=(20, 20, 20), width=3)
    dr.polygon([(110 + dx, 160), (220 + dx, 80), (330 + dx, 160)],
               fill=roof, outline=(20, 20, 20))
    dr.rectangle([320 + dx, 230, 420 + dx, 320], fill=fill,
                 outline=(20, 20, 20), width=3)
    for wx in (150, 240):
        dr.rectangle([wx + dx, 190, wx + 50 + dx, 240], fill=win,
                     outline=(10, 10, 10), width=2)
    dr.rectangle([190 + dx, 260, 250 + dx, 320], fill=(60, 45, 30),
                 outline=(10, 10, 10), width=2)
    if noise:
        rnd = random.Random(7)
        px = img.load()
        for _ in range(noise):
            x, y = rnd.randrange(480), rnd.randrange(360)
            r, g, b = px[x, y]
            j = rnd.randint(-25, 25)
            px[x, y] = (max(0, min(255, r + j)), max(0, min(255, g + j)),
                        max(0, min(255, b + j)))
    img.save(path)
    return path


class TestStructuralMatch(unittest.TestCase):
    """The metric must rank: identical >= restyled >> moved."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.base = draw_house(os.path.join(cls.dir, "base.png"))
        cls.same = draw_house(os.path.join(cls.dir, "same.png"))
        # Same edges, different materials, texture noise — what a faithful
        # restyle does and the guard must ALLOW.
        cls.restyled = draw_house(
            os.path.join(cls.dir, "restyled.png"), fill=(150, 90, 70),
            roof=(70, 60, 60), win=(90, 120, 150), bg=(200, 215, 235),
            noise=40000)
        # The failure the guard exists to catch: the building moved.
        cls.moved = draw_house(os.path.join(cls.dir, "moved.png"), dx=110)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_an_identical_image_scores_one(self):
        self.assertAlmostEqual(
            hero.structural_match(self.base, self.same), 1.0, places=3)

    def test_a_faithful_restyle_clears_the_threshold(self):
        s = hero.structural_match(self.base, self.restyled)
        self.assertGreater(s, hero.GUARD_MIN_CORRELATION + 0.2)

    def test_a_moved_building_falls_below_it(self):
        s = hero.structural_match(self.base, self.moved)
        self.assertLess(s, hero.GUARD_MIN_CORRELATION - 0.1)

    def test_the_ordering_is_strict(self):
        s_same = hero.structural_match(self.base, self.same)
        s_re = hero.structural_match(self.base, self.restyled)
        s_mv = hero.structural_match(self.base, self.moved)
        self.assertGreaterEqual(s_same, s_re)
        self.assertGreater(s_re, s_mv)

    def test_an_unreadable_image_is_none_not_a_pass(self):
        missing = os.path.join(self.dir, "nope.png")
        self.assertIsNone(hero.structural_match(self.base, missing))


class TestMakeVerdicts(unittest.TestCase):
    """make() accepts, rejects or declines — driven by a stubbed restyle."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.render = draw_house(os.path.join(self.dir, "render.png"))
        self.ai = draw_house(os.path.join(self.dir, "ai.png"),
                             fill=(150, 90, 70), noise=20000)
        self._restyle = hero.restyle
        self._key = os.environ.get("GOOGLE_AI_API_KEY")
        os.environ["GOOGLE_AI_API_KEY"] = "test-key-never-used"

    def tearDown(self):
        hero.restyle = self._restyle
        if self._key is None:
            os.environ.pop("GOOGLE_AI_API_KEY", None)
        else:
            os.environ["GOOGLE_AI_API_KEY"] = self._key
        shutil.rmtree(self.dir, ignore_errors=True)

    def _stub(self, score, exc=None):
        ai = self.ai

        def fake(render_path, model, work_dir, key, time_of_day="day",
                 out_name="hero.png", reference_photo=None):
            if exc:
                raise exc
            out = os.path.join(work_dir, out_name)
            shutil.copyfile(ai, out)
            return out, score
        hero.restyle = fake

    def test_a_good_score_is_accepted_and_says_verified(self):
        self._stub(0.9)
        arts, note = hero.make({}, self.render, self.dir, "job")
        self.assertEqual(len(arts), 1)
        self.assertTrue(arts[0][1].endswith("job.hero.png"))
        self.assertIn("verified", note)

    def test_a_low_score_is_rejected_and_renamed(self):
        self._stub(hero.GUARD_MIN_CORRELATION - 0.2)
        arts, note = hero.make({}, self.render, self.dir, "job")
        self.assertIn("REJECTED", note)
        self.assertTrue(arts[0][1].endswith("hero-rejected.png"))
        self.assertTrue(os.path.exists(arts[0][0]))
        # nobody downstream can mistake the reject for the proposal
        self.assertNotIn("job.hero.png", arts[0][1])

    def test_the_threshold_is_exact_at_the_boundary(self):
        self._stub(hero.GUARD_MIN_CORRELATION)
        _, note = hero.make({}, self.render, self.dir, "job")
        self.assertIn("verified", note)
        self._stub(hero.GUARD_MIN_CORRELATION - 0.01)
        _, note = hero.make({}, self.render, self.dir, "job")
        self.assertIn("REJECTED", note)

    def test_an_unscorable_pass_ships_labelled_unverified(self):
        self._stub(None)
        arts, note = hero.make({}, self.render, self.dir, "job")
        self.assertEqual(len(arts), 1)
        self.assertIn("UNVERIFIED", note)

    def test_no_key_means_no_pass_and_says_why(self):
        os.environ.pop("GOOGLE_AI_API_KEY", None)
        arts, note = hero.make({}, self.render, self.dir, "job")
        self.assertEqual(arts, [])
        self.assertIn("GOOGLE_AI_API_KEY", note)

    def test_a_hero_error_is_reported_not_raised(self):
        self._stub(None, exc=hero.HeroError("Gemini is rate-limited."))
        arts, note = hero.make({}, self.render, self.dir, "job")
        self.assertEqual(arts, [])
        self.assertIn("no photoreal pass", note)

    def test_a_mask_composites_and_the_note_says_so(self):
        self._stub(0.2)          # even a bad score: the mask bounds it
        mask = os.path.join(self.dir, "mask.png")
        m = Image.new("L", (480, 360), 0)
        ImageDraw.Draw(m).rectangle([120, 80, 420, 320], fill=255)
        m.save(mask)
        arts, note = hero.make({}, self.render, self.dir, "job",
                               mask_path=mask)
        self.assertEqual(len(arts), 1)
        self.assertIn("composited through the measured silhouette", note)
        self.assertNotIn("REJECTED", note)


class TestLayerOntoMesh(unittest.TestCase):
    """The composite: AI inside the silhouette, our render outside it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _solid(self, name, size, color, mode="RGB"):
        p = os.path.join(self.dir, name)
        Image.new(mode, size, color).save(p)
        return p

    def test_outside_the_mask_is_ours_inside_is_the_ai(self):
        base = self._solid("base.png", (100, 100), (0, 0, 255))
        ai = self._solid("ai.png", (100, 100), (255, 0, 0))
        mask = os.path.join(self.dir, "mask.png")
        m = Image.new("L", (100, 100), 0)
        ImageDraw.Draw(m).rectangle([25, 25, 74, 74], fill=255)
        m.save(mask)
        out = hero.layer_onto_mesh(base, mask, ai,
                                   os.path.join(self.dir, "out.png"))
        px = Image.open(out).load()
        self.assertEqual(px[50, 50], (255, 0, 0))      # inside: AI
        self.assertEqual(px[5, 5], (0, 0, 255))        # outside: ours

    def test_a_wrong_aspect_is_cover_fit_not_squashed(self):
        """A 2:1 AI image against a square base must be centre-cropped:
        squashing it stretches every vertical on the building."""
        base = self._solid("base.png", (100, 100), (0, 0, 255))
        ai = os.path.join(self.dir, "ai.png")
        wide = Image.new("RGB", (200, 100), (0, 255, 0))
        # left half green, right half red: a squash would blend both into
        # frame; a centre crop keeps the seam at the output's centre.
        ImageDraw.Draw(wide).rectangle([100, 0, 199, 99], fill=(255, 0, 0))
        wide.save(ai)
        mask = self._solid("mask.png", (100, 100), 255, mode="L")
        out = hero.layer_onto_mesh(base, mask, ai,
                                   os.path.join(self.dir, "out.png"))
        px = Image.open(out).load()
        self.assertEqual(px[10, 50], (0, 255, 0))      # crop keeps centre
        self.assertEqual(px[90, 50], (255, 0, 0))
        # the seam sits at the middle, where the source's middle was
        self.assertNotEqual(px[45, 50], px[55, 50])


class TestPrompt(unittest.TestCase):
    """_prompt must describe the render it was given, not a template house.

    The template version asserted 'ONE roof... do not add a second ridge
    ... or any valley' and 'the low flat-roofed block' whatever the model
    held — so a legitimate multi-range roof, or an extension built as a
    storey of the house, got a prompt instructing the restyle to erase
    measured geometry. These pin the clauses to the model's own data.
    """

    def test_a_single_range_roof_stays_single(self):
        model = {"storeys": 2,
                 "roof": {"kind": "hipped", "ranges": 1, "valley_m": 0.0},
                 "caps": [{"kind": "flat"}],
                 "extension_fit": {"built_m": {"width": 4.0, "depth": 3.0}}}
        p = hero._prompt(model)
        self.assertIn("ONE pitched roof", p)
        self.assertIn("or any valley", p)
        self.assertIn("flat-roofed block", p)

    def test_a_multi_range_roof_keeps_its_valleys(self):
        # roof_over splits a span past MAX_ROOF_SPAN_M into 2 ranges with a
        # valley between them — the render draws it, so the prompt must not
        # forbid it.
        model = {"storeys": 2,
                 "roof": {"kind": "hipped", "ranges": 2, "valley_m": 8.2},
                 "caps": [], "extension_fit": {}}
        p = hero._prompt(model)
        self.assertIn("2 parallel hipped ranges", p)
        self.assertIn("valley gutter", p)
        self.assertNotIn("ONE pitched roof", p)
        self.assertNotIn("or any valley", p)   # the erase order is gone

    def test_a_flat_topped_model_is_not_given_a_tile_roof(self):
        # No Solar data -> no roof_spec -> model["roof"] is None. Telling
        # the restyle this house has a pitched tile roof invents one.
        model = {"storeys": 1, "roof": None, "caps": [], "extension_fit": {}}
        p = hero._prompt(model)
        self.assertNotIn("concrete-tile", p)
        self.assertNotIn("pitched concrete", p)
        self.assertIn("FLAT top", p)

    def test_an_uncapped_extension_is_not_called_flat_roofed(self):
        # An "over" extension is a storey of the house under the main roof:
        # model3d gives it no flat cap, so 'the low flat-roofed block'
        # would describe a block the render does not contain.
        model = {"storeys": 2,
                 "roof": {"kind": "hipped", "ranges": 1},
                 "caps": [],
                 "extension_fit": {"type": "over",
                                   "built_m": {"width": 3.2, "depth": 6.0}}}
        p = hero._prompt(model)
        self.assertNotIn("flat-roofed block", p)
        self.assertNotIn("membrane roof", p)
        self.assertIn("extension block", p)

    def test_the_measured_size_still_reaches_the_prompt(self):
        model = {"storeys": 2,
                 "roof": {"kind": "gabled", "ranges": 1},
                 "caps": [{"kind": "flat"}],
                 "extension_fit": {"built_m": {"width": 4.0, "depth": 3.0}}}
        p = hero._prompt(model)
        self.assertIn("4.0m by 3.0m", p)


class TestMontagePrompt(unittest.TestCase):
    def test_the_size_comes_from_the_survey(self):
        p = hero.montage_prompt({"type": "rear", "storeys": 1,
                                 "built_m": {"width": 4.0, "depth": 3.0}})
        self.assertIn("4.0 metres wide", p)
        self.assertIn("3.0 metres deep", p)
        self.assertIn("BACK of the house", p)

    def test_it_defends_the_real_house(self):
        p = hero.montage_prompt({"type": "side", "side": "east"})
        self.assertIn("stays EXACTLY as photographed", p)
        self.assertIn("east side", p)


if __name__ == "__main__":
    unittest.main()
