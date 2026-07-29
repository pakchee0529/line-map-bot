import os
import unittest
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("BASE_URL", "https://example.invalid")

import app as app_module


class ExistingSearchRegressionTest(unittest.TestCase):
    def test_known_two_point_span_still_resolves_both_poles(self):
        result = app_module.resolve_one("木ノ原40E1S3～40E1S4")

        self.assertTrue(result["found"])
        self.assertTrue(result["is_range"])
        self.assertEqual(result["adopted"], "木ノ原40E1S4")
        self.assertIsNotNone(result["span_map_url"])

        parsed = urlparse(result["span_map_url"])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/multi-map")
        self.assertEqual(query["p1n"], ["木ノ原40E1S3"])
        self.assertEqual(query["p2n"], ["木ノ原40E1S4"])
        self.assertEqual(query["p1"], ["34.35771,135.6636"])
        self.assertEqual(query["p2"], ["34.3575,135.66363"])

    def test_pc_search_g9_completion_is_available(self):
        result = app_module.resolve_one("出谷49G1")

        self.assertTrue(result["found"])
        self.assertEqual(result["adopted"], "出谷49G1G9")
        self.assertTrue(any("G9" in warning for warning in result["warnings"]))

    def test_unresolved_key_returns_same_place_suggestions(self):
        result = app_module.resolve_one("西川118G1G9")

        self.assertFalse(result["found"])
        self.assertTrue(result["suggestion_details"])
        self.assertTrue(
            all(
                str(item["name"]).startswith("西川")
                for item in result["suggestion_details"]
            )
        )

    def test_place_name_search_collects_registered_poles(self):
        points = app_module.find_place_points("木ノ原")

        self.assertGreater(len(points), 1)
        self.assertTrue(
            all(str(point["display_name"]).startswith("木ノ原") for point in points)
        )

    def test_search_health_identifies_engine_and_gps_data(self):
        response = app_module.app.test_client().get("/healthz/search")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["search_engine"], "pc-core-v2")
        self.assertEqual(payload["gps_count"], len(app_module.POLE_COORDS))
        self.assertEqual(len(payload["gps_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
