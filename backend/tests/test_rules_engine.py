"""
Rule engine tests -- these implement the exact mandatory fixtures from the
build brief (Section 37): a fully compliant set of fields, a missing
consumer-care field, an uncertain font-size under curvature, and a cropped
image where the manufacturer block isn't visible.
"""

import unittest

from tests.testutils import (
    reset_db, make_rule_version, make_requirement, make_field,
    GOOD_QUALITY, POOR_QUALITY, CURVED_QUALITY,
)
from veripack.pipeline.rules_engine import evaluate_check, select_rule_version


def _standard_requirements(rule_version_id):
    make_requirement(rule_version_id, "MANUFACTURER_NAME_ADDRESS", "Manufacturer / Packer / Importer",
                      "MANUFACTURER", "ALL", {"type": "qualified_presence"})
    make_requirement(rule_version_id, "GENERIC_NAME", "Generic name of commodity",
                      "GENERIC_NAME", "ALL", {"type": "presence"})
    make_requirement(rule_version_id, "NET_QUANTITY", "Net quantity declaration",
                      "NET_QUANTITY", "ALL", {"type": "format", "requires": ["value", "unit"]})
    make_requirement(rule_version_id, "MRP", "Maximum Retail Price",
                      "MRP", "ALL", {"type": "format", "requires": ["value", "currency"]})
    make_requirement(rule_version_id, "MFG_DATE", "Manufacturing / packing date",
                      "MFG_DATE", "ALL", {"type": "presence"})
    make_requirement(rule_version_id, "CONSUMER_CARE", "Consumer care details",
                      "CONSUMER_CARE", "ALL", {"type": "presence"})
    make_requirement(rule_version_id, "FONT_SIZE", "Numeral/letter height",
                      "MRP", "ALL", {"type": "visual_geometric"})


class TestRuleEngineFixtures(unittest.TestCase):
    def setUp(self):
        reset_db()
        self.rv_id = make_rule_version()
        _standard_requirements(self.rv_id)
        self.rule_version = select_rule_version("PACKAGED_FOOD_FMCG", "2024-01-01")
        self.assertIsNotNone(self.rule_version)

    def _by_field(self, results, field_type):
        return next(r for r in results if r["field_type"] == field_type)

    # ---- Fixture 1: everything present and well-formed -> all COMPLIANT ----
    def test_fully_compliant_fields_yield_compliant_verdicts(self):
        fields = [
            make_field("MANUFACTURER", "Manufactured by ABC Foods Pvt Ltd, Pune 411019",
                       {"has_address_block": True, "qualified": True}, 0.95),
            make_field("GENERIC_NAME", "Generic Name: Wheat Biscuits", {"name": "Wheat Biscuits"}, 0.93),
            make_field("NET_QUANTITY", "Net Qty. 500 g", {"value": 500.0, "unit": "g"}, 0.94),
            make_field("MRP", "MRP Rs. 99.00 (Incl. of all taxes)", {"value": 99.0, "currency": "INR"}, 0.95),
            make_field("MFG_DATE", "Mfg Date: 11/2025", {"iso": "2025-11", "precision": "month"}, 0.92),
            make_field("CONSUMER_CARE", "Consumer Care: 1800-000-0000", {"has_contact_detail": True}, 0.90),
        ]
        results = evaluate_check(self.rule_version, fields, GOOD_QUALITY, panel_bbox=[0, 0, 800, 600])

        for field_type in ("MANUFACTURER", "GENERIC_NAME", "NET_QUANTITY", "MFG_DATE", "CONSUMER_CARE"):
            r = self._by_field(results, field_type)
            self.assertEqual(r["verdict"], "COMPLIANT", f"{field_type} reason: {r['reason']}")

    # ---- Fixture 2: consumer care missing, high-quality image -> POTENTIAL_NON_COMPLIANCE ----
    def test_missing_consumer_care_is_potential_non_compliance(self):
        fields = [
            make_field("MANUFACTURER", "Manufactured by ABC Foods Pvt Ltd, Pune 411019",
                       {"has_address_block": True, "qualified": True}, 0.95),
            make_field("GENERIC_NAME", "Generic Name: Wheat Biscuits", {"name": "Wheat Biscuits"}, 0.93),
            make_field("NET_QUANTITY", "Net Qty. 500 g", {"value": 500.0, "unit": "g"}, 0.94),
            make_field("MRP", "MRP Rs. 99.00 (Incl. of all taxes)", {"value": 99.0, "currency": "INR"}, 0.95),
            make_field("MFG_DATE", "Mfg Date: 11/2025", {"iso": "2025-11", "precision": "month"}, 0.92),
            # no CONSUMER_CARE field at all
        ]
        results = evaluate_check(self.rule_version, fields, GOOD_QUALITY, panel_bbox=[0, 0, 800, 600])
        r = self._by_field(results, "CONSUMER_CARE")
        self.assertEqual(r["verdict"], "POTENTIAL_NON_COMPLIANCE")

    # ---- Fixture 3: font-size under high curvature -> REQUIRES_OFFICER_VERIFICATION ----
    def test_font_size_under_curvature_requires_officer_verification(self):
        fields = [
            make_field("MRP", "MRP Rs. 99.00 (Incl. of all taxes)", {"value": 99.0, "currency": "INR"}, 0.7,
                       bbox=[20, 20, 100, 8]),
        ]
        results = evaluate_check(self.rule_version, fields, CURVED_QUALITY, panel_bbox=[0, 0, 800, 600])
        # Two requirements share field_type MRP (the MRP requirement itself,
        # and the FONT_SIZE visual-geometric requirement) -- match by name.
        font_result = next(r for r in results if r["requirement_name"] == "Numeral/letter height")
        self.assertEqual(font_result["verdict"], "REQUIRES_OFFICER_VERIFICATION")
        self.assertIn("curved", font_result["reason"].lower())

    # ---- Fixture 4: cropped image, manufacturer block not visible -> INSUFFICIENT_EVIDENCE ----
    def test_cropped_image_missing_manufacturer_is_insufficient_evidence(self):
        fields = []  # nothing extracted at all -- simulates a badly cropped photo
        results = evaluate_check(self.rule_version, fields, POOR_QUALITY, panel_bbox=[0, 0, 800, 600])
        r = self._by_field(results, "MANUFACTURER")
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")

    # ---- Additional: manufacturer present but unqualified -> REQUIRES_OFFICER_VERIFICATION ----
    def test_manufacturer_without_qualifier_requires_verification(self):
        fields = [
            make_field("MANUFACTURER", "ABC Foods, Pune 411019",
                       {"has_address_block": True, "qualified": False}, 0.9),
        ]
        results = evaluate_check(self.rule_version, fields, GOOD_QUALITY, panel_bbox=[0, 0, 800, 600])
        r = self._by_field(results, "MANUFACTURER")
        self.assertEqual(r["verdict"], "REQUIRES_OFFICER_VERIFICATION")

    # ---- Additional: net quantity present but doesn't parse -> POTENTIAL_NON_COMPLIANCE ----
    def test_net_quantity_bad_format_is_potential_non_compliance(self):
        fields = [
            make_field("NET_QUANTITY", "Net Qty. see label", {}, 0.6),
        ]
        results = evaluate_check(self.rule_version, fields, GOOD_QUALITY, panel_bbox=[0, 0, 800, 600])
        r = self._by_field(results, "NET_QUANTITY")
        self.assertEqual(r["verdict"], "POTENTIAL_NON_COMPLIANCE")

    # ---- Never returns the word "illegal" anywhere ----
    def test_no_result_ever_uses_the_word_illegal(self):
        fields = []
        results = evaluate_check(self.rule_version, fields, POOR_QUALITY, panel_bbox=[0, 0, 800, 600])
        for r in results:
            self.assertNotIn("illegal", r["reason"].lower())
            self.assertIn(r["verdict"], (
                "COMPLIANT", "POTENTIAL_NON_COMPLIANCE",
                "REQUIRES_OFFICER_VERIFICATION", "INSUFFICIENT_EVIDENCE",
            ))


