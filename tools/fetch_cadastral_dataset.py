from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and verify a prebuilt cadastral SQLite dataset."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("CADASTRAL_DATA_URL", ""),
    )
    parser.add_argument(
        "--sha256",
        default=os.getenv("CADASTRAL_DATA_SHA256", ""),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            os.getenv(
                "CADASTRAL_DATA_PATH",
                "data/cadastral/gojo_chiban.sqlite",
            )
        ),
    )
    parser.add_argument(
        "--optional",
        action="store_true",
        help="Exit successfully when URL or SHA-256 is not configured.",
    )
    return parser.parse_args()


def fetch_dataset(url: str, expected_hash: str, output_path: Path) -> None:
    normalized_hash = expected_hash.strip().lower()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cadastral-fetch-") as temp_name:
        temp_path = Path(temp_name) / "dataset.sqlite"
        print("downloading cadastral dataset")
        with urllib.request.urlopen(url, timeout=180) as response:
            with temp_path.open("wb") as output:
                shutil.copyfileobj(response, output)

        actual_hash = sha256_file(temp_path)
        if actual_hash != normalized_hash:
            raise SystemExit(
                f"SHA-256 mismatch: expected={normalized_hash} actual={actual_hash}"
            )
        temp_path.replace(output_path)

    print(f"cadastral dataset ready: {output_path.resolve()}")
    print(f"sha256: {normalized_hash}")


def main() -> None:
    args = parse_args()
    expected_hash = args.sha256.strip().lower()
    if not args.url or not expected_hash:
        if args.optional:
            print("cadastral dataset fetch skipped: URL/SHA-256 is not configured")
            return
        raise SystemExit("both --url and --sha256 are required")
    fetch_dataset(args.url, expected_hash, args.output)
