import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("BASE_URL", "https://example.invalid")

import app as app_module
from cadastral_service import CadastralStore
from tests.cadastral_fixture import create_cadastral_fixture


class CadastralRouteTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "fixture.sqlite"
        create_cadastral_fixture(database_path)
        self.store = CadastralStore(database_path)
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_api_is_hidden_when_feature_flag_is_off(self):
        with patch.object(app_module, "CADASTRAL_LAYER_ENABLED", False):
            response = self.client.get(
                "/api/cadastral/features"
                "?bbox=135.662,34.356,135.665,34.359&zoom=18"
            )
        self.assertEqual(response.status_code, 404)

    def test_api_returns_geojson_when_enabled(self):
        with (
            patch.object(app_module, "CADASTRAL_LAYER_ENABLED", True),
            patch.object(app_module, "CADASTRAL_STORE", self.store),
        ):
            response = self.client.get(
                "/api/cadastral/features"
                "?bbox=135.662,34.356,135.665,34.359&zoom=18"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertEqual(len(payload["features"]), 2)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=300")

    def test_two_point_map_shows_toggle_only_when_enabled(self):
        query = (
            "/multi-map"
            "?p1=34.35771,135.6636&p2=34.3575,135.66363"
            "&p1n=front&p2n=back"
        )
        with (
            patch.object(app_module, "CADASTRAL_LAYER_ENABLED", True),
            patch.object(app_module, "CADASTRAL_STORE", self.store),
        ):
            enabled_response = self.client.get(query)
        self.assertIn(
            'id="cadastral-toggle"',
            enabled_response.get_data(as_text=True),
        )

        with patch.object(app_module, "CADASTRAL_LAYER_ENABLED", False):
            disabled_response = self.client.get(query)
        self.assertNotIn(
            'id="cadastral-toggle"',
            disabled_response.get_data(as_text=True),
        )

    def test_invalid_query_is_rejected_without_database_error(self):
        with (
            patch.object(app_module, "CADASTRAL_LAYER_ENABLED", True),
            patch.object(app_module, "CADASTRAL_STORE", self.store),
        ):
            response = self.client.get(
                "/api/cadastral/features?bbox=bad&zoom=18"
            )
        self.assertEqual(response.status_code, 400)

    def test_cadastral_health_reports_safe_state(self):
        with (
            patch.object(app_module, "CADASTRAL_LAYER_ENABLED", True),
            patch.object(app_module, "CADASTRAL_STORE", self.store),
        ):
            response = self.client.get("/healthz/cadastral")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "available": True,
                "enabled": True,
                "license": "CC BY 4.0",
                "source_date": "2026-01-01",
            },
        )


if __name__ == "__main__":
    unittest.main()
