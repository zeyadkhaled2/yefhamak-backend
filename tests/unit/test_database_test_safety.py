"""Test URL validation without making a connection or loading local credentials."""
import os
import unittest
from unittest.mock import patch

from tests.integration.database import configure_test_environment, test_database_url


class DatabaseTestSafetyTests(unittest.TestCase):
    def test_only_explicit_loopback_postgres_test_database_is_accepted(self):
        value = test_database_url('postgresql://test:test@127.0.0.1:5432/yefhamak_test')
        self.assertTrue(value.startswith('postgresql+psycopg://'))
        test_database_url('postgresql://test:test@localhost:5432/yefhamak_test_local?connect_timeout=5')

    def test_missing_or_unsafe_targets_are_rejected(self):
        for url in [None, '', 'invalid', 'sqlite://',
                    'postgresql://test:test@db.neon.tech/yefhamak_test',
                    'postgresql://test:test@localhost/production',
                    'postgresql://test:test@localhost/yefhamak_testing',
                    'postgresql://test:test@localhost/yefhamak_test?host=remote.example',
                    'postgresql://test:test@localhost/yefhamak_test?service=production',
                    'postgresql://test:test@localhost/yefhamak_test?dbname=production']:
            with self.subTest(target=url):
                with self.assertRaises(ValueError):
                    test_database_url(url)

    def test_never_falls_back_to_application_database(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test:test@localhost/production'}, clear=True):
            with self.assertRaises(ValueError):
                configure_test_environment()
            self.assertNotIn('YEFHAMAK_RUN_DB_TESTS', os.environ)

    def test_configuration_explicitly_disables_model_access(self):
        with patch.dict(os.environ, {'TEST_DATABASE_URL': 'postgresql://test:test@localhost/yefhamak_test',
                                     'OPENROUTER_API_KEY': 'must-be-cleared', 'LIVE_CHAT_ENABLED': 'true'}, clear=True):
            url = configure_test_environment()
            self.assertEqual(os.environ['DATABASE_URL'], url)
            self.assertEqual(os.environ['DIRECT_URL'], url)
            self.assertEqual(os.environ['OPENROUTER_API_KEY'], '')
            self.assertEqual(os.environ['LIVE_CHAT_ENABLED'], 'false')
