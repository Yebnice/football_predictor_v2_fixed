"""Test database migration system."""
import unittest
import tempfile
import os
from app.migrations import MigrationRunner, MIGRATIONS, migration

class TestMigrationSystem(unittest.TestCase):
    """Test the migration system functionality."""

    def setUp(self):
        """Create a temporary database for testing."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db_path = self.temp_db.name

    def tearDown(self):
        """Clean up temporary database."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_migration_runner_initialization(self):
        """Test that MigrationRunner initializes correctly."""
        runner = MigrationRunner(self.db_path)
        self.assertIsNotNone(runner)
        self.assertEqual(runner.db_path, self.db_path)

    def test_migration_table_creation(self):
        """Test that migration table is created."""
        runner = MigrationRunner(self.db_path)
        with runner._connect() as conn:
            runner._ensure_migration_table(conn)
            # Check that table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            )
            result = cursor.fetchone()
            self.assertIsNotNone(result)

    def test_migration_registration(self):
        """Test that migrations can be registered."""
        @migration("999_test_migration")
        def test_migration(conn):
            pass

        self.assertIn("999_test_migration", MIGRATIONS)

    def test_get_applied_migrations(self):
        """Test getting applied migrations."""
        runner = MigrationRunner(self.db_path)
        with runner._connect() as conn:
            runner._ensure_migration_table(conn)
            applied = runner._get_applied_migrations(conn)
            self.assertIsInstance(applied, set)
            self.assertEqual(len(applied), 0)  # No migrations applied yet

    def test_record_migration(self):
        """Test recording a migration as applied."""
        runner = MigrationRunner(self.db_path)
        with runner._connect() as conn:
            runner._ensure_migration_table(conn)
            runner._record_migration(conn, "001_test")

            applied = runner._get_applied_migrations(conn)
            self.assertIn("001_test", applied)

if __name__ == '__main__':
    unittest.main()