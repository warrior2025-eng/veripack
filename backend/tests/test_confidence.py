import unittest

from veripack.pipeline.confidence import (
    compute_confidence, visual_quality_factor_from_issues, CONFIDENCE_THRESHOLD
)


class TestComputeConfidence(unittest.TestCase):
    def test_all_perfect_inputs_yield_high_confidence(self):
        self.assertEqual(compute_confidence(1.0, 1.0, 1.0, 1.0), 1.0)

    def test_multiplicative_not_additive(self):
        # 0.9 * 0.9 * 1.0 * 1.0 = 0.81, not e.g. an average (0.95)
        result = compute_confidence(0.9, 0.9, 1.0, 1.0)
        self.assertAlmostEqual(result, 0.81, places=2)

    def test_low_image_quality_drags_confidence_down_even_with_perfect_ocr(self):
        result = compute_confidence(field_confidence=1.0, image_quality_score=0.2,
                                     validation_confidence=1.0)
        self.assertLess(result, CONFIDENCE_THRESHOLD)

    def test_inputs_are_clamped_to_valid_range(self):
        result = compute_confidence(1.5, -0.5, 1.0, 1.0)  # out-of-range inputs
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_visual_quality_factor_defaults_to_one(self):
        with_default = compute_confidence(0.9, 0.9, 0.9)
        with_explicit = compute_confidence(0.9, 0.9, 0.9, 1.0)
        self.assertEqual(with_default, with_explicit)


class TestVisualQualityFactor(unittest.TestCase):
    def test_no_issues_full_factor(self):
        self.assertEqual(visual_quality_factor_from_issues([]), 1.0)

    def test_curved_surface_penalizes_heavily(self):
        factor = visual_quality_factor_from_issues(["CURVED_SURFACE"])
        self.assertLess(factor, 0.5)

    def test_glare_and_curvature_compound(self):
        both = visual_quality_factor_from_issues(["CURVED_SURFACE", "GLARE"])
        curve_only = visual_quality_factor_from_issues(["CURVED_SURFACE"])
        self.assertLess(both, curve_only)

    def test_unrelated_issue_does_not_penalize(self):
        # LOW_RESOLUTION isn't in the visual-geometric penalty list;
        # font-size heuristics shouldn't be penalized for it specifically
        # (that image would already have failed the quality gate anyway).
        self.assertEqual(visual_quality_factor_from_issues(["LOW_RESOLUTION"]), 1.0)


if __name__ == "__main__":
    unittest.main()