class TestRuleEngineApplicability(unittest.TestCase):
    def setUp(self):
        reset_db()
        self.rv_id = make_rule_version()
        make_requirement(self.rv_id, "COUNTRY_OF_ORIGIN", "Country of origin",
                          "COUNTRY_OF_ORIGIN", "IMPORTED_ONLY", {"type": "presence"})
        self.rule_version = select_rule_version("PACKAGED_FOOD_FMCG", "2024-01-01")

    def test_domestic_origin_produces_no_result_row(self):
        """A product declared as made in India should not have the
        imported-only country-of-origin requirement flagged as missing --
        it's genuinely not applicable, not a violation."""
        fields = [make_field("COUNTRY_OF_ORIGIN", "Country of Origin: India", {"country": "India"}, 0.9)]
        results = evaluate_check(self.rule_version, fields, GOOD_QUALITY)
        self.assertEqual(len(results), 0)

    def test_unknown_origin_status_is_insufficient_evidence_not_skipped(self):
        """When the image gives no signal about import status at all, the
        requirement should surface as INSUFFICIENT_EVIDENCE (applicability
        itself is uncertain), not be silently dropped."""
        fields = []
        results = evaluate_check(self.rule_version, fields, GOOD_QUALITY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_imported_product_is_evaluated(self):
        fields = [make_field("COUNTRY_OF_ORIGIN", "Made in Germany", {"country": "Germany"}, 0.9)]
        results = evaluate_check(self.rule_version, fields, GOOD_QUALITY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["verdict"], "COMPLIANT")


class TestRuleVersionSelection(unittest.TestCase):
    def setUp(self):
        reset_db()

    def test_selects_version_covering_the_audit_date(self):
        make_rule_version(effective_from="2020-01-01", effective_to="2023-01-01", version_label="1.0", status="RETIRED")
        v2_id = make_rule_version(effective_from="2023-01-01", effective_to=None, version_label="1.1", status="ACTIVE")
        selected = select_rule_version("PACKAGED_FOOD_FMCG", "2024-06-01")
        self.assertEqual(selected["id"], v2_id)

    def test_no_active_version_for_unsupported_category_returns_none(self):
        make_rule_version(category="PACKAGED_FOOD_FMCG")
        selected = select_rule_version("ELECTRONICS", "2024-06-01")
        self.assertIsNone(selected)

    def test_draft_version_is_never_selected(self):
        make_rule_version(status="DRAFT", effective_from="2020-01-01")
        selected = select_rule_version("PACKAGED_FOOD_FMCG", "2024-06-01")
        self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
