import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from map_preview import (
    DEFAULT_TILE_SOURCE,
    HEIGHT,
    TILE_SOURCE_GSI_AERIAL,
    TILE_SOURCE_OSM,
    WIDTH,
    _geometry,
    _nearby_label_features,
    normalize_tile_source,
    parse_preview_points,
    render_map_preview,
    serialize_preview_points,
)


class MapPreviewTest(unittest.TestCase):
    def test_points_round_trip(self):
        encoded = serialize_preview_points(
            [
                {"lat": 34.35771, "lng": 135.6636},
                {"lat": 34.3575, "lng": 135.66363},
            ]
        )
        self.assertEqual(
            encoded,
            "34.357710,135.663600|34.357500,135.663630",
        )
        self.assertEqual(
            parse_preview_points(encoded),
            [
                {"lat": 34.35771, "lng": 135.6636},
                {"lat": 34.3575, "lng": 135.66363},
            ],
        )

    def test_renders_offline_two_point_png(self):
        image_bytes = render_map_preview(
            [
                {"lat": 34.35771, "lng": 135.6636},
                {"lat": 34.3575, "lng": 135.66363},
            ],
            use_tiles=False,
            connect_points=True,
        )
        with Image.open(BytesIO(image_bytes)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (WIDTH, HEIGHT))
        self.assertGreater(len(image_bytes), 1000)

    def test_renders_cadastral_overlay(self):
        cadastral = {
            "type": "FeatureCollection",
            "metadata": {"source_date": "test"},
            "features": [
                {
                    "type": "Feature",
                    "properties": {"layer": "parcel"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [135.6634, 34.3574],
                                [135.6638, 34.3574],
                                [135.6638, 34.3578],
                                [135.6634, 34.3578],
                                [135.6634, 34.3574],
                            ]
                        ],
                    },
                }
            ],
        }
        image_bytes = render_map_preview(
            [
                {"lat": 34.35771, "lng": 135.6636},
                {"lat": 34.3575, "lng": 135.66363},
            ],
            use_tiles=False,
            cadastral=cadastral,
            connect_points=True,
        )
        with Image.open(BytesIO(image_bytes)) as image:
            self.assertEqual(image.size, (WIDTH, HEIGHT))

    def test_aerial_is_default_and_osm_remains_available(self):
        self.assertEqual(DEFAULT_TILE_SOURCE, TILE_SOURCE_GSI_AERIAL)
        self.assertEqual(normalize_tile_source("osm"), TILE_SOURCE_OSM)
        self.assertEqual(normalize_tile_source("unknown"), TILE_SOURCE_GSI_AERIAL)

    def test_cadastral_labels_are_limited_to_nearest_two(self):
        points = [
            {"lat": 34.35771, "lng": 135.6636},
            {"lat": 34.3575, "lng": 135.66363},
        ]
        cadastral = {
            "features": [
                {
                    "id": "near-young",
                    "properties": {"layer": "label", "label": "358"},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [135.66359, 34.35772],
                    },
                },
                {
                    "id": "near-old",
                    "properties": {"layer": "label", "label": "372"},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [135.66364, 34.35749],
                    },
                },
                {
                    "id": "extra",
                    "properties": {"layer": "label", "label": "999"},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [135.6645, 34.3585],
                    },
                },
            ]
        }
        selected = _nearby_label_features(
            cadastral,
            _geometry(points),
            _geometry(points)["screen_points"],
        )
        self.assertEqual(
            {feature["id"] for feature in selected},
            {"near-young", "near-old"},
        )

    def test_aerial_failure_falls_back_to_osm(self):
        requested_sources = []

        def fake_tile(_zoom, _x, _y, tile_source):
            requested_sources.append(tile_source)
            if tile_source == TILE_SOURCE_OSM:
                return Image.new("RGB", (256, 256), "white")
            return None

        with patch("map_preview._fetch_tile", side_effect=fake_tile):
            image_bytes = render_map_preview(
                [{"lat": 34.123456, "lng": 135.654321}],
                tile_source=TILE_SOURCE_GSI_AERIAL,
            )
        self.assertGreater(len(image_bytes), 1000)
        self.assertIn(TILE_SOURCE_GSI_AERIAL, requested_sources)
        self.assertIn(TILE_SOURCE_OSM, requested_sources)


if __name__ == "__main__":
    unittest.main()
