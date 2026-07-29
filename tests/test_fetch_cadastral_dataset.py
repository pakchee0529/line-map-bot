import tempfile
import unittest
from pathlib import Path

from tools.fetch_cadastral_dataset import fetch_dataset, sha256_file


class FetchCadastralDatasetTest(unittest.TestCase):
    def test_fetches_local_asset_and_verifies_hash(self):
        with tempfile.TemporaryDirectory() as temp_name:
            temp_dir = Path(temp_name)
            source = temp_dir / "source.sqlite"
            destination = temp_dir / "output" / "dataset.sqlite"
            source.write_bytes(b"verified cadastral fixture")

            fetch_dataset(source.as_uri(), sha256_file(source), destination)

            self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_hash_mismatch_does_not_publish_output(self):
        with tempfile.TemporaryDirectory() as temp_name:
            temp_dir = Path(temp_name)
            source = temp_dir / "source.sqlite"
            destination = temp_dir / "dataset.sqlite"
            source.write_bytes(b"wrong hash fixture")

            with self.assertRaises(SystemExit):
                fetch_dataset(source.as_uri(), "0" * 64, destination)

            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
