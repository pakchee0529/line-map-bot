import unittest

import app as app_module


class PythonFlexRoutesTest(unittest.TestCase):
    def setUp(self):
        self.original_base_url = app_module.BASE_URL
        self.original_tiles = app_module.MAP_PREVIEW_TILES_ENABLED
        self.original_tile_source = app_module.MAP_PREVIEW_TILE_SOURCE
        app_module.BASE_URL = "https://line-map-bot-ouvo.onrender.com"
        app_module.MAP_PREVIEW_TILES_ENABLED = False
        app_module.MAP_PREVIEW_TILE_SOURCE = "gsi_aerial"
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.BASE_URL = self.original_base_url
        app_module.MAP_PREVIEW_TILES_ENABLED = self.original_tiles
        app_module.MAP_PREVIEW_TILE_SOURCE = self.original_tile_source

    def test_two_point_search_builds_flex_ready_card(self):
        response = app_module.build_search_response(
            "木ノ原40E1S3～木ノ原40E1S4"
        )
        self.assertEqual(len(response["cards"]), 1)
        card = response["cards"][0]
        self.assertEqual(card["status"], "found")
        self.assertEqual(len(card["rows"]), 2)
        self.assertIn("/multi-map?", card["primary_url"])
        self.assertIn("/api/map-preview?", card["preview_url"])
        self.assertIn("connect=1", card["preview_url"])

    def test_single_pole_search_keeps_nearby_poles_in_flex_card(self):
        response = app_module.build_search_response("木ノ原40E1S3")
        self.assertEqual(len(response["cards"]), 1)
        card = response["cards"][0]
        self.assertEqual(card["status"], "found")
        self.assertIn("/map?lat=", card["primary_url"])
        self.assertEqual(card["primary_label"], "近くの電柱を見る")
        self.assertIn("google.com/maps", card["secondary_url"])
        self.assertEqual(card["secondary_label"], "Googleマップで地点確認")
        self.assertTrue(any(row["label"] == "近隣電柱" for row in card["rows"]))
        self.assertIn("%7C", card["preview_url"])
        self.assertNotIn("connect=1", card["preview_url"])

    def test_map_preview_route_returns_png(self):
        response = self.client.get(
            "/api/map-preview",
            query_string={
                "points": "34.35771,135.6636|34.3575,135.66363",
                "connect": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertGreater(len(response.data), 1000)

    def test_health_exposes_safe_feature_flags(self):
        response = self.client.get("/healthz/search")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("flex_reply_enabled", payload)
        self.assertIn("map_preview_tiles_enabled", payload)
        self.assertEqual(payload["map_preview_tile_source"], "gsi_aerial")


if __name__ == "__main__":
    unittest.main()
