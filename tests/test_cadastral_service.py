import tempfile
import unittest
from pathlib import Path

from cadastral_service import CadastralQueryError, CadastralStore
from tests.cadastral_fixture import create_cadastral_fixture


class CadastralStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "fixture.sqlite"
        create_cadastral_fixture(database_path)
        self.store = CadastralStore(database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_zoom_controls_returned_layers(self):
        bbox = (135.662, 34.356, 135.665, 34.359)

        zoom17 = self.store.query(bbox, 17)
        self.assertEqual(
            [feature["properties"]["layer"] for feature in zoom17["features"]],
            ["parcel"],
        )

        zoom18 = self.store.query(bbox, 18)
        self.assertEqual(
            {feature["properties"]["layer"] for feature in zoom18["features"]},
            {"parcel", "label"},
        )

        zoom19 = self.store.query(bbox, 19)
        self.assertEqual(
            {feature["properties"]["layer"] for feature in zoom19["features"]},
            {"parcel", "label", "leader"},
        )

    def test_outside_bbox_returns_empty_collection(self):
        result = self.store.query((136.0, 35.0, 136.01, 35.01), 18)
        self.assertEqual(result["features"], [])
        self.assertFalse(result["metadata"]["truncated"])
        self.assertTrue(result["metadata"]["outside_coverage"])

    def test_rejects_large_bbox_and_unsupported_zoom(self):
        with self.assertRaises(CadastralQueryError):
            self.store.query((135.0, 34.0, 135.2, 34.2), 18)
        with self.assertRaises(CadastralQueryError):
            self.store.query((135.66, 34.35, 135.67, 34.36), 16)

    def test_missing_database_is_not_available(self):
        missing = CadastralStore(Path(self.temp_dir.name) / "missing.sqlite")
        self.assertFalse(missing.available)


if __name__ == "__main__":
    unittest.main()
