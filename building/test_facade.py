"""Tests for facade.py — measuring a house off a photograph.

The headline test builds a TRUE elevation, warps it the way a camera
would, rectifies it back, and checks the window that comes out matches
the window that went in. If that holds, a photo of a real house yields
the real openings of its model.
"""
import unittest

import facade

try:
    from PIL import Image, ImageDraw
    HAVE_PIL = True
except ImportError:                              # pragma: no cover
    HAVE_PIL = False


class TestHomography(unittest.TestCase):
    def test_corners_map_exactly(self):
        src = [(180, 60), (1150, 130), (1120, 690), (210, 640)]
        dst = [(0, 0), (940, 0), (940, 510), (0, 510)]
        h = facade.solve_homography(src, dst)
        self.assertLess(facade.residual(h, src, dst), 1e-6)

    def test_round_trip_through_the_inverse(self):
        src = [(180, 60), (1150, 130), (1120, 690), (210, 640)]
        dst = [(0, 0), (940, 0), (940, 510), (0, 510)]
        fwd = facade.solve_homography(src, dst)
        inv = facade.solve_homography(dst, src)
        for x, y in [(400.0, 300.0), (900.0, 500.0)]:
            u, v = facade.project(fwd, x, y)
            bx, by = facade.project(inv, u, v)
            self.assertAlmostEqual(bx, x, places=6)
            self.assertAlmostEqual(by, y, places=6)

    def test_degenerate_corners_refuse_rather_than_lie(self):
        collinear = [(0, 0), (10, 0), (20, 0), (30, 0)]
        dst = [(0, 0), (100, 0), (100, 100), (0, 100)]
        with self.assertRaises(ValueError):
            facade.solve_homography(collinear, dst)

    def test_a_facade_needs_positive_measured_size(self):
        with self.assertRaises(ValueError):
            facade.rectify(None, [(0, 0)] * 4, 0.0, 5.1)


