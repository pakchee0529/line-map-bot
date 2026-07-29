from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cadastral_service import CadastralStore


EXPECTED_COUNTS = {
    "parcels": 105_527,
    "parcel_labels": 106_525,
    "leader_lines": 10_735,
    "oaza_boundaries": 344,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the generated Gojo cadastral SQLite dataset."
    )
    parser.add_argument(
        "database",
        nargs="?",
        type=Path,
        default=Path("data/cadastral/gojo_chiban.sqlite"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = CadastralStore(args.database)
    if not store.available:
        raise SystemExit(f"dataset not found: {args.database}")

    uri = args.database.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SystemExit(f"integrity_check failed: {integrity}")
        for table_name, expected_count in EXPECTED_COUNTS.items():
            actual_count = connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
            if actual_count != expected_count:
                raise SystemExit(
                    f"{table_name}: expected={expected_count} actual={actual_count}"
                )
            print(f"{table_name}: {actual_count}")
    finally:
        connection.close()

    manifest = store.manifest()
    if manifest.get("source_date") != "2026-01-01":
        raise SystemExit("unexpected source_date")
    if manifest.get("license") != "CC BY 4.0":
        raise SystemExit("unexpected license")

    known_area = store.query((135.660, 34.355, 135.667, 34.361), 18)
    layer_names = {
        feature["properties"]["layer"] for feature in known_area["features"]
    }
    if not {"parcel", "label"}.issubset(layer_names):
        raise SystemExit("known-area smoke test did not return parcel and label")

    print(f"known_area_features: {len(known_area['features'])}")
    print(f"source_date: {manifest['source_date']}")
    print("verify_ok")


if __name__ == "__main__":
    main()
