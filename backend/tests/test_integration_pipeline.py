"""
Integration test: image -> OCR -> extraction -> rule engine -> result ->
evidence -> report, run against the actual synthetic demo label images
(see seed/generate_demo_images.py), through the real Flask API -- no
mocking of the pipeline stages. This is the same path the SIH demo (PRD
Part 32) exercises live.
"""

import os
import unittest

from tests.testutils import reset_db, make_user
from veripack.auth import hash_password
import main
from db.database import get_db
from seed.generate_demo_images import generate_all


class TestFullPipelineIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_db()
        cls.officer_id = make_user("officer@integration.test", "OFFICER", "Integration Officer",
                                    password_hash=hash_password("Password123!"))
        cls.admin_id = make_user("admin@integration.test", "ADMIN", "Integration Admin",
                                  password_hash=hash_password("Password123!"))

        # Seed minimal ACTIVE rule versions for both MVP categories so the
        # pipeline has something real to evaluate against (mirrors what
        # seed/seed_data.py does for the full demo dataset).
        with get_db() as cur:
            cur.execute(
                """INSERT INTO rule_version (name, version_label, category, status, effective_from,
                                              source_document, source_reference, created_by, locked)
                   VALUES ('Integration Test Rules - Food', '1.0', 'PACKAGED_FOOD_FMCG', 'ACTIVE',
                           '2020-01-01', 'Legal Metrology (Packaged Commodities) Rules, 2011', 'Rule 6', ?, 0)""",
                (cls.admin_id,))
            rv_id = cur.lastrowid
            for code, name, field_type, vtype, extra in [
                ("MANUFACTURER", "Manufacturer / Packer / Importer", "MANUFACTURER", "qualified_presence", {}),
                ("GENERIC_NAME", "Generic name", "GENERIC_NAME", "presence", {}),
                ("NET_QUANTITY", "Net quantity", "NET_QUANTITY", "format", {"requires": ["value", "unit"]}),
                ("MRP", "MRP", "MRP", "format", {"requires": ["value", "currency"]}),
                ("MFG_DATE", "Mfg date", "MFG_DATE", "presence", {}),
                ("CONSUMER_CARE", "Consumer care", "CONSUMER_CARE", "presence", {}),
            ]:
                from db.database import to_json
                validation_logic = {"type": vtype, **extra}
                cur.execute(
                    """INSERT INTO rule_requirement
                       (rule_version_id, requirement_code, requirement_name, field_type,
                        applicability_logic, validation_logic, severity, source_citation, enabled)
                       VALUES (?,?,?,?, 'ALL', ?, 'MEDIUM', 'Rule 6, PC Rules 2011', 1)""",
                    (rv_id, code, name, field_type, to_json(validation_logic)),
                )

        # Generate the real synthetic demo label images used across the app.
        test_image_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_test_data", "demo_images")
        cls.demo_paths = generate_all(test_image_dir)

        cls.app = main.create_app()
        cls.client = cls.app.test_client()

    def _login(self, email="officer@integration.test"):
        resp = self.client.post("/api/auth/login", json={"email": email, "password": "Password123!"})
        return resp.get_json()["token"]

    def test_full_pipeline_on_compliant_demo_image(self):
        token = self._login()
        headers = {"Authorization": f"Bearer {token}"}
        image_path = self.demo_paths["compliant"]

        with open(image_path, "rb") as f:
            resp = self.client.post("/api/checks", headers=headers,
                                     data={"image": (f, "compliant.jpg"), "product_name": "Integration Test Product"},
                                     content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 201, resp.get_json())
        check_id = resp.get_json()["check_id"]

        process_resp = self.client.post(f"/api/checks/{check_id}/process", headers=headers)
        self.assertEqual(process_resp.status_code, 200, process_resp.get_json())
        self.assertEqual(process_resp.get_json()["status"], "COMPLETED")

        # OCR + extraction actually ran and found real fields
        with get_db() as cur:
            cur.execute("SELECT COUNT(*) as c FROM extracted_field WHERE compliance_check_id=?", (check_id,))
            field_count = cur.fetchone()["c"]
        self.assertGreater(field_count, 0, "OCR/extraction produced zero fields -- pipeline did not really run")

        # Rule engine produced per-requirement results
        results_resp = self.client.get(f"/api/checks/{check_id}/results", headers=headers)
        results = results_resp.get_json()["results"]
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn(r["verdict"], ("COMPLIANT", "POTENTIAL_NON_COMPLIANCE",
                                          "REQUIRES_OFFICER_VERIFICATION", "INSUFFICIENT_EVIDENCE"))
            self.assertNotIn("illegal", r["reason"].lower())

        # Evidence: annotated image was actually written to disk
        evidence_resp = self.client.get(f"/api/checks/{check_id}/evidence", headers=headers)
        evidence_items = evidence_resp.get_json()["evidence"]
        annotated = [e for e in evidence_items if e["kind"] == "ANNOTATED_IMAGE"]
        self.assertEqual(len(annotated), 1)
        self.assertTrue(os.path.exists(annotated[0]["file_path"]))
        self.assertGreater(os.path.getsize(annotated[0]["file_path"]), 0)

        # Report: a real PDF comes back
        report_resp = self.client.post(f"/api/checks/{check_id}/report", headers=headers)
        self.assertEqual(report_resp.status_code, 200, report_resp.get_json())
        download_resp = self.client.get(f"/api/checks/{check_id}/report", headers=headers)
        self.assertEqual(download_resp.status_code, 200)
        self.assertEqual(download_resp.data[:5], b"%PDF-")

        # Inspection history includes this check
        history_resp = self.client.get("/api/checks", headers=headers)
        ids = [c["id"] for c in history_resp.get_json()["checks"]]
        self.assertIn(check_id, ids)

    def test_full_pipeline_on_missing_declaration_demo_flags_the_missing_field(self):
        token = self._login()
        headers = {"Authorization": f"Bearer {token}"}
        image_path = self.demo_paths["missing_declaration"]

        with open(image_path, "rb") as f:
            resp = self.client.post("/api/checks", headers=headers,
                                     data={"image": (f, "missing.jpg")}, content_type="multipart/form-data")
        check_id = resp.get_json()["check_id"]
        self.client.post(f"/api/checks/{check_id}/process", headers=headers)

        results = self.client.get(f"/api/checks/{check_id}/results", headers=headers).get_json()["results"]
        consumer_care = next((r for r in results if r["field_type"] == "CONSUMER_CARE"), None)
        self.assertIsNotNone(consumer_care, "consumer care requirement should still produce a result row")
        self.assertEqual(consumer_care["verdict"], "POTENTIAL_NON_COMPLIANCE")

    def test_audit_trail_captures_the_whole_journey(self):
        token = self._login()
        headers = {"Authorization": f"Bearer {token}"}
        with open(self.demo_paths["compliant"], "rb") as f:
            resp = self.client.post("/api/checks", headers=headers,
                                     data={"image": (f, "x.jpg")}, content_type="multipart/form-data")
        check_id = resp.get_json()["check_id"]
        self.client.post(f"/api/checks/{check_id}/process", headers=headers)

        admin_token = self._login("admin@integration.test")
        logs_resp = self.client.get("/api/audit-logs", headers={"Authorization": f"Bearer {admin_token}"})
        actions = [l["action"] for l in logs_resp.get_json()["audit_logs"]]
        self.assertIn("CHECK_COMPLETED", actions)


if __name__ == "__main__":
    unittest.main()