class TestMeasurement(unittest.TestCase):
    def setUp(self):
        self.meta = {"px_per_m": 150.0, "width_m": 9.4, "height_m": 5.1,
                     "size_px": [1410, 765]}

    def test_pixels_to_metres_measures_height_from_the_ground(self):
        # bottom-left of the image is the base of the facade
        self.assertEqual(facade.to_metres(self.meta, 0, 765), (0.0, 0.0))
        along, h = facade.to_metres(self.meta, 150, 765 - 150)
        self.assertAlmostEqual(along, 1.0)
        self.assertAlmostEqual(h, 1.0)

    def test_opening_comes_out_in_the_shape_the_model_consumes(self):
        s = 150.0
        # a window: along 1.0-2.8 m, sill 0.9, head 2.25
        box = (1.0 * s, (5.1 - 2.25) * s, 2.8 * s, (5.1 - 0.9) * s)
        op = facade.opening_from_box(self.meta, box, kind="window", level=0)
        self.assertEqual(op["kind"], "window")
        self.assertAlmostEqual(op["along"], 1.0, places=3)
        self.assertAlmostEqual(op["width"], 1.8, places=3)
        self.assertAlmostEqual(op["height"], 1.35, places=3)
        self.assertAlmostEqual(op["sill"], 0.9, places=3)
        self.assertEqual(op["level"], 0)
        # every key model3d.apply_facade_openings reads
        for k in ("kind", "along", "width", "height", "sill"):
            self.assertIn(k, op)

    def test_box_corners_given_either_way_round(self):
        s = 150.0
        a = facade.opening_from_box(self.meta, (150, 300, 420, 630))
        b = facade.opening_from_box(self.meta, (420, 630, 150, 300))
        self.assertEqual(a, b)

    def test_describe_offers_no_fake_verification(self):
        """residual() over the four solving points is ~0 by construction
        — garbage corners included — so describe() printing 'corner
        residual 0.000 px' presented a tautology as a quality check. The
        real, independent check is check_brick_course; describe() must
        not dress the rectification in a metric that measured nothing."""
        text = facade.describe(self.meta)
        self.assertNotIn("residual", text)
        # the honest facts are still all there
        self.assertIn("9.40 x 5.10 m", text)
        self.assertIn("150 px/m", text)

    def test_brick_course_confirms_or_denies_the_scale(self):
        ok = facade.check_brick_course(self.meta, 0.075 * 150.0)
        self.assertTrue(ok["agrees"])
        self.assertAlmostEqual(ok["implied_course_m"], 0.075, places=4)
        # a scale 20% out must be caught
        bad = facade.check_brick_course(self.meta, 0.075 * 150.0 * 1.2)
        self.assertFalse(bad["agrees"])
        self.assertAlmostEqual(bad["error_pct"], 20.0, places=1)
        # four courses measured together is the standard check
        four = facade.check_brick_course(self.meta, 0.300 * 150.0, courses=4)
        self.assertTrue(four["agrees"])


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestRectifyRoundTrip(unittest.TestCase):
    """Draw a true elevation, photograph it at an angle, measure it back."""

    W_M, H_M = 9.4, 5.1
    WIN = (1.0, 2.8, 0.9, 2.25)          # along0, along1, sill, head

    def _true_elevation(self, s=60):
        img = Image.new("RGB", (int(self.W_M * s), int(self.H_M * s)),
                        (190, 90, 70))
        d = ImageDraw.Draw(img)
        a0, a1, sill, head = self.WIN
        d.rectangle([a0 * s, (self.H_M - head) * s,
                     a1 * s, (self.H_M - sill) * s], fill=(30, 40, 55))
        return img

    def test_measured_window_matches_the_drawn_window(self):
        true_img = self._true_elevation()
        corners = [(180, 60), (1150, 130), (1120, 690), (210, 640)]
        # warp the true elevation into a "photograph"
        fwd = facade.solve_homography(
            [(0, 0), (true_img.width, 0),
             (true_img.width, true_img.height), (0, true_img.height)],
            corners)
        photo_size = (1300, 800)
        back = facade.solve_homography(
            [(0, 0), (photo_size[0], 0), photo_size, (0, photo_size[1])],
            [facade.project(facade.solve_homography(corners, [
                (0, 0), (true_img.width, 0),
                (true_img.width, true_img.height), (0, true_img.height)]),
                x, y) for x, y in
             [(0, 0), (photo_size[0], 0), photo_size, (0, photo_size[1])]])
        photo = true_img.transform(photo_size, Image.PERSPECTIVE, back,
                                   resample=Image.BICUBIC)
        self.assertIsNotNone(fwd)

        rect, meta = facade.rectify(photo, corners, self.W_M, self.H_M,
                                    px_per_m=150)
        self.assertEqual(rect.size, tuple(meta["size_px"]))
        # No corner_residual_px: an exact 4-point solve reproduces its own
        # corners for ANY input, so the field was a 0.000 that read as
        # verification and measured nothing. It must stay out of meta.
        self.assertNotIn("corner_residual_px", meta)

        s = meta["px_per_m"]
        a0, a1, sill, head = self.WIN
        op = facade.opening_from_box(
            meta, (a0 * s, (self.H_M - head) * s,
                   a1 * s, (self.H_M - sill) * s), kind="window")
        self.assertAlmostEqual(op["along"], a0, places=2)
        self.assertAlmostEqual(op["width"], a1 - a0, places=2)
        self.assertAlmostEqual(op["sill"], sill, places=2)
        self.assertAlmostEqual(op["height"], head - sill, places=2)

    def test_rectified_size_follows_the_measured_facade(self):
        photo = Image.new("RGB", (400, 300), (200, 120, 90))
        corners = [(20, 10), (380, 30), (370, 280), (30, 260)]
        _, meta = facade.rectify(photo, corners, 8.0, 4.0, px_per_m=100)
        self.assertEqual(meta["size_px"], [800, 400])
        self.assertAlmostEqual(meta["px_per_m"], 100.0)


if __name__ == "__main__":
    unittest.main()
