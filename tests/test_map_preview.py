import unittest
from io import BytesIO

from PIL import Image

from map_preview import (
    HEIGHT,
    WIDTH,
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


if __name__ == "__main__":
    unittest.main()
