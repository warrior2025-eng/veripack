import os
import unittest

from tests.testutils import reset_db, make_user, make_rule_version, make_requirement
from db.database import get_db, to_json
from veripack.reports import generate_report, VERDICT_LABELS


class TestReportGeneration(unittest.TestCase):
    def setUp(self):
        reset_db()
        self.user_id = make_user()
        self.rv_id = make_rule_version()
        self.req_id = make_requirement(self.rv_id)

        with get_db() as cur:
            cur.execute("INSERT INTO product (id, name, category, organization_id) VALUES (1, 'Test Product', 'PACKAGED_FOOD_FMCG', 1)")
            cur.execute("INSERT INTO product_image (id, product_id, file_path, source) VALUES (1, 1, 'x.jpg', 'UPLOAD')")
            cur.execute(
                """INSERT INTO compliance_check
                   (id, product_id, product_image_id, submitted_by, organization_id, status,
                    category, rule_version_id, ocr_engine_version, pipeline_version, image_quality_score)
                   VALUES (1, 1, 1, ?, 1, 'COMPLETED', 'PACKAGED_FOOD_FMCG', ?, 'tesseract-test', 'pipeline-test', 0.9)""",
                (self.user_id, self.rv_id),
            )
            cur.execute(
                """INSERT INTO requirement_result
                   (compliance_check_id, rule_requirement_id, verdict, confidence, reason, rule_reference)
                   VALUES (1, ?, 'POTENTIAL_NON_COMPLIANCE', 0.8, 'Test reason for the report.', 'Rule 6(1)(a)')""",
                (self.req_id,),
            )
        self.check_id = 1

    def test_generate_report_creates_a_real_pdf_file(self):
        path = generate_report(self.check_id, self.user_id)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 1000)  # not an empty/stub file
        with open(path, "rb") as f:
            header = f.read(5)
        self.assertEqual(header, b"%PDF-")

    def test_report_row_is_persisted(self):
        generate_report(self.check_id, self.user_id)
        with get_db() as cur:
            cur.execute("SELECT * FROM report WHERE compliance_check_id=?", (self.check_id,))
            row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["generated_by"], self.user_id)

    def test_vocabulary_never_includes_the_word_illegal(self):
        # Structural guarantee check on the label map itself, not just this
        # one report's text -- see reports.py's VERDICT_LABELS docstring.
        for label in VERDICT_LABELS.values():
            self.assertNotIn("illegal", label.lower())

    def test_missing_check_raises_rather_than_producing_a_blank_report(self):
        with self.assertRaises(ValueError):
            generate_report(99999, self.user_id)


if __name__ == "__main__":
    unittest.main()
