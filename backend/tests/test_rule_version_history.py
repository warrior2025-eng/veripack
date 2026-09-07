import unittest

from tests.testutils import reset_db, make_user
from veripack.auth import hash_password
import main
from db.database import get_db


class TestRuleVersionHistoricalReproducibility(unittest.TestCase):
    """PRD Part 47: historical results must never silently change when the
    regulatory rule set is updated. This is the product's core promise --
    an admin can activate a new RuleVersion, and old checks keep citing the
    RuleVersion that was actually active when they ran."""

    def setUp(self):
        reset_db()
        self.admin_id = make_user("admin@test.demo", "ADMIN", "Test Admin",
                                   password_hash=hash_password("Password123!"))
        self.app = main.create_app()
        self.client = self.app.test_client()
        resp = self.client.post("/api/auth/login", json={"email": "admin@test.demo", "password": "Password123!"})
        self.token = resp.get_json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _create_and_activate_rule_version(self, version_label, effective_from):
        resp = self.client.post("/api/rules", headers=self.headers, json={
            "name": "Test Rules", "version_label": version_label, "category": "PACKAGED_FOOD_FMCG",
            "source_document": "Test Source Document",
        })
        rv_id = resp.get_json()["id"]
        self.client.post(f"/api/rules/{rv_id}/requirements", headers=self.headers, json={
            "requirement_code": "MRP", "requirement_name": "MRP", "field_type": "MRP",
            "applicability_logic": "ALL", "severity": "MEDIUM", "source_citation": "Test",
            "validation_logic": {"type": "presence"},
        })
        activate_resp = self.client.post(f"/api/rules/{rv_id}/activate", headers=self.headers,
                                          json={"effective_from": effective_from})
        self.assertEqual(activate_resp.status_code, 200, activate_resp.get_json())
        return rv_id

    def test_old_check_keeps_referencing_retired_rule_version(self):
        v1_id = self._create_and_activate_rule_version("1.0", "2024-01-01")

        # Manually insert a compliance_check as if it ran while v1 was active
        # (bypassing the full image pipeline -- this test is about rule
        # version binding, not OCR).
        with get_db() as cur:
            cur.execute(
                "INSERT INTO compliance_check (status, category, rule_version_id, audit_date) "
                "VALUES ('COMPLETED', 'PACKAGED_FOOD_FMCG', ?, '2024-06-01')", (v1_id,))
            check_id = cur.lastrowid

        # Now the law changes: v2 is created and activated.
        v2_id = self._create_and_activate_rule_version("1.1", "2026-01-01")
        self.assertNotEqual(v1_id, v2_id)

        # v1 should now be RETIRED (auto-closed by the activation of v2)...
        v1_resp = self.client.get(f"/api/rules/{v1_id}", headers=self.headers).get_json()
        self.assertEqual(v1_resp["rule_version"]["status"], "RETIRED")

        # ...but the OLD check's rule_version_id must be completely unchanged.
        with get_db() as cur:
            cur.execute("SELECT rule_version_id FROM compliance_check WHERE id=?", (check_id,))
            row = cur.fetchone()
        self.assertEqual(row["rule_version_id"], v1_id)

    def test_rule_version_locks_once_used_by_a_check(self):
        v1_id = self._create_and_activate_rule_version("1.0", "2024-01-01")
        with get_db() as cur:
            cur.execute(
                "INSERT INTO compliance_check (status, category, rule_version_id, audit_date) "
                "VALUES ('COMPLETED', 'PACKAGED_FOOD_FMCG', ?, '2024-06-01')", (v1_id,))

        # Attempting to add a requirement to a locked, already-used version must fail.
        resp = self.client.post(f"/api/rules/{v1_id}/requirements", headers=self.headers, json={
            "requirement_code": "NEW_REQ", "requirement_name": "New", "field_type": "MRP",
            "applicability_logic": "ALL", "severity": "LOW", "source_citation": "x",
            "validation_logic": {"type": "presence"},
        })
        self.assertEqual(resp.status_code, 409)

    def test_duplicate_creates_editable_draft_from_locked_version(self):
        v1_id = self._create_and_activate_rule_version("1.0", "2024-01-01")
        resp = self.client.post(f"/api/rules/{v1_id}/duplicate", headers=self.headers,
                                json={"version_label": "1.0-copy"})
        self.assertEqual(resp.status_code, 201, resp.get_json())
        new_id = resp.get_json()["id"]
        detail = self.client.get(f"/api/rules/{new_id}", headers=self.headers).get_json()
        self.assertEqual(detail["rule_version"]["status"], "DRAFT")
        self.assertEqual(len(detail["requirements"]), 1)  # requirement copied across


if __name__ == "__main__":
    unittest.main()
