import unittest
import importlib.util
from unittest.mock import patch, MagicMock

from app.appwrite_sync import AppwriteSync


def configured_kwargs(**overrides):
    base = dict(endpoint="https://cloud.appwrite.io/v1", project_id="proj123", api_key="key123",
                database_id="db1", profiles_collection_id="profiles", tips_collection_id="tips")
    base.update(overrides)
    return base


@unittest.skipUnless(importlib.util.find_spec("appwrite"), "optional dependency: appwrite")
class AppwriteSyncTests(unittest.TestCase):
    def test_not_configured_when_any_field_missing(self):
        sync = AppwriteSync(**configured_kwargs(project_id=""))
        self.assertFalse(sync.is_configured())

    def test_unconfigured_sync_calls_are_no_ops(self):
        sync = AppwriteSync(endpoint="", project_id="", api_key="", database_id="",
                             profiles_collection_id="", tips_collection_id="")
        # Should not raise even though no client was ever built.
        sync.sync_profile("u1", "a@example.com", ["vvip"])
        sync.sync_tip({"id": "t1", "match": "A vs B", "kickoff_time": "x", "market": "1X2",
                        "selection": "Home", "tier": "free", "status": "pending"})
        sync.delete_tip("t1")

    @patch("appwrite.services.databases.Databases")
    @patch("appwrite.client.Client")
    def test_configured_sync_calls_upsert_document(self, MockClient, MockDatabases):
        mock_client_instance = MagicMock()
        MockClient.return_value.set_endpoint.return_value.set_project.return_value.set_key.return_value = mock_client_instance
        mock_db = MagicMock()
        MockDatabases.return_value = mock_db

        sync = AppwriteSync(**configured_kwargs())
        self.assertTrue(sync.is_configured())
        sync.sync_profile("u1", "a@example.com", ["vvip"])

        mock_db.upsert_document.assert_called_once()
        _, kwargs = mock_db.upsert_document.call_args
        self.assertEqual(kwargs["database_id"], "db1")
        self.assertEqual(kwargs["collection_id"], "profiles")
        self.assertEqual(kwargs["document_id"], "u1")
        self.assertEqual(kwargs["data"], {"email": "a@example.com", "roles": ["vvip"]})

    @patch("appwrite.services.databases.Databases")
    @patch("appwrite.client.Client")
    def test_sync_tip_never_pushes_password_or_extra_fields(self, MockClient, MockDatabases):
        mock_db = MagicMock()
        MockDatabases.return_value = mock_db
        sync = AppwriteSync(**configured_kwargs())
        tip = {"id": "t1", "match": "A vs B", "kickoff_time": "2026-09-13T15:00:00Z", "market": "1X2",
               "selection": "Home", "odds": 1.9, "confidence": 0.6, "notes": "n", "tier": "free",
               "status": "pending", "created_by": "admin-id", "created_at": 123, "updated_at": 456}
        sync.sync_tip(tip)
        _, kwargs = mock_db.upsert_document.call_args
        self.assertNotIn("created_by", kwargs["data"])
        self.assertNotIn("password_hash", kwargs["data"])
        self.assertEqual(kwargs["document_id"], "t1")

    @patch("appwrite.services.databases.Databases")
    @patch("appwrite.client.Client")
    def test_sync_failure_is_swallowed_not_raised(self, MockClient, MockDatabases):
        mock_db = MagicMock()
        mock_db.upsert_document.side_effect = RuntimeError("network down")
        MockDatabases.return_value = mock_db
        sync = AppwriteSync(**configured_kwargs())
        try:
            sync.sync_profile("u1", "a@example.com", [])
        except Exception as exc:  # noqa: BLE001
            self.fail(f"sync_profile raised despite being best-effort: {exc}")

    @patch("appwrite.services.databases.Databases")
    @patch("appwrite.client.Client")
    def test_delete_tip_calls_delete_document(self, MockClient, MockDatabases):
        mock_db = MagicMock()
        MockDatabases.return_value = mock_db
        sync = AppwriteSync(**configured_kwargs())
        sync.delete_tip("t1")
        mock_db.delete_document.assert_called_once_with(database_id="db1", collection_id="tips", document_id="t1")


if __name__ == "__main__":
    unittest.main()
