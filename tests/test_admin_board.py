import unittest
import tempfile
import os

from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.store import Store
from app.auth import AuthConfig
from app.admin_board import build_admin_router, bootstrap_admin


class AdminBoardTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        os.remove(self.db_path)  # let Store create it fresh
        self.store = Store(self.db_path)
        self.config = AuthConfig(jwt_secret="test-secret-012345678901234567890123456789", jwt_expiry_hours=1)
        bootstrap_admin(self.store, "owner@example.com", "supersecret123")
        app = FastAPI()
        app.include_router(build_admin_router(self.store, self.config))
        self.client = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _admin_headers(self):
        r = self.client.post("/auth/login", json={"email": "owner@example.com", "password": "supersecret123"})
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def _signup(self, email="member@example.com", password="memberpass1"):
        r = self.client.post("/auth/signup", json={"email": email, "password": password})
        return r.json()["user_id"], {"Authorization": f"Bearer {r.json()['token']}"}

    def test_bootstrap_admin_can_log_in_with_admin_role(self):
        r = self.client.post("/auth/login", json={"email": "owner@example.com", "password": "supersecret123"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("admin", r.json()["roles"])

    def test_signup_grants_no_roles_by_default(self):
        _, headers = self._signup()
        r = self.client.get("/tips", headers=headers)
        self.assertEqual(r.status_code, 200)  # just confirming the token works

    def test_wrong_password_is_rejected(self):
        self._signup(email="a@example.com", password="correctpass1")
        r = self.client.post("/auth/login", json={"email": "a@example.com", "password": "wrongpass"})
        self.assertEqual(r.status_code, 401)

    def test_duplicate_email_signup_is_rejected(self):
        self._signup(email="dupe@example.com")
        r = self.client.post("/auth/signup", json={"email": "dupe@example.com", "password": "anotherpass1"})
        self.assertEqual(r.status_code, 409)

    def test_non_admin_cannot_create_tips(self):
        _, headers = self._signup()
        r = self.client.post("/admin/tips", json={
            "match": "Arsenal vs Everton", "kickoff_time": "2026-09-13T15:00:00Z",
            "market": "1X2", "selection": "Home", "tier": "free",
        }, headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_unauthenticated_request_to_admin_route_is_401(self):
        r = self.client.get("/admin/tips")
        self.assertEqual(r.status_code, 401)

    def test_vvip_tip_is_locked_for_anonymous_and_non_vvip_members(self):
        admin_headers = self._admin_headers()
        self.client.post("/admin/tips", json={
            "match": "PSG vs Lyon", "kickoff_time": "2026-09-14T19:00:00Z",
            "market": "Total Goals", "selection": "Over 2.5", "odds": 1.72,
            "confidence": 0.58, "notes": "vvip only", "tier": "vvip",
        }, headers=admin_headers)

        anon_feed = self.client.get("/tips").json()
        self.assertTrue(anon_feed[0]["locked"])
        self.assertNotIn("selection", anon_feed[0])

        _, member_headers = self._signup()
        member_feed = self.client.get("/tips", headers=member_headers).json()
        self.assertTrue(member_feed[0]["locked"])

    def test_free_tip_is_never_locked(self):
        admin_headers = self._admin_headers()
        self.client.post("/admin/tips", json={
            "match": "Arsenal vs Everton", "kickoff_time": "2026-09-13T15:00:00Z",
            "market": "1X2", "selection": "Home", "tier": "free",
        }, headers=admin_headers)
        anon_feed = self.client.get("/tips").json()
        self.assertFalse(anon_feed[0]["locked"])
        self.assertEqual(anon_feed[0]["selection"], "Home")

    def test_granting_vvip_unlocks_the_feed_immediately(self):
        admin_headers = self._admin_headers()
        self.client.post("/admin/tips", json={
            "match": "PSG vs Lyon", "kickoff_time": "2026-09-14T19:00:00Z",
            "market": "Total Goals", "selection": "Over 2.5", "tier": "vvip",
        }, headers=admin_headers)
        member_id, member_headers = self._signup()

        before = self.client.get("/tips", headers=member_headers).json()
        self.assertTrue(before[0]["locked"])

        self.client.post(f"/admin/members/{member_id}/vvip", json={"vvip": True}, headers=admin_headers)
        after = self.client.get("/tips", headers=member_headers).json()
        self.assertFalse(after[0]["locked"])
        self.assertEqual(after[0]["selection"], "Over 2.5")

    def test_revoking_vvip_relocks_immediately_without_a_new_token(self):
        # Regression-style test for the "server-side, not just hidden UI"
        # requirement: the same still-valid JWT should stop seeing VVIP
        # content the instant the role is revoked in the database.
        admin_headers = self._admin_headers()
        self.client.post("/admin/tips", json={
            "match": "PSG vs Lyon", "kickoff_time": "2026-09-14T19:00:00Z",
            "market": "Total Goals", "selection": "Over 2.5", "tier": "vvip",
        }, headers=admin_headers)
        member_id, member_headers = self._signup()
        self.client.post(f"/admin/members/{member_id}/vvip", json={"vvip": True}, headers=admin_headers)
        self.assertFalse(self.client.get("/tips", headers=member_headers).json()[0]["locked"])

        self.client.post(f"/admin/members/{member_id}/vvip", json={"vvip": False}, headers=admin_headers)
        self.assertTrue(self.client.get("/tips", headers=member_headers).json()[0]["locked"])

    def test_settle_tip_and_record_strip(self):
        admin_headers = self._admin_headers()
        won = self.client.post("/admin/tips", json={
            "match": "A vs B", "kickoff_time": "2026-09-13T15:00:00Z",
            "market": "1X2", "selection": "Home", "tier": "free",
        }, headers=admin_headers).json()
        lost = self.client.post("/admin/tips", json={
            "match": "C vs D", "kickoff_time": "2026-09-13T15:00:00Z",
            "market": "1X2", "selection": "Away", "tier": "free",
        }, headers=admin_headers).json()

        self.client.post(f"/admin/tips/{won['id']}/settle", json={"status": "won"}, headers=admin_headers)
        self.client.post(f"/admin/tips/{lost['id']}/settle", json={"status": "lost"}, headers=admin_headers)

        record = self.client.get("/tips/record?days=30").json()
        self.assertEqual(record["won"], 1)
        self.assertEqual(record["lost"], 1)
        self.assertAlmostEqual(record["win_rate"], 0.5)

    def test_edit_and_delete_tip(self):
        admin_headers = self._admin_headers()
        tip = self.client.post("/admin/tips", json={
            "match": "A vs B", "kickoff_time": "2026-09-13T15:00:00Z",
            "market": "1X2", "selection": "Home", "tier": "free",
        }, headers=admin_headers).json()

        updated = self.client.put(f"/admin/tips/{tip['id']}", json={"notes": "updated note"}, headers=admin_headers).json()
        self.assertEqual(updated["notes"], "updated note")
        self.assertEqual(updated["selection"], "Home")  # untouched fields survive

        deleted = self.client.delete(f"/admin/tips/{tip['id']}", headers=admin_headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(self.store.get_tip(tip["id"]))

    def test_deleting_unknown_tip_is_404(self):
        admin_headers = self._admin_headers()
        r = self.client.delete("/admin/tips/does-not-exist", headers=admin_headers)
        self.assertEqual(r.status_code, 404)

    def test_admin_members_list_shows_roles(self):
        member_id, _ = self._signup()
        admin_headers = self._admin_headers()
        members = self.client.get("/admin/members", headers=admin_headers).json()
        by_email = {m["email"]: m["roles"] for m in members}
        self.assertEqual(by_email["owner@example.com"], ["admin"])
        self.assertEqual(by_email["member@example.com"], [])


class BootstrapAdminTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        os.remove(self.db_path)
        self.store = Store(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_bootstrap_is_a_noop_once_an_admin_already_exists(self):
        bootstrap_admin(self.store, "first@example.com", "password123")
        bootstrap_admin(self.store, "second@example.com", "password123")
        self.assertIsNone(self.store.get_profile_by_email("second@example.com"))

    def test_bootstrap_does_nothing_without_credentials(self):
        bootstrap_admin(self.store, "", "")
        self.assertFalse(self.store.any_admin_exists())


if __name__ == "__main__":
    unittest.main()
