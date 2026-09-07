import unittest

from veripack.pipeline.normalization import normalize_quantity, normalize_mrp, normalize_date


class TestNormalizeQuantity(unittest.TestCase):
    def test_grams(self):
        self.assertEqual(normalize_quantity("Net Qty. 500 g"), {"value": 500.0, "unit": "g"})

    def test_kilograms_alias(self):
        self.assertEqual(normalize_quantity("Net Wt 2.5 kgs"), {"value": 2.5, "unit": "kg"})

    def test_millilitre(self):
        self.assertEqual(normalize_quantity("200ml"), {"value": 200.0, "unit": "ml"})

    def test_pieces_alias(self):
        self.assertEqual(normalize_quantity("Contains 6 pcs"), {"value": 6.0, "unit": "count"})

    def test_no_match_returns_none(self):
        self.assertIsNone(normalize_quantity("Manufactured by ABC Foods"))

    def test_unrecognized_unit_returns_none(self):
        self.assertIsNone(normalize_quantity("500 xyz"))


class TestNormalizeMRP(unittest.TestCase):
    def test_rupee_symbol(self):
        self.assertEqual(normalize_mrp("MRP \u20b999/-"), {"value": 99.0, "currency": "INR"})

    def test_rs_prefix(self):
        self.assertEqual(normalize_mrp("Rs. 149.50"), {"value": 149.50, "currency": "INR"})

    def test_with_commas(self):
        self.assertEqual(normalize_mrp("MRP: Rs 1,299.00"), {"value": 1299.0, "currency": "INR"})

    def test_no_currency_marker_returns_none(self):
        self.assertIsNone(normalize_mrp("Net Qty 500 g"))


class TestNormalizeDate(unittest.TestCase):
    def test_dmy_slash(self):
        result = normalize_date("Mfg Date: 15/03/2025")
        self.assertEqual(result["iso"], "2025-03-15")
        self.assertEqual(result["precision"], "day")

    def test_my_slash(self):
        result = normalize_date("Best Before 11/2026")
        self.assertEqual(result["iso"], "2026-11")
        self.assertEqual(result["precision"], "month")

    def test_month_name_year(self):
        result = normalize_date("Packed on Mar 2025")
        self.assertEqual(result["iso"], "2025-03")

    def test_two_digit_year_expands(self):
        result = normalize_date("12/06/24")
        self.assertEqual(result["iso"], "2024-06-12")

    def test_no_date_returns_none(self):
        self.assertIsNone(normalize_date("Manufactured by ABC Foods Pvt Ltd"))

    def test_invalid_month_rejected(self):
        # month=13 is not valid; must not silently produce a bad date
        self.assertIsNone(normalize_date("32/13/2025"))


if __name__ == "__main__":
    unittest.main()
