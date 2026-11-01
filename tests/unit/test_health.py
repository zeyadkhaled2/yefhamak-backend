"""HTTP smoke checks with an overridden database dependency."""
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()

    def test_health_requires_no_database_query(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.db.execute.assert_not_called()

    def test_database_health_success(self):
        response = self.client.get('/health/db')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'database': 'connected'})
        self.db.execute.assert_called_once()

    def test_database_health_failure(self):
        self.db.execute.side_effect = RuntimeError('offline')
        response = self.client.get('/health/db')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'database unreachable'})
