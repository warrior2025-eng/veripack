import unittest

from tests.testutils import reset_db, make_user
from veripack.auth import hash_password, verify_password, issue_token, decode_token
import main


class TestPasswordHashing(unittest.TestCase):
    def test_correct_password_verifies(self):
        h = hash_password("correct-horse-battery-staple")
        self.assertTrue(verify_password("correct-horse-battery-staple", h))

    def test_wrong_password_fails(self):
        h = hash_password("correct-horse-battery-staple")
        self.assertFalse(verify_password("wrong-password", h))

    def test_hash_is_not_the_plaintext(self):
        h = hash_password("ChangeMe123!")
        self.assertNotEqual(h, "ChangeMe123!")


class TestJWT(unittest.TestCase):
    def test_issue_and_decode_roundtrip(self):
        user = {"id": 5, "email": "officer@veripack.demo", "role": "OFFICER", "organization_id": 1}
        token = issue_token(user)
        payload = decode_token(token)
        self.assertEqual(payload["sub"], 5)
        self.assertEqual(payload["role"], "OFFICER")


class TestAuthEndpointsAndRBAC(unittest.TestCase):
    def setUp(self):
        reset_db()
        self.officer_id = make_user("officer@test.demo", "OFFICER", "Test Officer",
                                     password_hash=hash_password("Password123!"))
        self.admin_id = make_user("admin@test.demo", "ADMIN", "Test Admin",
                                   password_hash=hash_password("Password123!"))
        self.app = main.create_app()
        self.client = self.app.test_client()

    def _login(self, email, password="Password123!"):
        resp = self.client.post("/api/auth/login", json={"email": email, "password": password})
        return resp.get_json()

    def test_login_succeeds_with_correct_credentials(self):
        data = self._login("officer@test.demo")
        self.assertIn("token", data)
        self.assertEqual(data["user"]["role"], "OFFICER")

    def test_login_fails_with_wrong_password(self):
        resp = self.client.post("/api/auth/login", json={"email": "officer@test.demo", "password": "wrong"})
        self.assertEqual(resp.status_code, 401)

    def test_protected_endpoint_rejects_missing_token(self):
        resp = self.client.get("/api/checks")
        self.assertEqual(resp.status_code, 401)

    def test_protected_endpoint_rejects_garbage_token(self):
        resp = self.client.get("/api/checks", headers={"Authorization": "Bearer not-a-real-token"})
        self.assertEqual(resp.status_code, 401)

    def test_officer_cannot_create_rule_version(self):
        officer_token = self._login("officer@test.demo")["token"]
        resp = self.client.post("/api/rules",
                                headers={"Authorization": f"Bearer {officer_token}"},
                                json={"name": "x", "version_label": "1.0", "category": "PACKAGED_FOOD_FMCG",
                                      "source_document": "x"})
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_create_rule_version(self):
        admin_token = self._login("admin@test.demo")["token"]
        resp = self.client.post("/api/rules",
                                headers={"Authorization": f"Bearer {admin_token}"},
                                json={"name": "Test Rules", "version_label": "1.0",
                                      "category": "PACKAGED_FOOD_FMCG", "source_document": "Test source"})
        self.assertEqual(resp.status_code, 201)

    def test_admin_can_access_officer_endpoints_too(self):
        # Admin is a superset of Officer functionality per PRD 11.20
        admin_token = self._login("admin@test.demo")["token"]
        resp = self.client.get("/api/checks", headers={"Authorization": f"Bearer {admin_token}"})
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
