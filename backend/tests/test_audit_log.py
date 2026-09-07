import unittest

from tests.testutils import reset_db, make_user
from db.database import get_db
from veripack import audit


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        reset_db()
        self.user_id = make_user()

    def test_record_writes_a_row(self):
        audit.record(self.user_id, "TEST_ACTION", "test_entity", 123, metadata={"k": "v"})
        with get_db() as cur:
            cur.execute("SELECT * FROM audit_log WHERE action='TEST_ACTION'")
            row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["actor_id"], self.user_id)
        self.assertEqual(row["entity_type"], "test_entity")
        self.assertEqual(row["entity_id"], 123)

    def test_log_alias_matches_record(self):
        self.assertIs(audit.log, audit.record)

    def test_old_and_new_value_are_serialized_as_json(self):
        audit.record(self.user_id, "UPDATED", "widget", 1,
                     old_value={"status": "DRAFT"}, new_value={"status": "ACTIVE"})
        with get_db() as cur:
            cur.execute("SELECT old_value, new_value FROM audit_log WHERE action='UPDATED'")
            row = cur.fetchone()
        self.assertIn("DRAFT", row["old_value"])
        self.assertIn("ACTIVE", row["new_value"])

    def test_no_update_or_delete_function_exists_on_the_module(self):
        # Append-only by construction: there must be no function that could
        # mutate or remove an existing audit_log row.
        self.assertFalse(hasattr(audit, "update_audit_log"))
        self.assertFalse(hasattr(audit, "delete_audit_log"))

    def test_multiple_records_accumulate_rather_than_overwrite(self):
        audit.record(self.user_id, "ACTION_A", "entity", 1)
        audit.record(self.user_id, "ACTION_B", "entity", 1)
        with get_db() as cur:
            cur.execute("SELECT COUNT(*) as c FROM audit_log")
            count = cur.fetchone()["c"]
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
