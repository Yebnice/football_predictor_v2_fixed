"""Test security configuration validation."""
import unittest
import os
from app.config import Settings

class TestConfigSecurity(unittest.TestCase):
    """Test that security configuration is properly validated."""

    def setUp(self):
        # Each test mutates os.environ directly (Settings reads it, plus
        # pydantic-settings also reads .env, so isolating just the keys these
        # tests touch keeps them from leaking into later tests/CI runs).
        self._env_keys = ("APP_ENV", "RNG_SALT", "AUTH_JWT_SECRET")
        self._saved_env = {k: os.environ.get(k) for k in self._env_keys}

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_settings_warning_in_production(self):
        """Test that default security values trigger warnings in production."""
        # Set production environment with default values
        os.environ['APP_ENV'] = 'production'
        os.environ['RNG_SALT'] = 'change-me'
        os.environ['AUTH_JWT_SECRET'] = 'change-me-too'

        with self.assertRaises(ValueError):
            Settings()

    def test_secure_settings_no_warning(self):
        """Test that secure values don't trigger warnings."""
        os.environ['APP_ENV'] = 'production'
        os.environ['RNG_SALT'] = 'secure-random-salt-12345'
        os.environ['AUTH_JWT_SECRET'] = 'secure-jwt-secret-67890'

        settings = Settings()
        self.assertEqual(settings.app_env, 'production')
        self.assertEqual(settings.rng_salt, 'secure-random-salt-12345')
        self.assertEqual(settings.auth_jwt_secret, 'secure-jwt-secret-67890')

    def test_development_environment_allows_defaults(self):
        """Test that development environment allows default values."""
        os.environ['APP_ENV'] = 'development'
        os.environ['RNG_SALT'] = 'change-me'
        os.environ['AUTH_JWT_SECRET'] = 'change-me-too'

        settings = Settings()
        self.assertEqual(settings.app_env, 'development')
        # In development, defaults are acceptable

if __name__ == '__main__':
    unittest.main()