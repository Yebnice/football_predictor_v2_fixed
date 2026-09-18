import os
import unittest
from unittest.mock import patch

from app.db import assert_safe_for_current_host


class TestDbSafety(unittest.TestCase):
    def test_render_rejects_supabase_direct_ipv6_endpoint(self):
        with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "shared Session pooler"):
                assert_safe_for_current_host(
                    "postgresql://postgres:pw@db.example-ref.supabase.co:5432/postgres"
                )

    def test_render_accepts_supabase_pooler_endpoint(self):
        with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            assert_safe_for_current_host(
                "postgresql://postgres.example-ref:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
            )


if __name__ == "__main__":
    unittest.main()
